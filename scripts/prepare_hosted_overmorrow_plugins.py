#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P15 data-only plugin identity proof, shared by host and compile Boundary.

No path obtained from a link is opened. Only the exact pinned producer spelling
is admitted, then the separately authorized target is walked without following
links. Linux O_PATH/readlinkat binds the immutable link inode itself. The same
code checks the namespace's target against the host's original cache identities.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

POLICY_SHA = 'e30efbcab48d215b1a545727d075a63692b8bbca5b23d6c09d629b07838b2d9e'
LOGICAL_CACHE = '/state/pub-cache'
PLAN_NAME = 'p15-plugin-input.json'
MAX_PLAN = 8 * 1024**2
MAX_FILE = 256 * 1024**2
MAX_MEMBERS = 10000
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class PluginFailure(ValueError):
    def __init__(self, code, alias=None, target=None):
        super().__init__(code)
        self.plugin_failure = dict(code=code, alias=alias['path'] if alias else 'unknown',
            package=alias['package'] if alias else 'unknown',
            representation=('absolute' if target.startswith('/') else 'relative') if target is not None else 'unobserved',
            target_bytes=len(os.fsencode(target)) if target is not None else 0,
            target_sha256=sha(os.fsencode(target)) if target is not None else sha(b''))


def need(ok, code, alias=None, target=None):
    if not ok:
        raise PluginFailure(code, alias, target)


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'P15_PLUGIN_JSON_DUPLICATE')
        result[key] = value
    return result


def document(raw):
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: need(False, 'P15_PLUGIN_JSON_NUMBER'))


def identity(info):
    return [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_uid]


def stable(info):
    return identity(info) + [info.st_size, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns]


def components(path, absolute=False):
    need(type(path) is str and 0 < len(path) <= 4096 and '\\' not in path
         and '\x00' not in path and path.startswith('/') is absolute, 'P15_PLUGIN_PATH')
    parts = path.split('/')[1:] if absolute else path.split('/')
    need(0 < len(parts) <= 64 and all(p not in ('', '.', '..') for p in parts), 'P15_PLUGIN_PATH')
    return parts


@contextmanager
def directory(parent, name, *, owned=False, private=False):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    need(stat.S_ISDIR(before.st_mode), 'P15_PLUGIN_DIRECTORY_TYPE')
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        info = os.fstat(fd)
        need(identity(info) == identity(before), 'P15_PLUGIN_DIRECTORY_SWAP')
        if owned:
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022
                 and (not private or stat.S_IMODE(info.st_mode) == 0o700), 'P15_PLUGIN_DIRECTORY_METADATA')
        yield fd
        need(identity(os.fstat(fd)) == identity(info)
             and identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity(info),
             'P15_PLUGIN_DIRECTORY_SWAP')
    finally:
        os.close(fd)


@contextmanager
def absolute_directory(path, *, expected=None, capture=None):
    parts = components(path, absolute=True)
    root = os.open('/', DIR_FLAGS)
    def remember(prefix, fd):
        ident = identity(os.fstat(fd))
        if capture is not None:
            capture[prefix] = ident
        if expected is not None:
            need(ident == expected.get(prefix), 'P15_PLUGIN_DIRECTORY_SWAP')
    def descend(parent, index):
        if index == len(parts):
            yield parent
        else:
            with directory(parent, parts[index]) as child:
                remember('/' + '/'.join(parts[:index + 1]), child)
                yield from descend(child, index + 1)
    try:
        remember('/', root)
        yield from descend(root, 0)
    finally:
        os.close(root)


@contextmanager
def relative_directory(parent, path, *, private=False):
    parts = components(path)
    def descend(fd, index):
        if index == len(parts):
            yield fd
        else:
            with directory(fd, parts[index], owned=True, private=private) as child:
                yield from descend(child, index + 1)
    yield from descend(parent, 0)


def names(fd, expected):
    actual, count = set(), 0
    # Opening '.' creates a fresh directory offset, without resolving an input.
    scanfd = os.open('.', DIR_FLAGS, dir_fd=fd)
    try:
        with os.scandir(scanfd) as entries:
            for entry in entries:
                need(count < len(expected), 'P15_PLUGIN_EXTRA_ENTRY')
                count += 1
                need(entry.name not in actual, 'P15_PLUGIN_DUPLICATE_ENTRY')
                actual.add(entry.name)
        need(actual == set(expected), 'P15_PLUGIN_ENTRY_SET')
    finally:
        os.close(scanfd)


def read_file(parent, name, limit, *, mode=0o600, expected_identity=None):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
         and stat.S_IMODE(before.st_mode) == mode and before.st_size <= limit, 'P15_PLUGIN_FILE_METADATA')
    if expected_identity is not None:
        need(identity(before) == expected_identity, 'P15_PLUGIN_FILE_SWAP')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        info = os.fstat(fd)
        need(stable(info) == stable(before), 'P15_PLUGIN_FILE_SWAP')
        data = bytearray()
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            need(len(data) <= limit, 'P15_PLUGIN_FILE_BOUND')
        need(stable(os.fstat(fd)) == stable(info)
             and stable(os.stat(name, dir_fd=parent, follow_symlinks=False)) == stable(info),
             'P15_PLUGIN_FILE_SWAP')
        return bytes(data), identity(info)
    finally:
        os.close(fd)


def policy(raw):
    need(len(raw) <= 1024**2 and sha(raw) == POLICY_SHA, 'P15_PLUGIN_POLICY_CHANGED')
    value = document(raw)
    need(value['schema'] == 1 and value['kind'] == 'p15-overmorrow-plugin-inputs'
         and value['plugin_inputs_authorized'] is True and value['production_authority'] is False,
         'P15_PLUGIN_POLICY_SCHEMA')
    for name, item in value['packages'].items():
        need(sha(canonical(item['files'])) == item['archive']['files_sha256']
             and item['files']['pubspec.yaml']['sha256'] == item['pubspec_sha256']
             and item['input']['version'] == item['version']
             and item['input']['sha256'] == item['archive']['sha256'], 'P15_PLUGIN_PACKAGE_BINDING')
    for alias in value['aliases']:
        item = value['packages'][alias['package']]
        root = LOGICAL_CACHE + '/hosted/pub.dev/' + alias['package'] + '-' + item['version']
        need(alias['canonical_target'] == root and alias['target'] == root + '/'
             and alias['path'] == alias['platform'] + '/flutter/ephemeral/.plugin_symlinks/' + alias['package']
             and alias['platform'] in ('windows', 'linux'), 'P15_PLUGIN_ALIAS_POLICY')
    return value


def package_nodes(parent, item, baseline=None):
    files = item['files']
    need(0 < len(files) <= MAX_MEMBERS, 'P15_PLUGIN_MEMBER_BOUND')
    children = {'': {}}
    for path, member in files.items():
        parts = components(path)
        need(member['type'] in ('file', 'directory'), 'P15_PLUGIN_MEMBER_TYPE')
        for index, name in enumerate(parts):
            base = '/'.join(parts[:index])
            kind = member['type'] if index == len(parts) - 1 else 'directory'
            need(name not in children.setdefault(base, {}) or children[base][name] == kind,
                 'P15_PLUGIN_MEMBER_CONFLICT')
            children[base][name] = kind
            if kind == 'directory':
                children.setdefault('/'.join(parts[:index + 1]), {})
    nodes = {}
    def walk(fd, prefix):
        info = os.fstat(fd)
        need(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid(), 'P15_PLUGIN_DIRECTORY_METADATA')
        nodes[prefix] = identity(info)
        if baseline is not None:
            need(nodes[prefix] == baseline.get(prefix), 'P15_PLUGIN_DIRECTORY_SWAP')
        names(fd, children[prefix])
        for name, kind in sorted(children[prefix].items()):
            relative = prefix + '/' + name if prefix else name
            if kind == 'directory':
                with directory(fd, name, owned=True, private=True) as child:
                    walk(child, relative)
            else:
                member = files[relative]
                need(type(member['bytes']) is int and 0 <= member['bytes'] <= MAX_FILE, 'P15_PLUGIN_MEMBER_BOUND')
                raw, ident = read_file(fd, name, member['bytes'], mode=0o700 if member['executable'] else 0o600,
                    expected_identity=baseline.get(relative) if baseline is not None else None)
                need(len(raw) == member['bytes'] and sha(raw) == member['sha256'], 'P15_PLUGIN_PACKAGE_CHANGED')
                nodes[relative] = ident
        names(fd, children[prefix])
    walk(parent, '')
    need(baseline is None or set(nodes) == set(baseline), 'P15_PLUGIN_PACKAGE_NODE_SET')
    return nodes


def cache_nodes(cache, value, baseline=None):
    result = {}
    with directory(cache, 'hosted', owned=True, private=True) as parent, \
            directory(parent, 'pub.dev', owned=True, private=True) as hosted:
        # Parent identities remain stable while pub may add approved metadata.
        result['hosted'] = identity(os.fstat(parent))
        result['hosted/pub.dev'] = identity(os.fstat(hosted))
        if baseline is not None:
            need(all(result[n] == baseline[n] for n in ('hosted', 'hosted/pub.dev')), 'P15_PLUGIN_DIRECTORY_SWAP')
        for name, item in sorted(value['packages'].items()):
            with directory(hosted, name + '-' + item['version'], owned=True, private=True) as package:
                result[name] = package_nodes(package, item, baseline[name] if baseline is not None else None)
    return result


def alias_nodes(stage, value, enabled, previous=None, source_roots=None):
    result = {}
    for platform in ('windows', 'linux'):
        selected = [a for a in value['aliases'] if a['platform'] == platform]
        if not enabled[platform]:
            continue
        parent_path = platform + '/flutter/ephemeral/.plugin_symlinks'
        @contextmanager
        def chain(fd, parts, prefix=''):
            if not parts:
                yield fd
                return
            relative = prefix + '/' + parts[0] if prefix else parts[0]
            with directory(fd, parts[0], owned=True) as child:
                result[relative] = identity(os.fstat(child))
                if source_roots is not None and relative == platform:
                    need(result[relative] == source_roots[platform], 'P15_PLUGIN_DIRECTORY_SWAP')
                if previous is not None:
                    need(result[relative] == previous.get(relative), 'P15_PLUGIN_DIRECTORY_SWAP')
                with chain(child, parts[1:], relative) as leaf:
                    yield leaf
        with chain(stage, components(parent_path)) as parent:
            names(parent, [a['package'] for a in selected])
            for alias in selected:
                name = alias['package']
                fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    need(stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                         'P15_PLUGIN_LINK_METADATA', alias)
                    raw = os.readlink('', dir_fd=fd)
                    need(raw == alias['target'], 'P15_PLUGIN_SYMLINK_TARGET', alias, raw)
                    need(stable(os.fstat(fd)) == stable(info)
                         and stable(os.stat(name, dir_fd=parent, follow_symlinks=False)) == stable(info),
                         'P15_PLUGIN_LINK_SWAP', alias)
                    result[alias['path']] = identity(info)
                    if previous is not None:
                        need(result[alias['path']] == previous.get(alias['path']), 'P15_PLUGIN_LINK_SWAP', alias)
                finally:
                    os.close(fd)
            names(parent, [a['package'] for a in selected])
    need(previous is None or set(result) == set(previous), 'P15_PLUGIN_ALIAS_SET')
    return result


def validate(plan, *, namespace=False, seal=False):
    value = policy(plan['policy_raw'].encode())
    baseline = plan['baseline']
    need(seal or plan['alias_baseline'] is not None, 'P15_PLUGIN_NOT_SEALED')
    with absolute_directory(plan['stage'], expected=None if namespace else baseline['host_ancestors']['stage']) as stage, \
            absolute_directory(LOGICAL_CACHE if namespace else plan['cache'],
                expected=None if namespace else baseline['host_ancestors']['cache']) as cache:
        need(identity(os.fstat(stage)) == baseline['stage'] and identity(os.fstat(cache)) == baseline['cache'],
             'P15_PLUGIN_NAMESPACE_IDENTITY')
        cache_nodes(cache, value, baseline['packages'])
        raw, _ = read_file(stage, '.flutter-plugins-dependencies', 2 * 1024**2)
        manifest = document(raw)
        for platform, rows in value['manifest'].items():
            expected = [dict(row, path=LOGICAL_CACHE + '/hosted/pub.dev/' + row['name'] + '-'
                        + value['packages'][row['name']]['version'] + '/') for row in rows]
            need(canonical(manifest['plugins'][platform]) == canonical(expected), 'P15_PLUGIN_METADATA_CHANGED')
        aliases = alias_nodes(stage, value, plan['enabled'], None if seal else plan['alias_baseline'], baseline['source_roots'])
    # No absolute host paths or inode numbers enter the exported proof.
    receipt = dict(schema=1, kind='p15-plugin-identity-proof', policy_sha256=POLICY_SHA,
        namespace_identity_verified=namespace, package_membermaps_verified=True,
        original_file_identities_verified=True, exact_alias_set=True,
        aliases=[dict(alias=a['path'], package=a['package'], version=value['packages'][a['package']]['version'],
                 representation='absolute-directory-uri', archive_sha256=value['packages'][a['package']]['archive']['sha256'],
                 membermap_sha256=value['packages'][a['package']]['archive']['files_sha256'])
                 for a in value['aliases'] if plan['enabled'][a['platform']]],
        plugin_metadata_sha256=sha(raw))
    return receipt, aliases


class Binding:
    def __init__(self, stage, cache, policy_raw):
        value = policy(policy_raw)
        self.plan = dict(schema=1, stage=str(stage), cache=str(cache), policy_raw=policy_raw.decode(),
                         enabled={}, baseline={}, alias_baseline=None)
        chains = dict(stage={}, cache={})
        with absolute_directory(str(stage), capture=chains['stage']) as source, \
                absolute_directory(str(cache), capture=chains['cache']) as packages:
            baseline = dict(stage=identity(os.fstat(source)), cache=identity(os.fstat(packages)),
                            packages=cache_nodes(packages, value), source_roots={}, host_ancestors=chains)
            need(os.fstat(source).st_uid == os.getuid() and not os.fstat(source).st_mode & 0o022
                 and os.fstat(packages).st_uid == os.getuid()
                 and stat.S_IMODE(os.fstat(packages).st_mode) == 0o700, 'P15_PLUGIN_ROOT_METADATA')
            for platform, condition in value['platform_conditions'].items():
                try:
                    with relative_directory(source, platform) as root:
                        baseline['source_roots'][platform] = identity(os.fstat(root))
                        enabled = not condition['source_files'] or stat.S_ISREG(os.stat(
                            'CMakeLists.txt', dir_fd=root, follow_symlinks=False).st_mode)
                except FileNotFoundError:
                    enabled = False
                self.plan['enabled'][platform] = enabled
        self.plan['baseline'] = baseline
        self.input_identity = self.input_sha = None

    def seal(self):
        need(self.plan['alias_baseline'] is None, 'P15_PLUGIN_ALREADY_SEALED')
        receipt, aliases = validate(self.plan, seal=True)
        self.plan['alias_baseline'] = aliases
        return receipt

    def verify(self):
        need(self.plan['alias_baseline'] is not None, 'P15_PLUGIN_NOT_SEALED')
        return validate(self.plan)[0]

    def check_leaf(self, relative, observed):
        need(self.plan['alias_baseline'] is not None and relative in self.plan['alias_baseline']
             and identity(observed) == self.plan['alias_baseline'][relative], 'P15_PLUGIN_LINK_SWAP')
        with absolute_directory(self.plan['stage'], expected=self.plan['baseline']['host_ancestors']['stage']) as root:
            need(identity(os.fstat(root)) == self.plan['baseline']['stage'], 'P15_PLUGIN_DIRECTORY_SWAP')
            alias_nodes(root, policy(self.plan['policy_raw'].encode()), self.plan['enabled'],
                        self.plan['alias_baseline'], self.plan['baseline']['source_roots'])

    def write_probe_input(self, private):
        need(self.plan['alias_baseline'] is not None, 'P15_PLUGIN_NOT_SEALED')
        need(str(private) == self.plan['cache'].rsplit('/', 1)[0], 'P15_PLUGIN_PRIVATE_ROOT')
        raw = canonical(self.plan)
        need(len(raw) <= MAX_PLAN, 'P15_PLUGIN_PLAN_BOUND')
        path = Path(private) / PLAN_NAME
        self.input_ancestors = {}
        with absolute_directory(str(private), expected=self.plan['baseline']['host_ancestors']['cache'],
                                capture=self.input_ancestors) as parent:
            fd = os.open(PLAN_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb', closefd=False) as output:
                    output.write(raw)
                self.input_identity = identity(os.fstat(fd))
            finally:
                os.close(fd)
        self.input_sha = sha(raw)
        return path

    def check_probe_input(self, private):
        need(self.input_identity is not None and self.input_sha is not None, 'P15_PLUGIN_PLAN_MISSING')
        with absolute_directory(str(private), expected=self.input_ancestors) as parent:
            raw, _ = read_file(parent, PLAN_NAME, MAX_PLAN, expected_identity=self.input_identity)
            need(sha(raw) == self.input_sha, 'P15_PLUGIN_PLAN_CHANGED')

    def probe_command(self):
        need(self.input_identity is not None, 'P15_PLUGIN_PLAN_MISSING')
        return ['/usr/bin/python3', '-I', '-B', '-c', Path(__file__).read_text(),
                '/state/' + PLAN_NAME, self.input_sha, json.dumps(self.input_identity)]

    def accept_probe(self, raw, expected):
        need(type(raw) is bytes and len(raw) <= 65536, 'P15_PLUGIN_PROBE_BOUND')
        result = document(raw)
        if result.get('success') is False:
            row = result.get('rejection')
            value = policy(self.plan['policy_raw'].encode())
            allowed = {a['path']: a['package'] for a in value['aliases']}
            need(type(row) is dict and set(row) == {'code', 'alias', 'package', 'representation', 'target_bytes', 'target_sha256'}
                 and type(row['code']) is str and row['code'].startswith('P15_PLUGIN_')
                 and len(row['code']) <= 100 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in row['code'])
                 and (row['alias'] == 'unknown' and row['package'] == 'unknown'
                      or allowed.get(row['alias']) == row['package'])
                 and row['representation'] in ('absolute', 'relative', 'unobserved')
                 and type(row['target_bytes']) is int and 0 <= row['target_bytes'] <= 4096
                 and type(row['target_sha256']) is str and len(row['target_sha256']) == 64
                 and all(c in '0123456789abcdef' for c in row['target_sha256']), 'P15_PLUGIN_PROBE_REJECTION_SCHEMA')
            error = PluginFailure(row['code'])
            error.plugin_failure = row
            raise error
        desired = dict(expected, namespace_identity_verified=True)
        need(set(result) == {'success', 'proof'} and result['success'] is True
             and canonical(result['proof']) == canonical(desired), 'P15_PLUGIN_PROBE_BINDING')
        return result['proof']


def main():
    need(len(sys.argv) == 4 and sys.argv[1] == '/state/' + PLAN_NAME, 'P15_PLUGIN_PROBE_ARGUMENTS')
    with absolute_directory('/state') as parent:
        raw, _ = read_file(parent, PLAN_NAME, MAX_PLAN, expected_identity=document(sys.argv[3]))
        need(sha(raw) == sys.argv[2], 'P15_PLUGIN_PLAN_CHANGED')
        plan = document(raw)
        private = plan['cache'].rsplit('/', 1)[0]
        need(identity(os.fstat(parent)) == plan['baseline']['host_ancestors']['cache'].get(private),
             'P15_PLUGIN_NAMESPACE_IDENTITY')
        receipt, _ = validate(plan, namespace=True)
        after, _ = read_file(parent, PLAN_NAME, MAX_PLAN, expected_identity=document(sys.argv[3]))
        need(after == raw, 'P15_PLUGIN_PLAN_CHANGED')
    return dict(success=True, proof=receipt)


if __name__ == '__main__':
    try:
        result = main()
    except PluginFailure as error:
        result = dict(success=False, rejection=error.plugin_failure)
    except BaseException:
        result = dict(success=False, rejection=PluginFailure('P15_PLUGIN_PROBE_FAILED').plugin_failure)
    print(canonical(result).decode(), end='')
