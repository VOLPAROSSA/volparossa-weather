#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify F09 Debian source-build inputs; never install, download, or admit them.

The Core VM runner supplies the fixed evidence files. A candidate is data for
review, never build authority. Only the separately reviewed Core source lock at
LOCK can authorize the explicit source builder. No caller-selected lock exists.
"""
import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile

LOCK = Path('/home/vpci/source/tests/helper/weather-source-build-environment-v1.json')
KEYRING = Path('/usr/share/keyrings/debian-archive-keyring.gpg')
SNAPSHOT = '20261023T000000Z'
IMAGE_SHA512 = ('184761b0dad0f9ace02f9298050ca96ce3caa39a461a47706d47ff9698b59933918'
                'b91b40177fbd4d392f6446af8b4d18ecb94caca988169b19641606bf34003')
ROOT_PACKAGES = ['build-essential', 'cmake', 'git', 'mawk', 'python3', 'bubblewrap',
                 'binutils', 'util-linux', 'ca-certificates']
APT_OPTIONS = ['--yes', '--no-install-recommends', '--no-remove',
               '-o', 'Acquire::Check-Valid-Until=false', '-o', 'Acquire::Languages=none']
INDEX_PATH = 'main/binary-amd64/Packages.xz'
SCOPE = dict(disposable_test_only=True, decoder_authorized=False, compiled=False)
REPOSITORIES = {
    'debian': dict(codename='trixie', inrelease_bytes=140421,
        archive_url='https://snapshot.debian.org/archive/debian/20261023T000000Z/',
        inrelease_url='https://snapshot.debian.org/archive/debian/20261023T000000Z/dists/trixie/InRelease',
        inrelease_sha256='0584fba32e13e0ab8285fb16c27adea1ec03a73669c18702821094fd6ca86675',
        final_url='https://snapshot.debian.org/file/aa33cb317177428f33c9ff72fc3e9b634645f6ae/InRelease',
        signing_fingerprints=['4CB50190207B4758A3F73A796ED0E7B82643E131',
            'B8E5F13176D2A7A75220028078DBA3BC47EF2265', '41587F7DB8C774BCCF131416762F67A0B2C39DE4']),
    'debian-security': dict(codename='trixie-security', inrelease_bytes=43409,
        archive_url='https://snapshot.debian.org/archive/debian-security/20261023T000000Z/',
        inrelease_url='https://snapshot.debian.org/archive/debian-security/20261023T000000Z/dists/trixie-security/InRelease',
        inrelease_sha256='f439c50d207c42e50abd7db7804b0afa16eb57b67775cfa0996234176aeb26a1',
        final_url='https://snapshot.debian.org/file/7957d5dd5109d37741be18971cb12cb4d5c08b8b/InRelease',
        signing_fingerprints=['B0CAB9266E8C3929798B3EEEBDE6D2B9216EC7A8',
            '89C87ACEA5DD6B8E6A7068808E9F831205B4BA95']),
}
MAX_INDEX = 128 * 1024**2
MAX_RECORD = 32 * 1024**2
STATUS_FORMAT = '${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'DUPLICATE_KEY')
        value[key] = item
    return value


def read_file(path, maximum=2 * 1024**2):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid in (0, os.getuid()) and not before.st_mode & 0o022
                and 0 < before.st_size <= maximum, 'UNSAFE_INPUT')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require(len(raw) == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'INPUT_CHANGED')
        return raw


def json_file(path):
    return json.loads(read_file(path, MAX_RECORD), object_pairs_hook=unique)


def sha256(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def package_row(row):
    require(type(row) is dict and set(row) == {'name', 'version', 'architecture'}, 'PACKAGE_SCHEMA')
    require(type(row['name']) is str and re.fullmatch('[a-z0-9][a-z0-9+.-]{0,127}', row['name'])
            and type(row['version']) is str and re.fullmatch('[0-9][A-Za-z0-9.+:~_-]{0,255}', row['version'])
            and row['architecture'] in ('amd64', 'all'), 'PACKAGE_IDENTITY')
    return row['name']


def inventory(raw):
    require(0 < len(raw) <= 2 * 1024**2, 'STATUS_BOUND')
    rows = []
    for line in raw.decode('ascii').splitlines():
        fields = line.split('\t')
        require(len(fields) == 4 and fields[3] == 'installed', 'STATUS_NOT_INSTALLED')
        rows.append(dict(zip(('name', 'version', 'architecture'), fields[:3])))
    validate_inventory(rows)
    return sorted(rows, key=lambda item: item['name'])


def validate_inventory(rows):
    require(type(rows) is list and 0 < len(rows) <= 4096, 'INVENTORY_BOUND')
    names = [package_row(row) for row in rows]
    require(len(set(names)) == len(names), 'DUPLICATE_PACKAGE')


def control_records(raw):
    """Bounded Debian control records; reject ambiguity before using any field."""
    require(len(raw) <= MAX_INDEX, 'INDEX_BOUND')
    record, previous = {}, None
    for line in raw.decode('utf-8').splitlines() + ['']:
        if not line:
            if record:
                yield record
            record, previous = {}, None
        elif line[0] in ' \t':
            require(previous is not None, 'CONTROL_CONTINUATION')
            record[previous] += '\n' + line[1:]
        else:
            key, separator, value = line.partition(':')
            require(separator and re.fullmatch('[A-Za-z][A-Za-z0-9-]*', key)
                    and key not in record and (not value or value.startswith(' ')), 'CONTROL_FIELD')
            record[key], previous = value.removeprefix(' '), key


def verify_release(path, repository):
    pin = REPOSITORIES[repository]
    raw = read_file(path, 256 * 1024)
    require(len(raw) == pin['inrelease_bytes'] and digest(raw) == pin['inrelease_sha256'], 'INRELEASE_PIN')
    # The keyring belongs to the already pinned guest image; never fetch a key.
    result = subprocess.run(['/usr/bin/gpgv', '--keyring', str(KEYRING), '--status-fd', '2',
                             '--output', '-', str(path)], capture_output=True, check=False,
                            timeout=20, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd='/')
    require(result.returncode == 0 and len(result.stdout) <= 256 * 1024
            and len(result.stderr) <= 64 * 1024, 'INRELEASE_SIGNATURE')
    status = result.stderr.decode('ascii')
    fingerprints = re.findall(r'^\[GNUPG:\] VALIDSIG ([A-F0-9]{40}) ', status, re.M)
    require(sorted(fingerprints) == sorted(pin['signing_fingerprints']), 'INRELEASE_SIGNERS')
    records = list(control_records(result.stdout))
    require(len(records) == 1 and records[0].get('Codename') == pin['codename'], 'RELEASE_CODENAME')
    release = records[0]
    require('amd64' in release.get('Architectures', '').split()
            and 'main' in release.get('Components', '').split(), 'RELEASE_COMPONENT')
    indexes = {}
    for line in release.get('SHA256', '').splitlines():
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 3 and sha256(fields[0]) and fields[1].isdigit()
                and fields[2] not in indexes, 'RELEASE_INDEX')
        indexes[fields[2]] = dict(bytes=int(fields[1]), sha256=fields[0])
    require(INDEX_PATH in indexes and 0 < indexes[INDEX_PATH]['bytes'] <= 32 * 1024**2, 'MISSING_INDEX')
    return dict(**pin, index_path=INDEX_PATH, index=indexes[INDEX_PATH],
                keyring_sha256=digest(read_file(KEYRING)))


def index_records(path, expected):
    raw = read_file(path, 32 * 1024**2)
    require(len(raw) == expected['bytes'] and digest(raw) == expected['sha256'], 'INDEX_DIGEST')
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
    data = decoder.decompress(raw, max_length=MAX_INDEX + 1)
    require(len(data) <= MAX_INDEX and decoder.eof and not decoder.unused_data, 'INDEX_BOUND')
    return control_records(data)


def package_delta(before, after):
    validate_inventory(before)
    validate_inventory(after)
    old = {item['name']: item for item in before}
    new = {item['name']: item for item in after}
    require(old.keys() <= new.keys(), 'PACKAGE_REMOVAL')
    require(set(ROOT_PACKAGES) <= new.keys(), 'MISSING_ROOT_PACKAGE')
    return [new[name] for name in sorted(new) if old.get(name) != new[name]]


def indexed_packages(directory, changes, repositories):
    needed = {(item['name'], item['version'], item['architecture']) for item in changes}
    found = {}
    for repository, pin in repositories.items():
        for record in index_records(directory / (repository + '.Packages.xz'), pin['index']):
            identity = tuple(record.get(key) for key in ('Package', 'Version', 'Architecture'))
            if identity not in needed:
                continue
            filename = record.get('Filename', '')
            parts = PurePosixPath(filename).parts
            require(filename.startswith('pool/main/') and len(parts) >= 4 and
                    all(re.fullmatch('[A-Za-z0-9+.:~_-]+', part) and part not in ('.', '..') for part in parts)
                    and filename.endswith('.deb'), 'DEB_FILENAME')
            size, checksum = record.get('Size', ''), record.get('SHA256')
            require(size.isdigit() and 0 < int(size) <= 128 * 1024**2 and sha256(checksum), 'DEB_METADATA')
            item = dict(name=identity[0], version=identity[1], architecture=identity[2],
                        repository=repository, filename=filename, bytes=int(size), sha256=checksum)
            require(identity not in found, 'AMBIGUOUS_PACKAGE')
            found[identity] = item
    require(set(found) == needed, 'PACKAGE_NOT_IN_SIGNED_INDEX')
    return sorted(found.values(), key=lambda item: item['name'])


def verified_packages(directory, changes, repositories):
    packages = indexed_packages(directory, changes, repositories)
    names = [PurePosixPath(item['filename']).name for item in packages]
    require(len(names) == len(set(names)), 'DUPLICATE_DEB')
    debs = directory / 'debs'
    require(debs.is_dir() and not debs.is_symlink() and set(path.name for path in debs.iterdir()) == set(names),
            'DEB_SET')
    for item, name in zip(packages, names):
        raw = read_file(debs / name, 128 * 1024**2)
        require(len(raw) == item['bytes'] and digest(raw) == item['sha256'], 'DEB_DIGEST')
        item['files'] = deb_files(raw)
    return packages


def resolver_inventory(resolver):
    require(0 < len(resolver) <= 1024**2 and b'\x00' not in resolver, 'RESOLVER_LOG')
    resolved = []
    for line in resolver.decode('ascii').splitlines():
        require(not line.startswith('Remv '), 'RESOLVER_REMOVAL')
        if line.startswith('Inst '):
            match = re.fullmatch(r'Inst ([a-z0-9][a-z0-9+.-]*)(?::amd64)? (?:\[[^\]]+\] )?'
                                 r'\(([^ ]+) .* \[(amd64|all)\]\)', line)
            require(match is not None, 'RESOLVER_INSTALL')
            resolved.append(dict(name=match[1], version=match[2], architecture=match[3]))
    if resolved:
        validate_inventory(resolved)
    return sorted(resolved, key=lambda item: item['name'])


def member_path(name):
    name = name.removeprefix('./')
    require(not name.startswith('/') and all(part not in ('', '.', '..') for part in name.split('/')), 'MEMBER_PATH')
    # Debian 13 merged-/usr paths have one canonical executable name.
    if name.startswith(('bin/', 'sbin/', 'lib/', 'lib64/')):
        name = 'usr/' + name
    return '/' + name


def deb_files(raw):
    """Read archive data as data, without running dpkg or maintainer scripts."""
    require(raw.startswith(b'!<arch>\n'), 'DEB_AR')
    offset, members = 8, {}
    while offset < len(raw):
        header = raw[offset:offset + 60]
        require(len(header) == 60 and header[58:] == b'`\n', 'DEB_AR')
        name = header[:16].decode('ascii').strip().removesuffix('/')
        size = header[48:58].decode('ascii').strip()
        require(size.isdigit() and name not in members and len(members) < 4, 'DEB_AR')
        size = int(size)
        offset += 60
        require(offset + size <= len(raw), 'DEB_AR')
        members[name] = raw[offset:offset + size]
        offset += size + size % 2
    require(offset == len(raw) and members.get('debian-binary') == b'2.0\n'
            and len(members) == 3, 'DEB_AR')
    data = [name for name in members if name in ('data.tar.xz', 'data.tar.gz', 'data.tar')]
    require(len(data) == 1 and any(name.startswith('control.tar.') for name in members), 'DEB_DATA')
    files, seen, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(members[data[0]]), mode='r|*') as archive:
        for member in archive:
            if member.name in ('.', './') and member.isdir():
                continue
            path = member_path(member.name.rstrip('/') if member.isdir() else member.name)
            require(path not in seen and len(seen) < 100000, 'DEB_MEMBER_SET')
            seen.add(path)
            require(member.isdir() or member.isreg() or member.issym() or member.islnk(), 'DEB_MEMBER_TYPE')
            if not member.isreg():
                continue
            require(0 <= member.size <= 256 * 1024**2, 'DEB_MEMBER_BOUND')
            total += member.size
            require(total <= 1024**3, 'DEB_EXPANSION_BOUND')
            stream, checksum, size = archive.extractfile(member), hashlib.sha256(), 0
            while chunk := stream.read(1024**2):
                size += len(chunk)
                checksum.update(chunk)
            require(size == member.size, 'DEB_MEMBER_SIZE')
            files[path] = dict(bytes=size, sha256=checksum.hexdigest())
    require(files, 'DEB_EMPTY')
    return files


def validate_files(files):
    require(type(files) is dict and 0 < len(files) <= 100000, 'FILES_BOUND')
    for path, item in files.items():
        require(type(path) is str and path.startswith('/') and member_path(path[1:]) == path
                and type(item) is dict and set(item) == {'bytes', 'sha256'}
                and type(item['bytes']) is int and 0 <= item['bytes'] <= 256 * 1024**2
                and sha256(item['sha256']), 'FILE_PIN')


def capture_base(directory):
    # This operation hashes data only. The Core runner invokes it once before
    # APT in a fresh pinned guest; review does not trust it merely for existing.
    require(Path('/home/vpci/source').is_dir() and os.uname().machine == 'x86_64', 'PINNED_GUEST_REQUIRED')
    files, total = {}, 0
    for root, directories, names in os.walk('/usr', followlinks=False):
        directories[:] = sorted(name for name in directories if not Path(root, name).is_symlink())
        for name in sorted(names):
            path = Path(root, name)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            require(len(files) < 100000, 'BASE_FILES_BOUND')
            # Image-owned files can be empty; use a bounded no-follow stream.
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and before.st_size <= 256 * 1024**2, 'BASE_FILES_BOUND')
                checksum, count = hashlib.sha256(), 0
                while chunk := stream.read(1024**2):
                    count += len(chunk)
                    checksum.update(chunk)
                after = os.fstat(stream.fileno())
                require(count == before.st_size and
                        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'BASE_FILE_CHANGED')
            total += count
            require(count <= 256 * 1024**2 and total <= 4 * 1024**3, 'BASE_FILES_BOUND')
            files[str(path)] = dict(bytes=count, sha256=checksum.hexdigest())
    validate_files(files)
    write_candidate_file(directory / 'base-files.json', canonical(files))
    return dict(admitted=False, files=len(files), sha256=digest(canonical(files)))


def write_candidate_file(path, raw):
    require(len(raw) <= MAX_RECORD, 'RECORD_BOUND')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)


def candidate(directory):
    require(directory.is_absolute() and directory.resolve() == directory and directory.is_dir(), 'EVIDENCE_DIRECTORY')
    before_raw, after_raw = read_file(directory / 'before.tsv'), read_file(directory / 'after.tsv')
    before, after = inventory(before_raw), inventory(after_raw)
    repositories = {name: verify_release(directory / (name + '.InRelease'), name) for name in REPOSITORIES}
    changes = package_delta(before, after)
    packages = verified_packages(directory, changes, repositories)
    resolver = read_file(directory / 'resolver.log', 1024**2)
    require(resolver_inventory(resolver) == changes, 'RESOLVER_CLOSURE')
    base_files_raw = read_file(directory / 'base-files.json', MAX_RECORD)
    base_files = json.loads(base_files_raw, object_pairs_hook=unique)
    validate_files(base_files)
    return dict(schema=1, kind='volparossa-weather-source-environment-candidate', admitted=False,
                environment_id='weather-debian13-source-20261024-v1', scope=dict(SCOPE),
                image_sha512=IMAGE_SHA512, snapshot=SNAPSHOT, roots=list(ROOT_PACKAGES),
                apt_options=list(APT_OPTIONS), repositories=repositories, before=before, after=after,
                packages=packages, base_files=base_files,
                evidence=dict(before_sha256=digest(before_raw), after_sha256=digest(after_raw),
                    base_files_sha256=digest(base_files_raw),
                    resolver_sha256=digest(resolver)))


def validate_record(value, admitted):
    fields = {'schema', 'kind', 'admitted', 'environment_id', 'scope', 'image_sha512', 'snapshot',
              'roots', 'apt_options', 'repositories', 'before', 'after', 'packages', 'base_files', 'evidence'}
    require(type(value) is dict and set(value) == fields | ({'review'} if admitted else set()), 'ENVIRONMENT_SCHEMA')
    require(type(value['schema']) is int and value['schema'] == 1 and value['admitted'] is admitted
            and value['kind'] == ('volparossa-weather-source-environment-lock' if admitted else
                                  'volparossa-weather-source-environment-candidate'), 'ENVIRONMENT_NOT_ADMITTED')
    require(value['environment_id'] == 'weather-debian13-source-20261024-v1' and value['scope'] == SCOPE
            and all(type(item) is bool for item in value['scope'].values())
            and value['image_sha512'] == IMAGE_SHA512 and value['snapshot'] == SNAPSHOT
            and value['roots'] == ROOT_PACKAGES and value['apt_options'] == APT_OPTIONS, 'ENVIRONMENT_PROFILE')
    changes = package_delta(value['before'], value['after'])
    require(value['before'] == sorted(value['before'], key=lambda item: item['name'])
            and value['after'] == sorted(value['after'], key=lambda item: item['name']), 'INVENTORY_ORDER')
    repositories = value['repositories']
    require(type(repositories) is dict and set(repositories) == set(REPOSITORIES), 'REPOSITORIES')
    for name, pin in REPOSITORIES.items():
        row = repositories[name]
        require(type(row) is dict and set(row) == set(pin) | {'index_path', 'index', 'keyring_sha256'}
                and all(row[key] == expected for key, expected in pin.items())
                and row['index_path'] == INDEX_PATH and sha256(row['keyring_sha256']), 'REPOSITORY_PIN')
        require(type(row['index']) is dict and set(row['index']) == {'bytes', 'sha256'}
                and type(row['index']['bytes']) is int and 0 < row['index']['bytes'] <= 32 * 1024**2
                and sha256(row['index']['sha256']), 'INDEX_SCHEMA')
    packages = value['packages']
    require(type(packages) is list and len(packages) == len(changes), 'PACKAGE_CLOSURE')
    for item, changed in zip(packages, changes):
        require(type(item) is dict and set(item) == {'name', 'version', 'architecture', 'repository',
                    'filename', 'bytes', 'sha256', 'files'} and all(item[key] == val for key, val in changed.items()), 'PACKAGE_CLOSURE')
        filename = item['filename']
        require(item['repository'] in repositories and type(filename) is str
                and filename.startswith('pool/main/') and filename.endswith('.deb')
                and all(re.fullmatch('[A-Za-z0-9+.:~_-]+', part) and part not in ('.', '..')
                        for part in filename.split('/'))
                and type(item['bytes']) is int and 0 < item['bytes'] <= 128 * 1024**2
                and sha256(item['sha256']), 'PACKAGE_PIN')
        validate_files(item['files'])
    validate_files(value['base_files'])
    evidence = value['evidence']
    require(type(evidence) is dict and set(evidence) == {'before_sha256', 'after_sha256', 'resolver_sha256', 'base_files_sha256'}
            and all(sha256(item) for item in evidence.values()), 'EVIDENCE_SCHEMA')
    if admitted:
        review = value['review']
        require(type(review) is dict and set(review) == {'candidate_sha256', 'review_commit'}
                and sha256(review['candidate_sha256']) and type(review['review_commit']) is str
                and re.fullmatch('[0-9a-f]{40}', review['review_commit']), 'REVIEW_REQUIRED')
        original = {key: item for key, item in value.items() if key != 'review'}
        original.update(kind='volparossa-weather-source-environment-candidate', admitted=False)
        require(digest(canonical(original)) == review['candidate_sha256'], 'REVIEW_CANDIDATE_BINDING')
    return value


def installed_inventory():
    result = subprocess.run(['/usr/bin/dpkg-query', '--show', '--showformat=' + STATUS_FORMAT],
                            capture_output=True, check=True, timeout=20,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd='/')
    return inventory(result.stdout)


def check_environment():
    raw = read_file(LOCK, MAX_RECORD)
    value = validate_record(json.loads(raw, object_pairs_hook=unique), True)
    require(installed_inventory() == value['after'], 'INSTALLED_INVENTORY_MISMATCH')
    return dict(environment_lock_sha256=digest(raw), environment_id=value['environment_id'],
                image_sha512=IMAGE_SHA512, snapshot=SNAPSHOT, inventory=value['after'],
                packages=value['packages'], base_files=value['base_files'])


def bind_tools(tools, environment):
    installed = {item['name']: item for item in environment['inventory']}
    bindings = {}
    for name, item in sorted(tools.items()):
        path = item['path']
        require(type(path) is str and path.startswith('/usr/') and Path(path).resolve() == Path(path), 'TOOL_PATH')
        result = subprocess.run(['/usr/bin/dpkg-query', '--search', path], capture_output=True, check=True,
                                timeout=10, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd='/')
        lines = result.stdout.decode('ascii').splitlines()
        require(len(lines) == 1 and lines[0].endswith(': ' + path), 'TOOL_PACKAGE_OWNER')
        owner = lines[0][:-len(': ' + path)].removesuffix(':amd64')
        require(owner in installed, 'TOOL_PACKAGE_NOT_LOCKED')
        changed = {row['name']: row for row in environment['packages']}
        expected_files = changed[owner]['files'] if owner in changed else environment['base_files']
        require(path in expected_files and item['sha256'] == expected_files[path]['sha256']
                and item['bytes'] == expected_files[path]['bytes'], 'TOOL_PACKAGE_BYTES')
        bindings[name] = dict(package=installed[owner], path=path, sha256=item['sha256'])
    return bindings


def verify_development_files(environment):
    """Check the actual headers and linkable objects against reviewed bytes.

    Paths removed by an upgrade are not inputs. Any current regular library or
    header must match either its reviewed .deb member or the original image.
    Symlinks are resolved and the target, including directory links, is checked.
    """
    expected = dict(environment['base_files'])
    package_paths = set()
    for package in environment['packages']:
        require(not package_paths.intersection(package['files']), 'PACKAGE_FILE_COLLISION')
        package_paths.update(package['files'])
        expected.update(package['files'])
    checked = {}
    for base in (Path('/usr/include'), Path('/usr/lib')):
        if not base.exists():
            continue
        for root, directories, names in os.walk(base, followlinks=False):
            for name in sorted(names):
                path = Path(root, name)
                if not (path.is_relative_to('/usr/include') or path.is_relative_to('/usr/lib/gcc')
                        or re.search(r'\.so(?:\.|$)|\.a$', name)):
                    continue
                resolved = path.resolve(strict=True)
                require(resolved.is_relative_to('/usr') and str(resolved) in expected, 'DEVELOPMENT_FILE_NOT_LOCKED')
                if str(resolved) in checked:
                    continue
                info = resolved.stat()
                require(stat.S_ISREG(info.st_mode) and info.st_size <= 256 * 1024**2, 'DEVELOPMENT_FILE_TYPE')
                with os.fdopen(os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    require(stat.S_ISREG(before.st_mode) and before.st_size <= 256 * 1024**2, 'DEVELOPMENT_FILE_TYPE')
                    raw = stream.read(256 * 1024**2 + 1)
                    after = os.fstat(stream.fileno())
                require(len(raw) == before.st_size and
                        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'DEVELOPMENT_FILE_CHANGED')
                actual = dict(bytes=len(raw), sha256=digest(raw))
                require(actual == expected[str(resolved)], 'DEVELOPMENT_FILE_BYTES')
                checked[str(resolved)] = actual
            # Header/compiler subtrees check every file, whereas the general
            # library tree checks only linkable objects. A directory alias may
            # not move headers into that more weakly classified tree.
            for name in directories:
                path = Path(root, name)
                if path.is_symlink():
                    resolved = path.resolve(strict=True)
                    require(resolved.is_relative_to('/usr/include') or resolved.is_relative_to('/usr/lib'),
                            'DEVELOPMENT_DIRECTORY_LINK')
                    if path.is_relative_to('/usr/include') or path.is_relative_to('/usr/lib/gcc'):
                        require(resolved.is_relative_to('/usr/include') or resolved.is_relative_to('/usr/lib/gcc'),
                                'DEVELOPMENT_DIRECTORY_COVERAGE')
    return digest(canonical(checked))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('plan')
    actions.add_parser('check-environment')
    for name in ('candidate', 'verify-candidate'):
        actions.add_parser(name).add_argument('--evidence-dir', type=Path, required=True)
    actions.add_parser('capture-base').add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            value = dict(admitted=False, scope=dict(SCOPE), snapshot=SNAPSHOT,
                         repositories=REPOSITORIES, roots=ROOT_PACKAGES, apt_options=APT_OPTIONS,
                         trusted_lock_path=str(LOCK), status_format=STATUS_FORMAT)
        elif args.action == 'check-environment':
            value = check_environment()
        elif args.action == 'capture-base':
            value = capture_base(args.evidence_dir)
        else:
            value = validate_record(candidate(args.evidence_dir), False)
            path = args.evidence_dir / 'candidate.json'
            if args.action == 'candidate':
                write_candidate_file(path, canonical(value))
            else:
                require(json_file(path) == value, 'CANDIDATE_EVIDENCE_MISMATCH')
            value = dict(admitted=False, verified=True, candidate_sha256=digest(canonical(value)), scope=dict(SCOPE))
        print(json.dumps(value, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, lzma.LZMAError, tarfile.TarError, subprocess.SubprocessError):
        print('DECODER_ENVIRONMENT_VERIFICATION_FAILED', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
