#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert Android preparation contracts. Never run Flutter, Gradle or adb."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
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
    def jetifier_pattern(self):
        properties = P.planned(original(), b'entrypoint')[P.REPLACED[3]].decode()
        values = [line.split('=', 1)[1] for line in properties.splitlines()
                  if line.startswith('android.jetifier.ignorelist=')]
        self.assertEqual(len(values), 1)
        stored = values[0]
        # java.util.Properties.load consumes one level of backslash escaping.
        # This fixed value admits only doubled backslashes, never other escapes
        # or a comma that AGP would interpret as a second ignore expression.
        self.assertNotIn('\\', stored.replace('\\\\', ''))
        self.assertNotIn(',', stored)
        decoded = stored.replace('\\\\', '\\')
        self.assertTrue(decoded.startswith('\\A') and decoded.endswith('\\z'))
        self.assertEqual(stored, decoded.replace('\\', '\\\\'))
        # Python's strict end anchor is \Z; Java Pattern uses \z.
        return re.compile(decoded[:-2] + r'\Z')

    def test_jetifier_exact_native_engine_cache_jar(self):
        pattern = self.jetifier_pattern()
        version = '1.0.0-1527ae0ec577a4ef50e65f6fefcfc1326707d9bf'
        actual = ('/state/gradle-home/caches/modules-2/files-2.1/io.flutter/x86_64_debug/'
                  f'{version}/84cf36d999dbaf1d1922e01ac48b9b05d64a1b88/x86_64_debug-{version}.jar')
        self.assertIsNotNone(pattern.search(actual))
        # The cache content key is not build authority; the exact coordinates
        # and version remain fixed while Gradle verifies dependency bytes.
        self.assertIsNotNone(pattern.search(actual.replace('84cf36d999dbaf1d1922e01ac48b9b05d64a1b88', 'a' * 40)))
        for changed in (
            actual.lstrip('/'), '/other' + actual, actual + '\n', actual + '.backup',
            actual.replace('/state/', '/tmp/'), actual.replace('io.flutter/', 'other.vendor/'),
            actual.replace('x86_64_debug', 'flutter_embedding_debug'),
            actual.replace('x86_64_debug', 'arm64_v8a_debug'),
            actual.replace('x86_64_debug', 'x86_64_release'),
            actual.replace(version, '1.0.0-' + '0' * 40),
            actual.replace('files-2.1', 'files-2x1'),
            actual.replace('84cf36d999dbaf1d1922e01ac48b9b05d64a1b88', 'a' * 39),
            actual.replace('84cf36d999dbaf1d1922e01ac48b9b05d64a1b88', 'g' * 40),
            actual.replace('/x86_64_debug/', '/x86_64_debug/../x86_64_debug/'),
        ):
            with self.subTest(path=changed):
                self.assertIsNone(pattern.search(changed))

    def test_jetifier_remains_enabled_for_embedding_and_plugins(self):
        properties = P.planned(original(), b'entrypoint')[P.REPLACED[3]].decode().splitlines()
        self.assertEqual([line for line in properties if line.startswith('android.enableJetifier=')],
                         ['android.enableJetifier=true'])
        self.assertIn('android.useAndroidX=true', properties)
        pattern = self.jetifier_pattern()
        for name in ('flutter_embedding_debug-1.0.0-1527ae0ec577a4ef50e65f6fefcfc1326707d9bf.jar',
                     'plugin.jar', 'support-compat-28.0.0.aar'):
            self.assertIsNone(pattern.search('/state/gradle-home/caches/modules-2/files-2.1/' + name))

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
        self.assertEqual(source.count('registerExtension('), 2)
        self.assertIn('WidgetsBinding.instance.rootElement', source)
        self.assertIn('widget is DataTable', source)
        self.assertIn('hitTestInView(hit, center, view.viewId)', source)
        self.assertIn("'schema': 3, 'kind': 'overmorrow-native-mounted-ui'", source)
        self.assertIn('ancestor.state is ScrollableState', source)
        self.assertIn('position.hasPixels && position.hasContentDimensions', source)
        self.assertIn('!position.isScrollingNotifier.value', source)
        self.assertIn('++ancestorsVisited > 256', source)
        self.assertIn('++scrollAncestors > 16', source)
        self.assertIn("'idle': scrollAncestors == 0 ? null : scrollIdle", source)
        self.assertIn("'x': center.dx * scale, 'y': center.dy * scale", source)
        self.assertIn('kDebugMode', source)
        self.assertNotIn('onPressed()', source)
        self.assertNotIn('updateLocation(', source)
        self.assertNotIn('MockClient', source)
        self.assertNotIn('setState(', source)
        for operation in ('jumpTo(', 'animateTo(', 'goIdle(', 'goBallistic(', 'ensureVisible('):
            self.assertNotIn(operation, source)

    def test_dynamic_system_insets_protect_footer_and_native_physical_target(self):
        source = (HERE / 'native-android-entrypoint.dart').read_text()
        self.assertIn('final padding = view.viewPadding, insets = view.viewInsets;', source)
        for side in ('left', 'top', 'right', 'bottom'):
            self.assertIn(f'math.max(padding.{side}, insets.{side})', source)
        for check in ('topLeft.dx * scale >= safeLeft', 'topLeft.dy * scale >= safeTop',
                      '(topLeft.dx + box.size.width) * scale <= safeRight',
                      '(topLeft.dy + box.size.height) * scale <= safeBottom',
                      'tapX > safeLeft && tapX < safeRight', 'tapY > safeTop && tapY < safeBottom'):
            self.assertIn(check, source)
        self.assertIn('(center.dx * scale).roundToDouble()', source)
        self.assertIn('(center.dy * scale).roundToDouble()', source)
        self.assertIn("'safe_target': safeTarget", source)
        self.assertNotIn('systemGestureInsets', source)  # Gesture areas are not equivalent to tap interception.
        patch_text = (HERE / 'upstream.patch').read_text()
        self.assertIn('if (volparossaProfile) return SafeArea(top: false, child: Padding(padding: const EdgeInsets.all(24),', patch_text)
        pin = json.loads((HERE / 'upstream.json').read_text())
        self.assertEqual(pin['upstream_patch_sha256'], hashlib.sha256((HERE / 'upstream.patch').read_bytes()).hexdigest())
        widget_test = (HERE / 'overlay/test/volparossa_ui_test.dart').read_text()
        for operation in ('tester.view.padding = insets', 'tester.view.viewPadding = insets',
                          'final rect = tester.getRect(refresh)', 'await tester.tap(refresh)',
                          'layout.padding.bottom - 24', 'layout.padding.right - 24'):
            self.assertIn(operation, widget_test)
        self.assertNotIn('.onPressed!()', widget_test)
        driver = (HERE / 'native-android-driver.mjs').read_text()
        self.assertIn('schema: 5, acceptance_evidence: false', driver)
        self.assertIn('current_lifecycle: LIFECYCLE.includes(snapshot.current_lifecycle)', driver)
        self.assertIn('button.safe_target && button.scroll?.idle === true', driver)

    def test_read_only_product_observation_contract_and_no_raw_app_error(self):
        source = (HERE / 'native-android-entrypoint.dart').read_text()
        for field in ('state?.isLoading', 'state.data != null', 'state.weatherError != null',
                      'state.data?.nativeProducts?.weather != null', 'widget is NativeProductView',
                      'widget is ErrorWidget', "'provider': providerObservation()"):
            self.assertIn(field, source)
        self.assertNotIn('weatherError.toString', source)
        self.assertNotIn('errorDesc', source)
        mounted = source.split('Map<String, Object?> _snapshot(', 1)[1].split('Future<void> main()', 1)[0]
        self.assertNotIn('DateTime.now', mounted)
        provider = (HERE / 'overlay/lib/volparossa/provider.dart').read_text()
        driver = (HERE / 'native-android-driver.mjs').read_text()
        for dart_enum, key in (('_Stage', 'stage'), ('_Outcome', 'outcome'),
                               ('_Http', 'http_class'), ('_Clock', 'clock_relation')):
            values = re.search(r'enum ' + dart_enum + r' \{([^}]+)\}', provider).group(1)
            names = [v.strip() for v in values.split(',') if v.strip()]
            projection = re.search(r'    ' + key + r': \[([^]]+)\]', driver).group(1)
            self.assertEqual(names, re.findall(r"'([A-Za-z]+)'", projection))
        self.assertIn('final observed = _LoadObservation();\n    _lastLoad = observed;', provider)
        self.assertIn('if (closed || outcome != _Outcome.pending) return;', provider)
        self.assertIn('providerProductDeadline - providerAbortDrain', provider)
        self.assertIn('const providerBusyRetries = 5;', provider)
        self.assertIn('const providerProductDeadline = Duration(seconds: 195);', provider)
        self.assertLess(provider.index('final product = NativeProduct.parse('),
                        provider.index('observed.productValidated = true;'))

    def test_separate_lifecycle_extension_is_constant_size_current_clock_and_read_only(self):
        source = (HERE / 'native-android-entrypoint.dart').read_text()
        observation = source.split('Map<String, Object?> _lifecycleSnapshot(', 1)[1].split('String _text(', 1)[0]
        for expected in ("'schema': 1, 'kind': 'overmorrow-native-lifecycle'",
                         "'current_lifecycle': WidgetsBinding.instance.lifecycleState?.name",
                         "'callback_state': lifecycle.lastState", "'callback_sequence': lifecycle.sequence",
                         "'guest_utc_ms': DateTime.now().toUtc().millisecondsSinceEpoch"):
            self.assertIn(expected, observation)
        for operation in ('visit', 'rootElement', 'endOfFrame', 'await', 'setState', 'observed', 'scheduleFrame'):
            self.assertNotIn(operation, observation)
        callback = source.split('void didChangeAppLifecycleState(', 1)[1].split('Map<String, Object?> _lifecycleSnapshot', 1)[0]
        self.assertIn('sequence++;', callback)
        self.assertIn('lastState = state.name;', callback)
        self.assertNotIn('DateTime', callback)  # Never backdate acceptance to a callback time.
        extension = source.split("registerExtension('ext.volparossa.native_lifecycle'", 1)[1].split('await app.main()', 1)[0]
        self.assertIn("parameters.keys.any((key) => key != 'isolateId')", extension)
        self.assertIn('jsonEncode(_lifecycleSnapshot(lifecycle))', extension)
        self.assertIn('result.length > 1024', extension)
        self.assertNotIn('_snapshot(', extension)
        driver = (HERE / 'native-android-driver.mjs').read_text()
        self.assertIn('async function lifecycle() { remaining(); return readLifecycle(vm, isolate); }', driver)
        self.assertIn('vm.request(LIFECYCLE_EXTENSION, { isolateId: isolate })', driver)
        self.assertIn('timeout: 8000, killSignal:', driver)
        self.assertIn('}, 3000);', driver)
        self.assertIn('deadline = started + 180000', driver)

    def test_existing_dart_groups_preserved_plus_system_inset_widget_regression(self):
        tests = list((HERE / 'overlay/test').glob('*_test.dart'))
        # 23 declarations; the unchanged responsive UI declaration is run at
        # two widths, producing 24 hosted Flutter test cases. The additional
        # widget test exercises phone/side/zero insets through real tester.tap.
        self.assertEqual(sum(len(re.findall(r'\btest(?:Widgets)?\s*\(', path.read_text()))
                             for path in tests), 23)
        self.assertIn('for (final width in [390.0, 900.0])',
                      (HERE / 'overlay/test/volparossa_ui_test.dart').read_text())
        provider = (HERE / 'overlay/test/volparossa_provider_test.dart').read_text()
        for case in ('beforeAcquired', 'atOrAfterExpiry', 'private-transport', 'private-stream',
                     'observationBeforeLate', 'expect(providerObservation(), newer)', 'busyLimit'):
            self.assertIn(case, provider)


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
