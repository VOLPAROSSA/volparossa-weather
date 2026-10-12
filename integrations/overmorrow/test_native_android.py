#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert Android preparation contracts. Never run Flutter, Gradle or adb."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_android_prepare", HERE / "prepare_native_android.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def original():
    return dict(zip(P.REPLACED, (
        b'namespace = "com.marotidev.overmorrow"\napplicationId = "com.marotidev.Overmorrow"\n',
        b'id("com.android.application") version "8.9.1" apply false\n',
        b'distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-all.zip\n',
        b'org.gradle.jvmargs=-Xmx8G\n', b'<manifest />\n')))


class ProfileTests(unittest.TestCase):
    def test_only_android_and_new_target_changed(self):
        before = original()
        after = P.planned(before, b'// test entrypoint\n')
        self.assertEqual(set(after), {*P.REPLACED, *P.ADDED})
        self.assertEqual(before, original())
        self.assertTrue(all(name.startswith("android/") or name == P.TARGET for name in after))
        self.assertIn(b'namespace = "com.marotidev.overmorrow"', after[P.REPLACED[0]])
        self.assertIn(P.PACKAGE.encode(), after[P.REPLACED[0]])

    def test_fixed_verified_local_gradle_distribution(self):
        result = P.planned(original(), b'entrypoint')[P.REPLACED[2]].decode()
        self.assertIn("distributionUrl=" + P.GRADLE_URL, result)
        self.assertIn("distributionSha256Sum=" + P.GRADLE_SHA, result)
        self.assertEqual(len(P.GRADLE_SHA), 64)
        self.assertNotIn("https", result)

    def test_no_unreviewed_application_agp_or_wrapper(self):
        for path, content in ((P.REPLACED[0], b"applicationId = 'other'"),
                (P.REPLACED[1], b'plugin8.10'), (P.REPLACED[2], b'gradle-8.14-all.zip'),
                (P.REPLACED[2], b'gradle-8.13-all.zip\ndistributionSha256Sum=changed')):
            with self.subTest(path=path, content=content), self.assertRaises(ValueError):
                P.planned({**original(), path: content}, b'entrypoint')

    def test_loopback_exception_and_no_location_or_widget_authority(self):
        namespace = '{http://schemas.android.com/apk/res/android}'
        manifest = ET.fromstring(P.MANIFEST)
        self.assertEqual([permission.get(namespace + 'name') for permission in manifest.findall('uses-permission')],
                         ['android.permission.INTERNET'])
        application = manifest.find('application')
        self.assertEqual(application.get(namespace + 'allowBackup'), 'false')
        self.assertEqual(application.get(namespace + 'usesCleartextTraffic'), 'false')
        self.assertEqual(application.find('activity').get(namespace + 'name'), 'com.marotidev.overmorrow.MainActivity')
        self.assertFalse(application.findall('service') + application.findall('receiver'))
        config = ET.fromstring(P.NETWORK)
        self.assertEqual(config.find('base-config').get('cleartextTrafficPermitted'), 'false')
        self.assertEqual([entry.text for entry in config.findall('.//domain')], ['127.0.0.1'])
        self.assertEqual(config.find('.//domain').get('includeSubdomains'), 'false')

    def test_bounded_build_and_no_dependency_rewrite(self):
        properties = P.GRADLE_PROPERTIES
        for setting in ('-Xmx1536m', '-XX:MaxMetaspaceSize=512m', 'org.gradle.workers.max=2',
                        'org.gradle.daemon=false', 'org.gradle.parallel=false'):
            self.assertIn(setting, properties)
        self.assertFalse(any('pubspec' in path for path in P.planned(original(), b'entrypoint')))

    def test_entrypoint_only_observes_real_main_and_mounted_widgets(self):
        source = (HERE / 'native-android-entrypoint.dart').read_text()
        self.assertIn('await app.main()', source)
        self.assertIn("registerExtension('ext.volparossa.native_snapshot'", source)
        self.assertEqual(source.count('registerExtension('), 1)
        self.assertIn('WidgetsBinding.instance.rootElement', source)
        self.assertIn('widget is DataTable', source)
        self.assertIn('hitTestInView(hit, center, view.viewId)', source)
        self.assertIn('kDebugMode', source)
        self.assertNotIn('onPressed()', source)
        self.assertNotIn('updateLocation(', source)
        self.assertNotIn('MockClient', source)
        self.assertNotIn('setState(', source)


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.here = self.root / 'integration'
        self.here.mkdir(mode=0o700)
        (self.root / 'build').mkdir(mode=0o700)
        self.stage = self.root / 'build' / P.STAGE_NAME
        self.stage.mkdir(mode=0o700)
        self.original = original()
        self.activity = 'android/app/src/main/kotlin/com/marotidev/overmorrow/MainActivity.kt'
        self.original[self.activity] = b'package com.marotidev.overmorrow\nclass MainActivity : FlutterActivity()\n'
        for name, data in self.original.items():
            path = self.stage / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data); path.chmod(0o600)
        for name in P.ADDED:
            (self.stage / name).parent.mkdir(parents=True, exist_ok=True)
        self.lock = b'locked dependencies\n'
        self.write(self.stage / 'pubspec.lock', self.lock)
        self.write(self.here / 'upstream.patch', b'shared patch\n')
        self.write(self.here / 'native-android-entrypoint.dart', b'// read only native trial\n')
        self.pin = dict(commit='1' * 40, pubspec_lock_sha256=P.sha(self.lock),
                        upstream_patch_sha256=P.sha(b'shared patch\n'))
        self.write(self.here / 'upstream.json', json.dumps(self.pin).encode())
        self.enterContext(patch.object(P, 'ROOT', self.root))
        self.enterContext(patch.object(P, 'HERE', self.here))
        self.enterContext(patch.object(P, 'git', self.git))

    def write(self, path, data):
        path.write_bytes(data); path.chmod(0o600)

    def git(self, stage, *args):
        self.assertEqual(stage, self.stage)
        if args == ('rev-parse', 'HEAD'):
            return (self.pin['commit'] + '\n').encode()
        self.assertEqual(args[0], 'show')
        return self.original[args[1].split(':', 1)[1]]

    def test_preparation_preserves_lock_and_produces_truthful_profile(self):
        receipt = P.prepare(self.stage)
        self.assertEqual((self.stage / 'pubspec.lock').read_bytes(), self.lock)
        self.assertEqual(receipt['source_before'], {name: P.sha(self.original[name]) for name in P.REPLACED})
        self.assertFalse(receipt['scope']['installed'])
        self.assertFalse(receipt['scope']['core_delivery'])
        self.assertEqual(receipt['activity_sha256'], P.sha(self.original[self.activity]))
        for name, expected in receipt['source_after'].items():
            path = self.stage / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_original_xml_parent_fails_before_any_source_write(self):
        # Pinned upstream contains res/xml. A stage missing it is not repaired
        # by guessing a changed source tree or broad mkdir(parents=True).
        (self.stage / P.ADDED[0]).parent.rmdir()
        with self.assertRaises(FileNotFoundError): P.prepare(self.stage)
        for name, data in self.original.items(): self.assertEqual((self.stage / name).read_bytes(), data)

    def test_existing_target_symlink_or_source_edit_is_rejected(self):
        target = self.stage / P.TARGET
        target.symlink_to(self.here / 'native-android-entrypoint.dart')
        with self.assertRaises(ValueError): P.prepare(self.stage)
        target.unlink()
        self.write(self.stage / P.REPLACED[0], b'changed source')
        with self.assertRaises(ValueError): P.prepare(self.stage)

    def test_unexpected_package_case_is_rejected(self):
        self.original[self.activity] = b'package com.marotidev.Overmorrow\n'
        self.write(self.stage / self.activity, self.original[self.activity])
        with self.assertRaisesRegex(ValueError, 'activity package'): P.prepare(self.stage)

    def test_reprepare_does_not_overwrite_existing_trial(self):
        P.prepare(self.stage)
        before = (self.stage / 'volparossa-native-profile.json').read_bytes()
        with self.assertRaises(ValueError): P.prepare(self.stage)
        self.assertEqual((self.stage / 'volparossa-native-profile.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
