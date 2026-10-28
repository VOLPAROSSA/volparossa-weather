# SPDX-License-Identifier: GPL-3.0-only
"""Inert negative tests: no compiler, npm, APT, browser or namespace execution."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
C = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_drizzli_candidate.py'))
I = SimpleNamespace(**runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_inputs.py')))
G = C['build'].__globals__


class CandidateBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)

    def put(self, path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        for parent in path.parents:
            if parent == self.root.parent:
                break
            parent.chmod(0o700)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)

    def test_only_explicit_manual_event_reaches_existing_runner_guard(self):
        event = self.root / 'event.json'
        helper = SimpleNamespace(process=Mock())
        harness = SimpleNamespace(guards=Mock(return_value=(helper, {})))
        inputs = SimpleNamespace(hosted_guard=Mock(), read=I.read, document=I.document)
        for event_name, mode in (('push', C['MODE']), ('workflow_dispatch', 'historical-v1'),
                ('workflow_dispatch', ''), ('pull_request', C['MODE'])):
            self.put(event, {'inputs': {'input_mode': mode}})
            with self.subTest(event=event_name, mode=mode), patch.dict(os.environ,
                    GITHUB_EVENT_NAME=event_name, GITHUB_EVENT_PATH=str(event)):
                with self.assertRaisesRegex(ValueError, 'P14_EXPLICIT_MANUAL_MODE_REQUIRED'):
                    C['guard'](inputs, harness)
        harness.guards.assert_not_called()
        self.put(event, {'inputs': {'input_mode': C['MODE']}})
        with patch.dict(os.environ, GITHUB_EVENT_NAME='workflow_dispatch',
                GITHUB_EVENT_PATH=str(event), GITHUB_SHA='a' * 40):
            C['guard'](inputs, harness)
        harness.guards.assert_called_once()
        self.assertIn(C['P13_SOURCE'], helper.process.call_args.args[0])

    def test_optional_plugin_cache_remains_empty_readonly_and_same_directory(self):
        (self.root / 'project.inlang').mkdir(mode=0o700)
        anchor = C['prepare_optional_cache'](self.root)
        C['check_optional_cache'](self.root, anchor)
        cache = self.root / 'project.inlang/cache'
        cache.chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'P14_OPTIONAL_CACHE_CHANGED'):
            C['check_optional_cache'](self.root, anchor)
        (cache / 'unreviewed.json').write_text('{}')
        cache.chmod(0o500)
        with self.assertRaisesRegex(ValueError, 'P14_OPTIONAL_CACHE_CHANGED'):
            C['check_optional_cache'](self.root, anchor)
        cache.chmod(0o700)

    def test_source_change_blocks_before_another_compiler(self):
        stage = self.root / 'stage'
        self.put(stage / 'src/input.ts', b'reviewed source\n')
        seal = C['source_input_seal'](I, stage)
        C['check_source_inputs'](I, stage, seal)
        self.put(stage / 'src/input.ts', b'changed source\n')
        with self.assertRaisesRegex(ValueError, 'P14_ORIGINAL_SOURCE_CHANGED'):
            C['check_source_inputs'](I, stage, seal)

    def test_unknown_generated_source_fails_closed(self):
        stage = self.root / 'stage'
        self.put(stage / 'src/input.ts', b'source\n')
        seal = C['source_input_seal'](I, stage)
        self.put(stage / 'unexpected-plugin.mjs', b'export default 1;\n')
        with self.assertRaisesRegex(ValueError, 'P14_UNREVIEWED_GENERATED_PATH') as caught:
            C['check_source_inputs'](I, stage, seal)
        self.assertEqual(caught.exception.relative_path, 'unexpected-plugin.mjs')

    def test_declared_generated_output_does_not_authorize_original_replacement(self):
        stage = self.root / 'stage'
        self.put(stage / 'src/lib/paraglide/original.js', b'original\n')
        seal = C['source_input_seal'](I, stage)
        self.put(stage / 'src/lib/paraglide/generated.js', b'generated\n')
        C['check_source_inputs'](I, stage, seal)
        self.put(stage / 'src/lib/paraglide/original.js', b'changed\n')
        with self.assertRaisesRegex(ValueError, 'P14_ORIGINAL_SOURCE_CHANGED'):
            C['check_source_inputs'](I, stage, seal)

    def test_source_special_or_link_cannot_enter_seal(self):
        stage = self.root / 'stage'
        stage.mkdir(mode=0o700)
        outside = self.root / 'external.js'
        self.put(outside, b'external\n')
        (stage / 'injected.js').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'P14_SOURCE_LINK_OR_SPECIAL'):
            C['source_input_seal'](I, stage)

    def test_graph_bytes_must_match_content_address(self):
        graph = self.root / '.volparossa-source-graphs' / ('a' * 64 + '.json')
        self.put(graph, b'{"different":true}\n')
        with self.assertRaisesRegex(ValueError, 'P14_GRAPH_IDENTITY'):
            C['graph_report'](I, self.root, {})

    def test_unknown_virtual_module_is_retained_without_notice_admission(self):
        value = {'schema': 1, 'kind': 'volparossa-drizzli-module-graph', 'admitted': False,
            'format': 'es', 'plugins': ['review-pending'], 'outputs': {'index.js': {
                'type': 'chunk', 'modules': [{'kind': 'virtual', 'id': '\u0000unknown', 'renderedLength': 1}]}}}
        raw = json.dumps(value).encode()
        self.put(self.root / '.volparossa-source-graphs' / (hashlib.sha256(raw).hexdigest() + '.json'), raw + b'\n')
        result, graphs = C['graph_report'](I, self.root, {})
        self.assertFalse(result['closure_complete'])
        self.assertEqual(result['failure'], 'UNREVIEWED_VIRTUAL_MODULE')
        self.assertFalse(result['admitted'])
        self.assertFalse(result['virtual_module_authority'])
        self.assertEqual(graphs, [value])

    def test_cleanup_retains_all_data_until_runtime_drain_and_policy_confirmation(self):
        output, stage, proof = (self.root / name for name in ('inputs', 'stage', 'proof'))
        for path in (output, stage, proof):
            path.mkdir(mode=0o700)
        self.put(stage / 'unique-recovery.txt', b'keep\n')
        inputs = SimpleNamespace(hosted_guard=Mock(), read=I.read, document=I.document,
            cleanup_candidate=Mock())
        with patch.dict(G, BUILD=self.root, OUTPUT=output, STAGE=stage, PROOF=proof,
                module=Mock(return_value=inputs)):
            for value in ({'process_drain_confirmed': False, 'policy_removed': True},
                    {'process_drain_confirmed': True, 'policy_removed': False}):
                self.put(output / 'p14-result.json', value)
                with self.assertRaisesRegex(ValueError, 'P14_CLEANUP_UNCONFIRMED'):
                    C['cleanup']()
                self.assertEqual((stage / 'unique-recovery.txt').read_bytes(), b'keep\n')
        inputs.cleanup_candidate.assert_not_called()

    def test_cleanup_checks_installer_before_removing_application_output(self):
        output, stage = self.root / 'inputs', self.root / 'stage'
        stage.mkdir(mode=0o700)
        self.put(stage / 'recovery.txt', b'keep\n')
        self.put(output / 'p14-result.json', {'process_drain_confirmed': True, 'policy_removed': True})
        self.put(output / 'installer-install-started.json', {})
        self.put(output / 'installer-install-cleanup.json', {'owned_session_drained': False, 'leader_reaped': True})
        inputs = SimpleNamespace(hosted_guard=Mock(), read=I.read, document=I.document,
            cleanup_candidate=Mock())
        with patch.dict(G, BUILD=self.root, OUTPUT=output, STAGE=stage, PROOF=self.root / 'proof',
                module=Mock(return_value=inputs)):
            with self.assertRaisesRegex(ValueError, 'P14_INSTALLER_CLEANUP_UNCONFIRMED'):
                C['cleanup']()
        self.assertTrue((stage / 'recovery.txt').exists())
        inputs.cleanup_candidate.assert_not_called()


class ProjectMetadata(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        self.project = self.stage / 'project.inlang'
        self.project.mkdir(mode=0o700)
        (self.project / 'settings.json').write_bytes(b'{}\n')
        (self.project / 'settings.json').chmod(0o600)
        # Small independent byte fixtures exercise the actual bounded reader;
        # clean hosted checkouts need no downloaded SDK or ignored build data.
        self.payloads = {'project.inlang/.gitignore': b'cache\n',
            'project.inlang/README.md': b'fixed SDK project metadata\n',
            'project.inlang/.meta.json': b'{\n  "highestSdkVersion": "3.0.3"\n}'}
        pins = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in self.payloads.items()}
        self.mapping = patch.dict(G, PROJECT_METADATA=pins)
        self.mapping.start()
        self.addCleanup(self.mapping.stop)
        self.seal = C['source_input_seal'](I, self.stage)

    def generate(self):
        for name, raw in self.payloads.items():
            path = self.stage / name
            path.write_bytes(raw)
            path.chmod(0o600)

    def verify(self):
        C['check_source_inputs'](I, self.stage, self.seal, generated_metadata=True)

    def test_exact_complete_metadata_with_bound_parents_succeeds_repeatedly(self):
        self.generate()
        self.verify()
        self.verify()

    def test_exact_real_sdk_meta_literal_matches_original_production_pin(self):
        raw = self.payloads['project.inlang/.meta.json']
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), C['PROJECT_METADATA']['project.inlang/.meta.json'])

    def test_metadata_is_not_permitted_before_localization(self):
        self.generate()
        with self.assertRaisesRegex(ValueError, 'P14_UNREVIEWED_GENERATED_PATH'):
            C['check_source_inputs'](I, self.stage, self.seal)

    def test_missing_file_cannot_silently_become_optional(self):
        self.generate()
        (self.project / '.meta.json').unlink()
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_MISSING'):
            self.verify()

    def test_extra_file_in_project_directory_is_rejected(self):
        self.generate()
        (self.project / 'new-code.js').write_bytes(b'code')
        with self.assertRaisesRegex(ValueError, 'P14_UNREVIEWED_GENERATED_PATH'):
            self.verify()

    def test_metadata_cannot_exist_when_original_source_is_sealed(self):
        self.generate()
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_ALREADY_PRESENT'):
            C['source_input_seal'](I, self.stage)

    def test_same_length_metadata_mutation_is_rejected(self):
        self.generate()
        path = self.project / '.meta.json'
        path.write_bytes(path.read_bytes().replace(b'3.0.3', b'3.0.4'))
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_BYTES'):
            self.verify()

    def test_oversize_metadata_is_rejected_before_read(self):
        self.generate()
        (self.project / '.meta.json').write_bytes(b'x' * 128)
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_FILE'):
            self.verify()

    def test_symlink_metadata_is_rejected(self):
        self.generate()
        path = self.project / 'README.md'
        path.rename(self.stage / 'readme-copy')
        path.symlink_to('../readme-copy')
        with self.assertRaises((OSError, ValueError)):
            C['project_metadata_file'](self.stage, 'project.inlang/README.md')

    def test_hardlink_metadata_is_rejected(self):
        self.generate()
        os.link(self.project / 'README.md', self.stage / 'readme-copy')
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_FILE'):
            C['project_metadata_file'](self.stage, 'project.inlang/README.md')

    def test_executable_and_writable_metadata_are_rejected(self):
        self.generate()
        for mode in (0o700, 0o666):
            (self.project / 'README.md').chmod(mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_FILE'):
                C['project_metadata_file'](self.stage, 'project.inlang/README.md')

    def test_replaced_project_directory_is_rejected_even_with_same_bytes(self):
        self.generate()
        self.project.rename(self.stage / 'retired')
        self.project.mkdir(mode=0o700)
        self.generate()
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_REPLACED'):
            self.verify()

    def test_project_directory_symlink_is_rejected_before_source_read(self):
        self.generate()
        self.project.rename(self.stage / 'retired')
        self.project.symlink_to('retired', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_PARENT'):
            self.verify()

    def test_parent_replacement_during_read_is_rejected(self):
        self.generate()
        actual_read = os.read
        def replace(fd, bound):
            raw = actual_read(fd, bound)
            self.project.rename(self.stage / 'retired')
            self.project.mkdir(mode=0o700)
            self.generate()
            return raw
        with patch.object(os, 'read', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_REPLACED'):
                C['project_metadata_file'](self.stage, 'project.inlang/.meta.json')

    def test_parent_replacement_between_original_check_and_metadata_open_is_rejected(self):
        self.generate()
        actual_read = I.read
        def replace(path, bound):
            raw = actual_read(path, bound)
            self.project.rename(self.stage / 'retired')
            self.project.mkdir(mode=0o700)
            (self.project / 'settings.json').write_bytes(b'{}\n')
            (self.project / 'settings.json').chmod(0o600)
            self.generate()
            return raw
        with patch.object(I, 'read', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_REPLACED'):
                self.verify()

    def test_file_replacement_during_read_is_rejected(self):
        self.generate()
        actual_read = os.read
        def replace(fd, bound):
            raw = actual_read(fd, bound)
            path = self.project / '.meta.json'
            path.unlink()
            path.write_bytes(self.payloads['project.inlang/.meta.json'])
            path.chmod(0o600)
            return raw
        with patch.object(os, 'read', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'P14_PROJECT_METADATA_REPLACED'):
                C['project_metadata_file'](self.stage, 'project.inlang/.meta.json')

    def test_original_settings_cannot_be_replaced_by_metadata_contract(self):
        self.generate()
        (self.project / 'settings.json').write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'P14_ORIGINAL_SOURCE_CHANGED'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
