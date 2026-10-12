# SPDX-License-Identifier: GPL-3.0-only
"""Pure commands/scope/lifecycle contracts; no native tools or policy execution."""
import base64
from contextlib import ExitStack
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

    def test_only_app_builds_receive_exact_heap_and_workers(self):
        expected = "-Dorg.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:ReservedCodeCacheSize=128m -Dfile.encoding=UTF-8"
        for acquire in (True, False):
            argv = M.gradle(acquire)
            self.assertEqual([x for x in argv if x.startswith("-Dorg.gradle.jvmargs=")], [expected])
            self.assertEqual([x for x in argv if x.startswith("--max-workers=")], ["--max-workers=1"])
            self.assertIn("--no-daemon", argv)
            # The exact-command sandbox still rejects restoring the failed heap
            # or worker count, additional overrides and task changes.
            mode = "acquire" if acquire else "compile"
            for changed in ([x.replace("-Xmx1536m", "-Xmx1024m") for x in argv],
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
        self.assertEqual(value, dict(schema=2, kind="hosted-android-gradle-configured-limits",
            scope="acquisition-and-offline-app-build", max_workers=1, d8_thread_pool_size=1,
            cpu_soft_seconds=1800, cpu_hard_seconds=1800,
            jvm_args=["-Xmx1536m", "-XX:MaxMetaspaceSize=512m", "-XX:ReservedCodeCacheSize=128m", "-Dfile.encoding=UTF-8"],
            child_rss_limit_bytes=4294967296, host_reserve_bytes=2147483648, launch_min_available_bytes=6442450944,
            step_timeout_seconds=900, runtime_measurement=False))
        self.assertEqual("-Dorg.gradle.jvmargs=" + " ".join(value["jvm_args"]),
            next(x for x in M.gradle(True) if x.startswith("-Dorg.gradle.jvmargs=")))
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1]
        self.assertLess(source.index('H.save("gradle-resources.json", app_gradle_resources())'),
            source.index('run_app_gradle(True)'))
        self.assertIn('gradle_configured_limits=app_gradle_resources()', source)
        # Neither an adjusted heap nor a forced negative child exit may
        # turn an unconfirmed drain into cleanup success.
        self.assertIn('helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED', source)
        self.assertIn('require(cleanup["complete"], "CLEANUP_UNCONFIRMED")', source)

    def test_d8_project_property_is_exactly_bound_on_both_app_commands_only(self):
        option = "-Pandroid.r8.threadPoolSize=1"
        for acquire, mode in ((True, "acquire"), (False, "compile")):
            command = M.gradle(acquire)
            self.assertEqual([arg for arg in command if "threadPoolSize" in arg], [option])
            self.assertNotIn("threadPoolSize", next(arg for arg in command if arg.startswith("-Dorg.gradle.jvmargs=")))
            sandbox = M.gradle_sandbox(command, mode)
            self.assertEqual(sandbox[-len(command):], command)
            self.assertEqual(sandbox[:5], ["/usr/bin/prlimit", "--core=0", "--cpu=1800:1800", "--nofile=4096:4096", "--"])
            self.assertEqual(M.app_gradle_resources()["d8_thread_pool_size"], int(option.rsplit("=", 1)[1]))
            for replacement in ("-Pandroid.r8.threadPoolSize=2", "-Pandroid.r8.threadPoolSize=0",
                    "-Dandroid.r8.threadPoolSize=1", "-Pandroid.r8.maxWorkers=1"):
                changed = [replacement if arg == option else arg for arg in command]
                with self.assertRaisesRegex(ValueError, "NATIVE_GRADLE_RESOURCE_SCOPE"):
                    M.gradle_sandbox(changed, mode)
            for changed in ([arg for arg in command if arg != option], command + [option]):
                with self.assertRaisesRegex(ValueError, "NATIVE_GRADLE_RESOURCE_SCOPE"):
                    M.gradle_sandbox(changed, mode)
        self.assertFalse(any("threadPoolSize" in arg for arg in M.repository_fixture_command()))
        self.assertFalse(any("threadPoolSize" in value for value in M.environment().values()))
        self.assertNotIn("threadPoolSize", (ROOT / "tests/fixtures/hosted-android-repositories/gradle.properties").read_text())

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


class AptAwkProvenance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "mawk"
        self.raw = b"inert declared distro helper; never executed\n"
        self.target.write_bytes(self.raw)
        self.target.chmod(0o755)
        self.scope = ExitStack()
        self.addCleanup(self.scope.close)
        self.scope.enter_context(patch.object(M, "AWK", self.target))
        real_lstat = Path.lstat
        def root_lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if path == self.target:
                fields = ("st_dev", "st_ino", "st_mode", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
                return SimpleNamespace(st_uid=0, **{key: getattr(info, key) for key in fields})
            return info
        self.scope.enter_context(patch.object(Path, "lstat", root_lstat))

    def test_fixed_root_owned_descriptor_digest_without_execution(self):
        with patch.object(M.os, "fstat", side_effect=root_file_stat), patch.object(M.subprocess, "Popen") as execute:
            observed = M.apt_awk_digest()
        self.assertEqual(observed, dict(bytes=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest()))
        execute.assert_not_called()

    def test_unsafe_ownership_type_mode_link_and_size_are_rejected(self):
        bad = (dict(st_uid=1001), dict(st_uid=65534), dict(st_nlink=2), dict(st_size=0),
            dict(st_size=M.AWK_LIMIT + 1), dict(st_mode=stat.S_IFDIR | 0o755),
            *(dict(st_mode=stat.S_IFREG | mode) for mode in (0o644, 0o775, 0o757, 0o4755, 0o2755, 0o1755)))
        for changes in bad:
            with self.subTest(changes=changes), patch.object(M.os, "fstat", side_effect=lambda fd: root_file_stat(fd, **changes)), \
                    self.assertRaisesRegex(ValueError, "AWK_TOOL"):
                M.apt_awk_digest()
        self.target.unlink(); self.target.symlink_to(self.root / "not-allowed")
        with self.assertRaisesRegex(ValueError, "AWK_TOOL_PATH"): M.apt_awk_digest()

    def test_fifo_read_is_nonblocking_and_own_descriptor_closes(self):
        self.target.unlink(); os.mkfifo(self.target, 0o600)
        opened, actual_open = [], os.open
        def open_fixed(path, flags):
            self.assertEqual(path, self.target)
            self.assertTrue(flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK and flags & os.O_CLOEXEC)
            opened.append(actual_open(path, flags)); return opened[-1]
        with patch.object(M.os, "open", side_effect=open_fixed), patch.object(M.os, "fstat", side_effect=root_file_stat), \
                self.assertRaisesRegex(ValueError, "AWK_TOOL"):
            M.apt_awk_digest()
        with self.assertRaises(OSError): FSTAT(opened[0])

    def test_same_fd_mutation_and_equal_byte_path_replacement_are_rejected(self):
        read = os.read
        for renamed in (False, True):
            with self.subTest(renamed=renamed):
                self.target.write_bytes(self.raw); self.target.chmod(0o755)
                replaced = []
                def change(fd, size):
                    raw = read(fd, size)
                    if raw and not replaced:
                        replaced.append(fd)
                        if renamed:
                            self.target.rename(self.root / "old-helper")
                            self.target.write_bytes(self.raw); self.target.chmod(0o755)
                        else:
                            self.target.write_bytes(b"x" * len(self.raw))
                            info = self.target.stat()
                            os.utime(self.target, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                    return raw
                with patch.object(M.os, "fstat", side_effect=root_file_stat), patch.object(M.os, "read", side_effect=change), \
                        self.assertRaisesRegex(ValueError, "AWK_TOOL_CHANGED"):
                    M.apt_awk_digest()
                with self.assertRaises(OSError): FSTAT(replaced[0])

    def test_growth_read_bound_is_not_only_initial_stat(self):
        with patch.object(M, "AWK_LIMIT", 8), patch.object(M.os, "fstat", side_effect=lambda fd: root_file_stat(fd, st_size=8)), \
                self.assertRaisesRegex(ValueError, "AWK_TOOL_BOUND"):
            M.apt_awk_digest()

    def test_alias_is_android_only_before_readonly_root_and_uses_no_alternatives_bind(self):
        for mode in ("acquire", "compile", "emulator"):
            argv = M.sandbox(["inert"], mode)
            aliases = [argv[i:i+3] for i, value in enumerate(argv) if value == "--symlink" and argv[i+2] == "/tools/awk"]
            self.assertEqual(aliases, [["--symlink", str(self.target), "/tools/awk"]])
            self.assertLess(argv.index("/tools/awk"), argv.index("--remount-ro"))
            self.assertNotIn("/etc/alternatives", argv)
            self.assertEqual(argv[:5], ["/usr/bin/prlimit", "--core=0", "--cpu=900", "--nofile=1024", "--"])
        for mode in ("acquire", "compile"):
            self.assertNotIn("/tools/awk", M.W.sandbox(["inert"], mode=mode))
        self.assertIn("shutil.which('awk')=='/tools/awk'", M.PROBE)
        self.assertIn("os.readlink('/tools/awk')=='/usr/bin/mawk'", M.PROBE)
        self.assertIn("('/tools','/usr/bin/mawk')", M.PROBE)

    def test_initial_provenance_and_full_trial_rechecks_remain_required(self):
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1].split("def inside(", 1)[0]
        self.assertLess(source.index('awk = apt_awk_digest()'), source.index('phase = "policy-install"'))
        self.assertIn('sandbox_alias="/tools/awk"', source)
        full = source.split('phase = "installed-emulator-trial"', 1)[1]
        self.assertLess(full.index('require(apt_awk_digest() == awk'), full.index('H.run("installed-android-trial"'))
        self.assertGreater(full.rindex('require(apt_awk_digest() == awk'), full.index('H.run("installed-android-trial"'))
        self.assertIn('validate_report(original)', full)

    def test_changed_awk_rejected_before_early_sandbox_or_sdk_execution(self):
        with patch.object(M, "avd_input_identity", return_value={}), patch.object(M, "apt_java_digest", return_value={}), \
                patch.object(M, "apt_awk_digest", return_value={"sha256": "b"*64}), \
                patch.object(M, "preflight") as preflight, patch.object(M.H, "run") as run, \
                self.assertRaisesRegex(ValueError, "AWK_TOOL_CHANGED"):
            M.avd_preflight("inert", awk={"sha256": "a"*64})
        preflight.assert_not_called()
        run.assert_not_called()


class RepositoryFixture(unittest.TestCase):
    @staticmethod
    def receipt(**changes):
        value = dict(schema=3, kind="gradle-repository-contract", gradle_version="8.13", plugin_wrappers=3,
            rejected=["artifact-url", "unadmitted", "http", "file", "ivy", "flatdir"], networkless=True,
            external_dependencies=False, nofile_soft=4096, nofile_hard=4096, kotlin_property_scopes=["root", "included"])
        value.update(changes)
        return b"NATIVE_REPOSITORY_FIXTURE " + json.dumps(value).encode() + b"\n"

    def test_exact_runtime_receipt_required_not_a_success_message_or_mock_count(self):
        self.assertEqual(M.repository_fixture_report(b"Gradle output\n" + self.receipt())["plugin_wrappers"], 3)
        for raw in (b"BUILD SUCCESSFUL", self.receipt() * 2, self.receipt(plugin_wrappers=0),
                self.receipt(plugin_wrappers=True), self.receipt(plugin_wrappers=3.0), self.receipt(schema=True),
                self.receipt(rejected=[]), self.receipt(networkless=False), self.receipt(networkless=1),
                self.receipt(external_dependencies=True), self.receipt(external_dependencies=0),
                self.receipt(schema=1), self.receipt(schema=2), self.receipt(kotlin_property_scopes=["root"]),
                self.receipt(kotlin_property_scopes=["included", "root"]),
                self.receipt(nofile_soft=1024), self.receipt(nofile_hard=8192),
                self.receipt(nofile_soft=4096.0), self.receipt(nofile_hard=None),
                self.receipt(gradle_version="8.14"), self.receipt(extra="not closed")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                M.repository_fixture_report(raw)
        with self.assertRaises(ValueError):
            M.repository_fixture_report(b"x" * (M.H.LIMIT + 1))

    def fixture_paths(self, directory, properties=None):
        sdk, stage, private = (directory / name for name in ("sdk", "stage", "private"))
        private.mkdir(mode=0o700)
        (private / "gradle-home").mkdir(mode=0o700)
        with patch.object(M, "PRIVATE", private):
            M.prepare_gradle_user_properties()
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
            self.assertEqual(len(saved["fixture_files"]), 8)
            self.assertEqual(saved["fixture_files"]["compiler-property/build.gradle"],
                M.H.sha((ROOT / "tests/fixtures/hosted-android-repositories/compiler-property/build.gradle").read_bytes()))
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
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        private = Path(temporary.name)
        (private / "gradle-home").mkdir(mode=0o700)
        scope = patch.object(M, "PRIVATE", private)
        scope.start()
        self.addCleanup(scope.stop)
        M.prepare_gradle_user_properties()

    def test_app_cpu_hard_limit_admission_is_read_only_and_before_child(self):
        for hard in (resource.RLIM_INFINITY, 1800, 3600, 1799, 900):
            with patch.object(M.resource, "getrlimit", return_value=(900, hard)) as read, \
                    patch.object(M.resource, "setrlimit") as write, patch.object(M.D, "Capture"), \
                    patch.object(M.H, "run", return_value=b"inert") as run:
                if hard == resource.RLIM_INFINITY or hard >= 1800:
                    self.assertEqual(M.run_app_gradle(True), b"inert")
                    run.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, "NATIVE_APP_CPU_PARENT_LIMIT"):
                        M.run_app_gradle(True)
                    run.assert_not_called()
                read.assert_called_once_with(resource.RLIMIT_CPU)
                write.assert_not_called()

    def test_real_inert_cpu_limits_are_single_boundary_and_parent_unchanged(self):
        before = resource.getrlimit(resource.RLIMIT_CPU)
        child = "import json,resource;print(json.dumps(resource.getrlimit(resource.RLIMIT_CPU)))"
        for command, mode, expected in ((M.gradle(True), "acquire", [1800, 1800]),
                (M.gradle(False), "compile", [1800, 1800]),
                (M.repository_fixture_command(), "compile", [900, 900])):
            argv = M.gradle_sandbox(command, mode)
            self.assertEqual(argv.count("/usr/bin/prlimit"), 1)
            self.assertEqual([arg for arg in argv if arg.startswith("--cpu=")],
                ["--cpu=900"] if expected[0] == 900 else ["--cpu=1800:1800"])
            # Execute only the real resource prefix and a tiny Python child,
            # never bwrap/Java/Gradle or a CPU-consuming workload.
            result = subprocess.run([*argv[:argv.index("--")+1], sys.executable, "-I", "-c", child],
                check=True, capture_output=True, timeout=10)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CPU), before)
        # A hard 900 ancestor really cannot raise itself to 1800 without
        # privilege. Only this disposable Python child lowers its own limit.
        restricted = "import resource;resource.setrlimit(resource.RLIMIT_CPU,(900,900));" \
            "\ntry: resource.setrlimit(resource.RLIMIT_CPU,(1800,1800))" \
            "\nexcept (ValueError,PermissionError): print('raise-refused')"
        result = subprocess.run([sys.executable, "-I", "-c", restricted],
            check=True, capture_output=True, timeout=10)
        self.assertEqual(result.stdout, b"raise-refused\n")
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CPU), before)

    def test_diagnostic_cancellation_is_not_swallowed_to_launch_a_build(self):
        with patch.object(M.D, "Capture", side_effect=M.H.Interrupted("cancelled")), patch.object(M.H, "run") as run:
            with self.assertRaises(M.H.Interrupted): M.run_app_gradle(True)
        run.assert_not_called()

    def test_diagnostics_finish_after_run_drains_and_never_replace_primary_failure(self):
        for failure in ("constructor", "collector", "write", None):
            observer = Mock()
            observer.finish.return_value = {"closed": True}
            if failure == "collector": observer.finish.side_effect = OSError("private details")
            def run(*args, **kwargs):
                M.H.DRAIN_CONFIRMED = False
                M.H.LOGS.append(dict(name="android-acquisition-build", java_cpu={"closed_cpu": True}))
                raise ValueError("ORIGINAL_BUILD_FAILURE")
            with patch.object(M.D, "Capture", side_effect=OSError("inert") if failure == "constructor" else None,
                    return_value=observer), patch.object(M.H, "LOGS", []), patch.object(M.H, "DRAIN_CONFIRMED", True), \
                    patch.object(M.H, "run", side_effect=run), patch.object(M.H, "save",
                        side_effect=OSError("inert") if failure == "write" else None) as save:
                with self.assertRaisesRegex(ValueError, "^ORIGINAL_BUILD_FAILURE$"):
                    M.run_app_gradle(True)
                if failure != "constructor":
                    observer.finish.assert_called_once_with(drained=False, java_cpu={"closed_cpu": True})
                if failure is None:
                    save.assert_called_once_with("android-acquisition-build-diagnostics.json", {"closed": True})

    def test_only_exact_three_gradle_commands_get_4096_and_other_profiles_stay_1024(self):
        for command, mode in ((M.gradle(True), "acquire"), (M.gradle(False), "compile"),
                              (M.repository_fixture_command(), "compile")):
            previous = M.sandbox(command, mode)
            current = M.gradle_sandbox(command, mode)
            self.assertEqual(previous[3], "--nofile=1024")
            self.assertEqual(current[3], "--nofile=4096:4096")
            self.assertEqual(previous[:2] + previous[4:], current[:2] + current[4:])
            self.assertEqual(previous[2], "--cpu=900")
            self.assertEqual(current[2], "--cpu=900" if command == M.repository_fixture_command() else "--cpu=1800:1800")
        for mode in ("acquire", "compile", "emulator"):
            self.assertEqual(M.sandbox(["inert"], mode)[3], "--nofile=1024")
            self.assertEqual(M.sandbox(["inert"], mode)[2], "--cpu=900")
        for mode in ("acquire", "compile", "browser"):
            self.assertEqual(M.H.sandbox(["inert"], mode=mode,
                writable=M.H.PROOF if mode == "browser" else None)[3], "--nofile=1024")
            self.assertEqual(M.H.sandbox(["inert"], mode=mode,
                writable=M.H.PROOF if mode == "browser" else None)[2], "--cpu=300")

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
            with patch.object(M.H, "run", return_value=b"inert") as run, patch.object(M.D, "Capture"):
                self.assertEqual(M.run_app_gradle(acquire), b"inert")
            args, kwargs = run.call_args
            self.assertEqual(args, (name, M.gradle_sandbox(M.gradle(acquire), mode), 900))
            self.assertEqual(kwargs, dict(env=M.environment(), cwd=M.STAGE/"android", memory=4*M.GIB,
                memory_categories=True, java_cpu=True))
        for value in (None, "acquire", 1, [], ["unadmitted"]):
            with patch.object(M.H, "run") as run, self.assertRaisesRegex(ValueError, "NATIVE_APP_BUILD_SCOPE"):
                M.run_app_gradle(value)
            run.assert_not_called()


class GradleUserProperties(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.private = Path(temporary.name)
        (self.private / "gradle-home").mkdir(mode=0o700)
        self.target = self.private / "gradle-home/gradle.properties"
        scope = patch.object(M, "PRIVATE", self.private)
        scope.start()
        self.addCleanup(scope.stop)

    def test_exact_private_initialization_and_non_overwriting(self):
        receipt = M.prepare_gradle_user_properties()
        self.assertEqual(self.target.read_bytes(), b"kotlin.compiler.execution.strategy=in-process\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertEqual(receipt, dict(schema=1, kind="hosted-android-kotlin-configured-scope",
            scopes=["main-build", "included-builds"], compiler_execution_strategy="in-process",
            bytes=46, sha256=hashlib.sha256(self.target.read_bytes()).hexdigest(), runtime_measurement=False))
        with self.assertRaises(FileExistsError):
            M.prepare_gradle_user_properties()
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text().split("def execute(", 1)[1]
        self.assertLess(source.index('prepare_gradle_user_properties()'), source.index('repository_fixture()'))
        self.assertLess(source.index('prepare_gradle_user_properties()'), source.index('preflight("compile"'))
        original = (ROOT / "integrations/overmorrow/prepare_native_android.py").read_text()
        self.assertIn("kotlin.compiler.execution.strategy=in-process", original)

    def test_changed_missing_oversized_mode_and_link_are_rejected_before_either_build(self):
        for bad in ("missing", "changed", "oversized", "mode", "link", "hardlink"):
            with self.subTest(bad=bad):
                if self.target.exists() or self.target.is_symlink(): self.target.unlink()
                if bad != "missing": M.prepare_gradle_user_properties()
                if bad == "changed": self.target.write_bytes(b"kotlin.compiler.execution.strategy=daemon    \n")
                if bad == "oversized": self.target.write_bytes(b"x" * 1024)
                if bad == "mode": self.target.chmod(0o644)
                if bad in ("link", "hardlink"):
                    other = self.private / ("other-" + bad)
                    self.target.rename(other)
                    if bad == "link": self.target.symlink_to(other)
                    else: os.link(other, self.target)
                for acquire in (True, False):
                    with patch.object(M.H, "run") as child, self.assertRaises((OSError, ValueError)):
                        M.run_app_gradle(acquire)
                    child.assert_not_called()

    def test_private_parent_and_changed_same_length_bytes_rejected(self):
        M.prepare_gradle_user_properties()
        self.target.parent.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "GRADLE_USER_HOME_PRIVATE"):
            M.verify_gradle_user_properties()
        self.target.parent.chmod(0o700)
        raw = M.GRADLE_USER_PROPERTIES.replace(b"in-process", b"notprocess")
        self.assertEqual(len(raw), len(M.GRADLE_USER_PROPERTIES))
        self.target.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "GRADLE_USER_PROPERTIES_CHANGED"):
            M.verify_gradle_user_properties()

    def test_sandbox_mount_is_exact_readonly_file_inside_private_home(self):
        for mode in ("acquire", "compile", "emulator"):
            argv = M.sandbox(["inert"], mode)
            matches = [argv[i:i+3] for i, value in enumerate(argv) if value == "--ro-bind"
                and argv[i+2] == "/state/gradle-home/gradle.properties"]
            self.assertEqual(matches, [["--ro-bind", str(self.target), "/state/gradle-home/gradle.properties"]])
            self.assertLess(argv.index(str(self.target)), argv.index("--remount-ro"))
            self.assertEqual(M.environment()["GRADLE_USER_HOME"], "/state/gradle-home")
        self.assertIn("assert os.statvfs(properties).f_flag & os.ST_RDONLY", M.PROBE)
        self.assertIn("assert not os.statvfs(properties.parent).f_flag & os.ST_RDONLY", M.PROBE)

    def test_equal_bytes_path_replacement_after_fd_check_is_rejected(self):
        M.prepare_gradle_user_properties()
        original_lstat = Path.lstat
        def replace_before_named_check(path, *args, **kwargs):
            if path == self.target:
                path.rename(self.private / "original-properties")
                M.H.write(path, M.GRADLE_USER_PROPERTIES)
            return original_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", replace_before_named_check), \
                self.assertRaisesRegex(ValueError, "GRADLE_USER_PROPERTIES_CHANGED"):
            M.verify_gradle_user_properties()
        self.assertEqual(self.target.read_bytes(), M.GRADLE_USER_PROPERTIES)

    def test_hosted_included_build_assertion_is_a_real_dependency_without_downloads(self):
        fixture = ROOT / "tests/fixtures/hosted-android-repositories"
        root = (fixture / "build.gradle").read_text()
        included = (fixture / "compiler-property/build.gradle").read_text()
        self.assertIn("includeBuild('compiler-property')", (fixture / "settings.gradle").read_text())
        self.assertIn("dependsOn(gradle.includedBuild('compiler-property').task(':verifyCompilerProperty'))", root)
        assertion = "assert providers.gradleProperty('kotlin.compiler.execution.strategy').get() == 'in-process'"
        self.assertIn(assertion, root)
        self.assertIn(assertion, included)
        self.assertIn("assert !file('gradle.properties').exists()", included)
        self.assertIn("assert gradle.startParameter.offline", included)
        self.assertIn("assert !target.exists()", included)
        self.assertFalse((fixture / "compiler-property/gradle.properties").exists())
        self.assertNotIn("kotlin.compiler.execution.strategy", (fixture / "gradle.properties").read_text())
        self.assertNotIn("plugins {", included)
        self.assertIn("assert includedProperty.getText('US-ASCII') == 'in-process\\n'", root)


class EmulatorDiagnostics(unittest.TestCase):
    def test_known_markers_are_closed_indications_and_ambiguous_or_missing_is_not_cause(self):
        cases = {
            "java_version": b'Exception in thread "main" java.lang.UnsupportedClassVersionError: private-class\n',
            "java_home": b'ERROR: JAVA_HOME is set to an invalid directory: /private/canary\n',
            "sdk_root": b'Error: Could not determine SDK root. /private/canary\n',
            "sdk_package": b'Error: Package path is not valid. Valid system image paths are:\nprivate-canary\n',
            "sdk_license": b'com.android.builder.sdk.LicenceNotAcceptedException: private-canary\n',
            "java_classpath": b'Exception in thread "main" java.lang.NoClassDefFoundError: private-canary\n',
            "java_initialization": b'Exception in thread "main" java.lang.ExceptionInInitializerError\nprivate-canary\n',
            "launcher_helper": b'/tools/android-inputs/sdk/cmdline-tools/19.0/bin/avdmanager: 172: awk: not found\nprivate-canary\n',
            "sdk_image": b'Error: Package private-canary contains no system images.\n',
            "sdk_avd": b'Error: AVD not created.\nprivate-canary\n',
            "unknown": b'private-canary https://private.invalid/?token=secret\n',
            "ambiguous": b'Error: Could not determine SDK root.\nJava version 17 or higher is required.\n',
        }
        for expected, raw in cases.items():
            with self.subTest(expected=expected):
                diagnostic = M.EmulatorDiagnostic(); diagnostic.phase = "avd_create"
                error = subprocess.CalledProcessError(7, ["private-argv"], output=raw)
                diagnostic.failed_command(error, "avdmanager", 7, raw, True)
                result = diagnostic.receipt(error)
                self.assertEqual(result["sdk_error"], expected)
                self.assertEqual(result["failure_kind"], "command_exit")
                self.assertEqual(result["exit_status"], 7)
                self.assertTrue(result["output_complete"])
                self.assertFalse(result["raw_text_exported"] or result["cause_established"])
                encoded = json.dumps(result)
                self.assertLess(len(encoded), 1024)
                for forbidden in ("private-canary", "private-class", "private-argv", "private.invalid", "secret"):
                    self.assertNotIn(forbidden, encoded)

    def test_unknown_fields_bounds_and_caught_boot_errors_do_not_misattribute(self):
        diagnostic = M.EmulatorDiagnostic(); diagnostic.phase = "/private/phase"
        error = ValueError("EMULATOR_COMMAND_OUTPUT")
        diagnostic.failed_command(error, "/private/argv", -999,
            b"x" * 65536 + b"Error: Could not determine SDK root.", False)
        result = diagnostic.receipt(error)
        self.assertEqual(result["phase"], "unknown")
        self.assertEqual(result["command_category"], "unknown")
        self.assertIsNone(result["exit_status"])
        self.assertEqual(result["output_bytes"], 65536)
        self.assertTrue(result["output_truncated"])
        self.assertFalse(result["output_complete"])
        self.assertEqual(result["sdk_error"], "unknown")
        diagnostic.phase = "boot"
        later = diagnostic.receipt(ValueError("EMULATOR_BOOT_FAILED"))
        self.assertEqual(later["command_category"], "none")
        self.assertEqual(later["output_bytes"], 0)
        self.assertIsNone(later["exit_status"])
        self.assertEqual(later["check_code"], "EMULATOR_BOOT_FAILED")
        self.assertEqual(diagnostic.receipt(ValueError("private exception token"))["check_code"], "unknown")

    def guarded_inside(self, proof, popen):
        """Only fake guard observations and an explicit inert Python child.

        No native executable, /state mutation, namespace or policy operation.
        """
        stack = ExitStack()
        self.addCleanup(stack.close)
        original_read, original_exists = Path.read_text, Path.exists
        def read(path, *args, **kwargs):
            return "volparossa_ci_weather_clients_child" if str(path) == "/proc/self/attr/current" else original_read(path, *args, **kwargs)
        def exists(path):
            return False if str(path) in ("/etc/resolv.conf", "/state/avd", "/state/android-home", "/state/native-fixture") else original_exists(path)
        stack.enter_context(patch.object(M, "PROOF", proof))
        stack.enter_context(patch.object(M.os, "getuid", return_value=1000))
        stack.enter_context(patch.object(M.socket, "if_nameindex", return_value=[(1, "lo")]))
        stack.enter_context(patch.object(Path, "read_text", read))
        stack.enter_context(patch.object(Path, "exists", exists))
        stack.enter_context(patch.object(M.subprocess, "Popen", side_effect=popen))
        return stack

    def inert_popen(self, code, children):
        original = subprocess.Popen
        def spawn(argv, **kwargs):
            self.assertEqual(argv[0], str(M.ANDROID / "cmdline-tools/19.0/bin/avdmanager"))
            self.assertEqual(argv[1:4], ["create", "avd", "--name"])
            child = original([sys.executable, "-I", "-c", code], **kwargs)
            children.append(child)
            return child
        return spawn

    def test_real_inert_failure_is_recorded_before_original_cleanup_and_exception_survives(self):
        children, order = [], []
        code = "import sys;sys.stdin.read();print('Error: Package path is not valid.');print('private-token');sys.exit(7)"
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            self.guarded_inside(proof, self.inert_popen(code, children))
            original_drain = M.drain_children
            def drain(owned):
                value = json.loads((proof / "emulator-diagnostic.json").read_text())
                self.assertEqual(value["exit_status"], 7)
                self.assertEqual(value["sdk_error"], "sdk_package")
                self.assertEqual(owned[0].returncode, 7)
                order.append("diagnostic-before-drain")
                return original_drain(owned)
            with patch.object(M, "drain_children", side_effect=drain), self.assertRaises(subprocess.CalledProcessError) as raised:
                M.inside()
            self.assertEqual(raised.exception.returncode, 7)
            self.assertEqual(order, ["diagnostic-before-drain"])
            raw = (proof / "emulator-diagnostic.json").read_bytes()
            self.assertLessEqual(len(raw), 1024)
            self.assertNotIn(b"private-token", raw)
            self.assertEqual((proof / "emulator-diagnostic.json").stat().st_mode & 0o777, 0o600)
            self.assertFalse((proof / "emulator-diagnostic.part").exists())
            cleanup = json.loads((proof / "emulator-cleanup.json").read_text())
            self.assertTrue(cleanup["direct_children_reaped"] and cleanup["private_avd_removed"])
            self.assertFalse(cleanup["trial_returned"])
            self.assertTrue(all(c.poll() is not None and c.stdout.closed and c.stdin.closed for c in children))

    def test_spawn_failure_has_no_invented_exit_or_output_and_cleanup_still_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            original = FileNotFoundError("private path/token")
            self.guarded_inside(proof, Mock(side_effect=original))
            with self.assertRaises(FileNotFoundError) as raised: M.inside()
            self.assertIs(raised.exception, original)
            result = json.loads((proof / "emulator-diagnostic.json").read_text())
            self.assertEqual(result["phase"], "avd_create")
            self.assertEqual(result["command_category"], "avdmanager")
            self.assertEqual(result["failure_kind"], "not_found")
            self.assertIsNone(result["exit_status"])
            self.assertEqual(result["output_bytes"], 0)
            self.assertFalse(result["output_complete"])
            self.assertTrue(json.loads((proof / "emulator-cleanup.json").read_text())["direct_children_reaped"])

    def test_output_limit_retains_only_bounded_classification_and_reaps_real_inert_child(self):
        children = []
        code = "import os,sys;sys.stdin.read();os.write(1,b'x'*70000);import time;time.sleep(30)"
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            self.guarded_inside(proof, self.inert_popen(code, children))
            with self.assertRaisesRegex(ValueError, "EMULATOR_COMMAND_OUTPUT"): M.inside()
            result = json.loads((proof / "emulator-diagnostic.json").read_text())
            self.assertEqual(result["failure_kind"], "output_bound")
            self.assertEqual(result["output_bytes"], 65536)
            self.assertTrue(result["output_truncated"])
            self.assertFalse(result["output_complete"])
            self.assertIsNone(result["exit_status"])
            self.assertTrue(all(c.poll() is not None for c in children))

    def test_timeout_and_diagnostic_write_failure_keep_original_failure_and_cleanup(self):
        for failed_write in (False, True):
            with self.subTest(failed_write=failed_write), tempfile.TemporaryDirectory() as directory:
                children, proof = [], Path(directory)
                with self.guarded_inside(proof, self.inert_popen("import time;time.sleep(30)", children)):
                    original = subprocess.TimeoutExpired("private-cmd-token", 20)
                    original_write = M.H.write
                    def write(path, raw):
                        if failed_write and path.name == "emulator-diagnostic.part":
                            raise PermissionError("private IO failure")
                        return original_write(path, raw)
                    with patch.object(M.selectors, "DefaultSelector", side_effect=original), \
                            patch.object(M.H, "write", side_effect=write), self.assertRaises(subprocess.TimeoutExpired) as raised:
                        M.inside()
                    self.assertIs(raised.exception, original)
                    self.assertTrue(all(c.poll() is not None and c.stdout.closed for c in children))
                    self.assertTrue(json.loads((proof / "emulator-cleanup.json").read_text())["direct_children_reaped"])
                    if failed_write:
                        self.assertFalse((proof / "emulator-diagnostic.json").exists())
                    else:
                        result = json.loads((proof / "emulator-diagnostic.json").read_text())
                        self.assertEqual(result["failure_kind"], "deadline")
                        self.assertIsNone(result["exit_status"])
                        self.assertFalse(result["output_complete"])


class AvdPreflight(unittest.TestCase):
    def observation(self):
        return dict(schema=1, kind="hosted-android-avd-preflight-inputs", inputs={"fixed_test_identity": True},
            posix_helpers={name: True for name in ("sh", "dirname", "basename", "uname", "sed", "awk", "expr", "ls")},
            sdk_read_only=True, raw_text_exported=False, cause_established=False)

    def cleanup(self):
        return dict(schema=1, direct_children_reaped=True, private_avd_removed=True,
            private_android_home_removed=True, avd_creation_returned=True, installed_app_exercised=False,
            enclosing_namespace_cleanup_required=True)

    def test_exact_original_command_is_shared_and_early_before_any_gradle_or_pub(self):
        self.assertEqual(M.avd_command(), [str(M.ANDROID / "cmdline-tools/19.0/bin/avdmanager"), "create", "avd",
            "--name", "volparossa_trial", "--package", "system-images;android-36;default;x86_64", "--path", "/state/avd/trial.avd"])
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text()
        execute = source.split("def execute(", 1)[1].split("def inside(", 1)[0]
        self.assertEqual(execute.count('H.private_directory(PROOF)'), 1)
        for later in ('repository_fixture()', 'flutter("pub"', 'run_app_gradle(True)', 'run_app_gradle(False)'):
            self.assertLess(execute.index('avd_preflight(netns, awk=awk)'), execute.index(later))
        self.assertIn('H.sha(H.read(OUTPUT / "emulator-preflight.json"))', execute)
        self.assertIn('validate_report(original)', execute)
        self.assertIn('"--inside"], "emulator")', execute)
        inside = source.split("def inside(", 1)[1]
        self.assertEqual(inside.count('command("avdmanager", avd_command(), 30, b"no\\n")'), 1)
        with self.assertRaises(ValueError):
            M.validate_report(dict(schema=1, kind="hosted-android-avd-preflight", success=True))

    def test_real_inert_success_stops_after_single_create_and_keeps_separate_receipts(self):
        children = []
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            # Never execute SDK tools: replace only the Popen boundary with a
            # real tiny Python child consuming the same fixed stdin response.
            code = "import sys;assert sys.stdin.read()=='no\\n';print('private canary')"
            spawn = EmulatorDiagnostics.inert_popen(self, code, children)
            EmulatorDiagnostics.guarded_inside(self, proof, spawn)
            with patch.object(M, "avd_observations", return_value=self.observation()):
                M.inside(avd_only=True)
            self.assertEqual(len(children), 1)
            self.assertTrue(all(c.returncode == 0 and c.stdout.closed and c.stdin.closed for c in children))
            self.assertEqual(json.loads((proof / "emulator-preflight-cleanup.json").read_text()), self.cleanup())
            self.assertEqual(json.loads((proof / "emulator-preflight-inputs.json").read_text()), self.observation())
            self.assertEqual({p.name for p in proof.iterdir()}, {"emulator-preflight-inputs.json", "emulator-preflight-cleanup.json"})
            self.assertFalse((proof / "report.json").exists())

    def test_real_inert_preflight_failure_preserves_original_and_never_overwrites_full_trial(self):
        children = []
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            (proof / "emulator-diagnostic.json").write_bytes(b"unchanged")
            (proof / "emulator-cleanup.json").write_bytes(b"unchanged")
            spawn = EmulatorDiagnostics.inert_popen(self,
                "import sys;sys.stdin.read();print('Error: AVD not created.');print('private token');sys.exit(9)", children)
            EmulatorDiagnostics.guarded_inside(self, proof, spawn)
            with patch.object(M, "avd_observations", return_value=self.observation()), \
                    self.assertRaises(subprocess.CalledProcessError) as error:
                M.inside(avd_only=True)
            self.assertEqual(error.exception.returncode, 9)
            raw = (proof / "emulator-preflight-diagnostic.json").read_bytes()
            diagnostic = json.loads(raw)
            self.assertEqual((diagnostic["command_category"], diagnostic["sdk_error"], diagnostic["exit_status"]),
                ("avdmanager", "sdk_avd", 9))
            self.assertLessEqual(len(raw), 1024)
            self.assertNotIn(b"private token", raw)
            self.assertEqual(json.loads((proof / "emulator-preflight-cleanup.json").read_text()),
                dict(self.cleanup(), avd_creation_returned=False))
            self.assertEqual((proof / "emulator-diagnostic.json").read_bytes(), b"unchanged")
            self.assertEqual((proof / "emulator-cleanup.json").read_bytes(), b"unchanged")
            self.assertTrue(all(c.poll() is not None and c.stdout.closed for c in children))

    def test_preflight_absolute_thirty_seconds_and_inert_child_cleanup(self):
        children = []
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            spawn = EmulatorDiagnostics.inert_popen(self, "import time;time.sleep(30)", children)
            EmulatorDiagnostics.guarded_inside(self, proof, spawn)
            with patch.object(M, "avd_observations", return_value=self.observation()), \
                    patch.object(M.time, "monotonic", side_effect=[0, 29, 29, 30]), \
                    self.assertRaisesRegex(ValueError, "EMULATOR_COMMAND_DEADLINE"):
                M.inside(avd_only=True)
            diagnostic = json.loads((proof / "emulator-preflight-diagnostic.json").read_text())
            self.assertEqual(diagnostic["failure_kind"], "deadline")
            self.assertTrue(json.loads((proof / "emulator-preflight-cleanup.json").read_text())["direct_children_reaped"])
            self.assertTrue(all(c.poll() is not None for c in children))

    def test_outer_binding_cleanup_and_fresh_state_are_mandatory(self):
        cases = (None, "input", "java", "awk", "alias", "cleanup", "scope", "unknown", "child")
        for bad in cases:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); proof = root / "proof"; proof.mkdir()
                private = root / "private"; private.mkdir()
                observed, cleanup = self.observation(), self.cleanup()
                if bad == "input": observed["inputs"] = {"changed": True}
                if bad == "cleanup": cleanup["direct_children_reaped"] = False
                if bad == "scope": cleanup["installed_app_exercised"] = True
                if bad == "unknown": observed["unclosed"] = "private"
                if bad == "alias": observed["posix_helpers"]["awk"] = False
                for name, value in (("inputs", observed), ("cleanup", cleanup)):
                    M.H.write(proof / ("emulator-preflight-" + name + ".json"), json.dumps(value).encode())
                java = dict(bytes=1, sha256="a"*64)
                with patch.object(M, "PROOF", proof), patch.object(M, "PRIVATE", private), \
                        patch.object(M, "avd_input_identity", return_value=self.observation()["inputs"]), \
                        patch.object(M, "apt_java_digest", side_effect=[java, dict(java, sha256="b"*64) if bad == "java" else java]), \
                        patch.object(M, "apt_awk_digest", side_effect=[java, dict(java, sha256="b"*64) if bad == "awk" else java]), \
                        patch.object(M, "preflight") as preflight, patch.object(M.H, "save") as save, \
                        patch.object(M.H, "run", side_effect=ValueError("original-child-failure") if bad == "child" else None) as run:
                    if bad is None:
                        M.avd_preflight("inert-netns", awk=java)
                        self.assertEqual({p.name for p in private.iterdir()}, {"avd", "android-home"})
                        self.assertFalse(save.call_args.args[1]["installed_app_exercised"])
                        self.assertEqual(save.call_args.args[1]["creation_timeout_seconds"], 30)
                    else:
                        with self.assertRaises(ValueError): M.avd_preflight("inert-netns", awk=java)
                        save.assert_not_called()
                        self.assertEqual(list(private.iterdir()), [])
                    preflight.assert_called_once_with("emulator", "inert-netns", avd=True)
                    args, kwargs = run.call_args
                    self.assertEqual(args[0], "avdmanager-preflight")
                    self.assertEqual(args[2], 40)
                    self.assertEqual(args[1][-1], "--inside-avd-preflight")
                    self.assertIn("--unshare-net", args[1])
                    self.assertEqual(kwargs["memory"], 3*M.GIB)
                    self.assertEqual(kwargs["env"]["ANDROID_AVD_HOME"], "/state/avd")

    def test_successful_child_return_at_deadline_does_not_publish_creation_success(self):
        children, clock = [], [0]
        base_spawn = EmulatorDiagnostics.inert_popen(self, "import sys;sys.stdin.read()", children)
        def spawn(argv, **kwargs):
            child = base_spawn(argv, **kwargs)
            wait = child.wait
            def finish(*args, **kwargs):
                result = wait(*args, **kwargs)
                clock[0] = 30
                return result
            child.wait = finish
            return child
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory)
            EmulatorDiagnostics.guarded_inside(self, proof, spawn)
            with patch.object(M, "avd_observations", return_value=self.observation()), \
                    patch.object(M.time, "monotonic", side_effect=lambda: clock[0]), \
                    self.assertRaisesRegex(ValueError, "EMULATOR_DEADLINE"):
                M.inside(avd_only=True)
            self.assertEqual(children[0].returncode, 0)
            self.assertFalse(json.loads((proof / "emulator-preflight-cleanup.json").read_text())["avd_creation_returned"])

    def test_fixed_helper_observations_never_export_resolution_paths_or_execute_them(self):
        with patch.object(M, "avd_input_identity", return_value={"fixed_test_identity": True}), \
                patch.object(M.os, "statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                patch.object(M.shutil, "which", side_effect=lambda name: None if name == "awk" else "/private/" + name), \
                patch.object(M.subprocess, "Popen") as spawn:
            observed = M.avd_observations()
        self.assertFalse(observed["posix_helpers"]["awk"])
        self.assertNotIn("/private", json.dumps(observed))
        self.assertLess(len(json.dumps(observed)), 4096)
        spawn.assert_not_called()

    def test_identity_reads_only_exact_runner_owned_inputs_not_unmapped_distro_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = dict(android_provenance="provenance.json", launcher="sdk/cmdline-tools/19.0/bin/avdmanager",
                classpath="sdk/cmdline-tools/19.0/lib/avdmanager-classpath.jar",
                command_line_properties="sdk/cmdline-tools/19.0/source.properties",
                image_properties="sdk/system-images/android-36/default/x86_64/source.properties")
            for name in names.values():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                M.H.write(path, b"inert")
            # Root-owned distro tools need their existing ownership check
            # outside the user namespace, not its unmapped overflow UID.
            with patch.object(M, "apt_java_digest", side_effect=AssertionError("outside only")):
                value = M.avd_input_identity(root)
            self.assertEqual(value, dict({key: M.H.digest(root / name) for key, name in names.items()}, image_package_xml=None))
            package = root / "sdk/system-images/android-36/default/x86_64/package.xml"
            M.H.write(package, b"inert metadata")
            self.assertEqual(M.avd_input_identity(root)["image_package_xml"], M.H.digest(package))
            launcher = root / names["launcher"]; launcher.unlink(); launcher.symlink_to(root / "provenance.json")
            with self.assertRaises(OSError): M.avd_input_identity(root)


if __name__ == "__main__":
    unittest.main()
