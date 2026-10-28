# SPDX-License-Identifier: GPL-3.0-only
"""Inert P15 lifecycle/input checks. Never start Dart, Flutter or a sandbox."""
import json
import os
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
W = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_candidate.py'))
G = W['execute'].__globals__
I, H, O = W['I'], W['H'], W['O']


class CandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def file(self, name, raw=b'original'):
        path = self.base / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def test_only_explicit_offline_commands_and_original_full_font_build(self):
        self.assertEqual(W['tool_command'](), [str(O.SDK / 'bin/cache/dart-sdk/bin/dart'),
            '--suppress-analytics', 'pub', '--directory', str(O.SDK / 'packages/flutter_tools'),
            'get', '--offline', '--enforce-lockfile', '--no-precompile', '--no-example'])
        self.assertIn('--offline', W['command']('dependencies-offline'))
        self.assertEqual(W['command']('build')[-len(O.build_contract()['source_web_arguments']()):],
                         O.build_contract()['source_web_arguments']())
        for action in ('dependencies', 'version', 'upgrade', 'run'):
            with self.assertRaisesRegex(ValueError, 'P15_OFFLINE_ACTION'):
                W['command'](action)

    def test_original_application_input_cannot_change(self):
        self.file('pubspec.lock')
        expected = W['source_files'](self.base)
        self.file('pubspec.lock', b'changed')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_CHANGED'):
            W['recheck_source'](self.base, expected, {})

    def test_l10n_names_derive_from_bound_arbs_and_seal_after_pub(self):
        self.file('lib/l10n/app_en.arb', b'{}')
        self.file('lib/l10n/app_localizations_en.dart')
        expected = W['source_files'](self.base)
        self.file('lib/l10n/app_localizations_en.dart', b'generated')
        W['recheck_source'](self.base, expected, {})
        sealed = W['seal_app_sources'](self.base, {})
        self.file('lib/l10n/app_localizations_en.dart', b'different')
        self.assertNotEqual(W['seal_app_sources'](self.base, {}), sealed)
        self.file('lib/l10n/app_localizations_fake.dart', b'unknown')
        with self.assertRaisesRegex(ValueError, 'P15_UNKNOWN_GENERATED_SOURCE'):
            W['recheck_source'](self.base, expected, {})

    def test_unknown_platform_source_is_rejected(self):
        self.file('lib/main.dart')
        expected = W['source_files'](self.base)
        self.file('linux/flutter/arbitrary.cc')
        with self.assertRaisesRegex(ValueError, 'P15_UNKNOWN_GENERATED_SOURCE'):
            W['recheck_source'](self.base, expected, {})

    def test_plugin_alias_requires_a_separate_authenticated_binding(self):
        self.file('pubspec.lock')
        root = self.base / 'linux/flutter/ephemeral/.plugin_symlinks'
        root.mkdir(mode=0o700, parents=True)
        link = root / 'plugin'
        link.symlink_to('/state/pub-cache/hosted/pub.dev/plugin-1.0.0')
        app = dict(plugin=dict(source='hosted', version='1.0.0'))
        for target in ('/state/pub-cache/hosted/pub.dev/plugin-1.0.0/',
                       '/state/pub-cache/hosted/pub.dev/plugin-2.0.0', '/private', '../plugin-1.0.0'):
            link.unlink(); link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_BINDING_REQUIRED'):
                W['source_files'](self.base, app_packages=app)

    def test_source_hardlinks_and_undeclared_aliases_fail_closed(self):
        path = self.file('lib/main.dart')
        os.link(path, self.base / 'second.dart')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_FILE'):
            W['source_files'](self.base)
        (self.base / 'second.dart').unlink()
        (self.base / 'lib/unknown.dart').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'P15_SOURCE_ALIAS'):
            W['source_files'](self.base)

    def test_stage_scan_enforces_entry_budget_incrementally(self):
        for name in ('one', 'two', 'three', 'four'):
            self.file(name)
        with patch.dict(G, MAX_STAGE_ENTRIES=3), \
                self.assertRaisesRegex(ValueError, 'P15_STAGE_ENTRY_BOUND'):
            W['source_files'](self.base)

    def test_cleanup_checks_root_identity_before_deleting_anything(self):
        path = self.base / 'owned'
        path.mkdir(mode=0o700)
        marker = path / 'keep'
        marker.write_text('unique evidence')
        info = path.stat()
        with self.assertRaisesRegex(ValueError, 'P15_CLEANUP_IDENTITY'):
            W['cleanup_owned'](path, (info.st_dev, info.st_ino + 1))
        self.assertTrue(marker.exists())
        W['cleanup_owned'](path, (info.st_dev, info.st_ino))
        self.assertFalse(path.exists())

    def test_unowned_output_is_preserved(self):
        path = self.base / 'unexpected'
        path.mkdir()
        with self.assertRaisesRegex(ValueError, 'P15_UNOWNED_OUTPUT'):
            W['cleanup_owned'](path, None)
        self.assertTrue(path.exists())

    def test_diagnostic_projection_contains_no_raw_output_or_paths(self):
        path = self.file('p15-tool-pub-offline.log', b'Error: secret /private/token\n')
        rows = [dict(name='p15-tool-pub-offline', exit_status=1, returned=True, process_drain_confirmed=True)]
        with patch.object(H, 'OUTPUT', self.base), patch.object(H, 'LOGS', rows):
            value = W['diagnostics']()
        raw = json.dumps(value)
        self.assertNotIn('secret', raw)
        self.assertNotIn('/private', raw)
        self.assertTrue(value[0]['diagnostic_categories']['compiler'])

    def failed_attempt(self, *, drain=True, cleanup_rejected=False, failure=None, mode=W['MODE'], expected_code=None):
        root = self.base / 'repo'
        build = root / 'build'
        build.mkdir(mode=0o700, parents=True)
        for name in W['OWNED_SOURCE']:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixed source')
            path.chmod(0o600)
        public = build / 'p15-overmorrow-candidate-public'
        inputs = build / 'hosted-overmorrow-input-candidate'
        helper = SimpleNamespace(DRAIN_CONFIRMED=True)
        failure = failure or ValueError('TEST_PROVISIONING_REJECTED')
        apt = SimpleNamespace(installed_inventory=Mock(side_effect=failure))
        cleanup = I.cleanup_candidate
        if cleanup_rejected:
            cleanup = Mock(side_effect=ValueError('INSTALLER_CLEANUP_UNCONFIRMED'))
        with patch.dict(G, ROOT=root, INPUT=inputs, PUBLIC=public, STAGE=build/'stage', DEPLOY=build/'deploy',
                        guards=Mock(return_value=(helper, {})), module=Mock(return_value=apt)), \
                patch.object(I, 'ROOT', root), patch.object(I, 'cleanup_candidate', cleanup), \
                patch.object(I, 'load_package_inputs', return_value={}), \
                patch.object(H, 'DRAIN_CONFIRMED', drain), patch.object(H, 'LOGS', []), \
                patch.dict(os.environ, GITHUB_SHA='a'*40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1'):
            with self.assertRaisesRegex(ValueError, 'P15_CANDIDATE_FAILED'):
                W['execute'](mode=mode)
        result = json.loads((public/'result.json').read_text())
        receipt = json.loads((public/'cleanup.json').read_text())
        self.assertFalse(result['success'])
        self.assertFalse(result['compiled'])
        self.assertEqual(result['failure']['code'], str(failure) if expected_code is None else expected_code)
        return result, receipt, inputs

    def test_finally_retains_closed_typed_git_failure_without_private_output(self):
        observation = dict(command='diff', category='exit-status', exit_status=1,
                           output_bytes=0, output_sha256=I.sha(b''))
        result, receipt, _ = self.failed_attempt(failure=W['SDKGitFailure'](observation))
        self.assertEqual(result['failure']['sdk_git'], observation)
        self.assertTrue(receipt['private_inputs_absent'])

    def test_git_proxy_preserves_checks_timeouts_and_uses_explicit_patch_comparison(self):
        helper = H.policy_helper()
        result = (0, b'private source data')
        helper.process = Mock(return_value=result)
        receipts = []
        checked = W['SDKGitChecks'](helper, receipts)
        for name, argv, seconds in checked.expected:
            expected = list(argv)
            if name == 'diff':
                offset = expected.index('--quiet')
                expected[offset:offset + 1] = ['--patch', '--no-ext-diff', '--no-textconv']
                result = (0, b'')
                helper.process.return_value = result
            self.assertIs(checked.process(argv, seconds), result)
            helper.process.assert_called_with(expected, seconds)
            self.assertEqual(receipts[-1]['command'], name)
        self.assertNotIn('private', json.dumps(receipts))
        with self.assertRaisesRegex(ValueError, 'P15_SDK_GIT_CALL_COUNT'):
            checked.process(checked.expected[0][1], 10)

    def test_each_git_failure_projects_only_validated_typed_fields(self):
        for index in range(3):
            for category, status in (('exit-status', 1), ('exit-status', 128),
                                     ('deadline', None), ('output-bound', None)):
                with self.subTest(command=index, category=category, status=status):
                    helper = H.policy_helper()
                    raw = b'secret token and /private/path and ENV=value'
                    error = helper.CommandFailure(category, status, raw)
                    helper.process = Mock(side_effect=error)
                    receipts = []
                    checked = W['SDKGitChecks'](helper, receipts)
                    checked.index = index
                    _, argv, seconds = checked.expected[index]
                    with self.assertRaises(W['SDKGitFailure']) as caught:
                        checked.process(argv, seconds)
                    value = caught.exception.sdk_git_failure
                    self.assertEqual(value, dict(command=checked.expected[index][0],
                        category=category, exit_status=status, output_bytes=len(raw), output_sha256=I.sha(raw)))
                    projected = json.dumps([value, receipts])
                    for private in ('secret', '/private', 'ENV', 'token'):
                        self.assertNotIn(private, projected)

    def test_git_proxy_rejects_unknown_calls_timeouts_diagnostics_and_excess_receipts(self):
        helper = H.policy_helper()
        helper.process = Mock()
        for altered in ('argv', 'timeout', 'receipts', 'schema'):
            with self.subTest(altered=altered):
                checked = W['SDKGitChecks'](helper, [{}] * (64 if altered == 'receipts' else 0))
                _, argv, seconds = checked.expected[0]
                if altered == 'argv': argv = argv + ['--untrusted']
                if altered == 'timeout': seconds += 1
                error = helper.CommandFailure('exit-status', True, b'private')
                helper.process.side_effect = error
                with self.assertRaisesRegex(ValueError, 'P15_SDK_GIT_'):
                    checked.process(argv, seconds)

    def test_even_whitespace_or_private_patch_output_is_rejected_without_export(self):
        for raw in (b'\n', b'diff --git a/private/token b/private/token\nsecret\n'):
            helper = H.policy_helper()
            helper.process = Mock(return_value=(0, raw))
            checked = W['SDKGitChecks'](helper, [])
            checked.index = 1
            _, argv, seconds = checked.expected[1]
            with self.assertRaises(W['SDKGitFailure']) as caught:
                checked.process(argv, seconds)
            value = caught.exception.sdk_git_failure
            self.assertEqual(value['category'], 'content-difference')
            self.assertEqual(value['output_sha256'], I.sha(raw))
            self.assertNotIn('private', json.dumps(value))
            self.assertNotIn('secret', json.dumps(value))

    def test_actual_finally_cleans_early_failure_and_projects_original_failure(self):
        result, receipt, inputs = self.failed_attempt()
        self.assertIsNone(result['cleanup_failure'])
        self.assertTrue(receipt['private_inputs_absent'])
        self.assertFalse(inputs.exists())

    def test_actual_finally_retains_private_recovery_if_cleanup_rejected(self):
        result, receipt, inputs = self.failed_attempt(cleanup_rejected=True)
        self.assertEqual(result['cleanup_failure']['code'], 'P15_CLEANUP_UNPROVEN')
        self.assertFalse(receipt['private_inputs_absent'])
        self.assertTrue(inputs.exists())

    def test_actual_finally_never_deletes_undrained_state(self):
        result, receipt, inputs = self.failed_attempt(drain=False)
        self.assertFalse(receipt['process_drain_confirmed'])
        self.assertTrue(inputs.exists())

    def test_diagnostic_early_failure_is_not_a_completed_diagnostic_or_candidate(self):
        result, receipt, _ = self.failed_attempt(mode=W['DIAGNOSTIC_MODE'])
        self.assertEqual(result['kind'], 'p15-overmorrow-pub-diagnostic')
        self.assertFalse(result['diagnostics_complete'])
        self.assertFalse(result['candidate_success'])
        self.assertFalse(result['compiled'])
        self.assertTrue(receipt['private_inputs_absent'])

    def test_incomplete_diagnostic_sentinel_cannot_claim_success_and_finally_still_cleans(self):
        result, receipt, _ = self.failed_attempt(mode=W['DIAGNOSTIC_MODE'], failure=W['DiagnosticComplete'](),
                                                expected_code='P15_DIAGNOSTIC_EXECUTION_SCOPE')
        self.assertFalse(result['diagnostics_complete'])
        self.assertFalse(result['candidate_success'])
        self.assertTrue(receipt['private_inputs_absent'])

    def test_source_failure_reports_all_rejected_paths_without_admitting_catalogue_labels(self):
        self.file('pubspec.yaml', b'original')
        expected = W['source_files'](self.base)
        names = ['ios/Flutter/ephemeral/flutter_lldbinit',
                 'ios/Flutter/ephemeral/flutter_lldb_helper.py',
                 'macos/Flutter/ephemeral/Flutter-Generated.xcconfig',
                 'macos/Flutter/ephemeral/flutter_export_environment.sh',
                 'private-secret-name.txt']
        for name in names:
            self.file(name)
        with self.assertRaises(W['SourceAdmissionFailure']) as caught:
            W['recheck_source'](self.base, expected, {})
        row = caught.exception.source_rejection
        self.assertEqual(str(caught.exception), 'P15_UNKNOWN_GENERATED_SOURCE')
        self.assertEqual(len(row['unknown']), 5)
        self.assertFalse(row['authorizes_outputs'])
        encoded = json.dumps(row)
        self.assertNotIn('private-secret-name', encoded)
        self.assertNotIn(str(self.base), encoded)
        self.assertEqual({x['path'] for x in row['unknown'] if 'path' in x}, set(names[:-1]))

    def test_complete_diagnostic_boundary_cannot_fall_through_to_application_actions(self):
        self.file('pubspec.yaml', b'original')
        with W['S'].Inventory(self.base) as inventory:
            before = inventory.capture()
            expected = W['S'].files(before)
            self.file('macos/Flutter/ephemeral/Flutter-Generated.xcconfig', b'generated')
            app = inventory.capture()
            self.file('test/volparossa/fixtures/products.json', b'{}')
            final = inventory.capture()
            snapshots = dict(before=before, after_tool_pub=before, after_app_pub=app, after_fixtures=final)
            details, trace = {}, []
            def gate():
                trace.append('existing-source-gate')
                W['recheck_source'](self.base, expected, {}, inventory=inventory)
            def tail():
                W['diagnostic_boundary'](W['DIAGNOSTIC_MODE'], snapshots, expected, gate, details)
                trace.extend(('hook-authorization', 'flutter-tests', 'web-build'))
            with self.assertRaises(W['DiagnosticComplete']):
                tail()
        self.assertEqual(trace, ['existing-source-gate'])
        report = details['source_diagnostic']
        self.assertFalse(report['authorizes_outputs'])
        self.assertFalse(report['existing_source_policy_passed'])
        self.assertEqual(len(report['existing_source_policy_rejections']['unknown']), 1)
        self.assertEqual({x['path'] for x in report['deltas']['fixtures']['added'] if 'path' in x},
                         {'test/volparossa/fixtures/products.json', 'test/volparossa/fixtures',
                          'test/volparossa', 'test'})
        self.assertFalse(report['flutter_tests_reached'])
        self.assertFalse(report['hook_authorization_reached'])
        self.assertFalse(report['web_build_reached'])

    def test_diagnostic_gate_cannot_swallow_an_independent_sandbox_or_integrity_failure(self):
        details = {}
        gate = Mock(side_effect=ValueError('P15_RUNTIME_CHANGED'))
        with self.assertRaisesRegex(ValueError, 'P15_RUNTIME_CHANGED'):
            W['diagnostic_boundary'](W['DIAGNOSTIC_MODE'], {}, {}, gate, details)
        self.assertNotIn('source_diagnostic', details)
        W['diagnostic_boundary'](W['MODE'], {}, {}, gate, details)
        self.assertEqual(gate.call_count, 1)

    def test_diagnostic_gate_cannot_report_a_stale_smaller_unknown_set(self):
        self.file('pubspec.yaml', b'original')
        with W['S'].Inventory(self.base) as inventory:
            before = inventory.capture()
            expected = W['S'].files(before)
            self.file('first-unknown.txt')
            observed = inventory.capture()
            snapshots = dict(before=before, after_tool_pub=before,
                             after_app_pub=observed, after_fixtures=observed)
            details = {}
            def gate():
                self.file('second-unknown.txt')
                return W['recheck_source'](self.base, expected, {}, inventory=inventory)
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIAGNOSTIC_RACE'):
                W['diagnostic_boundary'](W['DIAGNOSTIC_MODE'], snapshots, expected, gate, details)
            self.assertNotIn('source_diagnostic', details)

    def test_diagnostic_successful_gate_also_binds_the_exact_observed_inventory(self):
        self.file('pubspec.yaml', b'original')
        with W['S'].Inventory(self.base) as inventory:
            observed = inventory.capture()
            expected = W['S'].files(observed)
            snapshots = {key: observed for key in ('before', 'after_tool_pub', 'after_app_pub', 'after_fixtures')}
            details = {}
            with self.assertRaises(W['DiagnosticComplete']):
                W['diagnostic_boundary'](W['DIAGNOSTIC_MODE'], snapshots, expected,
                    lambda: W['recheck_source'](self.base, expected, {}, inventory=inventory), details)
            self.assertTrue(details['source_diagnostic']['existing_source_policy_passed'])
            with self.assertRaisesRegex(ValueError, 'P15_SOURCE_DIAGNOSTIC_RACE'):
                W['diagnostic_boundary'](W['DIAGNOSTIC_MODE'], snapshots, expected,
                    lambda: dict(inventory_sha256='0' * 64), {})

    def test_fixture_action_has_a_closed_file_and_directory_delta(self):
        self.file('pubspec.yaml')
        with W['S'].Inventory(self.base) as inventory:
            before = inventory.capture()
            self.file('test/volparossa/fixtures/products.json', b'{}')
            after = inventory.capture()
            self.assertEqual(W['fixture_delta'](before, after), W['inventory_fingerprint'](after))
            self.file('.dart_tool/unknown.dart')
            with self.assertRaisesRegex(ValueError, 'P15_FIXTURE_OUTPUT_CLOSURE'):
                W['fixture_delta'](before, inventory.capture())

    def test_fixture_delta_rejects_changed_original_and_unknown_empty_directory(self):
        self.file('pubspec.yaml')
        with W['S'].Inventory(self.base) as inventory:
            before = inventory.capture()
            self.file('test/volparossa/fixtures/products.json', b'{}')
            self.file('pubspec.yaml', b'changed')
            with self.assertRaisesRegex(ValueError, 'P15_FIXTURE_OUTPUT_CLOSURE'):
                W['fixture_delta'](before, inventory.capture())
            self.file('pubspec.yaml')
            (self.base / 'build/unexpected').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'P15_FIXTURE_OUTPUT_CLOSURE'):
                W['fixture_delta'](before, inventory.capture())

    def test_reviewed_source_set_replaces_old_unreachable_allowances(self):
        self.file('pubspec.yaml')
        expected = W['source_files'](self.base)
        name = 'ios/Flutter/ephemeral/flutter_lldbinit'
        self.file(name)
        W['recheck_source'](self.base, expected, {}, generated_sources={name})
        self.file('.flutter-plugins', b'old unrestricted name')
        with self.assertRaisesRegex(ValueError, 'P15_UNKNOWN_GENERATED_SOURCE'):
            W['recheck_source'](self.base, expected, {}, generated_sources={name})

    def test_exact_explicit_workflow_modes_only(self):
        event = self.file('event.json', b'{}')
        with patch.dict(os.environ, GITHUB_EVENT_PATH=str(event)):
            for mode in (W['MODE'], W['DIAGNOSTIC_MODE']):
                event.write_text(json.dumps(dict(inputs=dict(input_mode=mode))))
                self.assertEqual(W['selected_mode'](), mode)
            for inputs in (dict(input_mode='allow-unknown'), dict(input_mode=W['MODE'], extra=True), {}):
                event.write_text(json.dumps(dict(inputs=inputs)))
                with self.assertRaisesRegex(ValueError, 'P15_EXPLICIT_MODE'):
                    W['selected_mode']()

    def test_workflow_runs_only_one_manual_bounded_candidate_and_exports_two_json_files(self):
        workflow = (ROOT / '.github/workflows/hosted-overmorrow.yml').read_text()
        job = workflow.split('\n  source-candidate:\n', 1)[1]
        self.assertIn("github.event_name == 'workflow_dispatch'", job)
        self.assertIn("input_mode == 'source-candidate-build'", job)
        self.assertIn('timeout-minutes: 45', job)
        self.assertIn('test "$GITHUB_RUN_ATTEMPT" = 1', job)
        self.assertIn('timeout --signal=TERM --kill-after=90s 2400s', job)
        self.assertNotIn('secrets.', job)
        exports = job.split('path: |\n', 1)[1].splitlines()
        self.assertEqual([line.strip() for line in exports if line.strip()], [
            'build/p15-overmorrow-candidate-public/result.json',
            'build/p15-overmorrow-candidate-public/cleanup.json'])


class SDKGitBehaviorTests(unittest.TestCase):
    """Real inert Git fixtures; never execute SDK or package code."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sdk = Path(temporary.name)
        self.helper = H.policy_helper()
        self.git = ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', '-C', str(self.sdk)]
        self.helper.process(self.git + ['init', '--quiet', '--template='], 10)
        self.source = self.sdk / 'source.txt'
        self.source.write_bytes(b'original SDK fixture\n')
        self.source.chmod(0o600)
        self.helper.process(self.git + ['add', 'source.txt'], 10)
        self.helper.process(self.git + ['commit', '--quiet', '-m', 'Inert fixture'], 10)
        _, head = self.helper.process(self.git + ['rev-parse', 'HEAD'], 10)
        self.lock = self.sdk / 'pubspec.lock'
        self.lock.write_bytes(b'original lock')
        self.pin = dict(flutter_commit=head.decode().strip(), pubspec_lock_sha256=I.sha(self.lock.read_bytes()))

    def verify(self, *, expected_commit=None):
        pin = dict(self.pin)
        if expected_commit is not None:
            pin['flutter_commit'] = expected_commit
        receipts = []
        with patch.object(O, 'SDK', self.sdk), patch.object(O, 'STAGE', self.sdk), \
                patch.object(O, 'build_contract', return_value={'SDK_FILES': {}}), \
                patch.object(O, 'sdk_inventory', return_value={'fixture': True}):
            checked = W['SDKGitChecks'](self.helper, receipts)
            O.verify_phase_inputs(checked, pin)
            self.assertEqual(checked.index, 3)
        return receipts

    def index(self):
        return I.sha((self.sdk / '.git/index').read_bytes())

    def test_clean_git_fixture_with_stale_stat_is_accepted_without_index_write(self):
        before = self.index()
        self.source.write_bytes(self.source.read_bytes())  # new stat, identical bytes
        self.assertTrue(all(row['success'] for row in self.verify()))
        self.assertEqual(self.index(), before)

    def test_changed_source_bytes_are_rejected_without_index_write(self):
        before = self.index()
        self.source.write_bytes(b'changed SDK fixture!\n')
        with self.assertRaises(W['SDKGitFailure']) as caught:
            self.verify()
        self.assertEqual(caught.exception.sdk_git_failure['command'], 'diff')
        self.assertEqual(caught.exception.sdk_git_failure['category'], 'content-difference')
        self.assertEqual(caught.exception.sdk_git_failure['exit_status'], 0)
        self.assertEqual(self.index(), before)

    def test_changed_executable_bit_is_rejected(self):
        before = self.index()
        self.source.chmod(0o700)
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()
        self.assertEqual(self.index(), before)

    def test_deleted_source_is_rejected(self):
        self.source.unlink()
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()

    def test_same_size_and_mtime_source_change_is_rejected(self):
        info = self.source.stat()
        before = self.index()
        raw = self.source.read_bytes()
        self.source.write_bytes(b'X' + raw[1:])
        os.utime(self.source, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()
        self.assertEqual(self.index(), before)

    def test_binary_source_change_is_rejected(self):
        self.source.write_bytes(b'\x00changed binary')
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()

    def test_source_type_change_is_rejected(self):
        self.source.unlink()
        self.source.symlink_to('/unopened-private-target')
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()

    def test_source_rename_is_rejected(self):
        self.source.rename(self.sdk / 'renamed.txt')
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()

    def test_staged_new_source_is_rejected_without_index_write(self):
        added = self.sdk / 'added.txt'
        added.write_bytes(b'new source')
        self.helper.process(self.git + ['add', 'added.txt'], 10)
        before = self.index()
        with self.assertRaises(W['SDKGitFailure']):
            self.verify()
        self.assertEqual(self.index(), before)

    def test_wrong_head_and_application_lock_are_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'FLUTTER_COMMIT_CHANGED'):
            self.verify(expected_commit='0' * 40)
        self.lock.write_bytes(b'modified lock')
        with self.assertRaisesRegex(ValueError, 'DEPENDENCY_LOCK_CHANGED'):
            self.verify()

    def test_unknown_bootstrap_file_is_still_rejected(self):
        bootstrap = self.sdk / 'bin/internal/unreviewed.sh'
        bootstrap.parent.mkdir(mode=0o700, parents=True)
        bootstrap.write_bytes(b'never executed')
        with self.assertRaisesRegex(ValueError, 'UNREVIEWED_FLUTTER_BOOTSTRAP'):
            self.verify()

    def test_unresolved_git_head_has_typed_command_failure(self):
        (self.sdk / '.git/HEAD').write_bytes(b'ref: refs/heads/absent\n')
        with self.assertRaises(W['SDKGitFailure']) as caught:
            self.verify()
        self.assertEqual(caught.exception.sdk_git_failure['command'], 'rev-parse')
        self.assertEqual(caught.exception.sdk_git_failure['exit_status'], 128)


if __name__ == '__main__':
    unittest.main()
