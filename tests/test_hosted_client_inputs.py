# SPDX-License-Identifier: GPL-3.0-only
"""Inert source/data tests; never invoke Node, Flutter, APT or downloaded code."""
import base64
import copy
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import runpy
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
I = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_inputs.py'))
G = I['main'].__globals__
A = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_apt.py'))


def sri(raw=b'archive'):
    return 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()


def lock(name='svelte', version='5.57.0'):
    return dict(lockfileVersion=3, packages={'': {'name': 'root', 'dependencies': {'svelte': '^5'}},
        'node_modules/' + name: dict(version=version, resolved=f'https://registry.npmjs.org/{name}/-/{name.split("/")[-1]}-{version}.tgz', integrity=sri())})


def pub(name='a', source='hosted'):
    desc = f'\n      name: {name}\n      sha256: {"a" * 64}\n      url: "https://pub.dev"' if source == 'hosted' else ' flutter'
    return f'packages:\n  {name}:\n    dependency: transitive\n    description:{desc}\n    source: {source}\n    version: "1.0.0"\nsdks:\n  dart: ">=3.10.3 <4.0.0"\n  flutter: ">=3.38.5"\n'.encode()


def archive(entries):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as target:
        for name, raw, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(raw) if kind == tarfile.REGTYPE else 0
            member.linkname = '../../escape' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
            target.addfile(member, io.BytesIO(raw) if member.isreg() else None)
    return result.getvalue()


class ClientInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tmp = Path(self.temporary.name)

    def put(self, path, raw):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def test_original_primary_locks_and_exact_pins(self):
        counts = {'drizzli': 347, 'overmorrow': 157}
        for profile, source in I['SOURCES'].items():
            raw = I['read'](ROOT / 'third_party/client-locks' / (profile + '-' + source['lock']))
            self.assertEqual(I['sha'](raw), source['sha256'])
            parsed = I['npm_lock'](raw) if profile == 'drizzli' else I['pub_lock'](raw)
            self.assertEqual(len(parsed), counts[profile])
        pub_entries = I['pub_lock'](I['read'](ROOT / 'third_party/client-locks/overmorrow-pubspec.lock'))
        self.assertEqual(sum(p.get('source') == 'hosted' for p in pub_entries.values()), 152)
        self.assertEqual({p['sdk_commit'] for p in pub_entries.values() if p['source'] == 'sdk'}, {I['SDK_COMMIT']})

    def test_fixed_npm_target_matches_exact_npm_11_list_semantics(self):
        self.assertEqual(I['NPM_TARGET'], dict(os='linux', cpu='x64', libc='glibc'))
        for selectors, included in (({}, True), ({'os': 'linux'}, True), ({'os': ['any']}, True),
                ({'os': []}, True), ({'os': ['!darwin', '!win32']}, True),
                ({'os': ['linux', '!linux']}, False), ({'os': ['any', 'darwin']}, False),
                ({'os': ['darwin', 'linux']}, True), ({'cpu': ['arm64']}, False),
                ({'cpu': 'x64', 'libc': 'glibc'}, True), ({'libc': ['musl']}, False),
                ({'os': ['!any']}, True)):
            with self.subTest(selectors=selectors):
                value = I['npm_target_selection'](dict(selectors, optional=True))
                self.assertEqual(value['included'], included)
                self.assertEqual(value['selectors'], selectors)
                self.assertEqual(bool(value['unsupported']), not included)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_PLATFORM_UNSUPPORTED'):
            I['npm_target_selection'](dict(os='darwin'))
        for entry in (dict(optional='true'), dict(optional=1), dict(optional=None), dict(os=None),
                dict(os=False), dict(os={}), dict(cpu=[['x64']]), dict(os=['!']), dict(os=['!!linux']),
                dict(os=['']), dict(os=['Linux']), dict(os=['linux'] * 65),
                dict(optional=True, os='darwin', libc=['glibc', 1])):
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, 'NPM_'):
                I['npm_target_selection'](entry)

    def test_all_locked_entries_survive_target_selection_and_excluded_modules_are_forbidden(self):
        packages = I['npm_lock'](I['read'](ROOT / 'third_party/client-locks/drizzli-package-lock.json'))
        selected = {path: I['npm_target_selection'](entry) for path, entry in packages.items()}
        self.assertEqual(len(packages), 347)
        self.assertEqual(sum(entry['included'] for entry in selected.values()), 300)
        self.assertEqual(sum(not entry['included'] for entry in selected.values()), 47)
        for path, selection in selected.items():
            if not selection['included']:
                self.assertTrue(packages[path]['optional'])
                self.assertTrue(packages[path]['integrity'].startswith('sha512-'))
        I['reject_excluded_npm_modules'](['node_modules/svelte/index.js',
            'node_modules/@lix-js/sdk-linux-x64/lix_js_sdk.node'], packages)
        for path in ('node_modules/@lix-js/sdk-darwin-arm64',
                'node_modules/@lix-js/sdk-darwin-arm64/package.json',
                'node_modules/vite/node_modules/lightningcss-linux-arm64-gnu/index.node'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'EXCLUDED_NPM_MODULE_PRESENT'):
                I['reject_excluded_npm_modules']([path], packages)
        for rendered in (0, 1):
            with self.assertRaisesRegex(ValueError, 'EXCLUDED_NPM_MODULE_PRESENT'):
                I['graph_notice_closure'](self.graph('@lix-js/sdk-darwin-arm64', rendered), packages)

    def test_optional_target_exclusion_retains_sri_and_never_downloads_archive(self):
        root = self.tmp / 'target-source'
        self.put(root / 'integrations/drizzli/build-plugins.json', b'{"plugins":[]}')
        output = self.tmp / 'target-candidate'; output.mkdir(mode=0o700)
        data = archive([('package/package.json', b'{"name":"svelte","version":"5.57.0"}', tarfile.REGTYPE)])
        value = lock(); value['packages']['node_modules/svelte']['integrity'] = sri(data)
        excluded = dict(version='1.0.0', resolved='https://registry.npmjs.org/darwin-only/-/darwin-only-1.0.0.tgz',
            integrity=sri(b'never downloaded'), optional=True, os=['darwin'], cpu=['arm64'])
        value['packages']['node_modules/darwin-only'] = excluded
        raw = json.dumps(value).encode(); source = dict(I['SOURCES']['drizzli'], sha256=I['sha'](raw))
        calls = []
        def download(url, _maximum, **_expected):
            calls.append(url)
            self.assertNotEqual(url, excluded['resolved'])
            return raw if url == source['url'] else data
        with patch.dict(G, ROOT=root, SOURCES={'drizzli': source}):
            result = I['candidate']('drizzli', output, downloader=download)
        self.assertEqual(len(calls), 2)
        entry = result['packages']['node_modules/darwin-only']
        self.assertEqual(entry['input']['integrity'], excluded['integrity'])
        self.assertEqual(entry['status'], 'excluded-for-target')
        self.assertNotIn('archive', entry)
        self.assertFalse(result['admitted'])

    def test_large_native_member_exception_is_exact_and_all_generic_bounds_stay(self):
        digest, name, size = I['LIX_ARCHIVE_SHA256'], I['LIX_MEMBER'], I['LIX_MEMBER_BYTES']
        self.assertTrue(I['approved_large_member'](digest, name, size, True))
        for args in (('0' * 64, name, size, True), (digest, name + '-other', size, True),
                     (digest, name, size + 1, True), (digest, name, size - 1, True),
                     (digest, name, size, False), (digest, name, size, 'true')):
            with self.subTest(args=args):
                self.assertFalse(I['approved_large_member'](*args))
        self.assertEqual(I['MAX_MEMBER'], 128 * 1024**2)
        self.assertEqual(I['MAX_ARCHIVE'], 96 * 1024**2)
        self.assertEqual(I['MAX_EXPANDED'], 512 * 1024**2)
        member = tarfile.TarInfo('package/' + name); member.size = size
        raw = gzip.compress(member.tobuf() + b'\0' * 1024)
        for npm in (True, False):
            with self.subTest(npm=npm), self.assertRaisesRegex(ValueError, 'ARCHIVE_MEMBER_BOUND'):
                I['archive_inventory'](raw, npm=npm)

    def test_shell_and_runtime_tool_packages_are_explicit_shared_candidate_roots(self):
        for profile, roots in A['PROFILES'].items():
            for name in ('bash', 'dash', 'coreutils', 'grep', 'sed', 'findutils', 'gzip', 'libc-bin'):
                with self.subTest(profile=profile, name=name):
                    self.assertEqual(roots.count(name), 1)
        self.assertFalse((ROOT / 'third_party/hosted-client-apt-v1.json').exists())

    def test_exact_inactive_musl_data_is_distinct_from_npm_native_exclusion(self):
        pins = I['npm_inactive_inputs']()
        packages = I['npm_lock'](I['read'](ROOT / 'third_party/client-locks/drizzli-package-lock.json'))
        self.assertEqual(len(pins), 2)
        for path, pin in pins.items():
            entry = packages[path]
            self.assertTrue(entry['inactive_optional_data'])
            self.assertNotIn('libc', entry)  # The original lock is not silently enriched.
            self.assertTrue(I['npm_target_selection'](entry)['included'])
            self.assertFalse(I['npm_target_selection'](dict(pin['archive_selectors'], optional=True))['included'])
            observed = [path + '/package.json', path + '/module.node']
            I['reject_excluded_npm_modules'](observed, packages)  # npm may install authenticated inactive data.
            with self.assertRaisesRegex(ValueError, 'INACTIVE_NPM_MODULE_CONTRIBUTION'):
                I['reject_inactive_npm_contributions'](observed, packages)
            with self.assertRaisesRegex(ValueError, 'INACTIVE_NPM_MODULE_CONTRIBUTION'):
                I['graph_notice_closure'](self.graph(pin['name']), packages)

    def test_inactive_selector_record_requires_exact_bytes_and_original_lock_binding(self):
        source = self.put(self.tmp / 'inactive.json', I['read'](I['NPM_INACTIVE_RECORD']) + b' ')
        with patch.dict(G, NPM_INACTIVE_RECORD=source), self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
            I['npm_inactive_inputs']()
        original = I['read'](ROOT / 'third_party/client-locks/drizzli-package-lock.json')
        for change in ('integrity', 'optional', 'libc'):
            value = json.loads(original)
            entry = value['packages']['node_modules/@tailwindcss/oxide-linux-x64-musl']
            entry[change] = sri(b'other') if change == 'integrity' else False if change == 'optional' else ['musl']
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'NPM_INACTIVE_LOCK_BINDING'):
                I['npm_lock'](json.dumps(value).encode())

    def test_changed_inactive_archive_cannot_be_labeled_inactive_data(self):
        raw = I['read'](ROOT / 'third_party/client-locks/drizzli-package-lock.json')
        packages = I['npm_lock'](raw)
        path = 'node_modules/@tailwindcss/oxide-linux-x64-musl'; entry = packages[path]
        manifest = dict(name=entry['name'], version=entry['version'], os=['linux'], cpu=['x64'], libc=['musl'])
        data = archive([('package/package.json', json.dumps(manifest).encode(), tarfile.REGTYPE)])
        output = self.tmp / 'inactive-failure'; output.mkdir(mode=0o700)
        with patch.dict(G, npm_lock=lambda _: {path: entry}), self.assertRaisesRegex(ValueError, 'NPM_INACTIVE_ARCHIVE_BINDING'):
            I['candidate']('drizzli', output, downloader=lambda url, *_args, **_kwargs:
                raw if url == I['SOURCES']['drizzli']['url'] else data)
        partial = json.loads((output / 'dependency-candidate.partial.json').read_bytes())
        self.assertFalse(partial['admitted'])
        self.assertEqual(partial['failed_input'], path)
        self.assertNotIn(path, partial['packages'])

    def test_npm_exact_urls_sri_versions_and_nested_paths(self):
        self.assertEqual(len(I['npm_lock'](json.dumps(lock()).encode())), 1)
        for field, value in [('resolved', 'https://registry.npmjs.org.evil/svelte/-/svelte-5.57.0.tgz'),
                ('resolved', 'https://user@registry.npmjs.org/svelte/-/svelte-5.57.0.tgz'),
                ('resolved', 'https://registry.npmjs.org:443/svelte/-/svelte-5.57.0.tgz'),
                ('resolved', 'https://registry.npmjs.org/svelte/-/svelte-5.57.0.tgz?x=1'),
                ('resolved', 'file:local'), ('integrity', 'sha256-' + 'a' * 44),
                ('integrity', sri() + ' ' + sri()), ('integrity', sri()[:-2] + 'A='),
                ('version', '^5.57.0'), ('version', '5.57.0-SNAPSHOT'), ('link', False)]:
            value_lock = lock()
            value_lock['packages']['node_modules/svelte'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                I['npm_lock'](json.dumps(value_lock).encode())
        for path in ('../node_modules/svelte', 'node_modules/../svelte', 'node_modules/svelte/extra', '/node_modules/svelte'):
            value = lock(); value['packages'][path] = value['packages'].pop('node_modules/svelte')
            with self.subTest(path=path), self.assertRaises(ValueError):
                I['npm_lock'](json.dumps(value).encode())
        raw = b'{"lockfileVersion":3,"lockfileVersion":3,"packages":{}}'
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_KEY'):
            I['npm_lock'](raw)
        value = lock(); value['lockfileVersion'] = True
        with self.assertRaisesRegex(ValueError, 'SCHEMA'):
            I['npm_lock'](json.dumps(value).encode())

    def test_pub_fixed_host_hash_duplicate_sdk_and_yaml_failures(self):
        self.assertEqual(I['pub_lock'](pub())['a']['sha256'], 'a' * 64)
        for raw in (pub().replace(b'https://pub.dev', b'https://pub.dev.evil'),
                pub().replace(b'https://pub.dev', b'https://pub.dev/'),
                pub().replace(b'a' * 64, b'a' * 63),
                pub().replace(b'    source: hosted', b'    source: hosted\n    source: hosted'),
                pub().replace(b'  a:\n', b'  a: &anchor\n'),
                pub().replace(b'description:\n', b'description: !tag\n'),
                pub().replace(b'    source: hosted', b'    source: git'),
                pub('not_an_sdk', 'sdk'),
                pub().replace(b'    version: "1.0.0"', b'    version: ">=1.0.0"')):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                I['pub_lock'](raw)

    def test_archive_members_original_notices_package_metadata_and_links(self):
        value = I['archive_inventory'](archive([
            ('package', b'', tarfile.DIRTYPE), ('package/package.json', b'{"name":"svelte","version":"5.57.0"}', tarfile.REGTYPE),
            ('package/LICENSE', b'complete original copyright\n', tarfile.REGTYPE),
            ('package/dist/index.js', b'export default 1;', tarfile.REGTYPE)]), npm=True)
        self.assertEqual(value['files']['LICENSE']['notice_text'], 'complete original copyright\n')
        self.assertEqual(value['files']['package.json']['package_json']['name'], 'svelte')
        self.assertIn('dist/index.js', value['files'])
        for entries in ([('package/../escape', b'x', tarfile.REGTYPE)],
                [('package/link', b'', tarfile.SYMTYPE)], [('package/link', b'', tarfile.LNKTYPE)],
                [('package/LICENSE', b'a', tarfile.REGTYPE), ('package/LICENSE', b'b', tarfile.REGTYPE)],
                [('other/LICENSE', b'x', tarfile.REGTYPE)]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                I['archive_inventory'](archive(entries), npm=True)
        with patch.dict(G, MAX_EXPANDED=1), self.assertRaisesRegex(ValueError, 'EXPANSION'):
            I['archive_inventory'](archive([('file', b'123', tarfile.REGTYPE)]), npm=False)

    def test_types_tar_root_is_bound_to_exact_locked_package_name(self):
        entries = [('chai', b'', tarfile.DIRTYPE),
            ('chai/package.json', b'{"name":"@types/chai","version":"5.2.3"}', tarfile.REGTYPE),
            ('chai/index.d.ts', b'type Example = number;', tarfile.REGTYPE)]
        result = I['archive_inventory'](archive(entries), npm=True, npm_name='@types/chai')
        self.assertEqual(result['npm_root'], 'chai')
        self.assertEqual(set(result['files']), {'package.json', 'index.d.ts'})
        for package_name in (None, '@types/other', 'chai'):
            with self.subTest(package_name=package_name), self.assertRaisesRegex(ValueError, 'NPM_ARCHIVE_ROOT'):
                I['archive_inventory'](archive(entries), npm=True, npm_name=package_name)
        for extra in (('package/other', b'x', tarfile.REGTYPE), ('chai/../escape', b'x', tarfile.REGTYPE)):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                I['archive_inventory'](archive(entries + [extra]), npm=True, npm_name='@types/chai')

    def test_read_rejects_writable_symlink_hardlink_and_bounds(self):
        path = self.put(self.tmp / 'value', b'123')
        with self.assertRaisesRegex(ValueError, 'UNSAFE'):
            I['read'](path, 2)
        path.chmod(0o660)
        with self.assertRaisesRegex(ValueError, 'UNSAFE'):
            I['read'](path)
        path.chmod(0o600)
        os.link(path, self.tmp / 'hard')
        with self.assertRaisesRegex(ValueError, 'UNSAFE'):
            I['read'](path)
        (self.tmp / 'link').symlink_to(path)
        with self.assertRaises(OSError):
            I['read'](self.tmp / 'link')

    def test_static_lock_missing_and_forged_candidate_rejected(self):
        path = self.tmp / 'lock.json'
        with patch.dict(G, LOCK=path), self.assertRaises(FileNotFoundError):
            I['load_build_lock']('drizzli')
        for admitted in (False, True):
            self.put(path, json.dumps(dict(schema=1, kind='volparossa-weather-client-input-candidate', admitted=admitted)).encode())
            with patch.dict(G, LOCK=path), self.assertRaisesRegex(ValueError, 'NOT_ADMITTED'):
                I['load_build_lock']('drizzli')
        self.assertFalse((ROOT / 'third_party/hosted-client-inputs-v1.json').exists())
        self.assertFalse((ROOT / 'third_party/hosted-client-apt-v1.json').exists())

    def graph(self, package, rendered=1):
        return [dict(schema=1, kind='volparossa-drizzli-module-graph', admitted=False, format='es', plugins=['svelte'], outputs={
            'chunk.js': dict(type='chunk', modules=[dict(id='node_modules/' + package + '/index.js', kind='file', renderedLength=rendered)])})]

    def test_original_svelte_and_graph_required_notice_closure(self):
        packages = I['npm_lock'](I['read'](ROOT / 'third_party/client-locks/drizzli-package-lock.json'))
        result = I['graph_notice_closure'](self.graph('svelte'), packages)
        self.assertIn('06257f4847b13a49a039efb17b944c141e71b12fd8d231b362d86919067d77a3', result)
        self.assertEqual(len(result['06257f4847b13a49a039efb17b944c141e71b12fd8d231b362d86919067d77a3']), 1126)
        for name in ('is-reference', 'locate-character'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'UNRESOLVED_RUNTIME_NOTICE'):
                I['graph_notice_closure'](self.graph(name), packages)
            self.assertEqual(I['graph_notice_closure'](self.graph(name, rendered=0), packages), {})
        graph = self.graph('svelte'); graph[0]['outputs']['chunk.js']['modules'][0].update(kind='virtual', id='\0unknown', producer=None)
        with self.assertRaisesRegex(ValueError, 'UNREVIEWED_VIRTUAL'):
            I['graph_notice_closure'](graph, packages)
        with self.assertRaisesRegex(ValueError, 'UNLOCKED_OUTPUT'):
            I['graph_notice_closure'](self.graph('unlisted'), packages)

    def test_exact_font_notices_and_separate_new_recipe_flags(self):
        notices, _ = I['notice_inputs']()
        material = notices['fonts']['MaterialIcons']
        self.assertEqual(material['license'], 'CC-BY-4.0')
        self.assertFalse(material['modified'])
        attribution = I['read'](ROOT / material['attribution']).decode()
        self.assertIn('Copyright 2019 Google LLC.', attribution)
        self.assertIn('https://creativecommons.org/licenses/by/4.0/', attribution)
        self.assertIn('full font unchanged', attribution)
        self.assertEqual(notices['fonts']['NotoSans']['bytes'], 4396)
        build = runpy.run_path(str(ROOT / 'integrations/overmorrow/build.py'))
        self.assertNotIn('--no-tree-shake-icons', build['ACTIONS']['build'])
        self.assertEqual(build['source_web_arguments'](), build['ACTIONS']['build'] + ['--no-tree-shake-icons'])
        sdk = self.tmp / 'sdk'; self.put(sdk / 'bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf', b'unreviewed font')
        with self.assertRaisesRegex(ValueError, 'MATERIAL_FONT_NOT_PINNED'):
            I['full_material_font'](sdk)

    def test_final_output_inventory_includes_assets_and_rejects_change_links(self):
        self.put(self.tmp / 'output/app.js', b'js')
        self.put(self.tmp / 'output/style.css', b'css')
        self.put(self.tmp / 'output/assets/font.otf', b'font')
        before = I['output_inventory'](self.tmp / 'output')
        self.assertEqual(set(before), {'app.js', 'style.css', 'assets/font.otf'})
        self.put(self.tmp / 'output/style.css', b'changed')
        self.assertNotEqual(before, I['output_inventory'](self.tmp / 'output'))
        (self.tmp / 'output/assets/link').symlink_to(self.tmp / 'output/app.js')
        with self.assertRaisesRegex(ValueError, 'LINK_OR_SPECIAL'):
            I['output_inventory'](self.tmp / 'output')

    def test_projection_closed_metadata_only_and_candidate_false(self):
        root = self.tmp / 'checkout'; source = root / 'build/hosted-drizzli-input-candidate'
        self.put(source / 'result.json', b'{"admitted":false,"phase":"failed"}')
        self.put(source / 'apt-private/anything.deb', b'ar binary data')
        self.put(source / 'extra.json', b'{"admitted":false}')
        with patch.dict(G, ROOT=root):
            dest = I['project_metadata']('drizzli')
        self.assertEqual({p.name for p in dest.iterdir()}, {'result.json', 'projection.json'})
        projection = json.loads((dest / 'projection.json').read_bytes())
        self.assertFalse(projection['binaries_exported'])
        other = root / 'build/hosted-overmorrow-input-candidate'
        self.put(other / 'result.json', b'{"admitted":true}')
        with patch.dict(G, ROOT=root), self.assertRaisesRegex(ValueError, 'AUTHORITY'):
            I['project_metadata']('overmorrow')

    def test_projection_preserves_both_original_locks_without_candidate_fields(self):
        for profile, spec in I['SOURCES'].items():
            with self.subTest(profile=profile):
                root = self.tmp / profile
                source = root / 'build' / ('hosted-' + profile + '-input-candidate')
                raw = I['read'](ROOT / 'third_party/client-locks' / (profile + '-' + spec['lock']))
                self.put(source / spec['lock'], raw)
                self.put(source / 'result.json', b'{"admitted":false,"phase":"complete"}')
                with patch.dict(G, ROOT=root):
                    destination = I['project_metadata'](profile)
                self.assertEqual((destination / spec['lock']).read_bytes(), raw)
                projection = json.loads((destination / 'projection.json').read_bytes())
                self.assertEqual(projection['files'][spec['lock']],
                    dict(bytes=len(raw), sha256=spec['sha256']))
                self.assertFalse(projection['admitted'])

    def test_projection_rejects_modified_and_wrong_profile_locks(self):
        for profile, spec in I['SOURCES'].items():
            raw = I['read'](ROOT / 'third_party/client-locks' / (profile + '-' + spec['lock']))
            for case, value, candidate_profile in (
                    ('changed', raw + b'\n', profile),
                    ('forged-candidate', b'{"admitted":false}', profile),
                    ('wrong-profile', raw, 'overmorrow' if profile == 'drizzli' else 'drizzli')):
                with self.subTest(profile=profile, case=case):
                    root = self.tmp / (profile + '-' + case)
                    source = root / 'build' / ('hosted-' + candidate_profile + '-input-candidate')
                    self.put(source / spec['lock'], value)
                    self.put(source / 'result.json', b'{"admitted":false}')
                    with patch.dict(G, ROOT=root), self.assertRaisesRegex(ValueError, 'PUBLIC_SOURCE_LOCK'):
                        I['project_metadata'](candidate_profile)

    def test_ubuntu_release_and_exact_snapshot_uri_rules(self):
        raw = (b'-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\nSuite: noble-security\nCodename: noble\nArchitectures: amd64 arm64\nSHA256:\n ' + b'a' * 64 + b' 12 main/binary-amd64/Packages\n-----BEGIN PGP SIGNATURE-----\nsignature-data\n')
        self.assertEqual(A['authenticated_release'](raw, 'noble-security')['main/binary-amd64/Packages']['bytes'], 12)
        with self.assertRaisesRegex(ValueError, 'IDENTITY'):
            A['authenticated_release'](raw, 'noble')
        url = A['BASE'] + 'pool/main/a/a/a_1.0_amd64.deb'
        line = "'" + url + "' a_1.0_amd64.deb 123 SHA256:" + 'a' * 64
        self.assertEqual(A['validate_uri_line'](line)['bytes'], 123)
        for bad in (line.replace(A['BASE'], 'https://archive.ubuntu.com/ubuntu/'),
                line.replace('/pool/', '/pool/../'), line.replace('SHA256:', 'MD5Sum:'),
                line.replace('/pool/main/', '/pool/unreviewed/'), line.replace('.deb\'', '.deb?x=1\'')):
            with self.subTest(line=bad), self.assertRaises(ValueError):
                A['validate_uri_line'](bad)

    def test_observed_apt_quoted_plus_and_tilde_preserve_url_and_signed_filename(self):
        filename = 'pool/main/x/xz-utils/example_1.0+dfsg~24.04_amd64.deb'
        url = A['BASE'] + filename.replace('+', '%2b').replace('~', '%7e')
        line = "'" + url + "' example_1%3a1.0+dfsg~24.04_amd64.deb 123 SHA256:" + 'a' * 64
        result = A['validate_uri_line'](line)
        self.assertEqual(result['url'], url)
        self.assertEqual(result['filename'], filename)
        for encoded in ('%252b', '%2f', '%2e%2e', '%23', '%3f', '%3a', '%2B', '%7E'):
            with self.subTest(encoded=encoded), self.assertRaisesRegex(ValueError, 'APT_URI'):
                A['validate_uri_line'](line.replace('%2b', encoded))

    def test_debian_archive_root_header_is_directory_only(self):
        for name in ('.', './'):
            root = tarfile.TarInfo(name)
            root.type = tarfile.DIRTYPE
            self.assertIsNone(A['package_member_name'](root))
            for kind in (tarfile.REGTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE):
                root.type = kind
                with self.subTest(name=name, kind=kind), self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
                    A['package_member_name'](root)
        for name in ('', '/', './/', '././', './..', './usr/../escape', '/usr'):
            root = tarfile.TarInfo(name)
            root.type = tarfile.DIRTYPE
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
                A['package_member_name'](root)
        self.assertEqual(A['package_member_name'](tarfile.TarInfo('./usr/share/doc/copyright')),
                         'usr/share/doc/copyright')

    def test_snapshot_keyring_bytes_are_authority_before_exclusive_private_copy(self):
        raw = b'exact public keyring fixture'
        source = self.put(self.tmp / 'system-keyring', raw)
        source.chmod(0o666)
        os.link(source, self.tmp / 'system-keyring-alias')
        private = self.tmp / 'private'; private.mkdir(mode=0o700)
        globals_ = A['pinned_keyring'].__globals__
        with patch.dict(globals_, KEYRING=source, KEYRING_BYTES=len(raw), KEYRING_SHA256=I['sha'](raw)):
            copy, observation = A['pinned_keyring'](private)
            self.assertEqual(I['read'](copy), raw)
            self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o600)
            self.assertEqual(copy.stat().st_nlink, 1)
            self.assertEqual(observation['source_links'], 2)
            self.assertEqual(observation['source_mode'], 0o666)
            with self.assertRaises(FileExistsError):
                A['pinned_keyring'](private)
            source.write_bytes(b'x' * len(raw))
            with self.assertRaisesRegex(ValueError, 'KEYRING_BYTES'):
                A['pinned_keyring'](private)
            source.write_bytes(raw + b'x')
            with self.assertRaisesRegex(ValueError, 'TYPE_OR_SIZE'):
                A['pinned_keyring'](private)
            source.unlink(); source.symlink_to(self.tmp / 'system-keyring-alias')
            with self.assertRaises(OSError):
                A['pinned_keyring'](private)

    def test_snapshot_keyring_rejects_special_files_without_blocking(self):
        source = self.tmp / 'fifo'
        os.mkfifo(source)
        with patch.dict(A['pinned_keyring'].__globals__, KEYRING=source), self.assertRaisesRegex(ValueError, 'TYPE_OR_SIZE'):
            A['pinned_keyring'](self.tmp)

    def test_debian_posix_metadata_keeps_exact_unicode_and_literal_backslashes(self):
        paths = ('usr/lib/systemd/system/system-systemd\\x2dcryptsetup.slice',
                 'usr/share/ca-certificates/mozilla/NetLock_Arany_=Class_Gold=_Főtanúsítvány.crt')
        for path in paths:
            self.assertEqual(A['package_member_name'](tarfile.TarInfo('./' + path)), path)
            with self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
                I['safe_path'](path)  # The generic acquisition-path policy is unchanged.
        for path in ('usr/../escape', 'usr//file', '/usr/file', 'usr/./file', 'usr/file/',
                     'usr/\x00file', 'usr/\x1ffile', 'usr/\x7ffile', 'usr/\x85file',
                     'usr/\u202efile', 'usr/\ud800file'):
            with self.subTest(path=repr(path)), self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
                A['package_member_name'](tarfile.TarInfo(path))
        for exact in ('usr/cafe\u0301', 'usr/café', r'usr/\x2e\x2e'):
            self.assertEqual(A['package_member_name'](tarfile.TarInfo(exact)), exact)

    def test_candidate_completed_and_partial_archives_stay_unadmitted(self):
        root = self.tmp / 'source'
        self.put(root / 'integrations/drizzli/build-plugins.json', b'{"plugins":[]}')
        for bad in (False, True):
            output = self.tmp / ('partial' if bad else 'complete'); output.mkdir(mode=0o700)
            data = archive([('package/package.json', json.dumps(dict(name='wrong' if bad else 'svelte', version='5.57.0')).encode(), tarfile.REGTYPE),
                            ('package/LICENSE', b'original notice', tarfile.REGTYPE)])
            value = lock(); value['packages']['node_modules/svelte']['integrity'] = sri(data)
            raw = json.dumps(value).encode()
            source = dict(I['SOURCES']['drizzli'], sha256=I['sha'](raw))
            def download(url, maximum, **expected):
                result = raw if url == source['url'] else data
                self.assertLessEqual(len(result), maximum)
                if 'sha256' in expected:
                    self.assertEqual(I['sha'](result), expected['sha256'])
                if 'integrity' in expected:
                    self.assertEqual(sri(result), expected['integrity'])
                return result
            with patch.dict(G, ROOT=root, SOURCES={'drizzli': source}):
                if bad:
                    with self.assertRaisesRegex(ValueError, 'ARCHIVE_IDENTITY'):
                        I['candidate']('drizzli', output, downloader=download)
                    partial = json.loads((output / 'dependency-candidate.partial.json').read_bytes())
                    self.assertFalse(partial['admitted'])
                    self.assertEqual(partial['failed_input'], 'node_modules/svelte')
                    self.assertFalse((output / 'dependency-candidate.json').exists())
                else:
                    result = I['candidate']('drizzli', output, downloader=download)
                    self.assertFalse(result['admitted'])
                    self.assertFalse(result['compiled'])
                    self.assertFalse(result['dependencies_executed'])
                    self.assertEqual(result['packages']['node_modules/svelte']['archive']['bytes'], len(data))

    def test_fetch_rejects_changed_hash_integrity_size_and_origin(self):
        raw = b'input bytes'; url = 'https://registry.npmjs.org/a/-/a-1.0.0.tgz'
        class Response:
            status = 200
            headers = {'Content-Length': str(len(raw)), 'Content-Encoding': 'identity'}
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self, _):
                return raw
        response = Response(); response.url = url
        class Opener:
            def open(self, *_args, **_kwargs):
                return response
        with patch.object(I['urllib'].request, 'build_opener', return_value=Opener()):
            self.assertEqual(I['fetch'](url, 100, sha256=I['sha'](raw), integrity=sri(raw)), raw)
            for kwargs in ({'sha256': 'a' * 64}, {'integrity': sri(b'changed')}):
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_'):
                    I['fetch'](url, 100, **kwargs)
            with self.assertRaisesRegex(ValueError, 'INPUT_LENGTH'):
                I['fetch'](url, 1)
            response.url = 'https://other/changed'
            with self.assertRaisesRegex(ValueError, 'INPUT_RESPONSE'):
                I['fetch'](url, 100)

    def test_cancellation_has_a_typed_failure_for_partial_evidence(self):
        with self.assertRaisesRegex(InterruptedError, 'CLIENT_INPUT_INTERRUPTED'):
            I['interrupted'](15, None)
        source = (ROOT / 'scripts/prepare_hosted_client_inputs.py').read_text()
        self.assertIn('signal.signal(sig, interrupted)', source)
        self.assertIn('signal.signal(sig, handler)', source)
        self.assertIn("write(output / 'result.json'", source)

    def test_host_context_and_redirect_are_rejected_before_acquisition(self):
        with patch.object(os, 'getuid', return_value=1000), patch.object(os, 'geteuid', return_value=1000), self.assertRaisesRegex(ValueError, 'DISPOSABLE'):
            I['hosted_guard']({}, 'drizzli')
        valid = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
            GITHUB_REPOSITORY='VOLPAROSSA/volparossa-weather', GITHUB_WORKSPACE=str(ROOT), RUNNER_ARCH='X64',
            GITHUB_WORKFLOW='Build hosted Weather clients', GITHUB_SHA='a' * 40, ImageOS='ubuntu24', ImageVersion='20261023.1.0')
        with patch.object(os, 'getuid', return_value=1000), patch.object(os, 'geteuid', return_value=1000), \
                patch.object(Path, 'read_text', return_value='ID=ubuntu\nVERSION_ID="24.04"\n'):
            I['hosted_guard'](valid, 'drizzli')
            valid.pop('ImageVersion')
            with self.assertRaisesRegex(ValueError, 'IMAGE_VERSION'):
                I['hosted_guard'](valid, 'drizzli')
        with self.assertRaisesRegex(ValueError, 'REDIRECT'):
            I['NoRedirect']().redirect_request(None, None, None, None, None, 'https://other/')

    def test_candidate_workflows_skip_all_builds_and_close_upload(self):
        for profile, name in (('drizzli', 'hosted-clients.yml'), ('overmorrow', 'hosted-overmorrow.yml')):
            source = (ROOT / '.github/workflows' / name).read_text()
            historical, candidate = source.split('\n  input-candidate:', 1)
            self.assertIn("if: github.event.inputs.input_mode != 'source-input-inventory'", historical)
            self.assertIn("options: [historical-v1, source-input-inventory]", historical)
            self.assertIn('timeout-minutes: 30', candidate)
            self.assertIn(f'--profile {profile} --mode source-input-inventory', candidate)
            self.assertIn(f'--profile {profile} --mode stage-input-metadata', candidate)
            self.assertIn(f'path: build/hosted-{profile}-input-candidate-public', candidate)
            for forbidden in ('sudo', 'npm ci', 'prepare_hosted_flutter.py', 'prepare_hosted_runtime.py',
                              'prepare_hosted_clients_ci.py', 'prepare_hosted_overmorrow_ci.py', 'gh run download',
                              'upload-artifact@master', 'cache@', '*.json', 'firefox-hosted-ci'):
                self.assertNotIn(forbidden, candidate)

    def test_signature_status_requires_success_fingerprints_without_failures(self):
        good = b'[GNUPG:] VALIDSIG ' + b'A' * 40 + b' 2026-10-23 123 0 4 0 1 8 01 ' + b'B' * 40 + b'\n'
        self.assertEqual(A['signature_identities'](good), [dict(subkey='A' * 40, primary='B' * 40)])
        for bad in (b'', good + good, good + b'[GNUPG:] BADSIG abcd\n', good.replace(b'A' * 40, b'A' * 39),
                    good + b'[GNUPG:] NO_PUBKEY abcd\n', good + b'[GNUPG:] EXPKEYSIG abcd\n'):
            with self.subTest(status=bad[:80]), self.assertRaisesRegex(ValueError, 'UBUNTU_SIGNATURE'):
                A['signature_identities'](bad)

    def test_apt_candidate_has_no_install_or_global_repo_write(self):
        source = (ROOT / 'scripts/prepare_hosted_client_apt.py').read_text()
        self.assertIn("I.write(private / 'status', b'')", source)
        self.assertIn("'--print-uris', '--yes', '--download-only'", source)
        self.assertIn("'Acquire::https::AllowRedirect=false'", source)
        self.assertNotIn('sudo', source)
        self.assertNotIn('/etc/apt/sources.list', source)
        self.assertNotIn("'--allow-unauthenticated'", source)
        self.assertIn('installed=False, compiled=False', source)
        self.assertIn('installed-file-config-alternatives-binding-required-before-build', source)


if __name__ == '__main__':
    unittest.main()
