#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P15-only, data-only materialization of the original locked pub dependencies.

No package, SDK, lifecycle or compiler code is executed here. The fixed original
record authenticates every archive and its complete canonical member inventory.
The caller owns hosted-runner, Boundary, deadline and cleanup authorization.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import time
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_p15_original_inputs', ROOT / 'scripts/prepare_hosted_client_inputs.py')
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)
require = I.require
SDK_PATHS = {name: 'packages/' + name for name in
             ('flutter', 'flutter_localizations', 'flutter_test', 'flutter_web_plugins')}
SDK_PATHS['sky_engine'] = 'bin/cache/pkg/sky_engine'
MAX_MAP_BYTES = 64 * 1024**2
MAX_CACHE_BYTES = 1024**3
MAX_FILES = 100000
PUB_SOURCE = 'f7f1891e2de3d795532f45ec214f88ac912ffcd6'
SDK_INVENTORY_SHA = '98df602485d0dd66195f614e950dc59ed3f7dddf5169431ece5a4c2a92ace5c7'
TOOL_LOCK = 'packages/flutter_tools/pubspec.lock'
TOOL_LOCK_SHA = '246d46461bdfa97d5734a188d16fc2741dddc88d111eeb49dfe6bc6087bc771f'
TOOL_INPUTS = ROOT / 'third_party/overmorrow-tool-inputs-v1.json'
TOOL_INPUTS_SHA = 'fc99497c4473f331ba63f0b986db2eaf25a447741320df76e7feca78dc254c9f'


def parse_tool_lock(raw):
    """Parse the original tool lock's narrower hosted-only, Dart-only schema."""
    require(type(raw) is bytes and 0 < len(raw) <= 1024**2, 'P15_TOOL_LOCK_BOUND')
    section, current, description, packages, sdks = None, None, False, {}, {}
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        require('\t' not in line and len(line) <= 4096, 'P15_TOOL_LOCK_LINE')
        if line in ('packages:', 'sdks:'):
            new = line[:-1]
            require((section is None and new == 'packages') or (section == 'packages' and new == 'sdks'),
                    'P15_TOOL_LOCK_SECTION')
            section, current = new, None
            continue
        match = re.fullmatch(r'  ([a-zA-Z0-9_]+):(?: (.+))?', line)
        if match:
            name, value = match.groups()
            if section == 'sdks':
                require(name not in sdks and value is not None, 'P15_TOOL_SDK_DUPLICATE')
                sdks[name] = I.scalar(value)
            else:
                require(section == 'packages' and value is None and name not in packages
                        and len(packages) < 1024, 'P15_TOOL_LOCK_PACKAGE')
                current = packages[name] = {}
                description = False
            continue
        match = re.fullmatch(r'(    |      )([a-z0-9_]+):(.*)', line)
        require(section == 'packages' and current is not None and match is not None, 'P15_TOOL_LOCK_SYNTAX')
        indent, key, value = match.groups()
        if indent == '    ':
            description = key == 'description' and value == ''
            target = current
        else:
            require(description and type(current.get('description')) is dict, 'P15_TOOL_LOCK_DESCRIPTION')
            target = current['description']
        require(key not in target and (value == '' or value.startswith(' ')), 'P15_TOOL_LOCK_DUPLICATE')
        target[key] = {} if description and indent == '    ' else I.scalar(value[1:])
    require(section == 'sdks' and sdks == {'dart': '>=3.9.0 <4.0.0'} and packages, 'P15_TOOL_LOCK_SDKS')
    result = {}
    for name, item in packages.items():
        require(set(item) == {'dependency', 'description', 'source', 'version'}
                and item['dependency'] in ('transitive', 'direct main', 'direct dev')
                and re.fullmatch(I.VERSION, item['version']) and item['source'] == 'hosted', 'P15_TOOL_LOCK_ENTRY')
        desc = item['description']
        require(type(desc) is dict and set(desc) == {'name', 'sha256', 'url'} and desc['name'] == name
                and desc['url'] == 'https://pub.dev' and type(desc['sha256']) is str
                and re.fullmatch(r'[0-9a-f]{64}', desc['sha256']), 'P15_TOOL_LOCK_HOSTED')
        result[name] = dict(source='hosted', version=item['version'], sha256=desc['sha256'],
                            url=f'https://pub.dev/api/archives/{name}-{item["version"]}.tar.gz')
    return result


def fixed_inputs():
    record = I.load_package_inputs('overmorrow')
    raw = I.read(ROOT / 'third_party/client-locks/overmorrow-pubspec.lock', 1024**2)
    require(I.sha(raw) == record['source']['sha256'], 'P15_ORIGINAL_LOCK_CHANGED')
    entries = I.pub_lock(raw)
    packages = record['dependencies']['packages']
    require(set(entries) == set(packages) and len(entries) == 157
            and sum(e['source'] == 'hosted' for e in entries.values()) == 152
            and {n for n, e in entries.items() if e['source'] == 'sdk'} == set(SDK_PATHS),
            'P15_DEPENDENCY_SET')
    for name, entry in entries.items():
        require((packages[name]['input'] if entry['source'] == 'hosted' else packages[name]) == entry,
                'P15_DEPENDENCY_SOURCE')
    return entries, packages


def sdk_verification(sdk):
    spec = importlib.util.spec_from_file_location('_p15_sdk_verify', ROOT / 'scripts/prepare_hosted_flutter.py')
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    binding = preparer.verify_materialized(sdk, allow_build_state=True)
    require(binding['input'] == preparer.input_record()
            and binding['input']['commit'] == I.SDK_COMMIT
            and binding['inventory_sha256'] == SDK_INVENTORY_SHA and binding['files'] == 17240,
            'P15_SDK_REFERENCE_CHANGED')
    return binding


def load_tool_record():
    raw = I.read(TOOL_INPUTS, 512 * 1024)
    require(I.sha(raw) == TOOL_INPUTS_SHA, 'P15_TOOL_INPUT_RECORD_CHANGED')
    record = I.document(raw)
    require(record['kind'] == 'p15-overmorrow-flutter-tool-inputs' and record['schema'] == 1
            and record['package_inputs_authorized'] is True and record['admitted'] is False
            and record['sdk']['inventory_sha256'] == SDK_INVENTORY_SHA
            and record['lock']['sha256'] == TOOL_LOCK_SHA
            and record['summary']['hosted_packages'] == 101
            and record['summary']['union_hosted_packages'] == 224
            and record['summary']['automatic_hook_packages'] == []
            and record['summary']['missing_notice_packages'] == [], 'P15_TOOL_INPUT_RECORD_SCHEMA')
    return record


def tool_inputs(sdk):
    """Bind original tool lock/preloads to the already fixed full SDK inventory."""
    sdk = Path(sdk)
    binding = sdk_verification(sdk)
    record = load_tool_record()
    require(record['sdk']['input'] == binding['input'], 'P15_TOOL_SDK_RECORD_CHANGED')
    inventory_raw = I.read(sdk / 'sdk-inventory.json', 8 * 1024**2)
    require(I.sha(inventory_raw) == SDK_INVENTORY_SHA, 'P15_TOOL_SDK_INVENTORY')
    inventory = I.document(inventory_raw)
    raw = I.read(sdk / TOOL_LOCK, 1024**2)
    require(I.sha(raw) == TOOL_LOCK_SHA and len(raw) == record['lock']['bytes']
            and record['lock'] == dict(path=TOOL_LOCK, **inventory[TOOL_LOCK]), 'P15_TOOL_LOCK_CHANGED')
    pubspec_path = 'packages/flutter_tools/pubspec.yaml'
    require(record['pubspec'] == dict(path=pubspec_path, **inventory[pubspec_path]), 'P15_TOOL_PUBSPEC_CHANGED')
    entries = parse_tool_lock(raw)
    require(set(entries) == set(record['packages']) and len(entries) == 101, 'P15_TOOL_PACKAGE_SET')
    for name, entry in entries.items():
        pin = record['packages'][name]
        path = '.pub-preload-cache/' + name + '-' + entry['version'] + '.tar.gz'
        require(entry == pin['input'] and pin['sdk_preload'] == dict(path=path, **inventory[path])
                and entry['sha256'] == pin['sdk_preload']['sha256'], 'P15_TOOL_PRELOAD_BINDING')
    return entries, record, binding


def union_inputs(app, app_packages, tool, tool_record):
    """Identity is (name,version); same identity with different bytes is fatal."""
    result = {}
    for name, entry in sorted(app.items()):
        if entry['source'] == 'hosted':
            result[name + '-' + entry['version']] = dict(name=name, input=entry,
                archive=app_packages[name]['archive'], origin='app')
    for name, entry in sorted(tool.items()):
        key = name + '-' + entry['version']
        pin = tool_record['packages'][name]
        if key in result:
            require(result[key]['input'] == entry and all(result[key]['archive'][field] == pin['archive'][field]
                    for field in ('bytes', 'sha256', 'expanded_bytes', 'files_sha256')), 'P15_CONFLICTING_PACKAGE_BYTES')
        result[key] = dict(name=name, input=entry, archive=pin['archive'], origin='sdk', preload=pin['sdk_preload'])
    require(len(result) == 224, 'P15_UNION_PACKAGE_SET')
    return result


def owned_directory(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'P15_CACHE_DIRECTORY')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'P15_CACHE_DIRECTORY')


def directory_paths(path, maximum):
    """Materialize only a cardinality-bounded, incrementally read directory."""
    require(type(maximum) is int and 0 <= maximum <= MAX_FILES, 'P15_DIRECTORY_BOUND')
    paths = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            require(len(paths) < maximum, 'P15_DIRECTORY_ENTRIES_BOUND')
            paths.append(Path(path) / entry.name)
    return paths


def private_map(cache):
    return cache.with_name(cache.name + '-p15-member-maps.json')


def hook_contract():
    # This is reviewed host orchestration, never a package import. The source
    # commit binds this fixed module; its independently pinned record supplies
    # the only hook/input/profile authority.
    spec = importlib.util.spec_from_file_location('_p15_hook_contract',
        ROOT / 'scripts/prepare_hosted_overmorrow_hooks.py')
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract


def lifecycle(files, archive_sha256):
    # Keep typed fixed owner observations from HookContractError intact. Source
    # and complete member-map checks precede this call at both production sites.
    return hook_contract().authorize_inventory(archive_sha256, files)


def authenticated_inventory(raw, pin):
    inventory = I.archive_inventory(raw, npm=False)
    require({key: inventory[key] for key in ('bytes', 'sha256', 'expanded_bytes')}
            == {key: pin[key] for key in ('bytes', 'sha256', 'expanded_bytes')}
            and I.sha(I.canonical(inventory['files'])) == pin['files_sha256'],
            'P15_ARCHIVE_MEMBER_BINDING')
    lifecycle(inventory['files'], inventory['sha256'])
    return inventory['files']


def extract_regular(raw, destination, files):
    """Extract only already authenticated regular members, never tar.extract."""
    require(not destination.exists() and not destination.is_symlink(), 'P15_PACKAGE_EXISTS')
    destination.mkdir(mode=0o700)
    seen = set()
    with tarfile.open(fileobj=I.BoundedGzip(raw), mode='r|') as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/') if member.isdir() else member.name.removeprefix('./')
            if name in ('', '.') and member.isdir():
                continue
            I.safe_path(name)
            require(name in files and name not in seen, 'P15_EXTRACTION_MEMBER')
            seen.add(name)
            expected = files[name]
            target = destination / name
            current = destination
            for component in Path(name).parts[:-1]:
                current /= component
                if not current.exists():
                    current.mkdir(mode=0o700)
                owned_directory(current)
            if expected['type'] == 'directory':
                require(member.isdir(), 'P15_EXTRACTION_TYPE')
                target.mkdir(mode=0o700, exist_ok=True)
                owned_directory(target)
                continue
            require(member.isreg() and member.size == expected['bytes'], 'P15_EXTRACTION_TYPE')
            source = archive.extractfile(member)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o700 if expected['executable'] else 0o600)
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as output:
                while chunk := source.read(65536):
                    size += len(chunk)
                    require(size <= expected['bytes'], 'P15_EXTRACTION_BOUND')
                    digest.update(chunk)
                    output.write(chunk)
            require(size == expected['bytes'] and digest.hexdigest() == expected['sha256'],
                    'P15_EXTRACTION_DIGEST')
    require(seen == set(files), 'P15_EXTRACTION_INCOMPLETE')


def prepare(cache, sdk, *, downloader=I.fetch):
    cache, sdk = Path(cache), Path(sdk)
    owned_directory(cache)
    require(not directory_paths(cache, 1), 'P15_CACHE_NOT_EMPTY')
    entries, packages = fixed_inputs()
    tool, tool_record, sdk_binding = tool_inputs(sdk)
    union = union_inputs(entries, packages, tool, tool_record)
    hosted, hashes = cache / 'hosted/pub.dev', cache / 'hosted-hashes/pub.dev'
    for parent in (cache / 'hosted', hosted, cache / 'hosted-hashes', hashes):
        parent.mkdir(mode=0o700)
    maps, total, expanded, downloaded, preload_bytes, hook_count, started = {}, 0, 0, 0, 0, 0, time.monotonic()
    # Tool preloads first. The 29 identical app identities are already present
    # and are never downloaded again or overwritten by the app closure.
    ordered = sorted(union, key=lambda key: (union[key]['origin'] != 'sdk', key))
    for key in ordered:
        require(time.monotonic() - started < 900, 'P15_PUB_ACQUISITION_DEADLINE')
        item = union[key]
        entry, pin = item['input'], item['archive']
        if item['origin'] == 'sdk':
            raw = I.read(sdk / item['preload']['path'], I.MAX_ARCHIVE)
            require(len(raw) == item['preload']['bytes'] and I.sha(raw) == item['preload']['sha256'],
                    'P15_PRELOAD_CHANGED')
            preload_bytes += len(raw)
        else:
            raw = downloader(entry['url'], I.MAX_ARCHIVE, sha256=entry['sha256'])
            downloaded += len(raw)
        total += len(raw)
        expanded += pin['expanded_bytes']
        require(total <= 512 * 1024**2 and expanded <= MAX_CACHE_BYTES, 'P15_PUB_TOTAL_BOUND')
        files = authenticated_inventory(raw, pin)
        hook_count += sum(files.get(name, {}).get('type') == 'file' for name in ('hook/build.dart', 'hook/link.dart'))
        extract_regular(raw, hosted / key, files)
        I.write(hashes / (key + '.sha256'), entry['sha256'].encode())
        maps[key] = files
    raw_maps = I.canonical(maps)
    require(len(raw_maps) <= MAX_MAP_BYTES, 'P15_MEMBER_MAP_BOUND')
    I.write(private_map(cache), raw_maps)
    return dict(schema=1, kind='p15-locked-pub-data-materialization', app_hosted_packages=152,
                tool_hosted_packages=101, union_hosted_packages=224, app_archives_reused=29,
                app_archives_downloaded=123, sdk_references=5, archive_bytes=total, expanded_bytes=expanded,
                sdk_preload_bytes=preload_bytes, app_download_bytes=downloaded,
                member_maps_sha256=I.sha(raw_maps), dependency_lock_sha256=I.SOURCES['overmorrow']['sha256'],
                tool_lock_sha256=TOOL_LOCK_SHA, tool_input_record_sha256=TOOL_INPUTS_SHA,
                sdk_inventory_sha256=sdk_binding['inventory_sha256'],
                package_record_sha256=I.PACKAGE_INPUTS['overmorrow'][1], package_code_executed=False,
                lifecycle_hooks_found=hook_count, lifecycle_hooks_authorized=hook_count, production_authority=False)


def regular_hash(path, expected):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == (0o700 if expected['executable'] else 0o600)
            and info.st_size == expected['bytes'], 'P15_PACKAGE_FILE_METADATA')
    require(I.sha(I.read(path, I.MAX_MEMBER)) == expected['sha256'], 'P15_PACKAGE_FILE_CHANGED')


def verify_package(root, files):
    owned_directory(root)
    expected_files = {name for name, item in files.items() if item['type'] == 'file'}
    expected_dirs = {name for name, item in files.items() if item['type'] == 'directory'}
    for name in files:
        expected_dirs.update(str(p) for p in Path(name).parents if str(p) != '.')
    found_files, found_dirs, pending, count = set(), set(), [(root, 0)], 0
    while pending:
        directory, depth = pending.pop()
        with os.scandir(directory) as iterator:
            for entry in iterator:
                require(count < MAX_FILES, 'P15_PACKAGE_MEMBERS_BOUND')
                count += 1
                require(depth < 64, 'P15_PACKAGE_DEPTH_BOUND')
                path = directory / entry.name
                name = str(path.relative_to(root))
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    require(name in expected_dirs, 'P15_UNKNOWN_PACKAGE_DIRECTORY')
                    owned_directory(path)
                    found_dirs.add(name)
                    pending.append((path, depth + 1))
                else:
                    require(name in expected_files, 'P15_UNKNOWN_PACKAGE_FILE')
                    regular_hash(path, files[name])
                    found_files.add(name)
    require(found_files == expected_files and found_dirs == expected_dirs, 'P15_PACKAGE_TREE_CHANGED')


def cache_metadata(hosted, entries):
    metadata = hosted / '.cache'
    if not metadata.exists() and not metadata.is_symlink():
        return 0
    owned_directory(metadata)
    expected = {name + '-versions.json' for name, entry in entries.items() if entry['source'] == 'hosted'}
    count = 0
    for path in directory_paths(metadata, len(expected)):
        require(path.name in expected, 'P15_UNKNOWN_PUB_METADATA')
        raw = I.read(path, 2 * 1024**2)
        value = I.document(raw)
        require(type(value) is dict and set(value) <= {'name', 'latest', 'versions', '_fetchedAt'}
                and value.get('name') == path.name.removesuffix('-versions.json')
                and type(value.get('versions')) is list and len(value['versions']) <= 10000,
                'P15_PUB_METADATA_SCHEMA')
        count += 1
    return count


def active_roots(cache, sdk, stage):
    # Dart 3.10.4 DEPS binds PUB_SOURCE above. Its system_cache.dart writes
    # sha256(canonical package_config file URI), split 2/62, with one JSON key.
    root = cache / 'active_roots'
    if not root.exists() and not root.is_symlink():
        return 0
    owned_directory(root)
    targets = [sdk / 'packages/flutter_tools/.dart_tool/package_config.json']
    if stage is not None:
        targets.append(Path(stage) / '.dart_tool/package_config.json')
    authorized = {}
    for target in targets:
        uri = target.as_uri()
        digest = hashlib.sha256(uri.encode()).hexdigest()
        authorized[digest[:2] + '/' + digest[2:]] = uri
    count = 0
    for directory in directory_paths(root, 2):
        require(directory.name in {name[:2] for name in authorized}, 'P15_UNKNOWN_ACTIVE_ROOT')
        owned_directory(directory)
        for path in directory_paths(directory, 2 - count):
            name = directory.name + '/' + path.name
            require(name in authorized, 'P15_UNKNOWN_ACTIVE_ROOT')
            value = I.document(I.read(path, 8192))
            require(value == dict(package_config=authorized[name]), 'P15_ACTIVE_ROOT_CHANGED')
            count += 1
    return count


def uri_path(base, value):
    require(type(value) is str and len(value) <= 4096 and '\\' not in value, 'P15_PACKAGE_URI')
    uri = urlparse(urljoin(base.as_uri() + '/', value))
    require(uri.scheme == 'file' and not uri.netloc and not uri.query and not uri.fragment
            and '%' not in unquote(uri.path), 'P15_PACKAGE_URI')
    return Path(os.path.normpath(unquote(uri.path)))


def pubspec_language(raw):
    """Derive pub's language major.minor from a bounded original SDK range.

    Dart 3.10.4's pinned pub LanguageVersion.fromSdkConstraint uses the
    ORIGINAL constraint's minimum, including prerelease minima, rather than
    its Dart-3 compatibility adjustment. Unbounded ranges default to 2.7.
    This deliberately supports only ordinary scalar caret/exact/interval
    forms present in the fixed inputs; aliases, unions and complex YAML fail.
    """
    require(type(raw) is bytes and len(raw) <= 512 * 1024, 'P15_PUBSPEC_BOUND')
    lines = raw.decode('utf-8').splitlines()
    headers = [i for i, line in enumerate(lines) if re.match(r'^environment\s*:', line)]
    require(len(headers) <= 1, 'P15_PUBSPEC_ENVIRONMENT')
    if not headers:
        return '2.7'
    index = headers[0]
    require(re.fullmatch(r'environment:\s*(?:#[^\n]*)?', lines[index]), 'P15_PUBSPEC_ENVIRONMENT')
    members = []
    for line in lines[index + 1:]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')):
            break
        require('\t' not in line, 'P15_PUBSPEC_ENVIRONMENT')
        members.append(line)
    if not members:
        return '2.7'
    indentation = min(len(line) - len(line.lstrip(' ')) for line in members)
    sdk_values = []
    for line in members:
        if len(line) - len(line.lstrip(' ')) != indentation:
            continue
        match = re.fullmatch(r' {' + str(indentation) + r'}([A-Za-z][A-Za-z0-9_]*):\s*(.*)', line)
        require(match is not None, 'P15_PUBSPEC_ENVIRONMENT')
        if match[1] == 'sdk':
            scalar = re.fullmatch(r'''("[^"\n]*"|'[^'\n]*'|[^#\n]+?)\s*(?:#[^\n]*)?''', match[2])
            require(scalar is not None, 'P15_PUBSPEC_SDK_SCALAR')
            value = scalar[1].strip()
            if value.startswith(('"', "'")):
                value = value[1:-1]
            sdk_values.append(value)
    require(len(sdk_values) <= 1, 'P15_PUBSPEC_SDK_DUPLICATE')
    if not sdk_values or sdk_values[0] == 'any':
        return '2.7'
    constraint = sdk_values[0]
    version = r'((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)'
    exact = re.fullmatch(r'\^?' + version, constraint)
    if exact:
        return '.'.join(exact[1].split('.')[:2])
    tokens = list(re.finditer(r'(>=|>|<=|<)\s*' + version, constraint))
    require(0 < len(tokens) <= 2 and ''.join(re.sub(r'\s+', '', t[0]) for t in tokens)
            == re.sub(r'\s+', '', constraint), 'P15_PUBSPEC_SDK_UNSUPPORTED')
    lower = [t[2] for t in tokens if t[1] in ('>=', '>')]
    upper = [t[2] for t in tokens if t[1] in ('<=', '<')]
    require(len(lower) <= 1 and len(upper) <= 1, 'P15_PUBSPEC_SDK_UNSUPPORTED')
    return '.'.join(lower[0].split('.')[:2]) if lower else '2.7'


def tool_state_files(directory):
    """The original nonworkspace `pub get --no-precompile` writes two files.

    No workspace redirect, generated code, nested state or extra package map
    receives execution authority merely by being inside a writable overlay.
    """
    directory = Path(directory)
    owned_directory(directory)
    paths = []
    with os.scandir(directory) as iterator:
        for entry in iterator:
            require(len(paths) < 2, 'P15_TOOL_STATE_FILE_SET')
            paths.append(directory / entry.name)
    require({path.name for path in paths} == {'package_config.json', 'package_graph.json'},
            'P15_TOOL_STATE_FILE_SET')
    for path in paths:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 2 * 1024**2,
                'P15_TOOL_STATE_FILE_METADATA')


def generated_binding(stage, sdk, cache, entries, *, logical_cache=Path('/state/pub-cache'),
                      config_directory=None, root_name='overmorrow'):
    stage = Path(stage)
    logical_config = stage / '.dart_tool/package_config.json'
    config = (Path(config_directory) if config_directory is not None else logical_config.parent) / 'package_config.json'
    owned_directory(config.parent)
    if root_name == 'flutter_tools':
        tool_state_files(config.parent)
    value = I.document(I.read(config, 2 * 1024**2))
    require(type(value) is dict and set(value) <= {'configVersion', 'packages', 'generated', 'generator',
                'generatorVersion', 'flutterRoot', 'flutterVersion', 'pubCache'}
            and value.get('configVersion') == 2 and type(value.get('packages')) is list
            and value.get('generator') == 'pub' and value.get('generatorVersion') == '3.10.4',
            'P15_PACKAGE_CONFIG_SCHEMA')
    require(root_name in ('overmorrow', 'flutter_tools'), 'P15_GENERATED_ROOT')
    expected = dict(entries, **{root_name: dict(source='root')})
    found = set()
    for package in value['packages']:
        require(type(package) is dict and set(package) == {'name', 'rootUri', 'packageUri', 'languageVersion'},
                'P15_PACKAGE_CONFIG_ENTRY')
        name = package['name']
        require(name in expected and name not in found and package['packageUri'] == 'lib/'
                and type(package['languageVersion']) is str
                and re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}', package['languageVersion']), 'P15_PACKAGE_CONFIG_ENTRY')
        found.add(name)
        entry = expected[name]
        root = uri_path(logical_config.parent, package['rootUri'])
        authorized = (stage if name == root_name else sdk / SDK_PATHS[name] if entry['source'] == 'sdk'
                      else logical_cache / 'hosted/pub.dev' / (name + '-' + entry['version']))
        require(root == authorized, 'P15_PACKAGE_CONFIG_ROOT')
        physical = (stage if name == root_name else sdk / SDK_PATHS[name] if entry['source'] == 'sdk'
                    else Path(cache) / 'hosted/pub.dev' / (name + '-' + entry['version']))
        require(package['languageVersion'] == pubspec_language(I.read(physical / 'pubspec.yaml', 512 * 1024)),
                'P15_PACKAGE_LANGUAGE_CHANGED')
    require(found == set(expected), 'P15_PACKAGE_CONFIG_SET')
    for field, allowed in (('flutterRoot', sdk), ('pubCache', logical_cache)):
        if field in value:
            require(uri_path(logical_config.parent, value[field]) == allowed, 'P15_PACKAGE_CONFIG_METADATA')
    if 'flutterVersion' in value:
        require(value['flutterVersion'] == '3.38.5', 'P15_PACKAGE_CONFIG_METADATA')
    graph_path = config.with_name('package_graph.json')
    graph_digest = None
    if graph_path.exists() or graph_path.is_symlink():
        raw = I.read(graph_path, 2 * 1024**2)
        graph = I.document(raw)
        require(type(graph) is dict and set(graph) == {'roots', 'packages', 'configVersion'}
                and graph['configVersion'] == 1 and graph['roots'] == [root_name]
                and type(graph['packages']) is list, 'P15_PACKAGE_GRAPH_SCHEMA')
        names = set()
        for package in graph['packages']:
            require(type(package) is dict and {'name', 'version', 'dependencies'} <= set(package)
                    and set(package) <= {'name', 'version', 'dependencies', 'devDependencies', 'source'}
                    and package['name'] in expected and package['name'] not in names, 'P15_PACKAGE_GRAPH_ENTRY')
            name = package['name']
            names.add(name)
            root_version = '2.6.4+64' if root_name == 'overmorrow' else '0.0.0'
            require(package['version'] == (root_version if name == root_name else entries[name]['version']),
                    'P15_PACKAGE_GRAPH_VERSION')
            for key in ('dependencies', 'devDependencies'):
                values = package.get(key, [])
                require(type(values) is list and len(values) == len(set(values))
                        and all(dependency in expected for dependency in values), 'P15_PACKAGE_GRAPH_DEPENDENCY')
            if 'source' in package:
                require(package['source'] == ('root' if name == root_name else entries[name]['source']),
                        'P15_PACKAGE_GRAPH_SOURCE')
        require(names == set(expected), 'P15_PACKAGE_GRAPH_SET')
        graph_digest = I.sha(raw)
    return dict(package_config_sha256=I.sha(I.read(config, 2 * 1024**2)),
                package_graph_sha256=graph_digest, packages=len(found), exact_authorized_roots=True)


def plugin_binding(stage, cache, entries, *, logical_cache=Path('/state/pub-cache')):
    """Bind generated plugin names/platforms/roots to original app cache sources."""
    path = Path(stage) / '.flutter-plugins-dependencies'
    raw = I.read(path, 2 * 1024**2)
    value = I.document(raw)
    require(type(value) is dict and set(value) == {'info', 'plugins', 'dependencyGraph', 'date_created',
                'version', 'swift_package_manager_enabled'}
            and value['info'] == 'This is a generated file; do not edit or check into version control.'
            and value['version'] == '3.38.5' and type(value['date_created']) is str
            and 0 < len(value['date_created']) <= 64
            and type(value['plugins']) is dict and set(value['plugins']) == {'ios', 'android', 'macos', 'linux', 'windows', 'web'}
            and type(value['swift_package_manager_enabled']) is dict
            and set(value['swift_package_manager_enabled']) == {'ios', 'macos'}
            and all(type(v) is bool for v in value['swift_package_manager_enabled'].values()), 'P15_PLUGIN_SCHEMA')
    plugin_sources = {}
    for name, entry in entries.items():
        if entry['source'] != 'hosted':
            continue
        source = I.read(Path(cache) / 'hosted/pub.dev' / (name + '-' + entry['version']) / 'pubspec.yaml', 512 * 1024)
        # This recognizes only the pinned, standard nested plugin declaration.
        # It does not run YAML constructors or accept caller-selected plugins.
        text = source.decode('utf-8')
        flutter = re.search(r'(?m)^flutter:\s*(?:#[^\n]*)?\n((?:[ \t].*(?:\n|$)|\n)*)', text)
        if flutter and re.search(r'(?m)^  plugin:\s*(?:#[^\n]*)?$', flutter[1]):
            plugin_sources[name] = flutter[1]
    total = 0
    for platform, rows in value['plugins'].items():
        require(type(rows) is list and len(rows) <= len(entries), 'P15_PLUGIN_LIST')
        seen = set()
        for row in rows:
            require(type(row) is dict and {'name', 'path', 'dependencies', 'dev_dependency'} <= set(row)
                    and set(row) <= {'name', 'path', 'dependencies', 'dev_dependency', 'native_build', 'shared_darwin_source'}
                    and row['name'] in plugin_sources and row['name'] not in seen
                    and type(row['dev_dependency']) is bool, 'P15_PLUGIN_ENTRY')
            name = row['name']
            seen.add(name)
            require(re.search(r'(?m)^      ' + re.escape(platform) + r':\s*(?:#[^\n]*)?$', plugin_sources[name]),
                    'P15_PLUGIN_PLATFORM_SOURCE')
            root = logical_cache / 'hosted/pub.dev' / (name + '-' + entries[name]['version'])
            require(type(row['path']) is str and Path(os.path.normpath(row['path'])) == root
                    and '\\' not in row['path'], 'P15_PLUGIN_ROOT')
            for flag in ('native_build', 'shared_darwin_source'):
                require(flag not in row or type(row[flag]) is bool, 'P15_PLUGIN_FLAG')
            require(type(row['dependencies']) is list and len(row['dependencies']) == len(set(row['dependencies']))
                    and all(n in plugin_sources for n in row['dependencies']), 'P15_PLUGIN_DEPENDENCIES')
            total += 1
    require(type(value['dependencyGraph']) is list and len(value['dependencyGraph']) <= len(entries), 'P15_PLUGIN_GRAPH')
    seen = set()
    for row in value['dependencyGraph']:
        require(type(row) is dict and set(row) == {'name', 'dependencies'} and row['name'] in plugin_sources
                and row['name'] not in seen and type(row['dependencies']) is list
                and len(row['dependencies']) == len(set(row['dependencies']))
                and all(n in plugin_sources for n in row['dependencies']), 'P15_PLUGIN_GRAPH')
        seen.add(row['name'])
    return dict(sha256=I.sha(raw), platform_entries=total, graph_entries=len(seen),
                exact_authorized_package_roots=True, plugin_source_declarations_bound=True)


def verify(cache, sdk, stage=None, *, tool_state=None, logical_cache=Path('/state/pub-cache')):
    cache, sdk = Path(cache), Path(sdk)
    require(stage is None or tool_state is not None, 'P15_TOOL_STATE_REQUIRED')
    owned_directory(cache)
    entries, packages = fixed_inputs()
    tool, tool_record, sdk_binding = tool_inputs(sdk)
    union = union_inputs(entries, packages, tool, tool_record)
    maps_raw = I.read(private_map(cache), MAX_MAP_BYTES)
    maps = I.document(maps_raw)
    require(type(maps) is dict and set(maps) == set(union), 'P15_PRIVATE_MAP_SET')
    cache_names = {p.name for p in directory_paths(cache, 4)}
    require({'hosted', 'hosted-hashes'} <= cache_names
            and cache_names <= {'hosted', 'hosted-hashes', 'active_roots', '_temp'}, 'P15_UNKNOWN_CACHE_ENTRY')
    if '_temp' in cache_names:
        owned_directory(cache / '_temp')
        require(not directory_paths(cache / '_temp', 1), 'P15_PUB_TEMP_NOT_EMPTY')
    for parent in (cache / 'hosted', cache / 'hosted-hashes'):
        owned_directory(parent)
        require({p.name for p in directory_paths(parent, 1)} == {'pub.dev'}, 'P15_UNKNOWN_CACHE_HOST')
    hosted, hashes = cache / 'hosted/pub.dev', cache / 'hosted-hashes/pub.dev'
    owned_directory(hosted)
    owned_directory(hashes)
    names = set(union)
    require({p.name for p in directory_paths(hosted, 225)} - {'.cache'} == names, 'P15_UNKNOWN_PACKAGE')
    require({p.name for p in directory_paths(hashes, 224)} == {name + '.sha256' for name in names}, 'P15_UNKNOWN_HASH_MARKER')
    hook_count = 0
    for basename, item in sorted(union.items()):
        files = maps[basename]
        require(I.sha(I.canonical(files)) == item['archive']['files_sha256'], 'P15_PRIVATE_MAP_CHANGED')
        lifecycle(files, item['archive']['sha256'])
        hook_count += sum(files.get(name, {}).get('type') == 'file' for name in ('hook/build.dart', 'hook/link.dart'))
        verify_package(hosted / basename, files)
        require(I.read(hashes / (basename + '.sha256'), 64) == item['input']['sha256'].encode(), 'P15_HASH_MARKER_CHANGED')
    metadata_count = cache_metadata(hosted, dict(entries, **tool))
    active_count = active_roots(cache, sdk, stage)
    generated = generated_binding(stage, sdk, cache, entries, logical_cache=logical_cache) if stage is not None else None
    tool_generated = generated_binding(sdk / 'packages/flutter_tools', sdk, cache, tool,
        logical_cache=logical_cache, config_directory=tool_state, root_name='flutter_tools') if tool_state is not None else None
    plugins = plugin_binding(stage, cache, entries, logical_cache=logical_cache) if stage is not None else None
    return dict(schema=1, kind='p15-locked-pub-reverification', app_hosted_packages=152,
                tool_hosted_packages=101, union_hosted_packages=224, sdk_references=5,
                member_maps_sha256=I.sha(maps_raw), original_package_files_unchanged=True,
                lifecycle_hooks_found=hook_count, lifecycle_hooks_authorized=hook_count,
                exact_package_set=True, metadata_files=metadata_count, active_roots=active_count,
                generated_binding=generated, tool_generated_binding=tool_generated, plugin_binding=plugins,
                tool_lock_sha256=TOOL_LOCK_SHA, tool_input_record_sha256=TOOL_INPUTS_SHA,
                sdk_inventory_sha256=sdk_binding['inventory_sha256'], production_authority=False)
