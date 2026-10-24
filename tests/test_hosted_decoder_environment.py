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
        def verify(argv, **kwargs):
            self.assertEqual(argv[:4], ['/usr/bin/gpgv', '--keyring', str(self.keyring), '--status-fd'])
            name = Path(argv[-1]).name.removesuffix('.InRelease')
            return SimpleNamespace(returncode=0, stdout=self.releases[name], stderr=''.join(
                '[GNUPG:] VALIDSIG ' + fp + ' rest\n' for fp in self.pins[name]['signing_fingerprints']).encode())
        self.fake_gpg = Mock(side_effect=verify)
        state = patch.dict(G, REPOSITORIES=self.pins, KEYRING=self.keyring)
        state.start()
        self.addCleanup(state.stop)
        command = patch.object(subprocess, 'run', self.fake_gpg)
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
        self.assertEqual(self.fake_gpg.call_count, 2)
        self.assertEqual(value['apt_options'], H['APT_OPTIONS'])
        self.assertFalse(value['scope']['compiled'])

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
        with patch.dict(G, LOCK=path, installed_inventory=lambda: sorted(self.after, key=lambda row: row['name'])):
            value = H['check_environment']()
            self.assertEqual(value['environment_lock_sha256'], H['digest'](path.read_bytes()))
        with patch.dict(G, LOCK=path, installed_inventory=lambda: self.before), self.assertRaisesRegex(ValueError, 'INSTALLED_INVENTORY_MISMATCH'):
            H['check_environment']()
        path.write_bytes(b'{"schema":1,"schema":1}')
        with patch.dict(G, LOCK=path), self.assertRaisesRegex(ValueError, 'DUPLICATE_KEY'): H['check_environment']()

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


if __name__ == '__main__':
    unittest.main()
