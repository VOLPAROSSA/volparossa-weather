# SPDX-License-Identifier: GPL-3.0-only
"""Inert exact-hook and generated-protocol guards; no Dart/Flutter execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
W = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_hooks.py'))
I = W['I']
G = W['load_record'].__globals__


class HookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.stage, self.sdk, self.cache = (self.base / name for name in ('stage', 'sdk', 'cache'))
        for path in (self.stage, self.sdk, self.cache):
            path.mkdir(mode=0o700)
        self.pubspec = b'name: overmorrow\nversion: 2.6.4+64\nenvironment:\n  sdk: ">=3.0.6 <4.0.0"\n'
        self.write(self.stage/'pubspec.yaml', self.pubspec)
        self.run = W['HookRun'](self.stage, self.sdk, self.cache, I.sha(self.pubspec))

    def write(self, path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(value if type(value) is bytes else I.canonical(value))
        path.chmod(0o600)
        return path

    def task(self, action):
        key = W['checksum'](W['CONFIGS'][action])
        root = self.run.root
        task = root / W['PACKAGE'] / key
        (task/'out').mkdir(mode=0o700, parents=True)
        shared_owner = root / 'shared' / W['PACKAGE']
        shared = shared_owner / 'build'
        (shared/key[:10]).mkdir(mode=0o700, parents=True)
        self.write(shared_owner/'.lock', b'private PID/time/path data')
        self.write(task/'.lock', b'private PID/time/path data')
        self.write(task/'hook.dill', b'inert kernel fixture, never executed')
        self.write(task/'hook.dill.d', b'inert depfile fixture')
        self.write(task/'stdout.txt', b'Running `private command/env/cwd`.\n')
        self.write(task/'stderr.txt', b'')
        value = dict(config=copy.deepcopy(W['CONFIGS'][action]), out_dir_shared=str(shared)+'/',
            out_file=str(task/'output.json'), package_name=W['PACKAGE'],
            package_root='/state/pub-cache/hosted/pub.dev/objective_c-9.5.0/', assets={})
        self.write(task/'input.json', value)
        self.write(task/'output.json', dict(assets_for_linking={}, status='success', timestamp='2026-10-28 12:00:00.000'))
        self.write(task/'hook.dependencies_hash_file.json', dict(file_system=[
            dict(path=str(self.stage/'.dart_tool/package_config.json'), hash=2**64-1),
            dict(path=str(self.sdk/'bin/cache/dart-sdk/version'), hash=1)], environment=[]))
        self.write(task/'dependencies.dependencies_hash_file.json', dict(file_system=[],
            environment=[dict(key='HOME', hash=1), dict(key='PATH', hash=2**64-1)]))
        if action == 'test':
            self.write(self.stage/'build/native_assets/linux/native_assets.json',
                       {'format-version': [1, 0, 0], 'native-assets': {}})
        return task

    def synthetic_inventory(self):
        record = copy.deepcopy(W['load_record']())
        files = {W['ENTRY']:dict(type='file', bytes=7018, sha256=W['HOOK_SHA'], executable=False)}
        record['archives'][W['ARCHIVE_SHA']]['membermap_sha256'] = I.sha(I.canonical(files))
        return record, files

    def test_exact_original_record_closure_and_first_rejection(self):
        record = W['load_record']()
        self.assertEqual(len(record['archives']), 224)
        owners = [v for v in record['archives'].values() if v['automatic_hooks']]
        self.assertEqual([(v['package'],v['version'],v['automatic_hooks']) for v in owners],
                         [('objective_c','9.5.0',['hook/build.dart'])])
        self.assertEqual(record['review']['legacy_first_rejection']['prepare_order_zero_based_index'],164)

    def test_fixed_hook_is_authorized_only_with_its_complete_membermap(self):
        record, files = self.synthetic_inventory()
        with patch.dict(G, load_record=lambda:record):
            value = W['authorize_inventory'](W['ARCHIVE_SHA'], files)
            self.assertEqual(value['automatic_hook_count'],1)
            self.assertEqual(set(value['authorized_profiles']),set(W['PROFILES'].values()))
            files[W['ENTRY']]['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'P15_HOOK_MEMBERMAP_CHANGED'):
                W['authorize_inventory'](W['ARCHIVE_SHA'],files)

    def test_unknown_archive_never_receives_hook_authority(self):
        with self.assertRaisesRegex(ValueError,'P15_HOOK_ARCHIVE_UNKNOWN'):
            W['authorize_inventory']('0'*64,{})

    def test_even_a_self_consistent_unknown_hook_is_rejected(self):
        record, files = self.synthetic_inventory()
        files['hook/link.dart']=files[W['ENTRY']].copy()
        record['archives'][W['ARCHIVE_SHA']]['membermap_sha256']=I.sha(I.canonical(files))
        with patch.dict(G,load_record=lambda:record), self.assertRaisesRegex(ValueError,'P15_UNREVIEWED_PACKAGE_HOOK'):
            W['authorize_inventory'](W['ARCHIVE_SHA'],files)

    def test_hook_source_hash_cannot_be_substituted_by_changing_map_authority(self):
        record, files = self.synthetic_inventory()
        files[W['ENTRY']]['sha256']='0'*64
        record['archives'][W['ARCHIVE_SHA']]['membermap_sha256']=I.sha(I.canonical(files))
        with patch.dict(G,load_record=lambda:record), self.assertRaisesRegex(ValueError,'P15_HOOK_SOURCE_CHANGED'):
            W['authorize_inventory'](W['ARCHIVE_SHA'],files)

    def test_profile_binds_original_commands_and_purged_environment(self):
        original=W['module']('prepare_hosted_overmorrow_ci');original.SDK=self.sdk
        for action in ('test','build'):
            args=original.flutter_command(action)+(['--no-tree-shake-icons'] if action=='build' else [])
            env=original.environment()
            self.assertEqual(W['authorize_profile'](action,self.sdk,args,env),W['PROFILES'][action])
            with self.assertRaisesRegex(ValueError,'P15_HOOK_TARGET_OVERRIDE'):
                W['authorize_profile'](action,self.sdk,args+['--target-platform=darwin'],env)
            with self.assertRaisesRegex(ValueError,'P15_HOOK_TARGET_OVERRIDE'):
                W['authorize_profile'](action,self.sdk,args,dict(env,DART_VM_OPTIONS='untrusted'))
        with self.assertRaisesRegex(ValueError,'P15_HOOK_PROFILE_REQUIRED'):
            W['authorize_profile']('android',self.sdk,[],{})

    def test_freshness_and_root_user_defines_are_preventive(self):
        self.run.root.mkdir(mode=0o700,parents=True)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_STATE_NOT_FRESH'):
            W['HookRun'](self.stage,self.sdk,self.cache,I.sha(self.pubspec))
        self.run.root.rmdir()
        changed=self.pubspec+b'  hooks:\n    user_defines: {}\n'
        self.write(self.stage/'pubspec.yaml',changed)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_ROOT_DEFINES'):
            W['HookRun'](self.stage,self.sdk,self.cache,I.sha(changed))

    def test_two_distinct_noop_profiles_validate_without_public_private_data(self):
        self.task('test'); first=self.run.after('test')
        self.assertEqual(first['tasks'],1)
        self.task('build'); final=self.run.after('build')
        self.assertEqual(final['tasks'],2)
        raw=json.dumps(final)
        self.assertNotIn(str(self.base),raw)
        self.assertNotIn('private command',raw)
        self.assertFalse(final['private_contents_exported'])
        self.assertEqual(final['native_asset_count'],0)

    def test_unknown_owner_or_task_cannot_be_admitted(self):
        self.task('test');(self.run.root/'unknown').mkdir()
        with self.assertRaises(ValueError):self.run.after('test')

    def test_native_outputs_even_if_unlisted_in_json_fail_closed(self):
        task=self.task('test');self.write(task/'out/native.so',b'unapproved')
        with self.assertRaisesRegex(ValueError,'P15_HOOK_NATIVE_OUTPUT'):self.run.after('test')

    def test_unknown_retained_task_file_fails_closed(self):
        task=self.task('test');self.write(task/'extra.dart',b'unapproved')
        with self.assertRaises(ValueError):self.run.after('test')

    def test_symlink_and_hardlink_task_state_are_rejected(self):
        task=self.task('test');p=task/'output.json';raw=p.read_bytes();p.unlink()
        external=self.write(self.base/'outside.json',raw);p.symlink_to(external)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_FILE'):self.run.after('test')
        p.unlink();os.link(external,p)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_FILE'):self.run.after('test')

    def test_wrong_native_target_and_user_defines_are_rejected(self):
        task=self.task('test');value=json.loads((task/'input.json').read_text())
        value['config']['extensions']['code_assets']['target_os']='macos'
        self.write(task/'input.json',value)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_PROTOCOL_INPUT'):self.run.after('test')
        value['config']=W['CONFIGS']['test'];value['user_defines']={}
        self.write(task/'input.json',value)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_PROTOCOL_INPUT'):self.run.after('test')

    def test_boolean_field_cannot_be_replaced_with_equal_integer(self):
        task=self.task('test');value=json.loads((task/'input.json').read_text())
        value['config']['linking_enabled']=0
        self.write(task/'input.json',value)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_PROTOCOL_INPUT'):self.run.after('test')

    def test_input_paths_are_never_followed_or_normalized_into_permission(self):
        task=self.task('test');value=json.loads((task/'input.json').read_text())
        value['out_file']=str(task/'../output.json')
        self.write(task/'input.json',value)
        with self.assertRaisesRegex(ValueError,'P15_HOOK_PROTOCOL_INPUT'):self.run.after('test')

    def test_link_assets_failure_and_extra_output_fields_are_rejected(self):
        task=self.task('test');value=json.loads((task/'output.json').read_text())
        for changed in (dict(value,assets_for_linking={'unknown':[]}),dict(value,status='failure'),dict(value,assets=[])):
            self.write(task/'output.json',changed)
            with self.assertRaisesRegex(ValueError,'P15_HOOK_PROTOCOL_OUTPUT'):self.run.after('test')

    def test_nonempty_native_asset_manifest_is_rejected(self):
        self.task('test');self.write(self.stage/'build/native_assets/linux/native_assets.json',
            {'format-version':[1,0,0],'native-assets':{'linux_x64':{'unapproved':'asset'}}})
        with self.assertRaisesRegex(ValueError,'P15_HOOK_NATIVE_ASSET_MANIFEST'):self.run.after('test')

    def test_stamp_external_paths_and_unknown_environment_are_rejected(self):
        task=self.task('test')
        self.write(task/'hook.dependencies_hash_file.json',dict(file_system=[dict(path='/etc/passwd',hash=1)],environment=[]))
        with self.assertRaisesRegex(ValueError,'P15_HOOK_STAMP_PATH'):self.run.after('test')

    def test_resource_bound_stops_before_late_directory_entries(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        seen=[]
        @contextmanager
        def scan(path):
            def generate():
                for index in range(100):
                    seen.append(index);yield SimpleNamespace(path=str(path/index.__str__()))
            yield generate()
        with patch.object(W['os'],'scandir',scan),self.assertRaisesRegex(ValueError,'P15_HOOK_ENTRY_BOUND'):
            W['children'](self.base,2)
        self.assertEqual(seen,[0,1,2])


if __name__=='__main__':
    unittest.main()
