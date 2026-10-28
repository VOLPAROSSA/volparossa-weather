#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""One manual P15 web candidate; existing P13 Boundary, no output admission.

Host orchestration and data acquisition only. Flutter/pub/test/build execute
through the unchanged Boundary API with no network. No binaries or raw logs
are exported. The historical producer and all shared input records stay intact.
"""
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
BASE = 'e774912e292f339d42ff23f00b4d8fc5d69e5b47'
INPUT = ROOT / 'build/hosted-overmorrow-input-candidate'
PUBLIC = ROOT / 'build/p15-overmorrow-candidate-public'
STAGE = ROOT / 'build/p15-overmorrow-stage'
DEPLOY = ROOT / 'build/p15-overmorrow-web'
P13_REPORT_SHA = '3a2988ab6f00ecee1ece59c00c9f1c169c7ef054da4d05fdba7848680bcbd4a9'
MODE = 'source-candidate-build'
MAX_STAGE_ENTRIES = 20000
OWNED_SOURCE = ('scripts/prepare_hosted_overmorrow_candidate.py',
                'scripts/prepare_hosted_overmorrow_dependencies.py',
                'scripts/prepare_hosted_overmorrow_hooks.py',
                'scripts/prepare_hosted_overmorrow_plugins.py',
                'third_party/overmorrow-tool-inputs-v1.json',
                'third_party/overmorrow-hook-inputs-v1.json',
                'third_party/overmorrow-plugin-inputs-v1.json',
                '.github/workflows/hosted-overmorrow.yml')
GENERATED_PLATFORM_FILES = frozenset((
    '.flutter-plugins-dependencies', '.flutter-plugins', 'android/local.properties',
    'android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java',
    'ios/Runner/GeneratedPluginRegistrant.h', 'ios/Runner/GeneratedPluginRegistrant.m',
    'ios/Flutter/Generated.xcconfig', 'ios/Flutter/flutter_export_environment.sh',
    'macos/Flutter/GeneratedPluginRegistrant.swift',
    *(platform + '/flutter/' + name for platform in ('linux', 'windows') for name in
      ('generated_plugin_registrant.cc', 'generated_plugin_registrant.h', 'generated_plugins.cmake')),
))


def module(name):
    spec = importlib.util.spec_from_file_location('_p15_' + name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


I = module('prepare_hosted_client_inputs')
B = module('prepare_hosted_client_runtime')
O = module('prepare_hosted_overmorrow_ci')
H = O.H
require = I.require


def record(path, value):
    raw = I.canonical(value)
    require(len(raw) <= 4 * 1024**2, 'P15_CLOSED_METADATA_BOUND')
    I.write(path, raw)


class SDKGitFailure(ValueError):
    """Closed diagnostics only; never retain Git output, argv or environment."""
    def __init__(self, observation):
        super().__init__('P15_SDK_GIT_COMMAND_FAILED')
        self.sdk_git_failure = observation


class SDKGitChecks:
    """Preserve the adapter's checks with a content comparison on Git 2.43.

    Its immutable archive index contains the producer's cached file stats.
    With index refresh disabled, 2.43's --quiet/--exit-code falsely reports
    stat-only changes even when the rendered patch is empty. Require an empty
    explicit patch instead; nonzero commands AND any patch/output still fail.
    The original index is never refreshed. No external diff/textconv executes.
    Timeouts, environment and process cleanup use the unchanged P13 helper.
    """
    def __init__(self, helper, receipts):
        self.helper, self.receipts = helper, receipts
        self.expected = (
            ('rev-parse', ['/usr/bin/git', '--no-optional-locks', '-C', str(O.SDK), 'rev-parse', 'HEAD'], 10),
            ('diff', O.sdk_diff_command(), 20),
            ('ls-files', ['/usr/bin/git', '--no-optional-locks', '-C', str(O.SDK),
                          'ls-files', '--others', 'bin/internal'], 10),
        )
        self.index = 0

    def process(self, argv, seconds):
        require(self.index < len(self.expected), 'P15_SDK_GIT_CALL_COUNT')
        name, expected, limit = self.expected[self.index]
        require(argv == expected and seconds == limit, 'P15_SDK_GIT_COMMAND_CHANGED')
        require(len(self.receipts) < 64, 'P15_SDK_GIT_RECEIPT_BOUND')
        self.index += 1
        command = list(argv)
        if name == 'diff':
            offset = command.index('--quiet')
            command[offset:offset + 1] = ['--patch', '--no-ext-diff', '--no-textconv']
        try:
            result = self.helper.process(command, seconds)
        except self.helper.CommandFailure as error:
            # Validate typed fields before export, including bool/int and
            # integer bounds. No str(error), private paths or raw output.
            category, code = error.category, error.code
            count, digest = error.output_bytes, error.output_sha256
            require(type(category) is str and category in ('deadline', 'output-bound', 'exit-status')
                    and (code is None or type(code) is int and -255 <= code <= 255)
                    and type(count) is int and 0 <= count <= self.helper.LIMIT
                    and type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest),
                    'P15_SDK_GIT_DIAGNOSTIC_SCHEMA')
            observation = dict(command=name, category=category, exit_status=code,
                               output_bytes=count, output_sha256=digest)
            self.receipts.append(dict(observation, success=False))
            raise SDKGitFailure(observation) from None
        if name == 'diff' and result[1]:
            observation = dict(command=name, category='content-difference', exit_status=result[0],
                               output_bytes=len(result[1]), output_sha256=I.sha(result[1]))
            self.receipts.append(dict(observation, success=False))
            raise SDKGitFailure(observation)
        self.receipts.append(dict(command=name, category='complete', exit_status=0, success=True))
        return result


def guards():
    I.hosted_guard(os.environ, 'overmorrow')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'P15_SINGLE_MANUAL_ATTEMPT')
    event = I.document(I.read(Path(os.environ['GITHUB_EVENT_PATH']), 256 * 1024))
    require(event.get('inputs') == dict(input_mode=MODE), 'P15_EXPLICIT_MODE')
    require(os.getuid() == os.geteuid() != 0, 'ORDINARY_RUNNER_REQUIRED')
    helper = H.policy_helper()
    platform = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_decoder.py'))
    helper.process(['/usr/bin/git', '-C', str(ROOT), 'merge-base', '--is-ancestor', BASE, 'HEAD'], 10)
    _, head = helper.process(['/usr/bin/git', '-C', str(ROOT), 'rev-parse', 'HEAD'], 10)
    require(head.decode().strip() == os.environ['GITHUB_SHA'], 'P15_SOURCE_COMMIT')
    # P15 is allowed only its own files and its own Overmorrow workflow.
    _, changed = helper.process(['/usr/bin/git', '-C', str(ROOT), 'diff', '--name-only', BASE, 'HEAD'], 10)
    allowed = set(OWNED_SOURCE) | {'tests/test_hosted_overmorrow_candidate.py',
        'tests/test_hosted_overmorrow_dependencies.py', 'tests/test_hosted_overmorrow_hooks.py',
        'tests/test_hosted_overmorrow_plugins.py',
        'docs/P15_OVERMORROW_CANDIDATE.md'}
    require(set(changed.decode().splitlines()) <= allowed, 'P15_SHARED_SOURCE_CHANGED')
    helper.process(['/usr/bin/git', '-C', str(ROOT), 'diff', '--quiet', 'HEAD', '--'], 10)
    return helper, platform


def source_files(stage, *, app_packages=None, plugin_aliases=None):
    """Seal application inputs, excluding Git metadata, before any SDK runs."""
    files, total, count = {}, 0, 0
    pending = [stage]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(stage).as_posix()
                if name == '.git':
                    continue
                count += 1
                require(count <= MAX_STAGE_ENTRIES and len(path.relative_to(stage).parts) <= 64,
                        'P15_STAGE_ENTRY_BOUND')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    match = re.fullmatch(r'(?:linux|windows)/flutter/ephemeral/\.plugin_symlinks/([a-z0-9_]+)', name)
                    require(match is not None and app_packages is not None
                            and match[1] in app_packages and app_packages[match[1]]['source'] == 'hosted', 'P15_SOURCE_ALIAS')
                    require(plugin_aliases is not None, 'P15_PLUGIN_BINDING_REQUIRED')
                    plugin_aliases.check_leaf(name, info)
                    continue
                require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'P15_SOURCE_ALIAS')
                require(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'P15_SOURCE_FILE')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    total += info.st_size
                    require(info.st_nlink == 1 and info.st_size <= 256 * 1024**2
                            and total <= 1024**3, 'P15_SOURCE_FILE')
                    with path.open('rb') as stream:
                        files[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    require(0 < len(files) < 10000, 'P15_SOURCE_COUNT')
    return files


def recheck_source(stage, expected, app_packages, plugin_aliases=None):
    actual = source_files(stage, app_packages=app_packages, plugin_aliases=plugin_aliases)
    generated = {}
    localizations = {'lib/l10n/app_localizations.dart'}
    for name in expected:
        match = re.fullmatch(r'lib/l10n/app_([a-z]{2,3}(?:_[A-Za-z0-9]+)*)\.arb', name)
        if match:
            localizations.add('lib/l10n/app_localizations_' + match[1] + '.dart')
    for name, checksum in expected.items():
        # These exact tracked files are generated by the pinned SDK gen-l10n
        # from unchanged ARBs. No other application input may be replaced.
        require(name in actual and (actual[name] == checksum or name in localizations
                or name in GENERATED_PLATFORM_FILES), 'P15_SOURCE_CHANGED')
        if actual[name] != checksum:
            generated[name] = actual[name]
    for name in actual.keys() - expected.keys():
        require(name.startswith(('.dart_tool/', 'build/'))
                or name == 'test/volparossa/fixtures/products.json'
                or name in GENERATED_PLATFORM_FILES or name in localizations, 'P15_UNKNOWN_GENERATED_SOURCE')
    return dict(original_files=len(expected), original_sha256=I.sha(I.canonical(expected)),
                generated_localization_files=len(generated), generated_localization_sha256=I.sha(I.canonical(generated)))


def seal_app_sources(stage, app_packages, plugin_aliases=None):
    # Generated compilation state is not source authority. All source and
    # platform-generator outputs are sealed after the sole app-pub operation.
    return {name: digest for name, digest in source_files(stage, app_packages=app_packages,
            plugin_aliases=plugin_aliases).items()
            if not name.startswith(('.dart_tool/', 'build/'))
            and name != 'test/volparossa/fixtures/products.json'}


def asset_binding(stage, sdk, output=None):
    notices, _ = I.notice_inputs()
    noto = I.read(stage / 'fonts/NotoSans_Condensed-Regular.ttf', 2 * 1024**2)
    require(I.sha(noto) == notices['fonts']['NotoSans']['font_sha256'], 'P15_NOTO_FONT')
    material = I.full_material_font(sdk, output)
    if output is not None:
        require(I.read(output / 'assets/fonts/NotoSans_Condensed-Regular.ttf', 2 * 1024**2) == noto,
                'P15_NOTO_OUTPUT')
        for path in (stage / 'assets').rglob('*'):
            if path.is_file():
                target = output / 'assets' / path.relative_to(stage)
                require(I.read(target, 8 * 1024**2) == I.read(path, 8 * 1024**2), 'P15_ASSET_OUTPUT')
        raw = I.read(output / 'assets/NOTICES', 8 * 1024**2)
        require(raw and b'Copyright' in raw, 'P15_FLUTTER_NOTICES')
    return dict(noto_sha256=I.sha(noto), material=material, original_assets_unchanged=True)


def command(action):
    require(action in ('dependencies-offline', 'test', 'build'), 'P15_OFFLINE_ACTION')
    argv = O.flutter_command(action)
    if action == 'build':
        argv += ['--no-tree-shake-icons']
        require(argv[-len(O.build_contract()['source_web_arguments']()):]
                == O.build_contract()['source_web_arguments'](), 'P15_WEB_SOURCE_FLAGS')
    return argv


def tool_command():
    # Real locked resolution, before any Flutter artifact initialization.
    # Package sources and both original locks stay read-only. Only the
    # existing private .dart_tool mount receives the generated state.
    return [str(O.SDK / 'bin/cache/dart-sdk/bin/dart'), '--suppress-analytics', 'pub',
            '--directory', str(O.SDK / 'packages/flutter_tools'),
            'get', '--offline', '--enforce-lockfile', '--no-precompile', '--no-example']


def diagnostics():
    # Raw child output stays runner-private. Export only fixed diagnostic
    # categories plus exit/resource/hash observations, never content or paths.
    patterns = dict(read_only=r'Read-only file system', permission=r'Permission denied',
        network=r'(?:SocketException|Network is unreachable|Failed host lookup)',
        dependency=r'(?:version solving failed|Could not find a file named|doesn.t match the existing)',
        compiler=r'(?:Error:|Compilation failed|Target .* failed)', memory=r'(?:Out of [Mm]emory|out of memory)',
        sdk_download=r'(?:Downloading|download failed)', hook=r'(?:hook/build|hook/link|Running build hooks)')
    rows = []
    for item in H.LOGS:
        raw = I.read(H.OUTPUT / (item['name'] + '.log'), 2 * 1024**2)
        content = raw.decode('utf-8', errors='replace')
        rows.append(dict(item, diagnostic_categories={key: bool(re.search(pattern, content))
            for key, pattern in patterns.items()}))
    return rows


def cleanup_owned(path, identity):
    if identity is None:
        require(not path.exists() and not path.is_symlink(), 'P15_UNOWNED_OUTPUT')
        return
    info = path.lstat()
    require(path.resolve() == path and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and (info.st_dev, info.st_ino) == identity, 'P15_CLEANUP_IDENTITY')
    shutil.rmtree(path)
    require(not path.exists() and not path.is_symlink(), 'P15_OUTPUT_CLEANUP')


def execute():
    helper, platform = guards()
    PUBLIC.mkdir(mode=0o700)
    INPUT.mkdir(mode=0o700)
    private = INPUT / 'runtime-private'
    private.mkdir(mode=0o700)
    installed = attempted = runtime_started = success = compiled = tests_passed = False
    phase = 'package-provisioning'
    stage_identity = deploy_identity = None
    details = {}
    failure = None
    started = time.monotonic()
    netns = os.readlink('/proc/self/ns/net')
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_sig, _frame):
        raise H.Interrupted('P15_INTERRUPTED')
    for sig in handlers:
        signal.signal(sig, interrupted)
    try:
        apt = module('prepare_hosted_client_apt')
        package_inputs = I.load_package_inputs('overmorrow')
        apt.installed_inventory('overmorrow', INPUT, package_inputs)
        packages = I.document(I.read(INPUT / 'apt-candidate.json'))['packages']
        phase = 'materialize-pinned-runtime-sdk'
        runtime, sdk = private / 'runtime', private / 'flutter-sdk'
        runtime.mkdir(mode=0o700); sdk.mkdir(mode=0o700)
        rp, sp = module('prepare_hosted_runtime'), module('prepare_hosted_flutter')
        pin, pin_sha = rp.load_pin()
        rp.prepare(runtime, pin, pin_sha, fetch=True, with_npm=True)
        sp.prepare(sdk, sp.load_pin())
        # The controller owns distinct private state; no module source or
        # shared manifest is patched, and no historical fallback is enabled.
        H.RUNTIME, H.NODE, H.NPM = runtime, runtime / 'node/bin/node', runtime / 'node/lib/node_modules/npm/bin/npm-cli.js'
        H.OUTPUT = private / 'harness'
        H.OUTPUT.mkdir(mode=0o700)
        base = private / 'overmorrow'
        base.mkdir(mode=0o700)
        H.PRIVATE, H.STAGE, H.PROOF = base / 'state', STAGE, base / 'proof'
        H.BOUNDARY_DEPLOY, H.BOUNDARY_TABLE_PROOF = DEPLOY, base / 'table-proof'
        H.FIREFOX = H.BROWSER / 'build/firefox-hosted-ci'
        O.OUTPUT, O.PRIVATE, O.STAGE = H.OUTPUT, H.PRIVATE, STAGE
        O.DEPLOY, O.PROOF, O.TABLE_PROOF, O.SDK = DEPLOY, H.PROOF, H.BOUNDARY_TABLE_PROOF, sdk
        O.SDK_TOOL_STATE, O.SDK_TOOL_MOUNT = H.PRIVATE / 'flutter-tool-state', sdk / 'packages/flutter_tools/.dart_tool'
        phase = 'boundary-bindings'
        view = B.View(base / 'view', B.subset(packages, 'overmorrow', I), 'overmorrow')
        # Every executed dependency/compiler command is offline. No resolver
        # snapshot is needed; the original API rejects acquire without one.
        boundary = B.Boundary(view, H, H.BROWSER, sdk)
        H.BOUNDARY = boundary
        H.write(H.OUTPUT / 'passwd', f'runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n'.encode())
        H.write(H.OUTPUT / 'group', f'runner:x:{os.getgid()}:\n'.encode())
        helper.prechecks(platform)
        record(INPUT / 'runtime-boundary-started.json', dict(schema=1, admitted=False, source=os.environ['GITHUB_SHA']))
        runtime_started = True
        phase = 'policy-install'
        installed = True
        helper.process(['/usr/bin/sudo', '-n', '/usr/bin/install', '-o', 'root', '-g', 'root', '-m', '0600',
            '--', str(H.PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(['/usr/bin/sudo', '-n', helper.PARSER, '--add', '--skip-cache', str(helper.STAGED)], 10)
        details['cache_bindings'] = len(boundary.prepare_cache())
        H.PRIVATE.mkdir(mode=0o700)
        for name in ('config', 'cache'):
            (H.PRIVATE / name).mkdir(mode=0o700)
        O.prepare_tool_state()
        phase = 'controlled-source-stage'
        # Staging is inert, the exact commit/tree/patch/lock are checked by
        # the existing stager. No project/dependency lifecycle runs here.
        stager = runpy.run_path(str(ROOT / 'integrations/overmorrow/stage.py'))
        try:
            stager['stage'](STAGE, source_recipe=True)
        finally:
            if STAGE.is_dir() and not STAGE.is_symlink():
                info = STAGE.lstat(); stage_identity = (info.st_dev, info.st_ino)
        expected_source = source_files(STAGE)
        stage_git = {name: I.sha(I.read(STAGE / '.git' / name)) for name in ('HEAD', 'config')}
        hooks = module('prepare_hosted_overmorrow_hooks')
        hook_run = hooks.HookRun(STAGE, sdk, H.PRIVATE / 'pub-cache', expected_source['pubspec.yaml'])
        details['assets_before'] = asset_binding(STAGE, sdk)
        phase = 'controlled-pub-data'
        deps = module('prepare_hosted_overmorrow_dependencies')
        cache = H.PRIVATE / 'pub-cache'
        cache.mkdir(mode=0o700)
        details['dependencies_prepared'] = deps.prepare(cache, sdk)
        details['dependencies_initial'] = deps.verify(cache, sdk)
        plugins = module('prepare_hosted_overmorrow_plugins')
        plugin_aliases = plugins.Binding(STAGE, cache,
            I.read(ROOT / 'third_party/overmorrow-plugin-inputs-v1.json', 1024**2))
        phase = 'offline-preflight'
        details['compile_preflight'] = O.preflight('compile')
        runtime_before = H.runtime_inventory()
        sdk_before = sp.verify_materialized(sdk, allow_build_state=True)
        app_packages = I.pub_lock(I.read(ROOT / 'third_party/client-locks/overmorrow-pubspec.lock'))
        tool_ready = False
        sealed_app = None
        def verify_plugins():
            plugin_aliases.check_probe_input(H.PRIVATE)
            expected = plugin_aliases.verify()
            proofs = details.setdefault('plugin_namespace_proofs', [])
            require(len(proofs) < 8, 'P15_PLUGIN_PROOF_COUNT')
            raw = H.run('p15-plugins-' + str(len(proofs)),
                O.sandbox(plugin_aliases.probe_command(), mode='compile'), 60,
                env=O.environment(), memory=O.FLUTTER_MEMORY)
            plugin_aliases.check_probe_input(H.PRIVATE)
            proofs.append(plugin_aliases.accept_probe(raw, expected))
        def verify_inputs(with_config=False):
            boundary.check()
            require(H.runtime_inventory() == runtime_before, 'P15_RUNTIME_CHANGED')
            checked = SDKGitChecks(helper, details.setdefault('sdk_git_checks', []))
            O.verify_phase_inputs(checked, I.document(I.read(ROOT / 'integrations/overmorrow/upstream.json')))
            require(checked.index == 3, 'P15_SDK_GIT_CALL_COUNT')
            details['dependencies_final'] = deps.verify(cache, sdk, STAGE if with_config else None,
                tool_state=O.SDK_TOOL_STATE if tool_ready else None)
            if sealed_app is not None:
                verify_plugins()
            details['source'] = recheck_source(STAGE, expected_source, app_packages,
                plugin_aliases if sealed_app is not None else None)
            require(stage_git == {name: I.sha(I.read(STAGE / '.git' / name))
                for name in stage_git}, 'P15_STAGE_GIT_CHANGED')
            if sealed_app is not None:
                require(seal_app_sources(STAGE, app_packages, plugin_aliases) == sealed_app,
                        'P15_GENERATED_APP_SOURCE_CHANGED')
        phase = 'p15-tool-pub-offline'
        verify_inputs()
        H.run(phase, O.sandbox(tool_command(), mode='compile'), 180,
              env=O.environment(), memory=O.FLUTTER_MEMORY)
        tool_ready = True
        verify_inputs()
        for action, name, seconds in (('dependencies-offline', 'p15-pub-offline', 180),
                ('test', 'p15-flutter-tests', 900), ('build', 'p15-flutter-web-build', 900)):
            phase = name
            require(time.monotonic() - started < 2100, 'P15_WHOLE_DEADLINE')
            verify_inputs(with_config=action != 'dependencies-offline')
            argv, child_environment = command(action), O.environment()
            if action in ('test', 'build'):
                details.setdefault('hook_authorizations', {})[action] = hook_run.before(action, argv, child_environment)
            try:
                raw = H.run(name, O.sandbox(argv, mode='compile'), seconds,
                    env=child_environment, memory=O.FLUTTER_MEMORY)
            except BaseException:
                if action in ('test', 'build'):
                    details['hook_execution_unverified'] = hook_run.failure_observation()
                raise
            if action == 'dependencies-offline':
                # Authenticate all generated package/plugin metadata before any
                # alias admission. Both host and original compile namespace
                # must prove the same original package/file identities.
                details['dependencies_final'] = deps.verify(cache, sdk, STAGE, tool_state=O.SDK_TOOL_STATE)
                details['plugins_sealed'] = plugin_aliases.seal()
                plugin_aliases.write_probe_input(H.PRIVATE)
                verify_plugins()
                sealed_app = seal_app_sources(STAGE, app_packages, plugin_aliases)
                fixture = STAGE / 'test/volparossa/fixtures/products.json'
                fixture.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                H.run('p15-test-fixtures', O.sandbox([str(H.NODE),
                    str(ROOT / 'integrations/overmorrow/test-fixtures.mjs'), str(fixture)], mode='compile'),
                    30, env=O.environment())
            if action == 'test':
                require(re.search(rb'\+24: All tests passed!', raw), 'P15_FLUTTER_TEST_COUNT')
                tests_passed = True
            if action == 'build':
                compiled = True
            if action in ('test', 'build'):
                details['hook_execution'] = hook_run.after(action)
            verify_inputs(with_config=True)
        phase = 'output-integrity-and-notices'
        details['assets_output'] = asset_binding(STAGE, sdk, STAGE / 'build/web')
        # The existing bounded copier is reused; no publication or browser
        # service starts. Original font notices are added byte-for-byte.
        for path in (STAGE / 'build/web').rglob('*'):
            require(not path.is_symlink(), 'P15_BUILT_ALIAS')
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o022)
        copier = runpy.run_path(str(ROOT / 'integrations/overmorrow/deploy.py'))
        try:
            deployment = copier['deploy'](STAGE, DEPLOY)
        finally:
            if DEPLOY.is_dir() and not DEPLOY.is_symlink():
                info = DEPLOY.lstat(); deploy_identity = (info.st_dev, info.st_ino)
        font_notices = DEPLOY / 'source-font-notices'
        font_notices.mkdir(mode=0o700)
        for path in sorted((STAGE / 'volparossa-source-notices').iterdir()):
            I.write(font_notices / path.name, I.read(path))
        details['output'] = dict(deployment=deployment, full_tree=I.output_inventory(DEPLOY))
        details['sdk_before'] = sdk_before
        details['sdk_after'] = sp.verify_materialized(sdk, allow_build_state=True)
        details['tool_state'] = O.tool_state_binding()
        verify_inputs(with_config=True)
        phase, success = 'complete', True
    except BaseException as error:
        code = str(error)
        failure = dict(category=type(error).__name__,
            code=code if re.fullmatch(r'[A-Z0-9_]{1,100}', code) else 'P15_OPERATION_FAILED')
        if isinstance(error, SDKGitFailure):
            failure['sdk_git'] = error.sdk_git_failure
        if 'plugins' in locals() and isinstance(error, plugins.PluginFailure):
            details['plugin_rejection'] = error.plugin_failure
        observation = getattr(error, 'observation', None)
        if observation is not None:
            require(type(observation) is dict and set(observation) == {'code', 'package', 'version', 'hook'}
                and all(type(v) is str and len(v) <= 128 for v in observation.values()), 'P15_HOOK_OBSERVATION_SCHEMA')
            details['hook_rejection'] = observation
    finally:
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed) if installed or attempted else dict(complete=True)
            drained = H.DRAIN_CONFIRMED and cleaning['complete']
            if runtime_started:
                record(INPUT / 'runtime-boundary-cleanup.json', dict(schema=1, admitted=False,
                    process_drain_confirmed=H.DRAIN_CONFIRMED, policy_removed=cleaning['complete']))
            steps = diagnostics() if H.LOGS else []
            cleanup = dict(process_drain_confirmed=H.DRAIN_CONFIRMED,
                policy_removed=cleaning['complete'], private_inputs_absent=False,
                stage_absent=False, output_absent=False,
                host_netns_unchanged=os.readlink('/proc/self/ns/net') == netns)
            cleanup_error = None
            try:
                require(drained and cleanup['host_netns_unchanged'], 'P15_PROCESS_POLICY_CLEANUP')
                cleanup_owned(STAGE, stage_identity)
                cleanup_owned(DEPLOY, deploy_identity)
                I.cleanup_candidate('overmorrow')
                cleanup.update(private_inputs_absent=not INPUT.exists(),
                    stage_absent=not STAGE.exists(), output_absent=not DEPLOY.exists())
            except BaseException as error:
                cleanup_error = dict(category=type(error).__name__, code='P15_CLEANUP_UNPROVEN')
            success = success and all(cleanup.values()) and cleanup_error is None
            record(PUBLIC / 'cleanup.json', dict(schema=1, admitted=False, **cleanup, failure=cleanup_error))
            record(PUBLIC / 'result.json', dict(schema=1, kind='p15-overmorrow-first-candidate', admitted=False,
                source=os.environ['GITHUB_SHA'], base=BASE, run_id=os.environ['GITHUB_RUN_ID'],
                run_attempt=os.environ['GITHUB_RUN_ATTEMPT'], p13_acceptance_sha256=P13_REPORT_SHA,
                phase=phase, success=success, failure=failure, cleanup_failure=cleanup_error,
                steps=steps, details=details,
                controller_sources={p:I.sha(I.read(ROOT/p)) for p in OWNED_SOURCE},
                compiled=compiled, offline_execution_required=True, flutter_tests=24 if tests_passed else None,
                reproducible_output_verified=False, consumer_admitted=False, production_authority=False,
                browser_product_tested=False, native_mobile=False, binaries_exported=False))
        finally:
            H.BOUNDARY = None
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    require(success, 'P15_CANDIDATE_FAILED')


def main():
    require(sys.argv[1:] == [], 'P15_NO_ARGUMENTS')
    os.umask(0o077)
    execute()


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print('P15_CANDIDATE_FAILED; inspect closed candidate metadata', file=sys.stderr)
        sys.exit(1)
