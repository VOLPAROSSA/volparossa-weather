# SPDX-License-Identifier: GPL-3.0-only
"""Inert package provisioning tests: never invoke sudo/APT or package code."""
import copy
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
I = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_inputs.py'))
IG = I['main'].__globals__
A = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_client_apt.py'))
AG = A['installed_inventory'].__globals__


class ClientEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, raw=b'data', mode=0o600):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_bytes(raw)
        p.chmod(mode)
        return p

    def packages(self):
        return [dict(identity=['demo', '1.2-3', 'amd64'], files={'usr/bin/demo':
            dict(type='file', bytes=4, sha256=I['sha'](b'data'), mode=0o600)})]

    def plan(self):
        return b'Inst demo [1.0] (1.2-3 local-deb [amd64]) [other:amd64 ]\nConf demo (1.2-3 local-deb [amd64]) []\n'

    def cache_fixture(self, name='private'):
        private = self.root / name
        for path in (private, private / 'archives', private / 'archives/partial'):
            path.mkdir(mode=0o700)
        (private / '0.deb').write_bytes(b'data')
        (private / '0.deb').chmod(0o600)
        packages = self.packages()
        packages[0]['input'] = dict(bytes=4, sha256=I['sha'](b'data'))
        return private, packages

    def test_offline_cache_name_matches_apt_epoch_and_underscore_quoting(self):
        self.assertEqual(A['archive_cache_name'](['git', '1:2.43.0-1ubuntu7.4', 'amd64']),
            'git_1%3a2.43.0-1ubuntu7.4_amd64.deb')
        self.assertEqual(A['archive_cache_name'](['demo', '2:1.0_test+2~old', 'all']),
            'demo_2%3a1.0%5ftest+2~old_all.deb')
        for identity in (['../demo', '1', 'amd64'], ['demo', '../1', 'all'], ['demo', '1', '../all']):
            with self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_IDENTITY'):
                A['archive_cache_name'](identity)

    def test_offline_cache_copies_are_exclusive_independent_absolute_and_rehashed(self):
        private, packages = self.cache_fixture()
        A['stage_archive_cache'](private, packages)
        paths = A['verified_cached_packages'](private, packages)
        expected = private / 'archives/demo_1.2-3_amd64.deb'
        self.assertEqual(paths, [str(expected)])
        self.assertTrue(expected.is_absolute())
        self.assertEqual(expected.read_bytes(), b'data')
        self.assertNotEqual(expected.stat().st_ino, (private / '0.deb').stat().st_ino)
        self.assertEqual(expected.stat().st_nlink, 1)
        with self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_NOT_EMPTY'):
            A['stage_archive_cache'](private, packages)
        expected.write_bytes(b'edit')
        with self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_CHANGED'):
            A['verified_cached_packages'](private, packages)
        self.assertEqual((private / '0.deb').read_bytes(), b'data')

    def test_offline_cache_rejects_alias_hardlink_mode_extra_and_original_changes(self):
        for problem in ('symlink', 'hardlink', 'mode', 'extra', 'original'):
            private, packages = self.cache_fixture(problem)
            A['stage_archive_cache'](private, packages)
            path = private / 'archives/demo_1.2-3_amd64.deb'
            if problem == 'symlink':
                path.unlink(); path.symlink_to(private / '0.deb')
            elif problem == 'hardlink':
                os.link(path, private / 'second-link')
            elif problem == 'mode':
                path.chmod(0o666)
            elif problem == 'extra':
                (private / 'archives/unreviewed.deb').write_bytes(b'data')
            else:
                (private / '0.deb').write_bytes(b'edit')
            with self.subTest(problem=problem), self.assertRaises((ValueError, OSError)):
                if problem == 'original':
                    A['verified_local_packages'](private, packages)
                else:
                    A['verified_cached_packages'](private, packages)

    def test_cache_partial_and_lock_aliases_never_reach_privileged_apt(self):
        for alias in ('partial', 'lock'):
            private, packages = self.cache_fixture(alias)
            if alias == 'lock':
                A['stage_archive_cache'](private, packages)
            path = private / 'archives' / alias
            if alias == 'partial':
                path.rmdir()
            path.symlink_to(self.root)
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_'):
                if alias == 'partial':
                    A['stage_archive_cache'](private, packages)
                else:
                    A['verified_cached_packages'](private, packages)
            self.assertTrue(path.is_symlink())

    def test_interrupted_cache_copy_and_replaced_directory_preserve_recovery(self):
        private, packages = self.cache_fixture('interrupted')
        original = AG['I'].read
        original_fdopen = os.fdopen
        @contextmanager
        def interrupted_writer(fd, mode):
            with original_fdopen(fd, mode) as stream:
                def truncated_write(raw):
                    stream.write(raw[:2])
                    raise InterruptedError('cancel')
                yield SimpleNamespace(write=truncated_write)
        def open_stream(fd, mode):
            return interrupted_writer(fd, mode) if mode == 'wb' else original_fdopen(fd, mode)
        with patch.object(os, 'fdopen', side_effect=open_stream), \
                self.assertRaises(InterruptedError):
            A['stage_archive_cache'](private, packages)
        self.assertEqual((private / '0.deb').read_bytes(), b'data')
        self.assertEqual((private / 'archives/demo_1.2-3_amd64.deb').read_bytes(), b'da')
        with self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_FILE'):
            A['verified_cached_packages'](private, packages)
        private, packages = self.cache_fixture('replaced')
        reads = 0
        def replace_cache(path, *args):
            nonlocal reads
            reads += 1
            raw = original(path, *args)
            if reads == 2:
                (private / 'archives').rename(private / 'original-archives')
                (private / 'archives').mkdir(mode=0o700)
            return raw
        with patch.object(AG['I'], 'read', side_effect=replace_cache), self.assertRaisesRegex(ValueError, 'LOCAL_CACHE_REPLACED'):
            A['stage_archive_cache'](private, packages)
        self.assertEqual((private / 'original-archives/demo_1.2-3_amd64.deb').read_bytes(), b'data')
        self.assertEqual(list((private / 'archives').iterdir()), [])

    def test_fixed_reviewed_input_record_authorizes_only_package_provisioning(self):
        record = I['load_package_inputs']('drizzli')
        self.assertTrue(record['package_inputs_authorized'])
        for key in ('admitted', 'build_environment_admitted', 'consumer_admitted'):
            self.assertIs(record[key], False)
        self.assertEqual(len(record['apt']['packages']), 227)
        self.assertEqual(len(record['dependencies']['packages']), 347)
        self.assertEqual(sum(v['status'] == 'excluded-for-target' for v in record['dependencies']['packages'].values()), 47)
        self.assertEqual(sum(v['status'] == 'inactive-optional-data' for v in record['dependencies']['packages'].values()), 2)
        self.assertEqual(len(I['load_package_inputs']('overmorrow')['apt']['packages']), 235)
        with self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
            I['load_package_inputs']('android')
        with self.assertRaises(FileNotFoundError):
            I['load_build_lock']('drizzli')
        with patch.dict(IG, ROOT=self.root):
            with self.assertRaises(FileNotFoundError):
                I['load_package_inputs']('drizzli')
            self.put('third_party/client-package-inputs-drizzli-v1.json', b'{}')
            with self.assertRaisesRegex(ValueError, 'INPUTS_CHANGED'):
                I['load_package_inputs']('drizzli')

    def test_companions_preserve_original_records_with_fixed_narrow_authority(self):
        record = A['load_installer_companions']()
        self.assertEqual(len(record['packages']), 7)
        self.assertEqual(record['base_inputs'], {p: dict(file=f, sha256=h) for p, (f, h) in I['PACKAGE_INPUTS'].items()})
        self.assertEqual(record['repositories'], A['SUITES'])
        for profile in ('drizzli', 'overmorrow'):
            base = I['load_package_inputs'](profile)
            self.assertFalse({p['identity'][0] for p in base['apt']['packages']} & A['COMPANION_NAMES'])
        filename, digest = A['COMPANION_INPUT']
        self.assertEqual(I['sha']((ROOT / 'third_party' / filename).read_bytes()), digest)
        with patch.dict(AG, ROOT=self.root):
            self.put('third_party/' + filename, b'{}')
            with self.assertRaisesRegex(ValueError, 'COMPANION_INPUTS_CHANGED'):
                A['load_installer_companions']()
        self.assertIn('installer-companions.json', I['PUBLIC_NAMES'])
        recipe = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_source_recipe.py'))
        for profile in ('drizzli', 'overmorrow'):
            self.assertIn('third_party/' + filename, recipe['PROFILES'][profile])
            sizes = [(ROOT / name).stat().st_size for name in recipe['PROFILES'][profile]]
            self.assertLessEqual(max(sizes), recipe['MAX_FILE'])
            self.assertLessEqual(sum(sizes), recipe['MAX_TOTAL'])

    def test_companion_origin_rejects_changed_dependency_index_identity_or_archive(self):
        expected = copy.deepcopy(A['load_installer_companions']()['packages'][0])
        key = tuple(expected['identity'])
        rows = [dict(suite=o['suite'], index=o['path'], Filename=expected['input']['filename'],
            Size=str(expected['input']['bytes']), SHA256=expected['input']['sha256'], control=expected['control'])
            for o in expected['indexed_origins']]
        A['bind_companion_origin'](expected, {key: rows})
        for field in ('suite', 'index', 'Filename', 'Size', 'SHA256', 'control'):
            changed = copy.deepcopy(rows)
            changed[0][field] = {} if field == 'control' else '0'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'COMPANION_INDEX_CHANGED'):
                A['bind_companion_origin'](expected, {key: changed})
        with self.assertRaisesRegex(ValueError, 'COMPANION_INDEX_CHANGED'):
            A['bind_companion_origin'](expected, {})
        changed = copy.deepcopy(expected); changed['input']['url'] += '?override'
        with self.assertRaisesRegex(ValueError, 'COMPANION_URL_CHANGED'):
            A['bind_companion_origin'](changed, {key: rows})

    def test_companion_receipt_rebinds_complete_maps_and_authority_before_union(self):
        record = dict(packages=[dict(identity=['demo', '1.2-3', 'amd64'],
            input={'sha256': 'a' * 64}, files_sha256=I['sha'](I['canonical'](self.packages()[0]['files'])))])
        receipt = dict(schema=1, admitted=False, package_inputs_authorized=True,
            build_environment_admitted=False, consumer_admitted=False,
            input_sha256=A['COMPANION_INPUT'][1], packages=[dict(self.packages()[0], input={'sha256': 'a' * 64})])
        A['bind_installer_companions'](receipt, record)
        for field in ('admitted', 'package_inputs_authorized', 'build_environment_admitted', 'consumer_admitted',
                'input_sha256', 'packages', 'schema'):
            bad = copy.deepcopy(receipt)
            bad[field] = True if field == 'schema' else ([] if field == 'packages' else not bad[field])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'COMPANION_RECEIPT_CHANGED'):
                A['bind_installer_companions'](bad, record)
        for field in ('bytes', 'sha256', 'mode'):
            bad = copy.deepcopy(receipt); bad['packages'][0]['files']['usr/bin/demo'][field] = 0
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'COMPANION_RECEIPT_CHANGED'):
                A['bind_installer_companions'](bad, record)
        union = I['load_package_inputs']('drizzli')['apt']['packages'] + A['load_installer_companions']()['packages']
        raw = b''.join((f"{action} {p['identity'][0]} ({p['identity'][1]} local-deb [{p['identity'][2]}])\n").encode()
            for action in ('Inst', 'Conf') for p in union)
        self.assertEqual(len(A['validate_install_simulation'](raw, union)['Inst']), 234)
        for changed in (raw.replace(b'Conf udev ', b'Conf extra ', 1), raw + b'Remv udev [old]\n'):
            with self.assertRaisesRegex(ValueError, 'INSTALL_PLAN_'):
                A['validate_install_simulation'](changed, union)

    def test_changed_authority_candidate_types_and_runtime_are_not_accepted(self):
        record = I['load_package_inputs']('drizzli')
        filename = I['PACKAGE_INPUTS']['drizzli'][0]
        for key, value in [('schema', True), ('admitted', True), ('package_inputs_authorized', 1),
                ('consumer_admitted', True), ('build_environment_admitted', True), ('profile', 'overmorrow')]:
            changed = copy.deepcopy(record); changed[key] = value
            raw = I['canonical'](changed)
            pins = dict(drizzli=(filename, I['sha'](raw)))
            with self.subTest(key=key), patch.dict(IG, PACKAGE_INPUTS=pins, read=Mock(return_value=raw)), \
                    self.assertRaisesRegex(ValueError, 'INPUTS_SCHEMA'):
                I['load_package_inputs']('drizzli')
        with patch.dict(IG, read=Mock(side_effect=[I['canonical'](record), b'changed'])), \
                patch.dict(IG, PACKAGE_INPUTS=dict(drizzli=(filename, I['sha'](I['canonical'](record))))), \
                self.assertRaisesRegex(ValueError, 'RUNTIME_CHANGED'):
            I['load_package_inputs']('drizzli')

    def test_candidate_requires_exact_full_signed_closure_not_baseline_tools(self):
        record = copy.deepcopy(I['load_package_inputs']('drizzli'))
        package = dict(identity=['demo', '1.2-3', 'amd64'], files={'usr/bin/demo': dict(type='file', bytes=4, mode=0o600, sha256=I['sha'](b'data'))})
        record['apt']['packages'] = [dict(identity=package['identity'], files_sha256=I['sha'](I['canonical'](package['files'])))]
        record['apt']['repositories'] = {'noble': {'input': {'sha256': 'a' * 64}, 'indexes_sha256': I['sha'](I['canonical']({}))}}
        candidate = dict(record['apt'], repositories={'noble': {'input': {'sha256': 'a' * 64}, 'indexes': {}}}, packages=[package], admitted=False, installed=False, compiled=False,
            full_build_environment_admitted=False, baseline={'tools': 'observation'})
        A['bind_package_candidate'](candidate, record)
        candidate['baseline'] = {'tools': 'different observation'}
        A['bind_package_candidate'](candidate, record)
        for key in ('packages', 'indexes', 'repositories', 'roots'):
            bad = copy.deepcopy(candidate)
            bad[key] = [] if isinstance(bad[key], list) else {}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'CLOSURE_CHANGED'):
                A['bind_package_candidate'](bad, record)
        for key in ('admitted', 'installed', 'compiled'):
            bad = dict(candidate, **{key: True})
            with self.assertRaisesRegex(ValueError, 'CLOSURE_CHANGED'):
                A['bind_package_candidate'](bad, record)
        for change in ('name', 'bytes', 'mode', 'sha256', 'extra', 'link'):
            bad = copy.deepcopy(candidate)
            files = bad['packages'][0]['files']
            entry = files['usr/bin/demo']
            if change == 'name':
                files['usr/bin/renamed'] = files.pop('usr/bin/demo')
            elif change == 'extra':
                files['usr/bin/extra'] = dict(entry)
            elif change == 'link':
                files['usr/bin/demo'] = dict(type='symlink', target='/outside')
            else:
                entry[change] = '0' * 64 if change == 'sha256' else entry[change] + 1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'CLOSURE_CHANGED'):
                A['bind_package_candidate'](bad, record)

    def test_simulation_is_complete_exact_and_never_allows_extra_removal_or_fetch(self):
        self.assertEqual(A['validate_install_simulation'](self.plan(), self.packages())['Inst'], {'demo': ['1.2-3', 'amd64']})
        for raw in (self.plan() + b'Remv other [1.0]\n', self.plan() + b'E: missing download\n',
                self.plan().replace(b'1.2-3', b'1.2-4'), self.plan().replace(b'[amd64]', b'[all]'),
                self.plan().replace(b'Conf demo', b'Conf other'), self.plan().split(b'Conf')[0],
                self.plan() + b'Inst extra (1.0 local-deb [amd64])\n', self.plan() * 2,
                self.plan().replace(b' []', b' [bad/]'), b'0 upgraded, 0 newly installed\n'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'INSTALL_PLAN_'):
                A['validate_install_simulation'](raw, self.packages())
        argv = A['provision_options'](self.root)
        self.assertIn('Dir::Etc::sourcelist=/dev/null', argv)
        self.assertIn('Dir::Etc::netrc=/dev/null', argv)
        self.assertIn('APT::Get::Download=false', argv)
        self.assertFalse(any('http:' in value or 'https:' in value for value in argv))

    def test_installed_file_maps_detect_content_mode_missing_and_link_changes(self):
        self.put('usr/bin/demo')
        packages = self.packages()
        inventory = A['package_file_inventory'](packages, root=self.root)
        self.assertTrue(inventory['demo']['usr/bin/demo']['matches_package'])
        self.put('usr/bin/demo', b'edit')
        self.assertFalse(A['package_file_inventory'](packages, root=self.root)['demo']['usr/bin/demo']['matches_package'])
        self.put('usr/bin/demo', b'data', 0o644)
        self.assertFalse(A['package_file_inventory'](packages, root=self.root)['demo']['usr/bin/demo']['matches_package'])
        (self.root / 'usr/bin/demo').unlink()
        (self.root / 'usr/bin/demo').symlink_to('/private/credential')
        actual = A['observe_path']('usr/bin/demo', root=self.root)
        self.assertEqual(actual, dict(type='symlink', target_sha256=I['sha'](b'/private/credential')))
        self.assertNotIn('private', json.dumps(actual))
        self.assertFalse(A['package_file_inventory'](packages, root=self.root)['demo']['usr/bin/demo']['matches_package'])

    def test_unknown_directory_link_is_not_followed_even_to_valid_file(self):
        self.put('usr/lib/foo/header.h', b'private')
        (self.root / 'usr/include').mkdir()
        (self.root / 'usr/include/foo').symlink_to(self.root / 'usr/lib/foo')
        actual = A['observe_path']('usr/include/foo/header.h', root=self.root)
        self.assertEqual(actual, dict(type='unvalidated-parent-alias'))
        (self.root / 'bin').symlink_to('usr/bin')
        self.put('usr/bin/demo')
        self.assertEqual(A['observe_path']('bin/demo', root=self.root)['sha256'], I['sha'](b'data'))
        for name in ('../escape', '/absolute', 'usr/../etc/passwd'):
            with self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
                A['observe_path'](name, root=self.root)

    def test_original_posix_unicode_and_systemd_literal_escape_names_are_not_decoded(self):
        names = ('usr/lib/systemd/system/system-systemd\\x2dcryptsetup.slice',
            'usr/share/ca-certificates/mozilla/NetLock_Arany_=Class_Gold=_Főtanúsítvány.crt')
        for name in names:
            self.put(name)
            self.assertEqual(A['observe_path'](name, root=self.root)['sha256'], I['sha'](b'data'))
        self.assertFalse((self.root / 'usr/lib/systemd/system/system-systemd-cryptsetup.slice').exists())

    def test_local_archive_is_rehashed_and_changed_or_linked_bytes_never_install(self):
        private = self.root / 'private'; private.mkdir()
        packages = self.packages()
        packages[0]['input'] = dict(bytes=4, sha256=I['sha'](b'data'))
        path = self.put('private/0.deb')
        self.assertEqual(A['verified_local_packages'](private, packages), [str(path)])
        self.put('private/0.deb', b'edit')
        with self.assertRaisesRegex(ValueError, 'LOCAL_PACKAGE_CHANGED'):
            A['verified_local_packages'](private, packages)
        path.unlink(); path.symlink_to('/untrusted/archive')
        with self.assertRaises(OSError):
            A['verified_local_packages'](private, packages)

    def test_configuration_receipt_has_only_fixed_scope_hashes_no_contents_or_link_targets(self):
        self.put('etc/fonts/fonts.conf', b'secret configuration')
        self.put('etc/private/auth.conf', b'never opened')
        (self.root / 'etc/alternatives').mkdir()
        (self.root / 'etc/alternatives/private').symlink_to('/private/secret')
        value = A['configuration_inventory'](root=self.root)
        self.assertIn('etc/fonts/fonts.conf', value)
        self.assertNotIn('etc/private/auth.conf', value)
        raw = json.dumps(value)
        for secret in ('secret configuration', '/private/secret', 'never opened'):
            self.assertNotIn(secret, raw)
        self.assertEqual(value['etc/alternatives/private']['type'], 'symlink')

    def test_package_transition_rejects_unreviewed_changes_and_missing_versions(self):
        before = b'base\t1\tall\tinstalled\ndemo\t1.0\tamd64\tinstalled\n'
        after = b'base\t1\tall\tinstalled\ndemo\t1.2-3\tamd64\tinstalled\n'
        A['validate_package_transition'](before, after, self.packages())
        for raw in (after.replace(b'base\t1', b'base\t2'), after.replace(b'1.2-3', b'1.2-4'),
                after + b'extra\t1\tall\tinstalled\n', after.split(b'demo')[0],
                after.replace(b'installed', b'config-files'), after + after):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'PACKAGE_'):
                A['validate_package_transition'](before, raw, self.packages())

    def test_cleanup_keeps_leader_held_until_final_privileged_kill_and_drain(self):
        child = Mock(pid=1234)
        child.wait = Mock()
        events = []
        def kill(argv, **_kwargs):
            events.append(argv)
            child.wait.assert_not_called()
            return SimpleNamespace(returncode=0)
        with patch.object(subprocess, 'run', side_effect=kill), patch.dict(AG, installer_group_running=Mock(return_value=False)):
            A['finish_installer_group'](child)
        self.assertEqual([e[4] for e in events], ['-TERM', '-KILL'])
        self.assertTrue(all(e[-1] == '-1234' for e in events))
        child.wait.assert_called_once()
        child.poll.assert_not_called()
        child.wait.reset_mock()
        for problem in (SimpleNamespace(returncode=1), PermissionError('denied')):
            with self.subTest(problem=problem), patch.object(subprocess, 'run',
                    side_effect=problem if isinstance(problem, BaseException) else None,
                    return_value=problem), self.assertRaises((ValueError, PermissionError)):
                A['finish_installer_group'](child)
            child.wait.assert_not_called()

    def test_provision_run_normal_early_exit_and_cancel_always_drains_without_poll(self):
        (self.root / 'build').mkdir()
        for case in ('normal', 'early-exit', 'cancel'):
            output = self.root / case; output.mkdir()
            child = Mock(pid=1234)
            status = SimpleNamespace(si_code=os.CLD_EXITED, si_status=0 if case == 'normal' else 1)
            waiter = Mock(side_effect=InterruptedError() if case == 'cancel' else None, return_value=status)
            finish = Mock()
            with self.subTest(case=case), patch.dict(AG, ROOT=self.root, finish_installer_group=finish), \
                    patch.object(subprocess, 'Popen', return_value=child), patch.object(os, 'waitid', waiter):
                if case == 'normal':
                    self.assertEqual(A['provision_run'](['/usr/bin/sudo', '-n', '--'], output, 'install', 1), b'')
                else:
                    with self.assertRaises((ValueError, InterruptedError)):
                        A['provision_run'](['/usr/bin/sudo', '-n', '--'], output, 'install', 1)
            child.poll.assert_not_called(); child.wait.assert_not_called()
            finish.assert_called_once_with(child)
            receipt = json.loads((output / 'installer-install-cleanup.json').read_bytes())
            self.assertTrue(receipt['owned_session_drained'])
            self.assertFalse(receipt['package_services_cleaned'])

    def test_unconfirmed_cleanup_is_observed_and_private_data_is_preserved(self):
        (self.root / 'build').mkdir()
        output = self.root / 'build/hosted-drizzli-input-candidate'; output.mkdir(mode=0o700)
        self.put('build/hosted-drizzli-input-candidate/installer-install-started.json', b'{}')
        self.put('build/hosted-drizzli-input-candidate/installer-install-cleanup.json',
            I['canonical'](dict(admitted=False, owned_session_drained=False, leader_reaped=False)))
        with patch.dict(IG, ROOT=self.root), self.assertRaisesRegex(ValueError, 'CLEANUP_UNCONFIRMED'):
            I['cleanup_candidate']('drizzli')
        self.assertTrue(output.exists())
        self.put('build/hosted-drizzli-input-candidate/installer-install-cleanup.json',
            I['canonical'](dict(admitted=False, owned_session_drained=True, leader_reaped=True)))
        with patch.dict(IG, ROOT=self.root):
            I['cleanup_candidate']('drizzli')
        self.assertFalse(output.exists())

    def test_empty_partial_cleanup_uses_parent_rmdir_and_confirms_full_absence(self):
        output = self.root / 'build/hosted-drizzli-input-candidate'
        output.mkdir(parents=True, mode=0o700)
        private, _packages = self.cache_fixture('build/hosted-drizzli-input-candidate/apt-private')
        for label in ('simulation', 'install'):
            self.put('build/hosted-drizzli-input-candidate/installer-' + label + '-started.json', b'{}')
            self.put('build/hosted-drizzli-input-candidate/installer-' + label + '-cleanup.json',
                I['canonical'](dict(admitted=False, owned_session_drained=True, leader_reaped=True)))
        original = os.open
        def reject_child_open(path, *args, **kwargs):
            if path == 'partial':
                raise AssertionError('unreadable child must not be opened')
            return original(path, *args, **kwargs)
        stream = io.StringIO()
        with patch.dict(IG, ROOT=self.root), patch.object(os, 'open', side_effect=reject_child_open), \
                patch('sys.stdout', stream):
            I['cleanup_candidate']('drizzli')
            I['cleanup_candidate']('drizzli')
        self.assertFalse(output.exists())
        receipts = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith('{')]
        self.assertTrue(any(r.get('removed') and r.get('absent') for r in receipts))
        self.assertTrue(receipts[-1]['private_absent'])
        self.assertTrue(receipts[-1]['public_absent'])
        self.assertFalse(receipts[-1]['privileged_cleanup'])

    def test_partial_cleanup_rejects_nonempty_alias_mode_and_undrained_installer(self):
        for problem in ('nonempty', 'symlink', 'mode', 'undrained'):
            root = self.root / problem; root.mkdir()
            output = root / 'build/hosted-drizzli-input-candidate'
            output.mkdir(parents=True, mode=0o700)
            private, _packages = self.cache_fixture(problem + '/build/hosted-drizzli-input-candidate/apt-private')
            partial = private / 'archives/partial'
            if problem == 'nonempty':
                (partial / 'recovery').write_bytes(b'keep')
            elif problem == 'symlink':
                partial.rmdir(); partial.symlink_to(root)
            elif problem == 'mode':
                partial.chmod(0o755)
            else:
                (output / 'installer-install-started.json').write_bytes(b'{}')
                (output / 'installer-install-cleanup.json').write_bytes(I['canonical'](
                    dict(admitted=False, owned_session_drained=False, leader_reaped=False)))
                (output / 'installer-install-started.json').chmod(0o600)
                (output / 'installer-install-cleanup.json').chmod(0o600)
            with self.subTest(problem=problem), patch.dict(IG, ROOT=root), self.assertRaises((ValueError, OSError)):
                I['cleanup_candidate']('drizzli')
            self.assertTrue(output.exists())
            self.assertTrue(partial.exists() or partial.is_symlink())

    def test_partial_cleanup_cancellation_preserves_data_and_retry_is_idempotent(self):
        output = self.root / 'build/hosted-drizzli-input-candidate'
        output.mkdir(parents=True, mode=0o700)
        private, _packages = self.cache_fixture('build/hosted-drizzli-input-candidate/apt-private')
        with patch.dict(IG, ROOT=self.root), patch.object(os, 'rmdir', side_effect=InterruptedError('cancel')), \
                self.assertRaises(InterruptedError):
            I['cleanup_candidate']('drizzli')
        self.assertTrue((private / 'archives/partial').is_dir())
        with patch.dict(IG, ROOT=self.root):
            I['cleanup_candidate']('drizzli')
        self.assertFalse(output.exists())

    def test_partial_cleanup_rejects_replaced_parent_before_any_removal(self):
        output = self.root / 'build/hosted-drizzli-input-candidate'
        output.mkdir(parents=True, mode=0o700)
        private, _packages = self.cache_fixture('build/hosted-drizzli-input-candidate/apt-private')
        original = os.stat
        replaced = False
        def replace_cache(path, *args, **kwargs):
            nonlocal replaced
            result = original(path, *args, **kwargs)
            if path == 'partial' and not replaced:
                replaced = True
                (private / 'archives').rename(private / 'retained-archives')
                (private / 'archives').mkdir(mode=0o700)
            return result
        with patch.dict(IG, ROOT=self.root), patch.object(os, 'stat', side_effect=replace_cache), \
                patch.object(os, 'rmdir') as remove, self.assertRaisesRegex(ValueError, 'CANDIDATE_CACHE_REPLACED'):
            I['cleanup_candidate']('drizzli')
        remove.assert_not_called()
        self.assertTrue((private / 'retained-archives/partial').is_dir())
        self.assertTrue(output.is_dir())

    def test_partial_cleanup_unexpected_owner_never_removes_private_data(self):
        output = self.root / 'build/hosted-drizzli-input-candidate'
        output.mkdir(parents=True, mode=0o700)
        private, _packages = self.cache_fixture('build/hosted-drizzli-input-candidate/apt-private')
        original = os.stat
        def unexpected_owner(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == 'partial':
                return SimpleNamespace(st_mode=result.st_mode, st_uid=2**30, st_gid=result.st_gid)
            return result
        with patch.dict(IG, ROOT=self.root), patch.object(os, 'stat', side_effect=unexpected_owner), \
                patch.object(os, 'rmdir') as remove, self.assertRaisesRegex(ValueError, 'CANDIDATE_CACHE_PARTIAL'):
            I['cleanup_candidate']('drizzli')
        remove.assert_not_called()
        self.assertTrue((private / 'archives/partial').is_dir())

    def test_cleanup_retry_after_partial_removal_needs_no_permission_change(self):
        import shutil
        output = self.root / 'build/hosted-drizzli-input-candidate'
        output.mkdir(parents=True, mode=0o700)
        private, _packages = self.cache_fixture('build/hosted-drizzli-input-candidate/apt-private')
        with patch.dict(IG, ROOT=self.root), patch.object(shutil, 'rmtree', side_effect=InterruptedError('cancel')), \
                self.assertRaises(InterruptedError):
            I['cleanup_candidate']('drizzli')
        self.assertFalse((private / 'archives/partial').exists())
        self.assertTrue(output.exists())
        with patch.dict(IG, ROOT=self.root):
            I['cleanup_candidate']('drizzli')
        self.assertFalse(output.exists())

    def test_permission_failure_cannot_report_success_or_reap_identity_anchor(self):
        (self.root / 'build').mkdir()
        output = self.root / 'failure'; output.mkdir()
        child = Mock(pid=1234)
        status = SimpleNamespace(si_code=os.CLD_EXITED, si_status=0)
        with patch.dict(AG, ROOT=self.root, finish_installer_group=Mock(side_effect=PermissionError())), \
                patch.object(subprocess, 'Popen', return_value=child), patch.object(os, 'waitid', return_value=status), \
                self.assertRaises(PermissionError):
            A['provision_run'](['/usr/bin/sudo', '-n', '--'], output, 'install', 1)
        receipt = json.loads((output / 'installer-install-cleanup.json').read_bytes())
        self.assertIs(receipt['owned_session_drained'], False)
        self.assertIs(receipt['leader_reaped'], False)
        child.wait.assert_not_called(); child.poll.assert_not_called()

    def test_install_gate_rejects_context_and_record_before_provisioning(self):
        record = I['load_package_inputs']('drizzli')
        fake_i = Mock()
        fake_i.hosted_guard.side_effect = ValueError('ORDINARY_HOSTED_RUNNER_REQUIRED')
        with patch.dict(AG, I=fake_i, provisioning_bootstrap=Mock(side_effect=AssertionError('not reached'))), \
                self.assertRaisesRegex(ValueError, 'ORDINARY_HOSTED'):
            A['installed_inventory']('drizzli', self.root, record)
        # Production's original strict guard executes before any acquisition or
        # privilege action. The separate compiler lock is still missing.
        self.assertIn("I.hosted_guard(os.environ, profile)", (ROOT / 'scripts/prepare_hosted_client_apt.py').read_text())

    def test_new_mode_is_manual_separate_from_historical_build_with_closed_projection(self):
        for profile, name in [('drizzli', 'hosted-clients.yml'), ('overmorrow', 'hosted-overmorrow.yml')]:
            text = (ROOT / '.github/workflows' / name).read_text()
            block = text.split('\n  installed-environment:', 1)[1]
            self.assertIn("github.event_name == 'workflow_dispatch'", block)
            self.assertIn("github.event.inputs.input_mode == 'installed-environment-inventory'", block)
            self.assertIn('--profile ' + profile + ' --mode installed-environment-inventory', block)
            self.assertIn('--profile ' + profile + ' --mode cleanup-input-data', block)
            self.assertIn('timeout-minutes: 30', block)
            self.assertIn('kill-after=60s 1500s', block)
            for forbidden in ('npm ci', 'flutter ', 'prepare_hosted_runtime.py', 'apt-get install', 'sudo ', '**', '*.deb'):
                self.assertNotIn(forbidden, block)
            self.assertEqual(block.count('path: build/hosted-' + profile + '-input-candidate-public'), 1)
        self.assertNotIn('apt-private', I['PUBLIC_NAMES'])
        self.assertIn('installed-environment.json', I['PUBLIC_NAMES'])
        self.assertFalse(any(name.endswith(('.deb', '.tgz', '.zip')) for name in I['PUBLIC_NAMES']))


if __name__ == '__main__':
    unittest.main()
