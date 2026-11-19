# SPDX-License-Identifier: GPL-3.0-only
"""Inert producer-shaped metadata tests. No SDK, subprocess, or filesystem data."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_overmorrow_pub_metadata.py'))

# Frozen independent data-reference vectors. Input byte i is (37*i +11)%256.
# Reference source receipt: build/p15g-source-hash/reproduction.json; the four
# two-read vectors extend the same source-derived model without executing SDK.
PADDING_VECTORS = (
    (0, 'd41d8cd98f00b204e9800998ecf8427e'),
    (1, '13c8ffd977013703a701cf8e11deac65'),
    (54, '5e5534f470ef1d65657807ed96610693'),
    (55, 'd872aa0473a24da995ce4ac518ade767'),
    (56, 'f558791287315c4845b3b85993781d36'),
    (57, 'b1eaee86ce0ccff33e2a58ba2b5127a1'),
    (58, '877a1082d2e60acfb89ef559f3c2c856'),
    (59, '7e5d044f65ec719384c0da282e8b5d12'),
    (60, '6e9632c6ff9600eb20ff265796cd0101'),
    (61, 'c71d1ba29881a5f40f1830921add3fc4'),
    (62, '1bee3ce8713ef96d19a3a73c7f978df3'),
    (63, '008813a74205a5fa24a041ba68bcdd6e'),
    (64, '71e123b70c7aa64826fcfe472694cd1c'),
    (65, '5949948f26e35203661075214faa3966'),
    (119, '87f72c7241c5fe218bb4df8c0aba3232'),
    (120, 'badc8e807e94d27d9540948747a5b3c5'),
    (127, '9c0fb8b86166a925dcc5cb6173d7fd05'),
    (128, '3e93b378458b77da96b2357c3bda8cc2'),
    (129, 'd1ae06bbf9128955a34bedb6231eee62'),
    (65535, '6cdc039b06ec4fedf7f37a7c0123f08a'),
    (65536, 'd0f0f2df82bfee40db154d5873a4a7cc'),
    (65537, '2b1db02f284fe0fa3b34b63045c806ef'),
    (65591, '81e79065cc05684b3eb65f1e3c8fac47'),
    (65592, '2369d2f612ff6f0014ae7370507322c1'),
    (65599, '39b41d2472fc03497a12964c2f83439c'),
    (65600, '8d25b25dd34ce7607e997d13943c0923'),
    (131127, 'f192749d18d4c8c3f207d5f70c0a7e03'),
    (131128, '1b4fa5ec32010ec1295a929a4cc084e0'),
    (131135, '809755e7280e2fba14b017a4c2495e8e'),
    (131136, '5512a8c0ec2614031acfadd151e9bf86'),
)


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

    def test_original_flutter_license_is_preserved_byte_for_byte(self):
        raw = M['FLUTTER_HASH_LICENSE'].encode()
        self.assertEqual(len(raw), 1519)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         'a598db94b6290ffbe10b5ecf911057b6a943351c727fdda9e5f2891d68700a20')

    def test_original_six_upstream_hash_vectors_with_little_endian_serialization(self):
        vectors = [(b'', 'd41d8cd98f00b204e9800998ecf8427e'),
            (b'The quick brown fox jumps over the lazy dog', '9e107d9d372bb6826bd81d3542a419d6'),
            (b'The quick brown fox jumps over the lazy dog.', 'e4d909c290d0fb1ca068ffaddf22cbd0'),
            (bytes((1, 2, 3, 4, 5, 6)), struct.pack('<4I', 1810219370, 268668871, 3900423769, 1277973076).hex()),
            (bytes([2]) * 64, struct.pack('<4I', 260592333, 2557619848, 2729912077, 812879060).hex()),
            (bytes([2]) * 514, struct.pack('<4I', 387658779, 2003142991, 243395797, 1487291259).hex())]
        for raw, expected in vectors:
            with self.subTest(bytes=len(raw)):
                self.assertEqual(M['cache_hash'](raw), expected)

    def test_padding_edges_and_multiple_file_store_64k_reads(self):
        for length, expected in PADDING_VECTORS:
            with self.subTest(bytes=length):
                raw = bytes((index * 37 + 11) % 256 for index in range(length))
                actual = M['cache_hash'](raw)
                self.assertEqual(actual, expected)
                self.assertEqual(actual != hashlib.md5(raw).hexdigest(), length % 64 >= 56)
        for bad in (None, 'bytes', bytearray(b'bytes'), b'x' * (M['MAX_FILE'] + 1)):
            with self.assertRaisesRegex(ValueError, '^P15_PUB_METADATA_HASH_BOUND$'):
                M['cache_hash'](bad)

    def test_seven_tail_bytes_can_collide_but_sha256_changes(self):
        first = b'a' * 56 + b'1234567'
        second = b'a' * 56 + b'ABCDEFG'
        self.assertEqual(M['cache_hash'](first), M['cache_hash'](second))
        self.assertNotEqual(hashlib.md5(first).digest(), hashlib.md5(second).digest())
        self.assertNotEqual(hashlib.sha256(first).digest(), hashlib.sha256(second).digest())

    def test_all_73_original_role_vectors_new_values_pass_old_values_report_12(self):
        raw = (ROOT / 'third_party/overmorrow-filecache-semantics-v1.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '314a60c54b76753e2fda91a77357e7de22da2764ad1f1b33f510e1075d8d0edc')
        rows = json.loads(raw)['cache_roles']
        self.assertEqual(len(rows), 73)
        self.assertEqual(sum(row['differs'] for row in rows), 12)
        self.assertEqual(sum(not row['differs'] for row in rows), 61)
        self.assertEqual(sum(not row['differs'] for row in rows
            if row['role'] in ('arb-input', 'generated-l10n-output')), 59)
        old_inputs, old_outputs, new_inputs, new_outputs = {}, {}, {}, {}
        cache = []
        expected_labels = set()
        for row in rows:
            output = row['role'] == 'generated-l10n-output'
            sdk = row['role'] == 'sdk-target-input'
            path = (self.sdk if sdk else self.app) + '/' + row['path']
            (old_outputs if output else old_inputs)[path] = row['standard_md5']
            (new_outputs if output else new_inputs)[path] = row['producer_bookkeeping_hash']
            cache.append(dict(path=path, hash=row['producer_bookkeeping_hash']))
            if row['differs']:
                expected_labels.add(('output' if output else 'input', row['path']))
        self.files[self.prefix + '.filecache'] = encoded(dict(version=2, files=cache))
        self.assertEqual(self.call(input_hashes=new_inputs, output_hashes=new_outputs)['cache_entries'], 73)
        with self.assertRaises(M['CacheHashFailure']) as failure:
            self.call(input_hashes=old_inputs, output_hashes=old_outputs)
        observation = failure.exception.cache_observation()
        self.assertEqual(observation['mismatch_count'], 12)
        self.assertEqual({(x['role'], x['label']) for x in observation['mismatches']}, expected_labels)

    def test_cache_diagnostics_collect_all_mismatches_in_controlled_order(self):
        cache = json.loads(self.files[self.prefix + '.filecache'])
        for item in cache['files']:
            item['hash'] = '0' * 32
        observations = []
        for entries in (cache['files'], list(reversed(cache['files']))):
            self.files[self.prefix + '.filecache'] = encoded(dict(version=2, files=entries))
            with self.assertRaises(M['CacheHashFailure']) as failure:
                self.call()
            self.assertIsNone(getattr(failure.exception, 'observation', None))
            self.assertEqual(str(failure.exception), 'P15_PUB_METADATA_CACHE_HASH')
            observation = failure.exception.cache_observation()
            self.assertEqual(set(observation), {'metadata_file', 'algorithm', 'entries_checked',
                'mismatch_count', 'mismatches'})
            self.assertEqual(observation['entries_checked'], 73)
            self.assertEqual(observation['mismatch_count'], 73)
            self.assertEqual(observation['algorithm'], 'flutter-3.38.5-Md5Hash')
            self.assertEqual(observation['mismatches'][0]['label'], 'sdk-target')
            self.assertEqual(observation['mismatches'][-1]['label'], 'lib/l10n/app_localizations.dart')
            self.assertNotIn(self.app, json.dumps(observation))
            self.assertNotIn(self.sdk, json.dumps(observation))
            observations.append(observation)
            observation['mismatches'][0]['label'] = 'untrusted caller mutation'
            self.assertEqual(failure.exception.cache_observation()['mismatches'][0]['label'], 'sdk-target')
            observation['mismatches'][0]['label'] = 'sdk-target'
        self.assertEqual(observations[0], observations[1])

    def test_malformed_digest_values_are_bounded_fingerprints_never_raw_content(self):
        secret = '/private/hidden-secret-' * 7000
        values = [secret, 'A' * 32, None, True, 2, ['secret'], {'host': '/private/secret'}, '\ud800']
        cache = json.loads(self.files[self.prefix + '.filecache'])
        for item, value in zip(cache['files'], values):
            item['hash'] = value
        self.files[self.prefix + '.filecache'] = encoded(cache)
        with self.assertRaises(M['CacheHashFailure']) as failure:
            self.call()
        observation = failure.exception.cache_observation()
        self.assertEqual(observation['mismatch_count'], len(values))
        self.assertNotIn('private', json.dumps(observation))
        self.assertNotIn('secret', json.dumps(observation))
        for row in observation['mismatches']:
            self.assertEqual(set(row), {'role', 'label', 'expected_digest', 'observed_type',
                                       'observed_length', 'observed_sha256'})
            self.assertIs(type(row['observed_length']), int)
            self.assertRegex(row['observed_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(observation['mismatches'][0]['observed_length'], len(secret.encode()))
        self.assertEqual(observation['mismatches'][0]['observed_sha256'], hashlib.sha256(secret.encode()).hexdigest())

    def test_unknown_or_duplicate_cache_path_precedes_digest_diagnostic(self):
        for bad in ('unknown', 'duplicate'):
            cache = json.loads(self.files[self.prefix + '.filecache'])
            cache['files'][0]['hash'] = '/private/secret'
            cache['files'][-1]['path'] = '/private/secret' if bad == 'unknown' else cache['files'][0]['path']
            self.files[self.prefix + '.filecache'] = encoded(cache)
            with self.assertRaisesRegex(ValueError, '^P15_PUB_METADATA_CACHE_PATH$') as failure:
                self.call()
            self.assertNotIsInstance(failure.exception, M['CacheHashFailure'])


if __name__ == '__main__':
    unittest.main()
