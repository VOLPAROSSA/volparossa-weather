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
DIAGNOSTIC_MODE = 'source-pub-diagnostic'
OBSERVATIONS_SHA = '5dfda4d8a1716b798f9c3b5979cd18b3a7b3c7256304d5a2f8f3c4556d2918f9'
METADATA_OBSERVATIONS_SHA = 'bc96728fd748e61420e3e9770035ddee8fac535f8e2e32b143d3c6d7f4c2b561'
PUB_OUTPUTS_SHA = 'c8d87288da4897bb2baf04b8f00c89c2816ced78abd94b5cdaa621c61e638509'
ORIGINAL_SOURCE_SHA = '94a0f9632f425453887f41b8b3e9926e3d4c3516f3fd4ce3d8db1540d7e48baf'
MAX_STAGE_ENTRIES = 20000
OWNED_SOURCE = ('scripts/prepare_hosted_overmorrow_candidate.py',
                'scripts/prepare_hosted_overmorrow_dependencies.py',
                'scripts/prepare_hosted_overmorrow_hooks.py',
                'scripts/prepare_hosted_overmorrow_plugins.py',
                'scripts/prepare_hosted_overmorrow_sources.py',
                'scripts/prepare_hosted_overmorrow_pub_metadata.py',
                'scripts/prepare_hosted_overmorrow_pub_outputs.py',
                'third_party/overmorrow-tool-inputs-v1.json',
                'third_party/overmorrow-hook-inputs-v1.json',
                'third_party/overmorrow-plugin-inputs-v1.json',
                'third_party/overmorrow-pub-source-observations-v1.json',
                'third_party/overmorrow-pub-metadata-observations-v1.json',
                'third_party/overmorrow-pub-outputs-v1.json',
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
S = module('prepare_hosted_overmorrow_sources')
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


def selected_mode():
    event = I.document(I.read(Path(os.environ['GITHUB_EVENT_PATH']), 256 * 1024))
    require(type(event.get('inputs')) is dict and set(event['inputs']) == {'input_mode'}
            and event['inputs']['input_mode'] in (MODE, DIAGNOSTIC_MODE), 'P15_EXPLICIT_MODE')
    return event['inputs']['input_mode']


def guards(*, mode=MODE):
    I.hosted_guard(os.environ, 'overmorrow')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'P15_SINGLE_MANUAL_ATTEMPT')
    event = I.document(I.read(Path(os.environ['GITHUB_EVENT_PATH']), 256 * 1024))
    require(mode in (MODE, DIAGNOSTIC_MODE) and event.get('inputs') == dict(input_mode=mode), 'P15_EXPLICIT_MODE')
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
        'tests/test_hosted_overmorrow_sources.py',
        'tests/test_hosted_overmorrow_pub_metadata.py',
        'tests/test_hosted_overmorrow_pub_outputs.py',
        'docs/P15_OVERMORROW_CANDIDATE.md'}
    require(set(changed.decode().splitlines()) <= allowed, 'P15_SHARED_SOURCE_CHANGED')
    helper.process(['/usr/bin/git', '-C', str(ROOT), 'diff', '--quiet', 'HEAD', '--'], 10)
    return helper, platform


def capture_source(stage, inventory=None, plugin_aliases=None):
    owned = inventory is None
    inventory = S.Inventory(stage) if owned else inventory
    try:
        value = inventory.capture(plugin_aliases)
        require(sum(len(value[k]) for k in S.KINDS) <= MAX_STAGE_ENTRIES, 'P15_STAGE_ENTRY_BOUND')
        require(0 < len(value['files']) < 10000, 'P15_SOURCE_COUNT')
        return value
    except S.SourceFailure as error:
        mapping = dict(P15_SOURCE_ENTRY_BOUND='P15_STAGE_ENTRY_BOUND',
                       P15_SOURCE_DEPTH_BOUND='P15_STAGE_ENTRY_BOUND', P15_SOURCE_FILE_METADATA='P15_SOURCE_FILE')
        raise ValueError(mapping.get(str(error), str(error))) from None
    finally:
        if owned:
            require(inventory.close(), 'P15_SOURCE_DESCRIPTOR_CLEANUP')


def snapshot_files(snapshot, app_packages=None, plugin_aliases=None):
    for name in snapshot['aliases']:
        package = name.rsplit('/', 1)[-1]
        require(app_packages is not None and package in app_packages
                and app_packages[package]['source'] == 'hosted', 'P15_SOURCE_ALIAS')
    for name, row in snapshot['unsafe'].items():
        match = re.fullmatch(r'(?:linux|windows)/flutter/ephemeral/\.plugin_symlinks/([a-z0-9_]+)', name)
        require(row['type'] == 'symlink' and match is not None and app_packages is not None
                and match[1] in app_packages and app_packages[match[1]]['source'] == 'hosted', 'P15_SOURCE_ALIAS')
        require(plugin_aliases is not None, 'P15_PLUGIN_BINDING_REQUIRED')
        require(False, 'P15_SOURCE_ALIAS')
    return S.files(snapshot)


def source_files(stage, *, app_packages=None, plugin_aliases=None, inventory=None):
    """Observe through anchored descriptors, then require the existing policy."""
    return snapshot_files(capture_source(stage, inventory, plugin_aliases), app_packages, plugin_aliases)


def source_catalogue():
    raw = I.read(ROOT / 'third_party/overmorrow-pub-source-observations-v1.json', 256 * 1024)
    require(I.sha(raw) == OBSERVATIONS_SHA, 'P15_SOURCE_OBSERVATION_CATALOGUE_CHANGED')
    value = I.document(raw)
    require(value['kind'] == 'p15f-controlled-pub-generated-source-closure'
            and value['admitted'] is False and value['pub_executed'] is False
            and value['regular_count'] == len(value['regular_files']) == 53,
            'P15_SOURCE_OBSERVATION_CATALOGUE_SCHEMA')
    return value


def localization_paths(expected):
    # Retain the previous acceptance conditions during diagnostic discovery.
    # The producer catalogue does not enlarge this set or grant output authority.
    result = {'lib/l10n/app_localizations.dart'}
    for name in expected:
        match = re.fullmatch(r'lib/l10n/app_([a-z]{2,3}(?:_[A-Za-z0-9]+)*)\.arb', name)
        if match:
            result.add('lib/l10n/app_localizations_' + match[1] + '.dart')
    return result


def source_differences(expected, actual, generated_sources=None):
    mutable = (set(GENERATED_PLATFORM_FILES) | localization_paths(expected)
               if generated_sources is None else set(generated_sources))
    return dict(missing=sorted(expected.keys() - actual.keys()),
        changed_original=sorted(n for n in expected.keys() & actual.keys()
            if expected[n] != actual[n] and n not in mutable),
        unknown=sorted(n for n in actual.keys() - expected.keys()
            if not n.startswith(('.dart_tool/', 'build/'))
            and n != 'test/volparossa/fixtures/products.json' and n not in mutable))


def observation_labels(expected):
    catalogue = source_catalogue()
    raw = I.read(ROOT / 'third_party/overmorrow-pub-metadata-observations-v1.json', 128 * 1024)
    require(I.sha(raw) == METADATA_OBSERVATIONS_SHA, 'P15_METADATA_OBSERVATION_CATALOGUE_CHANGED')
    metadata = I.document(raw)
    require(metadata['admitted'] is False and metadata['pub_executed'] is False
            and metadata['parent_catalogue_sha256'] == OBSERVATIONS_SHA,
            'P15_METADATA_OBSERVATION_CATALOGUE_SCHEMA')
    result = set(expected) | {row['path'] for row in catalogue['regular_files']}
    result.update(catalogue['desktop_aliases']['paths'])
    result.update(('.dart_tool/package_config.json', '.dart_tool/package_graph.json', '.dart_tool/version',
                   '.dart_tool/dartpad/web_plugin_registrant.dart', 'test/volparossa/fixtures/products.json'))
    # Parent names are reviewed labels too, never source admission.
    for name in list(result):
        result.update(str(p) for p in Path(name).parents if str(p) != '.')
    return result


def inventory_fingerprint(snapshot):
    return I.sha(I.canonical({kind: snapshot[kind] for kind in S.KINDS}))


class SourceAdmissionFailure(ValueError):
    def __init__(self, code, differences, expected, snapshot=None):
        super().__init__(code)
        self.inventory_sha256 = inventory_fingerprint(snapshot) if snapshot is not None else None
        labels = observation_labels(expected)
        self.source_rejection = dict(code=code, authorizes_outputs=False,
            **{key: [S.path_label(name, labels) for name in rows] for key, rows in differences.items()})


def diagnostic_projection(snapshot, labels):
    value = S.projection(snapshot, labels)
    if 'normalized_outputs' in snapshot:
        value['normalized_outputs'] = [dict(S.path_label(path, labels), **row)
                                       for path, row in snapshot['normalized_outputs'].items()]
        value['missing_catalogue_outputs'] = [S.path_label(path, labels)
                                              for path in snapshot['missing_catalogue_outputs']]
    return value


def source_diagnostic_report(snapshots, expected):
    require(set(snapshots) == {'before', 'after_tool_pub', 'after_app_pub', 'after_fixtures'},
            'P15_SOURCE_DIAGNOSTIC_CHECKPOINTS')
    labels = observation_labels(expected)
    def public_delta(before, after):
        changes = S.delta(before, after)
        return {key: [dict(S.path_label(row['path'], labels, row.get('after', row.get('before'))['kind']),
                     **{side: row[side] for side in ('before', 'after') if side in row}) for row in rows]
                for key, rows in changes.items()}
    actual = S.files(snapshots['after_fixtures'])
    differences = source_differences(expected, actual)
    return dict(schema=1, kind='p15-pub-source-observations', authorizes_outputs=False,
        original_source_sha256=I.sha(I.canonical(expected)), catalogue_sha256=OBSERVATIONS_SHA, metadata_catalogue_sha256=METADATA_OBSERVATIONS_SHA,
        inventories={name: diagnostic_projection(value, labels) for name, value in snapshots.items()},
        deltas=dict(tool_pub=public_delta(snapshots['before'], snapshots['after_tool_pub']),
                    app_pub=public_delta(snapshots['after_tool_pub'], snapshots['after_app_pub']),
                    fixtures=public_delta(snapshots['after_app_pub'], snapshots['after_fixtures'])),
        existing_source_policy_passed=not any(differences.values()) and not snapshots['after_fixtures']['unsafe'],
        existing_source_policy_rejections={key: [S.path_label(n, labels) for n in names]
                                           for key, names in differences.items()},
        unsafe_entries=len(snapshots['after_fixtures']['unsafe']),
        flutter_tests_reached=False, hook_authorization_reached=False, web_build_reached=False)


class DiagnosticComplete(Exception):
    """A completed measurement, never a successful candidate/source admission."""


def diagnostic_boundary(mode, snapshots, expected, verify_gate, details):
    if mode != DIAGNOSTIC_MODE:
        return
    try:
        receipt = verify_gate()
    except SourceAdmissionFailure as error:
        require(error.inventory_sha256 == inventory_fingerprint(snapshots['after_fixtures']),
                'P15_SOURCE_DIAGNOSTIC_RACE')
        details['source_rejection'] = error.source_rejection
    else:
        require(type(receipt) is dict and receipt.get('inventory_sha256') == inventory_fingerprint(snapshots['after_fixtures']),
                'P15_SOURCE_DIAGNOSTIC_RACE')
    details['source_diagnostic'] = source_diagnostic_report(snapshots, expected)
    details.pop('source_checkpoints', None)
    # Returning into the application-command loop is forbidden in this mode.
    raise DiagnosticComplete()


def recheck_source(stage, expected, app_packages, plugin_aliases=None, inventory=None, generated_sources=None):
    snapshot = capture_source(stage, inventory, plugin_aliases)
    actual = snapshot_files(snapshot, app_packages, plugin_aliases)
    generated = {}
    mutable = (set(GENERATED_PLATFORM_FILES) | localization_paths(expected)
               if generated_sources is None else set(generated_sources))
    differences = source_differences(expected, actual, generated_sources)
    if differences['missing'] or differences['changed_original']:
        raise SourceAdmissionFailure('P15_SOURCE_CHANGED', differences, expected, snapshot)
    for name, checksum in expected.items():
        # These exact tracked files are generated by the pinned SDK gen-l10n
        # from unchanged ARBs. No other application input may be replaced.
        require(name in actual and (actual[name] == checksum or name in mutable), 'P15_SOURCE_CHANGED')
        if actual[name] != checksum:
            generated[name] = actual[name]
    if differences['unknown']:
        raise SourceAdmissionFailure('P15_UNKNOWN_GENERATED_SOURCE', differences, expected, snapshot)
    return dict(original_files=len(expected), original_sha256=I.sha(I.canonical(expected)),
                inventory_sha256=inventory_fingerprint(snapshot),
                generated_localization_files=len(generated), generated_localization_sha256=I.sha(I.canonical(generated)))


def fixture_delta(before, after):
    """The sole trusted fixture action may add exactly its file and parents."""
    path = 'test/volparossa/fixtures/products.json'
    expected = {(path, 'files')}
    expected.update((str(parent), 'directories') for parent in Path(path).parents
                    if str(parent) != '.' and str(parent) not in before['directories'])
    changes = S.delta(before, after)
    require(not changes['changed'] and not changes['missing']
            and {(row['path'], row['after']['kind']) for row in changes['added']} == expected,
            'P15_FIXTURE_OUTPUT_CLOSURE')
    return inventory_fingerprint(after)


def seal_app_sources(stage, app_packages, plugin_aliases=None, inventory=None):
    # Generated compilation state is not source authority. All source and
    # platform-generator outputs are sealed after the sole app-pub operation.
    return {name: digest for name, digest in source_files(stage, app_packages=app_packages,
            plugin_aliases=plugin_aliases, inventory=inventory).items()
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


def execute(*, mode=MODE):
    helper, platform = guards(mode=mode)
    PUBLIC.mkdir(mode=0o700)
    INPUT.mkdir(mode=0o700)
    private = INPUT / 'runtime-private'
    private.mkdir(mode=0o700)
    installed = attempted = runtime_started = success = compiled = tests_passed = False
    diagnostics_complete = False
    source_inventory = None
    source_snapshots = {}
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
        source_inventory = S.Inventory(STAGE)
        source_snapshots['before'] = capture_source(STAGE, source_inventory)
        expected_source = snapshot_files(source_snapshots['before'])
        require(I.sha(I.canonical(expected_source)) == ORIGINAL_SOURCE_SHA, 'P15_ORIGINAL_SOURCE_INVENTORY_CHANGED')
        if mode == DIAGNOSTIC_MODE:
            details['source_checkpoints'] = dict(before=S.projection(source_snapshots['before'], observation_labels(expected_source)))
        stage_git = source_inventory.git_binding()
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
        prepared_authorization = None
        prepared_final_fingerprint = None
        def source_checkpoint(name, aliases=None):
            source_snapshots[name] = capture_source(STAGE, source_inventory, aliases)
            if mode == DIAGNOSTIC_MODE:
                if name in ('after_app_pub', 'after_fixtures'):
                    candidates = {row['path'] for row in source_catalogue()['regular_files']}
                    selected = sorted(candidates & source_snapshots[name]['files'].keys())
                    source_snapshots[name]['normalized_outputs'] = source_inventory.normalized(
                        source_snapshots[name], selected, dict(sdk=str(sdk), app=str(STAGE))) if selected else {}
                    source_snapshots[name]['missing_catalogue_outputs'] = sorted(candidates - set(selected))
                details.setdefault('source_checkpoints', {})[name] = diagnostic_projection(
                    source_snapshots[name], observation_labels(expected_source))
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
            require(stage_git == source_inventory.git_binding(), 'P15_STAGE_GIT_CHANGED')
            details['source'] = recheck_source(STAGE, expected_source, app_packages,
                plugin_aliases if sealed_app is not None else None, source_inventory,
                prepared_authorization if prepared_authorization is not None else frozenset() if mode == MODE else None)
            if prepared_authorization is not None and not details.get('hook_authorizations'):
                require(prepared_final_fingerprint is not None and details['source']['inventory_sha256']
                        == prepared_final_fingerprint, 'P15_PREPARATION_SOURCE_CHANGED')
            if sealed_app is not None:
                require(seal_app_sources(STAGE, app_packages, plugin_aliases, source_inventory) == sealed_app,
                        'P15_GENERATED_APP_SOURCE_CHANGED')
            return details['source']
        phase = 'p15-tool-pub-offline'
        verify_inputs()
        H.run(phase, O.sandbox(tool_command(), mode='compile'), 180,
              env=O.environment(), memory=O.FLUTTER_MEMORY)
        tool_ready = True
        source_checkpoint('after_tool_pub')
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
                source_checkpoint('after_app_pub', plugin_aliases)
                if mode == MODE:
                    # The entire successful preparation closure is checked
                    # before any generated executable source can be consumed.
                    policy_raw = I.read(ROOT / 'third_party/overmorrow-pub-outputs-v1.json', 128 * 1024)
                    require(I.sha(policy_raw) == PUB_OUTPUTS_SHA, 'P15_PUB_OUTPUT_AUTHORIZATION_CHANGED')
                    policy = I.document(policy_raw)
                    output_validator = module('prepare_hosted_overmorrow_pub_outputs')
                    metadata_validator = module('prepare_hosted_overmorrow_pub_metadata')
                    details['pub_outputs'] = output_validator.validate(source_inventory,
                        source_snapshots['after_app_pub'], source_snapshots['before'], policy,
                        dict(app=str(STAGE), sdk=str(sdk)), metadata_validator,
                        dict(manifest=I.read(sdk / 'bin/cache/flutter.version.json', 4096),
                             target=I.read(sdk / 'packages/flutter_tools/lib/src/build_system/targets/localizations.dart', 16384)))
                    details['pub_output_authorization_sha256'] = PUB_OUTPUTS_SHA
                    prepared_authorization = frozenset(policy['generated_sources'])
                sealed_app = seal_app_sources(STAGE, app_packages, plugin_aliases, source_inventory)
                fixture = STAGE / 'test/volparossa/fixtures/products.json'
                fixture.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                H.run('p15-test-fixtures', O.sandbox([str(H.NODE),
                    str(ROOT / 'integrations/overmorrow/test-fixtures.mjs'), str(fixture)], mode='compile'),
                    30, env=O.environment())
                source_checkpoint('after_fixtures', plugin_aliases)
                if mode == MODE:
                    prepared_final_fingerprint = fixture_delta(source_snapshots['after_app_pub'],
                                                                source_snapshots['after_fixtures'])
                if mode == DIAGNOSTIC_MODE:
                    # The real source gate still runs. Only its measured
                    # rejection is caught here; no hook/test/build follows.
                    require(stage_git == source_inventory.git_binding(), 'P15_STAGE_GIT_CHANGED')
                    diagnostic_boundary(mode, source_snapshots, expected_source,
                                        lambda: verify_inputs(with_config=True), details)
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
    except DiagnosticComplete:
        report = details.get('source_diagnostic')
        if (mode == DIAGNOSTIC_MODE and not compiled and not tests_passed
                and 'hook_authorizations' not in details and type(report) is dict
                and report.get('authorizes_outputs') is False
                and report.get('original_source_sha256') == ORIGINAL_SOURCE_SHA
                and set(report.get('inventories', {})) == {'before', 'after_tool_pub', 'after_app_pub', 'after_fixtures'}):
            phase = 'source-diagnostic-complete'
            diagnostics_complete = True
        else:
            failure = dict(category='ValueError', code='P15_DIAGNOSTIC_EXECUTION_SCOPE')
    except BaseException as error:
        code = str(error)
        failure = dict(category=type(error).__name__,
            code=code if re.fullmatch(r'[A-Z0-9_]{1,100}', code) else 'P15_OPERATION_FAILED')
        if isinstance(error, SDKGitFailure):
            failure['sdk_git'] = error.sdk_git_failure
        if isinstance(error, SourceAdmissionFailure):
            details['source_rejection'] = error.source_rejection
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
            inventory_closed = source_inventory.close() if source_inventory is not None else True
            details['source_inventory_descriptors_closed'] = inventory_closed
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed) if installed or attempted else dict(complete=True)
            drained = H.DRAIN_CONFIRMED and cleaning['complete'] and inventory_closed
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
            diagnostics_complete = diagnostics_complete and all(cleanup.values()) and cleanup_error is None
            record(PUBLIC / 'cleanup.json', dict(schema=1, admitted=False, **cleanup, failure=cleanup_error))
            record(PUBLIC / 'result.json', dict(schema=1,
                kind='p15-overmorrow-pub-diagnostic' if mode == DIAGNOSTIC_MODE else 'p15-overmorrow-first-candidate',
                mode=mode, diagnostics_complete=diagnostics_complete, candidate_success=success, admitted=False,
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
    require(success or mode == DIAGNOSTIC_MODE and diagnostics_complete, 'P15_CANDIDATE_FAILED')


def main():
    require(sys.argv[1:] == [], 'P15_NO_ARGUMENTS')
    os.umask(0o077)
    execute(mode=selected_mode())


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print('P15_CANDIDATE_FAILED; inspect closed candidate metadata', file=sys.stderr)
        sys.exit(1)
