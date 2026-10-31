#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P15c authority for one original hook in two fixed, networkless profiles.

This is host orchestration, not package code or a hook wrapper. The original
SDK compiles/runs the original hook. Exact source/commands/configuration supply
preventive target authority; bounded generated-state checks supply evidence.
No native compiler, linker, network or additional sandbox right is authorized.
"""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'third_party/overmorrow-hook-inputs-v1.json'
RECORD_SHA = '5e3837532d2c6f5638f0125aa24e3daa87f87f3b951a3cb79eafc0968a6d3121'
PACKAGE = 'objective_c'
VERSION = '9.5.0'
ENTRY = 'hook/build.dart'
ARCHIVE_SHA = 'b7fb95a6d9a4f009edd63dc5ac69f07420b23a16161c6dd8660290b59c602e8e'
HOOK_SHA = 'aa8cd26a22f3d5f7cb1e769f6de647bae2b485db4576a43743c20f9a34301f7e'
PROFILES = {'test': 'linux-x64-tests-no-native-output', 'build': 'web-js-empty-code-assets'}
CONFIGS = {
    # code_assets 0.19.7 uses the asset discriminator code_assets/code.
    # The extension namespace is separately named code_assets. The original
    # runner hashes the complete sorted config, including this discriminator.
    'test': dict(build_asset_types=['code_assets/code'], extensions=dict(code_assets=dict(
        link_mode_preference='dynamic', target_architecture='x64', target_os='linux')),
        linking_enabled=False),
    'build': dict(build_asset_types=[], linking_enabled=True),
}
TASK_FILES = frozenset(('.lock', 'input.json', 'output.json', 'hook.dill', 'hook.dill.d',
    'hook.dependencies_hash_file.json', 'dependencies.dependencies_hash_file.json', 'stdout.txt', 'stderr.txt'))
MAX_ENTRIES = 128


def module(name):
    spec = importlib.util.spec_from_file_location('_p15c_' + name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


I = module('prepare_hosted_client_inputs')


class HookContractError(ValueError):
    def __init__(self, code, owner=None, hook=None):
        super().__init__(code)
        self.observation = dict(code=code, package=owner.get('package', 'unknown') if owner else 'unknown',
            version=owner.get('version', '') if owner else '',
            hook=hook if hook in ('hook/build.dart', 'hook/link.dart') else 'unknown')


class TaskSetError(HookContractError):
    """Bounded names are diagnostics only; never derive authority from them."""
    def __init__(self, tasks, observed, owner):
        super().__init__('P15_HOOK_TASK_SET', owner, ENTRY)
        self._expected = tuple(sorted((action, key) for key, action in tasks.items()))
        self._observed = tuple(sorted(observed))

    def task_observation(self):
        rows = []
        for name in self._observed:
            if re.fullmatch(r'[0-9a-f]{32}', name):
                rows.append(dict(checksum=name))
            else:
                raw = os.fsencode(name)
                rows.append(dict(kind='unrecognized-name', bytes=len(raw), sha256=I.sha(raw)))
        return dict(kind='p15-hook-task-identity', expected=[
            dict(action=action, checksum=key) for action, key in self._expected],
            observed=rows, observed_names_authorize_execution=False)


def check(ok, code, owner=None, hook=None):
    if not ok:
        raise HookContractError(code, owner, hook)


def same(left, right):
    # Preserve JSON type distinctions (in particular bool versus int).
    return I.canonical(left) == I.canonical(right)


def load_record():
    raw = I.read(RECORD, 512 * 1024)
    check(I.sha(raw) == RECORD_SHA, 'P15_HOOK_RECORD_CHANGED')
    record = I.document(raw)
    check(record['schema'] == 1 and record['kind'] == 'p15-overmorrow-hook-inputs'
        and record['hook_inputs_authorized'] is True and record['admitted'] is False
        and record['production_authority'] is False and len(record['archives']) == 224
        and record['summary']['automatic_hook_entrypoints'] == 1
        and set(record['profiles']) == set(PROFILES.values()), 'P15_HOOK_RECORD_SCHEMA')
    for key in ('app_record', 'tool_record', 'runtime_record'):
        item = record['original_inputs'][key]
        check(I.sha(I.read(ROOT / item['path'])) == item['sha256'], 'P15_HOOK_INPUT_CHANGED')
    item = record['original_inputs']['overmorrow']
    check(I.sha(I.read(ROOT / 'integrations/overmorrow/upstream.json')) == item['pin_sha256'],
          'P15_HOOK_UPSTREAM_CHANGED')
    hook = record['hook']
    check(hook['package'] == PACKAGE and hook['version'] == VERSION and hook['path'] == ENTRY
        and hook['archive_sha256'] == ARCHIVE_SHA and hook['sha256'] == HOOK_SHA
        and hook['bytes'] == 7018, 'P15_HOOK_IDENTITY')
    return record


def authorize_inventory(archive_sha256, files):
    """The complete original membermap, not a global hook-name allowlist."""
    record = load_record()
    owner = record['archives'].get(archive_sha256)
    check(owner is not None, 'P15_HOOK_ARCHIVE_UNKNOWN')
    check(type(files) is dict and I.sha(I.canonical(files)) == owner['membermap_sha256'],
          'P15_HOOK_MEMBERMAP_CHANGED', owner)
    automatic = sorted(name for name, item in files.items()
        if item.get('type') == 'file' and name in ('hook/build.dart', 'hook/link.dart'))
    legacy = sorted(name for name, item in files.items() if item.get('type') == 'file' and
        ((name.startswith(('hook/', 'hooks/')) and name.endswith('.dart')) or name in ('build.dart', 'link.dart')))
    check(automatic == owner['automatic_hooks'] and legacy == owner['legacy_predicate_matches'],
          'P15_UNREVIEWED_PACKAGE_HOOK', owner, automatic[0] if automatic else None)
    if automatic:
        check(archive_sha256 == ARCHIVE_SHA and automatic == [ENTRY],
              'P15_UNREVIEWED_PACKAGE_HOOK', owner, automatic[0])
        item = files[ENTRY]
        check(item['bytes'] == 7018 and item['sha256'] == HOOK_SHA and not item['executable'],
              'P15_HOOK_SOURCE_CHANGED', owner, ENTRY)
    return dict(package=owner['package'], version=owner['version'], automatic_hook_count=len(automatic),
                authorized_profiles=list(PROFILES.values()) if automatic else [], record_sha256=RECORD_SHA)


def checksum(config):
    # Original constructors/setters sort these two closed configurations before
    # hooks 0.20.1 encodes compact UTF-8 JSON and takes this SHA256 prefix.
    # Naming only: package/source/config checks still supply execution authority.
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]


def authorize_profile(action, sdk, argv, environment):
    load_record()
    check(action in PROFILES and platform.system() == 'Linux' and platform.machine() == 'x86_64',
          'P15_HOOK_PROFILE_REQUIRED', dict(package=PACKAGE, version=VERSION), ENTRY)
    original = module('prepare_hosted_overmorrow_ci')
    original.SDK = Path(sdk)
    expected = original.flutter_command(action)
    if action == 'build':
        expected += ['--no-tree-shake-icons']
    check(argv == expected and environment == original.environment(), 'P15_HOOK_TARGET_OVERRIDE',
          dict(package=PACKAGE, version=VERSION), ENTRY)
    return PROFILES[action]


def directory(path):
    info = path.lstat()
    check(path.resolve() == path and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
        and not info.st_mode & 0o022, 'P15_HOOK_DIRECTORY')


def children(path, maximum):
    directory(path)
    result = []
    with os.scandir(path) as entries:
        for entry in entries:
            check(len(result) < maximum, 'P15_HOOK_ENTRY_BOUND')
            result.append(Path(entry.path))
    return result


def regular(path, maximum=2 * 1024**2):
    info = path.lstat()
    check(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= maximum, 'P15_HOOK_FILE')
    return I.read(path, maximum)


def document(path):
    return I.document(regular(path))


def absolute(value, expected, *, directory_path=False):
    # JSON paths are data. Never open them or follow supplied URI/path aliases.
    return type(value) is str and (value == str(expected)
        or directory_path and value == str(expected) + '/')


def stamp(path, *, stage, sdk, dependency):
    value = document(path)
    check(type(value) is dict and set(value) == {'file_system', 'environment'}
        and type(value['file_system']) is list and type(value['environment']) is list
        and len(value['file_system']) <= 4096 and len(value['environment']) <= 2, 'P15_HOOK_STAMP_SCHEMA')
    seen = set()
    for row in value['file_system']:
        check(type(row) is dict and set(row) == {'path', 'hash'} and type(row['path']) is str
            and len(row['path']) < 4096 and row['path'] not in seen and type(row['hash']) is int
            and 0 <= row['hash'] < 2**64, 'P15_HOOK_STAMP_ENTRY')
        seen.add(row['path'])
        target = Path(row['path'])
        check(target.is_absolute() and str(target) == os.path.normpath(row['path'])
            and (target == stage / '.dart_tool/package_config.json' or target.is_relative_to(sdk)),
            'P15_HOOK_STAMP_PATH')
    keys = set()
    for row in value['environment']:
        check(type(row) is dict and set(row) == {'key', 'hash'} and row['key'] in ('HOME', 'PATH')
            and row['key'] not in keys and type(row['hash']) is int and 0 <= row['hash'] < 2**64,
            'P15_HOOK_STAMP_ENVIRONMENT')
        keys.add(row['key'])
    check((not seen and keys == {'HOME', 'PATH'}) if dependency else (not keys and bool(seen)),
          'P15_HOOK_STAMP_SCOPE')


class HookRun:
    """Fresh per-candidate state; two targets, no cross-run cache admission."""
    def __init__(self, stage, sdk, cache, source_pubspec_sha256):
        load_record()
        self.stage, self.sdk, self.cache = map(Path, (stage, sdk, cache))
        self.root = self.stage / '.dart_tool/hooks_runner'
        self.pubspec_sha256 = source_pubspec_sha256
        self.completed = set()
        self.owner = dict(package=PACKAGE, version=VERSION)
        self._source_guard()
        check(not self.root.exists() and not self.root.is_symlink(), 'P15_HOOK_STATE_NOT_FRESH', self.owner, ENTRY)

    def _source_guard(self):
        directory(self.stage)
        raw = I.read(self.stage / 'pubspec.yaml', 128 * 1024)
        check(I.sha(raw) == self.pubspec_sha256 and not re.search(rb'(?m)^ *(hooks|workspace|resolution):', raw)
            and not (self.stage / 'pubspec_overrides.yaml').exists()
            and not (self.stage / 'pubspec_overrides.yaml').is_symlink(), 'P15_HOOK_ROOT_DEFINES', self.owner, ENTRY)

    def before(self, action, argv, environment):
        self._source_guard()
        profile = authorize_profile(action, self.sdk, argv, environment)
        check(action not in self.completed and (action == 'test' or self.completed == {'test'}),
              'P15_HOOK_PHASE_ORDER', self.owner, ENTRY)
        self._inspect(self.completed)
        return dict(profile=profile, hook_kernel_and_protocol_authorized=True,
                    native_compilation_authorized=False, additional_network_or_filesystem_rights=False)

    def after(self, action):
        self._source_guard()
        expected = self.completed | {action}
        result = self._inspect(expected)
        self.completed = expected
        if action == 'test':
            manifest = document(self.stage / 'build/native_assets/linux/native_assets.json')
            check(same(manifest, {'format-version': [1, 0, 0], 'native-assets': {}}),
                  'P15_HOOK_NATIVE_ASSET_MANIFEST', self.owner, ENTRY)
        return result

    def _inspect(self, actions):
        if not actions:
            check(not self.root.exists() and not self.root.is_symlink(), 'P15_HOOK_PREMATURE_STATE', self.owner, ENTRY)
            return dict(verified_profiles=[], tasks=0, native_asset_count=0, private_contents_exported=False)
        check({p.name for p in children(self.root, 2)} == {PACKAGE, 'shared'}, 'P15_HOOK_OWNER_SET', self.owner, ENTRY)
        tasks = {checksum(CONFIGS[action]): action for action in actions}
        owner_dir = self.root / PACKAGE
        observed = {p.name for p in children(owner_dir, 2)}
        if observed != set(tasks):
            raise TaskSetError(tasks, observed, self.owner)
        shared = self.root / 'shared'
        check({p.name for p in children(shared, 1)} == {PACKAGE}, 'P15_HOOK_SHARED_OWNER', self.owner, ENTRY)
        shared_owner = shared / PACKAGE
        check({p.name for p in children(shared_owner, 2)} == {'.lock', 'build'}, 'P15_HOOK_SHARED_FILES', self.owner, ENTRY)
        regular(shared_owner / '.lock', 16384)
        shared_build = shared_owner / 'build'
        check({p.name for p in children(shared_build, 2)} == {key[:10] for key in tasks},
              'P15_HOOK_SHARED_CHECKSUMS', self.owner, ENTRY)
        for path in children(shared_build, 2):
            check(not children(path, 1), 'P15_HOOK_NATIVE_OUTPUT', self.owner, ENTRY)
        for key, action in tasks.items():
            task = owner_dir / key
            paths = children(task, 10)
            check({p.name for p in paths} == TASK_FILES | {'out'}, 'P15_HOOK_TASK_FILES', self.owner, ENTRY)
            check(not children(task / 'out', 1), 'P15_HOOK_NATIVE_OUTPUT', self.owner, ENTRY)
            for path in paths:
                if path.name != 'out':
                    maximum = 128 * 1024**2 if path.name == 'hook.dill' else 2 * 1024**2
                    regular(path, maximum)
            check((task / 'hook.dill').stat().st_size > 0 and (task / 'hook.dill.d').stat().st_size > 0,
                  'P15_HOOK_KERNEL_MISSING', self.owner, ENTRY)
            value = document(task / 'input.json')
            check(type(value) is dict and set(value) == {
                'config', 'out_dir_shared', 'out_file', 'package_name', 'package_root', 'assets'}
                and same(value['config'], CONFIGS[action]) and same(value['assets'], {})
                and value['package_name'] == PACKAGE
                and absolute(value['out_dir_shared'], shared_build, directory_path=True)
                and absolute(value['out_file'], task / 'output.json')
                and absolute(value['package_root'], Path('/state/pub-cache/hosted/pub.dev') / (PACKAGE + '-' + VERSION),
                             directory_path=True),
                'P15_HOOK_PROTOCOL_INPUT', self.owner, ENTRY)
            output = document(task / 'output.json')
            check(type(output) is dict and set(output) == {'assets_for_linking', 'status', 'timestamp'}
                and same(output['assets_for_linking'], {}) and output['status'] == 'success'
                and type(output['timestamp']) is str and 19 <= len(output['timestamp']) <= 32,
                'P15_HOOK_PROTOCOL_OUTPUT', self.owner, ENTRY)
            try:
                timestamp = datetime.datetime.fromisoformat(output['timestamp'])
                check(timestamp.microsecond == 0, 'P15_HOOK_TIMESTAMP', self.owner, ENTRY)
            except ValueError:
                raise HookContractError('P15_HOOK_TIMESTAMP', self.owner, ENTRY) from None
            # Stdout includes runner's private command/env/cwd line, not just
            # hook output. Neither logs nor hash stamps are publicly exported.
            check(regular(task / 'stderr.txt') == b'', 'P15_HOOK_STDERR', self.owner, ENTRY)
            stamp(task / 'hook.dependencies_hash_file.json', stage=self.stage, sdk=self.sdk, dependency=False)
            stamp(task / 'dependencies.dependencies_hash_file.json', stage=self.stage, sdk=self.sdk, dependency=True)
        return dict(verified_profiles=sorted(PROFILES[action] for action in actions), tasks=len(tasks),
            hook_package=PACKAGE, hook_version=VERSION, hook_source_sha256=HOOK_SHA,
            hook_record_sha256=RECORD_SHA, hook_kernel_and_protocol_authorized=True,
            native_asset_count=0, native_compilation_authorized=False, native_link_hook_allowed=False,
            private_contents_exported=False)

    def failure_observation(self):
        # Fixed identity only. A failed Flutter command does not establish
        # that a hook was reached, even if it was authorized for that target.
        return dict(package=PACKAGE, version=VERSION, hook=ENTRY,
                    execution_reached_unverified=True, profile_contract_sha256=RECORD_SHA)
