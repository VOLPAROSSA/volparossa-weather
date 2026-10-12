# SPDX-License-Identifier: GPL-3.0-only
"""Pure commands/scope/lifecycle contracts; no native tools or policy execution."""
import base64
import hashlib
import importlib.util
import os
import io
import json
from pathlib import Path
import resource
import subprocess
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_ci_tests", ROOT / "scripts/prepare_hosted_android_ci.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
FSTAT = os.fstat


def root_file_stat(fd, **changes):
    """Inert ownership simulation; never chown or execute an apt tool."""
    info = FSTAT(fd)
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
        "st_size", "st_mtime_ns", "st_ctime_ns")
    values = {k: getattr(info, k) for k in fields}
    values.update(st_uid=0)
    values.update(changes)
    return SimpleNamespace(**values)


def report():
    products = dict(weather=dict(rows=4, table_sha256="a"*64, product_sha256="b"*64),
        air_quality=dict(rows=5, table_sha256="c"*64, product_sha256="d"*64))
    return dict(schema=1, kind="overmorrow-installed-android-synthetic-trial", passed=True, phase="complete", package=M.PACKAGE,
        scope=dict(installed_android_app=True, mounted_widget_tables=True, real_adb_interaction=True,
            synthetic_weather=True, synthetic_air_quality=True, pixel_visibility_proven=False, core_executed=False,
            overlay_proven=False, physical_device=False, production_authority=False),
        observations=dict(requests=dict(weather=3, air_quality=3), initial=products, refresh=products),
        checks=dict(initial_exact_native_rows=True, actual_tap_refresh_and_missing_values=True,
            real_android_background_resume=True, expired_products_hidden_without_network_refresh=True),
        cleanup=dict(app_stopped=True, forward_removed=True, vm_closed=True))


class NativeCI(unittest.TestCase):
    def test_rejects_developer_and_selfhosted(self):
        with self.assertRaisesRegex(ValueError, "DISPOSABLE_HOSTED_ONLY"):
            M.guards({})
        with self.assertRaisesRegex(ValueError, "DISPOSABLE_HOSTED_ONLY"):
            M.guards(dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="self-hosted"))

    def test_acquisition_build_is_explicit_and_final_is_offline_strict(self):
        online, offline = M.gradle(True), M.gradle(False)
        self.assertIn("--write-verification-metadata", online)
        self.assertNotIn("--offline", online)
        self.assertIn("--offline", offline)
        self.assertEqual(offline[offline.index("--dependency-verification") + 1], "strict")
        self.assertLess(offline.index("clean"), offline.index("assembleDebug"))
        self.assertIn("--no-daemon", offline)
        self.assertIn("--max-workers=1", offline)
        self.assertIn("-Ptarget-platform=android-x64", offline)
        defines = next(x for x in offline if x.startswith("-Pdart-defines=")).split("=", 1)[1]
        self.assertEqual([base64.b64decode(x).decode() for x in defines.split(",")],
            ["VOLPAROSSA_WEATHER=true", "VOLPAROSSA_CORE_ORIGIN=http://127.0.0.1:43210"])

    def test_only_app_builds_override_staged_heap_and_workers(self):
        expected = "-Dorg.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m -XX:ReservedCodeCacheSize=128m -Dfile.encoding=UTF-8"
        for acquire in (True, False):
            argv = M.gradle(acquire)
            self.assertEqual([x for x in argv if x.startswith("-Dorg.gradle.jvmargs=")], [expected])
            self.assertEqual([x for x in argv if x.startswith("--max-workers=")], ["--max-workers=1"])
            self.assertIn("--no-daemon", argv)
            # The exact-command sandbox still rejects restoring the old heap
            # or worker count, additional overrides and task changes.
            mode = "acquire" if acquire else "compile"
            for changed in ([x.replace("-Xmx1024m", "-Xmx1536m") for x in argv],
                    ["--max-workers=2" if x == "--max-workers=1" else x for x in argv],
                    argv + ["-Dorg.gradle.jvmargs=-Xmx2048m"]):
                with self.assertRaisesRegex(ValueError, "NATIVE_GRADLE_RESOURCE_SCOPE"):
                    M.gradle_sandbox(changed, mode)
        self.assertIn("--max-workers=2", M.repository_fixture_command())
        self.assertFalse(any(x.startswith("-Dorg.gradle.jvmargs=") for x in M.repository_fixture_command()))
        self.assertIn("-Xmx256m", (ROOT / "tests/fixtures/hosted-android-repositories/gradle.properties").read_text())
        self.assertNotIn("JAVA_OPTS", M.environment())
        self.assertEqual(M.environment()["GRADLE_OPTS"], "-Dorg.gradle.daemon=false")

    def test_configured_limits_receipt_is_not_runtime_or_cleanup_evidence(self):
        value = M.app_gradle_resources()
        self.assertEqual(value, dict(schema=1, kind="hosted-android-gradle-configured-limits",
            scope="acquisition-and-offline-app-build", max_workers=1,
            jvm_args=["-Xmx1024m", "-XX:MaxMetaspaceSize=512m", "-XX:ReservedCodeCacheSize=128m", "-Dfile.encoding=UTF-8"],
            child_rss_limit_bytes=4294967296, host_reserve_bytes=2147483648, launch_min_available_bytes=6442450944,
            step_timeout_seconds=900, runtime_measurement=False))
        self.assertEqual("-Dorg.gradle.jvmargs=" + " ".join(value["jvm_args"]),
            next(x for x in M.gradle(True) if x.startswith("-Dorg.gradle.jvmargs=")))
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1]
        self.assertLess(source.index('H.save("gradle-resources.json", app_gradle_resources())'),
            source.index('run_app_gradle(True)'))
        self.assertIn('gradle_configured_limits=app_gradle_resources()', source)
        # Neither a smaller configuration nor a forced negative child exit may
        # turn an unconfirmed drain into cleanup success.
        self.assertIn('helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED', source)
        self.assertIn('require(cleanup["complete"], "CLEANUP_UNCONFIRMED")', source)

    def test_sandbox_network_and_kvm_separation(self):
        for mode in ("acquire", "compile", "emulator"):
            args = M.sandbox(["inert"], mode)
            self.assertEqual("--unshare-net" in args, mode != "acquire")
            self.assertEqual("--dev-bind" in args, mode == "emulator")
            self.assertIn(str(M.INPUTS), args)
            self.assertIn("/tools/android-inputs", args)
            self.assertNotIn("--share-net", args)
            self.assertNotIn("--cap-add", args)
            self.assertNotIn("/dev", [args[i+1] for i, a in enumerate(args[:-1]) if a == "--dev-bind"])
        with self.assertRaises(ValueError):
            M.sandbox(["inert"], "host")

    def test_environment_contains_no_host_credentials(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "not-forwarded", "HTTP_PROXY": "not-forwarded", "HOME": "/private"}):
            env = M.environment()
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertEqual(env["HOME"], "/home/runner")
        self.assertEqual(env["ANDROID_AVD_HOME"], "/state/avd")
        self.assertEqual(env["GRADLE_USER_HOME"], "/state/gradle-home")

    def test_apk_alone_never_qualifies(self):
        with self.assertRaises(ValueError):
            M.validate_report({"success": True})
        M.validate_report(report())
        for key in ("installed_android_app", "real_adb_interaction", "mounted_widget_tables"):
            value = report(); value["scope"][key] = False
            with self.assertRaises(ValueError):
                M.validate_report(value)
        for key in ("core_executed", "pixel_visibility_proven", "production_authority"):
            value = report(); value["scope"][key] = True
            with self.assertRaises(ValueError):
                M.validate_report(value)

    def test_missing_product_and_unclean_trial_rejected(self):
        value = report(); value["observations"]["requests"]["air_quality"] = 0
        with self.assertRaises(ValueError): M.validate_report(value)
        for key in ("app_stopped", "vm_closed", "forward_removed"):
            value = report(); value["cleanup"][key] = False
            with self.assertRaises(ValueError): M.validate_report(value)

    def test_no_downgraded_checks_or_unbound_rows(self):
        value = report(); value["checks"].pop("actual_tap_refresh_and_missing_values")
        with self.assertRaises(ValueError): M.validate_report(value)
        value = report(); value["observations"]["initial"]["weather"]["rows"] = 3
        with self.assertRaises(ValueError): M.validate_report(value)
        value = report(); value["observations"]["refresh"]["air_quality"]["table_sha256"] = "not-a-hash"
        with self.assertRaises(ValueError): M.validate_report(value)

    def test_captured_metadata_not_review_authority(self):
        with tempfile.TemporaryDirectory() as root, patch.object(M, "STAGE", Path(root)):
            target = Path(root) / "android/gradle/verification-metadata.xml"
            target.parent.mkdir(parents=True)
            target.write_text('<verification-metadata><sha256 value="' + 'a'*64 + '"/></verification-metadata>')
            target.chmod(0o600)
            value = M.verification_metadata()
            self.assertTrue(value["captured_after_execution"])
            self.assertFalse(value["independently_reviewed"])
            target.write_text('<!DOCTYPE unsafe><verification-metadata/>')
            with self.assertRaises(ValueError): M.verification_metadata()

    def test_owned_children_are_joined_in_reverse_order(self):
        events = []
        def child(name):
            c = Mock(stdin=io.BytesIO(), stdout=io.BytesIO())
            c.poll.side_effect = [None, 0]
            c.terminate.side_effect = lambda: events.append(name + ":term")
            c.wait.side_effect = lambda **kw: events.append(name + ":join")
            return c
        first, last = child("first"), child("last")
        self.assertTrue(M.drain_children([first, last]))
        self.assertEqual(events, ["last:term", "last:join", "first:term", "first:join"])
        self.assertTrue(first.stdin.closed and last.stdout.closed)

    def test_timeout_kill_and_uncertainty_do_not_skip_sibling_cleanup(self):
        stopped = Mock(stdin=None, stdout=None)
        stopped.poll.side_effect = [None, -9]
        stopped.wait.side_effect = [subprocess.TimeoutExpired("owned", 5), -9]
        self.assertTrue(M.drain_children([stopped]))
        stopped.kill.assert_called_once()
        bad, good = Mock(stdin=None, stdout=None), Mock(stdin=None, stdout=None)
        bad.poll.return_value = None
        bad.terminate.side_effect = OSError("inert failure")
        good.poll.return_value = 0
        self.assertFalse(M.drain_children([good, bad]))
        good.wait.assert_called_once_with(timeout=5)

    def test_guest_no_default_route_is_required_even_in_host_netns_isolation(self):
        self.assertTrue(M.no_guest_egress_routes(b"local 127.0.0.0/8 dev lo table local\nlocal ::1 dev lo table local\n"))
        for raw in (b"default via 10.0.2.2 dev wlan0\n", b"0.0.0.0/0 dev eth0\n", b"::/0 via fe80::1\n",
                    b"10.0.2.0/24 dev wlan0 proto kernel scope link src 10.0.2.15\n",
                    b"local 10.0.2.15 dev wlan0 table local\n", b"fe80::/64 dev wlan0\n"):
            self.assertFalse(M.no_guest_egress_routes(raw))
        with self.assertRaises(ValueError):
            M.no_guest_egress_routes(b"x" * 65537)

    def test_source_profile_and_overlay_remain_exact(self):
        import hashlib, json
        with tempfile.TemporaryDirectory() as root:
            stage, here = Path(root) / "stage", Path(root) / "here"
            (stage / "lib").mkdir(parents=True)
            (here / "overlay/lib").mkdir(parents=True)
            for path in (stage / "lib/shared.dart", here / "overlay/lib/shared.dart"):
                path.write_bytes(b"shared"); path.chmod(0o600)
            target = stage / "lib/volparossa_native_trial.dart"
            target.write_bytes(b"inert"); target.chmod(0o600)
            profile = dict(kind="overmorrow-native-android-trial-profile", package=M.PACKAGE,
                target="lib/volparossa_native_trial.dart", origin="http://127.0.0.1:43210",
                source_after={"lib/volparossa_native_trial.dart": hashlib.sha256(b"inert").hexdigest()})
            (stage / "volparossa-native-profile.json").write_text(json.dumps(profile))
            (stage / "volparossa-native-profile.json").chmod(0o600)
            with patch.object(M, "STAGE", stage), patch.object(M.W, "HERE", here):
                binding = M.native_sources()
                M.native_sources(binding)
                target.write_bytes(b"modified")
                with self.assertRaisesRegex(ValueError, "NATIVE_SOURCE_CHANGED"):
                    M.native_sources(binding)


class AptJavaProvenance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.java = Path(temporary.name) / "jdk"
        self.target = self.java / "bin/java"
        self.target.parent.mkdir(parents=True)
        self.raw = b"inert Java launcher fixture; never executed\n"
        self.target.write_bytes(self.raw)
        self.target.chmod(0o755)
        self.addCleanup(patch.stopall)
        patch.object(M, "JAVA", self.java).start()
        self.helper = Mock()
        self.helper.process.return_value = (0, b'openjdk version "17.0.20.1"\n')

    def test_old_runner_digest_rejects_apt_owner_new_fixed_provenance_accepts(self):
        with patch.object(M.os, "fstat", side_effect=root_file_stat), patch.object(M.os, "getuid", return_value=1001):
            with self.assertRaisesRegex(ValueError, "UNSAFE_FILE"):
                M.H.digest(self.target)
            value = M.java_provenance(self.helper)
        self.assertEqual(value, dict(path=str(self.java),
            executable=dict(bytes=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest()),
            version='openjdk version "17.0.20.1"', authority="signed-disposable-apt-package-inventory",
            independently_reproducible=False))
        self.helper.process.assert_called_once_with([str(self.target), "-version"], 10)

    def test_root_ownership_regular_single_link_executable_and_size_are_required(self):
        bad = (dict(st_uid=1001), dict(st_uid=65534), dict(st_mode=stat.S_IFDIR | 0o755),
            dict(st_nlink=2), dict(st_mode=stat.S_IFREG | 0o644), dict(st_size=0),
            dict(st_size=M.JAVA_LAUNCHER_LIMIT + 1))
        for changes in bad:
            with self.subTest(changes=changes), patch.object(M.os, "fstat",
                    side_effect=lambda fd: root_file_stat(fd, **changes)):
                with self.assertRaisesRegex(ValueError, "JAVA_TOOL"):
                    M.java_provenance(self.helper)
        self.helper.process.assert_not_called()

    def test_writable_and_special_modes_are_rejected(self):
        for mode in (0o775, 0o757, 0o777, 0o4755, 0o2755, 0o1755):
            with self.subTest(mode=mode), patch.object(M.os, "fstat",
                    side_effect=lambda fd: root_file_stat(fd, st_mode=stat.S_IFREG | mode)):
                with self.assertRaisesRegex(ValueError, "JAVA_TOOL"):
                    M.apt_java_digest()

    def test_symlink_and_fifo_do_not_follow_or_block(self):
        self.target.unlink()
        self.target.symlink_to("../not-a-java-tool")
        with self.assertRaisesRegex(ValueError, "JAVA_TOOL_PATH"):
            M.apt_java_digest()
        self.target.unlink()
        os.mkfifo(self.target, 0o600)
        opened = []
        actual_open = os.open
        def open_nonblocking(path, flags):
            self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertTrue(flags & os.O_NONBLOCK)
            opened.append(actual_open(path, flags))
            return opened[-1]
        with patch.object(M.os, "open", side_effect=open_nonblocking), patch.object(M.os, "fstat", side_effect=root_file_stat):
            with self.assertRaisesRegex(ValueError, "JAVA_TOOL"):
                M.apt_java_digest()
        with self.assertRaises(OSError):
            FSTAT(opened[0])

    def test_same_descriptor_metadata_change_and_in_place_write_fail_closed(self):
        actual_read, opened = os.read, []
        def mutate_after_read(fd, size):
            result = actual_read(fd, size)
            if result:
                opened.append(fd)
                before = self.target.stat()
                self.target.write_bytes(b"x" * len(self.raw))
                # Some temporary filesystems have coarse update timestamps.
                os.utime(self.target, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            return result
        with patch.object(M.os, "read", side_effect=mutate_after_read), patch.object(M.os, "fstat", side_effect=root_file_stat):
            with self.assertRaisesRegex(ValueError, "JAVA_TOOL_CHANGED"):
                M.apt_java_digest()
        with self.assertRaises(OSError):
            FSTAT(opened[0])
        for field in ("st_uid", "st_mode", "st_nlink", "st_size", "st_ino", "st_mtime_ns", "st_ctime_ns"):
            calls = []
            def changing_stat(fd):
                info = root_file_stat(fd)
                if calls:
                    setattr(info, field, getattr(info, field) + 1)
                calls.append(fd)
                return info
            with self.subTest(field=field), patch.object(M.os, "fstat", side_effect=changing_stat):
                with self.assertRaisesRegex(ValueError, "JAVA_TOOL_CHANGED"):
                    M.apt_java_digest()
            self.assertEqual(calls, [calls[0], calls[0]])

    def test_actual_read_bound_is_enforced_even_if_initial_size_is_stale(self):
        with patch.object(M, "JAVA_LAUNCHER_LIMIT", 8), patch.object(M.os, "fstat",
                side_effect=lambda fd: root_file_stat(fd, st_size=8)):
            with self.assertRaisesRegex(ValueError, "JAVA_TOOL_BOUND"):
                M.apt_java_digest()

    def test_probe_change_or_wrong_version_never_gets_provenance(self):
        def replace_during_probe(*args):
            self.target.write_bytes(b"another inert launcher")
            return (0, b'openjdk version "17.0.20.1"\n')
        self.helper.process.side_effect = replace_during_probe
        with patch.object(M.os, "fstat", side_effect=root_file_stat):
            with self.assertRaisesRegex(ValueError, "JAVA_TOOL_CHANGED"):
                M.java_provenance(self.helper)
        self.helper.process.side_effect = None
        self.helper.process.return_value = (0, b'openjdk version "21.0.1"\n')
        with patch.object(M.os, "fstat", side_effect=root_file_stat):
            with self.assertRaisesRegex(ValueError, "JAVA_17_REQUIRED"):
                M.java_provenance(self.helper)


class RepositoryFixture(unittest.TestCase):
    @staticmethod
    def receipt(**changes):
        value = dict(schema=2, kind="gradle-repository-contract", gradle_version="8.13", plugin_wrappers=3,
            rejected=["artifact-url", "unadmitted", "http", "file", "ivy", "flatdir"], networkless=True,
            external_dependencies=False, nofile_soft=4096, nofile_hard=4096)
        value.update(changes)
        return b"NATIVE_REPOSITORY_FIXTURE " + json.dumps(value).encode() + b"\n"

    def test_exact_runtime_receipt_required_not_a_success_message_or_mock_count(self):
        self.assertEqual(M.repository_fixture_report(b"Gradle output\n" + self.receipt())["plugin_wrappers"], 3)
        for raw in (b"BUILD SUCCESSFUL", self.receipt() * 2, self.receipt(plugin_wrappers=0),
                self.receipt(plugin_wrappers=True), self.receipt(plugin_wrappers=3.0), self.receipt(schema=True),
                self.receipt(rejected=[]), self.receipt(networkless=False), self.receipt(networkless=1),
                self.receipt(external_dependencies=True), self.receipt(external_dependencies=0),
                self.receipt(schema=1), self.receipt(nofile_soft=1024), self.receipt(nofile_hard=8192),
                self.receipt(nofile_soft=4096.0), self.receipt(nofile_hard=None),
                self.receipt(gradle_version="8.14"), self.receipt(extra="not closed")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                M.repository_fixture_report(raw)
        with self.assertRaises(ValueError):
            M.repository_fixture_report(b"x" * (M.H.LIMIT + 1))

    def fixture_paths(self, directory, properties=None):
        sdk, stage, private = (directory / name for name in ("sdk", "stage", "private"))
        private.mkdir(mode=0o700)
        wrapper = sdk / "bin/cache/artifacts/gradle_wrapper"
        (wrapper / "gradle/wrapper").mkdir(parents=True)
        (stage / "android/gradle/wrapper").mkdir(parents=True)
        for name, raw in (("gradlew", b"inert launcher"), ("gradle/wrapper/gradle-wrapper.jar", b"inert jar")):
            (wrapper / name).write_bytes(raw)
            (wrapper / name).chmod(0o600)
        native = M.runpy.run_path(str(M.W.HERE / "prepare_native_android.py"))
        if properties is None:
            properties = f'distributionUrl={native["GRADLE_URL"]}\ndistributionSha256Sum={native["GRADLE_SHA"]}\n'.encode()
        path = stage / "android/gradle/wrapper/gradle-wrapper.properties"
        path.write_bytes(properties)
        path.chmod(0o600)
        return sdk, stage, private

    def test_real_preparation_binds_wrapper_and_runs_only_offline_fake_child(self):
        with tempfile.TemporaryDirectory() as root:
            sdk, stage, private = self.fixture_paths(Path(root))
            with patch.object(M, "SDK", sdk), patch.object(M, "STAGE", stage), patch.object(M, "PRIVATE", private), \
                    patch.object(M, "gradle_sandbox", side_effect=lambda argv, mode: ["inert-" + mode, *argv]), \
                    patch.object(M.H, "run", return_value=self.receipt()) as run, patch.object(M.H, "save") as save:
                M.repository_fixture()
            args, kwargs = run.call_args
            self.assertEqual(args[0], "gradle-repository-contract")
            self.assertEqual(args[2], 120)
            self.assertEqual(args[1][0], "inert-compile")
            self.assertIn("--offline", args[1])
            self.assertIn("--no-daemon", args[1])
            self.assertIn("--max-workers=2", args[1])
            self.assertEqual(args[1][-1], "verifyRepositoryContract")
            self.assertEqual(kwargs["memory"], 3 * M.GIB)
            self.assertEqual((private / "repository-fixture/gradlew").stat().st_mode & 0o777, 0o700)
            saved = save.call_args.args[1]
            self.assertEqual(len(saved["fixture_files"]), 6)
            self.assertEqual(saved["fixture_files"]["gradle/wrapper/gradle-wrapper.jar"], hashlib.sha256(b"inert jar").hexdigest())
            self.assertEqual(saved["guard_sha256"], M.H.sha(M.H.read(ROOT / "scripts/hosted-android-repositories.gradle")))

    def test_distribution_authority_checked_before_first_gradle_child(self):
        for properties in (b"", b"distributionUrl=https://unadmitted.invalid/gradle.zip\n",
                           b"distributionSha256Sum=" + b"a" * 64 + b"\n"):
            with self.subTest(properties=properties), tempfile.TemporaryDirectory() as root:
                sdk, stage, private = self.fixture_paths(Path(root), properties)
                with patch.object(M, "SDK", sdk), patch.object(M, "STAGE", stage), patch.object(M, "PRIVATE", private), \
                        patch.object(M.H, "run") as run, self.assertRaisesRegex(ValueError, "REPOSITORY_FIXTURE_DISTRIBUTION"):
                    M.repository_fixture()
                run.assert_not_called()

    def test_source_contract_keeps_exact_typed_wrapper_and_all_url_checks(self):
        source = (ROOT / "scripts/hosted-android-repositories.gradle").read_text()
        self.assertIn("gradle.gradleVersion != '8.13'", source)
        self.assertIn("repository.class.name == 'org.gradle.plugin.use.internal.PluginArtifactRepository'", source)
        self.assertIn("repository instanceof ResolutionAwareRepository", source)
        self.assertIn("descriptor instanceof MavenRepositoryDescriptor", source)
        self.assertIn("descriptor.properties['URL']", source)
        self.assertIn("descriptor.properties['ARTIFACT_URLS']", source)
        self.assertIn("artifactUrls = repository.artifactUrls", source)
        self.assertIn("!artifactUrls.every(admittedUrl)", source)
        self.assertNotIn("getDeclaredField", source)
        self.assertNotIn("setAccessible", source)
        self.assertNotIn("getArtifactUrls()", source)
        self.assertIn('NATIVE_REPOSITORY_DENIED:${reason}:${kind}', source)

    def test_hosted_fixture_requires_actual_wrappers_and_negative_cases_before_app_build(self):
        fixture = (ROOT / "tests/fixtures/hosted-android-repositories/build.gradle").read_text()
        self.assertIn("plugins { id 'java' }", fixture)
        self.assertIn("assert wrappers.size() == 3", fixture)
        self.assertIn("it instanceof ResolutionAwareRepository && it.descriptor instanceof MavenRepositoryDescriptor", fixture)
        self.assertIn("assert gradle.startParameter.offline", fixture)
        self.assertIn("new File('/proc/self/limits')", fixture)
        self.assertIn("assert descriptorFields == ['Max', 'open', 'files', '4096', '4096', 'files']", fixture)
        self.assertIn("nofile_soft: nofileSoft, nofile_hard: nofileHard", fixture)
        self.assertIn("assert caught", fixture)
        for label in ("artifact-url", "unadmitted", "http", "file", "ivy", "flatdir"):
            self.assertIn("deny('" + label + "'", fixture)
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1]
        self.assertLess(source.index('repository_fixture()'), source.index('phase = "public-acquisition-build"'))


class GradleDescriptorProfile(unittest.TestCase):
    def test_only_exact_three_gradle_commands_get_4096_and_other_profiles_stay_1024(self):
        for command, mode in ((M.gradle(True), "acquire"), (M.gradle(False), "compile"),
                              (M.repository_fixture_command(), "compile")):
            previous = M.sandbox(command, mode)
            current = M.gradle_sandbox(command, mode)
            self.assertEqual(previous[3], "--nofile=1024")
            self.assertEqual(current[3], "--nofile=4096:4096")
            self.assertEqual(previous[:3] + previous[4:], current[:3] + current[4:])
        for mode in ("acquire", "compile", "emulator"):
            self.assertEqual(M.sandbox(["inert"], mode)[3], "--nofile=1024")
        for mode in ("acquire", "compile", "browser"):
            self.assertEqual(M.H.sandbox(["inert"], mode=mode,
                writable=M.H.PROOF if mode == "browser" else None)[3], "--nofile=1024")

    def test_arbitrary_commands_changed_arguments_and_wrong_modes_are_rejected(self):
        for command, mode in ((["inert"], "compile"), (M.gradle(True), "compile"),
                (M.gradle(False), "acquire"), (M.repository_fixture_command(), "acquire"),
                (M.gradle(False), "emulator"), (M.gradle(True), "host"),
                (M.gradle(True) + ["unexpectedTask"], "acquire")):
            with self.subTest(command=command, mode=mode), self.assertRaisesRegex(ValueError, "NATIVE_GRADLE_RESOURCE_SCOPE"):
                M.gradle_sandbox(command, mode)
        with patch.object(M, "sandbox", return_value=["/usr/bin/prlimit", "--nofile=1024"]), \
                self.assertRaisesRegex(ValueError, "NATIVE_GRADLE_RESOURCE_TEMPLATE"):
            M.gradle_sandbox(M.gradle(True), "acquire")

    def test_inert_real_prlimit_reproduces_1024_exhaustion_and_4096_success(self):
        # No sandbox/native tool runs: only the exact prlimit prefix and an
        # isolated Python child holding bounded read-only /dev/null descriptors.
        child = r'''
import errno,json,os,resource
fds=[]; exhausted=False
try:
    try:
        for _ in range(1100): fds.append(os.open('/dev/null',os.O_RDONLY|os.O_CLOEXEC))
    except OSError as error:
        if error.errno!=errno.EMFILE: raise
        exhausted=True
    print(json.dumps(dict(opened=len(fds),exhausted=exhausted,limits=resource.getrlimit(resource.RLIMIT_NOFILE))))
finally:
    for fd in fds: os.close(fd)
'''
        before = resource.getrlimit(resource.RLIMIT_NOFILE)
        observed = []
        for argv in (M.sandbox(M.gradle(True), "acquire"), M.gradle_sandbox(M.gradle(True), "acquire")):
            prefix = argv[:argv.index("--") + 1]
            result = subprocess.run([*prefix, sys.executable, "-I", "-c", child],
                check=True, capture_output=True, timeout=10)
            self.assertEqual(result.stderr, b"")
            observed.append(json.loads(result.stdout))
        self.assertEqual(observed[0]["limits"], [1024, 1024])
        self.assertTrue(observed[0]["exhausted"])
        self.assertLess(observed[0]["opened"], 1024)
        self.assertEqual(observed[1], dict(opened=1100, exhausted=False, limits=[4096, 4096]))
        self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE), before)

    def test_both_actual_builds_use_scoped_profile(self):
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1]
        self.assertEqual(source.count('run_app_gradle(True)'), 1)
        self.assertEqual(source.count('run_app_gradle(False)'), 1)
        self.assertEqual(M.MEMORY, 3*M.GIB)
        for acquire, name, mode in ((True, "android-acquisition-build", "acquire"),
                (False, "android-offline-build", "compile")):
            with patch.object(M.H, "run", return_value=b"inert") as run:
                self.assertEqual(M.run_app_gradle(acquire), b"inert")
            args, kwargs = run.call_args
            self.assertEqual(args, (name, M.gradle_sandbox(M.gradle(acquire), mode), 900))
            self.assertEqual(kwargs, dict(env=M.environment(), cwd=M.STAGE/"android", memory=4*M.GIB, memory_categories=True))
        for value in (None, "acquire", 1, [], ["unadmitted"]):
            with patch.object(M.H, "run") as run, self.assertRaisesRegex(ValueError, "NATIVE_APP_BUILD_SCOPE"):
                M.run_app_gradle(value)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
