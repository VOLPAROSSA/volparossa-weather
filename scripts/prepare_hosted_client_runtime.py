#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Closed input-view adapter for the existing hosted Weather bwrap harness.

No independent execution CLI, caller commands, URLs, hashes or input records.
The manual inventory entrypoint supplies its already authenticated fixed APT
candidate. All native execution belongs to the guarded disposable runner.
"""
import hashlib
import ast
import configparser
import importlib.util
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import runpy
import stat
import struct

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 192 * 1024**2
MAX_VIEW = 768 * 1024**2
ALIASES = {'bin': 'usr/bin', 'sbin': 'usr/sbin', 'lib': 'usr/lib', 'lib64': 'usr/lib64'}
PRIVATE_TOOLS = frozenset(('usr/bin/su', 'usr/bin/mount', 'usr/bin/umount', 'usr/bin/passwd',
    'usr/bin/chage', 'usr/bin/chfn', 'usr/bin/chsh', 'usr/bin/expiry', 'usr/bin/gpasswd',
    'usr/lib/dbus-1.0/dbus-daemon-launch-helper', 'usr/sbin/pam_extrausers_chkpwd', 'usr/sbin/unix_chkpwd',
    'usr/bin/pidof', 'usr/bin/systemd'))
EXCLUDED = ('usr/share/doc/', 'usr/share/man/', 'usr/lib/systemd/', 'usr/lib/environment.d/',
    'usr/share/dbus-1/', 'usr/share/polkit-1/', 'usr/share/icons/', 'usr/share/locale/')
ETC = ('etc/fonts', 'etc/ld.so.conf', 'etc/ld.so.conf.d/libc.conf', 'etc/ld.so.conf.d/x86_64-linux-gnu.conf',
    'etc/ssl/openssl.cnf', 'etc/X11/rgb.txt')
BROWSER_FILES = ('scripts/stage_firefox.py', 'scripts/smoke_privacy.py', 'scripts/smoke_compute_model.py', 'defaults/privacy.json')
LOADER = '/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def module(name):
    spec = importlib.util.spec_from_file_location('_boundary_' + name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def regular(path, maximum=MAX_FILE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid in (0, os.getuid())
            and before.st_nlink == 1 and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum, 'BOUNDARY_FILE')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size and (before.st_dev, before.st_ino, before.st_size,
        before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns), 'BOUNDARY_FILE_CHANGED')
    current = path.lstat()
    require((current.st_dev, current.st_ino) == (before.st_dev, before.st_ino), 'BOUNDARY_FILE_REPLACED')
    return raw


def put(path, raw, executable=False):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.parent.resolve() == path.parent, 'BOUNDARY_PARENT_ALIAS')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o700 if executable else 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def package_path(name):
    require(isinstance(name, str) and not name.startswith('/') and all(p not in ('', '.', '..')
        for p in name.split('/')), 'BOUNDARY_PACKAGE_PATH')
    first, slash, rest = name.partition('/')
    if first in ALIASES:
        return ALIASES[first] + (slash + rest if rest else '')
    return name


def selected(name):
    if name in ALIASES:
        return False  # Structural roots, never usr/bin -> usr/bin self-links.
    path = package_path(name)
    if path in PRIVATE_TOOLS or path.startswith(EXCLUDED) or path == 'usr/lib/python3.12/sitecustomize.py':
        return False
    if path.startswith('usr/sbin/') and path != 'usr/sbin/ldconfig.real':
        return False
    return path == 'usr' or path.startswith('usr/') or any(path == p or path.startswith(p + '/') for p in ETC)


def elf(raw):
    """Bounded ELF64 little-endian metadata only; never invoke ldd/readelf."""
    if not raw.startswith(b'\x7fELF'):
        return None
    require(len(raw) >= 64 and raw[:7] == b'\x7fELF\x02\x01\x01'
        and struct.unpack_from('<H', raw, 18)[0] == 62, 'BOUNDARY_ELF_ABI')
    phoff = struct.unpack_from('<Q', raw, 32)[0]
    size, count = struct.unpack_from('<HH', raw, 54)
    kind = struct.unpack_from('<H', raw, 16)[0]
    if kind == 1:  # Authorized relocatable compiler inputs have no load segments.
        require(count == 0 and phoff == 0, 'BOUNDARY_ELF_RELOCATABLE')
        return dict(interpreter=None, needed=[], soname=None, search=[])
    require(kind in (2, 3), 'BOUNDARY_ELF_TYPE')
    require(size == 56 and 0 < count <= 512 and phoff + size * count <= len(raw), 'BOUNDARY_ELF_HEADERS')
    loads, dynamic, interpreter = [], [], None
    for index in range(count):
        kind, _flags, offset, address, _physical, length, _memory, _align = struct.unpack_from('<IIQQQQQQ', raw, phoff + index * size)
        require(offset + length <= len(raw), 'BOUNDARY_ELF_SEGMENT')
        if kind == 1:
            loads.append((address, offset, length))
        elif kind == 2:
            require(length % 16 == 0 and length // 16 <= 4096, 'BOUNDARY_ELF_DYNAMIC')
            for position in range(offset, offset + length, 16):
                tag, value = struct.unpack_from('<qQ', raw, position)
                if tag == 0:
                    break
                dynamic.append((tag, value))
        elif kind == 3:
            require(1 < length <= 256 and raw[offset:offset + length].endswith(b'\0'), 'BOUNDARY_ELF_INTERPRETER')
            interpreter = raw[offset:offset + length - 1].decode('ascii')
    strings = dict(dynamic)
    require(not dynamic or 5 in strings and 10 in strings, 'BOUNDARY_ELF_STRING_TABLE')
    start = None
    if dynamic:
        for address, offset, length in loads:
            if address <= strings[5] and strings[5] + strings[10] <= address + length:
                start = offset + strings[5] - address
                break
        require(start is not None and 0 < strings[10] <= 16 * 1024**2, 'BOUNDARY_ELF_STRING_TABLE')
    def string(offset):
        require(0 <= offset < strings[10], 'BOUNDARY_ELF_STRING')
        end = raw.find(b'\0', start + offset, min(start + strings[10], start + offset + 4097))
        require(end != -1, 'BOUNDARY_ELF_STRING')
        return raw[start + offset:end].decode('ascii')
    return dict(interpreter=interpreter, needed=[string(v) for t, v in dynamic if t == 1],
        soname=string(strings[14]) if 14 in strings else None,
        search=[string(v) for t, v in dynamic if t in (15, 29)])


def resolve(name, entries):
    """Resolve only the synthetic namespace's reviewed paths, never host links."""
    require(name.startswith('/') and '\0' not in name, 'BOUNDARY_LINK_PATH')
    name = posixpath.normpath(name).lstrip('/')
    for _ in range(40):
        parts = name.split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:index])
            item = entries.get(prefix)
            require(item is not None, 'BOUNDARY_UNAUTHORIZED_PATH')
            if item['type'] == 'symlink':
                target = item['target']
                name = posixpath.normpath(posixpath.join('/' if target.startswith('/') else '/' + posixpath.dirname(prefix),
                    target, *parts[index:])).lstrip('/')
                break
            require(index == len(parts) or item['type'] == 'directory', 'BOUNDARY_NON_DIRECTORY')
        else:
            return name, entries[name]
    require(False, 'BOUNDARY_LINK_CYCLE')


def subset(packages, profile, inputs):
    record = inputs.load_package_inputs(profile)
    indexed = {tuple(p['identity']): p for p in packages}
    result = []
    for expected in record['apt']['packages']:
        package = indexed.get(tuple(expected['identity']))
        require(package is not None, 'BOUNDARY_PROFILE_PACKAGE_MISSING')
        item = dict(package)
        item['files_sha256'] = sha(canonical(item.pop('files')))
        require(item == expected, 'BOUNDARY_PROFILE_INPUT_CHANGED')
        result.append(package)
    return result


class View:
    def __init__(self, root, packages, profile, *, host=Path('/')):
        # Constructor authority is fixed too; future source-mode callers cannot
        # turn an observed package/member map into a new expected-value record.
        packages = subset(packages, profile, module('prepare_hosted_client_inputs'))
        self.root, self.profile, self.entries = root, profile, {}
        require(root.is_absolute() and root.parent.resolve() == root.parent
            and root.parent.stat().st_uid == os.getuid() and stat.S_IMODE(root.parent.stat().st_mode) == 0o700,
            'BOUNDARY_VIEW_PARENT')
        root.mkdir(mode=0o700)
        self.anchor = (root.stat().st_dev, root.stat().st_ino)
        self.parent_anchor = (root.parent.stat().st_dev, root.parent.stat().st_ino)
        raw_entries = {}
        for package in packages:
            members = package['files']
            for name, item in members.items():
                if not selected(name):
                    continue
                path = package_path(name)
                expected = dict(item)
                if expected['type'] == 'hardlink':
                    target = expected['target'].removeprefix('./').lstrip('/')
                    require(members.get(target, {}).get('type') == 'file', 'BOUNDARY_HARDLINK')
                    expected = dict(members[target])
                previous = raw_entries.get(path)
                require(previous is None or previous[1] == expected, 'BOUNDARY_PACKAGE_COLLISION')
                raw_entries[path] = (package_path(name), expected)
        # Build directories before links and files. No copied symlink becomes
        # a staging write route. The view's private files lose all set-id bits.
        for path in sorted(raw_entries, key=lambda n: (n.count('/'), n)):
            for parent in reversed(PurePosixPath(path).parents):
                if str(parent) != '.':
                    self.entries.setdefault(str(parent), dict(type='directory'))
            source, expected = raw_entries[path]
            self.entries[path] = expected if expected['type'] != 'file' else dict(expected,
                mode=0o700 if expected['mode'] & 0o111 else 0o600)
        for name, item in sorted(self.entries.items(), key=lambda p: (p[0].count('/'), p[0])):
            if item['type'] == 'directory':
                (root / name).mkdir(mode=0o700, exist_ok=True)
        total = 0
        for name, (source, expected) in raw_entries.items():
            if expected['type'] != 'file':
                continue
            # Canonical /usr paths have no inherited usrmerge alias. Every
            # intermediate host directory must itself be a real directory.
            parts = source.split('/')
            fd = os.open(host, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd); fd = child
                leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(leaf, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.getuid())
                        and not info.st_mode & 0o022 and info.st_size == expected['bytes'] <= MAX_FILE,
                        'BOUNDARY_INSTALLED_LEAF')
                    raw = stream.read(MAX_FILE + 1)
                    after = os.fstat(stream.fileno())
                current = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
                require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'BOUNDARY_INSTALLED_REPLACED')
                require(len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], 'BOUNDARY_INSTALLED_BYTES')
            finally:
                os.close(fd)
            total += len(raw)
            require(total <= MAX_VIEW, 'BOUNDARY_VIEW_BYTES')
            put(root / name, raw, executable=bool(expected['mode'] & 0o111))
            metadata = elf(raw)
            if metadata is not None:
                self.entries[name]['elf'] = metadata
        for name, item in self.entries.items():
            if item['type'] == 'symlink':
                os.symlink(item['target'], root / name)
        for name, target in ALIASES.items():
            self.directory(target)
            self.link(name, target)
        for alias, target in (('usr/bin/awk', 'mawk'), ('usr/bin/nawk', 'mawk'), ('usr/bin/which', 'which.debianutils')):
            if alias not in self.entries and 'usr/bin/' + target in self.entries:
                self.link(alias, target)
        # Host timezone and generated CA state never become expected inputs.
        for directory in ('etc', 'etc/ssl', 'etc/ssl/certs', 'etc/ssl/private'):
            self.directory(directory)
        if 'usr/share/zoneinfo/Etc/UTC' in self.entries:
            self.link('etc/localtime', '/usr/share/zoneinfo/Etc/UTC')
        certificates = [name for name, item in self.entries.items()
            if name.startswith('usr/share/ca-certificates/mozilla/') and item['type'] == 'file' and name.endswith('.crt')]
        require(certificates, 'BOUNDARY_CA_INPUTS_MISSING')
        bundle = b''.join(regular(root / name).rstrip(b'\n') + b'\n' for name in sorted(certificates))
        self.generated('etc/ssl/certs/ca-certificates.crt', bundle, 'sorted-fixed-package-certificates')
        self.generated('etc/ld.so.cache', b'', 'empty-cache-until-closed-generator-completes')
        self.generated('etc/resolv.conf', b'', 'offline-empty-resolver-until-explicit-acquisition')
        self.generated('etc/passwd', b'', 'mountpoint-for-fixed-ephemeral-uid-record')
        self.generated('etc/group', b'', 'mountpoint-for-fixed-ephemeral-gid-record')
        for name, item in list(self.entries.items()):
            if item['type'] == 'symlink':
                resolve('/' + name, self.entries)
        require('usr/sbin/ldconfig.real' in self.entries and LOADER[1:] in self.entries, 'BOUNDARY_LOADER_TOOLS_MISSING')
        self.cache_sha = None
        self.recheck()

    def directory(self, name):
        (self.root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        for parent in reversed(PurePosixPath(name).parents):
            if str(parent) != '.':
                self.entries.setdefault(str(parent), dict(type='directory'))
        self.entries[name] = dict(type='directory')

    def link(self, name, target):
        require(name not in self.entries, 'BOUNDARY_ALIAS_COLLISION')
        self.directory(str(PurePosixPath(name).parent)) if '/' in name else None
        os.symlink(target, self.root / name)
        self.entries[name] = dict(type='symlink', target=target)

    def generated(self, name, raw, rule):
        put(self.root / name, raw)
        for parent in reversed(PurePosixPath(name).parents):
            if str(parent) != '.':
                self.entries.setdefault(str(parent), dict(type='directory'))
        self.entries[name] = dict(type='file', mode=0o600, bytes=len(raw), sha256=sha(raw), generated_rule=rule)

    def recheck(self):
        info, parent = self.root.lstat(), self.root.parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_ISDIR(parent.st_mode)
            and (info.st_dev, info.st_ino) == self.anchor and (parent.st_dev, parent.st_ino) == self.parent_anchor
            and self.root.resolve() == self.root, 'BOUNDARY_VIEW_REPLACED')
        actual = {str(path.relative_to(self.root)) for path in self.root.rglob('*')}
        require(actual == set(self.entries), 'BOUNDARY_VIEW_EXTRA_OR_MISSING')
        for name, item in self.entries.items():
            path = self.root / name
            info = path.lstat()
            require(info.st_uid == os.getuid(), 'BOUNDARY_VIEW_OWNER')
            if item['type'] == 'directory':
                require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700, 'BOUNDARY_VIEW_DIRECTORY')
            elif item['type'] == 'symlink':
                require(stat.S_ISLNK(info.st_mode) and os.readlink(path) == item['target'], 'BOUNDARY_VIEW_ALIAS')
            else:
                raw = regular(path)
                require(info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == item['mode']
                    and len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'BOUNDARY_VIEW_CHANGED')
        if self.cache_sha is not None:
            require(sha(regular(self.root.parent / 'ld.so.cache')) == self.cache_sha, 'BOUNDARY_CACHE_CHANGED')

    def cache_semantics(self, raw):
        require(len(raw) <= 2 * 1024**2, 'BOUNDARY_CACHE_LIST_BOUND')
        lines = raw.decode('utf-8').splitlines()
        header = re.fullmatch(r"([0-9]+) libs found in cache `/state/ld\.so\.cache'", lines[0]) if lines else None
        require(header is not None and 0 < int(header[1]) <= 4096, 'BOUNDARY_CACHE_HEADER')
        count = int(header[1])
        require(len(lines) in (count + 1, count + 2), 'BOUNDARY_CACHE_COUNT')
        if len(lines) == count + 2:
            require(re.fullmatch(r'Cache generated by: ldconfig \(Ubuntu GLIBC 2\.39-0ubuntu8\.9\)', lines[-1]),
                'BOUNDARY_CACHE_GENERATOR')
        bindings, records = {}, set()
        for line in lines[1:count + 1]:
            match = re.fullmatch(r'\s+([A-Za-z0-9.+_-]{1,256}) \((libc6,x86-64)\) => (/[^\s]{1,1024})', line)
            require(match is not None, 'BOUNDARY_CACHE_LIST_SYNTAX')
            soname, flags, path = match.groups()
            canonical_path, item = resolve(path, self.entries)
            require(item['type'] == 'file' and item.get('elf', {}).get('soname') == soname,
                'BOUNDARY_UNAUTHORIZED_LIBRARY_SELECTION')
            require(soname not in bindings or bindings[soname] == canonical_path, 'BOUNDARY_AMBIGUOUS_SONAME')
            require((soname, flags, canonical_path) not in records, 'BOUNDARY_CACHE_DUPLICATE')
            records.add((soname, flags, canonical_path))
            bindings[soname] = canonical_path
        require(0 < len(bindings) <= 4096, 'BOUNDARY_CACHE_EMPTY_OR_OVERSIZED')
        return bindings


class Boundary:
    def __init__(self, view, helper, browser, sdk=None):
        self.view, self.h, self.browser, self.sdk = view, helper, browser, sdk
        self.base = view.root.parent
        self.witness = self.base.parent.parent / 'runtime-boundary-unapproved-library.so'
        self.source = self.base / 'source'
        self.browser_source = self.base / 'browser-source'
        self.cache = self.base / 'ld.so.cache'
        self.firefox_copy = self.base / 'firefox-copy'
        self.deploy = getattr(helper, 'BOUNDARY_DEPLOY', ROOT / 'build/overmorrow-hosted-web-ci')
        self.table_proof = getattr(helper, 'BOUNDARY_TABLE_PROOF', ROOT / 'build/overmorrow-hosted-table-ci')
        self.sdk_metadata = {}
        recipe = module('prepare_hosted_source_recipe')
        sources = recipe.snapshot(ROOT, view.profile, os.environ['GITHUB_SHA'])
        self.source.mkdir(mode=0o700)
        for name, raw in sources.items():
            put(self.source / name, raw)
        # Browser imports only these fixed tracked helper files. Git identity
        # below is compatibility data; blob verification supplies provenance.
        (browser / 'build').mkdir(mode=0o700, exist_ok=True)
        browser_sources = recipe.tracked_snapshot(browser, helper.BROWSER_COMMIT, BROWSER_FILES)
        self.browser_source.mkdir(mode=0o700)
        for name, raw in browser_sources.items():
            put(self.browser_source / name, raw)
        for name in ('objects', 'refs'):
            (self.browser_source / '.git' / name).mkdir(mode=0o700, parents=True)
        put(self.browser_source / '.git/HEAD', (helper.BROWSER_COMMIT + '\n').encode())
        put(self.browser_source / '.git/config', b'[core]\nrepositoryformatversion = 0\nbare = false\nhooksPath = /dev/null\n')
        # Empty mountpoints are data-free: ROOT/build is never a host bind.
        for path in (helper.RUNTIME, helper.BROWSER, helper.STAGE, helper.PROOF, helper.OUTPUT):
            require(path.is_relative_to(ROOT / 'build'), 'BOUNDARY_OVERLAY_SCOPE')
            (self.source / path.relative_to(ROOT)).mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('node', 'firefox', 'licenses'):
            (self.source / (helper.RUNTIME / name).relative_to(ROOT)).mkdir(mode=0o700)
        require(helper.FIREFOX.is_relative_to(ROOT / 'build'), 'BOUNDARY_FIREFOX_SCOPE')
        if helper.FIREFOX.is_relative_to(browser):
            (self.browser_source / helper.FIREFOX.relative_to(browser)).mkdir(mode=0o700, parents=True)
        else:
            (self.source / helper.FIREFOX.relative_to(ROOT)).mkdir(mode=0o700, parents=True)
        if sdk is not None:
            require(sdk.is_relative_to(ROOT / 'build'), 'BOUNDARY_SDK_SCOPE')
            (self.source / sdk.relative_to(ROOT)).mkdir(mode=0o700, parents=True, exist_ok=True)
            for path in (self.deploy, self.table_proof):
                require(path.is_relative_to(ROOT / 'build'), 'BOUNDARY_APP_OUTPUT_SCOPE')
                (self.source / path.relative_to(ROOT)).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.source_files = {str(p.relative_to(self.source)): sha(regular(p)) for p in self.source.rglob('*') if p.is_file()}
        self.browser_files = {str(p.relative_to(self.browser_source)): sha(regular(p))
            for p in self.browser_source.rglob('*') if p.is_file()}
        self.source_anchors = {str(p): (p.stat().st_dev, p.stat().st_ino) for p in (self.source, self.browser_source)}
        self.runtime_initial = helper.runtime_inventory()
        self.firefox_ready = False
        self.sdk_preparer = module('prepare_hosted_flutter') if sdk is not None else None
        if sdk is not None:
            self.sdk_initial = self.sdk_preparer.verify_materialized(sdk)
            # Only declared scalar metadata can be writable. Cache binaries,
            # snapshots, source and directory entries stay sealed.
            metadata = self.base / 'sdk-metadata'
            metadata.mkdir(mode=0o700)
            require(regular(sdk / 'bin/cache/flutter_tools.stamp', 65536).strip() ==
                (self.sdk_preparer.COMMIT + ':').encode(), 'BOUNDARY_SDK_COMPILE_KEY')
            require((sdk / 'packages/flutter_tools/pubspec.yaml').stat().st_mtime_ns <=
                (sdk / 'packages/flutter_tools/pubspec.lock').stat().st_mtime_ns, 'BOUNDARY_SDK_BOOTSTRAP_TIMESTAMPS')
            required = frozenset('bin/cache/' + name for name in ('engine.stamp', 'engine.realm', 'lockfile'))
            for name in sorted(self.sdk_preparer.MUTABLE_CACHE):
                original = sdk / name
                if not original.exists():
                    if name not in required:
                        continue  # Do not change absent JSON/stamp semantics.
                    put(original, b'')  # Direct truncation/flock producer.
                info = original.stat()
                raw = regular(original, 65536)
                require(not original.stat().st_mode & 0o111, 'BOUNDARY_SDK_METADATA_MODE')
                path = metadata / Path(name).name
                put(path, raw)
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                self.sdk_metadata[name] = path
            self.sdk_preparer.verify_materialized(sdk, allow_build_state=True)

    def stage_firefox(self):
        # Reuse the pinned Browser data-only stager, with its original fixed
        # private build scope. Relocate its independent copy before sealing the
        # source view; no Browser worktree or payload is modified.
        stager = runpy.run_path(str(self.browser_source / 'scripts/stage_firefox.py'))
        temporary = self.browser_source / 'build/boundary-stage'
        stager['stage'](self.h.RUNTIME / 'firefox/firefox-esr', temporary,
            self.h.FIREFOX_VERSION, self.h.FIREFOX_SOURCE_STAMP)
        require(not self.firefox_copy.exists() and not self.firefox_copy.is_symlink(), 'BOUNDARY_FIREFOX_EXISTS')
        temporary.rename(self.firefox_copy)
        self.firefox_anchor = (self.firefox_copy.stat().st_dev, self.firefox_copy.stat().st_ino)
        self.firefox_ready = True
        self.firefox_binding()

    def firefox_binding(self):
        info = self.firefox_copy.lstat()
        require(stat.S_ISDIR(info.st_mode) and self.firefox_copy.resolve() == self.firefox_copy
            and info.st_uid == os.getuid() and (info.st_dev, info.st_ino) == self.firefox_anchor,
            'BOUNDARY_BROWSER_COPY_REPLACED')
        files = json.loads(regular(self.h.RUNTIME / 'provenance.json', 2 * 1024**2))['files']
        self.h.verify_firefox_copy(files, root=self.firefox_copy)
        for name, item in files.items():
            if name.startswith('firefox/'):
                require(stat.S_IMODE((self.firefox_copy / name.removeprefix('firefox/')).stat().st_mode) == item['mode'],
                    'BOUNDARY_BROWSER_COPY_MODE')
        source = self.browser_source / 'scripts/stage_firefox.py'
        stager = runpy.run_path(str(source))
        defaults = stager['load_defaults']()
        expected = stager['render_defaults'](defaults).encode('utf-8')
        constants = [node.args[0].value for node in ast.walk(ast.parse(regular(source).decode('utf-8')))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'configuration'
            and node.func.attr == 'write_text' and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
        require(len(constants) == 1 and len(constants[0]) <= 65536, 'BOUNDARY_BROWSER_BOOTSTRAP_RULE')
        require(regular(self.firefox_copy / 'volparossa.cfg') == expected
            and regular(self.firefox_copy / 'defaults/pref/volparossa-autoconfig.js') == constants[0].encode('utf-8'),
            'BOUNDARY_BROWSER_CONFIG_CHANGED')
        application = configparser.ConfigParser()
        application.read_string(regular(self.h.RUNTIME / 'firefox/application.ini').decode('utf-8'))
        expected_marker = dict(schema=1, kind='installed-runtime-privacy-overlay-not-a-firefox-source-build',
            source_gre=str(self.h.RUNTIME / 'firefox'), version=self.h.FIREFOX_VERSION,
            source_repository=application['App']['SourceRepository'], source_stamp=self.h.FIREFOX_SOURCE_STAMP,
            build_id=application['App']['BuildID'], executable='firefox-esr',
            runtime_sha256={name: files['firefox/' + name]['sha256'] for name in
                ('firefox-esr', 'libxul.so', 'omni.ja', 'browser/omni.ja')},
            defaults_sha256=sha(regular(self.browser_source / 'defaults/privacy.json')), autoconfig_sha256=sha(expected),
            excluded_host_distribution_policies=True, excluded_host_system_preferences=True)
        require(json.loads(regular(self.firefox_copy / 'volparossa-staging.json')) == expected_marker,
            'BOUNDARY_BROWSER_MARKER_CHANGED')
        return dict(defaults_sha256=expected_marker['defaults_sha256'], autoconfig_sha256=sha(expected),
            bootstrap_sha256=sha(constants[0].encode('utf-8')), marker_matches_fixed_derivation=True)

    def check(self):
        self.view.recheck()
        for root, expected in ((self.source, self.source_files), (self.browser_source, self.browser_files)):
            root_info = root.lstat()
            require(stat.S_ISDIR(root_info.st_mode) and root.resolve() == root
                and (root_info.st_dev, root_info.st_ino) == self.source_anchors[str(root)], 'BOUNDARY_SOURCE_REPLACED')
            actual = {}
            for path in root.rglob('*'):
                info = path.lstat()
                require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'BOUNDARY_SOURCE_ALIAS')
                if stat.S_ISREG(info.st_mode):
                    actual[str(path.relative_to(root))] = sha(regular(path, 512 * 1024))
            require(actual == expected, 'BOUNDARY_SOURCE_CHANGED')
        require(self.h.runtime_inventory() == self.runtime_initial, 'BOUNDARY_RUNTIME_CHANGED')
        if self.firefox_ready:
            self.firefox_binding()
        if self.sdk is not None:
            self.sdk_preparer.verify_materialized(self.sdk, allow_build_state=True)
            for path in self.sdk_metadata.values():
                info = path.lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 65536, 'BOUNDARY_SDK_METADATA_CHANGED')
        immutable = [self.view.root, self.source, self.browser_source, self.h.RUNTIME, self.cache, self.firefox_copy]
        if self.sdk is not None:
            immutable += [self.sdk, self.deploy]
        writable = [self.h.PRIVATE, self.h.STAGE, self.h.PROOF, *self.sdk_metadata.values()]
        if self.sdk is not None:
            writable.append(self.table_proof)
        require(all(not ro.is_relative_to(rw) and not rw.is_relative_to(ro) for ro in immutable for rw in writable),
            'BOUNDARY_WRITABLE_ALIAS')
        for path in writable:
            if path in (self.h.PRIVATE, self.h.STAGE, self.h.PROOF, self.table_proof) and not path.exists() and not path.is_symlink():
                continue  # Existing execute creates these fresh at its phase.
            info = path.lstat()
            require(path.resolve() == path and info.st_uid == os.getuid() and not info.st_mode & 0o022,
                'BOUNDARY_WRITABLE_SOURCE')

    def system_mounts(self):
        self.check()
        argv = ['--ro-bind', str(self.view.root / 'usr'), '/usr', '--ro-bind', str(self.view.root / 'etc'), '/etc']
        for name, target in ALIASES.items():
            argv += ['--symlink', target, '/' + name]
        if self.view.cache_sha is not None:
            argv += ['--ro-bind', str(self.cache), '/etc/ld.so.cache']
        return argv

    def source_mounts(self, mode):
        require(ROOT.is_relative_to(Path('/home/runner/work')), 'BOUNDARY_RUNNER_LAYOUT')
        argv = ['--tmpfs', '/home/runner/work', '--ro-bind', str(self.source), str(ROOT),
            '--ro-bind', str(self.browser_source), str(self.browser)]
        for name in ('node', 'firefox', 'licenses'):
            argv += ['--ro-bind', str(self.h.RUNTIME / name), str(self.h.RUNTIME / name)]
        if self.sdk is not None:
            argv += ['--ro-bind', str(self.sdk), str(self.sdk)]
        if self.firefox_ready:
            argv += ['--ro-bind', str(self.firefox_copy), str(self.h.FIREFOX)]
        if mode == 'browser':
            require(self.firefox_ready, 'BOUNDARY_FIREFOX_NOT_STAGED')
            argv += ['--ro-bind', str(self.h.STAGE), str(self.h.STAGE)]
            if self.sdk is not None:
                deploy = self.deploy
                require(deploy.resolve() == deploy and deploy.is_dir(), 'BOUNDARY_DEPLOY_ROOT')
                argv += ['--ro-bind', str(deploy), str(deploy)]
        return argv

    def acquisition_mounts(self):
        # DNS is acquisition-only platform configuration, never compiler input
        # or authority for the separately authenticated archive bytes.
        path = self.base / 'resolv.conf'
        if not path.exists():
            source = Path('/etc/resolv.conf').resolve(strict=True)
            servers = []
            for line in regular(source, 65536).decode('ascii').splitlines():
                values = line.split('#', 1)[0].split()
                if values and values[0] == 'nameserver':
                    require(len(values) == 2, 'BOUNDARY_DNS_CONFIGURATION')
                    servers.append(str(ipaddress.ip_address(values[1])))
            require(0 < len(servers) <= 4, 'BOUNDARY_DNS_CONFIGURATION')
            put(path, ''.join('nameserver ' + name + '\n' for name in servers).encode())
        return ['--ro-bind', str(path), '/etc/resolv.conf']

    def sdk_metadata_mounts(self):
        require(self.sdk is not None, 'BOUNDARY_SDK_NOT_SELECTED')
        return [value for name, path in sorted(self.sdk_metadata.items())
            for value in ('--bind', str(path), str(self.sdk / name))]

    def prepare_cache(self):
        """Prepare a live context before existing execute creates app scratch.

        The caller has installed the existing short-lived AppArmor profile.
        Generator scratch is exclusively created and removed empty on success;
        no existing application state is reused or deleted.
        """
        require(self.h.BOUNDARY is self and self.view.cache_sha is None, 'BOUNDARY_CONTEXT_REQUIRED')
        self.h.PRIVATE.mkdir(mode=0o700)
        generated = self.h.PRIVATE / 'ld.so.cache'
        def run(label, command):
            return self.h.run(self.view.profile + '-' + label,
                self.h.sandbox(command, mode='compile'), 60, env=self.h.environment(), memory=3 * 1024**3)
        run('cache-generate', ['/usr/sbin/ldconfig.real', '-X', '-i', '-c', 'new', '-C', '/state/ld.so.cache',
            '-f', '/etc/ld.so.conf'])
        original = regular(generated, 2 * 1024**2)
        listing = run('cache-list', ['/usr/sbin/ldconfig.real', '-p', '-C', '/state/ld.so.cache'])
        bindings = self.view.cache_semantics(listing)
        raw = regular(generated, 2 * 1024**2)
        require(raw == original, 'BOUNDARY_CACHE_CHANGED_DURING_SEMANTIC_CHECK')
        put(self.cache, raw)
        generated.unlink()
        self.h.PRIVATE.rmdir()  # Fails closed on any unexpected generator output.
        self.view.cache_sha = sha(raw)
        return bindings

    def library(self, path):
        if path.startswith(('/usr/', '/lib/', '/lib64/')):
            name, item = resolve(path, self.view.entries)
            require(item['type'] == 'file' and 'elf' in item, 'BOUNDARY_UNAUTHORIZED_LIBRARY_SELECTION')
            return dict(path='/' + name, sha256=item['sha256'])
        runtime = self.h.RUNTIME
        if Path(path).is_relative_to(self.h.FIREFOX):
            name = 'firefox/' + str(Path(path).relative_to(self.h.FIREFOX))
            files = json.loads(regular(runtime / 'provenance.json', 2 * 1024**2))['files']
            require(name in files and sha(regular(self.firefox_copy / name.removeprefix('firefox/'))) == files[name]['sha256'],
                'BOUNDARY_UNAUTHORIZED_BROWSER_LIBRARY')
            return dict(path='firefox-copy/' + name.removeprefix('firefox/'), sha256=files[name]['sha256'])
        if self.sdk is not None and Path(path).is_relative_to(self.sdk):
            name = str(Path(path).relative_to(self.sdk))
            files = json.loads(regular(self.sdk / 'sdk-inventory.json', 8 * 1024**2))
            require(name in files and sha(regular(self.sdk / name)) == files[name]['sha256'],
                'BOUNDARY_UNAUTHORIZED_SDK_LIBRARY')
            return dict(path='sdk/' + name, sha256=files[name]['sha256'])
        require(Path(path).is_relative_to(runtime), 'BOUNDARY_UNAUTHORIZED_LIBRARY_SELECTION')
        name = str(Path(path).relative_to(runtime))
        files = json.loads(regular(runtime / 'provenance.json', 2 * 1024**2))['files']
        require(name in files, 'BOUNDARY_UNAUTHORIZED_RUNTIME_LIBRARY')
        require(sha(regular(runtime / name)) == files[name]['sha256'], 'BOUNDARY_RUNTIME_LIBRARY_CHANGED')
        return dict(path=name, sha256=files[name]['sha256'])

    def loader_semantics(self, raw):
        require(len(raw) <= 2 * 1024**2, 'BOUNDARY_LOADER_LIST_BOUND')
        selected_files = []
        for line in raw.decode('utf-8').splitlines():
            require('not found' not in line, 'BOUNDARY_LIBRARY_NOT_FOUND')
            if re.fullmatch(r'\s*linux-vdso\.so\.1 \(0x[0-9a-f]+\)', line):
                continue
            match = re.fullmatch(r'\s*(?:[A-Za-z0-9.+_-]+ => )?(/[^\s]+) \(0x[0-9a-f]+\)', line)
            require(match is not None, 'BOUNDARY_LOADER_LIST_SYNTAX')
            selected_files.append(self.library(match[1]))
        require(selected_files, 'BOUNDARY_LOADER_LIST_EMPTY')
        return selected_files

    def preflight(self, mode, *, overmorrow=None, proof=None):
        require(mode in ('acquire', 'compile', 'browser') and self.view.cache_sha is not None,
            'BOUNDARY_PREFLIGHT_MODE')
        require(proof is None if mode != 'browser' else (proof or self.h.PROOF) in (self.h.PROOF, self.table_proof),
            'BOUNDARY_PROOF_SCOPE')
        witness = self.witness
        writable = [str(proof or self.h.PROOF), '/home/runner/.mozilla'] if mode == 'browser' else [str(self.h.STAGE), '/state']
        if overmorrow is not None and mode != 'browser':
            writable += [str(self.sdk / name) for name in sorted(self.sdk_metadata)]
            writable.append(str(overmorrow.SDK_TOOL_MOUNT))
        command = ['/usr/bin/python3.12', '-I', '-S', '-c', PROBE, str(witness), str(ROOT.parent),
            self.view.cache_sha, os.readlink('/proc/self/ns/net'), str(ROOT), mode, json.dumps(writable),
            str(self.sdk) if overmorrow is not None else '', str(proof or self.h.PROOF if mode == 'browser' else self.h.STAGE),
            str(os.getuid())]
        argv = overmorrow.sandbox(command, mode=mode, proof=proof) if overmorrow is not None else \
            self.h.sandbox(command, mode=mode, writable=self.h.PROOF if mode == 'browser' else self.h.STAGE)
        raw = self.h.run(self.view.profile + '-preflight-' + mode, argv, 30,
            env=overmorrow.environment() if overmorrow is not None else self.h.environment())
        result = json.loads(raw)
        require(type(result) is dict and result and all(value is True for value in result.values()),
            'BOUNDARY_PREFLIGHT_FAILED')
        return result


PROBE = r'''
import ctypes, errno, hashlib, json, os, re, socket, sys
from pathlib import Path
assert not Path('/etc/ld.so.conf.d/fakeroot-x86_64-linux-gnu.conf').exists()
assert not Path('/etc/ld.so.conf.d/zz_i386-biarch-compat.conf').exists()
assert not Path('/usr/bin/su').exists()
assert not Path(sys.argv[1]).exists()
try: ctypes.CDLL(sys.argv[1])
except OSError: pass
else: raise AssertionError('unapproved library visible')
assert hashlib.sha256(Path('/etc/ld.so.cache').read_bytes()).hexdigest()==sys.argv[3]
assert not Path('/etc/python3.12/sitecustomize.py').exists()
assert sys.flags.isolated and sys.flags.no_site
assert os.getuid()==int(sys.argv[10])!=0
assert not any(Path(p).exists() for p in ('/root','/run'))
assert not any('TOKEN' in key or 'PROXY' in key or 'AUTH' in key for key in os.environ)
assert Path.home()==Path('/home/runner') and list(Path('/home').iterdir())==[Path('/home/runner')]
assert not os.statvfs(sys.argv[9]).f_flag & os.ST_RDONLY
assert os.statvfs('/home/runner/work').f_flag & os.ST_RDONLY
try: os.rename(sys.argv[2],sys.argv[2]+'.unapproved-rename')
except OSError as error: assert error.errno in (errno.EROFS,errno.EBUSY,errno.EPERM)
else: raise AssertionError('immutable namespace ancestor renamed')
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
assert int(status['CapEff'],16)==int(status['CapPrm'],16)==0 and int(status['NoNewPrivs'])==1
assert re.fullmatch(r'(?:volparossa_ci_weather_clients_bwrap//&)?volparossa_ci_weather_clients_child \(enforce\)',
 Path('/proc/self/attr/current').read_text().strip())
mode=sys.argv[6]
assert Path('/state').exists()==(mode!='browser')
if mode=='browser':
 assert os.statvfs('/home/runner').f_flag & os.ST_RDONLY
 expected=Path(sys.argv[9]+'/appdata').stat(); mounted=Path('/home/runner/.mozilla').stat()
 assert (expected.st_dev,expected.st_ino)==(mounted.st_dev,mounted.st_ino)
network=mode=='acquire'
assert (os.readlink('/proc/self/ns/net')==sys.argv[4])==network
if not network: assert [n for _,n in socket.if_nameindex()]==['lo']
if not network: assert Path('/etc/resolv.conf').read_bytes()==b''
allowed=set(json.loads(sys.argv[7]))
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 fields=line.split(); filesystem=fields[fields.index('-')+1]; path=fields[4]
 if filesystem not in ('tmpfs','proc','devpts') and not path.startswith('/dev/') and path not in allowed:
  assert 'ro' in fields[5].split(',')
if sys.argv[8]:
 assert os.statvfs(sys.argv[8]+'/bin/cache').f_flag & os.ST_RDONLY
 if mode!='browser':
  assert Path('/tools/which').is_symlink() and os.readlink('/tools/which')=='/usr/bin/which.debianutils'
  try: Path(sys.argv[8]+'/bin/cache/boundary-unapproved-metadata').open('xb')
  except OSError as error: assert error.errno in (errno.EROFS,errno.EACCES,errno.EPERM)
  else: raise AssertionError('SDK cache directory unexpectedly writable')
assert all(os.statvfs(p).f_flag & os.ST_RDONLY for p in ('/','/usr','/etc',sys.argv[5]))
print(json.dumps(dict(unauthorized_library_denied=True,unauthorized_loader_config_absent=True,
 source_build_cache_hidden=True,private_cache_visible=True,capabilities_zero=True,immutable_ancestry_protected=True,
 no_new_privileges=True,capability_denied_child=True,network_scope_correct=True,read_only_inputs=True)))
'''


def verify(output):
    """One manual hosted round, both fixed profiles, no application builds."""
    inputs, apt = module('prepare_hosted_client_inputs'), module('prepare_hosted_client_apt')
    inputs.hosted_guard(os.environ, 'overmorrow')
    candidate = inputs.document(inputs.read(output / 'apt-candidate.json'))
    apt.bind_package_candidate(candidate, inputs.load_package_inputs('overmorrow'))
    private = output / 'runtime-private'
    private.mkdir(mode=0o700)
    runtime, sdk = private / 'runtime', private / 'flutter-sdk'
    runtime.mkdir(mode=0o700); sdk.mkdir(mode=0o700)
    runtime_preparer = module('prepare_hosted_runtime')
    pin, pin_sha = runtime_preparer.load_pin()
    sdk_preparer = module('prepare_hosted_flutter')
    overmorrow = module('prepare_hosted_overmorrow_ci')
    h = overmorrow.H
    h.RUNTIME, h.NODE, h.NPM = runtime, runtime / 'node/bin/node', runtime / 'node/lib/node_modules/npm/bin/npm-cli.js'
    overmorrow.SDK = sdk
    h.OUTPUT = private / 'harness'
    h.OUTPUT.mkdir(mode=0o700)
    helper, platform = h.policy_helper(), runpy.run_path(str(ROOT / 'scripts/prepare_hosted_decoder.py'))
    attempted = installed = False
    results, failure, phase = {}, None, 'runtime-materialization'
    inputs.write(output / 'runtime-boundary-started.json', canonical(dict(schema=1, admitted=False,
        kind='client-runtime-boundary-start', source=os.environ['GITHUB_SHA'])))
    try:
        runtime_preparer.prepare(runtime, pin, pin_sha, fetch=True, with_npm=True)
        phase = 'sdk-materialization'
        sdk_preparer.prepare(sdk, sdk_preparer.load_pin())
        phase = 'policy-prechecks'
        helper.prechecks(platform)
        h.runtime_inventory()
        sdk_preparer.verify_materialized(sdk)
        # These are the same fixed short-lived profile operations as the
        # existing harness. No new helper/socket/capability permission exists.
        installed = True
        helper.process(['/usr/bin/sudo', '-n', '/usr/bin/install', '-o', 'root', '-g', 'root', '-m', '0600',
            '--', str(h.PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(['/usr/bin/sudo', '-n', helper.PARSER, '--add', '--skip-cache', str(helper.STAGED)], 10)
        witness = output / 'runtime-boundary-unapproved-library.so'
        require(not witness.exists() and not witness.is_symlink(), 'BOUNDARY_WITNESS_EXISTS')
        # A copy of already approved libc is intentionally NOT mounted. If
        # isolation regresses, even the failed negative probe executes no new
        # unreviewed native bytes.
        libc = next(p['files']['usr/lib/x86_64-linux-gnu/libc.so.6'] for p in candidate['packages']
            if 'usr/lib/x86_64-linux-gnu/libc.so.6' in p['files'])
        libc_raw = regular(Path('/usr/lib/x86_64-linux-gnu/libc.so.6'))
        require(sha(libc_raw) == libc['sha256'], 'BOUNDARY_WITNESS_INPUT')
        put(witness, libc_raw)
        for profile in ('drizzli', 'overmorrow'):
            phase = profile + '-view'
            base = private / profile
            base.mkdir(mode=0o700)
            h.PRIVATE, h.STAGE, h.PROOF = base / 'state', base / 'stage', base / 'proof'
            h.FIREFOX = h.BROWSER / 'build/firefox-hosted-ci'
            h.BOUNDARY_DEPLOY, h.BOUNDARY_TABLE_PROOF = base / 'deploy', base / 'table-proof'
            for path in (h.STAGE, h.PROOF, h.BOUNDARY_DEPLOY, h.BOUNDARY_TABLE_PROOF):
                path.mkdir(mode=0o700)
            view = View(base / 'view', subset(candidate['packages'], profile, inputs), profile)
            boundary = Boundary(view, h, h.BROWSER, sdk if profile == 'overmorrow' else None)
            boundary.stage_firefox()
            h.BOUNDARY = boundary
            h.write(h.OUTPUT / 'passwd', f'runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n'.encode()) \
                if not (h.OUTPUT / 'passwd').exists() else None
            h.write(h.OUTPUT / 'group', f'runner:x:{os.getgid()}:\n'.encode()) if not (h.OUTPUT / 'group').exists() else None
            def run(name, command, seconds=60):
                nonlocal phase
                phase = profile + '-' + name
                return h.run(phase, h.sandbox(command, mode='compile', writable=h.STAGE),
                    seconds, env=h.environment(), memory=3 * 1024**3)
            phase = profile + '-cache'
            cache_bindings = boundary.prepare_cache()
            h.PRIVATE.mkdir(mode=0o700)
            (h.PRIVATE / 'cache').mkdir(mode=0o700)
            probes = {'python': '/usr/bin/python3.12', 'node': str(h.NODE),
                'firefox': str(h.FIREFOX / 'firefox-esr'), 'xul': str(h.FIREFOX / 'libxul.so'),
                'git': '/usr/bin/git', 'shell': '/usr/bin/bash'}
            if profile == 'overmorrow':
                probes['dart'] = str(sdk / 'bin/cache/dart-sdk/bin/dart')
            loaded = {name: boundary.loader_semantics(run('loader-' + name, [LOADER,
                *(['--library-path', str(h.FIREFOX)] if name in ('firefox', 'xul') else []), '--list', executable]))
                for name, executable in probes.items()}
            if profile == 'overmorrow':
                overmorrow.PRIVATE, overmorrow.STAGE = h.PRIVATE, h.STAGE
                overmorrow.PROOF, overmorrow.TABLE_PROOF, overmorrow.DEPLOY = h.PROOF, h.BOUNDARY_TABLE_PROOF, h.BOUNDARY_DEPLOY
                overmorrow.SDK_TOOL_STATE = h.PRIVATE / 'flutter-tool-state'
                overmorrow.SDK_TOOL_MOUNT = sdk / 'packages/flutter_tools/.dart_tool'
                overmorrow.prepare_tool_state()
                proof = overmorrow.preflight('compile')
            else:
                proof = h.preflight('compile')
            acquisition = overmorrow.preflight('acquire') if profile == 'overmorrow' else h.preflight('acquire')
            for output_root in (h.PROOF, h.BOUNDARY_TABLE_PROOF):
                for path in (output_root / 'appdata', output_root / 'appdata/firefox', output_root / 'appdata/firefox-esr'):
                    path.mkdir(mode=0o700)
            browser = overmorrow.preflight('browser', proof=h.PROOF) if profile == 'overmorrow' else h.preflight('browser')
            require(run('browser-source-identity', ['/usr/bin/git', '-C', str(h.BROWSER), 'rev-parse', 'HEAD']).decode().strip()
                == h.BROWSER_COMMIT, 'BOUNDARY_BROWSER_IDENTITY')
            node_version = run('node-version', [str(h.NODE), '-e', 'process.stdout.write(process.versions.node + "\\n")']).decode().strip()
            require(node_version == pin['artifacts']['node']['version'], 'BOUNDARY_NODE_VERSION')
            npm_pin, _npm_sha = runtime_preparer.load_npm_pin(pin)
            npm_version = run('npm-version', [str(h.NODE), str(h.NPM), '--version']).decode().strip()
            require(npm_version == npm_pin['version'], 'BOUNDARY_NPM_VERSION')
            firefox_output = run('firefox-version', [str(h.FIREFOX / 'firefox-esr'), '--version']).decode()
            require(re.search(r'^Mozilla Firefox ' + re.escape(h.FIREFOX_VERSION) + r'(?:esr)?$',
                firefox_output, re.M), 'BOUNDARY_FIREFOX_VERSION')
            font_output = run('font-match', ['/usr/bin/fc-match', '-f', '%{file}\n', 'monospace']).decode()
            fonts = re.findall(r'^(/usr/share/fonts/[^\r\n]+)$', font_output, re.M)
            require(len(fonts) == 1 and font_output.strip() == fonts[0], 'BOUNDARY_FONT_SELECTION')
            font_name, font = resolve(fonts[0], view.entries)
            require(font['type'] == 'file' and font_name.startswith('usr/share/fonts/'), 'BOUNDARY_FONT_SELECTION')
            sdk_version = None
            if profile == 'overmorrow':
                # The same Overmorrow adapter supplies individual scalar SDK
                # metadata overlays; no app, pub acquisition or compilation.
                phase = 'overmorrow-flutter-version'
                sdk_output = h.run('overmorrow-flutter-version', overmorrow.sandbox([str(sdk / 'bin/flutter'),
                    '--version', '--machine', '--no-version-check'], mode='compile'), 90,
                    env=overmorrow.environment(), memory=3 * 1024**3)
                sdk_version = json.loads(sdk_output)
                require(sdk_version.get('frameworkVersion') == sdk_preparer.VERSION
                    and sdk_version.get('frameworkRevision') == sdk_preparer.COMMIT, 'BOUNDARY_FLUTTER_VERSION')
            boundary.check()
            results[profile] = dict(package_inputs_sha256=inputs.PACKAGE_INPUTS[profile][1],
                selected_entries=len(view.entries), view_sha256=sha(canonical(view.entries)),
                private_cache_sha256=view.cache_sha, semantic_library_bindings=cache_bindings,
                actual_loader_selections=loaded, negative_probe=proof,
                acquisition_preflight=acquisition, browser_preflight=browser,
                browser_config=boundary.firefox_binding(),
                runtime_versions=dict(node=node_version, npm=npm_version, firefox=h.FIREFOX_VERSION,
                    flutter=sdk_version.get('frameworkVersion') if sdk_version else None),
                selected_font=dict(path='/' + font_name, sha256=font['sha256']),
                source_sha256=sha(canonical(boundary.source_files)), runtime=h.runtime_inventory(),
                sdk=sdk_preparer.verify_materialized(sdk, allow_build_state=True) if profile == 'overmorrow' else None,
                host_usr_visible=False, host_cache_visible=False, whole_source_parent_visible=False)
        inputs.write(output / 'runtime-boundary.json', canonical(dict(schema=1, admitted=False,
            kind='client-closed-runtime-input-verification', source=os.environ['GITHUB_SHA'], profiles=results,
            build_environment_admitted=False, consumer_admitted=False, compiled=False,
            boundary_verified=True, original_package_inputs_unchanged=True)))
    except BaseException as error:
        failure = dict(category=type(error).__name__, message=str(error)[:2048])
        raise
    finally:
        h.BOUNDARY = None
        try:
            diagnostics = []
            for step in h.LOGS:
                require(re.fullmatch(r'(?:drizzli|overmorrow)-(?:cache-generate|cache-list|loader-(?:python|node|firefox|xul|dart|git|shell)|preflight-(?:acquire|compile|browser)|browser-source-identity|node-version|npm-version|firefox-version|font-match|flutter-version)',
                    step['name']), 'BOUNDARY_LOG_NAME')
                raw = regular(h.OUTPUT / (step['name'] + '.log'), 2 * 1024**2)
                diagnostics.append(dict(step, stdout=raw[:65536].decode('utf-8', errors='replace'),
                    stdout_truncated=len(raw) > 65536))
            inputs.write(output / 'runtime-boundary-diagnostics.json', canonical(dict(schema=1, admitted=False,
                kind='client-runtime-boundary-diagnostics', phase=phase, failure=failure, probes=diagnostics)))
        finally:
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and h.DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed) if installed or attempted else dict(complete=True)
            inputs.write(output / 'runtime-boundary-cleanup.json', canonical(dict(schema=1, admitted=False,
                kind='client-runtime-boundary-cleanup', process_drain_confirmed=h.DRAIN_CONFIRMED,
                policy_removed=cleaning['complete'], compiled=False)))
            # The fixture remains in the private inputcandidate, excluded from
            # projection. Its existing guarded cleanup owns removal only after
            # both installer and runtime process/policy receipts confirm drain.
            require(h.DRAIN_CONFIRMED and cleaning['complete'], 'BOUNDARY_CLEANUP_UNPROVEN')
