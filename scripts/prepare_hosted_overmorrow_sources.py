#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, inert P15 source observations. An observation never admits output.

The private snapshots and deltas contain relative names. Only ``projection`` is
intended for public evidence. Link targets are never opened or published.
"""
import hashlib
import os
from pathlib import Path
import re
import runpy
import stat

P = runpy.run_path(str(Path(__file__).with_name('prepare_hosted_overmorrow_plugins.py')))
MAX_ENTRIES = 20000
MAX_DEPTH = 64
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 1024**3
MAX_HELD_DIRS = 512
MAX_NORMALIZED_FILE = 1024**2
MAX_NORMALIZED_PATHS = 53
MAX_CONTENT_PATHS = 96
MAX_CONTENT_FILE = 1024**2
MAX_CONTENT_TOTAL = 16 * 1024**2
MAX_GIT_FILE = 16 * 1024
ROOT_TOKENS = {'sdk': b'@P15_SDK_ROOT@', 'app': b'@P15_APP_ROOT@'}
KINDS = ('files', 'directories', 'aliases', 'unsafe')
DESKTOP_ALIAS = re.compile(r'(?:linux|windows)/flutter/ephemeral/\.plugin_symlinks/[a-z0-9_]+\Z')
PUB_BUILD_DIRECTORY = re.compile(r'build/[0-9a-f]{32}\Z')
PUB_BUILD_FILE = re.compile(r'build/[0-9a-f]{32}/(?:\.filecache|gen_l10n_inputs_and_outputs\.json|'
                            r'gen_localizations\.d|gen_localizations\.stamp|outputs\.json)\Z')
LOCATIONS = frozenset(('lib', 'assets', 'android', 'ios', 'macos', 'linux', 'windows',
                       'web', 'test', 'integration_test', '.dart_tool', 'build'))


class SourceFailure(ValueError):
    """A bounded public category, without operating-system path diagnostics."""


def need(condition, code):
    if not condition:
        raise SourceFailure(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_relative(path):
    return (type(path) is str and 0 < len(os.fsencode(path)) <= 4096 and path.isascii()
            and all(32 <= ord(c) < 127 for c in path) and '\\' not in path and ':' not in path
            and not path.startswith('/') and len(path.split('/')) <= MAX_DEPTH
            and all(part not in ('', '.', '..') for part in path.split('/')))


def path_label(path, known_paths, kind=None):
    """Allowlisted observation labels do not constitute source authorization."""
    raw = os.fsencode(path)
    safe = safe_relative(path)
    # Diagnostic classification only: these exact producer-derived spellings
    # grant neither source admission nor permission to read/follow any node.
    metadata = (path == 'build/.last_build_id' or PUB_BUILD_FILE.fullmatch(path)
                or PUB_BUILD_DIRECTORY.fullmatch(path)) if safe else False
    if metadata:
        if kind == 'files' and path == 'build/.last_build_id':
            return {'path': path, 'path_sha256': sha(raw)}
        if ((kind == 'files' and PUB_BUILD_FILE.fullmatch(path))
                or (kind == 'directories' and PUB_BUILD_DIRECTORY.fullmatch(path))):
            parts = path.split('/')
            parts[1] = '<pub-build-id>'
            return {'path': '/'.join(parts), 'path_sha256': sha(raw)}
        # Even an explicit observation label cannot disguise a link/special node
        # as a regular metadata file or publish the raw build ID.
    elif safe and path in known_paths:
        return {'path': path}
    first = path.split('/', 1)[0]
    return {'path_sha256': sha(raw), 'path_bytes': len(raw),
            'location': first if first in LOCATIONS else 'other'}


def projection(snapshot, known_paths):
    """Complete redacted inventory; no raw targets, contents or inode IDs."""
    labels = frozenset(known_paths)
    result = {}
    for group in KINDS:
        result[group] = []
        for name, row in sorted(snapshot[group].items()):
            public = path_label(name, labels, group)
            public.update({key: row[key] for key in ('type', 'mode', 'bytes', 'sha256') if key in row})
            result[group].append(public)
    return result


def files(snapshot):
    return {name: row['sha256'] for name, row in snapshot['files'].items()}


def _nodes(snapshot):
    result = {}
    for group in KINDS:
        for name, row in snapshot[group].items():
            need(name not in result, 'P15_SOURCE_DUPLICATE_NODE')
            result[name] = dict(row, kind=group)
    return result


def delta(before, after):
    """Private complete delta, including empty directories and type changes."""
    old, new = _nodes(before), _nodes(after)
    return {
        'added': [{'path': name, 'after': new[name]} for name in sorted(new.keys() - old.keys())],
        'changed': [{'path': name, 'before': old[name], 'after': new[name]}
                    for name in sorted(old.keys() & new.keys()) if old[name] != new[name]],
        'missing': [{'path': name, 'before': old[name]} for name in sorted(old.keys() - new.keys())],
    }


class Inventory:
    def __init__(self, stage):
        self.stage = os.fspath(stage)
        self.ancestors = {}
        self.directories = {}
        self._pins = {}
        self._closed = False
        self._cleanup_ok = True
        self._git_identity = None
        # Open descriptors also prevent a deleted directory inode from being
        # recycled between phases. Metadata comparisons alone cannot do that.
        try:
            parts = P['components'](self.stage, absolute=True)
            parent = os.open('/', P['DIR_FLAGS'])
            self._pins[('ancestor', '/')] = parent
            self.ancestors['/'] = P['identity'](os.fstat(parent))
            for index, part in enumerate(parts):
                with P['directory'](parent, part) as child:
                    prefix = '/' + '/'.join(parts[:index + 1])
                    need(len(self._pins) < MAX_HELD_DIRS, 'P15_SOURCE_DESCRIPTOR_BOUND')
                    pinned = os.open('.', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     dir_fd=child)
                    self._pins[('ancestor', prefix)] = pinned
                    self.ancestors[prefix] = P['identity'](os.fstat(pinned))
                    parent = pinned
            info = os.fstat(parent)
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'P15_SOURCE_DIRECTORY_METADATA')
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self._closed:
            self._closed = True
            for fd in self._pins.values():
                try:
                    os.close(fd)
                except OSError:
                    self._cleanup_ok = False
            self._pins.clear()
        return self._cleanup_ok

    def __enter__(self):
        need(not self._closed, 'P15_SOURCE_INVENTORY_CLOSED')
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if hasattr(self, '_closed'):
            self.close()

    def _file(self, parent, name, before, budget):
        mode = stat.S_IMODE(before.st_mode)
        need(before.st_uid == os.getuid() and before.st_nlink == 1 and not mode & 0o022
             and 0 <= before.st_size <= MAX_FILE, 'P15_SOURCE_FILE_METADATA')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        try:
            info = os.fstat(fd)
            need(P['stable'](info) == P['stable'](before), 'P15_SOURCE_FILE_SWAP')
            digest, size = hashlib.sha256(), 0
            while True:
                limit = min(MAX_FILE - size, MAX_TOTAL - budget['bytes'])
                raw = os.read(fd, min(65536, limit + 1))
                if not raw:
                    break
                size += len(raw)
                budget['bytes'] += len(raw)
                need(size <= MAX_FILE and budget['bytes'] <= MAX_TOTAL, 'P15_SOURCE_BYTE_BOUND')
                digest.update(raw)
            need(size == info.st_size and P['stable'](os.fstat(fd)) == P['stable'](info)
                 and P['stable'](os.stat(name, dir_fd=parent, follow_symlinks=False)) == P['stable'](info),
                 'P15_SOURCE_FILE_SWAP')
            return {'bytes': size, 'sha256': digest.hexdigest(), 'mode': mode}
        finally:
            os.close(fd)

    def _link(self, parent, name, before):
        # O_PATH pins the link itself. readlinkat on its empty descriptor path
        # observes text only and never resolves or opens the named target.
        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            info = os.fstat(fd)
            need(stat.S_ISLNK(info.st_mode) and P['stable'](info) == P['stable'](before),
                 'P15_SOURCE_LINK_SWAP')
            raw = os.fsencode(os.readlink('', dir_fd=fd))
            need(0 < len(raw) <= 4096 and len(raw) == info.st_size, 'P15_SOURCE_LINK_BOUND')
            need(P['stable'](os.fstat(fd)) == P['stable'](info)
                 and P['stable'](os.stat(name, dir_fd=parent, follow_symlinks=False)) == P['stable'](info),
                 'P15_SOURCE_LINK_SWAP')
            return {'type': 'symlink', 'mode': stat.S_IMODE(info.st_mode),
                    'bytes': len(raw), 'sha256': sha(raw)}
        finally:
            os.close(fd)

    def _bind_git_directory(self, fd):
        info = os.fstat(fd)
        ident = P['identity'](info)
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
             'P15_SOURCE_GIT_DIRECTORY')
        key = ('admin', '.git')
        if self._git_identity is None:
            need(len(self._pins) < MAX_HELD_DIRS, 'P15_SOURCE_DESCRIPTOR_BOUND')
            self._pins[key] = os.open('.', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                      dir_fd=fd)
            self._git_identity = ident
        need(ident == self._git_identity == P['identity'](os.fstat(self._pins[key])),
             'P15_SOURCE_GIT_SWAP')

    def git_binding(self):
        """Hash only HEAD/config through the original captured admin directory."""
        need(not self._closed, 'P15_SOURCE_INVENTORY_CLOSED')
        need(self._git_identity is not None, 'P15_SOURCE_GIT_MISSING')
        result = {}
        try:
            with P['absolute_directory'](self.stage, expected=self.ancestors) as root:
                with P['directory'](root, '.git', owned=True) as admin:
                    self._bind_git_directory(admin)
                    for name in ('HEAD', 'config'):
                        info = os.stat(name, dir_fd=admin, follow_symlinks=False)
                        mode = stat.S_IMODE(info.st_mode)
                        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                             and info.st_nlink == 1 and not mode & 0o022
                             and 0 <= info.st_size <= MAX_GIT_FILE, 'P15_SOURCE_GIT_FILE')
                        raw, _ = P['read_file'](admin, name, MAX_GIT_FILE, mode=mode,
                                               expected_identity=P['identity'](info))
                        result[name] = sha(raw)
        except OSError:
            raise SourceFailure('P15_SOURCE_IO') from None
        return result

    def _snapshot_bytes(self, snapshot, name, limit, directory_code, changed_code):
        parts = P['components'](name)
        expected = snapshot['files'][name]
        def read(fd, index):
            if index == len(parts) - 1:
                return P['read_file'](fd, parts[index], limit, mode=expected['mode'])[0]
            prefix = '/'.join(parts[:index + 1])
            need(prefix in self.directories, directory_code)
            with P['directory'](fd, parts[index], owned=True) as child:
                need(P['identity'](os.fstat(child)) == self.directories[prefix]
                     == P['identity'](os.fstat(self._pins[('directory', prefix)])),
                     'P15_SOURCE_DIRECTORY_SWAP')
                return read(child, index + 1)
        try:
            with P['absolute_directory'](self.stage, expected=self.ancestors) as root:
                raw = read(root, 0)
        except OSError:
            raise SourceFailure('P15_SOURCE_IO') from None
        need(len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], changed_code)
        return raw

    def contents(self, snapshot, paths):
        """Private bytes for an explicit caller-reviewed set; never public evidence.

        Syntax and snapshot membership grant no output admission. The caller must
        independently authorize its selection and keep returned bytes private.
        """
        need(not self._closed, 'P15_SOURCE_INVENTORY_CLOSED')
        selected, seen, total = [], set(), 0
        for name in paths:
            need(len(selected) < MAX_CONTENT_PATHS and safe_relative(name) and name not in seen
                 and name in snapshot['files'], 'P15_SOURCE_CONTENTS_PATHS')
            row = snapshot['files'][name]
            need(type(row['bytes']) is int and 0 <= row['bytes'] <= MAX_CONTENT_FILE
                 and type(row['mode']) is int and not row['mode'] & 0o022, 'P15_SOURCE_CONTENTS_FILE')
            total += row['bytes']
            need(total <= MAX_CONTENT_TOTAL, 'P15_SOURCE_CONTENTS_TOTAL')
            selected.append(name)
            seen.add(name)
        result, consumed = {}, 0
        for name in sorted(selected):
            raw = self._snapshot_bytes(snapshot, name, min(MAX_CONTENT_FILE, MAX_CONTENT_TOTAL - consumed),
                                       'P15_SOURCE_CONTENTS_DIRECTORY', 'P15_SOURCE_CONTENTS_CHANGED')
            consumed += len(raw)
            result[name] = raw
        return result

    def normalized(self, snapshot, paths, roots):
        """Observe caller-reviewed files with only the two declared roots masked.

        This data cannot authorize a generated file or a normalization rule. Raw
        bytes, root strings and descriptor identities never enter the result.
        """
        need(not self._closed, 'P15_SOURCE_INVENTORY_CLOSED')
        need(type(roots) is dict and set(roots) == set(ROOT_TOKENS)
             and roots['app'] == self.stage, 'P15_SOURCE_NORMALIZED_ROOTS')
        encoded = {}
        for label, value in roots.items():
            P['components'](value, absolute=True)
            encoded[label] = os.fsencode(value)
            need(not any(token in encoded[label] for token in ROOT_TOKENS.values()),
                 'P15_SOURCE_NORMALIZED_ROOTS')
        need(encoded['app'] != encoded['sdk'], 'P15_SOURCE_NORMALIZED_ROOTS')
        selected, seen = [], set()
        for name in paths:
            need(len(selected) < MAX_NORMALIZED_PATHS and type(name) is str
                 and name not in seen, 'P15_SOURCE_NORMALIZED_PATHS')
            need(path_label(name, {name}) == {'path': name} and name in snapshot['files'],
                 'P15_SOURCE_NORMALIZED_PATHS')
            row = snapshot['files'][name]
            need(type(row['bytes']) is int and 0 <= row['bytes'] <= MAX_NORMALIZED_FILE
                 and type(row['mode']) is int and not row['mode'] & 0o022,
                 'P15_SOURCE_NORMALIZED_FILE')
            selected.append(name)
            seen.add(name)
        result = {}
        for name in sorted(selected):
            raw = self._snapshot_bytes(snapshot, name, MAX_NORMALIZED_FILE,
                                       'P15_SOURCE_NORMALIZED_DIRECTORY', 'P15_SOURCE_NORMALIZED_CHANGED')
            need(not any(token in raw for token in ROOT_TOKENS.values()), 'P15_SOURCE_NORMALIZED_TOKEN')
            normalized, occurrences = raw, {}
            for label in sorted(encoded, key=lambda key: (-len(encoded[key]), key)):
                occurrences[label] = normalized.count(encoded[label])
                normalized = normalized.replace(encoded[label], ROOT_TOKENS[label])
            result[name] = dict(bytes=len(raw), sha256=sha(raw), normalized_sha256=sha(normalized),
                                root_occurrences=occurrences)
        return result

    def capture(self, plugin_aliases=None):
        need(not self._closed, 'P15_SOURCE_INVENTORY_CLOSED')
        result = {group: {} for group in KINDS}
        budget = {'entries': 0, 'bytes': 0}
        observed_directories = {}

        def walk(fd, prefix, depth):
            need(depth <= MAX_DEPTH, 'P15_SOURCE_DEPTH_BOUND')
            before = os.fstat(fd)
            ident = P['identity'](before)
            need(before.st_uid == os.getuid() and not before.st_mode & 0o022,
                 'P15_SOURCE_DIRECTORY_METADATA')
            need(prefix not in self.directories or self.directories[prefix] == ident,
                 'P15_SOURCE_DIRECTORY_SWAP')
            key = ('directory', prefix)
            if key in self._pins:
                need(P['identity'](os.fstat(self._pins[key])) == ident, 'P15_SOURCE_DIRECTORY_SWAP')
            else:
                need(len(self._pins) < MAX_HELD_DIRS, 'P15_SOURCE_DESCRIPTOR_BOUND')
                pinned = os.open('.', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                self._pins[key] = pinned
                need(P['identity'](os.fstat(pinned)) == ident, 'P15_SOURCE_DIRECTORY_SWAP')
            observed_directories[prefix] = ident
            def names():
                actual = set()
                scanfd = os.open('.', P['DIR_FLAGS'], dir_fd=fd)
                try:
                    with os.scandir(scanfd) as entries:
                        for entry in entries:
                            budget['entries'] += 1
                            need(budget['entries'] <= MAX_ENTRIES, 'P15_SOURCE_ENTRY_BOUND')
                            name = entry.name
                            need(name not in actual and name not in ('', '.', '..') and '/' not in name,
                                 'P15_SOURCE_DUPLICATE_ENTRY')
                            actual.add(name)
                    return actual
                finally:
                    os.close(scanfd)
            # Freeze each entry set before reading contents. A second consumed,
            # bounded enumeration catches additions even on coarse timestamps.
            initial = names()
            if not prefix and self._git_identity is not None:
                need('.git' in initial, 'P15_SOURCE_GIT_MISSING')
            for name in sorted(initial):
                if not prefix and name == '.git':
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    need(stat.S_ISDIR(info.st_mode), 'P15_SOURCE_GIT_DIRECTORY')
                    with P['directory'](fd, name, owned=True) as admin:
                        need(P['identity'](os.fstat(admin)) == P['identity'](info),
                             'P15_SOURCE_GIT_SWAP')
                        self._bind_git_directory(admin)
                    continue  # Metadata is bound; contents are not app sources.
                relative = prefix + '/' + name if prefix else name
                need(len(os.fsencode(relative)) <= 4096 and depth + 1 <= MAX_DEPTH,
                     'P15_SOURCE_DEPTH_BOUND')
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    result['directories'][relative] = {'mode': mode}
                    with P['directory'](fd, name, owned=True) as child:
                        need(P['identity'](os.fstat(child)) == P['identity'](info),
                             'P15_SOURCE_DIRECTORY_SWAP')
                        walk(child, relative, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    result['files'][relative] = self._file(fd, name, info, budget)
                elif stat.S_ISLNK(info.st_mode) and DESKTOP_ALIAS.fullmatch(relative) and plugin_aliases is not None:
                    plugin_aliases.check_leaf(relative, info)
                    result['aliases'][relative] = self._link(fd, name, info)
                elif stat.S_ISLNK(info.st_mode):
                    result['unsafe'][relative] = self._link(fd, name, info)
                else:
                    kind = ('fifo' if stat.S_ISFIFO(info.st_mode)
                            else 'socket' if stat.S_ISSOCK(info.st_mode) else 'device' if
                            stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode) else 'unknown')
                    result['unsafe'][relative] = {'type': kind, 'mode': mode, 'bytes': info.st_size}
            need(names() == initial and P['stable'](os.fstat(fd)) == P['stable'](before),
                 'P15_SOURCE_DIRECTORY_RACE')

        try:
            with P['absolute_directory'](self.stage, expected=self.ancestors) as root:
                walk(root, '', 0)
        except OSError:
            raise SourceFailure('P15_SOURCE_IO') from None
        # Retain identities of disappeared directories so replacement cannot erase
        # the original binding on a later capture.
        self.directories.update(observed_directories)
        return result
