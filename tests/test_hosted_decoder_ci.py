#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline policy/lifecycle tests. Never apply policy or launch a native build."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT/"scripts/prepare_hosted_decoder_ci.py"))
G = H["execute"].__globals__
D = runpy.run_path(str(ROOT/"scripts/prepare_hosted_decoder.py"))


def probe():
    return dict(schema=1, kind="hosted-decoder-sandbox-preflight", unprivileged=True,
        capabilities_zero=True, no_new_privileges=True, capability_denied_child_profile=True,
        separate_network_namespace=True, loopback_only=True, host_private_paths_absent=True,
        toolchain_read_only=True, build_writable=True, only_build_host_writable=True)


class HostedDecoderCI(unittest.TestCase):
    def setUp(self):
        self.state = patch.dict(G, DRAIN_CONFIRMED=True)
        self.state.start()
        self.addCleanup(self.state.stop)

    def test_policy_and_unchanged_original_license_are_pinned(self):
        provenance = json.loads((ROOT/"third_party/apparmor-ci/provenance.json").read_bytes())
        profile = (ROOT/"scripts/hosted-decoder-bwrap.apparmor").read_bytes()
        license_data = (ROOT/"third_party/apparmor-ci/LICENSE").read_bytes()
        self.assertEqual(hashlib.sha256(profile).hexdigest(), H["PROFILE_SHA"])
        self.assertEqual(hashlib.sha256(license_data).hexdigest(), H["LICENSE_SHA"])
        self.assertEqual(provenance["local_profile_sha256"], H["PROFILE_SHA"])
        self.assertEqual(provenance["license_sha256"], H["LICENSE_SHA"])
        self.assertEqual(provenance["commit"], "b0eb95457bc2de401920308869d016e696c73664")
        text = profile.decode()
        self.assertIn("profile volparossa_ci_weather_bwrap /usr/bin/bwrap", text)
        self.assertIn("allow px /** -> volparossa_ci_weather_bwrap//&volparossa_ci_weather_child", text)
        child = text.split("profile volparossa_ci_weather_child", 1)[1]
        self.assertIn("audit deny capability,", child)
        self.assertNotIn("allow capability,", child)
        self.assertNotIn("include if exists", text)

    def test_development_root_selfhosted_and_other_workflows_rejected_before_commands(self):
        valid = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
            GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW="Prepare hosted Weather inputs",
            GITHUB_WORKSPACE=str(ROOT), GITHUB_SHA="a"*40)
        for key in ("GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_ENVIRONMENT", "GITHUB_REPOSITORY", "GITHUB_WORKFLOW"):
            env = dict(valid, **{key: "wrong"})
            with self.subTest(key=key), patch.dict(G, process=Mock(side_effect=AssertionError("must not execute"))), \
                    self.assertRaisesRegex(ValueError, "DISPOSABLE_CI"):
                H["guards"](env)
        with patch.object(os, "geteuid", return_value=0), self.assertRaisesRegex(ValueError, "ORDINARY_RUNNER"):
            H["guards"](valid)

    def test_guard_binds_actual_git_commit(self):
        env = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
            GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW="Prepare hosted Weather inputs",
            GITHUB_WORKSPACE=str(ROOT), GITHUB_SHA="a"*40)
        with patch.dict(G, process=lambda *args: (0, b"b"*40+b"\n")), self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            H["guards"](env)

    def test_preflight_reuses_exact_decoder_sandbox_and_binds_current_netns(self):
        seen = []
        def fake_process(argv, seconds):
            seen.append((argv, seconds))
            return 0, json.dumps(probe()).encode()
        with patch.dict(G, process=fake_process):
            value = H["preflight"](D, Path("/private/output"))
        self.assertEqual(value, probe())
        argv, seconds = seen[0]
        expected = D["sandbox"](Path("/private/output"), {"bwrap": {"path": "/usr/bin/bwrap"}},
            ["/usr/bin/python3", "-I", "-c", H["PROBE"], str(os.getuid()), os.readlink("/proc/self/ns/net")])
        self.assertEqual(argv, expected)
        self.assertEqual(seconds, 20)
        self.assertIn("--unshare-net", argv)
        self.assertEqual(argv.count("--bind"), 1)

    def test_closed_preflight_requires_every_real_isolation_check(self):
        H["validate_probe"](probe())
        for key in set(probe()) - {"schema", "kind"}:
            with self.subTest(key=key), self.assertRaises(ValueError):
                H["validate_probe"](dict(probe(), **{key: False}))
        for changed in (dict(probe(), schema=True), dict(probe(), invented=True)):
            with self.assertRaises(ValueError): H["validate_probe"](changed)

    def test_root_policy_hash_read_is_fixed_sudo_operation_not_unprivileged_read(self):
        info = Mock(st_mode=0o100600, st_uid=0, st_nlink=1, st_dev=1, st_ino=2, st_mtime_ns=3, st_ctime_ns=4)
        command = Mock(return_value=(0, (H["PROFILE_SHA"]+"  "+str(H["STAGED"])+"\n").encode()))
        with patch.object(Path, "lstat", return_value=info), patch.dict(G, process=command):
            H["staged_owned"]({"read_file": Mock(side_effect=AssertionError("root0600 not readable"))})
        command.assert_called_once_with(["/usr/bin/sudo", "-n", "/usr/bin/sha256sum", "--", str(H["STAGED"])], 10)

    def test_cleanup_never_removes_changed_or_preexisting_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory)/"policy"
            staged.write_bytes(b"not our policy")
            restriction = Path(directory)/"restriction"
            restriction.write_text("1\n")
            command = Mock(side_effect=AssertionError("must not mutate"))
            with patch.dict(G, STAGED=staged, RESTRICTION=restriction, process=command,
                            staged_owned=Mock(side_effect=ValueError("changed"))):
                receipt = H["cleanup"]({}, True, True)
            self.assertFalse(receipt["complete"])
            self.assertTrue(staged.exists())
            command.assert_not_called()

    def test_cleanup_removes_only_exact_owned_profile_and_never_writes_sysctl(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory)/"policy"
            staged.write_bytes(b"own")
            restriction = Path(directory)/"restriction"
            restriction.write_text("1\n")
            calls = []
            def fake_process(argv, seconds):
                calls.append(argv)
                if "/usr/bin/rm" in argv: staged.unlink()
                return 0, b""
            with patch.dict(G, STAGED=staged, RESTRICTION=restriction, process=fake_process,
                            staged_owned=lambda helper: None, inventory=lambda: ["unrelated-profile"]):
                receipt = H["cleanup"]({}, True, True)
            self.assertTrue(receipt["complete"])
            self.assertEqual(calls, [["/usr/bin/sudo", "-n", H["PARSER"], "--remove", "--skip-cache", str(staged)],
                                    ["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", str(staged)]])
            self.assertEqual(restriction.read_text(), "1\n")

    def test_add_failure_attempts_cleanup_and_records_failure_not_build_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = []
            receipt = dict(schema=1, complete=True)
            def fake_process(argv, seconds):
                calls.append(argv)
                if "--add" in argv: raise ValueError("policy failed")
                return 0, b""
            cleaning = Mock(return_value=receipt)
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
            with patch.dict(G, prechecks=lambda helper: {}, process=fake_process, staged_owned=lambda helper: None,
                            cleanup=cleaning, audit=lambda *args: None), self.assertRaisesRegex(ValueError, "policy failed"):
                H["execute"]({}, output)
            cleaning.assert_called_once_with({}, True, True)
            result = json.loads((output/"result.json").read_bytes())
            self.assertEqual(result["stage"], "policy-install")
            self.assertFalse(result["build_returned_successfully"])
            self.assertFalse(result["decoder_authorized"])
            self.assertEqual({sig: signal.getsignal(sig) for sig in handlers}, handlers)

    def test_install_interruption_marks_ownership_attempt_before_command(self):
        with tempfile.TemporaryDirectory() as directory:
            cleaning = Mock(return_value=dict(schema=1, complete=True))
            with patch.dict(G, prechecks=lambda helper: {}, process=Mock(side_effect=InterruptedError()),
                            cleanup=cleaning, audit=lambda *args: None), self.assertRaises(InterruptedError):
                H["execute"]({}, Path(directory))
            cleaning.assert_called_once_with({}, False, True)

    def test_audit_filters_only_timebounded_matching_sandbox_denials(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = b'private unrelated line\napparmor="DENIED" comm="bwrap" capability=12\napparmor="DENIED" comm="other"\n'
            command = Mock(return_value=(0, raw))
            with patch.dict(G, process=command): H["audit"](Path(directory), 12345)
            value = json.loads((Path(directory)/"audit.json").read_bytes())
            self.assertEqual(value["matching_denials"], ['apparmor="DENIED" comm="bwrap" capability=12'])
            self.assertIn("@12345", command.call_args.args[0])
            self.assertEqual(command.call_args.args[1], 10)

    def test_no_freeform_cli_command_is_accepted(self):
        with patch.object(sys, "argv", ["wrapper", "arbitrary-command"]), \
                patch.dict(G, guards=Mock(side_effect=AssertionError("must not reach guards"))), \
                self.assertRaisesRegex(ValueError, "NO_COMMAND_ARGUMENTS"):
            H["main"]()

    def test_mount_preflight_allows_only_exact_bwrap_character_devices(self):
        namespace = {"os": os}
        exec(H["MOUNT_CHECK"], namespace)
        devices = {"/dev/null": (1,3), "/dev/zero": (1,5), "/dev/full": (1,7),
                   "/dev/random": (1,8), "/dev/urandom": (1,9), "/dev/tty": (5,0)}
        lines = [f"1 0 0:1 / {path} rw - devtmpfs devtmpfs rw" for path in devices]
        lines += ["2 0 8:1 / /usr ro - ext4 disk rw", "3 0 8:1 / /build rw - ext4 disk rw",
                  "4 0 0:2 / /tmp rw - tmpfs tmpfs rw", "5 0 0:2 / / rw - tmpfs tmpfs rw"]
        lookup = lambda path: Mock(st_mode=stat.S_IFCHR, st_rdev=os.makedev(*devices[path]))
        namespace["validate_mounts"]("\n".join(lines), lookup)
        for extra in ("6 0 0:1 / /dev/sda rw - devtmpfs devtmpfs rw", "6 0 8:1 / /host rw - ext4 disk rw"):
            with self.assertRaises(AssertionError): namespace["validate_mounts"]("\n".join(lines+[extra]), lookup)
        with self.assertRaises(AssertionError):
            namespace["validate_mounts"]("\n".join(lines), lambda path: Mock(st_mode=stat.S_IFREG, st_rdev=0))

    def test_cleanup_failure_and_unconfirmed_drain_retain_policy(self):
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as directory:
                staged = Path(directory)/"owned"
                staged.write_text("policy")
                restriction = Path(directory)/"restriction"
                restriction.write_text("1\n")
                command = Mock(side_effect=ValueError("remove failed"))
                with patch.dict(G, STAGED=staged, RESTRICTION=restriction, DRAIN_CONFIRMED=not uncertain,
                        staged_owned=lambda helper: None, process=command):
                    value = H["cleanup"]({}, True, True)
                self.assertFalse(value["complete"])
                self.assertTrue(staged.exists())
                if uncertain: command.assert_not_called()
                else: self.assertEqual(command.call_args.args[0][3], "--remove")

    def test_fixed_decoder_cleanup_exit125_never_allows_policy_removal(self):
        # Only inert Python is run. Match the decoder argv classifier through a
        # temporary function-global path; no recipe or privileged command runs.
        with patch.dict(G, DECODER=Path("-c")):
            with self.assertRaises(H["CommandFailure"]) as error:
                H["process"](["/usr/bin/python3", "-B", "-c", "raise SystemExit(125)"], 2)
            self.assertFalse(G["DRAIN_CONFIRMED"])
        self.assertEqual(error.exception.code, 125)
        command = Mock(side_effect=AssertionError("must not remove"))
        with tempfile.TemporaryDirectory() as directory:
            restriction = Path(directory)/"restriction"
            restriction.write_text("1")
            with patch.dict(G, RESTRICTION=restriction, process=command, DRAIN_CONFIRMED=False):
                self.assertFalse(H["cleanup"]({}, True, True)["complete"])
        command.assert_not_called()

    def test_timeout_terms_owned_child_and_forced_kill_is_not_confirmed_drain(self):
        # The deterministic forced-kill branch is mocked; no stubborn process
        # or real SIGKILL is needed to test this safety decision.
        child = Mock(pid=123, returncode=-9)
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("inert", 5), -9]
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.get_map.return_value = {1: "fake"}
        with patch.object(subprocess, "Popen", return_value=child), patch.object(H["selectors"], "DefaultSelector", return_value=selector), \
                patch.object(H["time"], "monotonic", side_effect=[0, 2]), patch.object(os, "killpg") as kill:
            with self.assertRaises(H["CommandFailure"]) as error: H["process"](["inert"], 1)
        self.assertEqual(error.exception.category, "deadline")
        self.assertEqual(kill.call_args_list[0].args, (123, signal.SIGTERM))
        self.assertEqual(kill.call_args_list[1].args, (123, signal.SIGKILL))
        self.assertFalse(G["DRAIN_CONFIRMED"])
        self.assertTrue(child.stdout.close.called)

    def test_normal_success_uses_fixed_unprivileged_recipe_commands_then_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root/"build/hosted-sandbox-ci"
            output.mkdir(parents=True)
            calls = []
            def fake_process(argv, seconds):
                calls.append(argv)
                if "capture-toolchain" in argv:
                    manifest = root/"build/hosted-toolchain-ci/toolchain.json"
                    manifest.parent.mkdir()
                    manifest.write_bytes(b"verified toolchain")
                    return 0, json.dumps(dict(toolchain_manifest=str(manifest), decoder_authorized=False,
                        provenance_only=True, toolchain_manifest_sha256=H["digest"](manifest.read_bytes()))).encode()
                return 0, b""
            cleaning = Mock(return_value=dict(schema=1, complete=True))
            helper = {"unique": D["unique"], "read_file": lambda path: path.read_bytes()}
            with patch.dict(G, ROOT=root, process=fake_process, prechecks=lambda helper: {}, staged_owned=lambda helper: None,
                    preflight=lambda *args: probe(), cleanup=cleaning, audit=lambda *args: None):
                H["execute"](helper, output)
            self.assertTrue(json.loads((output/"result.json").read_bytes())["build_returned_successfully"])
            for argv in calls:
                if "capture-toolchain" in argv or "build" in argv:
                    self.assertEqual(argv[:3], ["/usr/bin/python3", "-B", str(H["DECODER"])])
                    self.assertNotIn("/usr/bin/sudo", argv)
            cleaning.assert_called_once_with(helper, True, True)

    def test_original_failure_is_closed_diagnostic_not_raw_stream(self):
        error = H["CommandFailure"]("exit-status", 1, b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n")
        self.assertEqual(error.setup_code, "bwrap-loopback-address-denied")
        self.assertEqual(error.code, 1)
        self.assertEqual(error.output_bytes, 61)
        self.assertFalse(hasattr(error, "raw"))

    def test_timeout_cleanup125_during_grace_keeps_drain_unconfirmed(self):
        child = Mock(pid=123, returncode=125)
        child.poll.return_value = None
        child.wait.return_value = 125
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.get_map.return_value = {1: "fake"}
        with patch.object(subprocess, "Popen", return_value=child), patch.object(H["selectors"], "DefaultSelector", return_value=selector), \
                patch.object(H["time"], "monotonic", side_effect=[0, 2]), patch.object(os, "killpg") as kill:
            with self.assertRaises(H["CommandFailure"]):
                H["process"](["/usr/bin/python3", "-B", str(H["DECODER"]), "build"], 1)
        self.assertFalse(G["DRAIN_CONFIRMED"])
        kill.assert_called_once_with(123, signal.SIGTERM)

    def test_real_wrapper_signal_interrupts_select_and_drains_child_before_cleanup(self):
        code = r'''
import os, runpy, signal, subprocess, sys, threading
from pathlib import Path
h = runpy.run_path(sys.argv[1])
g = h['execute'].__globals__
real_process = h['process']
real_popen = subprocess.Popen
children = []
def popen(*args, **kwargs):
    child = real_popen(*args, **kwargs)
    children.append(child)
    return child
g['subprocess'].Popen = popen
g['prechecks'] = lambda helper: {}
g['staged_owned'] = lambda helper: None
g['process'] = lambda *args, **kwargs: (0, b'')
g['audit'] = lambda *args: None
def probe(*args):
    timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        return real_process([sys.executable, '-c', 'import time; time.sleep(10)'], 5)
    finally:
        timer.cancel()
        timer.join()
g['preflight'] = probe
def cleanup(*args):
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdout.closed
    return dict(schema=1, complete=True)
g['cleanup'] = cleanup
before = signal.getsignal(signal.SIGTERM)
try:
    h['execute']({}, Path(sys.argv[2]))
except h['CIInterrupted']:
    pass
else:
    raise AssertionError('signal swallowed')
assert signal.getsignal(signal.SIGTERM) == before
print('wrapper-child-drained')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT/"scripts/prepare_hosted_decoder_ci.py"), directory],
                                    capture_output=True, timeout=5)
            failure = json.loads((Path(directory)/"failure.json").read_bytes())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith(b"wrapper-child-drained\n"))
        self.assertEqual(failure["category"], "interrupted")


if __name__ == "__main__":
    unittest.main()
