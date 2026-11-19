#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Client input validation and explicit disposable hosted environment inventory.

Candidates never grant build or consumer authority. The data-candidate mode
executes no dependency/SDK/plugin/maintainer code. The separate installed mode
provisions only fixed reviewed packages and captures unadmitted installed state.
"""
import argparse
import importlib.util
import base64
import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'third_party/hosted-client-inputs-v1.json'
# Package provisioning is a separate, narrower authority than build admission.
# No CLI record, digest, URL or profile override is accepted.
PACKAGE_INPUTS = {
    'drizzli': ('client-package-inputs-drizzli-v1.json', '775192250323cb74dd0e1f07c77fd4ab9a7c45706a8e0436e88f7eafa9fdd0d0'),
    'overmorrow': ('client-package-inputs-overmorrow-v1.json', '42fa6761fa56b2b7beb80a493100ec3d65ffd7c61a47e23622d735e874e1328e'),
}
MAX_JSON = 64 * 1024**2
MAX_ARCHIVE = 96 * 1024**2
MAX_EXPANDED = 512 * 1024**2
MAX_MEMBER = 128 * 1024**2
# Parser resource exception, not permission to execute this native module.
# The fixed archive SHA256 also binds its original reviewed lockfile SRI.
LIX_ARCHIVE_SHA256 = '44776b0a99ac3e441c87c1079dc7055ba7b813f8a605ad88b874f83145aeaa6e'
LIX_MEMBER = 'lix_js_sdk.node'  # npm's normalized package/ member name
LIX_MEMBER_BYTES = 272305120
NPM_TARGET = dict(os='linux', cpu='x64', libc='glibc')
NPM_INACTIVE_RECORD = ROOT / 'third_party/client-npm-inactive-v1.json'
NPM_INACTIVE_SHA256 = '108d1659868109a98290c16e5f2e8bb4b60ee1297af89e2bc857e3f1997a3b0b'
# npm 11.17.0, npm/cli commit 5866280804c68682d9cfd839e1902f6929ce333e,
# node_modules/npm-install-checks/lib/index.js checkPlatform/checkList.
# Original source SHA256 2372095fc73982184f77759432935af6259b51201c750464fe7ed52033ab0640.
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?'
NAME = r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+'
SOURCES = {
    'drizzli': dict(commit='d2a6839e2b3f2e561b849d83014fc5959bed39cc',
        lock='package-lock.json', sha256='9b04f44d254fff82180b32716353c2e7b4e444de7da26cd3fad7eb92512f3454',
        url='https://raw.githubusercontent.com/open-meteo/drizz.li/d2a6839e2b3f2e561b849d83014fc5959bed39cc/package-lock.json'),
    'overmorrow': dict(commit='97995e2e00e454389e00e35f1e65654afe3e8bed',
        lock='pubspec.lock', sha256='fdfb5275aac49a1a62f7424a665f88b7db6fe1314d1e7c9f037ad6d32d906ce3',
        url='https://raw.githubusercontent.com/bmaroti9/Overmorrow/97995e2e00e454389e00e35f1e65654afe3e8bed/pubspec.lock'),
}
SDK_COMMIT = 'f6ff1529fd6d8af5f706051d9251ac9231c83407'
SDK_PACKAGES = frozenset(('flutter', 'flutter_test', 'flutter_web_plugins', 'sky_engine', 'integration_test', 'flutter_localizations'))


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'DUPLICATE_KEY')
        value[key] = item
    return value


def document(raw):
    require(type(raw) is bytes and len(raw) <= MAX_JSON, 'JSON_BOUND')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: require(False, 'JSON_CONSTANT'))


def read(path, bound=MAX_JSON):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid in (0, os.getuid())
                and not info.st_mode & 0o022 and 0 <= info.st_size <= bound, 'UNSAFE_INPUT')
        raw = stream.read(bound + 1)
    require(len(raw) <= bound, 'INPUT_BOUND')
    return raw


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def write(path, raw):
    require(len(raw) <= MAX_JSON, 'OUTPUT_BOUND')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def safe_path(name):
    require(type(name) is str and 0 < len(name) <= 1024 and '\\' not in name
        and all(32 <= ord(c) < 127 for c in name) and not name.startswith('/')
        and all(p not in ('', '.', '..') for p in name.split('/')), 'INPUT_PATH')
    return name


def sri(value):
    require(type(value) is str and re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==', value), 'NPM_SRI')
    decoded = base64.b64decode(value[7:], validate=True)
    require(len(decoded) == 64 and base64.b64encode(decoded).decode() == value[7:], 'NPM_SRI')
    return decoded


def npm_archive(name, version, url, integrity):
    require(type(name) is str and re.fullmatch(NAME, name) and type(version) is str
        and re.fullmatch(VERSION, version) and 'snapshot' not in version.lower()
        and all(part not in ('.', '..') and not part.startswith('.') for part in name.split('/')), 'NPM_IDENTITY')
    expected = f'https://registry.npmjs.org/{name}/-/{name.split("/")[-1]}-{version}.tgz'
    require(url == expected, 'NPM_ORIGIN')
    sri(integrity)
    return dict(name=name, version=version, url=url, integrity=integrity)


def npm_target_selection(entry):
    require(type(entry) is dict and type(entry.get('optional', False)) is bool, 'NPM_OPTIONAL_TYPE')
    selectors, unsupported = {}, []
    for key, target in NPM_TARGET.items():
        if key not in entry:
            continue
        raw = entry[key]
        require(type(raw) is str or type(raw) is list, 'NPM_SELECTOR_TYPE')
        values = [raw] if type(raw) is str else raw
        require(len(values) <= 64 and all(type(value) is str and
            re.fullmatch(r'!?[a-z0-9][a-z0-9_-]{0,31}', value) for value in values), 'NPM_SELECTOR_VALUE')
        selectors[key] = raw if type(raw) is str else list(raw)
        # Match npm's string/list, singleton 'any', negative veto, positive
        # membership and all-negative/empty-list semantics for valid selectors.
        supported = values == ['any'] or (('!' + target) not in values and
            (target in values or all(value.startswith('!') for value in values)))
        if not supported:
            unsupported.append(key)
    optional = entry.get('optional', False)
    require(not unsupported or optional, 'NPM_REQUIRED_PLATFORM_UNSUPPORTED')
    return dict(target=dict(NPM_TARGET), optional=optional, selectors=selectors,
                included=not unsupported, unsupported=unsupported)


def npm_inactive_inputs():
    raw = read(NPM_INACTIVE_RECORD, 16384)
    require(sha(raw) == NPM_INACTIVE_SHA256, 'NPM_INACTIVE_INPUT_CHANGED')
    value = document(raw)
    require(type(value) is dict and set(value) == {'schema', 'kind', 'admitted', 'profile', 'lock_sha256',
        'target', 'npm_version', 'npm_source_commit', 'installation', 'packages', 'limitations'}
        and type(value['schema']) is int and value['schema'] == 1 and value['admitted'] is False
        and value['kind'] == 'volparossa-weather-npm-inactive-optional-inputs' and value['profile'] == 'drizzli'
        and value['lock_sha256'] == '9b04f44d254fff82180b32716353c2e7b4e444de7da26cd3fad7eb92512f3454'
        and value['target'] == NPM_TARGET and value['npm_version'] == '11.17.0'
        and value['npm_source_commit'] == '5866280804c68682d9cfd839e1902f6929ce333e'
        and value['installation'] == 'source-inference-pending-disposable-npm-ci'
        and type(value['limitations']) is list and all(type(v) is str for v in value['limitations']),
        'NPM_INACTIVE_INPUT_SCHEMA')
    packages = value['packages']
    require(type(packages) is dict and set(packages) == {'node_modules/@tailwindcss/oxide-linux-x64-musl',
        'node_modules/lightningcss-linux-x64-musl'}, 'NPM_INACTIVE_INPUT_SET')
    for path, item in packages.items():
        require(type(item) is dict and set(item) == {'name', 'version', 'url', 'integrity', 'archive_bytes',
            'archive_sha256', 'package_json_bytes', 'package_json_sha256', 'locked_selectors', 'archive_selectors'}
            and item['name'] == path.removeprefix('node_modules/')
            and type(item['archive_bytes']) is int and 0 < item['archive_bytes'] <= MAX_ARCHIVE
            and type(item['package_json_bytes']) is int and 0 < item['package_json_bytes'] <= 512 * 1024
            and all(type(item[k]) is str and re.fullmatch(r'[0-9a-f]{64}', item[k]) for k in
                    ('archive_sha256', 'package_json_sha256'))
            and item['locked_selectors'] == dict(os=['linux'], cpu=['x64'])
            and item['archive_selectors'] == dict(os=['linux'], cpu=['x64'], libc=['musl']), 'NPM_INACTIVE_INPUT')
        npm_archive(item['name'], item['version'], item['url'], item['integrity'])
    return packages


def npm_lock(raw):
    value = document(raw)
    require(type(value) is dict and type(value.get('lockfileVersion')) is int and value['lockfileVersion'] == 3
        and type(value.get('packages')) is dict and 1 < len(value['packages']) <= 4096
        and type(value['packages'].get('')) is dict, 'NPM_LOCK_SCHEMA')
    result, inactive = {}, npm_inactive_inputs()
    for path, entry in value['packages'].items():
        if not path:
            continue  # root dependency ranges are not resolved archive versions
        safe_path(path)
        parts = path.split('node_modules/')
        require(parts[0] == '' and all(re.fullmatch(NAME + r'/?', p) for p in parts[1:])
            and type(entry) is dict and not any(k in entry for k in ('link', 'inBundle')),
            'NPM_PACKAGE_PATH_OR_LINK')
        name = path.rsplit('node_modules/', 1)[1]
        require(entry.get('name', name) == name, 'NPM_ALIAS')
        record = npm_archive(name, entry.get('version'), entry.get('resolved'), entry.get('integrity'))
        record['optional'] = entry.get('optional', False)
        record.update({key: entry[key] for key in NPM_TARGET if key in entry})
        npm_target_selection(record)  # Validate all entries before acquisition.
        if path in inactive:
            pin = inactive[path]
            require(all(record[k] == pin[k] for k in ('name', 'version', 'url', 'integrity'))
                and record['optional'] is True
                and {key: record[key] for key in NPM_TARGET if key in record} == pin['locked_selectors'],
                'NPM_INACTIVE_LOCK_BINDING')
            record['inactive_optional_data'] = True
        result[path] = record
    return result


def reject_excluded_npm_modules(paths, packages):
    """Required by future installed-tree verification; never an admission alone."""
    require(type(paths) in (list, tuple, dict) and len(paths) <= 200000, 'NPM_INSTALLED_TREE_BOUND')
    excluded = [path for path, entry in packages.items() if not npm_target_selection(entry)['included']]
    for name in paths:
        safe_path(name)
        require(not any(name == path or name.startswith(path + '/') for path in excluded),
                'EXCLUDED_NPM_MODULE_PRESENT')


def reject_inactive_npm_contributions(paths, packages):
    """For future loaded-module/output evidence, distinct from installed data."""
    require(type(paths) in (list, tuple, dict) and len(paths) <= 200000, 'NPM_MODULE_EVIDENCE_BOUND')
    inactive = [path for path, entry in packages.items() if entry.get('inactive_optional_data') is True]
    for name in paths:
        safe_path(name)
        require(not any(name == path or name.startswith(path + '/') for path in inactive),
                'INACTIVE_NPM_MODULE_CONTRIBUTION')


def scalar(text):
    # Exact generated pub lock subset, not general YAML: no anchors, tags,
    # aliases, multiline values, comments, coercion or duplicate mappings.
    if text.startswith('"'):
        value = json.loads(text)
        require(type(value) is str, 'PUB_SCALAR')
        return value
    require(re.fullmatch(r'[A-Za-z0-9_.+ -]+', text) is not None, 'PUB_SCALAR')
    return text


def pub_lock(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 1024**2, 'PUB_BOUND')
    packages, sdks, current, description = {}, {}, None, False
    section = None
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        require('\t' not in line and len(line) <= 4096, 'PUB_LINE')
        if line in ('packages:', 'sdks:'):
            new = line[:-1]
            require((section is None and new == 'packages') or (section == 'packages' and new == 'sdks'), 'PUB_SECTION')
            section, current = new, None
            continue
        match = re.fullmatch(r'  ([a-zA-Z0-9_]+):(?: (.+))?', line)
        if match:
            name, value = match.groups()
            if section == 'sdks':
                require(name not in sdks and value is not None, 'PUB_SDK_DUPLICATE')
                sdks[name] = scalar(value)
            else:
                require(section == 'packages' and value is None and name not in packages and len(packages) < 1024, 'PUB_PACKAGE')
                current = packages[name] = {}
                description = False
            continue
        match = re.fullmatch(r'(    |      )([a-z0-9_]+):(.*)', line)
        require(section == 'packages' and current is not None and match is not None, 'PUB_SYNTAX')
        indent, key, text = match.groups()
        if indent == '    ':
            description = key == 'description' and text == ''
            target = current
        else:
            require(description and type(current.get('description')) is dict, 'PUB_DESCRIPTION')
            target = current['description']
        require(key not in target, 'PUB_DUPLICATE')
        require(text == '' or text.startswith(' '), 'PUB_SYNTAX')
        target[key] = {} if description and indent == '    ' else scalar(text[1:])
    require(section == 'sdks' and set(sdks) == {'dart', 'flutter'} and packages, 'PUB_SDKS')
    result = {}
    for name, item in packages.items():
        require(set(item) == {'dependency', 'description', 'source', 'version'}
            and item['dependency'] in ('transitive', 'direct main', 'direct dev')
            and re.fullmatch(VERSION, item['version']), 'PUB_ENTRY')
        if item['source'] == 'sdk':
            require(name in SDK_PACKAGES and item['description'] == 'flutter', 'PUB_SDK_SOURCE')
            result[name] = dict(source='sdk', version=item['version'], sdk_commit=SDK_COMMIT)
        else:
            desc = item['description']
            require(item['source'] == 'hosted' and type(desc) is dict
                and set(desc) == {'name', 'sha256', 'url'} and desc['name'] == name
                and desc['url'] == 'https://pub.dev' and type(desc['sha256']) is str
                and re.fullmatch(r'[0-9a-f]{64}', desc['sha256']), 'PUB_HOSTED_SOURCE')
            result[name] = dict(source='hosted', version=item['version'], sha256=desc['sha256'],
                url=f'https://pub.dev/api/archives/{name}-{item["version"]}.tar.gz')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('INPUT_REDIRECT_REJECTED')


def fetch(url, maximum, *, sha256=None, integrity=None):
    # URLs are derived only from one validated fixed lock. No proxy or auth env.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(urllib.request.Request(url, headers={'Accept-Encoding': 'identity'}), timeout=30) as response:
        require(response.status == 200 and response.url == url
            and response.headers.get('Content-Encoding', 'identity') == 'identity', 'INPUT_RESPONSE')
        length = response.headers.get('Content-Length')
        require(length is None or (length.isdigit() and 0 < int(length) <= maximum), 'INPUT_LENGTH')
        raw = response.read(maximum + 1)
        require(length is None or len(raw) == int(length), 'INPUT_LENGTH')
    require(0 < len(raw) <= maximum, 'ARCHIVE_BOUND')
    require(sha256 is None or sha(raw) == sha256, 'ARCHIVE_SHA256')
    require(integrity is None or hashlib.sha512(raw).digest() == sri(integrity), 'ARCHIVE_SRI')
    return raw


class BoundedGzip:
    def __init__(self, raw):
        self.stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
        self.total = 0

    def read(self, size):
        require(type(size) is int and 0 < size <= MAX_MEMBER, 'ARCHIVE_READ_BOUND')
        raw = self.stream.read(min(size, MAX_EXPANDED + 1 - self.total))
        self.total += len(raw)
        require(self.total <= MAX_EXPANDED, 'ARCHIVE_EXPANSION_BOUND')
        return raw


def approved_large_member(archive_sha256, name, size, npm):
    return (npm is True and archive_sha256 == LIX_ARCHIVE_SHA256
            and name == LIX_MEMBER and size == LIX_MEMBER_BYTES)


def archive_inventory(raw, *, npm, npm_name=None):
    """Hash all members as data; never extract, import, load or execute them."""
    require(type(npm) is bool and len(raw) <= MAX_ARCHIVE, 'ARCHIVE_BOUND')
    require(npm_name is None or (npm is True and type(npm_name) is str and re.fullmatch(NAME, npm_name)),
            'NPM_ARCHIVE_IDENTITY')
    archive_sha256 = sha(raw)
    files, total, npm_root = {}, 0, None
    with tarfile.open(fileobj=BoundedGzip(raw), mode='r|') as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/') if member.isdir() else member.name.removeprefix('./')
            if name in ('', '.') and member.isdir():
                continue
            safe_path(name)
            if npm:
                prefix, separator, relative = name.partition('/')
                roots = {'package'}
                if npm_name is not None and npm_name.startswith('@types/'):
                    roots.add(npm_name.split('/')[1])
                require(prefix in roots and (npm_root is None or prefix == npm_root), 'NPM_ARCHIVE_ROOT')
                npm_root = prefix
                if not separator and member.isdir():
                    continue
                require(separator, 'NPM_ARCHIVE_ROOT')
                name = relative
            require(name not in files and len(files) < 100000, 'ARCHIVE_MEMBERS')
            require(member.isdir() or member.isreg(), 'ARCHIVE_LINK_OR_SPECIAL')
            if member.isdir():
                files[name] = dict(type='directory')
                continue
            require(0 <= member.size <= MAX_MEMBER or
                approved_large_member(archive_sha256, name, member.size, npm), 'ARCHIVE_MEMBER_BOUND')
            total += member.size
            require(total <= MAX_EXPANDED, 'ARCHIVE_EXPANSION_BOUND')
            stream = archive.extractfile(member)
            checksum, size, notice = hashlib.sha256(), 0, bytearray()
            package_json = npm and name == 'package.json'
            keep = package_json or bool(re.fullmatch(r'(?:[^/]+/)*(?:licen[cs]e|copying|notice|copyright)(?:\.[A-Za-z0-9_.-]+)?', name, re.I))
            while chunk := stream.read(65536):
                size += len(chunk)
                require(size <= member.size, 'ARCHIVE_MEMBER_SIZE')
                checksum.update(chunk)
                if keep and size <= 512 * 1024:
                    notice.extend(chunk)
            require(size == member.size, 'ARCHIVE_MEMBER_SIZE')
            item = dict(type='file', bytes=size, sha256=checksum.hexdigest(), executable=bool(member.mode & 0o111))
            if keep:
                require(size <= 512 * 1024, 'NOTICE_BOUND')
                if package_json:
                    item['package_json'] = document(bytes(notice))
                else:
                    item['notice_text'] = notice.decode('utf-8')
            files[name] = item
    require(files, 'EMPTY_ARCHIVE')
    require(not npm or type(files.get('package.json', {}).get('package_json')) is dict, 'NPM_PACKAGE_JSON_MISSING')
    return dict(bytes=len(raw), sha256=archive_sha256, expanded_bytes=total, files=files,
                **(dict(npm_root=npm_root) if npm else {}))


def prepare_source_stage(profile, stage):
    """Source changes only, before execution; historical stage remains separate."""
    require(profile in SOURCES and stage.resolve() == stage and stage.parent == ROOT / 'build', 'SOURCE_STAGE')
    receipt = dict(schema=1, kind='client-source-stage', admitted=False, profile=profile, compiled=False)
    if profile == 'drizzli':
        config = stage / 'vite.config.ts'
        raw = read(config, 32768)
        require(sha(raw) == '0c9545f12f38b29b4ed85467b8a75bf6a31ae8a3a7bbc8873f4b00c52dae42ce', 'VITE_CONFIG_SOURCE_CHANGED')
        require(raw.count(b'plugins: [') == 1, 'VITE_PLUGIN_LOCATION')
        patched = b"import sourceModuleGraph from './volparossa-source-module-graph.mjs';\n" + raw.replace(
            b'plugins: [', b'plugins: [sourceModuleGraph(),', 1)
        observer = read(ROOT / 'integrations/drizzli/source-module-graph.mjs')
        write(stage / 'volparossa-source-module-graph.mjs', observer)
        fd = os.open(config, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(patched)
        receipt.update(config_sha256=sha(patched), observer_sha256=sha(observer))
    else:
        value, _ = notice_inputs()
        target = stage / 'volparossa-source-notices'
        target.mkdir(mode=0o700)
        for item in value['fonts'].values():
            for key in ('notice', 'attribution'):
                if key in item:
                    write(target / Path(item[key]).name, read(ROOT / item[key]))
        receipt.update(material_icons_policy='require-unchanged-full-font-before-build-and-in-output',
            required_web_flag='--no-tree-shake-icons',
            flutter_notices_policy='preserve-complete-generated-assets/NOTICES')
    write(stage / 'volparossa-source-stage.json', canonical(receipt))
    return receipt


def notice_inputs():
    value = document(read(ROOT / 'third_party/client-notices-v1.json'))
    require(type(value) is dict and value.get('schema') == 1
        and value.get('kind') == 'volparossa-weather-client-notice-inputs'
        and value.get('admitted') is False, 'NOTICE_INPUT_SCHEMA')
    npm = value['npm']
    bundle = read(ROOT / npm['bundle'])
    require(sha(bundle) == npm['bundle_sha256'], 'NOTICE_BUNDLE_CHANGED')
    for digest, item in npm['records'].items():
        require(type(item['offset']) is int and type(item['bytes']) is int
            and 0 <= item['offset'] and 0 < item['bytes'] <= 512 * 1024
            and item['offset'] + item['bytes'] <= len(bundle)
            and digest == item['sha256']
            and sha(bundle[item['offset']:item['offset'] + item['bytes']]) == digest, 'ORIGINAL_NOTICE_CHANGED')
    for item in value['fonts'].values():
        raw = read(ROOT / item['notice'])
        require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'FONT_NOTICE_CHANGED')
        if 'attribution' in item:
            require(sha(read(ROOT / item['attribution'])) == item['attribution_sha256'], 'FONT_ATTRIBUTION_CHANGED')
    return value, bundle


def graph_notice_closure(graphs, packages):
    """Determine emitted dependency notices; unknown virtual producers block.

    This data validator never admits a graph or authorizes its executable code.
    A subsequent reviewed source lock must map virtual modules to their exact
    plugin/source bytes; this first observer deliberately records null owners.
    """
    inputs, bundle = notice_inputs()
    needed = {}
    require(type(graphs) is list and 0 < len(graphs) <= 16, 'GRAPH_COUNT')
    for graph in graphs:
        require(type(graph) is dict and set(graph) == {'schema', 'kind', 'admitted', 'format', 'plugins', 'outputs'}
            and type(graph['schema']) is int and graph['schema'] == 1
            and graph['kind'] == 'volparossa-drizzli-module-graph' and graph['admitted'] is False
            and graph['format'] in ('es', 'cjs', 'iife') and type(graph['plugins']) is list
            and all(type(p) is str and len(p) <= 256 for p in graph['plugins'])
            and type(graph['outputs']) is dict and 0 < len(graph['outputs']) <= 8192, 'GRAPH_SCHEMA')
        for name, output in graph['outputs'].items():
            safe_path(name)
            require(type(output) is dict and output.get('type') in ('chunk', 'asset'), 'GRAPH_OUTPUT')
            if output['type'] == 'asset':
                continue  # Final output tree inventories CSS/fonts/copied assets separately.
            require(type(output.get('modules')) is list and len(output['modules']) <= 100000, 'GRAPH_MODULE_BOUND')
            for module in output['modules']:
                require(type(module) is dict and module.get('kind') in ('file', 'virtual')
                    and type(module.get('id')) is str and len(module['id']) <= 8192
                    and type(module.get('renderedLength')) is int and module['renderedLength'] >= 0, 'GRAPH_MODULE')
                require(module['kind'] != 'virtual', 'UNREVIEWED_VIRTUAL_MODULE')
                path = module['id'].split('?', 1)[0]
                safe_path(path)
                if not path.startswith('node_modules/'):
                    continue
                matches = [p for p in packages if path.startswith(p + '/')]
                require(matches, 'UNLOCKED_OUTPUT_MODULE')
                package = packages[max(matches, key=len)]
                require(npm_target_selection(package)['included'], 'EXCLUDED_NPM_MODULE_PRESENT')
                require(not package.get('inactive_optional_data'), 'INACTIVE_NPM_MODULE_CONTRIBUTION')
                if module['renderedLength'] == 0:
                    continue
                component = inputs['npm']['components'].get(package['name'])
                require(component is not None and component['version'] == package['version']
                    and component['integrity'] == package['integrity'] and component['notices'], 'UNRESOLVED_RUNTIME_NOTICE')
                for digest in component['notices']:
                    item = inputs['npm']['records'][digest]
                    needed[digest] = bundle[item['offset']:item['offset'] + item['bytes']]
    return needed


def output_inventory(root):
    """Complete output map, including CSS/copied assets, kept separate from logs."""
    require(root.resolve() == root and root.is_dir(), 'OUTPUT_ROOT')
    files, scanned, total = {}, 0, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            scanned += 1
            require(scanned <= 50000, 'OUTPUT_COUNT')
            path = Path(directory) / name
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'OUTPUT_LINK_OR_SPECIAL')
            require(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'OUTPUT_OWNER_OR_MODE')
            if stat.S_ISREG(info.st_mode):
                raw = read(path, 128 * 1024**2)
                total += len(raw)
                require(total <= 512 * 1024**2, 'OUTPUT_TOTAL_BOUND')
                files[safe_path(str(path.relative_to(root)))] = dict(bytes=len(raw), sha256=sha(raw), mode=stat.S_IMODE(info.st_mode))
    require(files, 'OUTPUT_EMPTY')
    return files


def full_material_font(sdk, output=None):
    value, _ = notice_inputs()
    item = value['fonts']['MaterialIcons']
    raw = read(sdk / 'bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf', 2 * 1024**2)
    require(len(raw) == item['font_bytes'] and sha(raw) == item['font_sha256'], 'MATERIAL_FONT_NOT_PINNED')
    if output is not None:
        emitted = read(output / 'assets/fonts/MaterialIcons-Regular.otf', 2 * 1024**2)
        require(emitted == raw, 'MATERIAL_FONT_MODIFIED')
    return dict(bytes=len(raw), sha256=sha(raw), modified=False, license='CC-BY-4.0')


def load_build_lock(profile):
    """Only the fixed checked-in reviewed record can authorize new execution."""
    require(profile in SOURCES, 'CLIENT_PROFILE')
    value = document(read(LOCK))  # missing is fatal, no producer/hash override
    require(type(value) is dict and set(value) == {'schema', 'kind', 'admitted', 'review', 'profiles'}
        and type(value['schema']) is int and value['schema'] == 1
        and value['kind'] == 'volparossa-weather-client-input-lock' and value['admitted'] is True
        and type(value['review']) is dict and set(value['review']) == {'commit', 'candidate_sha256'}
        and re.fullmatch(r'[0-9a-f]{40}', value['review']['commit'])
        and re.fullmatch(r'[0-9a-f]{64}', value['review']['candidate_sha256'])
        and type(value['profiles']) is dict and set(value['profiles']) == set(SOURCES), 'CLIENT_LOCK_NOT_ADMITTED')
    entry = value['profiles'][profile]
    require(type(entry) is dict and set(entry) == {'source', 'packages', 'environment_lock_sha256', 'runtime_inputs'}
        and entry['source'] == SOURCES[profile] and type(entry['packages']) is dict and entry['packages']
        and re.fullmatch(r'[0-9a-f]{64}', entry['environment_lock_sha256'])
        and type(entry['runtime_inputs']) is dict and entry['runtime_inputs'], 'CLIENT_LOCK_INPUTS')
    # Inventory is not yet an execution API. Callers must additionally bind
    # every installed input byte and environment before launching a compiler.
    return entry


def load_package_inputs(profile):
    require(profile in SOURCES and profile in PACKAGE_INPUTS, 'PACKAGE_INPUTS_NOT_REVIEWED')
    filename, digest = PACKAGE_INPUTS[profile]
    raw = read(ROOT / 'third_party' / filename)
    require(sha(raw) == digest, 'PACKAGE_INPUTS_CHANGED')
    value = document(raw)
    require(type(value) is dict and set(value) == {'schema', 'kind', 'id', 'profile', 'admitted',
        'package_inputs_authorized', 'build_environment_admitted', 'consumer_admitted', 'source', 'target',
        'review', 'apt', 'dependencies', 'runtime_inputs', 'limitations'}
        and type(value['schema']) is int and value['schema'] == 1
        and value['kind'] == 'volparossa-weather-client-package-inputs'
        and value['profile'] == profile and value['source'] == SOURCES[profile]
        and value['package_inputs_authorized'] is True and value['admitted'] is False
        and value['build_environment_admitted'] is False and value['consumer_admitted'] is False
        and value['target'] == NPM_TARGET, 'PACKAGE_INPUTS_SCHEMA')
    # Runtime records are references only here; this mode never executes them.
    for filename, pin in value['runtime_inputs'].items():
        require(filename in ('third_party/hosted-runtime-inputs.json', 'third_party/hosted-runtime-npm.json',
            'integrations/overmorrow/upstream.json'), 'PACKAGE_RUNTIME_RECORD')
        raw = read(ROOT / filename)
        require(pin == dict(bytes=len(raw), sha256=sha(raw)), 'PACKAGE_RUNTIME_CHANGED')
    return value


def candidate(profile, output, *, downloader=fetch):
    require(profile in SOURCES, 'CLIENT_PROFILE')
    source = SOURCES[profile]
    raw = downloader(source['url'], 2 * 1024**2, sha256=source['sha256'])
    require(sha(raw) == source['sha256'], 'SOURCE_LOCK_CHANGED')
    entries = npm_lock(raw) if profile == 'drizzli' else pub_lock(raw)
    inactive = npm_inactive_inputs() if profile == 'drizzli' else {}
    write(output / source['lock'], raw)
    result, plugins, started, total = {}, {}, time.monotonic(), 0
    current = None
    try:
        for name, entry in sorted(entries.items()):
            current = name
            require(time.monotonic() - started < 900, 'CANDIDATE_DEADLINE')
            if entry.get('source') == 'sdk':
                result[name] = entry
                continue
            selection = npm_target_selection(entry) if profile == 'drizzli' else None
            if selection is not None and not selection['included']:
                result[name] = dict(input=entry, status='excluded-for-target', selection=selection)
                continue
            kwargs = {'integrity': entry['integrity']} if profile == 'drizzli' else {'sha256': entry['sha256']}
            data = downloader(entry['url'], MAX_ARCHIVE, **kwargs)
            total += len(data)
            require(total <= 512 * 1024**2, 'CANDIDATE_DOWNLOAD_BOUND')
            inventory = archive_inventory(data, npm=profile == 'drizzli',
                                          npm_name=entry['name'] if profile == 'drizzli' else None)
            if profile == 'drizzli':
                manifest = inventory['files']['package.json']['package_json']
                require(manifest.get('name') == entry['name'] and manifest.get('version') == entry['version'], 'NPM_ARCHIVE_IDENTITY')
                actual_selection = npm_target_selection(dict(manifest, optional=entry['optional']))
                if name in inactive:
                    pin, package_json = inactive[name], inventory['files']['package.json']
                    require(not actual_selection['included'] and inventory['sha256'] == pin['archive_sha256']
                        and inventory['bytes'] == pin['archive_bytes']
                        and package_json['sha256'] == pin['package_json_sha256']
                        and package_json['bytes'] == pin['package_json_bytes']
                        and actual_selection['selectors'] == pin['archive_selectors'], 'NPM_INACTIVE_ARCHIVE_BINDING')
                    result[name] = dict(input=entry, archive=inventory, status='inactive-optional-data',
                        selection=selection, archive_target_selection=actual_selection,
                        selector_input_sha256=NPM_INACTIVE_SHA256,
                        npm_installation='source-inference-pending-disposable-npm-ci')
                else:
                    require(actual_selection['included'], 'NPM_ARCHIVE_TARGET_MISMATCH')
                    result[name] = dict(input=entry, archive=inventory, status='acquired', selection=selection,
                                       archive_target_selection=actual_selection)
            else:
                result[name] = dict(input=entry, archive=inventory)
        if profile == 'drizzli':
            current = 'plugin-metadata'
            for p in document(read(ROOT / 'integrations/drizzli/build-plugins.json'))['plugins']:
                current = 'plugin:' + p['local_name']
                require(time.monotonic() - started < 900, 'CANDIDATE_DEADLINE')
                entry = npm_archive(p['name'], p['version'], p['url'], p['integrity'])
                data = downloader(entry['url'], MAX_ARCHIVE, integrity=entry['integrity'])
                total += len(data)
                require(total <= 512 * 1024**2, 'CANDIDATE_DOWNLOAD_BOUND')
                inventory = archive_inventory(data, npm=True, npm_name=entry['name'])
                manifest = inventory['files']['package.json']['package_json']
                require(manifest.get('name') == entry['name'] and manifest.get('version') == entry['version'], 'NPM_PLUGIN_IDENTITY')
                npm_target_selection(dict(manifest, optional=False))
                plugins[p['local_name']] = dict(input=entry, archive=inventory)
    except BaseException:
        write(output / 'dependency-candidate.partial.json', canonical(dict(schema=1,
            kind='client-dependency-partial-candidate', admitted=False, profile=profile, source=source,
            packages=result, plugins=plugins, failed_input=current, compiled=False, dependencies_executed=False)))
        raise
    value = dict(schema=1, kind='volparossa-weather-client-input-candidate', admitted=False,
        profile=profile, source=source, packages=result, plugins=plugins,
        **(dict(target=dict(NPM_TARGET), npm_version='11.17.0') if profile == 'drizzli' else {}),
        compiled=False, dependencies_executed=False, environment_admitted=False,
        required_reviews=['signed-ubuntu-package-closure', 'package-member-inventory', 'runtime-input-closure',
                          'actual-output-module-graph', 'complete-original-notices'] +
                         (['disposable-npm-ci-installation-state', 'inactive-native-modules-not-loaded-or-emitted']
                          if profile == 'drizzli' else []))
    write(output / 'dependency-candidate.json', canonical(value))
    return value


def hosted_guard(environment, profile):
    require(profile in SOURCES and os.getuid() == os.geteuid() != 0, 'ORDINARY_HOSTED_RUNNER_REQUIRED')
    required = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
        GITHUB_REPOSITORY='VOLPAROSSA/volparossa-weather', GITHUB_WORKSPACE=str(ROOT), RUNNER_ARCH='X64',
        GITHUB_WORKFLOW='Build hosted Weather clients' if profile == 'drizzli' else 'Build hosted Overmorrow client')
    require(all(environment.get(k) == v for k, v in required.items())
        and re.fullmatch(r'[0-9a-f]{40}', environment.get('GITHUB_SHA', '')), 'DISPOSABLE_CANDIDATE_CONTEXT')
    require(all(type(environment.get(key)) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', environment[key])
        for key in ('ImageOS', 'ImageVersion')), 'RUNNER_IMAGE_VERSION_REQUIRED')
    release = Path('/etc/os-release').read_text()
    require('ID=ubuntu' in release.splitlines() and 'VERSION_ID="24.04"' in release.splitlines(), 'UBUNTU_24_REQUIRED')


PUBLIC_NAMES = frozenset(('dependency-candidate.json', 'dependency-candidate.partial.json', 'apt-candidate.json', 'source-binding.json', 'bootstrap-observations.json',
    'installer-simulation-started.json', 'installer-install-started.json',
    'installer-simulation-stdout.log', 'installer-install-stdout.log',
    'installed-environment.json', 'installed-before.json', 'installer-simulation-cleanup.json',
    'installer-install-cleanup.json', 'installer-simulation-stderr.log', 'installer-install-stderr.log', 'installed-packages-before.tsv',
    'installed-packages-after.tsv', 'install-simulation.log', 'install.log', 'provisioning-bootstrap.json', 'installer-companions.json',
    'installer-cache-before.json', 'installer-cache-after.json',
    'runtime-boundary-started.json', 'runtime-boundary.json', 'runtime-boundary-cleanup.json', 'runtime-boundary-diagnostics.json',
    'result.json', 'apt-update.log', 'apt-failure.log', 'apt-resolver.log', 'runner-packages.tsv', 'package-lock.json', 'pubspec.lock',
    'noble.InRelease', 'noble-updates.InRelease', 'noble-security.InRelease',
    'noble.signature.log', 'noble-updates.signature.log', 'noble-security.signature.log'))


def project_metadata(profile):
    require(profile in SOURCES, 'CLIENT_PROFILE')
    source = ROOT / 'build' / ('hosted-' + profile + '-input-candidate')
    destination = source.with_name(source.name + '-public')
    require(source.resolve() == source and source.is_dir() and source.parent.resolve() == source.parent, 'CANDIDATE_ROOT')
    destination.mkdir(mode=0o700)
    files, total = {}, 0
    for name in sorted(PUBLIC_NAMES):
        path = source / name
        if not path.exists() and not path.is_symlink():
            continue  # Partial failure evidence is allowed; no success fabricated.
        raw = read(path)
        total += len(raw)
        require(total <= 96 * 1024**2, 'PUBLIC_METADATA_BOUND')
        if name in ('package-lock.json', 'pubspec.lock'):
            # Original upstream locks have their own schema. Preserve their
            # bytes and require the fixed source identity, not candidate fields.
            require(name == SOURCES[profile]['lock']
                and sha(raw) == SOURCES[profile]['sha256'], 'PUBLIC_SOURCE_LOCK')
            raw.decode('utf-8')
        elif name.endswith('.json'):
            value = document(raw)
            require(type(value) is dict and value.get('admitted') is False, 'PUBLIC_CANDIDATE_AUTHORITY')
        else:
            raw.decode('utf-8')
        write(destination / name, raw)
        files[name] = dict(bytes=len(raw), sha256=sha(raw))
    require('result.json' in files, 'CANDIDATE_RESULT_REQUIRED')
    write(destination / 'projection.json', canonical(dict(schema=1, kind='closed-client-input-metadata',
        admitted=False, files=files, binaries_exported=False)))
    return destination


def interrupted(_signum, _frame):
    raise InterruptedError('CLIENT_INPUT_INTERRUPTED')


def remove_empty_installer_partial(source):
    # APT's privileged cache lock changes this existing directory to
    # _apt:root 0700. Its runner-owned parent permits rmdir without opening or
    # changing the inaccessible child. Only an empty fixed directory qualifies.
    import pwd
    allowed = {0, os.getuid()}
    try:
        allowed.add(pwd.getpwnam('_apt').pw_uid)
    except KeyError:
        pass
    descriptors = []
    try:
        require(source.is_absolute() and source.resolve(strict=True) == source, 'CANDIDATE_ROOT')
        descriptors.append(os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for name in ('apt-private', 'archives'):
            info = os.fstat(descriptors[-1])
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'CANDIDATE_CACHE_PARENT')
            try:
                descriptors.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptors[-1]))
            except FileNotFoundError:
                return  # No installer cache was materialized.
        cache = descriptors[-1]
        info = os.fstat(cache)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'CANDIDATE_CACHE_PARENT')
        try:
            info = os.stat('partial', dir_fd=cache, follow_symlinks=False)
        except FileNotFoundError:
            return  # Idempotent after an interrupted later rmtree.
        observation = dict(schema=1, admitted=False, action='remove-empty-installer-cache-partial',
            uid=info.st_uid, gid=info.st_gid, mode=stat.S_IMODE(info.st_mode), privileged=False)
        print(canonical(observation).decode(), flush=True)
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid in allowed and info.st_gid in (0, os.getgid()), 'CANDIDATE_CACHE_PARTIAL')
        anchors = [(source.lstat(), os.fstat(descriptors[0]))]
        anchors += [(os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(child))
            for parent, name, child in zip(descriptors, ('apt-private', 'archives'), descriptors[1:])]
        require(all(stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) ==
            (opened.st_dev, opened.st_ino) for observed, opened in anchors), 'CANDIDATE_CACHE_REPLACED')
        current = os.stat('partial', dir_fd=cache, follow_symlinks=False)
        require((current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid) ==
            (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid), 'CANDIDATE_CACHE_PARTIAL_REPLACED')
        os.rmdir('partial', dir_fd=cache)  # Atomic empty-directory check; never follows a symlink.
        try:
            os.stat('partial', dir_fd=cache, follow_symlinks=False)
        except FileNotFoundError:
            print(canonical(dict(observation, removed=True, absent=True)).decode(), flush=True)
        else:
            require(False, 'CANDIDATE_CACHE_PARTIAL_REPLACED')
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def cleanup_candidate(profile):
    # Retain runner-local recovery data if privileged installer cleanup is
    # unconfirmed. Never publish that private directory as a fallback.
    import shutil
    source = ROOT / 'build' / ('hosted-' + profile + '-input-candidate')
    require(source.parent.resolve() == source.parent, 'CANDIDATE_ROOT')
    if source.exists() or source.is_symlink():
        require(source.resolve() == source and source.is_dir(), 'CANDIDATE_ROOT')
        for label in ('simulation', 'install'):
            marker = source / ('installer-' + label + '-started.json')
            if marker.exists() or marker.is_symlink():
                document(read(marker))
                receipt = document(read(source / ('installer-' + label + '-cleanup.json')))
                require(receipt.get('owned_session_drained') is True and receipt.get('leader_reaped') is True,
                    'INSTALLER_CLEANUP_UNCONFIRMED')
        runtime_marker = source / 'runtime-boundary-started.json'
        if runtime_marker.exists() or runtime_marker.is_symlink():
            document(read(runtime_marker))
            receipt = document(read(source / 'runtime-boundary-cleanup.json'))
            require(receipt.get('process_drain_confirmed') is True and receipt.get('policy_removed') is True,
                'RUNTIME_BOUNDARY_CLEANUP_UNCONFIRMED')
        remove_empty_installer_partial(source)
        shutil.rmtree(source)
    public = source.with_name(source.name + '-public')
    if public.exists() or public.is_symlink():
        require(public.resolve() == public and public.is_dir(), 'CANDIDATE_ROOT')
        shutil.rmtree(public)
    require(not source.exists() and not source.is_symlink() and not public.exists() and not public.is_symlink(),
        'CANDIDATE_CLEANUP_INCOMPLETE')
    print(canonical(dict(schema=1, admitted=False, kind='client-input-data-cleanup',
        private_absent=True, public_absent=True, privileged_cleanup=False)).decode(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=SOURCES, required=True)
    parser.add_argument('--mode', choices=('source-input-inventory', 'installed-environment-inventory',
        'runtime-boundary-verification', 'stage-input-metadata', 'cleanup-input-data'), required=True)
    args = parser.parse_args()
    hosted_guard(os.environ, args.profile)
    os.umask(0o077)
    if args.mode == 'cleanup-input-data':
        cleanup_candidate(args.profile)
        return
    if args.mode == 'stage-input-metadata':
        project_metadata(args.profile)
        return
    require(args.mode != 'runtime-boundary-verification' or args.profile == 'overmorrow', 'BOUNDARY_FULL_PROFILE_REQUIRED')
    package_inputs = load_package_inputs(args.profile) if args.mode in (
        'installed-environment-inventory', 'runtime-boundary-verification') else None
    output = ROOT / 'build' / ('hosted-' + args.profile + '-input-candidate')
    info = output.parent.lstat()
    require(output.parent.resolve() == output.parent and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid() and not info.st_mode & 0o022, 'BUILD_PARENT')
    output.mkdir(mode=0o700)
    write(output / 'source-binding.json', canonical(dict(schema=1, admitted=False,
        weather_commit=os.environ['GITHUB_SHA'], run_id=os.environ.get('GITHUB_RUN_ID'),
        run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), profile=args.profile,
        recipes={name: sha(read(ROOT / 'scripts' / name)) for name in
            ('prepare_hosted_client_inputs.py', 'prepare_hosted_client_apt.py',
             'prepare_hosted_client_runtime.py', 'prepare_hosted_source_recipe.py')})))
    phase, failure = 'ubuntu-package-closure', None
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in handlers:
        signal.signal(sig, interrupted)
    try:
        spec = importlib.util.spec_from_file_location('_client_apt', ROOT / 'scripts/prepare_hosted_client_apt.py')
        apt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(apt)
        if package_inputs is not None:
            phase = 'installed-environment-inventory'
            apt.installed_inventory(args.profile, output, package_inputs)
            if args.mode == 'runtime-boundary-verification':
                phase = 'runtime-boundary-verification'
                spec = importlib.util.spec_from_file_location('_runtime_boundary', ROOT / 'scripts/prepare_hosted_client_runtime.py')
                boundary = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(boundary)
                boundary.verify(output)
        else:
            apt.candidate('web' if args.profile == 'drizzli' else 'flutter', output)
            phase = 'source-and-dependencies'
            candidate(args.profile, output)
        phase = 'complete'
    except BaseException as error:
        failure = dict(category=type(error).__name__,
            code=str(error) if isinstance(error, (ValueError, InterruptedError)) and re.fullmatch(r'[A-Z_]{1,80}', str(error)) else 'CLIENT_INPUT_ACQUISITION_FAILED')
        raise
    finally:
        try:
            write(output / 'result.json', canonical(dict(schema=1, kind='client-input-inventory-result',
                profile=args.profile, mode=args.mode, phase=phase, failure=failure, admitted=False, compiled=False, production_authority=False)))
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    main()
