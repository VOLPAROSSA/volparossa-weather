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

    def test_only_exact_app_version_plugin_alias_is_accepted(self):
        self.file('pubspec.lock')
        root = self.base / 'linux/flutter/ephemeral/.plugin_symlinks'
        root.mkdir(mode=0o700, parents=True)
        link = root / 'plugin'
        link.symlink_to('/state/pub-cache/hosted/pub.dev/plugin-1.0.0')
        app = dict(plugin=dict(source='hosted', version='1.0.0'))
        W['source_files'](self.base, app_packages=app)
        for target in ('/state/pub-cache/hosted/pub.dev/plugin-2.0.0', '/private', '../plugin-1.0.0'):
            link.unlink(); link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'P15_PLUGIN_SYMLINK_TARGET'):
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

    def failed_attempt(self, *, drain=True, cleanup_rejected=False):
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
        apt = SimpleNamespace(installed_inventory=Mock(side_effect=ValueError('TEST_PROVISIONING_REJECTED')))
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
                W['execute']()
        result = json.loads((public/'result.json').read_text())
        receipt = json.loads((public/'cleanup.json').read_text())
        self.assertFalse(result['success'])
        self.assertFalse(result['compiled'])
        self.assertEqual(result['failure']['code'], 'TEST_PROVISIONING_REJECTED')
        return result, receipt, inputs

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


if __name__ == '__main__':
    unittest.main()
