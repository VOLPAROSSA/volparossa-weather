#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P14-only dependency materialization; fixed original inputs, no admission.

Acquisition treats tarballs as data. npm operates offline through the existing
live Boundary, with scripts disabled. Every installed byte and CLI link must
originate in an authenticated archive. Inactive optional musl data is recorded
then removed, together with cache/archive payloads, before application execution.
"""
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import time

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('_p14_' + name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


I = module('prepare_hosted_client_inputs')
require = I.require


def file_digest(path, bound=512 * 1024**2):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.getuid() and not before.st_mode & 0o022
            and before.st_size <= bound, 'P14_INSTALLED_FILE_TYPE')
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    current = path.lstat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(all(getattr(before, k) == getattr(after, k) == getattr(current, k) for k in fields),
        'P14_INSTALLED_FILE_CHANGED')
    return dict(bytes=before.st_size, sha256=checksum)


def acquire(output, *, downloader=None):
    """Return private archive/member records bound to existing approved pins."""
    downloader = downloader or I.fetch
    require(output.resolve() == output and output.is_dir(), 'P14_DEPENDENCY_ROOT')
    approved = I.load_package_inputs('drizzli')['dependencies']
    raw = I.read(ROOT / 'third_party/client-locks/drizzli-package-lock.json')
    require(I.sha(raw) == I.SOURCES['drizzli']['sha256'], 'P14_SOURCE_LOCK')
    locked = I.npm_lock(raw)
    require(set(locked) == set(approved['packages']), 'P14_DEPENDENCY_SET')
    packages, plugins, archives = {}, {}, []
    started, total = time.monotonic(), 0
    records = [('package', name, entry) for name, entry in sorted(approved['packages'].items())]
    records += [('plugin', name, entry) for name, entry in sorted(approved['plugins'].items())]
    for kind, name, entry in records:
        require(time.monotonic() - started <= 900, 'P14_DEPENDENCY_DEADLINE')
        if kind == 'package':
            require(entry['input'] == locked[name], 'P14_DEPENDENCY_LOCK_BINDING')
        if entry.get('status') == 'excluded-for-target':
            require(not I.npm_target_selection(entry['input'])['included'], 'P14_TARGET_SELECTION')
            continue
        pin = entry['input']
        data = downloader(pin['url'], I.MAX_ARCHIVE, integrity=pin['integrity'])
        total += len(data)
        require(total <= 512 * 1024**2, 'P14_ARCHIVE_TOTAL')
        inventory = I.archive_inventory(data, npm=True, npm_name=pin['name'])
        summary = {k: v for k, v in inventory.items() if k != 'files'}
        summary['files_sha256'] = I.sha(I.canonical(inventory['files']))
        require(summary == entry['archive'], 'P14_ARCHIVE_MEMBER_BINDING')
        require(inventory['files']['package.json']['package_json'].get('name') == pin['name']
            and inventory['files']['package.json']['package_json'].get('version') == pin['version'],
            'P14_ARCHIVE_IDENTITY')
        target = output / ('archive-' + str(len(archives)).zfill(4) + '.tgz')
        require(len(data) == entry['archive']['bytes'] <= I.MAX_ARCHIVE, 'P14_ARCHIVE_WRITE_BOUND')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        archives.append(target)
        (packages if kind == 'package' else plugins)[name] = dict(input=pin, archive=inventory,
            path=target, inactive=entry.get('status') == 'inactive-optional-data')
    return dict(packages=packages, plugins=plugins, archives=archives, lock_sha256=I.sha(raw),
        acquired_bytes=total, approved=approved)


def bin_links(packages):
    """Enumerate npm POSIX CLI links solely from authenticated manifests."""
    links = {}
    for name, package in packages.items():
        manifest = package['archive']['files']['package.json']['package_json']
        bins = manifest.get('bin', {})
        if isinstance(bins, str):
            bins = {manifest['name'].split('/')[-1]: bins}
        require(type(bins) is dict and len(bins) <= 128, 'P14_MANIFEST_BIN')
        container = name.rsplit('node_modules/', 1)[0] + 'node_modules/.bin/'
        for command, target in bins.items():
            require(type(command) is str and command not in ('', '.', '..')
                and '/' not in command and '\\' not in command and len(command) <= 128,
                'P14_BIN_NAME')
            require(type(target) is str, 'P14_BIN_TARGET')
            target = target.removeprefix('./')
            I.safe_path(target)
            require(package['archive']['files'].get(target, {}).get('type') == 'file', 'P14_BIN_INPUT')
            link, absolute = container + command, name + '/' + target
            # Multiple packages may claim the same bin name. Only an exact
            # manifest-authorized target is permitted; installed_cli separately
            # binds the four actually invoked build entrypoints.
            links.setdefault(link, set()).add(absolute)
    return links


def installed_tree(stage, record, *, after_removal=False):
    """No unbound files, nested symlinks, omitted active packages or extra dirs."""
    require(stage.resolve() == stage, 'P14_STAGE_ALIAS')
    root = stage / 'node_modules'
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
        and not info.st_mode & 0o022, 'P14_NODE_MODULES_ROOT')
    packages = record['packages']
    actual_packages = {}
    for name, entry in packages.items():
        path = stage / name
        if entry['inactive'] and (after_removal or not path.exists()):
            require(not path.exists() and not path.is_symlink(), 'P14_INACTIVE_PACKAGE_PRESENT')
            continue
        if entry['input'].get('optional') is True and not path.exists():
            require(not path.is_symlink(), 'P14_OPTIONAL_PACKAGE_ALIAS')
            continue
        require(path.is_dir() and not path.is_symlink(), 'P14_ACTIVE_PACKAGE_MISSING')
        actual_packages[name] = entry
    # Vite 8.3.1's pinned bundle config loader creates this directory, writes a
    # derived config module and removes that module in its finally block. Kit's
    # pinned secondary build uses that loader even with an outer native loader.
    # Only an empty directory is permitted at every drained stable checkpoint;
    # no generated config bytes become an additional installed dependency.
    expected, directories = {}, {'node_modules', 'node_modules/.vite-temp'}
    for name, entry in actual_packages.items():
        directories.add(name)
        for relative, item in entry['archive']['files'].items():
            full = name + '/' + relative
            if item['type'] == 'directory':
                directories.add(full)
            else:
                require(full not in expected, 'P14_INSTALLED_COLLISION')
                expected[full] = item
    links = bin_links(actual_packages)
    all_names = set(expected) | directories | set(links) | {'node_modules/.package-lock.json'}
    for name in tuple(all_names):
        directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != '.')
    files, seen_links, scanned, total = {}, {}, 0, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for leaf in dirs + names:
            scanned += 1
            require(scanned <= 200000, 'P14_INSTALLED_COUNT')
            path = Path(directory) / leaf
            name = str(path.relative_to(stage))
            info = path.lstat()
            require(info.st_uid == os.getuid(), 'P14_INSTALLED_OWNER')
            if stat.S_ISDIR(info.st_mode):
                require(name in directories and not info.st_mode & 0o022, 'P14_UNBOUND_DIRECTORY')
                if name == 'node_modules/.vite-temp':
                    require(not any(path.iterdir()), 'P14_VITE_TEMP_NOT_EMPTY')
            elif stat.S_ISLNK(info.st_mode):
                require(name in links and leaf not in dirs, 'P14_UNBOUND_LINK')
                target = os.readlink(path)
                require(not os.path.isabs(target) and path.resolve().is_relative_to(root), 'P14_BIN_ESCAPE')
                resolved = str(path.resolve().relative_to(stage))
                require(resolved in links[name] and resolved in expected, 'P14_BIN_BINDING')
                seen_links[name] = resolved
            else:
                require(name in expected or name == 'node_modules/.package-lock.json', 'P14_UNBOUND_FILE')
                actual = file_digest(path)
                total += actual['bytes']
                require(total <= 2 * 1024**3, 'P14_INSTALLED_TOTAL')
                if name in expected:
                    require(actual == {k: expected[name][k] for k in ('bytes', 'sha256')}, 'P14_INSTALLED_BYTES')
                    files[name] = actual
    require(set(files) == set(expected), 'P14_INSTALLED_FILES_MISSING')
    require(set(seen_links) == set(links), 'P14_BIN_LINKS_MISSING')
    hidden = I.document(I.read(root / '.package-lock.json'))
    require(hidden.get('lockfileVersion') == 3 and type(hidden.get('packages')) is dict,
        'P14_HIDDEN_LOCK_SCHEMA')
    # npm may retain entries for successfully installed inactive data after our
    # deliberate removal. This metadata never authorizes loading that data.
    allowed = set(packages)
    require(set(actual_packages) <= set(hidden['packages']) <= allowed, 'P14_HIDDEN_LOCK_SET')
    for name, value in hidden['packages'].items():
        pin = packages[name]['input']
        require(type(value) is dict and value.get('version') == pin['version']
            and value.get('integrity') == pin['integrity'] and value.get('resolved') == pin['url'],
            'P14_HIDDEN_LOCK_BINDING')
    I.reject_excluded_npm_modules(list(files) + list(seen_links),
        {n: e['input'] for n, e in record['approved']['packages'].items()})
    if after_removal:
        I.reject_inactive_npm_contributions(list(files) + list(seen_links),
            {n: e['input'] for n, e in record['approved']['packages'].items()})
    return dict(files=files, links=seen_links, packages=sorted(actual_packages),
        hidden_lock=file_digest(root / '.package-lock.json'), total_bytes=total)


def check_execution_tree(h, record):
    require(h.BOUNDARY is not None, 'RUNTIME_BOUNDARY_REQUIRED')
    require(file_digest(h.STAGE / 'package-lock.json')['sha256'] == record['lock_sha256'], 'P14_LOCK_CHANGED')
    h.project_npm_config()
    check_plugins(h.STAGE, record)
    actual = installed_tree(h.STAGE, record, after_removal=True)
    require(actual == record['sealed'], 'P14_INSTALLED_TREE_CHANGED')
    require(not (h.PRIVATE / 'npm-cache').exists()
        and not any(h.PRIVATE.glob('archive-*.tgz')), 'P14_EXECUTION_CACHE_PRESENT')
    h.BOUNDARY.check()
    return actual


def check_plugins(stage, record):
    directory = stage / 'volparossa-build-plugins'
    expected = {}
    for name, entry in record['plugins'].items():
        for source, suffix in (('dist/index.js', '.mjs'), ('LICENSE', '.LICENSE')):
            item = entry['archive']['files'][source]
            expected[name + suffix] = {k: item[k] for k in ('bytes', 'sha256')}
    require(directory.is_dir() and not directory.is_symlink()
        and {p.name for p in directory.iterdir()} == set(expected), 'P14_PLUGIN_FILES')
    for name, value in expected.items():
        require(file_digest(directory / name) == value, 'P14_PLUGIN_BYTES')
    settings = I.document(I.read(stage / 'project.inlang/settings.json'))
    pins = I.document(I.read(ROOT / 'integrations/drizzli/build-plugins.json'))['plugins']
    require(settings.get('modules') == ['./volparossa-build-plugins/' + p['local_name'] + '.mjs' for p in pins],
        'P14_PLUGIN_CONFIG')


def install(h, record):
    require(h.BOUNDARY is not None, 'RUNTIME_BOUNDARY_REQUIRED')
    require(file_digest(h.STAGE / 'package-lock.json')['sha256'] == record['lock_sha256'], 'P14_LOCK_CHANGED')
    h.project_npm_config()
    for archive in record['archives']:
        require(archive.parent == h.PRIVATE, 'P14_ARCHIVE_SCOPE')
    for entry in list(record['packages'].values()) + list(record['plugins'].values()):
        require(file_digest(entry['path']) == {k: entry['archive'][k] for k in ('bytes', 'sha256')},
            'P14_ARCHIVE_CHANGED')
    # Plugins are materialized by the existing SHA512 verifier separately; only
    # lock entries belong in npm's installation cache.
    argv = [str(h.NODE), str(h.NPM), 'cache', 'add', '--offline', '--ignore-scripts', '--no-audit', '--no-fund']
    argv += ['/state/' + record['packages'][name]['path'].name for name in sorted(record['packages'])]
    h.run('p14-npm-cache', h.sandbox(argv, mode='compile', writable=h.STAGE),
        300, env=h.environment(), memory=1536 * 1024**2)
    h.run('p14-npm-ci', h.sandbox([*h.npm_command(), '--offline'], mode='compile', writable=h.STAGE),
        300, env=h.environment(), memory=1536 * 1024**2)
    installed = installed_tree(h.STAGE, record)
    inactive_installed = [n for n in installed['packages'] if record['packages'][n]['inactive']]
    for name in inactive_installed:
        shutil.rmtree(h.STAGE / name)
    # Remove all alternate source payloads before application code runs. npm
    # installation is the final cache consumer; no post-install downloads.
    cache = h.PRIVATE / 'npm-cache'
    require(cache.is_dir() and not cache.is_symlink(), 'P14_CACHE_ROOT')
    shutil.rmtree(cache)
    for archive in record['archives']:
        archive.unlink()
    record['sealed'] = installed_tree(h.STAGE, record, after_removal=True)
    check_execution_tree(h, record)
    return dict(schema=1, kind='p14-offline-installed-dependencies', admitted=False,
        package_input_sha256=I.PACKAGE_INPUTS['drizzli'][1], lock_sha256=record['lock_sha256'],
        package_count=len(record['sealed']['packages']), file_count=len(record['sealed']['files']),
        installed_map_sha256=I.sha(I.canonical(record['sealed'])),
        installed_inactive_as_data=inactive_installed,
        absent_optional_packages=sorted(set(record['packages']) - set(installed['packages'])),
        inactive_removed_before_execution=True, original_lock_unchanged=True,
        archive_payloads_and_cache_removed=True, networkless=True, lifecycle_scripts=False,
        consumer_admitted=False, output_admitted=False)
