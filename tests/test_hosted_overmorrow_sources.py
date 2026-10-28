# SPDX-License-Identifier: GPL-3.0-only
"""Inert source observations: descriptor races, complete deltas and redaction."""
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
S = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_sources.py'))
G = S['Inventory'].capture.__globals__


def put(path, raw=b'original\n'):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def descriptors():
    return len(os.listdir('/proc/self/fd'))


class InventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='p15f-source-inert-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.stage = self.base / 'stage'
        self.stage.mkdir(mode=0o700)
        put(self.stage / 'pubspec.yaml')
        put(self.stage / 'lib/main.dart', b'const original = true;\n')
        self.inventory = S['Inventory'](str(self.stage))
        self.addCleanup(self.inventory.close)

    def test_repeat_capture_and_sha_map(self):
        before = self.inventory.capture()
        self.assertEqual(self.inventory.capture(), before)
        self.assertEqual(S['files'](before), {
            'pubspec.yaml': S['sha'](b'original\n'),
            'lib/main.dart': S['sha'](b'const original = true;\n')})
        self.assertEqual(S['delta'](before, before), dict(added=[], changed=[], missing=[]))

    def test_all_unknowns_original_mutation_and_missing_are_collected(self):
        before = self.inventory.capture()
        put(self.stage / 'lib/main.dart', b'changed')
        (self.stage / 'pubspec.yaml').unlink()
        for index in range(37):
            put(self.stage / ('unknown-%02d' % index))
        after = self.inventory.capture()
        delta = S['delta'](before, after)
        self.assertEqual([row['path'] for row in delta['added']], ['unknown-%02d' % i for i in range(37)])
        self.assertEqual([row['path'] for row in delta['changed']], ['lib/main.dart'])
        self.assertEqual([row['path'] for row in delta['missing']], ['pubspec.yaml'])

    def test_empty_directories_and_type_changes_are_in_delta(self):
        (self.stage / 'new-empty').mkdir(mode=0o700)
        before = self.inventory.capture()
        (self.stage / 'new-empty').rmdir()
        put(self.stage / 'new-empty')
        delta = S['delta'](before, self.inventory.capture())
        self.assertEqual(delta['changed'][0]['before']['kind'], 'directories')
        self.assertEqual(delta['changed'][0]['after']['kind'], 'files')

    def test_root_git_is_excluded_but_nested_git_is_observed(self):
        put(self.stage / '.git/HEAD', b'ignored by this helper')
        put(self.stage / 'lib/.git/unknown', b'observed')
        snapshot = self.inventory.capture()
        self.assertFalse(any(name.startswith('.git') for group in S['KINDS'] for name in snapshot[group]))
        self.assertIn('lib/.git/unknown', snapshot['files'])

    def git_files(self):
        values = {'HEAD': b'ref: refs/heads/p15\n', 'config': b'[core]\n\trepositoryformatversion = 0\n'}
        for name, raw in values.items():
            put(self.stage / '.git' / name, raw)
        return values

    def test_git_binding_hashes_only_two_files_and_excludes_admin_tree(self):
        original = self.inventory.capture()
        values = self.git_files()
        put(self.stage / '.git/objects/private-admin-data', b'not source inventory')
        after = self.inventory.capture()
        self.assertEqual(S['files'](original), S['files'](after))
        self.assertEqual(original['directories'], after['directories'])
        self.assertEqual(self.inventory.git_binding(), {name: S['sha'](raw) for name, raw in values.items()})
        self.assertNotIn('ref:', json.dumps(self.inventory.git_binding()))

    def test_missing_git_is_allowed_for_capture_but_not_git_binding(self):
        self.inventory.capture()
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_MISSING'):
            self.inventory.git_binding()
        self.git_files()
        self.inventory.capture()
        (self.stage / '.git').rename(self.base / 'saved-admin')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_MISSING'):
            self.inventory.capture()

    def test_git_sibling_symlink_same_bytes_rejected_without_target_reads(self):
        self.git_files()
        self.inventory.capture()
        (self.stage / '.git').rename(self.base / 'sibling-admin')
        (self.stage / '.git').symlink_to(self.base / 'sibling-admin', target_is_directory=True)
        real_open = os.open
        def guarded(name, flags, *args, **kwargs):
            self.assertNotIn(name, ('.git', 'HEAD', 'config', str(self.base / 'sibling-admin')))
            return real_open(name, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=guarded):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_DIRECTORY'):
                self.inventory.capture()
            with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_DIRECTORY_TYPE'):
                self.inventory.git_binding()

    def test_git_admin_directory_clone_replacement_rejected(self):
        self.git_files()
        self.inventory.capture()
        (self.stage / '.git').rename(self.base / 'saved-admin')
        shutil.copytree(self.base / 'saved-admin', self.stage / '.git')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_SWAP'):
            self.inventory.capture()
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_SWAP'):
            self.inventory.git_binding()

    def test_git_leaf_symlinks_and_hardlinks_rejected_before_open(self):
        values = self.git_files()
        self.inventory.capture()
        real_open = os.open
        for name in ('HEAD', 'config'):
            for kind in ('symlink', 'hardlink'):
                path = self.stage / '.git' / name
                outside = self.base / ('outside-' + name + '-' + kind)
                put(outside, values[name])
                path.unlink()
                if kind == 'symlink':
                    path.symlink_to(outside)
                else:
                    os.link(outside, path)
                def guarded(open_name, flags, *args, **kwargs):
                    self.assertNotEqual(open_name, name)
                    self.assertNotEqual(open_name, str(outside))
                    return real_open(open_name, flags, *args, **kwargs)
                with patch.object(os, 'open', side_effect=guarded):
                    with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_FILE'):
                        self.inventory.git_binding()
                path.unlink()
                put(path, values[name])

    def test_git_leaf_size_and_write_permissions_rejected(self):
        self.git_files()
        self.inventory.capture()
        path = self.stage / '.git/HEAD'
        path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_FILE'):
            self.inventory.git_binding()
        put(path, b'x' * (S['MAX_GIT_FILE'] + 1))
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_FILE'):
            self.inventory.git_binding()

    def test_git_leaf_mutation_during_read_rejected_and_descriptors_closed(self):
        self.git_files()
        self.inventory.capture()
        count = descriptors()
        real_read = os.read
        changed = []
        def mutate(fd, size):
            raw = real_read(fd, size)
            if raw and not changed:
                changed.append(True)
                put(self.stage / '.git/HEAD', b'changed-head')
            return raw
        with patch.object(os, 'read', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_FILE_SWAP'):
                self.inventory.git_binding()
        self.assertEqual(descriptors(), count)

    def test_git_binding_success_and_admin_swap_do_not_leak_descriptors(self):
        count = descriptors()
        self.git_files()
        with S['Inventory'](str(self.stage)) as inventory:
            inventory.capture()
            captured = descriptors()
            for _ in range(12):
                inventory.git_binding()
            self.assertEqual(descriptors(), captured)
            (self.stage / '.git').rename(self.base / 'saved-admin')
            shutil.copytree(self.base / 'saved-admin', self.stage / '.git')
            for _ in range(12):
                with self.assertRaisesRegex(ValueError, 'P15_SOURCE_GIT_SWAP'):
                    inventory.git_binding()
            self.assertEqual(descriptors(), captured)
        self.assertEqual(descriptors(), count)

    def test_symlink_chain_and_fifo_are_unsafe_never_opened(self):
        (self.stage / 'first').symlink_to('second')
        (self.stage / 'second').symlink_to('/private/outside')
        os.mkfifo(self.stage / 'pipe', mode=0o600)
        real_open = os.open
        def guarded(name, flags, *args, **kwargs):
            self.assertNotEqual(name, 'pipe')
            self.assertNotIn(name, ('/private/outside',))
            if name in ('first', 'second'):
                self.assertTrue(flags & os.O_PATH)
                self.assertTrue(flags & os.O_NOFOLLOW)
            return real_open(name, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=guarded):
            snapshot = self.inventory.capture()
        self.assertEqual(set(snapshot['unsafe']), {'first', 'second', 'pipe'})
        self.assertEqual(snapshot['unsafe']['pipe']['type'], 'fifo')
        self.assertNotIn('target', json.dumps(snapshot))

    def test_same_length_symlink_target_change_is_observed_but_unsafe(self):
        path = self.stage / 'unknown-link'
        path.symlink_to('/private/first')
        before = self.inventory.capture()
        path.unlink()
        path.symlink_to('/private/other')
        after = self.inventory.capture()
        self.assertEqual(before['unsafe']['unknown-link']['bytes'], after['unsafe']['unknown-link']['bytes'])
        self.assertNotEqual(before['unsafe']['unknown-link']['sha256'], after['unsafe']['unknown-link']['sha256'])
        self.assertEqual([row['path'] for row in S['delta'](before, after)['changed']], ['unknown-link'])
        public = json.dumps(S['projection'](after, ()))
        self.assertNotIn('/private/first', public)
        self.assertNotIn('/private/other', public)

    def test_symlink_swap_during_readlink_is_rejected_and_descriptor_closed(self):
        path = self.stage / 'unknown-link'
        path.symlink_to('/private/first')
        self.inventory.capture()
        count = descriptors()
        real_readlink = os.readlink
        def replace(name, *args, **kwargs):
            self.assertEqual(name, '')
            raw = real_readlink(name, *args, **kwargs)
            path.unlink()
            path.symlink_to('/private/other')
            return raw
        with patch.object(os, 'readlink', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_LINK_SWAP'):
                self.inventory.capture()
        self.assertEqual(descriptors(), count)

    def test_successful_symlink_observations_do_not_leak_descriptors(self):
        (self.stage / 'unknown-link').symlink_to('/private/target')
        self.inventory.capture()
        count = descriptors()
        for _ in range(12):
            snapshot = self.inventory.capture()
            self.assertEqual(snapshot['unsafe']['unknown-link']['sha256'], S['sha'](b'/private/target'))
        self.assertEqual(descriptors(), count)

    def test_desktop_alias_requires_binding_and_exact_location(self):
        path = 'linux/flutter/ephemeral/.plugin_symlinks/sample'
        alias = self.stage / path
        alias.parent.mkdir(mode=0o700, parents=True)
        alias.symlink_to('/state/pub-cache/hosted/pub.dev/sample-1.0.0/')
        self.assertIn(path, self.inventory.capture()['unsafe'])
        seen = []
        class Binding:
            def check_leaf(self, name, info):
                seen.append(name)
                self_info = os.lstat(alias)
                if (info.st_ino, info.st_dev) != (self_info.st_ino, self_info.st_dev):
                    raise ValueError('bad binding')
        result = self.inventory.capture(Binding())
        self.assertEqual(seen, [path])
        self.assertIn(path, result['aliases'])
        self.assertEqual(result['aliases'][path]['sha256'], S['sha'](os.fsencode(os.readlink(alias))))
        self.assertFalse(result['unsafe'])

    def test_rejected_binding_is_not_converted_into_authorization(self):
        alias = self.stage / 'windows/flutter/ephemeral/.plugin_symlinks/sample'
        alias.parent.mkdir(mode=0o700, parents=True)
        alias.symlink_to('/outside')
        class Binding:
            def check_leaf(self, name, info):
                raise ValueError('P15_PLUGIN_LINK_SWAP')
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_LINK_SWAP'):
            self.inventory.capture(Binding())

    def test_directory_replacement_identical_contents_is_rejected(self):
        self.inventory.capture()
        (self.stage / 'lib').rename(self.stage / 'saved')
        shutil.copytree(self.stage / 'saved', self.stage / 'lib')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIRECTORY_SWAP'):
            self.inventory.capture()

    def test_disappeared_directory_identity_is_retained(self):
        self.inventory.capture()
        shutil.rmtree(self.stage / 'lib')
        self.inventory.capture()
        put(self.stage / 'lib/main.dart', b'const original = true;\n')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIRECTORY_SWAP'):
            self.inventory.capture()

    def test_root_replacement_identical_contents_is_rejected(self):
        self.inventory.capture()
        self.stage.rename(self.base / 'old-stage')
        shutil.copytree(self.base / 'old-stage', self.stage)
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_DIRECTORY_SWAP'):
            self.inventory.capture()

    def test_absolute_ancestor_replacement_is_rejected(self):
        self.inventory.capture()
        renamed = self.base.with_name(self.base.name + '-moved')
        self.base.rename(renamed)
        try:
            self.base.mkdir(mode=0o700)
            shutil.copytree(renamed / 'stage', self.stage)
            with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_DIRECTORY_SWAP'):
                self.inventory.capture()
        finally:
            shutil.rmtree(self.base)
            renamed.rename(self.base)

    def test_directory_symlink_substitution_is_rejected(self):
        self.inventory.capture()
        (self.stage / 'lib').rename(self.base / 'outside')
        (self.stage / 'lib').symlink_to(self.base / 'outside', target_is_directory=True)
        snapshot = self.inventory.capture()
        self.assertIn('lib', snapshot['unsafe'])
        self.assertNotIn('lib/main.dart', snapshot['files'])

    def test_world_writable_original_and_hardlink_are_rejected(self):
        path = self.stage / 'pubspec.yaml'
        path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_FILE_METADATA'):
            self.inventory.capture()
        path.chmod(0o600)
        os.link(path, self.base / 'hardlink')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_FILE_METADATA'):
            self.inventory.capture()

    def test_directory_write_permission_is_rejected(self):
        (self.stage / 'lib').chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_DIRECTORY_METADATA'):
            self.inventory.capture()

    def test_entry_and_depth_bounds(self):
        with patch.dict(G, MAX_ENTRIES=1):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_ENTRY_BOUND'):
                self.inventory.capture()
        with patch.dict(G, MAX_DEPTH=1):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DEPTH_BOUND'):
                self.inventory.capture()

    def test_file_and_total_byte_bounds(self):
        with patch.dict(G, MAX_FILE=3):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_FILE_METADATA'):
                self.inventory.capture()
        with patch.dict(G, MAX_TOTAL=3):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_BYTE_BOUND'):
                self.inventory.capture()

    def test_growing_file_read_is_bounded(self):
        reads = []
        def grow(fd, count):
            reads.append(count)
            return b'x' * count
        with patch.dict(G, MAX_FILE=32, MAX_TOTAL=128), patch.object(os, 'read', side_effect=grow):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_BYTE_BOUND'):
                self.inventory.capture()
        self.assertEqual(reads, [33])

    def test_file_replacement_during_read_is_rejected(self):
        real_read = os.read
        changed = []
        def replace(fd, count):
            raw = real_read(fd, count)
            if raw and not changed:
                changed.append(True)
                # Replace the inode corresponding to the held descriptor.
                for path in (self.stage / 'pubspec.yaml', self.stage / 'lib/main.dart'):
                    if path.stat().st_ino == os.fstat(fd).st_ino:
                        path.unlink()
                        put(path, raw)
                        break
            return raw
        with patch.object(os, 'read', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_FILE_SWAP'):
                self.inventory.capture()

    def test_directory_mutation_during_capture_is_rejected(self):
        real_read = os.read
        changed = []
        def add(fd, count):
            raw = real_read(fd, count)
            if raw and not changed:
                changed.append(True)
                put(self.stage / 'new-unexpected')
            return raw
        with patch.object(os, 'read', side_effect=add):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIRECTORY_RACE'):
                self.inventory.capture()

    def test_regular_leaf_opens_have_nofollow_and_nonblock(self):
        real_open = os.open
        observed = []
        def observe(name, flags, *args, **kwargs):
            if name in ('pubspec.yaml', 'main.dart'):
                observed.append(name)
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertTrue(flags & os.O_NONBLOCK)
            return real_open(name, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=observe):
            self.inventory.capture()
        self.assertEqual(set(observed), {'pubspec.yaml', 'main.dart'})

    def test_descriptor_cleanup_after_success_and_failure(self):
        self.inventory.capture()
        count = descriptors()
        for _ in range(12):
            self.inventory.capture()
            with patch.dict(G, MAX_TOTAL=1):
                with self.assertRaises(ValueError):
                    self.inventory.capture()
        self.assertEqual(descriptors(), count)

    def test_close_releases_pinned_ancestors_and_directories(self):
        count = descriptors()
        with S['Inventory'](str(self.stage)) as inventory:
            inventory.capture()
            self.assertGreater(descriptors(), count)
        self.assertEqual(descriptors(), count)
        inventory.close()
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_INVENTORY_CLOSED'):
            inventory.capture()

    def test_descriptor_bound_is_fail_closed_and_released(self):
        count = descriptors()
        with S['Inventory'](str(self.stage)) as inventory:
            with patch.dict(G, MAX_HELD_DIRS=len(inventory._pins) + 1):
                with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DESCRIPTOR_BOUND'):
                    inventory.capture()
        self.assertEqual(descriptors(), count)
        with patch.dict(G, MAX_HELD_DIRS=1):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DESCRIPTOR_BOUND'):
                S['Inventory'](str(self.stage))
        self.assertEqual(descriptors(), count)

    def test_close_attempts_every_descriptor_after_one_failure(self):
        count = descriptors()
        inventory = S['Inventory'](str(self.stage))
        inventory.capture()
        expected = set(inventory._pins.values())
        calls = []
        real_close = os.close
        def close(fd):
            calls.append(fd)
            real_close(fd)
            if len(calls) == 1:
                raise OSError('inert injected close status failure')
        with patch.object(os, 'close', side_effect=close):
            self.assertFalse(inventory.close())
            self.assertFalse(inventory.close())
        self.assertEqual(set(calls), expected)
        self.assertEqual(len(calls), len(expected))
        self.assertEqual(descriptors(), count)

    def test_duplicate_directory_entries_are_rejected(self):
        real_scandir = os.scandir
        class Duplicate:
            def __init__(self, fd):
                self.scan = real_scandir(fd)
            def __enter__(self):
                entries = list(self.scan)
                return iter(entries + entries)
            def __exit__(self, *args):
                self.scan.close()
        with patch.object(os, 'scandir', side_effect=Duplicate):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DUPLICATE_ENTRY'):
                self.inventory.capture()

    def test_normalized_hash_is_stable_across_declared_context_roots(self):
        sdk = str(self.base / 'sdk-original')
        roots = dict(sdk=sdk, app=str(self.stage))
        put(self.stage / 'lib/main.dart', ('sdk=' + sdk + '\napp=' + str(self.stage) + '\n').encode())
        first = self.inventory.normalized(self.inventory.capture(), ['lib/main.dart'], roots)
        alternate = self.base / 'different-stage-name'
        alternate.mkdir(mode=0o700)
        other_sdk = str(self.base / 'different-sdk-name')
        put(alternate / 'lib/main.dart', ('sdk=' + other_sdk + '\napp=' + str(alternate) + '\n').encode())
        with S['Inventory'](str(alternate)) as inventory:
            second = inventory.normalized(inventory.capture(), ['lib/main.dart'],
                                          dict(sdk=other_sdk, app=str(alternate)))
        self.assertEqual(first['lib/main.dart']['normalized_sha256'], second['lib/main.dart']['normalized_sha256'])
        self.assertNotEqual(first['lib/main.dart']['sha256'], second['lib/main.dart']['sha256'])
        self.assertEqual(first['lib/main.dart']['root_occurrences'], dict(sdk=1, app=1))
        public = json.dumps(first)
        for private in (sdk, str(self.stage), other_sdk, str(alternate)):
            self.assertNotIn(private, public)

    def test_normalization_uses_longest_root_first_and_only_selected_files(self):
        roots = dict(sdk=str(self.base), app=str(self.stage))
        put(self.stage / 'lib/main.dart', (str(self.stage) + '\n' + str(self.base)).encode())
        put(self.stage / 'unselected-private', b'not selected')
        result = self.inventory.normalized(self.inventory.capture(), ['lib/main.dart'], roots)
        self.assertEqual(set(result), {'lib/main.dart'})
        self.assertEqual(result['lib/main.dart']['root_occurrences'], dict(app=1, sdk=1))
        self.assertEqual(result['lib/main.dart']['normalized_sha256'], S['sha'](b'@P15_APP_ROOT@\n@P15_SDK_ROOT@'))

    def test_normalization_rejects_unknown_unsafe_or_duplicate_names_before_open(self):
        snapshot = self.inventory.capture()
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        for paths in (['not-captured'], ['../lib/main.dart'], ['lib/main.dart', 'lib/main.dart']):
            with patch.object(os, 'open', side_effect=AssertionError('must validate before any read')):
                with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_PATHS'):
                    self.inventory.normalized(snapshot, paths, roots)

    def test_normalization_rejects_snapshot_hash_or_mode_mismatch(self):
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        snapshot = self.inventory.capture()
        put(self.stage / 'lib/main.dart', b'changed original')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_CHANGED'):
            self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        snapshot = self.inventory.capture()
        (self.stage / 'lib/main.dart').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_FILE_METADATA'):
            self.inventory.normalized(snapshot, ['lib/main.dart'], roots)

    def test_normalization_rejects_parent_replacement_and_leaf_symlink(self):
        snapshot = self.inventory.capture()
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        (self.stage / 'lib').rename(self.base / 'old-lib')
        shutil.copytree(self.base / 'old-lib', self.stage / 'lib')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIRECTORY_SWAP'):
            self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        shutil.rmtree(self.stage / 'lib')
        (self.base / 'old-lib').rename(self.stage / 'lib')
        (self.stage / 'lib/main.dart').unlink()
        (self.stage / 'lib/main.dart').symlink_to('/private/never-open')
        with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_FILE_METADATA'):
            self.inventory.normalized(snapshot, ['lib/main.dart'], roots)

    def test_normalization_rejects_existing_reserved_tokens(self):
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        for token in S['ROOT_TOKENS'].values():
            put(self.stage / 'lib/main.dart', b'prefix ' + token + b' suffix')
            snapshot = self.inventory.capture()
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_TOKEN'):
                self.inventory.normalized(snapshot, ['lib/main.dart'], roots)

    def test_normalization_rejects_ambiguous_roots_and_bounds(self):
        snapshot = self.inventory.capture()
        for roots in (dict(sdk='/fixed-sdk', app='/other-stage'),
                      dict(sdk=str(self.stage), app=str(self.stage)),
                      dict(sdk='/@P15_SDK_ROOT@', app=str(self.stage)),
                      dict(sdk='/fixed-sdk', app=str(self.stage), other='/unknown')):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_ROOTS'):
                self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        with patch.dict(G, MAX_NORMALIZED_FILE=8):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_FILE'):
                self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        with patch.dict(G, MAX_NORMALIZED_PATHS=0):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_PATHS'):
                self.inventory.normalized(snapshot, ['lib/main.dart'], roots)

    def test_normalization_descriptor_cleanup_on_success_and_mismatch(self):
        snapshot = self.inventory.capture()
        roots = dict(sdk='/fixed-sdk', app=str(self.stage))
        count = descriptors()
        for _ in range(12):
            self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        put(self.stage / 'lib/main.dart', b'changed')
        for _ in range(12):
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_NORMALIZED_CHANGED'):
                self.inventory.normalized(snapshot, ['lib/main.dart'], roots)
        self.assertEqual(descriptors(), count)


class ProjectionTests(unittest.TestCase):
    def snapshot(self, names):
        result = {kind: {} for kind in S['KINDS']}
        result['files'] = {name: dict(mode=0o600, bytes=1, sha256=S['sha'](b'x')) for name in names}
        return result

    def test_only_explicit_reviewed_safe_names_are_published(self):
        names = ('lib/main.dart', 'lib/private-account-name.dart', '/absolute', '../escape',
                 'lib/../escape', 'line\nbreak', 'windows\\escape', 'lib/é.dart', 'C:/absolute')
        projection = S['projection'](self.snapshot(names), set(names) - {'lib/private-account-name.dart'})
        rendered = json.dumps(projection)
        self.assertEqual([row['path'] for row in projection['files'] if 'path' in row], ['lib/main.dart'])
        for name in names[1:]:
            self.assertNotIn(json.dumps(name)[1:-1], rendered)
        self.assertEqual(len(projection['files']), len(names))

    def test_redacted_set_is_complete_stable_and_preserves_hashes(self):
        names = ['private-%03d' % i for i in range(386)]
        snapshot = self.snapshot(names)
        first = S['projection'](snapshot, ())
        self.assertEqual(first, S['projection'](snapshot, ()))
        self.assertEqual(len(first['files']), 386)
        self.assertEqual({r['path_sha256'] for r in first['files']}, {S['sha'](n.encode()) for n in names})
        self.assertTrue(all(row['sha256'] == S['sha'](b'x') and row['location'] == 'other'
                            for row in first['files']))
        self.assertLess(len(json.dumps(first).encode()), 4 * 1024**2)

    def test_projection_cannot_publish_private_identity_or_target_fields(self):
        snapshot = self.snapshot(['known'])
        snapshot['files']['known'].update(inode=1234, target='/private/target', contents='secret', host='/host/path')
        rendered = json.dumps(S['projection'](snapshot, {'known'}))
        for text in ('inode', '1234', '/private/target', 'secret', '/host/path'):
            self.assertNotIn(text, rendered)

    def test_type_changes_unknowns_and_all_groups_are_projected(self):
        snapshot = self.snapshot(['lib/private'])
        snapshot['directories']['build/private'] = dict(mode=0o700)
        snapshot['aliases']['linux/private'] = dict(mode=0o777, bytes=12, type='symlink')
        snapshot['unsafe']['unknown-private'] = dict(mode=0o600, bytes=0, type='fifo')
        result = S['projection'](snapshot, ())
        self.assertTrue(all(len(rows) == 1 for rows in result.values()))
        self.assertEqual(result['directories'][0]['location'], 'build')
        self.assertEqual(result['aliases'][0]['type'], 'symlink')
        self.assertEqual(result['unsafe'][0]['type'], 'fifo')

    def test_exact_pub_metadata_file_labels_mask_only_the_build_id(self):
        build_id = '0123456789abcdef0123456789abcdef'
        leaves = ('.filecache', 'gen_l10n_inputs_and_outputs.json', 'gen_localizations.d',
                  'gen_localizations.stamp', 'outputs.json')
        names = ['build/' + build_id + '/' + leaf for leaf in leaves] + ['build/.last_build_id']
        result = S['projection'](self.snapshot(names), names)
        rows = {row['path']: row for row in result['files']}
        self.assertEqual(set(rows), {'build/<pub-build-id>/' + leaf for leaf in leaves}
                         | {'build/.last_build_id'})
        self.assertEqual({row['path_sha256'] for row in rows.values()}, {S['sha'](name.encode()) for name in names})
        self.assertNotIn(build_id, json.dumps(result))

    def test_exact_pub_metadata_directory_label_and_node_type_separation(self):
        name = 'build/' + 'a' * 32
        snapshot = self.snapshot([])
        snapshot['directories'][name] = dict(mode=0o700)
        result = S['projection'](snapshot, {name})
        self.assertEqual(result['directories'][0]['path'], 'build/<pub-build-id>')
        for kind in ('files', 'aliases', 'unsafe'):
            label = S['path_label'](name, {name}, kind)
            self.assertNotIn('path', label)
        for name in (name + '/outputs.json', 'build/.last_build_id'):
            for kind in ('directories', 'aliases', 'unsafe', None):
                self.assertNotIn('path', S['path_label'](name, {name}, kind))

    def test_pub_metadata_labels_reject_nested_uppercase_unknown_and_absolute_names(self):
        prefix = 'build/' + 'a' * 32
        names = (prefix + '/nested/outputs.json', prefix + '/outputs.json/extra',
                 'build/' + 'A' * 32 + '/outputs.json', prefix + '/unknown.json',
                 prefix + '/outputs.json.old', '/'+prefix+'/outputs.json',
                 prefix + '/.filecache\n', 'build/.last_build_id/extra',
                 'nested/build/' + 'a' * 32 + '/outputs.json')
        result = S['projection'](self.snapshot(names), ())
        self.assertTrue(all('path' not in row for row in result['files']))
        self.assertNotIn('unknown.json', json.dumps(result))

    def test_pub_metadata_symlink_is_never_labelled_as_regular_output(self):
        name = 'build/' + 'a' * 32 + '/outputs.json'
        snapshot = self.snapshot([])
        snapshot['unsafe'][name] = dict(type='symlink', mode=0o777, bytes=12, sha256=S['sha'](b'/private/link'))
        row = S['projection'](snapshot, {name})['unsafe'][0]
        self.assertNotIn('path', row)
        self.assertEqual(row['type'], 'symlink')
        self.assertEqual(row['path_sha256'], S['sha'](name.encode()))


if __name__ == '__main__':
    unittest.main()
