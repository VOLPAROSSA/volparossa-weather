#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""One fixed Drizz.li candidate in the existing P13 Boundary, never admission.

Only the explicit hosted manual mode can execute. Projection exports bounded
metadata, original notices and logs; all application assets remain runner-local.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
OUTPUT = BUILD / 'hosted-drizzli-input-candidate'
PUBLIC = BUILD / 'hosted-drizzli-input-candidate-public'
STAGE = BUILD / 'drizzli-p14-stage'
PROOF = BUILD / 'drizzli-p14-proof'
MODE = 'drizzli-candidate-build'
P13_SOURCE = 'e774912e292f339d42ff23f00b4d8fc5d69e5b47'
MAX_PUBLIC = 96 * 1024**2
RESULT_NAMES = frozenset(('p14-started.json', 'p14-result.json', 'p14-steps.json',
    'p14-output.json', 'p14-module-graphs.json', 'p14-dependencies.json',
    'p14-source-stage.json', 'p14-runtime.json', 'p14-source-inputs.json'))
# Paraglide 2.25.0 -> @inlang/sdk 3.0.3 saveProjectToDirectory(skipExporting).
# These fixed metadata literals are not code or a new source/dependency pin.
# No prior .meta.json may contribute another highestSdkVersion.
PROJECT_METADATA = {
    'project.inlang/.gitignore': (368, 'ee2c9073cd36a97eb77d35fa3321b6c08e3c032e5f42ac08f9cb105eaf57d5ef'),
    'project.inlang/README.md': (6439, 'aa3380d39ef750deede804f7d0ae96e4db3950f90f33dd26a1c70beeaf7d90f4'),
    'project.inlang/.meta.json': (34, '7673ec216ada828b609aac29c19e16e89047497a466ad9a4de08b04532c67191'),
}


class UnreviewedGeneratedPath(ValueError):
    def __init__(self, relative):
        super().__init__('P14_UNREVIEWED_GENERATED_PATH')
        self.relative_path = relative if re.fullmatch(r'[A-Za-z0-9_./@+\-]{1,256}', relative) else 'unrepresentable-path'


class SourceSeal(dict):
    # Directory identities stay private; JSON exports the original file map.
    pass


def require(ok, code):
    if not ok:
        raise ValueError(code)


def module(name):
    spec = importlib.util.spec_from_file_location('_p14_' + name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def receipt(kind, **value):
    return dict(schema=1, kind=kind, admitted=False, consumer_admitted=False,
        product_admitted=False, production_authority=False, **value)


def guard(inputs, h):
    inputs.hosted_guard(os.environ, 'drizzli')
    event = inputs.document(inputs.read(Path(os.environ['GITHUB_EVENT_PATH']), 256 * 1024))
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        and type(event) is dict and type(event.get('inputs')) is dict
        and event['inputs'].get('input_mode') == MODE, 'P14_EXPLICIT_MANUAL_MODE_REQUIRED')
    helper, platform = h.guards(os.environ)
    helper.process(['/usr/bin/git', '-C', str(ROOT), 'merge-base', '--is-ancestor',
        P13_SOURCE, os.environ['GITHUB_SHA']], 10)
    return h, helper, platform


def safe_directory(path, *, create=False):
    require(path.is_relative_to(BUILD) and path.parent.resolve() == path.parent, 'P14_DIRECTORY_SCOPE')
    if create:
        path.mkdir(mode=0o700)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and path.resolve() == path
        and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
        'P14_PRIVATE_DIRECTORY_REQUIRED')


def source_input_seal(inputs, stage):
    require(all(not (stage / name).exists() and not (stage / name).is_symlink()
        for name in PROJECT_METADATA), 'P14_PROJECT_METADATA_ALREADY_PRESENT')
    files, total = SourceSeal(), 0
    files.stage_identity = directory_identity(stage)
    project = stage / 'project.inlang'
    files.project_identity = directory_identity(project) if project.exists() else None
    for directory, dirs, names in os.walk(stage, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'P14_SOURCE_LINK_OR_SPECIAL')
            require(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'P14_SOURCE_OWNER_OR_MODE')
        for name in names:
            path = Path(directory) / name
            raw = inputs.read(path, 128 * 1024**2)
            total += len(raw)
            require(len(files) < 50000 and total <= 512 * 1024**2, 'P14_SOURCE_SEAL_BOUND')
            files[str(path.relative_to(stage))] = dict(bytes=len(raw), sha256=sha(raw))
    require(files, 'P14_SOURCE_SEAL_EMPTY')
    return files


def directory_identity(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
        and not info.st_mode & 0o022, 'P14_PROJECT_METADATA_PARENT')
    return (info.st_dev, info.st_ino)


def project_metadata_file(stage, relative, *, stage_identity=None, project_identity=None):
    """Validate one fixed derived file through nofollow parent descriptors."""
    require(relative in PROJECT_METADATA and stage.resolve() == stage, 'P14_PROJECT_METADATA_SCOPE')
    size, expected = PROJECT_METADATA[relative]
    anchor = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent = None
    try:
        root_before = os.fstat(anchor)
        parent = os.open('project.inlang', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=anchor)
        parent_before = os.fstat(parent)
        require((stage_identity is None or (root_before.st_dev, root_before.st_ino) == stage_identity)
            and (project_identity is None or (parent_before.st_dev, parent_before.st_ino) == project_identity),
            'P14_PROJECT_METADATA_REPLACED')
        for item in (root_before, parent_before):
            require(stat.S_ISDIR(item.st_mode) and item.st_uid == os.getuid()
                and not item.st_mode & 0o022, 'P14_PROJECT_METADATA_PARENT')
        leaf = relative.split('/')[1]
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) in (0o600, 0o644)
                and before.st_size == size, 'P14_PROJECT_METADATA_FILE')
            raw = os.read(fd, size + 1)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        def same(first, second):
            return all(getattr(first, key) == getattr(second, key) for key in fields)
        require(same(before, after) and same(after, os.stat(leaf, dir_fd=parent, follow_symlinks=False))
            and same(parent_before, os.fstat(parent))
            and same(parent_before, os.stat('project.inlang', dir_fd=anchor, follow_symlinks=False))
            and same(root_before, os.fstat(anchor)) and same(root_before, stage.lstat()),
            'P14_PROJECT_METADATA_REPLACED')
        require(len(raw) == size and sha(raw) == expected, 'P14_PROJECT_METADATA_BYTES')
    finally:
        if parent is not None:
            os.close(parent)
        os.close(anchor)


def check_source_inputs(inputs, stage, original, *, generated_metadata=False):
    require(directory_identity(stage) == original.stage_identity, 'P14_PROJECT_METADATA_REPLACED')
    if original.project_identity is not None:
        require(directory_identity(stage / 'project.inlang') == original.project_identity,
            'P14_PROJECT_METADATA_REPLACED')
    require(not generated_metadata or original.project_identity is not None, 'P14_PROJECT_METADATA_PARENT')
    for name, expected in original.items():
        raw = inputs.read(stage / name, 128 * 1024**2)
        require(dict(bytes=len(raw), sha256=sha(raw)) == expected, 'P14_ORIGINAL_SOURCE_CHANGED')
    allowed = ('node_modules/', '.svelte-kit/', '.volparossa-source-graphs/', 'build/', 'src/lib/paraglide/')
    count, found = 0, set()
    for directory, dirs, names in os.walk(stage, followlinks=False):
        for name in dirs + names:
            count += 1
            require(count <= 250000, 'P14_SOURCE_TREE_BOUND')
            path = Path(directory) / name
            relative = str(path.relative_to(stage))
            info = path.lstat()
            # node_modules has a separate exact file/link seal.
            if relative == 'node_modules':
                require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), 'P14_NODE_MODULES_TYPE')
                dirs.remove(name)
                continue
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'P14_SOURCE_LINK_OR_SPECIAL')
            if stat.S_ISREG(info.st_mode):
                if generated_metadata and relative in PROJECT_METADATA:
                    project_metadata_file(stage, relative, stage_identity=original.stage_identity,
                        project_identity=original.project_identity)
                    found.add(relative)
                elif relative not in original and not relative.startswith(allowed):
                    raise UnreviewedGeneratedPath(relative)
    require(not generated_metadata or found == set(PROJECT_METADATA), 'P14_PROJECT_METADATA_MISSING')
    require(directory_identity(stage) == original.stage_identity, 'P14_PROJECT_METADATA_REPLACED')
    if original.project_identity is not None:
        require(directory_identity(stage / 'project.inlang') == original.project_identity,
            'P14_PROJECT_METADATA_REPLACED')


def prepare_optional_cache(stage):
    # Exact pinned Paraglide 2.25.0 catches failed optional cache writes. Its
    # cache is not a source input; keep this directory empty and read-only.
    path = stage / 'project.inlang/cache'
    require(not path.exists() and not path.is_symlink(), 'P14_UPSTREAM_CACHE_PRESENT')
    path.mkdir(mode=0o500)
    info = path.lstat()
    return (info.st_dev, info.st_ino)


def check_optional_cache(stage, anchor):
    path = stage / 'project.inlang/cache'
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink()
        and (info.st_dev, info.st_ino) == anchor and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o500 and not any(path.iterdir()), 'P14_OPTIONAL_CACHE_CHANGED')


def source_notices(inputs, h, archives):
    """Preserve original texts; graph/output checks separately establish coverage."""
    notices, bundle = inputs.notice_inputs()
    target = h.STAGE / 'build' / 'VOLPAROSSA-NOTICES'
    target.mkdir(mode=0o700)
    sources = {'LICENSE.DRIZZLI': h.STAGE / 'LICENSE',
        'LICENSE.VOLPAROSSA': h.STAGE / 'LICENSE.VOLPAROSSA',
        'npm-originals.txt': ROOT / notices['npm']['bundle']}
    for plugin in inputs.document(inputs.read(ROOT / 'integrations/drizzli/build-plugins.json'))['plugins']:
        sources[plugin['local_name'] + '.LICENSE'] = h.STAGE / 'volparossa-build-plugins' / (plugin['local_name'] + '.LICENSE')
    hashes = {}
    for name, source in sources.items():
        raw = inputs.read(source, 16 * 1024**2)
        raw.decode('utf-8')
        inputs.write(target / name, raw)
        hashes[name] = dict(bytes=len(raw), sha256=sha(raw))
    require(sha(bundle) == hashes['npm-originals.txt']['sha256'], 'P14_NOTICE_BUNDLE_CHANGED')
    for path, item in module('prepare_hosted_drizzli_provenance').notices(inputs, archives).items():
        inputs.write(h.STAGE / 'build' / path, item['raw'])
        hashes[Path(path).name] = dict(bytes=item['bytes'], sha256=item['sha256'])
    return hashes


def graph_report(inputs, stage, package_records, *, archives=None, output_map=None,
        source_seal=None, notice_records=None):
    directory = stage / '.volparossa-source-graphs'
    require(directory.resolve() == directory and directory.is_dir(), 'P14_GRAPHS_MISSING')
    paths = sorted(directory.iterdir())
    require(0 < len(paths) <= 16, 'P14_GRAPH_COUNT')
    graphs = []
    hashes = {}
    for path in paths:
        require(re.fullmatch(r'[0-9a-f]{64}\.json', path.name) is not None, 'P14_GRAPH_NAME')
        raw = inputs.read(path, 8 * 1024**2)
        require(sha(raw.rstrip(b'\n')) == path.stem, 'P14_GRAPH_IDENTITY')
        graphs.append(inputs.document(raw))
        hashes[path.name] = dict(bytes=len(raw), sha256=sha(raw))
    try:
        if archives is None:
            # Legacy observations never gain virtual-module authority. This
            # path remains useful for retained schema1 diagnostic validation.
            needed = inputs.graph_notice_closure(graphs, package_records)
            coverage = None
        else:
            provenance = module('prepare_hosted_drizzli_provenance')
            closure = provenance.graph_closure(inputs, graphs, archives)
            needed = closure['notices']
            coverage = provenance.output_closure(inputs, stage, output_map, source_seal,
                notice_records, graphs, closure)
    except ValueError as error:
        code = str(error)
        require(re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code) is not None, 'P14_GRAPH_FAILURE_CODE')
        return receipt('p14-output-module-graph', graphs=hashes, closure_complete=False,
            failure=code, virtual_module_authority=False), graphs
    return receipt('p14-output-module-graph', graphs=hashes, closure_complete=True,
        notices=sorted(needed), output_notice_coverage=coverage,
        virtual_module_authority=False), graphs


def build():
    os.umask(0o077)
    inputs = module('prepare_hosted_client_inputs')
    # guards() expects a preexisting empty runtime directory, before any code runs.
    safe_directory(BUILD)
    safe_directory(OUTPUT, create=True)
    private = OUTPUT / 'runtime-private'
    safe_directory(private, create=True)
    runtime = private / 'runtime'
    safe_directory(runtime, create=True)
    h = module('prepare_hosted_clients_ci')
    # Materialized runtime is prepared only after fixed source/runner validation.
    h.RUNTIME = runtime
    h, helper, platform = guard(inputs, h)
    apt = module('prepare_hosted_client_apt')
    boundary_api = module('prepare_hosted_client_runtime')
    dependencies = module('prepare_hosted_drizzli_dependencies')
    h.RUNTIME, h.NODE, h.NPM = runtime, runtime / 'node/bin/node', runtime / 'node/lib/node_modules/npm/bin/npm-cli.js'
    h.OUTPUT = private / 'harness'
    h.PRIVATE, h.STAGE, h.PROOF = private / 'drizzli/state', STAGE, PROOF
    safe_directory(h.OUTPUT, create=True)
    started = time.monotonic()
    attempted = installed = produced = False
    project_metadata_verified = False
    phase, failure = 'package-provisioning', None
    boundary = None
    policy_removed = False
    resolver = boundary_api.AcquisitionResolver(private / 'resolv.conf')
    prior_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_sig, _frame):
        raise h.Interrupted('P14_INTERRUPTED')
    for sig in prior_handlers:
        signal.signal(sig, interrupted)
    inputs.write(OUTPUT / 'p14-started.json', encoded(receipt('p14-drizzli-start',
        source=os.environ['GITHUB_SHA'], p13_source=P13_SOURCE, maximum_candidate_rounds=1)))
    try:
        pins = inputs.load_package_inputs('drizzli')
        apt.installed_inventory('drizzli', OUTPUT, pins)
        candidate = inputs.document(inputs.read(OUTPUT / 'apt-candidate.json'))
        apt.bind_package_candidate(candidate, pins)
        phase = 'runtime-materialization'
        resolver.capture()
        runtime_preparer = module('prepare_hosted_runtime')
        pin, pin_sha = runtime_preparer.load_pin()
        runtime_preparer.prepare(runtime, pin, pin_sha, fetch=True, with_npm=True)
        runtime_binding = h.runtime_inventory()
        inputs.write(OUTPUT / 'p14-runtime.json', encoded(receipt('p14-runtime-binding', runtime=runtime_binding)))
        phase = 'source-stage'
        h.run('p14-source-stage', ['/usr/bin/python3', '-B', str(ROOT / 'integrations/drizzli/stage.py'),
            '--execute', '--source-recipe', '--destination', str(STAGE)], 270)
        h.run('p14-plugin-stage', ['/usr/bin/python3', '-B', str(ROOT / 'integrations/drizzli/prepare_build.py'),
            '--execute', '--stage', str(STAGE)], 90)
        metadata = h.locked_dependencies()
        inputs.write(OUTPUT / 'p14-source-stage.json', encoded(receipt('p14-source-stage',
            upstream_commit=metadata['commit'], upstream_tree=metadata['tree'],
            lock_sha256=metadata['package_lock_sha256'], source_recipe=True,
            plugin_execution=False, upstream_lifecycle_execution=False)))
        optional_cache = prepare_optional_cache(STAGE)
        source_seal = source_input_seal(inputs, STAGE)
        inputs.write(OUTPUT / 'p14-source-inputs.json', encoded(receipt('p14-original-source-inputs',
            files=source_seal, generated_paths_are_output_authority=False)))
        phase = 'runtime-boundary'
        helper.prechecks(platform)
        installed = True
        helper.process(['/usr/bin/sudo', '-n', '/usr/bin/install', '-o', 'root', '-g', 'root', '-m', '0600',
            '--', str(h.PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(['/usr/bin/sudo', '-n', helper.PARSER, '--add', '--skip-cache', str(helper.STAGED)], 10)
        base = private / 'drizzli'
        safe_directory(base, create=True)
        safe_directory(PROOF, create=True)
        view = boundary_api.View(base / 'view', candidate['packages'], 'drizzli')
        boundary = boundary_api.Boundary(view, h, h.BROWSER, resolver=resolver)
        boundary.stage_firefox()
        h.BOUNDARY = boundary
        h.write(h.OUTPUT / 'passwd', f'runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n'.encode())
        h.write(h.OUTPUT / 'group', f'runner:x:{os.getgid()}:\n'.encode())
        inputs.write(OUTPUT / 'runtime-boundary-started.json', encoded(receipt('p14-live-runtime-boundary',
            source=os.environ['GITHUB_SHA'], compiled=False)))
        boundary.prepare_cache()
        safe_directory(h.PRIVATE, create=True)
        safe_directory(h.PRIVATE / 'cache', create=True)
        h.write(h.PRIVATE / 'user.npmrc', b'')
        h.write(h.PRIVATE / 'global.npmrc', b'')
        libc = next(package['files']['usr/lib/x86_64-linux-gnu/libc.so.6'] for package in candidate['packages']
            if 'usr/lib/x86_64-linux-gnu/libc.so.6' in package['files'])
        libc_bytes = boundary_api.regular(Path('/usr/lib/x86_64-linux-gnu/libc.so.6'))
        require(sha(libc_bytes) == libc['sha256'], 'P14_WITNESS_INPUT')
        boundary_api.put(boundary.witness, libc_bytes)
        h.preflight('compile')
        phase = 'dependencies-acquisition'
        record = dependencies.acquire(h.PRIVATE)
        module('prepare_hosted_drizzli_provenance').notices(inputs, record['packages'])
        phase = 'dependencies-offline-installation'
        dependency_result = dependencies.install(h, record)
        check_optional_cache(STAGE, optional_cache)
        check_source_inputs(inputs, STAGE, source_seal)
        inputs.write(OUTPUT / 'p14-dependencies.json', encoded(receipt('p14-installed-dependencies',
            installation=dependency_result)))
        # The exact pure first-party guards used by the observer are exercised
        # with this authenticated Node, before any application source compiler.
        # No Vite, native binding, dependency or upstream code is imported here.
        phase = 'virtual-module-negative-tests'
        dependencies.check_execution_tree(h, record)
        boundary.check()
        h.run('p14-virtual-module-negative-tests', h.sandbox([str(h.NODE),
            str(STAGE / 'test-virtual-module-guards.mjs')], mode='compile', writable=STAGE),
            30, env=h.environment(), memory=h.compilation_memory('typecheck'))
        dependencies.check_execution_tree(h, record)
        check_source_inputs(inputs, STAGE, source_seal)
        check_optional_cache(STAGE, optional_cache)
        boundary.check()
        phase = 'offline-compilation'
        generated_metadata = False
        for name, cli, arguments, seconds in h.compile_commands():
            require(time.monotonic() - started <= 1800, 'P14_WHOLE_BUILD_DEADLINE')
            phase = name
            dependencies.check_execution_tree(h, record)
            check_source_inputs(inputs, STAGE, source_seal, generated_metadata=generated_metadata)
            check_optional_cache(STAGE, optional_cache)
            boundary.check()
            executable = h.installed_cli(cli)
            if name == 'production-build':
                # The exact Vite 8.3.1 native loader consumes this sealed TS
                # config directly with Node 24 type stripping. Kit's nested
                # build still uses its fixed Vite generator; .vite-temp must
                # be empty at stable dependency verification checkpoints.
                arguments = [*arguments, '--configLoader', 'native']
            h.run('p14-' + name, h.sandbox([str(h.NODE), str(executable), *arguments],
                mode='compile', writable=STAGE), seconds, env=h.environment(), memory=h.compilation_memory(name))
            if name == 'production-build':
                produced = True
            if name == 'localization':
                generated_metadata = True
            dependencies.check_execution_tree(h, record)
            check_source_inputs(inputs, STAGE, source_seal, generated_metadata=generated_metadata)
            check_optional_cache(STAGE, optional_cache)
            boundary.check()
            if name == 'localization':
                project_metadata_verified = True
        phase = 'output-inventory-and-notices'
        for path in (STAGE / 'build').rglob('*'):
            info = path.lstat()
            require(not path.is_symlink() and info.st_uid == os.getuid()
                and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)), 'P14_OUTPUT_TYPE')
            os.chmod(path, stat.S_IMODE(info.st_mode) & ~0o022)
        notice_records = source_notices(inputs, h, record['packages'])
        output_map = inputs.output_inventory(STAGE / 'build')
        inputs.write(OUTPUT / 'p14-output.json', encoded(receipt('p14-candidate-output',
            build_produced=produced, files=output_map, original_notice_files=notice_records,
            independent_reproduction=False, assets_exported=False)))
        graph, _graphs = graph_report(inputs, STAGE,
            {name: entry['input'] for name, entry in pins['dependencies']['packages'].items()},
            archives=record['packages'], output_map=output_map, source_seal=source_seal,
            notice_records=notice_records)
        graph['observed_graphs'] = _graphs
        graph_raw = encoded(graph)
        require(len(graph_raw) <= 32 * 1024**2, 'P14_GRAPH_TOTAL_BOUND')
        inputs.write(OUTPUT / 'p14-module-graphs.json', graph_raw)
        require(h.runtime_inventory() == runtime_binding, 'P14_RUNTIME_CHANGED')
        require(graph['closure_complete'], graph.get('failure', 'P14_MODULE_CLOSURE_INCOMPLETE'))
        phase = 'complete'
    except BaseException as error:
        failure = dict(category=type(error).__name__,
            code=str(error) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', str(error)) else 'P14_CANDIDATE_FAILED')
        if isinstance(error, UnreviewedGeneratedPath):
            failure['relative_path'] = error.relative_path
        raise
    finally:
        for sig in prior_handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and h.DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed) if installed or attempted else dict(complete=True)
            policy_removed = cleaning['complete']
            inputs.write(OUTPUT / 'runtime-boundary-cleanup.json', encoded(receipt('p14-runtime-cleanup',
                process_drain_confirmed=h.DRAIN_CONFIRMED, policy_removed=policy_removed, compiled=produced)))
            inputs.write(OUTPUT / 'p14-steps.json', encoded(receipt('p14-bounded-child-steps', steps=h.LOGS)))
            result = receipt('p14-drizzli-candidate-result', source=os.environ['GITHUB_SHA'], p13_source=P13_SOURCE,
                phase=phase, failure=failure, build_produced=produced,
                candidate_complete=phase == 'complete' and h.DRAIN_CONFIRMED and policy_removed,
                process_drain_confirmed=h.DRAIN_CONFIRMED, policy_removed=policy_removed,
                independent_reproduction=False, output_admitted=False,
                project_metadata_verified_after_localization=project_metadata_verified,
                project_metadata_after_localization={name: dict(bytes=size, sha256=digest)
                    for name, (size, digest) in PROJECT_METADATA.items()} if project_metadata_verified else {},
                dependencies_lifecycle_executed=False, compiled_networkless=True,
                release_created=False, assets_exported=False)
            inputs.write(OUTPUT / 'p14-result.json', encoded(result))
            inputs.write(OUTPUT / 'result.json', encoded(receipt('client-input-inventory-result',
                profile='drizzli', mode=MODE, phase=phase, failure=failure, compiled=produced)))
            require(h.DRAIN_CONFIRMED and policy_removed, 'P14_CLEANUP_UNPROVEN')
        finally:
            h.BOUNDARY = None
            for sig, previous in prior_handlers.items():
                signal.signal(sig, previous)


def project():
    os.umask(0o077)
    inputs = module('prepare_hosted_client_inputs')
    inputs.hosted_guard(os.environ, 'drizzli')
    safe_directory(OUTPUT)
    destination = inputs.project_metadata('drizzli')
    manifest = inputs.document(inputs.read(destination / 'projection.json'))
    total = sum(item['bytes'] for item in manifest['files'].values())
    files = dict(manifest['files'])
    def copy(source, name, bound=8 * 1024**2):
        nonlocal total
        raw = inputs.read(source, bound)
        raw.decode('utf-8')
        total += len(raw)
        require(total <= MAX_PUBLIC, 'P14_PUBLIC_BOUND')
        inputs.write(destination / name, raw)
        files[name] = dict(bytes=len(raw), sha256=sha(raw))
    for name in sorted(RESULT_NAMES):
        path = OUTPUT / name
        if path.exists() or path.is_symlink():
            value = inputs.document(inputs.read(path))
            require(value.get('admitted') is False and value.get('product_admitted') is False,
                'P14_PROJECTION_AUTHORITY')
            copy(path, name, 32 * 1024**2)
    steps_path = OUTPUT / 'p14-steps.json'
    if steps_path.exists():
        steps = inputs.document(inputs.read(steps_path))['steps']
        require(type(steps) is list and len(steps) <= 2048, 'P14_LOG_COUNT')
        for step in steps:
            name = step['name']
            require(type(name) is str and re.fullmatch(r'[a-z0-9-]{1,100}', name), 'P14_LOG_NAME')
            source = OUTPUT / 'runtime-private/harness' / (name + '.log')
            raw = inputs.read(source, 2 * 1024**2)
            require(sha(raw) == step['sha256'] and len(raw) == step['bytes'], 'P14_LOG_IDENTITY')
            copy(source, name + '.log', 2 * 1024**2)
    # Original notice input bundle and upstream licenses only; no application assets.
    notices, _bundle = inputs.notice_inputs()
    copy(ROOT / notices['npm']['bundle'], 'npm-originals.txt', 16 * 1024**2)
    for item in module('prepare_hosted_drizzli_provenance').notices(inputs).values():
        copy(ROOT / item['source'], Path(item['output']).name, 128 * 1024)
    for source_name, public_name in (('LICENSE', 'LICENSE.DRIZZLI'), ('LICENSE.VOLPAROSSA', 'LICENSE.VOLPAROSSA')):
        source = STAGE / source_name
        if source.exists():
            copy(source, public_name, 128 * 1024)
    for name in ('message-format', 'm-function-matcher'):
        source = STAGE / 'volparossa-build-plugins' / (name + '.LICENSE')
        if source.exists():
            copy(source, name + '.LICENSE', 128 * 1024)
    inputs.write(destination / 'p14-projection.json', encoded(receipt('p14-closed-projection',
        files=files, binaries_exported=False, application_assets_exported=False)))


def cleanup():
    inputs = module('prepare_hosted_client_inputs')
    inputs.hosted_guard(os.environ, 'drizzli')
    safe_directory(OUTPUT)
    value = inputs.document(inputs.read(OUTPUT / 'p14-result.json'))
    require(value.get('process_drain_confirmed') is True and value.get('policy_removed') is True,
        'P14_CLEANUP_UNCONFIRMED')
    # Installer and boundary receipts must be confirmed before deleting any tree.
    for label in ('simulation', 'install'):
        if (OUTPUT / ('installer-' + label + '-started.json')).exists():
            evidence = inputs.document(inputs.read(OUTPUT / ('installer-' + label + '-cleanup.json')))
            require(evidence.get('owned_session_drained') is True and evidence.get('leader_reaped') is True,
                'P14_INSTALLER_CLEANUP_UNCONFIRMED')
    for path in (STAGE, PROOF):
        if path.exists() or path.is_symlink():
            safe_directory(path)
            if path == STAGE:
                cache = path / 'project.inlang/cache'
                if cache.exists() or cache.is_symlink():
                    info = cache.lstat()
                    require(stat.S_ISDIR(info.st_mode) and not cache.is_symlink()
                        and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o500
                        and not any(cache.iterdir()), 'P14_OPTIONAL_CACHE_CLEANUP')
                    cache.rmdir()
            shutil.rmtree(path)
    inputs.cleanup_candidate('drizzli')
    require(all(not path.exists() and not path.is_symlink() for path in (OUTPUT, PUBLIC, STAGE, PROOF)),
        'P14_CLEANUP_INCOMPLETE')
    print(encoded(receipt('p14-final-cleanup', private_absent=True, public_absent=True,
        stage_absent=True, proof_absent=True, privileged_cleanup=False)).decode(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('build', 'project', 'cleanup'), required=True)
    args = parser.parse_args()
    {'build': build, 'project': project, 'cleanup': cleanup}[args.mode]()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        print('P14_CANDIDATE_FAILED; inspect closed diagnostics', file=sys.stderr)
        sys.exit(1)
