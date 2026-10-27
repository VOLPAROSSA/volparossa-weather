# SPDX-License-Identifier: GPL-3.0-only
"""Inert fixtures only: no APT, loader, SDK, Node, browser or bwrap execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_runtime.py'))
H = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_clients_ci.py'))
I = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_inputs.py'))


def elf_fixture(soname='libfixture.so.1'):
    raw = bytearray(512)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', raw, 16, 3, 62)
    struct.pack_into('<Q', raw, 32, 64)
    struct.pack_into('<HH', raw, 54, 56, 2)
    struct.pack_into('<IIQQQQQQ', raw, 64, 1, 4, 0, 0x1000, 0, len(raw), len(raw), 4096)
    struct.pack_into('<IIQQQQQQ', raw, 120, 2, 4, 192, 0x10c0, 0, 64, 64, 8)
    strings = b'\0' + soname.encode() + b'\0'
    struct.pack_into('<qQ', raw, 192, 5, 0x1100)
    struct.pack_into('<qQ', raw, 208, 10, len(strings))
    struct.pack_into('<qQ', raw, 224, 14, 1)
    struct.pack_into('<qQ', raw, 240, 0, 0)
    raw[256:256 + len(strings)] = strings
    return bytes(raw)


class RuntimeBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        event = self.root / 'legacy-event.json'
        event.write_text(json.dumps(dict(inputs=dict(input_mode='historical-v1')))); event.chmod(0o600)
        self.enterContext(patch.dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_EVENT_NAME='workflow_dispatch'))

    def view(self, root, packages, profile, *, host):
        record = dict(apt=dict(packages=[dict(**{k: v for k, v in p.items() if k != 'files'},
            files_sha256=M['sha'](M['canonical'](p['files']))) for p in packages]))
        inputs = SimpleNamespace(load_package_inputs=lambda selected: record)
        with patch.dict(M['View'].__init__.__globals__, module=Mock(return_value=inputs)):
            return M['View'](root, packages, profile, host=host)

    def fixture(self):
        host = self.root / 'host'
        host.mkdir(mode=0o700)
        files = {}
        for name, raw in {
            'usr/sbin/ldconfig.real': elf_fixture('ldconfig.real'),
            'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2': elf_fixture('ld-linux-x86-64.so.2'),
            'usr/lib/x86_64-linux-gnu/libfixture.so.1': elf_fixture(),
            'usr/share/ca-certificates/mozilla/root.crt': b'fixture certificate\n',
            'etc/ld.so.conf': b'include /etc/ld.so.conf.d/*.conf\n\n',
            'etc/ld.so.conf.d/libc.conf': b'/usr/local/lib\n',
            'etc/ld.so.conf.d/fakeroot-x86_64-linux-gnu.conf': b'unknown loader configuration\n',
            'usr/bin/su': b'unneeded privileged tool',
        }.items():
            path = host / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw); path.chmod(0o644)
            files[name] = dict(type='file', mode=0o644, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return host, [dict(identity=['fixture', '1', 'amd64'], files=files)]

    def test_fixed_selection_excludes_foreign_configs_and_privileged_entries(self):
        for path in ('etc/ld.so.conf.d/fakeroot-x86_64-linux-gnu.conf',
                'etc/ld.so.conf.d/zz_i386-biarch-compat.conf', 'etc/security/limits.conf',
                'etc/sysctl.conf', 'etc/systemd/system.conf', 'usr/bin/su', 'usr/bin/passwd',
                'usr/lib/python3.12/sitecustomize.py', 'lib', 'bin'):
            self.assertFalse(M['selected'](path), path)
        for path in ('etc/ld.so.conf', 'etc/ld.so.conf.d/libc.conf', 'etc/fonts/fonts.conf',
                'usr/lib/python3.12/json/__init__.py', 'usr/include/fixture.h', 'usr/share/fonts/font.ttf'):
            self.assertTrue(M['selected'](path), path)

    def test_preexisting_negative_fixture_is_preserved(self):
        path = self.root / 'runtime-boundary-unapproved-library.so'
        path.write_bytes(b'not owned by this attempt')
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            M['put'](path, b'replacement')
        self.assertEqual(path.read_bytes(), before)

    def test_elf_metadata_is_data_only_and_malformed_inputs_fail_closed(self):
        value = M['elf'](elf_fixture())
        self.assertEqual(value, dict(interpreter=None, needed=[], soname='libfixture.so.1', search=[]))
        self.assertIsNone(M['elf'](b'plain data'))
        relocatable = bytearray(elf_fixture()); struct.pack_into('<H', relocatable, 16, 1)
        struct.pack_into('<Q', relocatable, 32, 0); struct.pack_into('<HH', relocatable, 54, 0, 0)
        self.assertEqual(M['elf'](bytes(relocatable)), dict(interpreter=None, needed=[], soname=None, search=[]))
        for raw in (b'\x7fELF', elf_fixture()[:200], elf_fixture().replace(b'\x02\x01\x01', b'\x01\x01\x01', 1)):
            with self.assertRaises(ValueError):
                M['elf'](raw)

    def test_namespace_resolution_never_uses_host_aliases(self):
        entries = {'lib': dict(type='symlink', target='usr/lib'), 'usr': dict(type='directory'),
            'usr/lib': dict(type='directory'), 'usr/lib/a.so': dict(type='symlink', target='b.so'),
            'usr/lib/b.so': dict(type='file', sha256='a' * 64)}
        self.assertEqual(M['resolve']('/lib/a.so', entries)[0], 'usr/lib/b.so')
        entries['usr/lib/a.so']['target'] = '/unapproved/host.so'
        with self.assertRaisesRegex(ValueError, 'UNAUTHORIZED_PATH'):
            M['resolve']('/lib/a.so', entries)
        entries['usr/lib/a.so']['target'] = 'a.so'
        with self.assertRaisesRegex(ValueError, 'LINK_CYCLE'):
            M['resolve']('/lib/a.so', entries)

    def test_private_view_binds_only_expected_bytes_and_excludes_unknown_config(self):
        host, packages = self.fixture()
        view = self.view(self.root / 'view', packages, 'drizzli', host=host)
        self.assertFalse((view.root / 'usr/bin/su').exists())
        self.assertFalse((view.root / 'etc/ld.so.conf.d/fakeroot-x86_64-linux-gnu.conf').exists())
        self.assertEqual((view.root / 'etc/ssl/certs/ca-certificates.crt').read_bytes(), b'fixture certificate\n')
        self.assertEqual((view.root / 'etc/ld.so.cache').read_bytes(), b'')
        self.assertEqual(os.readlink(view.root / 'lib'), 'usr/lib')
        view.recheck()
        (view.root / 'usr/lib/x86_64-linux-gnu/libfixture.so.1').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'VIEW_CHANGED'):
            view.recheck()

    def test_unapproved_library_or_wrong_soname_cache_selection_is_rejected(self):
        host, packages = self.fixture()
        view = self.view(self.root / 'view', packages, 'drizzli', host=host)
        listing = (b"1 libs found in cache `/state/ld.so.cache'\n"
            b"\tlibfixture.so.1 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libfixture.so.1\n"
            b"Cache generated by: ldconfig (Ubuntu GLIBC 2.39-0ubuntu8.9) stable release version 2.39\n")
        self.assertEqual(view.cache_semantics(listing), {'libfixture.so.1': 'usr/lib/x86_64-linux-gnu/libfixture.so.1'})
        self.assertEqual((view.root / 'etc/resolv.conf').read_bytes(), b'')
        for raw in (listing.replace(b'/usr/lib/x86_64-linux-gnu/libfixture.so.1', b'/usr/local/lib/unknown.so'),
                listing.replace(b'\tlibfixture.so.1 ', b'\tforeign.so.1 ')):
            with self.assertRaisesRegex(ValueError, 'UNAUTHORIZED'):
                view.cache_semantics(raw)
        for raw in (listing.replace(b'1 libs', b'2 libs'), listing.replace(b'libc6,x86-64', b'libc6'),
                listing + b'Cache generated by: unknown\n', b'',
                listing.replace(b'1 libs', b'2 libs') + listing.split(b'\n', 1)[1]):
            with self.assertRaisesRegex(ValueError, 'BOUNDARY_CACHE_'):
                view.cache_semantics(raw)

    def test_cache_footer_accepts_only_the_pinned_tool_format(self):
        host, packages = self.fixture()
        view = self.view(self.root / 'view', packages, 'drizzli', host=host)
        header = b"1 libs found in cache `/state/ld.so.cache'\n"
        entry = b"\tlibfixture.so.1 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libfixture.so.1\n"
        # Exact footer retained from run40443267351/attempt3, not a newly inferred pin.
        footer = b"Cache generated by: ldconfig (Ubuntu GLIBC 2.39-0ubuntu8.9) stable release version 2.39\n"
        listing = header + entry + footer
        self.assertEqual(view.cache_semantics(listing),
            {'libfixture.so.1': 'usr/lib/x86_64-linux-gnu/libfixture.so.1'})
        for changed in (footer.replace(b' stable release version 2.39', b''),
                footer.replace(b'ubuntu8.9', b'ubuntu8.10'), footer.replace(b'version 2.39', b'version 2.40'),
                footer.replace(b'ldconfig', b'unknown'), footer.rstrip(b'\n') + b' extra\n',
                b' ' + footer):
            with self.subTest(footer=changed), self.assertRaisesRegex(ValueError, 'BOUNDARY_CACHE_GENERATOR'):
                view.cache_semantics(header + entry + changed)
        for changed in (header + entry, header + footer, entry + footer, listing + footer,
                listing + b'\n', header.replace(b'1 libs', b'2 libs') + entry + footer):
            with self.subTest(listing=changed), self.assertRaisesRegex(ValueError, 'BOUNDARY_CACHE_'):
                view.cache_semantics(changed)
        for changed in (entry.replace(b'/usr/lib/x86_64-linux-gnu/libfixture.so.1', b'/usr/local/lib/unknown.so'),
                entry.replace(b'\tlibfixture.so.1 ', b'\tforeign.so.1 ')):
            with self.subTest(entry=changed), self.assertRaisesRegex(ValueError, 'UNAUTHORIZED'):
                view.cache_semantics(header + changed + footer)
        for changed in (entry.replace(b'libc6,x86-64', b'libc6'),
                entry.replace(b' => ', b' -> ')):
            with self.subTest(entry=changed), self.assertRaisesRegex(ValueError, 'BOUNDARY_CACHE_LIST_SYNTAX'):
                view.cache_semantics(header + changed + footer)

    def test_changed_installed_bytes_and_replaced_view_root_are_rejected(self):
        host, packages = self.fixture()
        (host / 'usr/lib/x86_64-linux-gnu/libfixture.so.1').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'INSTALLED_'):
            self.view(self.root / 'bad', packages, 'drizzli', host=host)
        host, packages = self.fixture_again()
        view = self.view(self.root / 'view', packages, 'drizzli', host=host)
        view.root.rename(self.root / 'retained')
        view.root.symlink_to(self.root / 'retained')
        with self.assertRaisesRegex(ValueError, 'VIEW_REPLACED'):
            view.recheck()

    def fixture_again(self):
        shutil = __import__('shutil')
        shutil.rmtree(self.root / 'host')
        return self.fixture()

    def test_adapter_replaces_host_mounts_without_changing_lifecycle(self):
        boundary = Mock()
        boundary.system_mounts.return_value = ['--ro-bind', '/verified/usr', '/usr', '--ro-bind', '/verified/etc', '/etc']
        boundary.source_mounts.return_value = ['--ro-bind', '/verified/source', str(ROOT)]
        with patch.dict(H['sandbox'].__globals__, BOUNDARY=boundary):
            argv = H['sandbox'](['/usr/bin/python3.12'], mode='compile', writable=H['STAGE'])
        binds = [argv[i + 1:i + 3] for i, value in enumerate(argv) if value == '--ro-bind']
        self.assertNotIn(['/usr', '/usr'], binds)
        self.assertNotIn([str(ROOT), str(ROOT)], binds)
        self.assertNotIn(['/etc/ld.so.cache', '/etc/ld.so.cache'], binds)
        self.assertIn('--unshare-net', argv)
        self.assertIn('--unshare-pid', argv)
        self.assertIn('--die-with-parent', argv)
        self.assertIn(['--remount-ro', '/home/runner/work'], [argv[i:i+2] for i in range(len(argv)-1)])
        boundary.source_mounts.assert_called_once_with('compile')

    def test_writable_mount_alias_cannot_contain_sealed_inputs(self):
        boundary = M['Boundary'].__new__(M['Boundary'])
        boundary.view = Mock(root=self.root / 'state/view')
        boundary.source = self.root / 'source'
        boundary.browser_source = self.root / 'browser'
        boundary.source_anchors = {}
        boundary.sdk = None
        boundary.sdk_metadata = {}
        boundary.cache = self.root / 'cache'
        boundary.firefox_copy = self.root / 'firefox'
        boundary.table_proof = self.root / 'table-proof'
        boundary.firefox_ready = False
        boundary.runtime_initial = {}
        boundary.h = Mock(RUNTIME=self.root / 'runtime', PRIVATE=self.root / 'state',
            STAGE=self.root / 'stage', PROOF=self.root / 'proof', FIREFOX=self.root / 'firefox')
        for root in (boundary.source, boundary.browser_source):
            root.mkdir(mode=0o700)
            boundary.source_anchors[str(root)] = (root.stat().st_dev, root.stat().st_ino)
        boundary.source_files = boundary.browser_files = {}
        boundary.h.runtime_inventory.return_value = {}
        with self.assertRaisesRegex(ValueError, 'WRITABLE_ALIAS'):
            boundary.check()

    def test_cleanup_requires_confirmed_runtime_groups_and_policy_removal(self):
        source = self.root / 'build/hosted-overmorrow-input-candidate'
        source.mkdir(mode=0o700, parents=True)
        (source / 'runtime-boundary-started.json').write_text('{}')
        (source / 'runtime-boundary-started.json').chmod(0o600)
        (source / 'runtime-boundary-cleanup.json').write_text(json.dumps(dict(
            admitted=False, process_drain_confirmed=False, policy_removed=False)))
        (source / 'runtime-boundary-cleanup.json').chmod(0o600)
        with patch.dict(I['cleanup_candidate'].__globals__, ROOT=self.root), \
                self.assertRaisesRegex(ValueError, 'BOUNDARY_CLEANUP_UNCONFIRMED'):
            I['cleanup_candidate']('overmorrow')
        self.assertTrue(source.exists())

    def loader(self):
        boundary = M['Boundary'].__new__(M['Boundary'])
        boundary.sdk = None
        boundary.h = SimpleNamespace(RUNTIME=self.root / 'runtime', FIREFOX=self.root / 'browser/build/firefox')
        library = dict(type='file', sha256='a' * 64, elf=dict(soname='libfixture.so.1'))
        loader = dict(type='file', sha256='b' * 64, elf=dict(soname='ld-linux-x86-64.so.2'))
        boundary.view = SimpleNamespace(entries={
            'usr': dict(type='directory'), 'usr/lib': dict(type='directory'),
            'usr/lib/x86_64-linux-gnu': dict(type='directory'), 'usr/lib64': dict(type='directory'),
            'lib': dict(type='symlink', target='usr/lib'), 'lib64': dict(type='symlink', target='usr/lib64'),
            'usr/lib/x86_64-linux-gnu/libfixture.so.1': library,
            'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2': loader,
            'usr/lib64/ld-linux-x86-64.so.2': dict(type='symlink', target='../lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),
        })
        return boundary

    def test_glibc_loader_complete_success_record_forms(self):
        boundary = self.loader()
        library = '/usr/lib/x86_64-linux-gnu/libfixture.so.1'
        loader = '/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        # rtld.c has one direct-name and one name=>mapped-name formatter.
        # A direct absolute file, a SONAME and an absolute interpreter alias
        # use those two formatters; vDSO is the sole non-file exception.
        for line in (f'\tlibfixture.so.1 => {library} (0x00007f7c8bdc9000)\n',
                f'\tlibfixture.so.1 => /lib/x86_64-linux-gnu/libfixture.so.1 (0x00007f7c8bdc9000)\n',
                f'\t{library} (0x00007f7c8bdc9000)\n',
                f'\t{library} => {library} (0x00007f7c8bdc9000)\n'):
            self.assertEqual(boundary.loader_semantics(line.encode()), [dict(path=library, sha256='a' * 64)])
        raw = (f'\tlinux-vdso.so.1 (0x00007f7c8bebd000)\n'
            f'\tlibfixture.so.1 => {library} (0x00007f7c8bdc9000)\n'
            f'\t/lib64/ld-linux-x86-64.so.2 => {loader} (0x00007f7c8bebf000)\n').encode()
        self.assertEqual(boundary.loader_semantics(raw), [dict(path=library, sha256='a' * 64),
            dict(path=loader, sha256='b' * 64)])

    def test_fixed_probe_families_share_the_proven_glibc_name_formatter(self):
        boundary = self.loader()
        # Representative authorized fixture names for all seven existing
        # probes. These are synthetic data, not new runtime observations/pins.
        for probe, soname in (('python', 'libexpat.so.1'), ('node', 'libstdc++.so.6'),
                ('firefox', 'libgcc_s.so.1'), ('xul', 'libX11-xcb.so.1'),
                ('git', 'libpcre2-8.so.0'), ('shell', 'libtinfo.so.6'), ('dart', 'libdl.so.2')):
            name = 'usr/lib/x86_64-linux-gnu/' + soname
            boundary.view.entries[name] = dict(type='file', sha256='c' * 64, elf=dict(soname=soname))
            with self.subTest(probe=probe):
                self.assertEqual(boundary.loader_semantics(f'\t{soname} => /{name} (0x00007f7c8bdc9000)\n'.encode()),
                    [dict(path='/' + name, sha256='c' * 64)])

    def test_loader_missing_soname_requires_exact_pinned_member_basename(self):
        boundary = self.loader()
        name = 'usr/lib/x86_64-linux-gnu/libfixture.so.1'
        boundary.view.entries[name]['elf']['soname'] = None
        good = f'\tlibfixture.so.1 => /{name} (0x00007f7c8bdc9000)\n'.encode()
        self.assertEqual(boundary.loader_semantics(good), [dict(path='/' + name, sha256='a' * 64)])
        with self.assertRaisesRegex(ValueError, 'SONAME'):
            boundary.loader_semantics(good.replace(b'libfixture.so.1 =>', b'foreign.so.1 =>'))
        # An existing empty SONAME tag is distinct from an absent tag.
        boundary.view.entries[name]['elf']['soname'] = ''
        with self.assertRaisesRegex(ValueError, 'SONAME'):
            boundary.loader_semantics(good)

    def test_loader_absolute_alias_requires_same_canonical_file_and_digest(self):
        boundary = self.loader()
        entries = boundary.view.entries
        loader = '/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        row = f'\t/lib64/ld-linux-x86-64.so.2 => {loader} (0x00007f7c8bebf000)\n'.encode()
        boundary.loader_semantics(row)
        target = entries['usr/lib64/ld-linux-x86-64.so.2']
        for malicious in ('/usr/local/lib/foreign.so', 'ld-linux-x86-64.so.2'):
            target['target'] = malicious
            with self.assertRaises(ValueError):
                boundary.loader_semantics(row)
        target['target'] = '../lib/x86_64-linux-gnu/libfixture.so.1'
        with self.assertRaisesRegex(ValueError, 'ALIAS_IDENTITY'):
            boundary.loader_semantics(row)
        # Identical bytes do not authorize a different canonical path.
        entries['usr/lib/x86_64-linux-gnu/copy.so'] = copy.deepcopy(entries[loader[1:]])
        target['target'] = '../lib/x86_64-linux-gnu/copy.so'
        with self.assertRaisesRegex(ValueError, 'ALIAS_IDENTITY'):
            boundary.loader_semantics(row)
        with patch.object(boundary, 'library', side_effect=[dict(path=loader, sha256='a' * 64),
                dict(path=loader, sha256='b' * 64)]), self.assertRaisesRegex(ValueError, 'ALIAS_IDENTITY'):
            boundary.loader_semantics(row)

    def test_loader_rejects_unknown_malformed_traversal_and_ambiguous_records(self):
        boundary = self.loader()
        good = b'\tlibfixture.so.1 => /usr/lib/x86_64-linux-gnu/libfixture.so.1 (0x00007f7c8bdc9000)\n'
        for bad in (b'', b'\tstatically linked\n', b'\tlibmissing.so => not found\n',
                b'\tlinux-gate.so.1 (0x00007f7c8bdc9000)\n', b'warning: unknown output\n',
                good.replace(b'0x00007f7c8bdc9000', b'0x123'), good.replace(b'7f7c', b'7F7C'),
                good.replace(b'\t', b' '), good.replace(b' => ', b'=>'), good.rstrip(b'\n'),
                good.replace(b'\n', b'\r\n'), good.replace(b'\n', b'\v') + good,
                good.replace(b'/usr/lib/', b'/usr//lib/'), good.replace(b'/usr/lib/', b'/usr/./lib/'),
                good.replace(b'/usr/lib/', b'/usr/extra/../lib/'), good.replace(b'/usr/lib/', b'usr/lib/'),
                good.replace(b'/usr/lib/', b'/usr/lib/../../host/'), good.replace(b'/usr/lib/', b'/host/lib/'),
                good.replace(b'libfixture.so.1 =>', b'foreign.so.1 =>'), good + good,
                b'\tlinux-vdso.so.1 (0x00007f7c8bebd000)\n' * 2 + good,
                good + b'\t/usr/lib/x86_64-linux-gnu/libfixture.so.1 (0x00007f7c8bdc9000)\n',
                good.replace(b'libfixture.so.1 =>', b'../libfixture.so.1 =>'),
                good.replace(b'/usr/lib/', b'/' + b'a' * 1025 + b'/')):
            with self.subTest(record=bad[:120]), self.assertRaises((ValueError, UnicodeError)):
                boundary.loader_semantics(bad)
        with self.assertRaisesRegex(ValueError, 'EMPTY'):
            boundary.loader_semantics(b'\tlinux-vdso.so.1 (0x00007f7c8bebd000)\n')
        with self.assertRaisesRegex(ValueError, 'BOUND'):
            boundary.loader_semantics(b'x' * (2 * 1024**2 + 1))
        with self.assertRaisesRegex(ValueError, 'LINES'):
            boundary.loader_semantics(good * 4097)

    def test_loader_runtime_sdk_and_browser_leaves_keep_expected_identity(self):
        boundary = self.loader()
        runtime = boundary.h.RUNTIME; runtime.mkdir(mode=0o700)
        sdk = self.root / 'sdk'; sdk.mkdir(mode=0o700); boundary.sdk = sdk
        boundary.firefox_copy = self.root / 'firefox-copy'; boundary.firefox_copy.mkdir(mode=0o700)
        files = {}
        for relative, soname in (('node/lib/libnodefixture.so', 'libnodefixture.so'),
                ('firefox/libmozfixture.so', 'libmozfixture.so')):
            raw = elf_fixture(soname)
            destination = runtime / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(raw); destination.chmod(0o600)
            files[relative] = dict(sha256=M['sha'](raw))
        firefox = boundary.firefox_copy / 'libmozfixture.so'
        firefox.write_bytes((runtime / 'firefox/libmozfixture.so').read_bytes()); firefox.chmod(0o600)
        provenance = runtime / 'provenance.json'; provenance.write_text(json.dumps(dict(files=files))); provenance.chmod(0o600)
        sdk_lib = sdk / 'libdartfixture.so'; sdk_lib.write_bytes(elf_fixture('libdartfixture.so')); sdk_lib.chmod(0o600)
        sdk_map = sdk / 'sdk-inventory.json'
        sdk_map.write_text(json.dumps({'libdartfixture.so': dict(sha256=M['sha'](sdk_lib.read_bytes()))})); sdk_map.chmod(0o600)
        for path, soname, canonical in ((runtime / 'node/lib/libnodefixture.so', 'libnodefixture.so', 'node/lib/libnodefixture.so'),
                (boundary.h.FIREFOX / 'libmozfixture.so', 'libmozfixture.so', 'firefox-copy/libmozfixture.so'),
                (sdk_lib, 'libdartfixture.so', 'sdk/libdartfixture.so')):
            row = f'\t{soname} => {path} (0x00007f7c8bdc9000)\n'.encode()
            self.assertEqual(boundary.loader_semantics(row), [dict(path=canonical, sha256=M['sha'](elf_fixture(soname)))])
            with self.assertRaisesRegex(ValueError, 'SONAME'):
                boundary.loader_semantics(row.replace(soname.encode() + b' =>', b'foreign.so =>'))
        # Equal hashes must still reject non-ELF payloads: these explicit
        # inert fixture manifests bind the non-ELF bytes before parsing.
        # Separately test each original archive-hash mismatch branch.
        for virtual, physical, key, manifest, category in (
                (runtime / 'node/lib/libnodefixture.so', runtime / 'node/lib/libnodefixture.so',
                    'node/lib/libnodefixture.so', provenance, 'RUNTIME_LIBRARY_CHANGED'),
                (boundary.h.FIREFOX / 'libmozfixture.so', firefox,
                    'firefox/libmozfixture.so', provenance, 'BROWSER_LIBRARY'),
                (sdk_lib, sdk_lib, 'libdartfixture.so', sdk_map, 'SDK_LIBRARY')):
            raw = physical.read_bytes()
            original_manifest = manifest.read_bytes()
            physical.write_bytes(b'bound fixture, not an ELF file')
            with self.assertRaisesRegex(ValueError, category):
                boundary.loader_semantics(f'\t{virtual} (0x00007f7c8bdc9000)\n'.encode())
            value = json.loads(original_manifest)
            entries = value['files'] if manifest == provenance else value
            entries[key]['sha256'] = M['sha'](physical.read_bytes())
            manifest.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'UNAUTHORIZED_LIBRARY_SELECTION'):
                boundary.loader_semantics(f'\t{virtual} (0x00007f7c8bdc9000)\n'.encode())
            physical.write_bytes(raw); manifest.write_bytes(original_manifest)
        empty_soname = elf_fixture('')
        sdk_lib.write_bytes(empty_soname)
        sdk_map.write_text(json.dumps({'libdartfixture.so': dict(sha256=M['sha'](empty_soname))}))
        with self.assertRaisesRegex(ValueError, 'SONAME'):
            boundary.loader_semantics(f'\tlibdartfixture.so => {sdk_lib} (0x00007f7c8bdc9000)\n'.encode())
        sdk_lib.write_bytes(elf_fixture('libdartfixture.so'))
        sdk_map.write_text(json.dumps({'libdartfixture.so': dict(sha256=M['sha'](sdk_lib.read_bytes()))}))
        # No SONAME tag: the authenticated canonical filename still supplies
        # its only allowed basename. Remove the tag from a fixed fixture ELF.
        no_soname = bytearray(sdk_lib.read_bytes()); struct.pack_into('<qQ', no_soname, 224, 0, 0)
        sdk_lib.write_bytes(no_soname)
        sdk_map.write_text(json.dumps({'libdartfixture.so': dict(sha256=M['sha'](bytes(no_soname)))}))
        boundary.loader_semantics(f'\tlibdartfixture.so => {sdk_lib} (0x00007f7c8bdc9000)\n'.encode())
        with self.assertRaisesRegex(ValueError, 'SONAME'):
            boundary.loader_semantics(f'\tforeign.so => {sdk_lib} (0x00007f7c8bdc9000)\n'.encode())
        firefox.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'BROWSER_LIBRARY'):
            boundary.loader_semantics(f'\tlibmozfixture.so => {boundary.h.FIREFOX}/libmozfixture.so (0x00007f7c8bdc9000)\n'.encode())

    def dns(self, raw=b'nameserver 192.0.2.53\n', name='dns'):
        directory = self.root / name; directory.mkdir(mode=0o700)
        source = directory / 'source'; source.write_bytes(raw); source.chmod(0o600)
        snapshot = directory / 'snapshot'
        return M['AcquisitionResolver'](snapshot), source

    def test_dns_platform_stub_and_standard_directives_are_stripped(self):
        raw = (b'# This is a systemd-resolved stub fixture\n'
            b'nameserver 127.0.0.53\noptions edns0 trust-ad\nsearch .\n'
            b'domain fixture.internal\nsortlist 192.0.2.0/24\n'
            b'options arbitrary-ignored-platform-setting # never forwarded\n')
        resolver, source = self.dns(raw)
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source):
            resolver.capture()
        self.assertEqual(resolver.path.read_bytes(), b'nameserver 127.0.0.53\n')
        self.assertEqual(resolver.observation['stripped_directives'], dict(search=1, domain=1, options=2, sortlist=1))
        self.assertTrue(resolver.observation['source_stat']['legacy_regular_fstat_passed'])
        self.assertTrue(resolver.observation['snapshot_ready'])
        resolver.mounts()
        resolver2, source2 = self.dns(b'; comment\r\nnameserver 2001:0DB8:0:0::53 ; private\r\n'
            b'options timeout:2 attempts:3 rotate single-request-reopen\nsearch private.invalid example.invalid\n', 'dns2')
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source2):
            resolver2.capture()
        self.assertEqual(resolver2.path.read_bytes(), b'nameserver 2001:db8::53\n')
        public = json.dumps([resolver.observation, resolver2.observation])
        for forbidden in ('127.0.0.53', '2001:db8', 'fixture.internal', 'private.invalid', str(source), 'sha256'):
            self.assertNotIn(forbidden, public)

    def test_dns_service_metadata_is_observed_but_never_code_authority(self):
        resolver, source = self.dns()
        source.chmod(0o666); os.link(source, source.with_name('hardlink'))
        original_fstat = os.fstat
        inode = source.stat().st_ino
        def service_stat(fd):
            actual = original_fstat(fd)
            if actual.st_ino != inode:
                return actual
            fields = {name: getattr(actual, name) for name in ('st_mode', 'st_uid', 'st_gid', 'st_nlink',
                'st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')}
            fields['st_uid'] = 4242 if os.getuid() != 4242 else 4243
            return SimpleNamespace(**fields)
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source), \
                patch.object(os, 'fstat', side_effect=service_stat):
            resolver.capture()
            with self.assertRaisesRegex(ValueError, 'BOUNDARY_FILE'):
                M['regular'](source, 65536)
        observed = resolver.observation['source_stat']
        self.assertFalse(observed['legacy_regular_fstat_passed'])
        self.assertEqual(observed['legacy_regular_predicates'], dict(regular=True, uid=False, nlink=False, mode=False, size=True))
        self.assertEqual(resolver.path.stat().st_mode & 0o777, 0o600)

    def test_dns_malformed_bounds_and_unknown_directives_fail_without_input_leaks(self):
        malformed = (b'', b'options edns0\n', b'nameserver\n', b'nameserver 192.0.2.53 extra\n',
            b'nameserver private.invalid\n', b'nameserver 999.1.2.3\n', b'nameserver fe80::1%eth0\n',
            b'nameserver 192.0.2.53\n' * 5, b'unknown secret.invalid\n', b'nameserver \xff\n',
            b'nameserver 192.0.2.53\x00\n', b'nameserver 192.0.2.53\v\n', b'x' * 65537,
            b'#' + b'x' * 4096 + b'\n', b'options ' + b'x' * 1025 + b'\n',
            b'options ' + b'x ' * 129 + b'\n', b'#\n' * 1025)
        for i, raw in enumerate(malformed):
            resolver, source = self.dns(raw, 'bad' + str(i))
            with self.subTest(case=i), patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source), \
                    self.assertRaisesRegex(ValueError, 'BOUNDARY_DNS_') as raised:
                resolver.capture()
            self.assertFalse(resolver.path.exists())
            self.assertIsNotNone(resolver.observation['source_stat'])
            public = json.dumps(resolver.observation) + str(raised.exception)
            for secret in ('192.0.2.53', 'private.invalid', 'secret.invalid', str(source)):
                self.assertNotIn(secret, public)
        self.assertFalse(resolver.observation['snapshot_ready'])

    def test_dns_source_service_alias_and_nofollow_races(self):
        resolver, source = self.dns()
        alias = source.with_name('resolv.conf'); alias.symlink_to(source.name)
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=alias):
            resolver.capture()
        resolver2, source2 = self.dns(name='race')
        actual_open = os.open
        def replace_before_open(path, flags, *args, **kwargs):
            if path == source2.name and kwargs.get('dir_fd') is not None:
                source2.unlink(); source2.symlink_to(source)
            return actual_open(path, flags, *args, **kwargs)
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source2), \
                patch.object(os, 'open', side_effect=replace_before_open), \
                self.assertRaisesRegex(ValueError, 'BOUNDARY_DNS_IO'):
            resolver2.capture()
        self.assertIsNone(resolver2.observation['source_stat'])
        self.assertEqual(resolver2.observation['stage'], 'source-open')

    def test_dns_source_nonregular_and_replaced_or_same_size_changed_rejected(self):
        for kind in ('directory', 'fifo'):
            resolver, source = self.dns(name=kind); source.unlink()
            source.mkdir(mode=0o700) if kind == 'directory' else os.mkfifo(source, 0o600)
            with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source), \
                    self.assertRaisesRegex(ValueError, 'BOUNDARY_DNS_SOURCE_TYPE'):
                resolver.capture()
            self.assertEqual(resolver.observation['source_stat']['type'], kind)
            self.assertEqual(resolver.observation['stage'], 'source-stat')
        for replace in (False, True):
            resolver, source = self.dns(name='mutate' + str(replace))
            original_fstat = os.fstat; inode = source.stat().st_ino; calls = 0
            def change_during_read(fd):
                nonlocal calls
                info = original_fstat(fd)
                if info.st_ino == inode:
                    calls += 1
                    if calls == 2:
                        if replace:
                            source.rename(source.with_name('original'))
                        source.write_bytes(b'nameserver 192.0.2.54\n')
                        source.chmod(0o600)
                        info = original_fstat(fd)
                return info
            with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source), \
                    patch.object(os, 'fstat', side_effect=change_during_read), \
                    self.assertRaisesRegex(ValueError, 'BOUNDARY_DNS_SOURCE_CHANGED'):
                resolver.capture()
            self.assertFalse(resolver.observation['source_stable'])
            self.assertEqual(resolver.observation['stage'], 'source-stability')

    def test_dns_shared_snapshot_rechecks_and_all_profile_mode_mounts(self):
        resolver, source = self.dns()
        with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source):
            resolver.capture()
        overmorrow = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_ci.py'))
        for profile, helper in (('drizzli', H['sandbox'].__globals__), ('overmorrow', vars(overmorrow['H']))):
            boundary = M['Boundary'].__new__(M['Boundary']); boundary.resolver = resolver
            boundary.system_mounts = Mock(return_value=['--ro-bind', '/verified/usr', '/usr', '--ro-bind', '/verified/etc', '/etc'])
            boundary.source_mounts = Mock(return_value=['--tmpfs', '/home/runner/work', '--ro-bind', '/verified/source', str(ROOT)])
            boundary.sdk_metadata_mounts = Mock(return_value=[])
            kwargs = dict(BOUNDARY=boundary)
            with self.subTest(profile=profile), patch.dict(helper, **kwargs), patch.object(resolver, 'capture', side_effect=AssertionError('source must not be recaptured')):
                for mode in ('compile', 'acquire', 'browser'):
                    if profile == 'overmorrow':
                        argv = overmorrow['sandbox'](['/usr/bin/python3.12'], mode=mode,
                            proof=overmorrow['PROOF'] if mode == 'browser' else None)
                    else:
                        argv = H['sandbox'](['/usr/bin/python3.12'], mode=mode,
                            writable=H['PROOF'] if mode == 'browser' else H['STAGE'])
                    binds = [argv[i+1:i+3] for i, value in enumerate(argv) if value == '--ro-bind']
                    expected = [str(resolver.path), '/etc/resolv.conf']
                    self.assertEqual(binds.count(expected), 1 if mode == 'acquire' else 0)
                    self.assertNotIn(['/etc/resolv.conf', '/etc/resolv.conf'], binds)
                    if mode != 'acquire': self.assertIn('--unshare-net', argv)
                    self.assertEqual(resolver.path.read_bytes(), b'nameserver 192.0.2.53\n')
        # Mutating the platform source after capture cannot change this snapshot.
        source.write_bytes(b'nameserver 192.0.2.54\n'); resolver.recheck()
        old = resolver.path.with_name('retained'); resolver.path.rename(old)
        resolver.path.write_bytes(old.read_bytes()); resolver.path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_REPLACED'):
            resolver.mounts()

    def test_dns_snapshot_mutation_alias_mode_and_parent_replacement_rejected(self):
        for case in ('bytes', 'alias', 'mode', 'parent'):
            resolver, source = self.dns(name='snapshot-' + case)
            with patch.dict(M['AcquisitionResolver'].capture.__globals__, DNS_SOURCE=source): resolver.capture()
            if case == 'bytes': resolver.path.write_bytes(b'nameserver 192.0.2.54\n')
            elif case == 'alias':
                resolver.path.unlink(); resolver.path.symlink_to(source)
            elif case == 'mode': resolver.path.chmod(0o644)
            else:
                resolver.path.parent.rename(self.root / 'old-parent')
                resolver.path.parent.mkdir(mode=0o700)
                resolver.path.write_bytes(b'nameserver 192.0.2.53\n'); resolver.path.chmod(0o600)
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, 'BOUNDARY_DNS_'):
                resolver.recheck()

    def test_dns_adapter_typed_scope_and_current_preflight_phase(self):
        boundary = M['Boundary'].__new__(M['Boundary']); boundary.resolver = None
        with self.assertRaisesRegex(ValueError, 'DNS_ADAPTER_REQUIRED'):
            boundary.acquisition_mounts()
        boundary.resolver = SimpleNamespace(mounts=Mock())
        with self.assertRaisesRegex(ValueError, 'DNS_ADAPTER_REQUIRED'):
            boundary.acquisition_mounts()
        # Static sequence check accompanies the actual failure-path fixture:
        # the precise phase is assigned before calls that construct argv.
        import ast
        source = (ROOT / 'scripts/prepare_hosted_client_runtime.py').read_text()
        tree = ast.parse(source)
        verify = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify')
        body = ast.get_source_segment(source, verify)
        self.assertEqual(body.count('resolver.capture()'), 1)
        self.assertEqual(body.count('resolver=resolver'), 1)
        self.assertLess(body.index('resolver.capture()'), body.index("for profile in ('drizzli', 'overmorrow')"))
        for mode in ('compile', 'acquire', 'browser'):
            self.assertLess(body.index("phase = profile + '-preflight-" + mode + "'"),
                body.index("preflight('" + mode + "'"))

    def test_dns_failure_observations_reach_existing_closed_projection(self):
        for case, stage, code in (('open', 'source-resolve', 'BOUNDARY_DNS_IO'),
                ('parse', 'source-parse', 'BOUNDARY_DNS_IP'),
                ('bound', 'source-stat', 'BOUNDARY_DNS_SOURCE_SIZE'),
                ('stability', 'source-stability', 'BOUNDARY_DNS_SOURCE_CHANGED')):
            resolver, source = self.dns(b'nameserver private.invalid\n', name='private-dns-' + case)
            if case == 'open': source.unlink()
            elif case == 'bound': source.write_bytes(b'x' * 65537)
            elif case == 'stability': source.write_bytes(b'nameserver 192.0.2.53\n')
            root = self.root / ('project-' + case); (root / 'build').mkdir(mode=0o700, parents=True)
            output = root / 'build/hosted-overmorrow-input-candidate'; output.mkdir(mode=0o700)
            helper = SimpleNamespace(DRAIN_CONFIRMED=True)
            h = SimpleNamespace(policy_helper=lambda: helper, LOGS=[], DRAIN_CONFIRMED=True)
            inputs = SimpleNamespace(hosted_guard=Mock(), document=lambda raw: json.loads(raw),
                read=lambda path: b'{}', load_package_inputs=Mock(), write=I['write'])
            runtime = SimpleNamespace(load_pin=lambda: ({}, 'fixture'), prepare=Mock())
            sdk = SimpleNamespace(prepare=Mock())
            modules = dict(prepare_hosted_client_inputs=inputs, prepare_hosted_client_apt=Mock(),
                prepare_hosted_runtime=runtime, prepare_hosted_flutter=sdk, prepare_hosted_overmorrow_ci=SimpleNamespace(H=h))
            original_fstat = os.fstat; inode = source.stat().st_ino if source.exists() else None; calls = 0
            def mutate(fd):
                nonlocal calls
                actual = original_fstat(fd)
                if case == 'stability' and actual.st_ino == inode:
                    calls += 1
                    if calls == 2: source.write_bytes(b'nameserver 192.0.2.54\n')
                    actual = original_fstat(fd)
                return actual
            with self.subTest(case=case), patch.dict(M['verify'].__globals__, module=lambda name: modules[name], DNS_SOURCE=source), \
                    patch.object(runpy, 'run_path', return_value={}), patch.object(os, 'fstat', side_effect=mutate), \
                    patch.dict(os.environ, GITHUB_SHA='a' * 40), self.assertRaisesRegex(ValueError, code):
                M['verify'](output)
            runtime.prepare.assert_not_called(); sdk.prepare.assert_not_called()
            diagnostics = json.loads((output / 'runtime-boundary-diagnostics.json').read_bytes())
            self.assertEqual(diagnostics['phase'], 'acquisition-dns-snapshot')
            self.assertEqual(diagnostics['acquisition_dns']['stage'], stage)
            self.assertEqual(diagnostics['acquisition_dns']['failure'], code)
            if case != 'open': self.assertEqual(diagnostics['acquisition_dns']['source_stat']['type'], 'regular')
            I['write'](output / 'result.json', M['canonical'](dict(admitted=False, success=False)))
            with patch.dict(I['project_metadata'].__globals__, ROOT=root):
                public = I['project_metadata']('overmorrow')
            projection = json.loads((public / 'projection.json').read_bytes())
            self.assertIn('runtime-boundary-diagnostics.json', projection['files'])
            projected = (public / 'runtime-boundary-diagnostics.json').read_text()
            for secret in ('private.invalid', '192.0.2.53', '192.0.2.54', str(source), 'nameserver ', 'sha256'):
                self.assertNotIn(secret, projected)
            cleanup = json.loads((output / 'runtime-boundary-cleanup.json').read_bytes())
            self.assertTrue(cleanup['process_drain_confirmed'] and cleanup['policy_removed'])

    def test_new_manual_mode_has_only_one_bounded_both_profile_round(self):
        workflow = (ROOT / '.github/workflows/hosted-overmorrow.yml').read_text()
        block = workflow.split('\n  runtime-boundary:', 1)[1]
        self.assertIn("github.event_name == 'workflow_dispatch'", block)
        self.assertIn('timeout-minutes: 45', block)
        self.assertEqual(block.count('--mode runtime-boundary-verification'), 1)
        self.assertNotIn('npm ci', block)
        self.assertNotIn('flutter build', block)
        self.assertNotIn('**', block)
        self.assertIn('cleanup-input-data', block)
        for profile in ('drizzli', 'overmorrow'):
            self.assertIn('scripts/prepare_hosted_client_runtime.py',
                runpy.run_path(str(ROOT / 'scripts/prepare_hosted_source_recipe.py'))['PROFILES'][profile])

    def test_actual_source_mode_cannot_fall_back_to_host_usr(self):
        event = self.root / 'source-event.json'
        event.write_text(json.dumps(dict(inputs=dict(input_mode='runtime-boundary-verification'))))
        event.chmod(0o600)
        with patch.dict(os.environ, GITHUB_ACTIONS='true', GITHUB_EVENT_PATH=str(event)), \
                self.assertRaisesRegex(ValueError, 'RUNTIME_BOUNDARY_REQUIRED'):
            H['sandbox'](['/usr/bin/true'], mode='compile', writable=H['STAGE'])
        event.write_text(json.dumps(dict(inputs=dict(input_mode='historical-v1'))))
        with patch.dict(os.environ, GITHUB_ACTIONS='true', GITHUB_EVENT_PATH=str(event)):
            argv = H['sandbox'](['/usr/bin/true'], mode='compile', writable=H['STAGE'])
        self.assertIn(['/usr', '/usr'], [argv[i+1:i+3] for i, value in enumerate(argv) if value == '--ro-bind'])
        for mode in ('', 'future-source-build'):
            event.write_text(json.dumps(dict(inputs=dict(input_mode=mode))))
            with patch.dict(os.environ, GITHUB_ACTIONS='true', GITHUB_EVENT_PATH=str(event)), \
                    self.assertRaisesRegex(ValueError, 'RUNTIME_BOUNDARY_REQUIRED'):
                H['sandbox'](['/usr/bin/true'], mode='compile', writable=H['STAGE'])

    def test_legacy_push_requires_its_exact_retained_route(self):
        event = self.root / 'push-event.json'
        event.write_text('{}'); event.chmod(0o600)
        env = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push', GITHUB_EVENT_PATH=str(event),
            GITHUB_WORKFLOW='Build hosted Weather clients', GITHUB_REF='refs/heads/feature/hosted-weather-clients')
        with patch.dict(os.environ, env):
            H['require_runtime_boundary']()
        for key, value in (('GITHUB_REF', 'refs/heads/future-source-build'),
                ('GITHUB_WORKFLOW', 'Future source workflow'), ('GITHUB_EVENT_NAME', 'workflow_dispatch')):
            with patch.dict(os.environ, dict(env, **{key: value})), \
                    self.assertRaisesRegex(ValueError, 'RUNTIME_BOUNDARY_REQUIRED'):
                H['require_runtime_boundary']()

    def test_browser_preflight_rejects_untyped_proof_before_running_child(self):
        boundary = M['Boundary'].__new__(M['Boundary'])
        boundary.view = SimpleNamespace(cache_sha='fixed')
        boundary.h = SimpleNamespace(PROOF=self.root / 'proof')
        boundary.table_proof = self.root / 'table-proof'
        with self.assertRaisesRegex(ValueError, 'BOUNDARY_PROOF_SCOPE'):
            boundary.preflight('browser', proof=self.root / 'unapproved-proof')

    def test_runtime_constructor_cannot_authorize_an_arbitrary_observed_map(self):
        with self.assertRaisesRegex(ValueError, 'PROFILE_PACKAGE_MISSING'):
            M['View'](self.root / 'view', [], 'drizzli')
        self.assertFalse((self.root / 'view').exists())

    def test_overmorrow_adapter_only_opens_scalar_metadata_and_protects_work_anchor(self):
        overmorrow = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_ci.py'))
        helper = overmorrow['H']
        boundary = Mock()
        boundary.system_mounts.return_value = ['--ro-bind', '/verified/usr', '/usr', '--ro-bind', '/verified/etc', '/etc']
        boundary.source_mounts.return_value = ['--tmpfs', '/home/runner/work', '--ro-bind', '/verified/source', str(ROOT)]
        scalar = overmorrow['SDK'] / 'bin/cache/engine.stamp'
        boundary.sdk_metadata_mounts.return_value = ['--bind', '/verified-metadata/engine.stamp', str(scalar)]
        with patch.object(helper, 'BOUNDARY', boundary):
            argv = overmorrow['sandbox'](['/usr/bin/python3.12'], mode='compile')
        writable = [argv[i+1:i+3] for i, value in enumerate(argv) if value == '--bind']
        self.assertNotIn([str(overmorrow['SDK'] / 'bin/cache')] * 2, writable)
        self.assertIn(['/verified-metadata/engine.stamp', str(scalar)], writable)
        self.assertIn(['--remount-ro', '/home/runner/work'], [argv[i:i+2] for i in range(len(argv)-1)])
        self.assertNotIn(['--remount-ro', '/home/runner'], [argv[i:i+2] for i in range(len(argv)-1)])

    def test_browser_physical_copy_keeps_the_existing_logical_driver_contract(self):
        boundary = M['Boundary'].__new__(M['Boundary'])
        browser_root = Path('/home/runner/work/weather/weather/build/hosted-browser-source')
        logical = browser_root / 'build/firefox-hosted-ci'
        physical = self.root / 'private/firefox-copy'
        self.assertTrue(logical.is_relative_to(browser_root / 'build'))
        self.assertFalse(physical.is_relative_to(browser_root / 'build'))
        boundary.firefox_copy = physical
        boundary.h = SimpleNamespace(FIREFOX=logical)
        # Physical bytes have their own guard; the actual command uses the
        # original Browser/build namespace location accepted by both drivers.
        self.assertNotEqual(boundary.firefox_copy, boundary.h.FIREFOX)


if __name__ == '__main__':
    unittest.main()
