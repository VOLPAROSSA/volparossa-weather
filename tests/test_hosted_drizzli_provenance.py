# SPDX-License-Identifier: GPL-3.0-only
"""Inert contract mutations; fixtures do not claim an actual compiler run."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
P = SimpleNamespace(**runpy.run_path(str(ROOT / 'scripts/prepare_hosted_drizzli_provenance.py')))
I = SimpleNamespace(**runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_inputs.py')))


def digest(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def fixture():
    approved = I.load_package_inputs('drizzli')['dependencies']['packages']
    # Minimal synthetic member maps exercise data guards; real build acquire()
    # must separately authenticate the complete maps and installed file tree.
    archives = {name: dict(input=copy.deepcopy(entry['input']), inactive=False,
        archive=dict(files={})) for name, entry in approved.items()}
    supplemental = P.notices(I)
    for item in supplemental.values():
        archives['node_modules/' + item['package']]['archive']['files'][item['member']] = dict(
            type='file', bytes=item['bytes'], sha256=item['sha256'])
    archives['node_modules/@rolldown/binding-linux-x64-gnu']['archive']['files'][
        'rolldown-binding.linux-x64-gnu.node'] = dict(type='file', sha256=P.NATIVE)
    graphs = []
    for environment in ('ssr', 'client'):
        ids = [P.RUNTIME] + ([key for key in P.SOURCES if key.startswith('\0virtual:')]
            if environment == 'ssr' else ['\0vite/preload-helper.js'])
        records = [P.expected_virtual(key, environment) for key in ids]
        refs = [dict(id=item['id'], kind='virtual', producer=item['producer']) for item in records]
        chunk = dict(type='chunk', **digest(b'export {};\n'), facadeModuleId=copy.deepcopy(refs[0]),
            moduleIds=copy.deepcopy(refs), modules=[dict(**item, renderedLength=1,
                rendered_sha256=digest(b'x')['sha256'], rendered_bytes=1) for item in refs])
        graphs.append(dict(schema=2, kind='volparossa-drizzli-module-graph', admitted=False,
            format='es', plugins=['inert-fixture'], environment=copy.deepcopy(P.ENVIRONMENTS[environment]),
            virtualModules=records, outputs={'_app/immutable/chunks/test.js': chunk}))
    return graphs, archives


class ProducerContracts(unittest.TestCase):
    def setUp(self):
        self.graphs, self.archives = fixture()

    def closure(self):
        return P.graph_closure(I, self.graphs, self.archives)

    def test_exact_four_source_derived_producers_and_original_notices(self):
        result = self.closure()
        self.assertEqual(set(result['virtual_modules']), set(P.SOURCES) | {P.RUNTIME})
        self.assertTrue({'tailwindcss', 'tw-animate-css', 'vite', 'rolldown', '@sveltejs/kit'}
            <= set(result['components']))

    def test_unknown_module_in_each_reference_field_is_denied(self):
        for field in ('facadeModuleId', 'moduleIds', 'modules'):
            with self.subTest(field=field):
                graphs, _ = fixture()
                unknown = dict(id='\0unreviewed', kind='virtual', producer='vite', renderedLength=1,
                    rendered_sha256=digest(b'x')['sha256'], rendered_bytes=1)
                chunk = graphs[1]['outputs']['_app/immutable/chunks/test.js']
                chunk[field] = unknown if field == 'facadeModuleId' else [unknown]
                with self.assertRaisesRegex(ValueError, 'UNREVIEWED_VIRTUAL_MODULE'):
                    P.graph_closure(I, graphs, self.archives)

    def test_wrong_producer_and_identical_code_is_denied(self):
        self.graphs[1]['virtualModules'][1]['producer'] = 'sveltekit'
        with self.assertRaisesRegex(ValueError, 'P14_VIRTUAL_PRODUCER_OR_CODE_CHANGED'):
            self.closure()

    def test_source_or_loader_or_post_transform_change_is_denied(self):
        for field in ('load', 'transformed'):
            for key, value in (('sha256', '0' * 64), ('bytes', 1)):
                with self.subTest(field=field, key=key):
                    graphs, _ = fixture()
                    graphs[0]['virtualModules'][1][field][key] = value
                    with self.assertRaisesRegex(ValueError, 'P14_VIRTUAL_PRODUCER_OR_CODE_CHANGED'):
                        P.graph_closure(I, graphs, self.archives)

    def test_hook_and_native_binary_change_is_denied(self):
        for field in ('hook_sha256', 'native_member_sha256'):
            with self.subTest(field=field):
                graphs, _ = fixture()
                graphs[1]['virtualModules'][1][field] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'P14_VIRTUAL_PRODUCER_OR_CODE_CHANGED'):
                    P.graph_closure(I, graphs, self.archives)

    def test_unknown_version_is_denied(self):
        self.archives['node_modules/vite']['input']['version'] = '8.3.2'
        with self.assertRaisesRegex(ValueError, 'P14_NOTICE_ARCHIVE_BINDING'):
            self.closure()

    def test_ambiguous_duplicate_producer_is_denied(self):
        self.graphs[0]['virtualModules'].append(copy.deepcopy(self.graphs[0]['virtualModules'][0]))
        with self.assertRaisesRegex(ValueError, 'P14_AMBIGUOUS_VIRTUAL_PRODUCER'):
            self.closure()

    def test_missing_receipt_is_denied(self):
        self.graphs[1]['virtualModules'].pop()
        with self.assertRaisesRegex(ValueError, 'P14_UNBOUND_VIRTUAL_REFERENCE'):
            self.closure()

    def test_missing_virtual_rendered_code_is_explicitly_denied(self):
        self.graphs[1]['outputs']['_app/immutable/chunks/test.js']['modules'][0].update(
            rendered_sha256=None, rendered_bytes=None)
        with self.assertRaisesRegex(ValueError, 'P14_VIRTUAL_RENDERED_CODE_MISSING'):
            self.closure()

    def test_context_switch_or_duplicate_environment_is_denied(self):
        self.graphs[1]['environment']['base'] = '/'
        with self.assertRaisesRegex(ValueError, 'P14_GRAPH_ENVIRONMENT'):
            self.closure()
        self.graphs[1]['environment'] = copy.deepcopy(P.ENVIRONMENTS['ssr'])
        with self.assertRaisesRegex(ValueError, 'P14_GRAPH_AMBIGUOUS_ENVIRONMENT'):
            self.closure()

    def test_unknown_native_binary_is_denied(self):
        self.archives['node_modules/@rolldown/binding-linux-x64-gnu']['archive']['files'][
            'rolldown-binding.linux-x64-gnu.node']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'P14_NATIVE_BINDING'):
            self.closure()

    def test_unknown_file_module_and_missing_archive_member_are_denied(self):
        chunk = self.graphs[1]['outputs']['_app/immutable/chunks/test.js']
        for name, code in (('node_modules/unreviewed/index.js', 'UNLOCKED_OUTPUT_MODULE'),
                ('node_modules/svelte/not-in-original-archive.js', 'P14_OUTPUT_MODULE_MEMBER')):
            with self.subTest(name=name):
                chunk['modules'].append(dict(id=name, kind='file', renderedLength=0))
                with self.assertRaisesRegex(ValueError, code):
                    self.closure()
                chunk['modules'].pop()

    def test_zero_js_length_does_not_skip_notice_owner(self):
        package = self.archives['node_modules/urlpattern-polyfill']
        package['archive']['files']['index.js'] = dict(type='file')
        self.graphs[0]['outputs']['_app/immutable/chunks/test.js']['modules'].append(
            dict(id='node_modules/urlpattern-polyfill/index.js', kind='file', renderedLength=0))
        self.assertIn('urlpattern-polyfill', self.closure()['components'])

    def test_missing_original_notice_is_denied(self):
        original, bundle = I.notice_inputs()
        original = copy.deepcopy(original)
        original['npm']['components']['tailwindcss']['notices'] = []
        with patch.object(I, 'notice_inputs', return_value=(original, bundle)):
            with self.assertRaisesRegex(ValueError, 'UNRESOLVED_RUNTIME_NOTICE'):
                self.closure()

    def test_exact_supplemental_notice_is_required_from_archive(self):
        self.archives['node_modules/vite']['archive']['files'].pop('LICENSE.md')
        with self.assertRaisesRegex(ValueError, 'P14_NOTICE_ARCHIVE_BINDING'):
            self.closure()

    def test_nested_selected_pin_is_not_replaced_with_root_version(self):
        # The selected nested member must use its own pin when resolving notices.
        name = next(name for name in self.archives if '/node_modules/' in name)
        owner = self.archives[name]
        owner['archive']['files']['fixture.js'] = dict(type='file')
        self.graphs[0]['outputs']['_app/immutable/chunks/test.js']['modules'].append(
            dict(id=name + '/fixture.js', kind='file', renderedLength=0))
        owner['input']['version'] = '0.0.0-unapproved'
        with self.assertRaisesRegex(ValueError, 'P14_OUTPUT_PACKAGE_BINDING'):
            self.closure()


class OutputContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        self.stage.chmod(0o700)
        self.graphs, archives = fixture()
        self.closure = P.graph_closure(I, self.graphs, archives)
        self.source = {P.CSS_INPUT[0]: dict(sha256=P.CSS_INPUT[1])}
        self.records = {}
        self.put('_app/immutable/chunks/test.js', b'export {};\n')
        for name in P.STATIC:
            raw = ('original static ' + name).encode()
            self.source['static/' + name] = digest(raw)
            self.put(name, raw)
        for name in P.HTML:
            self.put(name, b'<html><body>Fixture, not a compiler result.</body></html>')
        self.put('_app/version.json', b'{"version":"d2a6839e2b3f2e561b849d83014fc5959bed39cc"}')
        for name in ('LICENSE.DRIZZLI', 'LICENSE.VOLPAROSSA', 'npm-originals.txt',
                'message-format.LICENSE', 'm-function-matcher.LICENSE'):
            raw = I.notice_inputs()[1] if name == 'npm-originals.txt' else b'original fixture notice'
            self.put('VOLPAROSSA-NOTICES/' + name, raw)
            self.records[name] = digest(raw)
            source = {'LICENSE.DRIZZLI': 'LICENSE', 'LICENSE.VOLPAROSSA': 'LICENSE.VOLPAROSSA',
                'message-format.LICENSE': 'volparossa-build-plugins/message-format.LICENSE',
                'm-function-matcher.LICENSE': 'volparossa-build-plugins/m-function-matcher.LICENSE'}.get(name)
            if source:
                self.source[source] = digest(raw)
        for name, item in self.closure['supplemental'].items():
            self.put(name, item['raw'])
            self.records[Path(name).name] = digest(item['raw'])

    def put(self, name, raw):
        path = self.stage / 'build' / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        for parent in path.parents:
            if parent == self.stage:
                break
            parent.chmod(0o700)
        path.write_bytes(raw)
        path.chmod(0o600)

    def check(self):
        return P.output_closure(I, self.stage, I.output_inventory(self.stage / 'build'), self.source,
            self.records, self.graphs, self.closure)

    def test_actual_files_are_all_covered_with_separate_producer_classes(self):
        result = self.check()
        self.assertTrue(result['complete'])
        self.assertIn('tailwindcss', result['components'])
        self.assertFalse(result['independent_reproduction'])
        self.assertEqual(result['files_count'], 21)

    def test_changed_client_output_is_denied(self):
        self.put('_app/immutable/chunks/test.js', b'new bytes')
        with self.assertRaisesRegex(ValueError, 'P14_OUTPUT_GRAPH_BYTES_CHANGED'):
            self.check()

    def test_changed_static_copy_is_denied(self):
        self.put('favicon.svg', b'replaced')
        with self.assertRaisesRegex(ValueError, 'P14_STATIC_OUTPUT_CHANGED'):
            self.check()

    def test_missing_or_changed_distributed_notice_is_denied(self):
        path = self.stage / 'build/VOLPAROSSA-NOTICES/vite-LICENSE.md'
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'P14_OUTPUT_NOTICE_MISSING'):
            self.check()
        self.put('VOLPAROSSA-NOTICES/vite-LICENSE.md', b'not original notice')
        with self.assertRaisesRegex(ValueError, 'P14_OUTPUT_NOTICE_MISSING'):
            self.check()

    def test_original_notice_cannot_be_omitted_from_both_inventory_and_records(self):
        self.records.pop('LICENSE.DRIZZLI')
        (self.stage / 'build/VOLPAROSSA-NOTICES/LICENSE.DRIZZLI').unlink()
        with self.assertRaisesRegex(ValueError, 'P14_REQUIRED_ORIGINAL_NOTICE_MISSING'):
            self.check()

    def test_unreviewed_font_or_html_or_other_copy_is_denied(self):
        for name in ('font.woff2', 'other/index.html', 'unrelated.svg'):
            with self.subTest(name=name):
                self.put(name, b'unreviewed')
                with self.assertRaisesRegex(ValueError, 'P14_UNCOVERED_DISTRIBUTED_OUTPUT'):
                    self.check()
                (self.stage / 'build' / name).unlink()

    def test_changed_css_input_is_denied(self):
        self.source[P.CSS_INPUT[0]]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'P14_CSS_INPUT_CHANGED'):
            self.check()

    def test_version_must_be_the_exact_upstream_source(self):
        self.put('_app/version.json', b'{"version":"0000000000000000000000000000000000000000"}')
        with self.assertRaisesRegex(ValueError, 'P14_VERSION_OUTPUT_CHANGED'):
            self.check()

    def test_unknown_bundle_asset_is_denied_even_with_matching_hash(self):
        self.put('_app/evil.bin', b'unknown')
        self.graphs[1]['outputs']['_app/evil.bin'] = dict(type='asset', **digest(b'unknown'))
        with self.assertRaisesRegex(ValueError, 'P14_UNREVIEWED_BUNDLE_ASSET'):
            self.check()


if __name__ == '__main__':
    unittest.main()
