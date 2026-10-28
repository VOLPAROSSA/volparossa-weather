# SPDX-License-Identifier: GPL-3.0-only
"""Inert producer-shaped metadata tests. No SDK, subprocess, or filesystem data."""
import hashlib
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_pub_metadata.py'))


def encoded(value):
    return json.dumps(value, separators=(',', ':')).encode()


def producer_lists(app, bundles, preferred=()):
    """Independent fixture reconstruction of the pinned producer's ordering.

    AppResourceBundleCollection sorts source filenames before loading locales.
    gen_l10n._generateCode separately sorts locale strings and inserts only base
    languages into its file map. writeOutputFiles appends the base output last.
    preferredSupportedLocales affects the delegate, not that output map.
    This is source-shaped fixture data, never execution of Dart or the SDK.
    """
    locale_files = {}
    for filename, raw in sorted(bundles.items()):
        locale = json.loads(raw).get('@@locale', filename[4:-4])
        locale_files[locale] = app + '/lib/l10n/' + filename
    supported = list(locale_files)
    for locale in preferred:
        supported.remove(locale)
        supported[0:0] = preferred
    language_files = {}
    for locale in sorted(locale_files):
        if locale == locale.split('_')[0]:
            language_files.setdefault(app + '/lib/l10n/app_localizations_' + locale + '.dart', None)
    outputs = [*language_files, app + '/lib/l10n/app_localizations.dart']
    return list(locale_files.values()), outputs, supported


class PubMetadataTests(unittest.TestCase):
    def setUp(self):
        self.app = '/private/app'
        self.sdk = '/private/sdk'
        self.engine = 'a' * 40
        self.build_id = hashlib.md5((self.engine + 'build').encode()).hexdigest()
        self.prefix = 'build/' + self.build_id + '/'
        locales = ('ar bg bn ca da de el en es fi fr he hr hu id it ja mk nl pl pt '
                   'pt_BR ro ru sk sl sr sw ta tr uk ur uz vi zh zh_Hant').split()
        # Deliberately unsorted source collection. Do not construct expected
        # metadata from the validator's ARBS/OUTPUTS constants.
        self.bundles = {'app_' + locale + '.arb': encoded(
            {'hello': 'source', **({'@@locale': locale} if index % 2 else {})})
            for index, locale in enumerate(reversed(locales))}
        self.arbs, self.outputs, _ = producer_lists(self.app, self.bundles)
        self.dep_inputs = [self.app + '/l10n.yaml', *self.arbs]
        self.inputs = [self.sdk + '/packages/flutter_tools/lib/src/build_system/targets/localizations.dart',
                       *self.dep_inputs]
        self.input_hashes = {p: hashlib.md5(('original:' + p).encode()).hexdigest() for p in self.inputs}
        self.output_hashes = {p: hashlib.md5(('generated:' + p).encode()).hexdigest() for p in self.outputs}
        self.files = {
            self.prefix + 'gen_l10n_inputs_and_outputs.json': encoded(dict(inputs=self.arbs, outputs=self.outputs)),
            self.prefix + 'gen_localizations.stamp': encoded(dict(inputs=self.inputs, outputs=self.outputs)),
            self.prefix + 'outputs.json': encoded(self.outputs),
            self.prefix + '.filecache': encoded(dict(version=2, files=[dict(path=p, hash=h)
                for p, h in {**self.input_hashes, **self.output_hashes}.items()])),
            self.prefix + 'gen_localizations.d': (''.join(' ' + p for p in self.outputs)
                + ': ' + ''.join(' ' + p for p in self.dep_inputs)).encode(),
            'build/.last_build_id': self.build_id.encode(),
        }

    def call(self, **overrides):
        arguments = dict(app_root=self.app, sdk_root=self.sdk, engine_revision=self.engine,
                         input_hashes=self.input_hashes, output_hashes=self.output_hashes)
        files = overrides.pop('files', self.files)
        arguments.update(overrides)
        return M['validate'](files, **arguments)

    def mutate(self, name, change):
        path = self.prefix + name
        value = json.loads(self.files[path])
        change(value)
        self.files[path] = encoded(value)

    def rejected(self, **overrides):
        with self.assertRaisesRegex(ValueError, r'^P15_PUB_METADATA_[A-Z0-9_]+$') as failure:
            self.call(**overrides)
        self.assertNotIn(self.app, str(failure.exception))
        self.assertNotIn(self.sdk, str(failure.exception))

    def test_success_is_pure_and_returns_closed_private_receipt(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected I/O')):
            receipt = self.call()
        self.assertEqual(set(receipt), {'schema', 'kind', 'admitted', 'metadata_files',
            'inputs', 'outputs', 'cache_entries', 'metadata_bytes', 'metadata_sha256'})
        self.assertFalse(receipt['admitted'])
        self.assertEqual((receipt['inputs'], receipt['outputs'], receipt['cache_entries']), (38, 35, 73))
        self.assertEqual(receipt['metadata_files'], 6)
        self.assertNotIn(self.app, json.dumps(receipt))

    def test_producer_order_sorts_source_bundles_and_keeps_base_output_last(self):
        arbs, outputs, supported = producer_lists(self.app, self.bundles, preferred=('en',))
        self.assertEqual(supported[0], 'en')
        self.assertTrue(arbs[0].endswith('/app_ar.arb'))
        self.assertTrue(outputs[0].endswith('/app_localizations_ar.dart'))
        self.assertTrue(outputs[-1].endswith('/app_localizations.dart'))
        self.assertEqual((arbs, outputs), (self.arbs, self.outputs))
        self.assertFalse(any(path.endswith(('_pt_BR.dart', '_zh_Hant.dart')) for path in outputs))
        expected = (''.join(' ' + p for p in outputs) + ': '
                    + ''.join(' ' + p for p in [self.app + '/l10n.yaml', *arbs])).encode()
        self.assertEqual(self.files[self.prefix + 'gen_localizations.d'], expected)
        self.assertEqual(self.call()['metadata_files'], 6)

    def test_exact_six_files_no_unknown_missing_or_other_build_id(self):
        for change in ('extra', 'missing', 'wrong_id', 'traversal', 'nested'):
            with self.subTest(change=change):
                files = dict(self.files)
                name = self.prefix + 'outputs.json'
                if change == 'extra':
                    files[self.prefix + 'other.json'] = b'{}'
                elif change == 'missing':
                    del files[name]
                else:
                    replacement = {'wrong_id': 'build/' + 'b' * 32 + '/outputs.json',
                        'traversal': self.prefix + '../outputs.json',
                        'nested': self.prefix + 'nested/outputs.json'}[change]
                    files[replacement] = files.pop(name)
                self.rejected(files=files)

    def test_input_roles_reject_even_consistent_external_sdk_or_arb_substitution(self):
        for original, replacement in ((self.inputs[0], '/external/targets/localizations.dart'),
                (self.arbs[0], '/external/app_ar.arb'),
                (self.arbs[0], self.app + '/lib/l10n/app_fake.arb')):
            hashes = dict(self.input_hashes)
            hashes[replacement] = hashes.pop(original)
            self.rejected(input_hashes=hashes)
        self.rejected(sdk_root='/other/sdk')
        self.rejected(app_root='/other/app')

    def test_fixed_output_roles_exclude_sublocale_and_extra_dart_sources(self):
        for replacement in (self.app + '/lib/l10n/app_localizations_pt_BR.dart',
                            self.app + '/lib/main.dart'):
            hashes = dict(self.output_hashes)
            hashes[replacement] = hashes.pop(self.outputs[0])
            self.rejected(output_hashes=hashes)

    def test_duplicate_top_and_nested_json_keys_reject(self):
        for raw in (b'{"version":2,"version":2,"files":[]}',
                    b'{"version":2,"files":[{"path":"x","path":"x","hash":"x"}]}'):
            files = dict(self.files, **{self.prefix + '.filecache': raw})
            self.rejected(files=files)

    def test_duplicate_or_wrong_members_cannot_hide_behind_correct_counts(self):
        for name, field in (('gen_l10n_inputs_and_outputs.json', 'inputs'),
                            ('gen_l10n_inputs_and_outputs.json', 'outputs'),
                            ('gen_localizations.stamp', 'inputs'),
                            ('gen_localizations.stamp', 'outputs')):
            for bad in ('duplicate', 'external'):
                with self.subTest(name=name, field=field, bad=bad):
                    files = dict(self.files)
                    value = json.loads(files[self.prefix + name])
                    value[field][0] = value[field][1] if bad == 'duplicate' else '/external/injected'
                    files[self.prefix + name] = encoded(value)
                    self.rejected(files=files)
        files = dict(self.files)
        files[self.prefix + 'outputs.json'] = encoded([self.outputs[0]] * 35)
        self.rejected(files=files)

    def test_exact_keys_do_not_allow_buildkey_or_extra_fields(self):
        for name in ('gen_l10n_inputs_and_outputs.json', 'gen_localizations.stamp', '.filecache'):
            files = dict(self.files)
            value = json.loads(files[self.prefix + name]); value['buildKey'] = 'arbitrary'
            files[self.prefix + name] = encoded(value)
            self.rejected(files=files)

    def test_cache_rejects_wrong_hash_duplicate_path_and_unknown_path(self):
        for field, value in (('hash', '0' * 32), ('path', self.inputs[1]), ('path', '/external/secret')):
            files = dict(self.files)
            cache = json.loads(files[self.prefix + '.filecache'])
            cache['files'][0][field] = value
            files[self.prefix + '.filecache'] = encoded(cache)
            self.rejected(files=files)

    def test_cache_version_and_entry_schemas_are_strict(self):
        for version in (True, '2', 1, 2.0):
            files = dict(self.files)
            cache = json.loads(files[self.prefix + '.filecache']); cache['version'] = version
            files[self.prefix + '.filecache'] = encoded(cache)
            self.rejected(files=files)
        for bad in ('missing', 'extra', 'entry_extra', 'entry_nonobject'):
            files = dict(self.files); cache = json.loads(files[self.prefix + '.filecache'])
            if bad == 'missing': cache['files'].pop()
            elif bad == 'extra': cache['files'].append(cache['files'][0])
            elif bad == 'entry_extra': cache['files'][0]['other'] = True
            else: cache['files'][0] = []
            files[self.prefix + '.filecache'] = encoded(cache)
            self.rejected(files=files)

    def test_cache_entry_order_and_json_spacing_are_not_path_authority(self):
        value = json.loads(self.files[self.prefix + '.filecache'])
        value['files'].reverse()
        self.files[self.prefix + '.filecache'] = json.dumps(value, indent=2).encode()
        self.assertEqual(self.call()['cache_entries'], 73)

    def test_depfile_is_exact_including_separator_and_no_trailing_newline(self):
        original = self.files[self.prefix + 'gen_localizations.d']
        for raw in (original + b'\n', original.replace(b':  ', b': ', 1),
                    original.replace(self.outputs[0].encode(), b'/external/injection', 1)):
            files = dict(self.files, **{self.prefix + 'gen_localizations.d': raw})
            self.rejected(files=files)

    def test_spaces_in_bound_roots_use_exact_linux_depfile_escaping(self):
        app, sdk = self.app + ' space', self.sdk + ' space'
        files = {p: b.replace(self.app.encode(), app.encode()).replace(self.sdk.encode(), sdk.encode())
                 for p, b in self.files.items()}
        files[self.prefix + 'gen_localizations.d'] = files[self.prefix + 'gen_localizations.d'].replace(
            b' space', b'\\ space')
        inputs = {p.replace(self.app, app).replace(self.sdk, sdk): h for p, h in self.input_hashes.items()}
        outputs = {p.replace(self.app, app): h for p, h in self.output_hashes.items()}
        self.assertEqual(self.call(files=files, app_root=app, sdk_root=sdk,
            input_hashes=inputs, output_hashes=outputs)['metadata_files'], 6)

    def test_build_id_is_bound_to_engine_revision_and_exact_scalar_bytes(self):
        for bad in (self.build_id.encode() + b'\n', b'b' * 32):
            self.rejected(files=dict(self.files, **{'build/.last_build_id': bad}))
        for revision in ('b' * 40, 'A' * 40, 'a' * 39, None, True):
            self.rejected(engine_revision=revision)

    def test_roots_are_canonical_disjoint_absolute_paths(self):
        for root in ('relative', '/', '/private//app', '/private/../app', '/private/app/',
                     '/private/./app', '/private\\app', '/private/\napp', None):
            self.rejected(app_root=root)
        self.rejected(sdk_root=self.app)
        self.rejected(sdk_root=self.app + '/sdk')
        self.rejected(app_root=self.sdk + '/app')

    def test_hash_mappings_require_exact_counts_types_and_lowercase_md5(self):
        for bad in ('A' * 32, 'a' * 31, 'a' * 64, True, None):
            hashes = dict(self.input_hashes); hashes[self.inputs[0]] = bad
            self.rejected(input_hashes=hashes)
        for which in ('input_hashes', 'output_hashes'):
            hashes = dict(getattr(self, which)); hashes.pop(next(iter(hashes)))
            self.rejected(**{which: hashes})
            self.rejected(**{which: list(getattr(self, which))})

    def test_json_invalid_types_constants_encoding_and_depth_fail_closed(self):
        for raw in (b'[]', b'null', b'{', b'\xff', b'{"x":NaN}', b'{"x":1.5}',
                    b'{"x":' + b'1' * 100 + b'}', b'[' * 2000 + b']' * 2000):
            self.rejected(files=dict(self.files, **{self.prefix + '.filecache': raw}))
        for value in (None, {}, 'bad'):
            files = dict(self.files)
            files[self.prefix + 'gen_l10n_inputs_and_outputs.json'] = encoded(dict(inputs=value, outputs=self.outputs))
            self.rejected(files=files)

    def test_byte_inputs_and_resource_bounds_are_enforced_before_parsing(self):
        for raw in (b'', 'not bytes', bytearray(b'{}'), b'x' * (M['MAX_FILE'] + 1)):
            self.rejected(files=dict(self.files, **{self.prefix + '.filecache': raw}))
        files = {name: b'x' * M['MAX_FILE'] for name in self.files}
        self.rejected(files=files)
        self.rejected(files=list(self.files))


if __name__ == '__main__':
    unittest.main()
