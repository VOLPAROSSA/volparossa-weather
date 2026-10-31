# SPDX-License-Identifier: GPL-3.0-only
"""Inert tamper tests. No Node, downloaded code, network or privilege."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
D = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_drizzli_dependencies.py'))


class InstalledTreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name)
        (self.stage / 'node_modules').mkdir(mode=0o700)
        self.name = 'node_modules/tool'
        manifest = dict(name='tool', version='1.0.0', bin={'tool': 'cli.js'})
        data = {'package.json': json.dumps(manifest).encode(), 'cli.js': b'// fixed code\n'}
        files = {}
        for name, raw in data.items():
            path = self.stage / self.name / name
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
            files[name] = dict(type='file', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        files['package.json']['package_json'] = manifest
        self.pin = dict(name='tool', version='1.0.0', url='https://registry.npmjs.org/tool/-/tool-1.0.0.tgz',
            integrity='sha512-AAAA', optional=False)
        entry = dict(input=self.pin, archive=dict(files=files), inactive=False)
        self.record = dict(packages={self.name: entry}, approved=dict(packages={self.name: entry}))
        self.bin = self.stage / 'node_modules/.bin'
        self.bin.mkdir(mode=0o700)
        (self.bin / 'tool').symlink_to('../tool/cli.js')
        self.hidden = self.stage / 'node_modules/.package-lock.json'
        self.hidden.write_text(json.dumps(dict(lockfileVersion=3, packages={self.name: dict(
            version=self.pin['version'], resolved=self.pin['url'], integrity=self.pin['integrity'])})))
        self.hidden.chmod(0o600)

    def verify(self, **kwargs):
        return D['installed_tree'](self.stage, self.record, **kwargs)

    def test_exact_archive_bytes_and_manifest_cli_succeed(self):
        result = self.verify()
        self.assertEqual(result['packages'], [self.name])
        self.assertEqual(result['links'], {'node_modules/.bin/tool': self.name + '/cli.js'})

    def test_installed_tamper_rejected(self):
        (self.stage / self.name / 'cli.js').write_bytes(b'mutated')
        with self.assertRaisesRegex(ValueError, 'P14_INSTALLED_BYTES'):
            self.verify()

    def test_unbound_file_rejected(self):
        (self.stage / self.name / 'unbound.js').write_bytes(b'code')
        with self.assertRaisesRegex(ValueError, 'P14_UNBOUND_FILE'):
            self.verify()

    def test_unbound_generated_directory_rejected(self):
        (self.stage / 'node_modules/.unapproved-generator').mkdir()
        with self.assertRaisesRegex(ValueError, 'P14_UNBOUND_DIRECTORY'):
            self.verify()

    def test_exact_vite_config_temp_directory_must_be_empty(self):
        directory = self.stage / 'node_modules/.vite-temp'
        directory.mkdir(mode=0o700)
        self.assertEqual(self.verify()['packages'], [self.name])
        (directory / 'vite.config.ts.timestamp-1.mjs').write_bytes(b'generated config')
        with self.assertRaisesRegex(ValueError, 'P14_VITE_TEMP_NOT_EMPTY'):
            self.verify()

    def test_vite_temp_cannot_be_a_directory_alias(self):
        (self.stage / 'node_modules/.vite-temp').symlink_to(self.bin, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'P14_UNBOUND_LINK'):
            self.verify()

    def test_bin_escape_rejected(self):
        link = self.bin / 'tool'
        link.unlink()
        link.symlink_to('/usr/bin/node')
        with self.assertRaisesRegex(ValueError, 'P14_BIN_ESCAPE'):
            self.verify()

    def test_unknown_directory_symlink_rejected(self):
        (self.stage / self.name / 'alias').symlink_to(self.stage / self.name, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'P14_UNBOUND_LINK'):
            self.verify()

    def test_missing_required_package_rejected(self):
        self.record['packages']['node_modules/required'] = copy.deepcopy(self.record['packages'][self.name])
        with self.assertRaisesRegex(ValueError, 'P14_ACTIVE_PACKAGE_MISSING'):
            self.verify()

    def test_absent_optional_transitive_recorded_without_authorizing_extra_files(self):
        entry = copy.deepcopy(self.record['packages'][self.name])
        entry['input']['optional'] = True
        self.record['packages']['node_modules/optional'] = entry
        self.assertEqual(self.verify()['packages'], [self.name])

    def test_inactive_data_cannot_be_present_during_execution(self):
        self.record['packages'][self.name]['inactive'] = True
        with self.assertRaisesRegex(ValueError, 'P14_INACTIVE_PACKAGE_PRESENT'):
            self.verify(after_removal=True)

    def test_hidden_lock_cannot_introduce_a_new_package(self):
        value = json.loads(self.hidden.read_text())
        value['packages']['node_modules/unknown'] = value['packages'][self.name]
        self.hidden.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P14_HIDDEN_LOCK_SET'):
            self.verify()

    def test_hidden_lock_wrong_source_rejected(self):
        value = json.loads(self.hidden.read_text())
        value['packages'][self.name]['resolved'] = 'https://unreviewed.invalid/package'
        self.hidden.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P14_HIDDEN_LOCK_BINDING'):
            self.verify()

    def test_file_hardlink_rejected(self):
        path = self.stage / self.name / 'cli.js'
        os.link(path, self.stage / 'outside-copy')
        with self.assertRaisesRegex(ValueError, 'P14_INSTALLED_FILE_TYPE'):
            self.verify()

    def test_fixed_full_dependency_set_and_large_native_input_are_unchanged(self):
        inputs = D['I']
        value = inputs.load_package_inputs('drizzli')['dependencies']
        locked = inputs.npm_lock(inputs.read(ROOT / 'third_party/client-locks/drizzli-package-lock.json'))
        self.assertEqual(set(value['packages']), set(locked))
        self.assertEqual(len(locked), 347)
        self.assertEqual(len(value['plugins']), 2)
        self.assertEqual(value['packages']['node_modules/@lix-js/sdk-linux-x64']['archive']['bytes'], 77705486)
        for name, entry in value['packages'].items():
            self.assertEqual(entry['input'], locked[name])


if __name__ == '__main__':
    unittest.main()
