# SPDX-License-Identifier: GPL-3.0-only
"""Inert complete-closure validation; no SDK or generated code is executed."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
V = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_pub_outputs.py'))
G = V['validate'].__globals__
M = SimpleNamespace(**runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_pub_metadata.py')))
S = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_sources.py'))


def row(raw, mode=0o600):
    return dict(bytes=len(raw), sha256=V['sha'](raw), mode=mode)


def normalized(raw, roots):
    value, counts = raw, {}
    for name in sorted(roots, key=lambda name: (-len(roots[name].encode()), name)):
        raw_root = roots[name].encode()
        counts[name] = value.count(raw_root)
        value = value.replace(raw_root, ('@P15_' + name.upper() + '_ROOT@').encode())
    return dict(normalized_sha256=V['sha'](value), root_occurrences=counts)


class PrivateInventory:
    """Mock only the separately tested descriptor-bound byte-reader boundary."""
    def __init__(self, raw, roots):
        self.raw, self.roots, self.stage, self.calls = raw, roots, roots['app'], []

    def contents(self, snapshot, names):
        self.calls.append(('contents', tuple(names)))
        return {name: self.raw[name] for name in names}

    def normalized(self, snapshot, names, roots):
        self.calls.append(('normalized', tuple(names)))
        return {name: dict(normalized(self.raw[name], roots), bytes=len(self.raw[name]),
                           sha256=V['sha'](self.raw[name])) for name in names}


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.roots = dict(app='/inert/app', sdk='/inert/sdk')
        self.sdk = dict(manifest=V['canonical'](dict(engineRevision='b' * 40)), target=b'// original SDK target\n')
        self.raw = {name: ('// generated ' + name + '\n').encode() for name in V['GENERATED']}
        self.raw['android/local.properties'] = b'flutter.sdk=/inert/sdk'
        self.raw['ios/Flutter/Generated.xcconfig'] = b'APP=/inert/app\nSDK=/inert/sdk\n'
        self.raw[V['MANIFEST']] = V['canonical'](dict(
            info='This is a generated file; do not edit or check into version control.',
            version='3.38.5', plugins={platform: [] for platform in ('ios', 'android', 'macos', 'linux', 'windows', 'web')},
            dependencyGraph=[], date_created='2026-10-28 12:13:14.123456',
            swift_package_manager_enabled=dict(ios=False, macos=False)))
        original_generated = set(V['L10N_OUTPUTS']) | {name for name in V['GENERATED']
            if name.startswith(('linux/', 'windows/')) or name == 'macos/Flutter/GeneratedPluginRegistrant.swift'}
        original = original_generated | set(V['ARBS']) | {'l10n.yaml'}
        original.update('lib/original_%03d.dart' % number for number in range(386 - len(original)))
        for name in original - original_generated:
            self.raw[name] = ('original ' + name + '\n').encode()
        self.before = dict(files={name: row(self.raw[name]) for name in original},
                           directories={name: dict(mode=0o700) for name in V['parents'](original)},
                           aliases={}, unsafe={})
        before_sha = V['sha'](V['canonical']({name: item['sha256'] for name, item in self.before['files'].items()}))
        self.override = patch.dict(G, BEFORE_SHA=before_sha, SDK_MANIFEST_SHA=V['sha'](self.sdk['manifest']),
                                   SDK_TARGET_SHA=V['sha'](self.sdk['target']))
        self.override.start()
        self.addCleanup(self.override.stop)
        self.raw.update({name: b'{}' for name in V['DART_TOOL']})
        self.raw['.dart_tool/version'] = b'3.38.5'
        self.raw[V['DARTPAD']] = b'// original pinned Dartpad registrant\n'
        self.build_id = V['md5'](('b' * 40 + 'build').encode())
        self.metadata = {'build/' + self.build_id + '/' + leaf for leaf in V['METADATA_LEAVES']} | {'build/.last_build_id'}
        self.make_metadata()
        self.policy = dict(schema=1, kind='p15f-controlled-pub-output-authorization', before_files_sha256=before_sha,
            producer_catalogue_sha256=V['PRODUCERS_SHA'], metadata_catalogue_sha256=V['METADATA_CATALOGUE_SHA'],
            sdk_inventory_sha256=V['SDK_INVENTORY_SHA'], generated_sources={
                name: dict(mode=0o600, role='plugin_manifest') if name == V['MANIFEST'] else
                dict(mode=0o600, role='normalized', **normalized(self.raw[name], self.roots))
                for name in V['GENERATED']},
            dart_tool={name: dict(role=role, mode=0o600, **({'sha256': V['sha'](self.raw[name])}
                       if name == V['DARTPAD'] else {})) for name, role in V['DART_TOOL'].items()},
            metadata_paths={name: 0o600 for name in V['METADATA_PATHS']})
        self.snapshot = dict(files={name: row(raw) for name, raw in self.raw.items()},
            directories={name: dict(mode=0o700) for name in V['parents'](set(self.raw) | V['ALIASES'])},
            aliases={name: dict(type='symlink', mode=0o777, bytes=12, sha256=V['sha'](b'pinned target'))
                     for name in V['ALIASES']}, unsafe={})
        self.inventory = PrivateInventory(self.raw, self.roots)

    def make_metadata(self):
        app, sdk = self.roots['app'], self.roots['sdk']
        outputs = [app + '/' + name for name in M.OUTPUTS]
        arbs = [app + '/' + name for name in M.ARBS]
        dep_inputs = [app + '/l10n.yaml', *arbs]
        inputs = [sdk + M.SDK_TARGET, *dep_inputs]
        checksum = {app + '/' + name: M.cache_hash(self.raw[name]) for name in set(M.ARBS) | set(M.OUTPUTS) | {'l10n.yaml'}}
        checksum[sdk + M.SDK_TARGET] = M.cache_hash(self.sdk['target'])
        prefix = 'build/' + self.build_id + '/'
        self.raw[prefix + 'gen_l10n_inputs_and_outputs.json'] = V['canonical'](dict(inputs=arbs, outputs=outputs))
        self.raw[prefix + 'gen_localizations.stamp'] = V['canonical'](dict(inputs=inputs, outputs=outputs))
        self.raw[prefix + 'outputs.json'] = V['canonical'](outputs)
        self.raw[prefix + '.filecache'] = V['canonical'](dict(version=2,
            files=[dict(path=name, hash=digest) for name, digest in sorted(checksum.items())]))
        self.raw[prefix + 'gen_localizations.d'] = (''.join(' ' + M.escape(name) for name in outputs)
            + ': ' + ''.join(' ' + M.escape(name) for name in dep_inputs)).encode()
        self.raw['build/.last_build_id'] = self.build_id.encode()

    def validate(self):
        return V['validate'](self.inventory, self.snapshot, self.before, self.policy, self.roots, M, self.sdk)

    def change(self, name, raw):
        self.raw[name] = raw
        self.snapshot['files'][name] = row(raw, self.snapshot['files'][name]['mode'])

    def test_complete_first_pub_closure_uses_only_private_bound_reads(self):
        result = self.validate()
        self.assertEqual((result['source_files'], result['generated_sources'], result['dart_tool_files'],
                          result['metadata_files']), (407, 53, 4, 6))
        self.assertFalse(result['admitted'])
        self.assertTrue(result['existing_dependency_and_plugin_binders_required'])
        self.assertEqual(result['metadata']['cache_entries'], 73)
        self.assertEqual(len(self.inventory.calls[0][1]), 52)
        self.assertLessEqual(len(self.inventory.calls[1][1]), 96)
        rendered = json.dumps(result)
        self.assertNotIn('/inert/', rendered)
        self.assertNotIn(self.build_id, rendered)

    def test_cache_padding_collision_cannot_authorize_changed_original_source(self):
        name = 'lib/l10n/app_fr.arb'
        original = b'x' * 63
        changed = original[:-7] + b'y' * 7
        self.assertEqual(M.cache_hash(original), M.cache_hash(changed))
        self.assertNotEqual(V['sha'](original), V['sha'](changed))
        self.raw[name] = original
        self.before['files'][name] = row(original)
        self.snapshot['files'][name] = row(original)
        checksum = V['sha'](V['canonical']({n: r['sha256'] for n, r in self.before['files'].items()}))
        self.policy['before_files_sha256'] = checksum
        with patch.dict(G, BEFORE_SHA=checksum):
            self.make_metadata()
            self.snapshot['files'].update({n: row(raw) for n, raw in self.raw.items()})
            self.validate()
            self.raw[name] = changed
            self.snapshot['files'][name] = row(changed)
            # Even self-consistent cache bookkeeping must not replace SHA256.
            self.make_metadata()
            self.snapshot['files'].update({n: row(raw) for n, raw in self.raw.items()})
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_ORIGINAL_CHANGED'):
                self.validate()

    def test_unknown_missing_and_fixture_outputs_are_rejected_before_reads(self):
        for name in ('unknown.dart', 'build/private/extra', 'test/volparossa/fixtures/products.json'):
            self.snapshot['files'][name] = row(b'extra')
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_FILE_CLOSURE'):
                self.validate()
            del self.snapshot['files'][name]
        removed = self.snapshot['files'].pop('.dart_tool/version')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_FILE_CLOSURE'):
            self.validate()
        self.snapshot['files']['.dart_tool/version'] = removed
        self.assertEqual(self.inventory.calls, [])

    def test_unsafe_alias_and_empty_directory_changes_fail_closed(self):
        self.snapshot['unsafe']['unknown-link'] = dict(type='symlink')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_FILE_CLOSURE'):
            self.validate()
        self.snapshot['unsafe'].clear()
        self.snapshot['aliases']['linux/flutter/ephemeral/.plugin_symlinks/unknown'] = dict(type='symlink')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_ALIAS_CLOSURE'):
            self.validate()
        del self.snapshot['aliases']['linux/flutter/ephemeral/.plugin_symlinks/unknown']
        self.snapshot['directories']['build/unknown-empty'] = dict(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_DIRECTORY_CLOSURE'):
            self.validate()

    def test_all_original_sources_including_regenerated_files_remain_exact(self):
        for name in ('l10n.yaml', next(iter(V['L10N_OUTPUTS']))):
            previous = self.snapshot['files'][name]
            self.snapshot['files'][name] = row(b'changed original')
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_ORIGINAL_CHANGED'):
                self.validate()
            self.snapshot['files'][name] = previous
        name = next(iter(self.before['directories']))
        self.snapshot['directories'][name] = dict(mode=0o755)
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_ORIGINAL_DIRECTORY'):
            self.validate()

    def test_normalized_content_counts_and_modes_are_exact(self):
        name = 'android/local.properties'
        self.change(name, b'flutter.sdk=/inert/sdk/unauthorized')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_GENERATED_CHANGED'):
            self.validate()
        self.change(name, b'flutter.sdk=/inert/sdk')
        self.policy['generated_sources'][name]['root_occurrences']['sdk'] += 1
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_GENERATED_CHANGED'):
            self.validate()
        self.policy['generated_sources'][name]['root_occurrences']['sdk'] -= 1
        self.snapshot['files'][name]['mode'] = 0o755
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_MODE'):
            self.validate()

    def test_plugin_date_is_closed_scalar_and_spm_remains_false(self):
        original = json.loads(self.raw[V['MANIFEST']])
        for date in ('2026-10-28 12:13:14.123', '2026-10-28 12:13:14.123456'):
            value = dict(original, date_created=date)
            self.change(V['MANIFEST'], V['canonical'](value))
            self.validate()
        for date in ('2026-99-99 12:13:14.123', '2026-10-28T12:13:14.123',
                     '2026-10-28 12:13:14.123Z', '$(execute)', '2026-10-28 12:13:14.123\n'):
            self.change(V['MANIFEST'], V['canonical'](dict(original, date_created=date)))
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_PLUGIN_DATE'):
                self.validate()
        self.change(V['MANIFEST'], V['canonical'](dict(original, swift_package_manager_enabled=dict(ios=True, macos=False))))
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_SPM'):
            self.validate()

    def test_tool_version_and_dartpad_are_fixed(self):
        self.change('.dart_tool/version', b'3.38.5\n')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_TOOL_CONTENT'):
            self.validate()
        self.change('.dart_tool/version', b'3.38.5')
        self.change(V['DARTPAD'], b'changed Dartpad')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_TOOL_CONTENT'):
            self.validate()

    def test_metadata_semantics_and_actual_input_md5_are_checked(self):
        name = 'build/' + self.build_id + '/outputs.json'
        self.change(name, b'[]')
        with self.assertRaisesRegex(ValueError, 'P15_PUB_METADATA_MEMBERS'):
            self.validate()
        self.make_metadata()
        name = 'build/' + self.build_id + '/.filecache'
        value = json.loads(self.raw[name])
        value['files'][0]['hash'] = '0' * 32
        self.change(name, V['canonical'](value))
        with self.assertRaisesRegex(ValueError, 'P15_PUB_METADATA_CACHE_HASH'):
            self.validate()

    def test_sdk_manifest_target_and_baseline_are_bound(self):
        for name in ('manifest', 'target'):
            original = self.sdk[name]
            self.sdk[name] += b'changed'
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_SDK_METADATA'):
                self.validate()
            self.sdk[name] = original
        self.before['files']['l10n.yaml']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_BASELINE'):
            self.validate()

    def test_policy_cannot_authorize_unknown_names_roles_modes_or_pins(self):
        original = copy.deepcopy(self.policy)
        mutations = [lambda p: p.update(producer_catalogue_sha256='0' * 64),
                     lambda p: p['generated_sources'].update({'unknown.dart': dict(role='normalized', mode=0o600)}),
                     lambda p: p['generated_sources']['android/local.properties'].update(mode=0o666),
                     lambda p: p['generated_sources']['android/local.properties'].update(role='anything'),
                     lambda p: p['dart_tool']['.dart_tool/version'].update(role='anything'),
                     lambda p: p['metadata_paths'].update({'build/unknown': 0o600})]
        for mutate in mutations:
            self.policy = copy.deepcopy(original)
            mutate(self.policy)
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_'):
                self.validate()

    def test_real_inventory_rejects_postsnapshot_byte_and_directory_replacement(self):
        temporary = tempfile.TemporaryDirectory(prefix='p15f-output-inert-')
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        stage = base / 'stage'
        stage.mkdir(mode=0o700)
        def put(name, raw):
            path = stage / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        for name in self.before['files']:
            put(name, self.raw[name])
        descriptors = len(os.listdir('/proc/self/fd'))
        with S['Inventory'](str(stage)) as inventory:
            before = inventory.capture()
            self.roots['app'] = str(stage)
            self.raw['ios/Flutter/Generated.xcconfig'] = ('APP=' + str(stage) + '\nSDK=/inert/sdk\n').encode()
            self.make_metadata()
            for name, raw in self.raw.items():
                put(name, raw)
            for name in V['ALIASES']:
                path = stage / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.symlink_to('/state/pub-cache/authorized-test-target/')
            class BoundAliases:
                def check_leaf(self, name, info):
                    if name not in V['ALIASES']:
                        raise ValueError('unexpected alias')
            aliases = BoundAliases()
            snapshot = inventory.capture(aliases)
            self.assertEqual(V['validate'](inventory, snapshot, before, self.policy, self.roots, M, self.sdk)['source_files'], 407)
            count = len(os.listdir('/proc/self/fd'))
            put('android/local.properties', b'flutter.sdk=/inert/sdy')
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_CHANGED'):
                V['validate'](inventory, snapshot, before, self.policy, self.roots, M, self.sdk)
            put('android/local.properties', self.raw['android/local.properties'])
            put('unknown.dart', b'unknown')
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_FILE_CLOSURE'):
                V['validate'](inventory, inventory.capture(aliases), before, self.policy, self.roots, M, self.sdk)
            (stage / 'unknown.dart').unlink()
            (stage / 'unknown-empty-directory').mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'P15_PUB_OUTPUT_DIRECTORY_CLOSURE'):
                V['validate'](inventory, inventory.capture(aliases), before, self.policy, self.roots, M, self.sdk)
            (stage / 'unknown-empty-directory').rmdir()
            # That observed new directory is pinned, so account for its one FD.
            count += 1
            (stage / 'lib').rename(base / 'old-lib')
            shutil.copytree(base / 'old-lib', stage / 'lib')
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIRECTORY_SWAP'):
                V['validate'](inventory, snapshot, before, self.policy, self.roots, M, self.sdk)
            self.assertEqual(len(os.listdir('/proc/self/fd')), count)
        self.assertEqual(len(os.listdir('/proc/self/fd')), descriptors)


class PinTests(unittest.TestCase):
    def test_production_pins_and_actual_policy_shape(self):
        self.assertEqual(V['BEFORE_SHA'], '94a0f9632f425453887f41b8b3e9926e3d4c3516f3fd4ce3d8db1540d7e48baf')
        self.assertEqual(V['SDK_MANIFEST_SHA'], 'd7a750731cead19d1c5f931a5ca0a3a4dee1fb3829f3713465abd478b405537c')
        self.assertEqual(V['SDK_TARGET_SHA'], '2f8145786bbc9ce7f14a647cc40a407be87f5f3b596bd77a0f16f5233626c430')
        self.assertEqual((len(V['GENERATED']), len(V['ARBS']), len(V['L10N_OUTPUTS']), len(V['ALIASES'])), (53, 36, 35, 16))
        policy_path = ROOT / 'third_party/overmorrow-pub-outputs-v1.json'
        if policy_path.exists():
            V['policy_contract'](json.loads(policy_path.read_bytes()))


if __name__ == '__main__':
    unittest.main()
