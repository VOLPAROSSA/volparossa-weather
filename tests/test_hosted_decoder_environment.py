#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert input-integrity tests; synthetic archives are never executed/installed."""
import copy
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_decoder_environment.py'))
G = H['candidate'].__globals__
D = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_decoder.py'))


def deb(payload=b'compiler'):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:xz') as archive:
        item = tarfile.TarInfo('./usr/bin/test-cc')
        item.size = len(payload)
        archive.addfile(item, io.BytesIO(payload))
    raw = b'!<arch>\n'
    for name, data in [('debian-binary', b'2.0\n'), ('control.tar.xz', b'data only'), ('data.tar.xz', stream.getvalue())]:
        raw += (name + '/').ljust(16).encode() + b'0           0     0     100644  ' + str(len(data)).ljust(10).encode() + b'`\n'
        raw += data + (b'\n' if len(data) % 2 else b'')
    return raw


def status(rows):
    return ''.join('\t'.join([row['name'], row['version'], row['architecture'], 'installed']) + '\n' for row in rows).encode()


class Environment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.keyring = self.directory / 'keyring'
        self.keyring.write_bytes(b'pinned image keyring')
        self.verifier = self.directory / 'sqv'
        self.verifier.write_bytes(b'pinned image verifier')
        self.before = [dict(name=name, version='1.0', architecture='amd64') for name in H['ROOT_PACKAGES'] if name != 'build-essential']
        self.after = self.before + [dict(name='build-essential', version='2.0', architecture='amd64')]
        (self.directory / 'before.tsv').write_bytes(status(self.before))
        (self.directory / 'after.tsv').write_bytes(status(self.after))
        (self.directory / 'resolver.log').write_bytes(b'Inst build-essential (2.0 Debian:13/stable [amd64])\n')
        (self.directory / 'base-files.json').write_bytes(H['canonical']({'/usr/bin/base-cc': dict(bytes=4, sha256=H['digest'](b'base'))}))
        archive = deb()
        (self.directory / 'debs').mkdir()
        (self.directory / 'debs/test.deb').write_bytes(archive)
        self.pins, self.releases = copy.deepcopy(H['REPOSITORIES']), {}
        for name, pin in self.pins.items():
            record = (f'Package: build-essential\nVersion: 2.0\nArchitecture: amd64\nFilename: pool/main/t/test/test.deb\n'
                      f'Size: {len(archive)}\nSHA256: {H["digest"](archive)}\n\n') if name == 'debian' else 'Package: other\n\n'
            compressed = lzma.compress(record.encode())
            (self.directory / (name + '.Packages.xz')).write_bytes(compressed)
            signed = ('synthetic signed metadata ' + name).encode()
            (self.directory / (name + '.InRelease')).write_bytes(signed)
            pin.update(inrelease_bytes=len(signed), inrelease_sha256=H['digest'](signed))
            self.releases[name] = (f'Codename: {pin["codename"]}\nArchitectures: amd64\nComponents: main\nSHA256:\n'
                                   f' {H["digest"](compressed)} {len(compressed)} {H["INDEX_PATH"]}\n').encode()
        # Fixture safety must not depend on another test changing process umask.
        for path in self.directory.rglob('*'):
            if path.is_file():
                path.chmod(0o600)
        self.verifier.chmod(0o700)
        def verify(argv, **kwargs):
            self.assertEqual(argv[:3], [str(self.verifier), '--keyring', str(self.keyring)])
            name = Path(argv[-1]).name.removesuffix('.InRelease')
            self.assertEqual(argv[3:7], ['--signatures', str(len(self.pins[name]['certificate_fingerprints'])), '--cleartext', '--output'])
            self.assertEqual(kwargs['env'], {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            self.assertEqual(kwargs['umask'], 0o077)
            authenticated = Path(argv[7])
            self.assertFalse(authenticated.exists())
            authenticated.write_bytes(self.releases[name])
            authenticated.chmod(0o600)
            return SimpleNamespace(returncode=0, stdout=''.join(
                fp + '\n' for fp in self.pins[name]['certificate_fingerprints']).encode(), stderr=b'')
        self.fake_verifier = Mock(side_effect=verify)
        state = patch.dict(G, REPOSITORIES=self.pins, KEYRING=self.keyring,
            KEYRING_BYTES=len(self.keyring.read_bytes()), KEYRING_SHA=H['digest'](self.keyring.read_bytes()),
            VERIFIER=self.verifier, VERIFIER_BYTES=len(self.verifier.read_bytes()),
            VERIFIER_SHA=H['digest'](self.verifier.read_bytes()), CRYPTO_POLICY=self.directory / 'absent-policy')
        state.start()
        self.addCleanup(state.stop)
        command = patch.object(subprocess, 'run', self.fake_verifier)
        command.start()
        self.addCleanup(command.stop)

    def candidate(self):
        return H['validate_record'](H['candidate'](self.directory), False)

    def lock(self):
        candidate = self.candidate()
        value = dict(candidate, admitted=True, kind='volparossa-weather-source-environment-lock',
                     review=dict(candidate_sha256=H['digest'](H['canonical'](candidate)), review_commit='a' * 40))
        return H['validate_record'](value, True)

    def test_candidate_proves_signed_index_deb_and_member_bytes_without_admission(self):
        value = self.candidate()
        self.assertFalse(value['admitted'])
        self.assertEqual(len(value['packages']), 1)
        self.assertEqual(value['packages'][0]['files']['/usr/bin/test-cc'], dict(bytes=8, sha256=H['digest'](b'compiler')))
        self.assertEqual(self.fake_verifier.call_count, 2)
        self.assertEqual(value['apt_options'], H['APT_OPTIONS'])
        self.assertFalse(value['scope']['compiled'])

    def test_preinstall_selection_comes_only_from_signed_indexes_and_fixed_resolver(self):
        changes = H['resolver_inventory']((self.directory / 'resolver.log').read_bytes())
        repositories = {name: H['verify_release'](self.directory / (name + '.InRelease'), name) for name in self.pins}
        (self.directory / 'debs/test.deb').unlink()
        selected = H['indexed_packages'](self.directory, changes, repositories)
        self.assertEqual(selected[0]['filename'], 'pool/main/t/test/test.deb')
        self.assertNotIn('files', selected[0])
        with self.assertRaisesRegex(ValueError, 'DEB_SET'):
            H['verified_packages'](self.directory, changes, repositories)

    def test_security_archive_has_its_own_fixed_package_pool_prefix(self):
        H['package_filename']('debian', 'pool/main/g/gcc/test.deb')
        H['package_filename']('debian-security', 'pool/updates/main/g/gcc/test.deb')
        for repository, path in [('debian', 'pool/updates/main/g/gcc/test.deb'),
                                  ('debian-security', 'pool/main/g/gcc/test.deb'),
                                  ('debian-security', 'pool/updates/main/../test.deb')]:
            with self.assertRaisesRegex(ValueError, 'DEB_FILENAME'): H['package_filename'](repository, path)

    def test_realistic_apt_upgrade_diagnostics_do_not_change_selected_identity(self):
        line = 'Inst libc6 [2.41-12] (2.41-12+deb13u1 Debian-Security:13/stable-security [amd64])'
        expected = [dict(name='libc6', version='2.41-12+deb13u1', architecture='amd64')]
        for suffix in ['', ' [libc-bin:amd64 ]', ' []', ' [libc-bin:amd64 libgcc-s1:amd64 ]']:
            with self.subTest(suffix=suffix):
                self.assertEqual(H['resolver_inventory']((line + suffix + '\n').encode()), expected)
        self.assertEqual(H['resolver_inventory'](
            b'Inst build-essential (12.12 Debian:13/stable [all]) []\n'),
            [dict(name='build-essential', version='12.12', architecture='all')])

    def test_malformed_or_unbounded_apt_diagnostic_annotations_fail_closed(self):
        line = 'Inst libc6 [2.41-12] (2.41-12+deb13u1 Debian-Security:13/stable-security [amd64])'
        for suffix in [' [libc-bin:amd64]', ' [ ]', ' [[libc-bin:amd64 ]]', ' [] []',
                       ' [] ignored', ' [../escape ]', ' [libc-bin:arm64 ]', ' [libc-bin:amd64\t]',
                       ' [' + 'a ' * 2049 + ']']:
            with self.subTest(suffix=suffix[:80]), self.assertRaisesRegex(ValueError, 'RESOLVER_INSTALL'):
                H['resolver_inventory']((line + suffix + '\n').encode())
        with self.assertRaisesRegex(ValueError, 'RESOLVER_INSTALL'):
            H['resolver_inventory'](('Inst libc6 (2.41-12 ' + 'x' * 8192 + ' [amd64])\n').encode())
        with self.assertRaisesRegex(ValueError, 'RESOLVER_REMOVAL'):
            H['resolver_inventory']((line + ' []\nRemv libc-bin [2.41-12]\n').encode())

    def test_apt_diagnostic_annotation_never_authorizes_an_extra_dependency(self):
        (self.directory / 'resolver.log').write_bytes(
            b'Inst build-essential (2.0 Debian:13/stable [amd64]) [unselected-package:amd64 ]\n')
        value = self.candidate()
        self.assertEqual([item['name'] for item in value['packages']], ['build-essential'])
        self.assertNotIn('unselected-package', [item['name'] for item in value['after']])

    def test_candidate_is_rejected_by_consumer_even_with_toggled_flag(self):
        value = self.candidate()
        for changed in (value, dict(value, admitted=True), dict(value, admitted=1)):
            with self.subTest(changed=changed['admitted']), self.assertRaises(ValueError):
                H['validate_record'](changed, True)

    def test_changed_metadata_index_deb_and_extra_deb_fail(self):
        for name, code in [('debian.InRelease', 'INRELEASE_PIN'), ('debian.Packages.xz', 'INDEX_DIGEST'),
                           ('debs/test.deb', 'DEB_DIGEST')]:
            path = self.directory / name
            original = path.read_bytes()
            path.write_bytes(original + b'x')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, code): self.candidate()
            path.write_bytes(original)
        (self.directory / 'debs/extra.deb').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'DEB_SET'): self.candidate()

    def test_signature_failure_or_wrong_signer_never_authorizes_index(self):
        for status, code in [(SimpleNamespace(returncode=1, stdout=b'', stderr=b''), 'INRELEASE_SIGNATURE'),
                             (SimpleNamespace(returncode=0, stdout=b'', stderr=b'[GNUPG:] VALIDSIG ' + b'A' * 40 + b' rest\n'), 'INRELEASE_SIGNERS')]:
            with patch.object(subprocess, 'run', return_value=status), self.assertRaisesRegex(ValueError, code): self.candidate()

    def test_missing_or_changed_image_verifier_and_keyring_fail_before_execution(self):
        for path, code in [(self.verifier, 'BASE_VERIFIER_CHANGED'), (self.keyring, 'BASE_KEYRING_CHANGED')]:
            original = path.read_bytes()
            path.write_bytes(b'X' + original[1:])
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, code): self.candidate()
            path.write_bytes(original)
        self.verifier.unlink()
        with self.assertRaises(FileNotFoundError): self.candidate()
        self.fake_verifier.assert_not_called()

    def test_duplicate_certificates_and_unauthenticated_output_never_reach_parser(self):
        expected = self.pins['debian']['certificate_fingerprints']
        for signers, code in [(expected[:-1] + [expected[0]], 'INRELEASE_SIGNERS'),
                              (['A' * 40] * 3, 'INRELEASE_SIGNERS'),
                              (expected + [expected[0]], 'INRELEASE_SIGNERS')]:
            result = SimpleNamespace(returncode=0, stdout=('\n'.join(signers) + '\n').encode(), stderr=b'')
            with patch.object(subprocess, 'run', return_value=result), \
                    patch.dict(G, control_records=Mock(side_effect=AssertionError('must not parse unauthenticated data'))), \
                    self.assertRaisesRegex(ValueError, code): self.candidate()
        result = SimpleNamespace(returncode=1, stdout=('\n'.join(expected) + '\n').encode(), stderr=b'bad signature')
        with patch.object(subprocess, 'run', return_value=result), \
                patch.dict(G, control_records=Mock(side_effect=AssertionError('must not parse failed signature output'))), \
                self.assertRaisesRegex(ValueError, 'INRELEASE_SIGNATURE'): self.candidate()
        result.returncode = 0
        with patch.object(subprocess, 'run', return_value=result), self.assertRaises(FileNotFoundError): self.candidate()
        self.assertFalse(list(self.directory.glob('.verify-inrelease-*')))

    def test_unreviewed_default_policy_is_rejected_and_environment_injection_excluded(self):
        with patch.dict(os.environ, SEQUOIA_CRYPTO_POLICY='/untrusted/policy'):
            self.candidate()  # The fixed fake CLI asserts the complete sanitized child environment.
        self.fake_verifier.reset_mock()
        (self.directory / 'absent-policy').write_bytes(b'unreviewed policy')
        with self.assertRaisesRegex(ValueError, 'UNREVIEWED_CRYPTO_POLICY'): self.candidate()
        self.fake_verifier.assert_not_called()

    def test_removed_package_missing_root_and_resolver_delta_fail(self):
        for rows, resolver, code in [(self.after[1:], None, 'PACKAGE_REMOVAL'),
            (self.before, None, 'MISSING_ROOT_PACKAGE'), (self.after, b'no selected dependency\n', 'RESOLVER_CLOSURE'),
            (self.after, b'Remv git\n', 'RESOLVER_REMOVAL')]:
            (self.directory / 'after.tsv').write_bytes(status(rows))
            if resolver is not None: (self.directory / 'resolver.log').write_bytes(resolver)
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code): self.candidate()

    def test_lock_closure_review_and_strict_fields(self):
        original = self.lock()
        changes = [lambda value: value['packages'].clear(), lambda value: value.update(snapshot='latest'),
                   lambda value: value.update(url='https://arbitrary.invalid'), lambda value: value.update(schema=True),
                   lambda value: value['review'].update(candidate_sha256='0' * 64),
                   lambda value: value['packages'][0].update(filename='pool/main/../bad.deb'),
                   lambda value: value['packages'][0].update(bytes=True)]
        for change in changes:
            value = copy.deepcopy(original)
            change(value)
            with self.assertRaises(ValueError): H['validate_record'](value, True)

    def test_fixed_lock_requires_exact_installed_inventory_and_duplicate_keys_fail(self):
        path = self.directory / 'lock.json'
        path.write_bytes(H['canonical'](self.lock()))
        path.chmod(0o600)
        with patch.dict(G, LOCK=path, installed_inventory=lambda: sorted(self.after, key=lambda row: row['name'])):
            value = H['check_environment']()
            self.assertEqual(value['environment_lock_sha256'], H['digest'](path.read_bytes()))
        with patch.dict(G, LOCK=path, installed_inventory=lambda: self.before), self.assertRaisesRegex(ValueError, 'INSTALLED_INVENTORY_MISMATCH'):
            H['check_environment']()
        path.write_bytes(b'{"schema":1,"schema":1}')
        with patch.dict(G, LOCK=path), self.assertRaisesRegex(ValueError, 'DUPLICATE_KEY'): H['check_environment']()

    def test_locked_preinstall_inputs_require_fixed_admitted_lock_and_exact_bytes(self):
        path = self.directory / 'lock.json'
        value = self.lock()
        H['write_candidate_file'](path, H['canonical'](value))
        with patch.dict(G, LOCK=path):
            checked = H['verify_locked_inputs'](self.directory)
            self.assertEqual(checked['environment_lock_sha256'], H['digest'](path.read_bytes()))
            self.assertEqual(checked['packages'], ['pool/main/t/test/test.deb'])
            self.assertFalse(checked['compiled'])
            self.assertFalse(checked['decoder_authorized'])
            baseline = self.directory / 'base-files.json'
            raw = baseline.read_bytes()
            baseline.write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'BASE_FILES_MISMATCH'): H['verify_locked_inputs'](self.directory)
            baseline.write_bytes(raw)
            (self.directory / 'debs/test.deb').write_bytes(deb(b'changed bytes'))
            with self.assertRaisesRegex(ValueError, 'DEB_DIGEST'): H['verify_locked_inputs'](self.directory)
        path.write_bytes(H['canonical'](self.candidate_without_deb_recheck(value)))
        with patch.dict(G, LOCK=path), self.assertRaises(ValueError): H['verify_locked_inputs'](self.directory)
        path.unlink()
        with patch.dict(G, LOCK=path), self.assertRaises(FileNotFoundError): H['verify_locked_inputs'](self.directory)

    @staticmethod
    def candidate_without_deb_recheck(lock):
        value = {key: item for key, item in lock.items() if key != 'review'}
        value.update(admitted=False, kind='volparossa-weather-source-environment-candidate')
        return value

    def test_tool_binding_uses_reviewed_package_member_bytes_not_capture(self):
        lock = self.lock()
        environment = dict(inventory=lock['after'], packages=lock['packages'], base_files=lock['base_files'])
        tools = dict(cc=dict(path='/usr/bin/test-cc', bytes=8, sha256=H['digest'](b'compiler')))
        with patch.object(Path, 'resolve', lambda path: path), patch.object(subprocess, 'run', return_value=SimpleNamespace(stdout=b'build-essential: /usr/bin/test-cc\n')):
            value = H['bind_tools'](tools, environment)
            self.assertEqual(value['cc']['package']['name'], 'build-essential')
            tools['cc']['sha256'] = H['digest'](b'evil new capture')
            with self.assertRaisesRegex(ValueError, 'TOOL_PACKAGE_BYTES'): H['bind_tools'](tools, environment)
        tools['cc'] = dict(path='/usr/bin/base-cc', bytes=4, sha256=H['digest'](b'base'))
        with patch.object(Path, 'resolve', lambda path: path), patch.object(subprocess, 'run', return_value=SimpleNamespace(stdout=b'git: /usr/bin/base-cc\n')):
            self.assertEqual(H['bind_tools'](tools, environment)['cc']['sha256'], H['digest'](b'base'))

    def test_archive_path_traversal_and_truncated_ar_rejected(self):
        with self.assertRaisesRegex(ValueError, 'MEMBER_PATH'): H['member_path']('./usr/../etc/shadow')
        for raw in (b'not deb', deb()[:-10]):
            with self.assertRaises(ValueError): H['deb_files'](raw)
        self.assertEqual(H['member_path']('./lib/test.so'), '/usr/lib/test.so')

    def test_symlink_and_writable_evidence_rejected(self):
        path = self.directory / 'after.tsv'
        path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'UNSAFE_INPUT'): self.candidate()
        path.unlink()
        path.symlink_to(self.directory / 'before.tsv')
        with self.assertRaises(OSError): self.candidate()

    def test_candidate_cli_rechecks_evidence_and_never_accepts_lock_or_url_override(self):
        with patch.object(sys, 'argv', ['helper', 'candidate', '--evidence-dir', str(self.directory)]):
            self.assertEqual(H['main'](), 0)
        with patch.object(sys, 'argv', ['helper', 'verify-candidate', '--evidence-dir', str(self.directory)]):
            self.assertEqual(H['main'](), 0)
        value = json.loads((self.directory / 'candidate.json').read_bytes())
        value['admitted'] = True
        (self.directory / 'candidate.json').write_bytes(H['canonical'](value))
        with patch.object(sys, 'argv', ['helper', 'verify-candidate', '--evidence-dir', str(self.directory)]):
            self.assertEqual(H['main'](), 1)
        for args in [['check-environment', '--lock', 'elsewhere'], ['candidate', '--url', 'https://elsewhere']]:
            with patch.object(sys, 'argv', ['helper', *args]), self.assertRaises(SystemExit): H['main']()

    def test_source_builder_checks_static_authority_before_capture_or_execution(self):
        commands = Mock(side_effect=AssertionError('native build must not start'))
        with patch.dict(D['build_source'].__globals__, source_environment=Mock(side_effect=ValueError('MISSING_LOCK')), build=commands):
            with self.assertRaisesRegex(ValueError, 'MISSING_LOCK'):
                D['build_source'](Path('/archives'), Path('/output'), Path('/toolchain'))
        commands.assert_not_called()
        for function in ('capture_source_toolchain', 'build_source'):
            self.assertIn('source_environment', D[function].__code__.co_names)

    def test_development_object_uses_reviewed_bytes_and_rejects_collision(self):
        actual = self.directory / 'f09.so'
        actual.write_bytes(b'library')
        info, original_open = actual.stat(), os.open
        environment = dict(base_files={'/usr/lib/f09.so': dict(bytes=7, sha256=H['digest'](b'library'))}, packages=[])
        def opened(path, flags):
            self.assertEqual(str(path), '/usr/lib/f09.so')
            return original_open(actual, flags)
        with patch.object(os, 'walk', return_value=[('/usr/lib', [], ['f09.so'])]), \
                patch.object(Path, 'resolve', lambda path, **_kwargs: path), \
                patch.object(Path, 'stat', return_value=info), patch.object(os, 'open', opened):
            self.assertRegex(H['verify_development_files'](environment), '^[a-f0-9]{64}$')
            environment['base_files']['/usr/lib/f09.so']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'DEVELOPMENT_FILE_BYTES'):
                H['verify_development_files'](environment)
        environment['packages'] = [dict(files={'/usr/lib/duplicate.so': {}})] * 2
        with self.assertRaisesRegex(ValueError, 'PACKAGE_FILE_COLLISION'):
            H['verify_development_files'](environment)

    def test_source_build_checks_before_and_after_and_emits_deterministic_unadmitted_manifest(self):
        output = self.directory / 'output'
        output.mkdir()
        toolchain = dict(tools={'cc': dict(path='/usr/bin/test-cc')})
        environment = dict(environment_lock_sha256='1' * 64)
        checked = Mock(return_value=environment)
        helper = dict(check_environment=checked, bind_tools=Mock(return_value={'cc': 'reviewed package bytes'}),
                      verify_development_files=Mock(return_value='2' * 64), canonical=H['canonical'])
        report = dict(recipe_sha256='3' * 64, effective_flags={'compile': '-O3'},
                      artifacts=[dict(path='eccodes-build/bin/grib_ls', bytes=4, sha256='4' * 64)],
                      licenses=[], tests=dict(version=True))
        build = Mock(return_value=report)
        def source_file(path, *_args):
            return b'captured manifest' if path == Path('/manifest') else b'environment helper source'
        with patch.dict(D['build_source'].__globals__, source_environment=lambda: (helper, environment),
                read_file=source_file, load_toolchain=lambda *_args: toolchain, build=build):
            result = D['build_source'](Path('/archives'), output, Path('/manifest'))
        self.assertEqual(result['kind'], 'volparossa-weather-source-build-manifest')
        self.assertFalse(result['admitted'])
        self.assertEqual(result['environment_lock_sha256'], '1' * 64)
        self.assertEqual(json.loads((output / 'build-manifest.json').read_bytes()), result)
        self.assertNotIn(str(output), (output / 'build-manifest.json').read_text())
        self.assertEqual(helper['bind_tools'].call_count, 2)
        self.assertEqual(helper['verify_development_files'].call_count, 2)
        checked.assert_called_once_with()
        build.assert_called_once_with(Path('/archives'), output, Path('/manifest'), H['digest'](b'captured manifest'))

    def test_changed_environment_after_build_cannot_emit_source_manifest(self):
        output = self.directory / 'failed'
        output.mkdir()
        environment = dict(environment_lock_sha256='1' * 64)
        helper = dict(check_environment=Mock(return_value={'changed': True}), bind_tools=Mock(return_value={}),
                      verify_development_files=Mock(return_value='2' * 64))
        with patch.dict(D['build_source'].__globals__, source_environment=lambda: (helper, environment),
                read_file=lambda *_args: b'manifest', load_toolchain=lambda *_args: {'tools': {}}, build=Mock(return_value={})), \
                self.assertRaisesRegex(ValueError, 'SOURCE_ENVIRONMENT_CHANGED'):
            D['build_source'](Path('/archives'), output, Path('/manifest'))
        self.assertFalse((output / 'build-manifest.json').exists())

    def test_source_capture_authenticates_aliases_before_first_execution(self):
        output = self.directory / 'build/hosted-toolchain-test'
        executed = Mock(side_effect=AssertionError('must authenticate before execution'))
        binder = Mock(side_effect=ValueError('TOOL_PACKAGE_BYTES'))
        def record(path):
            return dict(path=str(path), bytes=8, sha256=H['digest'](b'compiler'), version_sha256=None)
        with patch.object(os, 'geteuid', return_value=1000), \
                patch.object(D['shutil'], 'which', side_effect=lambda name, **_kwargs: '/usr/bin/' + name), \
                patch.dict(D['capture_toolchain'].__globals__, ROOT=self.directory,
                    platform=lambda: {}, tool_record=record, captured_program=executed, run_step=executed):
            with self.assertRaisesRegex(ValueError, 'TOOL_PACKAGE_BYTES'):
                D['capture_toolchain'](output, pre_execute=binder)
        executed.assert_not_called()
        self.assertEqual(set(binder.call_args.args[0]), {'cc', 'cxx', 'python', 'bwrap', 'sh', 'ar',
            'ranlib', 'cmake', 'ctest', 'make', 'git', 'mawk'})
        self.assertFalse(output.exists())

    def test_source_capture_checks_discovered_compiler_before_version_execution(self):
        output = self.directory / 'build/hosted-toolchain-test'
        versions = Mock(side_effect=AssertionError('untrusted compiler must not execute'))
        discovery = Mock(return_value=(Path('/usr/bin/cc1'), {}))
        seen = []
        def binder(tools):
            seen.append(set(tools))
            if 'cc1' in tools: raise ValueError('TOOL_PACKAGE_BYTES')
        def record(path):
            return dict(path=str(path), bytes=8, sha256=H['digest'](b'compiler'), version_sha256=None)
        with patch.object(os, 'geteuid', return_value=1000), \
                patch.object(D['shutil'], 'which', side_effect=lambda name, **_kwargs: '/usr/bin/' + name), \
                patch.dict(D['capture_toolchain'].__globals__, ROOT=self.directory,
                    platform=lambda: {}, tool_record=record, captured_program=discovery, run_step=versions):
            with self.assertRaisesRegex(ValueError, 'TOOL_PACKAGE_BYTES'):
                D['capture_toolchain'](output, pre_execute=binder)
        self.assertEqual(seen[-1], {'cc1'})
        self.assertEqual(discovery.call_count, 1)
        versions.assert_not_called()

    def test_header_directory_link_cannot_hide_unchecked_library_tree_header(self):
        def resolved(path, **_kwargs):
            return Path('/usr/lib/unclassified-headers') if str(path) == '/usr/include/foo' else path
        with patch.object(os, 'walk', return_value=[('/usr/include', ['foo'], [])]), \
                patch.object(Path, 'is_symlink', return_value=True), patch.object(Path, 'resolve', resolved), \
                self.assertRaisesRegex(ValueError, 'DEVELOPMENT_DIRECTORY_COVERAGE'):
            H['verify_development_files'](dict(base_files={}, packages=[]))

    def payload_fixture(self):
        root = self.directory / 'recipe'
        root.mkdir()
        for name in ('scripts/prepare_hosted_decoder.py', 'scripts/prepare_hosted_decoder_environment.py',
                     'third_party/eccodes-sources.json'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            H['write_candidate_file'](path, (ROOT / name).read_bytes())
        output = root / 'build/hosted-decoder-fixture'
        output.mkdir(parents=True)
        environment = dict(environment_lock_sha256='1' * 64)
        manifest = dict.fromkeys(D['SOURCE_MANIFEST_FIELDS'])
        manifest.update(schema=1, kind='volparossa-weather-source-build-manifest', admitted=False,
            compiled=True, tests_passed=True, environment_lock_sha256='1' * 64,
            source_pin_sha256=D['PIN_SHA'], source_helper_sha256=D['LEGACY_SHA'],
            recipe_sha256=H['digest']((root / 'scripts/prepare_hosted_decoder.py').read_bytes()),
            environment_helper_sha256=H['digest']((root / 'scripts/prepare_hosted_decoder_environment.py').read_bytes()),
            source_date_epoch=D['EPOCH'], jobs=D['JOBS'], namespace_build_path='/build', environment=D['ENV'],
            date_shim_sha256=H['digest'](D['DATE_SHIM']), scope=D['SCOPE'], effective_flags={}, tests={},
            tool_package_bindings={}, development_files_sha256='2' * 64, artifacts=[], licenses=[])
        for name in D['SOURCE_ARTIFACTS']:
            raw = b'\x7fELF synthetic data only' if name.endswith(('grib_ls', 'grib_filter', 'codes_info')) else b'fixture'
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            H['write_candidate_file'](path, raw)
            manifest['artifacts'].append(dict(path=name, bytes=len(raw), sha256=H['digest'](raw)))
        pin = json.loads((root / 'third_party/eccodes-sources.json').read_bytes())
        names = {item['name'] + '-source/' + name for item in pin['sources'] for name in item['notices']}
        names.add('eccodes-source/third_party/expected/COPYING')
        for name in sorted(names):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b'unchanged synthetic notice bytes: ' + name.encode()
            H['write_candidate_file'](path, raw)
            manifest['licenses'].append(dict(path=name, bytes=len(raw), sha256=H['digest'](raw), symlink_target=None))
        H['write_candidate_file'](output / 'build-manifest.json', H['canonical'](manifest))
        return root, output, environment, manifest

    def payload_state(self, root, environment):
        helper = dict(check_environment=lambda: environment, canonical=H['canonical'])
        return patch.dict(D['stage_source_payload'].__globals__, ROOT=root,
            PIN=root / 'third_party/eccodes-sources.json', __file__=str(root / 'scripts/prepare_hosted_decoder.py'),
            source_environment=lambda: (helper, environment))

    def test_source_payload_is_closed_bounded_regular_files_and_unadmitted(self):
        root, build, environment, manifest = self.payload_fixture()
        H['write_candidate_file'](build / 'private-package.deb', b'never copied')
        output = root / 'build/hosted-payload-fixture'
        with self.payload_state(root, environment):
            value = D['stage_source_payload'](build, output)
        expected = {item['path'] for item in manifest['artifacts'] + manifest['licenses']} | {'build-manifest.json'}
        self.assertEqual(set(value['files']), expected)
        self.assertEqual({str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()}, expected)
        self.assertFalse(value['admitted'])
        self.assertLessEqual(value['bytes'], 160 * 1024**2)
        self.assertEqual(json.loads((build / 'payload-manifest.json').read_bytes()), value)
        self.assertNotIn(str(root), (build / 'payload-manifest.json').read_text())
        self.assertFalse((output / 'payload-manifest.json').exists())
        for name, item in value['files'].items():
            path = output / name
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.stat().st_mode & 0o777, item['mode'])
            self.assertEqual(H['digest'](path.read_bytes()), item['sha256'])
        self.assertEqual(value['files']['eccodes-build/bin/grib_ls']['mode'], 0o500)

    def test_source_payload_rejects_changed_bytes_extra_declared_file_and_wrong_lock(self):
        root, build, environment, manifest = self.payload_fixture()
        mutations = [lambda value: value.update(admitted=True),
                     lambda value: value.update(environment_lock_sha256='0' * 64),
                     lambda value: value['artifacts'].append(dict(path='extra-file', bytes=1, sha256='0' * 64))]
        with self.payload_state(root, environment):
            for index, mutate in enumerate(mutations):
                value = copy.deepcopy(manifest); mutate(value)
                (build / 'build-manifest.json').write_bytes(H['canonical'](value))
                with self.assertRaises(ValueError):
                    D['stage_source_payload'](build, root / ('build/hosted-payload-bad' + str(index)))
            (build / 'build-manifest.json').write_bytes(H['canonical'](manifest))
            (build / 'probe.grib2').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SOURCE_PAYLOAD_BYTES'):
                D['stage_source_payload'](build, root / 'build/hosted-payload-bytes')

    def test_source_payload_rejects_symlink_escape_and_total_bound_before_copy(self):
        root, build, environment, _manifest = self.payload_fixture()
        binary = build / 'eccodes-build/bin/grib_ls'
        original = binary.read_bytes()
        binary.unlink(); binary.symlink_to(root / 'scripts/prepare_hosted_decoder.py')
        with self.payload_state(root, environment):
            with self.assertRaisesRegex(ValueError, 'SOURCE_PAYLOAD_PATH'):
                D['stage_source_payload'](build, root / 'build/hosted-payload-escape')
            binary.unlink(); H['write_candidate_file'](binary, original)
            with patch.dict(D['source_payload_files'].__globals__, MAX_SOURCE_PAYLOAD=10), \
                    self.assertRaisesRegex(ValueError, 'SOURCE_PAYLOAD_BOUND'):
                D['stage_source_payload'](build, root / 'build/hosted-payload-large')
            self.assertFalse((root / 'build/hosted-payload-large').exists())


if __name__ == '__main__':
    unittest.main()
