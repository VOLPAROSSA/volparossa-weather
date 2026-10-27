# SPDX-License-Identifier: GPL-3.0-only
"""Inert fixtures only: no APT, loader, SDK, Node, browser or bwrap execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
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
        listing = b"1 libs found in cache `/state/ld.so.cache'\n\tlibfixture.so.1 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libfixture.so.1\n"
        self.assertEqual(view.cache_semantics(listing), {'libfixture.so.1': 'usr/lib/x86_64-linux-gnu/libfixture.so.1'})
        for raw in (listing.replace(b'/usr/lib/x86_64-linux-gnu/libfixture.so.1', b'/usr/local/lib/unknown.so'),
                listing.replace(b'\tlibfixture.so.1 ', b'\tforeign.so.1 ')):
            with self.assertRaisesRegex(ValueError, 'UNAUTHORIZED'):
                view.cache_semantics(raw)
        for raw in (listing.replace(b'1 libs', b'2 libs'), listing.replace(b'libc6,x86-64', b'libc6'),
                listing + b'Cache generated by: unknown\n', b'',
                listing.replace(b'1 libs', b'2 libs') + listing.split(b'\n', 1)[1]):
            with self.assertRaisesRegex(ValueError, 'BOUNDARY_CACHE_'):
                view.cache_semantics(raw)

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
