# SPDX-License-Identifier: GPL-3.0-only
"""Inert descriptor/identity regressions; no SDK, Dart, namespace or network."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import runpy
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
P = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_plugins.py'))
G = P['Binding'].__init__.__globals__
PRODUCTION = (ROOT / 'third_party/overmorrow-plugin-inputs-v1.json').read_bytes()


def put(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def descriptors():
    return len(os.listdir('/proc/self/fd'))


class PolicyTests(unittest.TestCase):
    def test_original_record_binds_all_packages_and_desktop_rows(self):
        value = P['policy'](PRODUCTION)
        self.assertEqual(len(value['packages']), 13)
        self.assertEqual(len(value['aliases']), 16)
        self.assertEqual(sum(not row['native_build'] for rows in value['manifest'].values() for row in rows), 8)
        self.assertEqual(value['manifest']['linux'][2]['dependencies'], ['package_info_plus'])
        for alias in value['aliases']:
            self.assertEqual(alias['target'], alias['canonical_target'] + '/')

    def test_original_policy_bytes_cannot_be_substituted(self):
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_POLICY_CHANGED'):
            P['policy'](PRODUCTION + b' ')


class BindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='p15-plugin-inert-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.base.chmod(0o700)
        self.stage, self.private = (self.base / name for name in ('stage', 'private'))
        self.cache = self.private / 'pub-cache'
        for path in (self.stage, self.private, self.cache):
            path.mkdir(mode=0o700)
        self.contents = {'pubspec.yaml': b'name: sample\nversion: 1.0.0\n',
                         'lib/sample.dart': b'const sample = 1;\n', 'lib/nested/data.bin': b'\x00\x01\x02'}
        files = {name: dict(type='file', bytes=len(raw), sha256=P['sha'](raw), executable=False)
                 for name, raw in self.contents.items()}
        self.package = self.cache / 'hosted/pub.dev/sample-1.0.0'
        for name, raw in self.contents.items():
            put(self.package / name, raw)
        archive_sha = P['sha'](b'inert synthetic archive identity')
        self.value = json.loads(PRODUCTION)
        self.value['packages'] = {'sample': dict(version='1.0.0',
            input=dict(source='hosted', version='1.0.0', sha256=archive_sha),
            archive=dict(sha256=archive_sha, files_sha256=P['sha'](P['canonical'](files))),
            files=files, pubspec_sha256=files['pubspec.yaml']['sha256'],
            platforms={platform: dict(dartPluginClass='Sample') for platform in ('linux', 'windows')})}
        self.target = '/state/pub-cache/hosted/pub.dev/sample-1.0.0/'
        self.value['aliases'] = [dict(platform=platform, package='sample',
            path=platform + '/flutter/ephemeral/.plugin_symlinks/sample',
            target=self.target, canonical_target=self.target[:-1]) for platform in ('windows', 'linux')]
        self.value['manifest'] = {platform: [dict(name='sample', native_build=False,
            dev_dependency=False, dependencies=[])] for platform in ('windows', 'linux')}
        self.manifest = dict(plugins={platform: [dict(row, path=self.target) for row in rows]
                                      for platform, rows in self.value['manifest'].items()})
        self.raw = P['canonical'](self.value)
        override = patch.dict(G, POLICY_SHA=P['sha'](self.raw))
        override.start()
        self.addCleanup(override.stop)
        put(self.stage / 'windows/CMakeLists.txt', b'# inert source marker\n')
        for alias in self.value['aliases']:
            path = self.stage / alias['path']
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.symlink_to(alias['target'])
        self.save_manifest()

    def save_manifest(self):
        put(self.stage / '.flutter-plugins-dependencies', P['canonical'](self.manifest))

    def binding(self, sealed=True):
        binding = P['Binding'](self.stage, self.cache, self.raw)
        if sealed:
            binding.seal()
        return binding

    def alias(self, platform='linux'):
        return self.stage / next(a['path'] for a in self.value['aliases'] if a['platform'] == platform)

    def replace_alias(self, target):
        alias = self.alias()
        alias.rename(self.base / 'held-old-link')
        alias.symlink_to(target)

    @contextmanager
    def mapped_namespace(self, *, private=None, cache=None):
        original = G['absolute_directory']
        @contextmanager
        def mapped(path, **kwargs):
            selected = str(cache or self.cache) if path == P['LOGICAL_CACHE'] else \
                str(private or self.private) if path == '/state' else path
            with original(selected, **kwargs) as fd:
                yield fd
        with patch.dict(G, absolute_directory=mapped):
            yield

    def run_probe(self, binding, *, private=None, digest=None):
        argv = ['inert-unit-probe', '/state/' + P['PLAN_NAME'], digest or binding.input_sha,
                json.dumps(binding.input_identity)]
        with self.mapped_namespace(private=private), patch.object(P['sys'], 'argv', argv):
            return P['main']()

    def test_exact_slash_target_with_private_physical_cache_passes(self):
        binding = self.binding()
        receipt = binding.verify()
        self.assertEqual(len(receipt['aliases']), 2)
        self.assertTrue(receipt['package_membermaps_verified'])
        self.assertTrue(receipt['original_file_identities_verified'])
        self.assertNotIn(str(self.base), json.dumps(receipt))

    def test_nonproducer_spellings_and_other_roots_are_rejected(self):
        variants = [self.target[:-1], '../../sample-1.0.0/',
            '/state/pub-cache/hosted/pub.dev/sample-2.0.0/',
            '/state/pub-cache/hosted/pub.dev//sample-1.0.0/',
            '/state/pub-cache/hosted/pub.dev/other/../sample-1.0.0/',
            '/outside/sample-1.0.0/']
        for target in variants:
            alias = self.alias()
            alias.unlink()
            alias.symlink_to(target)
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_SYMLINK_TARGET') as error:
                self.binding()
            observation = error.exception.plugin_failure
            self.assertEqual(observation['package'], 'sample')
            self.assertNotIn(target, json.dumps(observation))

    def test_unknown_extra_alias_is_rejected(self):
        self.alias().with_name('unknown').symlink_to(self.target)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_EXTRA_ENTRY'):
            self.binding()

    def test_missing_expected_alias_is_rejected(self):
        self.alias().unlink()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_ENTRY_SET'):
            self.binding()

    def test_link_chain_and_alias_ancestors_are_never_followed(self):
        alias = self.alias()
        chain = self.base / 'chain'
        chain.symlink_to(self.target)
        alias.unlink()
        alias.symlink_to(str(chain))
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_SYMLINK_TARGET'):
            self.binding()
        alias.unlink()
        alias.symlink_to(self.target)
        ancestor = self.stage / 'linux/flutter'
        ancestor.rename(self.base / 'held-flutter')
        ancestor.symlink_to(self.base / 'held-flutter', target_is_directory=True)
        with self.assertRaises(P['PluginFailure']):
            self.binding()

    def test_same_target_new_link_inode_fails_after_seal(self):
        binding = self.binding()
        self.replace_alias(self.target)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_LINK_SWAP'):
            binding.verify()

    def test_same_bytes_new_file_inode_fails_after_baseline(self):
        binding = self.binding()
        path = self.package / 'lib/sample.dart'
        path.rename(self.base / 'held-source')
        put(path, self.contents['lib/sample.dart'])
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_FILE_SWAP'):
            binding.verify()

    def test_same_files_new_package_directory_fails(self):
        binding = self.binding()
        old = self.base / 'held-package'
        self.package.rename(old)
        shutil.copytree(old, self.package)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_DIRECTORY_SWAP'):
            binding.verify()

    def test_same_files_new_nested_directory_fails(self):
        binding = self.binding()
        directory = self.package / 'lib/nested'
        directory.rename(self.base / 'held-nested')
        shutil.copytree(self.base / 'held-nested', directory)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_DIRECTORY_SWAP'):
            binding.verify()

    def test_cache_ancestor_replacement_is_rejected(self):
        binding = self.binding()
        hosted = self.cache / 'hosted'
        hosted.rename(self.base / 'held-hosted')
        shutil.copytree(self.base / 'held-hosted', hosted)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_DIRECTORY_SWAP'):
            binding.verify()

    def test_absolute_ancestor_replacement_with_same_root_inodes_is_rejected(self):
        binding = self.binding()
        held = self.base.with_name(self.base.name + '-held-ancestor')
        self.base.rename(held)
        self.base.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, held)
        for name in ('stage', 'private'):
            (held / name).rename(self.base / name)
        with self.assertRaises(P['PluginFailure']):
            binding.verify()

    def test_same_aliases_new_intermediate_directory_is_rejected(self):
        binding = self.binding()
        directory = self.alias().parent
        directory.rename(self.base / 'held-alias-directory')
        shutil.copytree(self.base / 'held-alias-directory', directory, symlinks=True)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_DIRECTORY_SWAP'):
            binding.verify()

    def test_same_size_mutation_of_original_source_is_rejected(self):
        binding = self.binding()
        raw = self.contents['lib/sample.dart']
        put(self.package / 'lib/sample.dart', raw.replace(b'1', b'2'))
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_PACKAGE_CHANGED'):
            binding.verify()

    def test_package_extra_entries_and_file_aliases_are_rejected(self):
        binding = self.binding()
        extra = self.package / 'extra.dart'
        put(extra, b'not authorized\n')
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_EXTRA_ENTRY'):
            binding.verify()
        extra.unlink()
        path = self.package / 'lib/sample.dart'
        path.unlink()
        path.symlink_to(self.package / 'pubspec.yaml')
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_FILE_METADATA'):
            binding.verify()

    def test_hardlinked_package_file_is_rejected(self):
        path = self.package / 'lib/sample.dart'
        os.link(path, self.base / 'held-hardlink')
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_FILE_METADATA'):
            self.binding()

    def test_metadata_wrong_package_set_and_source_path_are_rejected(self):
        binding = self.binding()
        original = copy.deepcopy(self.manifest)
        self.manifest['plugins']['linux'].append(dict(original['plugins']['linux'][0], name='unknown'))
        self.save_manifest()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_METADATA_CHANGED'):
            binding.verify()
        self.manifest = copy.deepcopy(original)
        self.manifest['plugins']['linux'][0]['path'] = self.target.replace('1.0.0', '2.0.0')
        self.save_manifest()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_METADATA_CHANGED'):
            binding.verify()

    def test_metadata_native_or_dependency_mutation_is_rejected(self):
        binding = self.binding()
        self.manifest['plugins']['linux'][0]['native_build'] = True
        self.save_manifest()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_METADATA_CHANGED'):
            binding.verify()

    def test_probe_plan_mutation_and_exact_byte_replacement_are_rejected(self):
        binding = self.binding()
        path = binding.write_probe_input(self.private)
        original = path.read_bytes()
        put(path, original + b' ')
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_PLAN_CHANGED'):
            binding.check_probe_input(self.private)
        put(path, original)
        path.rename(self.base / 'held-plan')
        put(path, original)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_FILE_SWAP'):
            binding.check_probe_input(self.private)

    def test_probe_private_parent_replacement_with_same_plan_inode_is_rejected(self):
        binding = self.binding()
        path = binding.write_probe_input(self.private)
        held = self.base / 'held-private'
        self.private.rename(held)
        self.private.mkdir(mode=0o700)
        (held / path.name).rename(path)
        with self.assertRaises(P['PluginFailure']):
            binding.check_probe_input(self.private)

    def test_actual_probe_entry_and_acceptance_roundtrip_with_mapped_namespace(self):
        binding = self.binding()
        expected = binding.verify()
        binding.write_probe_input(self.private)
        result = self.run_probe(binding)
        accepted = binding.accept_probe(P['canonical'](result), expected)
        self.assertTrue(accepted['namespace_identity_verified'])
        self.assertEqual(accepted, dict(expected, namespace_identity_verified=True))
        self.assertNotIn(str(self.base), json.dumps(accepted))

    def test_probe_entry_rejects_wrong_hash_and_different_private_parent_identity(self):
        binding = self.binding()
        path = binding.write_probe_input(self.private)
        before = descriptors()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_PLAN_CHANGED'):
            self.run_probe(binding, digest='0' * 64)
        other = self.base / 'different-private-parent'
        other.mkdir(mode=0o700)
        path.rename(other / path.name)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_NAMESPACE_IDENTITY'):
            self.run_probe(binding, private=other)
        self.assertEqual(descriptors(), before)

    def test_probe_success_cannot_forge_or_expand_expected_proof(self):
        binding = self.binding()
        expected = binding.verify()
        desired = dict(expected, namespace_identity_verified=True)
        for change in (dict(policy_sha256='0' * 64), dict(namespace_identity_verified=False),
                       dict(private_path=str(self.base))):
            proof = dict(desired, **change)
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_PROBE_BINDING') as error:
                binding.accept_probe(P['canonical'](dict(success=True, proof=proof)), expected)
            self.assertNotIn(str(self.base), json.dumps(error.exception.plugin_failure))

    def test_probe_typed_rejections_are_closed_and_bound_to_known_aliases(self):
        binding = self.binding()
        expected = binding.verify()
        alias = self.value['aliases'][0]
        row = dict(code='P15_PLUGIN_SYMLINK_TARGET', alias=alias['path'], package=alias['package'],
                   representation='relative', target_bytes=7, target_sha256=P['sha'](b'../bad/'))
        with self.assertRaisesRegex(P['PluginFailure'], row['code']) as error:
            binding.accept_probe(P['canonical'](dict(success=False, rejection=row)), expected)
        self.assertEqual(error.exception.plugin_failure, row)
        for altered in (dict(row, target=str(self.base)), dict(row, alias=str(self.base)),
                        dict(row, target_bytes=True), dict(row, target_sha256='not-a-digest')):
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_PROBE_REJECTION_SCHEMA') as error:
                binding.accept_probe(P['canonical'](dict(success=False, rejection=altered)), expected)
            self.assertNotIn(str(self.base), json.dumps(error.exception.plugin_failure))

    def test_leaf_observation_is_bound_to_sealed_inode(self):
        binding = self.binding()
        relative = self.alias().relative_to(self.stage).as_posix()
        binding.check_leaf(relative, self.alias().lstat())
        self.replace_alias(self.target)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_LINK_SWAP'):
            binding.check_leaf(relative, self.alias().lstat())

    def test_actual_candidate_scan_uses_real_binding_and_preserves_source_guard(self):
        candidate = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_candidate.py'))
        binding = self.binding()
        packages = dict(sample=dict(source='hosted', version='1.0.0'))
        expected = candidate['source_files'](self.stage, app_packages=packages, plugin_aliases=binding)
        candidate['recheck_source'](self.stage, expected, packages, plugin_aliases=binding)
        original = (self.stage / 'windows/CMakeLists.txt').read_bytes()
        put(self.stage / 'windows/CMakeLists.txt', b'# altered original source\n')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_CHANGED'):
            candidate['recheck_source'](self.stage, expected, packages, plugin_aliases=binding)
        put(self.stage / 'windows/CMakeLists.txt', original)
        self.replace_alias(self.target)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_LINK_SWAP'):
            candidate['source_files'](self.stage, app_packages=packages, plugin_aliases=binding)

    def test_namespace_checks_the_actual_mapped_cache_identity(self):
        binding = self.binding()
        original = G['absolute_directory']
        mapped = self.cache
        @contextmanager
        def namespace(path, **kwargs):
            selected = str(mapped) if path == P['LOGICAL_CACHE'] else str(self.private) if path == '/state' else path
            with original(selected, **kwargs) as fd:
                yield fd
        with patch.dict(G, absolute_directory=namespace):
            receipt, _ = P['validate'](binding.plan, namespace=True)
            self.assertTrue(receipt['namespace_identity_verified'])
            other = self.base / 'other-cache'
            shutil.copytree(self.cache, other)
            mapped = other
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_NAMESPACE_IDENTITY'):
                P['validate'](binding.plan, namespace=True)

    def test_failed_verifications_do_not_leak_descriptors(self):
        binding = self.binding()
        self.replace_alias(self.target[:-1])
        before = descriptors()
        for _ in range(10):
            with self.assertRaises(P['PluginFailure']):
                binding.verify()
        self.assertEqual(descriptors(), before)

    def test_root_identity_failures_do_not_leak_open_descriptors(self):
        before = descriptors()
        for _ in range(10):
            with self.assertRaises(P['PluginFailure']):
                with P['absolute_directory'](str(self.stage), expected={'/': [-1, -1, -1, -1, -1]}):
                    self.fail('wrong root identity admitted')
        self.assertEqual(descriptors(), before)

    def test_binding_cannot_validate_before_seal_or_replace_its_seal(self):
        binding = self.binding(sealed=False)
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_NOT_SEALED'):
            binding.verify()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_NOT_SEALED'):
            P['validate'](binding.plan)
        binding.seal()
        with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_ALREADY_SEALED'):
            binding.seal()

    def test_incremental_entry_limit_stops_before_consuming_remaining_entries(self):
        consumed = []
        @contextmanager
        def scan(_fd):
            def entries():
                for name in ('one', 'two', 'extra', 'must-not-be-consumed'):
                    consumed.append(name)
                    yield SimpleNamespace(name=name)
            yield entries()
        before = descriptors()
        with P['absolute_directory'](str(self.stage)) as fd, patch.object(P['os'], 'scandir', scan):
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_EXTRA_ENTRY'):
                P['names'](fd, {'one', 'two'})
        self.assertEqual(consumed, ['one', 'two', 'extra'])
        self.assertEqual(descriptors(), before)

    def test_repeated_duplicate_entries_cannot_bypass_incremental_limit(self):
        consumed = []
        @contextmanager
        def scan(_fd):
            def entries():
                while True:
                    consumed.append('one')
                    if len(consumed) > 3:
                        raise AssertionError('duplicate iterator was not bounded')
                    yield SimpleNamespace(name='one')
            yield entries()
        before = descriptors()
        with P['absolute_directory'](str(self.stage)) as fd, patch.object(P['os'], 'scandir', scan):
            with self.assertRaisesRegex(P['PluginFailure'], 'P15_PLUGIN_DUPLICATE_ENTRY'):
                P['names'](fd, {'one', 'two'})
        self.assertEqual(consumed, ['one', 'one'])
        self.assertEqual(descriptors(), before)


if __name__ == '__main__':
    unittest.main()
