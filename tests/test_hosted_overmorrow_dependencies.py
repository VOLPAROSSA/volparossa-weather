# SPDX-License-Identifier: GPL-3.0-only
"""Inert archive and generated-metadata guards; no SDK/package execution."""
import copy
import io
import hashlib
import json
import os
from pathlib import Path
import runpy
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
D = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_dependencies.py'))
I = D['I']


def archive(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as output:
        for name, raw, mode in members:
            member = tarfile.TarInfo(name)
            member.mode = mode
            member.size = len(raw)
            output.addfile(member, io.BytesIO(raw))
    return stream.getvalue()


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.raw = archive([('pubspec.yaml', b'name: example\nversion: 1.0.0\n', 0o644),
                            ('lib/example.dart', b'const answer = 42;\n', 0o644),
                            ('LICENSE', b'Original notice\n', 0o644),
                            ('bin/tool', b'inert fixture\n', 0o755)])
        self.inventory = I.archive_inventory(self.raw, npm=False)
        self.files = self.inventory['files']
        self.pin = {key: self.inventory[key] for key in ('bytes', 'sha256', 'expanded_bytes')}
        self.pin['files_sha256'] = I.sha(I.canonical(self.files))

    def extracted(self):
        target = self.root / 'package'
        D['extract_regular'](self.raw, target, self.files)
        return target

    def test_fixed_original_inputs_unchanged(self):
        entries, packages = D['fixed_inputs']()
        self.assertEqual(len(entries), 157)
        self.assertEqual(sum(e['source'] == 'hosted' for e in entries.values()), 152)
        self.assertEqual(len(packages), 157)

    def test_directory_cardinality_stops_incremental_reader_early(self):
        consumed = []
        @contextmanager
        def scan(_directory):
            def entries():
                for index in range(100):
                    consumed.append(index)
                    yield SimpleNamespace(name=str(index))
            yield entries()
        with patch.object(D['os'], 'scandir', scan):
            with self.assertRaisesRegex(ValueError, 'P15_DIRECTORY_ENTRIES_BOUND'):
                D['directory_paths'](self.root, 2)
        self.assertEqual(consumed, [0, 1, 2])

    def test_fixed_tool_record_and_exact_union(self):
        record = D['load_tool_record']()
        self.assertEqual(len(record['packages']), 101)
        app, packages = D['fixed_inputs']()
        tools = {name: package['input'] for name, package in record['packages'].items()}
        union = D['union_inputs'](app, packages, tools, record)
        self.assertEqual(len(union), 224)
        self.assertEqual(sum(item['origin'] == 'sdk' for item in union.values()), 101)
        self.assertEqual(sum(item['origin'] == 'app' for item in union.values()), 123)
        self.assertIn('analyzer-8.2.0', union)
        self.assertIn('analyzer-10.0.1', union)
        self.assertEqual(sum(len(p['notices']) for p in record['packages'].values()), 110)

    def test_conflicting_deduplication_rejected(self):
        record = copy.deepcopy(D['load_tool_record']())
        app, packages = D['fixed_inputs']()
        tools = {name: package['input'] for name, package in record['packages'].items()}
        shared = next(name for name, item in tools.items() if app.get(name) == item)
        record['packages'][shared]['archive']['files_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'P15_CONFLICTING_PACKAGE_BYTES'):
            D['union_inputs'](app, packages, tools, record)

    def test_tool_record_mutation_rejected(self):
        altered = self.root / 'record.json'
        altered.write_bytes(D['TOOL_INPUTS'].read_bytes() + b' ')
        with patch.dict(D['load_tool_record'].__globals__, TOOL_INPUTS=altered):
            with self.assertRaisesRegex(ValueError, 'P15_TOOL_INPUT_RECORD_CHANGED'):
                D['load_tool_record']()

    def tool_lock(self):
        return b'''packages:
  example:
    dependency: "direct main"
    description:
      name: example
      sha256: "''' + b'a' * 64 + b'''"
      url: "https://pub.dev"
    source: hosted
    version: "1.0.0"
sdks:
  dart: ">=3.9.0 <4.0.0"
'''

    def test_tool_lock_original_narrow_schema(self):
        parsed = D['parse_tool_lock'](self.tool_lock())
        self.assertEqual(parsed['example']['url'], 'https://pub.dev/api/archives/example-1.0.0.tar.gz')
        self.assertEqual(parsed['example']['sha256'], 'a' * 64)

    def test_tool_lock_other_sources_or_sdk_constraints_rejected(self):
        for raw in (self.tool_lock().replace(b'source: hosted', b'source: git'),
                    self.tool_lock().replace(b'https://pub.dev', b'https://example.invalid'),
                    self.tool_lock() + b'  flutter: ">=3.38.5"\n',
                    self.tool_lock().replace(b'    source: hosted', b'    source: hosted\n    source: hosted')):
            with self.assertRaises(ValueError):
                D['parse_tool_lock'](raw)

    def test_complete_archive_binding(self):
        self.assertEqual(D['authenticated_inventory'](self.raw, self.pin), self.files)
        altered = dict(self.pin, files_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'P15_ARCHIVE_MEMBER_BINDING'):
            D['authenticated_inventory'](self.raw, altered)

    def test_hooks_block_before_extraction(self):
        for name in ('hook/build.dart', 'hook/link.dart', 'hooks/build.dart', 'build.dart'):
            files = dict(self.files, **{name: dict(type='file')})
            with self.assertRaisesRegex(ValueError, 'P15_UNREVIEWED_PACKAGE_HOOK'):
                D['lifecycle'](files)

    def test_normal_bin_source_is_not_automatic_hook(self):
        D['lifecycle'](self.files)

    def test_extraction_preserves_notice_bytes_and_execution_bit(self):
        target = self.extracted()
        D['verify_package'](target, self.files)
        self.assertEqual((target / 'LICENSE').read_bytes(), b'Original notice\n')
        self.assertEqual((target / 'bin/tool').stat().st_mode & 0o777, 0o700)
        self.assertEqual((target / 'lib/example.dart').stat().st_mode & 0o777, 0o600)

    def test_mutated_original_file_rejected(self):
        target = self.extracted()
        (target / 'lib/example.dart').write_bytes(b'const answer = 43;\n')
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_FILE_CHANGED'):
            D['verify_package'](target, self.files)

    def test_extra_code_rejected(self):
        target = self.extracted()
        (target / 'lib/new.dart').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'P15_UNKNOWN_PACKAGE_FILE'):
            D['verify_package'](target, self.files)

    def test_deleted_original_rejected(self):
        target = self.extracted()
        (target / 'LICENSE').unlink()
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_TREE_CHANGED'):
            D['verify_package'](target, self.files)

    def test_package_alias_rejected(self):
        target = self.extracted()
        (target / 'lib/example.dart').unlink()
        (target / 'lib/example.dart').symlink_to(target / 'LICENSE')
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_FILE_METADATA'):
            D['verify_package'](target, self.files)

    def test_archive_path_escape_rejected(self):
        raw = archive([('../escape', b'inert', 0o644)])
        with self.assertRaises(ValueError):
            I.archive_inventory(raw, npm=False)

    def config(self, root='/state/pub-cache/hosted/pub.dev/example-1.0.0'):
        stage = self.root / 'stage'
        (stage / '.dart_tool').mkdir(parents=True, mode=0o700)
        (stage / 'pubspec.yaml').write_text('name: overmorrow\nenvironment:\n  sdk: ">=3.0.6 <4.0.0"\n')
        package = self.root / 'cache/hosted/pub.dev/example-1.0.0'
        package.mkdir(mode=0o700, parents=True)
        (package / 'pubspec.yaml').write_text('name: example\nenvironment:\n  sdk: ^3.0.0\n')
        value = dict(configVersion=2, generator='pub', generatorVersion='3.10.4', packages=[
            dict(name='example', rootUri='file://' + root, packageUri='lib/', languageVersion='3.0'),
            dict(name='overmorrow', rootUri='../', packageUri='lib/', languageVersion='3.0')])
        (stage / '.dart_tool/package_config.json').write_text(json.dumps(value))
        return stage, value

    def test_generated_config_authorized_roots(self):
        stage, _ = self.config()
        result = D['generated_binding'](stage, self.root / 'sdk', self.root / 'cache',
                    dict(example=dict(source='hosted', version='1.0.0')))
        self.assertTrue(result['exact_authorized_roots'])

    def test_generated_config_foreign_source_rejected(self):
        stage, _ = self.config('/tmp/foreign-source')
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_CONFIG_ROOT'):
            D['generated_binding'](stage, self.root / 'sdk', self.root / 'cache',
                    dict(example=dict(source='hosted', version='1.0.0')))

    def test_generated_config_duplicate_rejected(self):
        stage, value = self.config()
        value['packages'].append(value['packages'][0])
        (stage / '.dart_tool/package_config.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_CONFIG_ENTRY'):
            D['generated_binding'](stage, self.root / 'sdk', self.root / 'cache',
                    dict(example=dict(source='hosted', version='1.0.0')))

    def test_generated_language_version_bound_to_each_original_pubspec(self):
        stage, value = self.config()
        for package_index, altered in ((0, '2.0'), (0, '3.99'), (1, '3.99')):
            changed = copy.deepcopy(value)
            changed['packages'][package_index]['languageVersion'] = altered
            (stage / '.dart_tool/package_config.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_LANGUAGE_CHANGED'):
                D['generated_binding'](stage, self.root / 'sdk', self.root / 'cache',
                    dict(example=dict(source='hosted', version='1.0.0')))

    def test_generated_sdk_language_bound_to_original_sdk_pubspec(self):
        stage, value = self.config()
        sdk = self.root / 'sdk'
        flutter = sdk / 'packages/flutter'
        flutter.mkdir(mode=0o700, parents=True)
        (flutter / 'pubspec.yaml').write_text('name: flutter\nenvironment:\n  sdk: ^3.8.0-0\n')
        value['packages'].append(dict(name='flutter', rootUri=flutter.as_uri(), packageUri='lib/', languageVersion='3.8'))
        entries = dict(example=dict(source='hosted', version='1.0.0'), flutter=dict(source='sdk', version='0.0.0'))
        (stage / '.dart_tool/package_config.json').write_text(json.dumps(value))
        D['generated_binding'](stage, sdk, self.root / 'cache', entries)
        value['packages'][-1]['languageVersion'] = '3.99'
        (stage / '.dart_tool/package_config.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_LANGUAGE_CHANGED'):
            D['generated_binding'](stage, sdk, self.root / 'cache', entries)

    def test_pub_language_uses_original_lower_bound_and_prerelease(self):
        for constraint, expected in (('^3.8.0-0', '3.8'), ('">=2.12.0-0 <3.0.0"', '2.12'),
                                     ("'>=3.0.6 <4.0.0'", '3.0'), ('3.10.4', '3.10'),
                                     ('"<4.0.0"', '2.7'), ('any', '2.7')):
            raw = ('name: example\nenvironment:\n  sdk: ' + constraint + '\n').encode()
            self.assertEqual(D['pubspec_language'](raw), expected)
        self.assertEqual(D['pubspec_language'](b'name: example\n'), '2.7')

    def test_pub_language_unknown_or_complex_constraints_fail_closed(self):
        for raw in (b'environment: {sdk: ^3.0.0}\n',
                    b'environment:\n  sdk: ">=3.0.0 || >=2.12.0"\n',
                    b'environment:\n  sdk: &constraint ^3.0.0\n',
                    b'environment:\n  sdk: ^3.0.0\n  sdk: ^3.1.0\n'):
            with self.assertRaises(ValueError):
                D['pubspec_language'](raw)

    def test_tool_generated_config_physical_overlay_logical_sdk_roots(self):
        sdk, physical = self.root / 'sdk', self.root / 'tool-state'
        physical.mkdir(mode=0o700)
        logical_root = sdk / 'packages/flutter_tools'
        logical_root.mkdir(mode=0o700, parents=True)
        (logical_root / 'pubspec.yaml').write_text('name: flutter_tools\nenvironment:\n  sdk: ^3.8.0-0\n')
        package = self.root / 'cache/hosted/pub.dev/example-1.0.0'
        package.mkdir(mode=0o700, parents=True)
        (package / 'pubspec.yaml').write_text('name: example\nenvironment:\n  sdk: ^3.0.0\n')
        value = dict(configVersion=2, generator='pub', generatorVersion='3.10.4', packages=[
            dict(name='example', rootUri='file:///state/pub-cache/hosted/pub.dev/example-1.0.0',
                 packageUri='lib/', languageVersion='3.0'),
            dict(name='flutter_tools', rootUri='../', packageUri='lib/', languageVersion='3.8')])
        (physical / 'package_config.json').write_text(json.dumps(value))
        (physical / 'package_config.json').chmod(0o600)
        graph = dict(configVersion=1, roots=['flutter_tools'], packages=[
            dict(name='flutter_tools', version='0.0.0', dependencies=['example'], devDependencies=[]),
            dict(name='example', version='1.0.0', dependencies=[])])
        (physical / 'package_graph.json').write_text(json.dumps(graph))
        (physical / 'package_graph.json').chmod(0o600)
        result = D['generated_binding'](logical_root, sdk, self.root / 'cache',
            dict(example=dict(source='hosted', version='1.0.0')), config_directory=physical, root_name='flutter_tools')
        self.assertTrue(result['exact_authorized_roots'])
        graph['packages'][1]['version'] = '2.0.0'
        (physical / 'package_graph.json').write_text(json.dumps(graph))
        with self.assertRaisesRegex(ValueError, 'P15_PACKAGE_GRAPH_VERSION'):
            D['generated_binding'](logical_root, sdk, self.root / 'cache',
                dict(example=dict(source='hosted', version='1.0.0')), config_directory=physical, root_name='flutter_tools')

    def tool_state_fixture(self):
        state = self.root / 'closed-tool-state'
        state.mkdir(mode=0o700)
        for name in ('package_config.json', 'package_graph.json'):
            path = state / name
            path.write_text('{}')
            path.chmod(0o600)
        return state

    def test_tool_state_requires_both_original_generated_files(self):
        state = self.tool_state_fixture()
        D['tool_state_files'](state)
        (state / 'package_graph.json').unlink()
        with self.assertRaisesRegex(ValueError, 'P15_TOOL_STATE_FILE_SET'):
            D['tool_state_files'](state)

    def test_tool_state_extra_source_or_workspace_redirect_rejected(self):
        state = self.tool_state_fixture()
        for name in ('extra.dart', 'pub/workspace_ref.json'):
            path = state / name
            path.parent.mkdir(mode=0o700, exist_ok=True)
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'P15_TOOL_STATE_FILE_SET'):
                D['tool_state_files'](state)
            path.unlink()
            if path.parent != state:
                path.parent.rmdir()

    def test_tool_state_alias_or_public_metadata_rejected(self):
        state = self.tool_state_fixture()
        graph = state / 'package_graph.json'
        graph.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'P15_TOOL_STATE_FILE_METADATA'):
            D['tool_state_files'](state)
        graph.unlink()
        graph.symlink_to(state / 'package_config.json')
        with self.assertRaisesRegex(ValueError, 'P15_TOOL_STATE_FILE_METADATA'):
            D['tool_state_files'](state)

    def plugin_fixture(self):
        stage, cache = self.root / 'plugin-stage', self.root / 'plugin-cache'
        stage.mkdir(mode=0o700)
        source = cache / 'hosted/pub.dev/example-1.0.0'
        source.mkdir(parents=True, mode=0o700)
        (source / 'pubspec.yaml').write_text('name: example\nflutter:\n  plugin:\n    platforms:\n      web:\n        pluginClass: Example\n')
        value = dict(info='This is a generated file; do not edit or check into version control.',
            version='3.38.5', date_created='2026-10-28', swift_package_manager_enabled=dict(ios=False, macos=False),
            plugins={platform: [] for platform in ('ios', 'android', 'macos', 'linux', 'windows', 'web')},
            dependencyGraph=[dict(name='example', dependencies=[])])
        value['plugins']['web'].append(dict(name='example', path='/state/pub-cache/hosted/pub.dev/example-1.0.0/',
                                           dependencies=[], dev_dependency=False))
        (stage / '.flutter-plugins-dependencies').write_text(json.dumps(value))
        return stage, cache, value

    def test_plugin_original_source_platform_and_roots(self):
        stage, cache, value = self.plugin_fixture()
        result = D['plugin_binding'](stage, cache, dict(example=dict(source='hosted', version='1.0.0')))
        self.assertEqual(result['platform_entries'], 1)
        value['plugins']['web'][0]['path'] = '/state/pub-cache/hosted/pub.dev/example-2.0.0/'
        (stage / '.flutter-plugins-dependencies').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_ROOT'):
            D['plugin_binding'](stage, cache, dict(example=dict(source='hosted', version='1.0.0')))

    def test_plugin_unsupported_platform_rejected(self):
        stage, cache, value = self.plugin_fixture()
        value['plugins']['linux'] = value['plugins']['web']
        value['plugins']['web'] = []
        (stage / '.flutter-plugins-dependencies').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_PLATFORM_SOURCE'):
            D['plugin_binding'](stage, cache, dict(example=dict(source='hosted', version='1.0.0')))

    def test_unknown_pub_metadata_rejected(self):
        hosted = self.root / 'hosted'
        (hosted / '.cache').mkdir(parents=True, mode=0o700)
        (hosted / '.cache/foreign-versions.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'P15_UNKNOWN_PUB_METADATA'):
            D['cache_metadata'](hosted, dict(example=dict(source='hosted', version='1.0.0')))

    def test_active_root_derived_name_and_value(self):
        cache, sdk, stage = self.root / 'cache', self.root / 'sdk', self.root / 'stage'
        uri = (stage / '.dart_tool/package_config.json').as_uri()
        checksum = hashlib.sha256(uri.encode()).hexdigest()
        directory = cache / 'active_roots' / checksum[:2]
        directory.mkdir(mode=0o700, parents=True)
        (cache / 'active_roots').chmod(0o700)
        path = directory / checksum[2:]
        path.write_text(json.dumps(dict(package_config=uri)))
        self.assertEqual(D['active_roots'](cache, sdk, stage), 1)
        path.write_text(json.dumps(dict(package_config='file:///foreign')))
        with self.assertRaisesRegex(ValueError, 'P15_ACTIVE_ROOT_CHANGED'):
            D['active_roots'](cache, sdk, stage)


if __name__ == '__main__':
    unittest.main()
