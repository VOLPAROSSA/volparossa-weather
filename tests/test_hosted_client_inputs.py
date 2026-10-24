# SPDX-License-Identifier: GPL-3.0-only
"""Inert source/data tests; never invoke Node, Flutter, APT or downloaded code."""
import base64
import copy
import hashlib
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
