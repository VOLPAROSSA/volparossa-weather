#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Acquire fixed Ubuntu package data or explicitly inventory installed inputs.

The historical candidate path never installs packages. The separately selected
installed inventory provisions reviewed local packages only on a guarded runner.

The runner's original apt/gpgv/keyring are bootstrap observations. They cannot
become source-build authority simply by being captured. Independent review must
bind these and every installed executable/configuration before a cold build.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import tempfile
import subprocess
import time
import unicodedata

spec = importlib.util.spec_from_file_location('_client_inputs', Path(__file__).with_name('prepare_hosted_client_inputs.py'))
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)
ROOT = I.ROOT
SNAPSHOT = '20261023T000000Z'
BASE = f'https://snapshot.ubuntu.com/ubuntu/{SNAPSHOT}/'
KEYRING = Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg')
# Original member of ubuntu-keyring_2023.11.28.1_all.deb (11124 bytes),
# package SHA256 36de43b15853ccae0028e9a767613770c704833f82586f28eb262f0311adb8a8.
# Independently verified against the fixed noble index and Ubuntu's published
# archive-key fingerprints. The runner's mutable file metadata is observation,
# never authority for these expected public-key bytes.
KEYRING_BYTES = 3607
KEYRING_SHA256 = '80a36b0a6de2f69f49d2df75ef473ccde121e9e190b9ea01d20a4f63778d5c31'
ARCHIVE_SIGNER = 'F6ECB3762474EDA9D21B7022871920D1991BC93C'
SUITES = {
    'noble': dict(bytes=255850, sha256='cdb2f31d809f589719a53c6ad15f255b27569c4059542ada282aaa21b8e164b0'),
    'noble-updates': dict(bytes=126125, sha256='600c42e6d50b8bd7200f6a5c9e0d2eaee24728bddeb6c1529da9fc38c753a088'),
    'noble-security': dict(bytes=126127, sha256='f90eb747b2e1edab8e85d0f897423a3d0a404e1480c4848a6e4b00bd4f99ad4e'),
}
COMMON = ('apparmor', 'bubblewrap', 'git', 'python3', 'mawk', 'util-linux', 'iproute2', 'ca-certificates',
    'bash', 'dash', 'coreutils', 'grep', 'sed', 'findutils', 'gzip', 'libc-bin',
    'libgtk-3-0t64', 'libdbus-glib-1-2', 'libasound2t64', 'libx11-xcb1', 'libxt6t64', 'libpci3',
    'fontconfig', 'fonts-dejavu-core', 'libnspr4', 'libevent-2.1-7t64', 'libvpx9')
FLUTTER = ('curl', 'unzip', 'xz-utils', 'zip', 'libglu1-mesa', 'debianutils')
PROFILES = {'web': COMMON, 'flutter': COMMON + FLUTTER, 'android': COMMON + FLUTTER + ('openjdk-17-jdk-headless',)}
ENV = dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='UTC', HOME='/nonexistent',
    DEBIAN_FRONTEND='noninteractive', APT_CONFIG='/dev/null')


DIAGNOSTIC_OUTPUT = None
APT_CONFIG_FILE = None


def run(argv, seconds=180, maximum=16 * 1024**2):
    # Bound output while the baseline distro inspection tool is running.
    # Temporary files remain inside the workspace; never execute their bytes.
    with tempfile.TemporaryFile(dir=ROOT / 'build') as stdout, tempfile.TemporaryFile(dir=ROOT / 'build') as stderr:
        environment = dict(ENV, APT_CONFIG=str(APT_CONFIG_FILE)) if APT_CONFIG_FILE is not None else ENV
        child = None
        deadline = time.monotonic() + seconds
        try:
            # Defer cancellation only until the child PID is owned by finally.
            pending = []
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
            for sig in handlers:
                signal.signal(sig, lambda signum, _frame: pending.append(signum))
            try:
                child = subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL, stdout=stdout,
                    stderr=stderr, start_new_session=True, umask=0o077)
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
            I.require(not pending, 'CLIENT_INPUT_INTERRUPTED')
            while child.poll() is None:
                I.require(time.monotonic() < deadline, 'APT_INSPECTION_DEADLINE')
                I.require(os.fstat(stdout.fileno()).st_size <= maximum
                    and os.fstat(stderr.fileno()).st_size <= 2 * 1024**2, 'APT_LOG_BOUND')
                time.sleep(0.05)
            I.require(os.fstat(stdout.fileno()).st_size <= maximum
                and os.fstat(stderr.fileno()).st_size <= 2 * 1024**2, 'APT_LOG_BOUND')
            I.require(child.returncode == 0, 'APT_INSPECTION_FAILED')
            stdout.seek(0)
            return stdout.read(maximum + 1)
        finally:
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
            if child is not None and child.returncode != 0 and DIAGNOSTIC_OUTPUT is not None:
                stderr.seek(0)
                path = DIAGNOSTIC_OUTPUT / 'apt-failure.log'
                if not path.exists():
                    I.write(path, stderr.read(2 * 1024**2))


def paragraphs(raw):
    I.require(len(raw) <= 512 * 1024**2, 'PACKAGES_EXPANSION_BOUND')
    for paragraph in raw.decode('utf-8').split('\n\n'):
        value, previous = {}, None
        for line in paragraph.splitlines():
            if line.startswith((' ', '\t')):
                I.require(previous is not None, 'CONTROL_CONTINUATION')
                value[previous] += '\n' + line
                continue
            key, sep, item = line.partition(':')
            I.require(not item or item.startswith(' '), 'CONTROL_FIELD')
            item = item.removeprefix(' ')
            I.require(sep and key not in value and re.fullmatch(r'[A-Za-z0-9-]+', key), 'CONTROL_FIELD')
            value[key], previous = item, key
        if value:
            yield value


def signature_identities(status):
    I.require(type(status) is bytes and len(status) <= 65536, 'UBUNTU_SIGNATURE_BOUND')
    signers = re.findall(rb'^\[GNUPG:\] VALIDSIG ([0-9A-F]{40}) .* ([0-9A-F]{40})$', status, re.M)
    I.require(0 < len(signers) <= 8 and len(set(signers)) == len(signers)
        and not re.search(rb'\[GNUPG:\] (?:BADSIG|ERRSIG|REVKEYSIG|EXPKEYSIG|EXPSIG|NO_PUBKEY)', status), 'UBUNTU_SIGNATURE')
    return [dict(subkey=a.decode(), primary=b.decode()) for a, b in signers]


def pinned_keyring(private):
    # Read the fixed system path as untrusted data, never as executable input.
    # Hash the complete bounded bytes before making our own exclusive private
    # copy; permissions or aliases of the original cannot authorize different
    # keys. The general source-file reader remains unchanged.
    fd = os.open(KEYRING, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        I.require(stat.S_ISREG(info.st_mode) and info.st_size == KEYRING_BYTES, 'UBUNTU_KEYRING_TYPE_OR_SIZE')
        raw = stream.read(KEYRING_BYTES + 1)
    I.require(len(raw) == KEYRING_BYTES and I.sha(raw) == KEYRING_SHA256, 'UBUNTU_KEYRING_BYTES')
    path = private / 'ubuntu-snapshot-keyring.gpg'
    I.write(path, raw)
    return path, dict(bytes=len(raw), sha256=I.sha(raw), source_mode=stat.S_IMODE(info.st_mode),
        source_uid=info.st_uid, source_links=info.st_nlink)


def authenticated_release(raw, suite):
    I.require(raw.startswith(b'-----BEGIN PGP SIGNED MESSAGE-----\n') and raw.count(b'-----BEGIN PGP SIGNATURE-----') == 1, 'UBUNTU_CLEARTEXT')
    body = raw.split(b'\n\n', 1)[1].split(b'-----BEGIN PGP SIGNATURE-----', 1)[0]
    body = b'\n'.join(line[2:] if line.startswith(b'- ') else line for line in body.split(b'\n'))
    value = list(paragraphs(body))
    I.require(len(value) == 1 and value[0].get('Suite') == suite and value[0].get('Codename') == 'noble'
        and 'amd64' in value[0].get('Architectures', '').split(), 'UBUNTU_RELEASE_IDENTITY')
    hashes = {}
    for line in value[0]['SHA256'].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r' ([0-9a-f]{64}) +([0-9]+) (\S+)', line)
        I.require(match is not None, 'UBUNTU_INDEX_HASH')
        digest, size, path = match.groups()
        I.safe_path(path)
        I.require(path not in hashes, 'UBUNTU_INDEX_DUPLICATE')
        hashes[path] = dict(bytes=int(size), sha256=digest)
    return hashes


def validate_uri_line(line):
    parts = shlex.split(line)
    I.require(len(parts) == 4 and parts[0].startswith(BASE + 'pool/') and '?' not in parts[0]
        and '#' not in parts[0], 'APT_URI')
    # APT's observed URI spelling quotes '+' and '~' with lowercase hex.
    # Decode only these two non-separator characters for the signed Filename
    # comparison; retain the original exact URL for acquisition. Never apply
    # general URL decoding to an authenticated package path.
    filename = parts[0][len(BASE):].replace('%2b', '+').replace('%7e', '~')
    I.require('%' not in filename and I.safe_path(filename)
        and re.fullmatch(r'pool/(?:main|restricted|universe|multiverse)/[A-Za-z0-9+_.~/-]+\.deb', filename)
        and re.fullmatch(r'[A-Za-z0-9_+.~:%-]+\.deb', parts[1])
        and parts[2].isdigit() and re.fullmatch(r'SHA256:[0-9a-f]{64}', parts[3]), 'APT_URI')
    return dict(url=parts[0], filename=filename, bytes=int(parts[2]), sha256=parts[3][7:])


def package_member_name(member):
    # Debian data archives may explicitly name their root directory '.'.
    # Skip only that directory header, never a file/link or a normalized path.
    if member.isdir() and member.name in ('.', './'):
        return None
    name = member.name.removeprefix('./')
    if member.isdir():
        name = name.removesuffix('/')
    return package_data_path(name)


def package_data_path(name):
    # These are POSIX names in authenticated Debian archives, recorded only
    # as metadata. Keep Unicode and literal backslashes byte-for-byte (e.g.
    # systemd's unit-name escapes). Never decode escapes, normalize Unicode,
    # extract a path, or apply Windows path rules here.
    I.require(type(name) is str and 0 < len(name) <= 1024
        and not name.startswith('/') and all(p not in ('', '.', '..') for p in name.split('/'))
        and all(not unicodedata.category(c).startswith('C') for c in name), 'INPUT_PATH')
    return name


def candidate(profile, output, *, downloader=I.fetch):
    global DIAGNOSTIC_OUTPUT, APT_CONFIG_FILE
    DIAGNOSTIC_OUTPUT = output
    I.require(profile in ('web', 'flutter'), 'CANDIDATE_APT_PROFILE')  # Android acquisition has its own later gate.
    private = output / 'apt-private'
    private.mkdir(mode=0o700)
    keyring, keyring_observation = pinned_keyring(private)
    # Fail before acquisition if bootstrap tools cannot be safely observed.
    # These hashes describe this runner; they are not compiler/input admission.
    bootstrap_tools = {str(path): I.sha(I.read(path)) for path in map(Path,
        ('/usr/bin/apt-get', '/usr/bin/gpgv', '/usr/bin/dpkg-query', '/usr/bin/dpkg-deb', '/usr/lib/apt/apt-helper'))}
    I.write(output / 'bootstrap-observations.json', I.canonical(dict(schema=1, admitted=False,
        kind='client-input-bootstrap-observations', keyring=keyring_observation, tools=bootstrap_tools)))
    APT_CONFIG_FILE = private / 'apt.conf'
    # Set before apt reads its normal config fragments, not only as late CLI
    # overrides. This excludes host proxy/auth settings and update hooks.
    I.write(APT_CONFIG_FILE, b'Dir::Etc::main "/dev/null";\nDir::Etc::parts "-";\nAcquire::https::Proxy "DIRECT";\n')
    for name in ('lists', 'lists/partial', 'archives', 'archives/partial', 'sourceparts', 'preferencesparts'):
        (private / name).mkdir(mode=0o700)
    I.write(private / 'status', b'')  # resolve full transitive closure, including already installed roots
    I.write(private / 'preferences', b'')
    I.write(private / 'sources.list', ''.join(f'deb [arch=amd64 signed-by={keyring}] {BASE} {suite} main restricted universe multiverse\n' for suite in SUITES).encode())
    options = ['-o', 'Dir::Etc::main=/dev/null', '-o', 'Dir::Etc::parts=-',
        '-o', 'Dir::Etc::sourcelist=' + str(private / 'sources.list'),
        '-o', 'Dir::Etc::sourceparts=' + str(private / 'sourceparts'),
        '-o', 'Dir::Etc::preferences=' + str(private / 'preferences'),
        '-o', 'Dir::Etc::preferencesparts=' + str(private / 'preferencesparts'),
        '-o', 'Dir::State::status=' + str(private / 'status'), '-o', 'Dir::State::lists=' + str(private / 'lists'),
        '-o', 'Dir::Cache::archives=' + str(private / 'archives'), '-o', 'Dir::Cache::pkgcache=',
        '-o', 'Dir::Cache::srcpkgcache=', '-o', 'APT::Architecture=amd64', '-o', 'APT::Architectures::=amd64',
        '-o', 'Acquire::Languages=none', '-o', 'Acquire::Check-Valid-Until=false',
        '-o', 'Acquire::https::AllowRedirect=false', '-o', 'Acquire::ForceHash=SHA256',
        '-o', 'Acquire::Retries=0', '-o', 'APT::Get::List-Cleanup=false', '-o', 'Debug::NoLocking=true']
    # The fixed release bytes are checked independently before apt can parse
    # any repository indexes. Both gpgv and apt use our exact private keyring.
    releases = {}
    for suite, pin in SUITES.items():
        raw = downloader(BASE + 'dists/' + suite + '/InRelease', pin['bytes'], sha256=pin['sha256'])
        I.require(len(raw) == pin['bytes'], 'UBUNTU_RELEASE_SIZE')
        path = private / (suite + '.InRelease')
        I.write(path, raw)
        I.write(output / (suite + '.InRelease'), raw)
        status = run(['/usr/bin/gpgv', '--status-fd', '1', '--keyring', str(keyring), str(path)], maximum=65536)
        I.write(output / (suite + '.signature.log'), status)
        signers = signature_identities(status)
        I.require(signers == [dict(subkey=ARCHIVE_SIGNER, primary=ARCHIVE_SIGNER)], 'UBUNTU_SIGNATURE_IDENTITY')
        releases[suite] = dict(input=pin, signatures=signers,
            indexes=authenticated_release(raw, suite))
    raw = run(['/usr/bin/apt-get', *options, 'update'], seconds=300)
    I.write(output / 'apt-update.log', raw)
    package_records, indexes = {}, []
    prefix = 'snapshot.ubuntu.com_ubuntu_' + SNAPSHOT + '_dists_'
    for suite, release in releases.items():
        # Verify the exact metadata apt used, not merely our separate fetch.
        I.require(I.sha(I.read(private / 'lists' / (prefix + suite + '_InRelease'), 512 * 1024)) == release['input']['sha256'], 'APT_RELEASE_CHANGED')
        for component in ('main', 'restricted', 'universe', 'multiverse'):
            relative = component + '/binary-amd64/Packages'
            pin = release['indexes'][relative]
            base = prefix + suite + '_' + component + '_binary-amd64_Packages'
            matches = [p for p in (private / 'lists').iterdir() if p.name in (base, base + '.lz4', base + '.xz', base + '.gz')]
            I.require(len(matches) == 1, 'APT_INDEX_SET')
            data = run(['/usr/lib/apt/apt-helper', 'cat-file', str(matches[0])], maximum=pin['bytes'])
            I.require(len(data) == pin['bytes'] and I.sha(data) == pin['sha256'], 'APT_INDEX_CHANGED')
            indexes.append(dict(suite=suite, path=relative, **pin))
            for row in paragraphs(data):
                if row.get('Architecture') not in ('all', 'amd64'):
                    continue
                identity = row['Package'], row['Version'], row['Architecture']
                package_records.setdefault(identity, []).append(dict(suite=suite, **{k: row[k] for k in ('Filename', 'Size', 'SHA256')}))
    raw = run(['/usr/bin/apt-get', *options, '--print-uris', '--yes', '--download-only', '--no-install-recommends', '--no-remove', 'install', *PROFILES[profile]])
    I.require(b'Remv ' not in raw, 'APT_REMOVAL')
    I.write(output / 'apt-resolver.log', raw)
    selected = [validate_uri_line(line) for line in raw.decode().splitlines() if line.startswith("'")]
    I.require(0 < len(selected) <= 1024, 'APT_PACKAGE_COUNT')
    bindings = []
    total, started = 0, time.monotonic()
    for item in selected:
        found = [(key, row) for key, rows in package_records.items() for row in rows
            if row['Filename'] == item['filename'] and int(row['Size']) == item['bytes'] and row['SHA256'] == item['sha256']]
        I.require(found and len({key for key, _ in found}) == 1, 'APT_PACKAGE_INDEX_BINDING')
        I.require(all(row['SHA256'] == item['sha256'] and int(row['Size']) == item['bytes']
            for row in package_records[found[0][0]]), 'APT_CONFLICTING_IDENTITY')
        I.require(time.monotonic() - started < 600, 'APT_DOWNLOAD_DEADLINE')
        data = downloader(item['url'], 192 * 1024**2, sha256=item['sha256'])
        I.require(len(data) == item['bytes'], 'APT_PACKAGE_SIZE')
        total += len(data)
        I.require(total <= 768 * 1024**2, 'APT_TOTAL_BOUND')
        # Archive remains private and is never installed. dpkg-deb only emits
        # data; no package executable or maintainer script is launched.
        deb = private / (str(len(bindings)) + '.deb')
        I.write(deb, data)
        tar = run(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(deb)], maximum=512 * 1024**2)
        import io
        import tarfile
        files, count = {}, 0
        with tarfile.open(fileobj=io.BytesIO(tar), mode='r|') as archive:
            for member in archive:
                count += 1
                I.require(count <= 100000, 'APT_MEMBERS_BOUND')
                name = package_member_name(member)
                if name is None:
                    continue
                I.require(name not in files, 'APT_MEMBER_DUPLICATE')
                if member.isdir():
                    files[name] = dict(type='directory')
                elif member.issym() or member.islnk():
                    I.require(len(member.linkname) <= 1024, 'APT_LINK_BOUND')
                    files[name] = dict(type='symlink' if member.issym() else 'hardlink', target=member.linkname)
                else:
                    I.require(member.isreg() and 0 <= member.size <= I.MAX_MEMBER, 'APT_MEMBER_TYPE')
                    content = archive.extractfile(member).read(I.MAX_MEMBER + 1)
                    I.require(len(content) == member.size, 'APT_MEMBER_SIZE')
                    files[name] = dict(type='file', bytes=len(content), sha256=I.sha(content), mode=member.mode & 0o777)
        bindings.append(dict(identity=list(found[0][0]), input=item, indexed_origins=[row['suite'] for _, row in found], files=files))
    baseline = run(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'])
    I.write(output / 'runner-packages.tsv', baseline)
    value = dict(schema=1, kind='volparossa-weather-client-apt-candidate', admitted=False, profile=profile,
        snapshot=SNAPSHOT, roots=list(PROFILES[profile]), repositories=releases, indexes=indexes, packages=bindings,
        baseline=dict(packages_sha256=I.sha(baseline), keyring_sha256=I.sha(I.read(keyring)),
            image_os=os.environ.get('ImageOS'), image_version=os.environ.get('ImageVersion'),
            bootstrap_tools=bootstrap_tools),
        installed=False, compiled=False, full_build_environment_admitted=False,
        limitations=['runner-bootstrap-tools-observed-not-independent-authority', 'installed-file-config-alternatives-binding-required-before-build'])
    I.write(output / 'apt-candidate.json', I.canonical(value))
    return value


# Inventory-only bootstrap exception: these fixed distro tools may provision
# authenticated packages on the guarded disposable runner. Their observations
# do not authorize a compiler, browser, SDK or later build.
PROVISION_TOOLS = ('/usr/bin/sudo', '/usr/bin/env', '/usr/bin/git', '/usr/bin/apt-get', '/usr/bin/dpkg',
    '/usr/bin/dpkg-deb', '/usr/bin/dpkg-query', '/usr/bin/python3', '/usr/bin/timeout', '/usr/bin/kill', '/bin/sh')
CONFIG_PATHS = ('etc/ld.so.cache', 'etc/ld.so.conf', 'etc/ld.so.conf.d', 'etc/fonts', 'etc/alternatives')
MERGED_USR = {'bin': 'usr/bin', 'sbin': 'usr/sbin', 'lib': 'usr/lib', 'lib64': 'usr/lib64'}
PACKAGE_ID = r'[a-z0-9][a-z0-9+.-]{0,127}'
PACKAGE_VERSION = r'[A-Za-z0-9][A-Za-z0-9.+:~_-]{0,255}'
INSTALL_LINE = re.compile(r'(Inst|Conf) (' + PACKAGE_ID + r')(?::(amd64|all))?(?: \[[^\]\r\n]{1,256}\])? '
    r'\((' + PACKAGE_VERSION + r') ([^()\r\n]{1,256}) \[(amd64|all)\]\)(?: \[[A-Za-z0-9+.: _-]{0,2048}\])?')


def bind_package_candidate(value, record):
    expected = record['apt']
    I.require(type(value) is dict and value.get('admitted') is False and value.get('installed') is False
        and value.get('compiled') is False and value.get('full_build_environment_admitted') is False
        and set(expected) == {'profile', 'snapshot', 'roots', 'repositories', 'indexes', 'packages'}
        and expected['profile'] in ('web', 'flutter') and expected['snapshot'] == SNAPSHOT
        and expected['roots'] == list(PROFILES[expected['profile']])
        and all(value.get(key) == item for key, item in expected.items() if key not in ('packages', 'repositories')), 'PACKAGE_CLOSURE_CHANGED')
    repositories = {}
    for suite, repository in value.get('repositories', {}).items():
        item = dict(repository)
        item['indexes_sha256'] = I.sha(I.canonical(item.pop('indexes')))
        repositories[suite] = item
    I.require(repositories == expected['repositories'], 'PACKAGE_CLOSURE_CHANGED')
    observed = []
    for package in value.get('packages', []):
        item = dict(package)
        item['files_sha256'] = I.sha(I.canonical(item.pop('files')))
        observed.append(item)
    I.require(observed == expected['packages'], 'PACKAGE_CLOSURE_CHANGED')
    identities = []
    for item in expected['packages']:
        identity = item['identity']
        I.require(type(identity) is list and len(identity) == 3
            and re.fullmatch(PACKAGE_ID, identity[0]) and re.fullmatch(PACKAGE_VERSION, identity[1])
            and identity[2] in ('all', 'amd64'), 'PACKAGE_IDENTITY')
        identities.append(identity[0])
    I.require(0 < len(identities) <= 1024 and len(set(identities)) == len(identities), 'PACKAGE_IDENTITY_SET')


def validate_install_simulation(raw, packages):
    I.require(type(raw) is bytes and len(raw) <= 16 * 1024**2, 'INSTALL_PLAN_BOUND')
    expected = {p['identity'][0]: p['identity'][1:] for p in packages}
    actions = {'Inst': {}, 'Conf': {}}
    for line in raw.decode('utf-8').splitlines():
        I.require(not line.startswith(('Remv ', 'Purg ', 'Del ', 'Err:', 'E:')), 'INSTALL_PLAN_REMOVAL_OR_FAILURE')
        if line.startswith(('Inst ', 'Conf ')):
            match = INSTALL_LINE.fullmatch(line)
            I.require(match is not None, 'INSTALL_PLAN_SYNTAX')
            action, name, qualifier, version, _description, architecture = match.groups()
            I.require(name in expected and expected[name] == [version, architecture]
                and qualifier in (None, architecture) and name not in actions[action], 'INSTALL_PLAN_UNREVIEWED_PACKAGE')
            actions[action][name] = [version, architecture]
    # --reinstall requires every fixed local package, including those whose
    # version is already present. Neither baseline satisfaction nor a subset
    # may silently bypass reinstalling independently reviewed package bytes.
    I.require(actions['Inst'] == expected and actions['Conf'] == expected, 'INSTALL_PLAN_INCOMPLETE')
    return actions


def provision_options(private):
    # No repositories/lists/auth/hooks/proxies from the runner. The fixed local
    # .debs are the only available inputs. --no-download is also enforced on
    # both simulation and installation; there is no acquisition fallback.
    return ['-o', 'Dir::Etc::main=/dev/null', '-o', 'Dir::Etc::parts=-',
        '-o', 'Dir::Etc::sourcelist=/dev/null', '-o', 'Dir::Etc::sourceparts=-',
        '-o', 'Dir::Etc::preferences=/dev/null', '-o', 'Dir::Etc::preferencesparts=-',
        '-o', 'Dir::Etc::netrc=/dev/null', '-o', 'Dir::Etc::netrcparts=-',
        '-o', 'Dir::State::lists=' + str(private / 'offline-lists'),
        '-o', 'Dir::Cache::archives=' + str(private / 'archives'),
        '-o', 'Dir::Cache::pkgcache=', '-o', 'Dir::Cache::srcpkgcache=',
        '-o', 'Acquire::Retries=0', '-o', 'APT::Get::Download=false',
        '-o', 'DPkg::Lock::Timeout=30']


def open_directory_beneath(root_fd, parts):
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def observe_path(name, *, root=Path('/')):
    """Read through owned directory descriptors, never unknown aliases."""
    parts = package_data_path(name).split('/')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = os.dup(root_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                return dict(type='missing')
            except OSError:
                info = os.stat(part, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISLNK(info.st_mode):
                    return dict(type='invalid-parent-type')
                target = os.readlink(part, dir_fd=directory)
                relative = '/'.join(parts[:index + 1])
                if relative not in MERGED_USR or target not in (MERGED_USR[relative], '/' + MERGED_USR[relative]):
                    return dict(type='unvalidated-parent-alias')
                child = open_directory_beneath(root_fd, MERGED_USR[relative].split('/'))
            os.close(directory)
            directory = child
        try:
            info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return dict(type='missing')
        if stat.S_ISLNK(info.st_mode):
            return dict(type='symlink', target_sha256=I.sha(os.fsencode(os.readlink(parts[-1], dir_fd=directory))))
        if stat.S_ISDIR(info.st_mode):
            return dict(type='directory')
        if not stat.S_ISREG(info.st_mode):
            return dict(type='unsupported-type')
        if info.st_size > I.MAX_MEMBER:
            return dict(type='oversized-file')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            I.require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino),
                'INSTALLED_FILE_CHANGED_DURING_READ')
            digest, total = hashlib.sha256(), 0
            while chunk := stream.read(65536):
                total += len(chunk)
                I.require(total <= I.MAX_MEMBER, 'INSTALLED_FILE_BOUND')
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        I.require(total == info.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
            (info.st_size, info.st_mtime_ns, info.st_ctime_ns), 'INSTALLED_FILE_CHANGED_DURING_READ')
        return dict(type='file', bytes=total, sha256=digest.hexdigest(), mode=stat.S_IMODE(info.st_mode))
    finally:
        os.close(directory)
        os.close(root_fd)


def package_file_inventory(packages, *, root=Path('/')):
    result, cache = {}, {}
    for package in packages:
        files, rows = package['files'], {}
        for name, expected in files.items():
            if name not in cache:
                cache[name] = observe_path(name, root=root)
            actual = cache[name]
            comparison = expected
            if expected['type'] == 'symlink':
                comparison = dict(type='symlink', target_sha256=I.sha(os.fsencode(expected['target'])))
            elif expected['type'] == 'hardlink':
                target = expected['target'].removeprefix('./').removeprefix('/')
                comparison = files.get(target, dict(type='unresolved-archive-hardlink'))
            rows[name] = dict(observed=actual, matches_package=actual == comparison)
        result[package['identity'][0]] = rows
    return result


def configuration_inventory(*, root=Path('/')):
    # Fixed public paths only, never a recursive /etc dump. Directory FDs keep
    # the walk beneath those paths even if an alias is replaced during capture.
    result = {}
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    def walk(directory, base):
        for child in sorted(os.listdir(directory)):
            I.require(len(result) < 16384, 'CONFIGURATION_ENTRY_BOUND')
            relative = base + '/' + child
            result[relative] = observe_path(relative, root=root)
            if result[relative]['type'] == 'directory':
                descriptor = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    walk(descriptor, relative)
                finally:
                    os.close(descriptor)
    try:
        for base in CONFIG_PATHS:
            result[base] = observe_path(base, root=root)
            if result[base]['type'] == 'directory':
                descriptor = open_directory_beneath(root_fd, base.split('/'))
                try:
                    walk(descriptor, base)
                finally:
                    os.close(descriptor)
    finally:
        os.close(root_fd)
    return result


def provisioning_bootstrap():
    tools = {}
    for name in PROVISION_TOOLS:
        path = Path(name)
        resolved = path.resolve(strict=True)
        info = resolved.stat()
        I.require(str(resolved).startswith(('/usr/bin/', '/usr/sbin/')) and stat.S_ISREG(info.st_mode)
            and info.st_uid == 0 and not info.st_mode & 0o022 and info.st_mode & 0o111,
            'UNSAFE_PROVISIONING_TOOL')
        tools[name] = dict(sha256=I.sha(I.read(resolved)), resolved=str(resolved), mode=stat.S_IMODE(info.st_mode))
    return dict(schema=1, admitted=False, kind='client-provisioning-bootstrap-observations', tools=tools,
        basis='trusted-github-hosted-ubuntu-bootstrap-inventory-only', compiler_authority=False)


def verified_local_packages(private, packages):
    paths = []
    for index, package in enumerate(packages):
        path = private / (str(index) + '.deb')
        raw = I.read(path, 192 * 1024**2)
        I.require(len(raw) == package['input']['bytes'] and I.sha(raw) == package['input']['sha256'],
            'LOCAL_PACKAGE_CHANGED')
        paths.append(str(path))
    return paths


def record_installed_environment(profile, output, packages, baseline, before_config, plan, succeeded):
    after = run(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'])
    I.write(output / 'installed-packages-after.tsv', after)
    after_files, after_config = package_file_inventory(packages), configuration_inventory()
    # Save the full observations before rejecting a failed/partial transition.
    I.write(output / 'installed-environment.json', I.canonical(dict(schema=1,
        kind='client-installed-environment-candidate', admitted=False, profile=profile,
        package_inputs_authorized=True, package_input_sha256=I.PACKAGE_INPUTS[profile][1],
        build_environment_admitted=False, consumer_admitted=False, compiled=False,
        installer_succeeded=succeeded, plan=plan, packages=after_files, configuration=after_config,
        configuration_changed=sorted(k for k in before_config.keys() | after_config.keys()
            if before_config.get(k) != after_config.get(k)),
        image=dict(os=os.environ['ImageOS'], version=os.environ['ImageVersion']),
        limitations=['trusted-hosted-bootstrap-not-independent-compiler-authority',
            'existing-package-triggers-and-interpreters-are-platform-bootstrap-not-reviewed-compiler-inputs',
            'installed-differences-and-generated-configuration-require-independent-review',
            'no-client-compiler-browser-sdk-npm-or-pub-execution', 'not-a-hermetic-runner-or-client-admission'])))
    if succeeded:
        validate_package_transition(baseline, after, packages)


def installed_inventory(profile, output, record):
    global APT_CONFIG_FILE
    I.hosted_guard(os.environ, profile)
    # This is deliberately not an API accepting an arbitrary package record.
    I.require(record == I.load_package_inputs(profile), 'PACKAGE_INPUTS_CHANGED')
    bootstrap = provisioning_bootstrap()
    I.require(run(['/usr/bin/git', '-C', str(ROOT), 'rev-parse', 'HEAD']).decode().strip() == os.environ['GITHUB_SHA']
        and not run(['/usr/bin/git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=all']).strip(),
        'PROVISIONING_SOURCE_CHANGED')
    I.write(output / 'provisioning-bootstrap.json', I.canonical(bootstrap))
    candidate(record['apt']['profile'], output)
    value = I.document(I.read(output / 'apt-candidate.json'))
    bind_package_candidate(value, record)
    packages, private = value['packages'], output / 'apt-private'
    # Recheck every complete archive immediately before any privileged action.
    paths = verified_local_packages(private, packages)
    (private / 'offline-lists').mkdir(mode=0o700)
    I.write(private / 'offline-lists/lock', b'')
    # APT_CONFIG is consumed before normal config fragments. Root receives
    # only this fixed file and an explicitly empty environment.
    APT_CONFIG_FILE = private / 'offline-apt.conf'
    I.write(APT_CONFIG_FILE, b'Dir::Etc::main "/dev/null";\nDir::Etc::parts "-";\nAcquire::http::Proxy "DIRECT";\nAcquire::https::Proxy "DIRECT";\n')
    argv = ['/usr/bin/apt-get', *provision_options(private), '--no-download', '--no-remove',
        '--allow-downgrades', '--reinstall', '--no-install-recommends']
    baseline = run(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'])
    I.write(output / 'installed-packages-before.tsv', baseline)
    before_files = package_file_inventory(packages)
    before_config = configuration_inventory()
    I.write(output / 'installed-before.json', I.canonical(dict(schema=1, admitted=False,
        packages=before_files, configuration=before_config)))
    # Run the same root-only resolver in simulation and installation. Passing
    # all authenticated local files prevents satisfying dependencies from a
    # different repository. No command, option or path comes from a caller.
    prefix = ['/usr/bin/sudo', '-n', '--', '/usr/bin/env', '-i', *[k + '=' + v for k, v in ENV.items() if k != 'APT_CONFIG'],
        'APT_CONFIG=' + str(APT_CONFIG_FILE)]
    print(I.canonical(dict(action='reinstall-reviewed-packages-on-disposable-runner',
        packages=[p['identity'] for p in packages], downloads=False, removals=False,
        effects='package-files-maintainer-scripts-and-generated-config-may-change',
        package_services_may_start=True, build_environment_admitted=False)).decode(), flush=True)
    simulation = provision_run([*prefix, '/usr/bin/timeout', '--foreground', '--signal=TERM', '--kill-after=5s', '120s',
        *argv, '--simulate', 'install', *paths], output, 'simulation', 120)
    I.write(output / 'install-simulation.log', simulation)
    plan = validate_install_simulation(simulation, packages)
    # A simulation receipt never authorizes changed archive bytes.
    I.require(paths == verified_local_packages(private, packages), 'LOCAL_PACKAGE_CHANGED')
    succeeded = False
    try:
        installed = provision_run([*prefix, '/usr/bin/timeout', '--foreground', '--signal=TERM', '--kill-after=5s', '600s',
            *argv, '--yes', 'install', *paths], output, 'install', 600)
        succeeded = True
        I.write(output / 'install.log', installed)
    finally:
        receipt = output / 'installer-install-cleanup.json'
        if receipt.exists() and I.document(I.read(receipt)).get('owned_session_drained') is True:
            record_installed_environment(profile, output, packages, baseline, before_config, plan, succeeded)


def installer_group_running(group):
    count = 0
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        count += 1
        I.require(count <= 32768, 'INSTALLER_PROCESS_INSPECTION_BOUND')
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        I.require(len(fields) >= 4, 'INSTALLER_PROCESS_INSPECTION_FAILED')
        if int(fields[3]) == group and fields[0] not in ('Z', 'X'):
            I.require(int(fields[2]) == group, 'INSTALLER_SESSION_GROUP_CHANGED')
        if int(fields[2]) == group and fields[0] not in ('Z', 'X'):
            return True
    return False


def finish_installer_group(child, grace=5):
    # The Popen leader has NOT been reaped: PID/PGID reuse is impossible until
    # after this final group kill. No caller can supply a PID or command.
    for name in ('TERM', 'KILL'):
        killed = subprocess.run(['/usr/bin/sudo', '-n', '--', '/usr/bin/kill', '-' + name, '--', '-' + str(child.pid)],
            env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False)
        I.require(killed.returncode == 0, 'INSTALLER_PRIVILEGED_CLEANUP_FAILED')
        deadline = time.monotonic() + grace
        while installer_group_running(child.pid):
            I.require(time.monotonic() < deadline or name == 'TERM', 'INSTALLER_GROUP_NOT_DRAINED')
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    I.require(not installer_group_running(child.pid), 'INSTALLER_GROUP_NOT_DRAINED')
    child.wait(timeout=5)  # Reap only after no live group members can write.


def provision_run(argv, output, label, seconds):
    I.require(label in ('simulation', 'install') and argv[:3] == ['/usr/bin/sudo', '-n', '--'], 'INSTALLER_ACTION')
    I.write(output / ('installer-' + label + '-started.json'), I.canonical(dict(schema=1,
        admitted=False, kind='client-installer-started', action=label)))
    child, cleanup = None, False
    with tempfile.TemporaryFile(dir=ROOT / 'build') as stdout, tempfile.TemporaryFile(dir=ROOT / 'build') as stderr:
        try:
            pending = []
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
            for sig in handlers:
                signal.signal(sig, lambda signum, _frame: pending.append(signum))
            try:
                child = subprocess.Popen(argv, env=ENV, stdin=subprocess.DEVNULL, stdout=stdout,
                    stderr=stderr, start_new_session=True, umask=0o077)
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
            I.require(not pending, 'CLIENT_INPUT_INTERRUPTED')
            deadline = time.monotonic() + seconds + 10
            while True:
                status = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                I.require(os.fstat(stdout.fileno()).st_size <= 16 * 1024**2
                    and os.fstat(stderr.fileno()).st_size <= 2 * 1024**2, 'INSTALLER_LOG_BOUND')
                if status is not None:
                    break
                I.require(time.monotonic() < deadline, 'INSTALLER_DEADLINE')
                time.sleep(0.05)
            I.require(status.si_code == os.CLD_EXITED and status.si_status == 0, 'INSTALLER_FAILED')
            stdout.seek(0)
            return stdout.read(16 * 1024**2 + 1)
        finally:
            try:
                if child is not None:
                    finish_installer_group(child)
                cleanup = True
            finally:
                stdout.seek(0)
                I.write(output / ('installer-' + label + '-stdout.log'), stdout.read(16 * 1024**2))
                stderr.seek(0)
                error_log = stderr.read(2 * 1024**2)
                if error_log:
                    I.write(output / ('installer-' + label + '-stderr.log'), error_log)
                I.write(output / ('installer-' + label + '-cleanup.json'), I.canonical(dict(schema=1,
                    admitted=False, kind='client-installer-group-cleanup', action=label,
                    owned_session_drained=cleanup, leader_reaped=cleanup,
                    package_services_cleaned=False, scope='owned-installer-process-group-only')))


def validate_package_transition(before, after, packages):
    def parse(raw):
        rows = {}
        for line in raw.decode('utf-8').splitlines():
            parts = line.split('\t')
            I.require(len(parts) == 4 and parts[0] not in rows, 'INSTALLED_PACKAGE_TABLE')
            rows[parts[0]] = parts[1:]
        return rows
    previous, current = parse(before), parse(after)
    expected = {p['identity'][0]: p['identity'][1:] for p in packages}
    for name, row in previous.items():
        if name.split(':')[0] not in expected:
            I.require(current.get(name) == row, 'UNREVIEWED_INSTALLED_PACKAGE_CHANGE')
    for name, row in current.items():
        base = name.split(':')[0]
        if base in expected:
            I.require(row == [*expected[base], 'installed'], 'INSTALLED_PACKAGE_IDENTITY_CHANGED')
        else:
            I.require(previous.get(name) == row, 'UNREVIEWED_INSTALLED_PACKAGE_CHANGE')
    I.require(set(expected) <= {name.split(':')[0] for name in current}, 'INSTALLED_PACKAGE_MISSING')
