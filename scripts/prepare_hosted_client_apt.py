#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Acquire a fixed Ubuntu snapshot package candidate without installing packages.

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
import tempfile
import subprocess
import time

spec = importlib.util.spec_from_file_location('_client_inputs', Path(__file__).with_name('prepare_hosted_client_inputs.py'))
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)
ROOT = I.ROOT
SNAPSHOT = '20261023T000000Z'
BASE = f'https://snapshot.ubuntu.com/ubuntu/{SNAPSHOT}/'
KEYRING = Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg')
SUITES = {
    'noble': dict(bytes=255850, sha256='cdb2f31d809f589719a53c6ad15f255b27569c4059542ada282aaa21b8e164b0'),
    'noble-updates': dict(bytes=126125, sha256='600c42e6d50b8bd7200f6a5c9e0d2eaee24728bddeb6c1529da9fc38c753a088'),
    'noble-security': dict(bytes=126127, sha256='f90eb747b2e1edab8e85d0f897423a3d0a404e1480c4848a6e4b00bd4f99ad4e'),
}
COMMON = ('apparmor', 'bubblewrap', 'git', 'python3', 'mawk', 'util-linux', 'iproute2', 'ca-certificates',
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


def candidate(profile, output, *, downloader=I.fetch):
    global DIAGNOSTIC_OUTPUT, APT_CONFIG_FILE
    DIAGNOSTIC_OUTPUT = output
    I.require(profile in ('web', 'flutter'), 'CANDIDATE_APT_PROFILE')  # Android acquisition has its own later gate.
    private = output / 'apt-private'
    private.mkdir(mode=0o700)
    APT_CONFIG_FILE = private / 'apt.conf'
    # Set before apt reads its normal config fragments, not only as late CLI
    # overrides. This excludes host proxy/auth settings and update hooks.
    I.write(APT_CONFIG_FILE, b'Dir::Etc::main "/dev/null";\nDir::Etc::parts "-";\nAcquire::https::Proxy "DIRECT";\n')
    for name in ('lists', 'lists/partial', 'archives', 'archives/partial', 'sourceparts', 'preferencesparts'):
        (private / name).mkdir(mode=0o700)
    I.write(private / 'status', b'')  # resolve full transitive closure, including already installed roots
    I.write(private / 'preferences', b'')
    I.write(private / 'sources.list', ''.join(f'deb [arch=amd64 signed-by={KEYRING}] {BASE} {suite} main restricted universe multiverse\n' for suite in SUITES).encode())
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
    # any repository indexes. gpgv uses the existing Ubuntu image trust store.
    releases = {}
    for suite, pin in SUITES.items():
        raw = downloader(BASE + 'dists/' + suite + '/InRelease', pin['bytes'], sha256=pin['sha256'])
        I.require(len(raw) == pin['bytes'], 'UBUNTU_RELEASE_SIZE')
        path = private / (suite + '.InRelease')
        I.write(path, raw)
        I.write(output / (suite + '.InRelease'), raw)
        status = run(['/usr/bin/gpgv', '--status-fd', '1', '--keyring', str(KEYRING), str(path)], maximum=65536)
        I.write(output / (suite + '.signature.log'), status)
        signers = signature_identities(status)
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
                name = member.name.removeprefix('./').rstrip('/')
                if not name and member.isdir():
                    continue
                I.safe_path(name)
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
        baseline=dict(packages_sha256=I.sha(baseline), keyring_sha256=I.sha(I.read(KEYRING)),
            image_os=os.environ.get('ImageOS'), image_version=os.environ.get('ImageVersion'),
            bootstrap_tools={str(path): I.sha(I.read(path)) for path in map(Path,
                ('/usr/bin/apt-get', '/usr/bin/gpgv', '/usr/bin/dpkg-query', '/usr/bin/dpkg-deb', '/usr/lib/apt/apt-helper'))}),
        installed=False, compiled=False, full_build_environment_admitted=False,
        limitations=['runner-bootstrap-tools-observed-not-independent-authority', 'installed-file-config-alternatives-binding-required-before-build'])
    I.write(output / 'apt-candidate.json', I.canonical(value))
    return value
