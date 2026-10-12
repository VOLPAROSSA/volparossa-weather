# SPDX-License-Identifier: GPL-3.0-only
"""Inert contract checks; never execute Flutter, Node, bwrap or Firefox."""
import copy
import hashlib
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
W = runpy.run_path(str(ROOT / "scripts/prepare_hosted_overmorrow_ci.py"))
G = W["main"].__globals__
H = W["H"]


def report(table=False):
    value = dict(schema=1, passed=True, phase="complete",
        cleanup={name: True for name in ("browser_exited", "fixture_exited", "private_profile_removed",
                                         "normal_browser_stop", "normal_fixture_stop")},
        scope=dict(actual_overmorrow_ui=True, actual_http_bridge=True, synthetic_weather=True,
            synthetic_air_quality=True, core_executed=False, overlay_proven=False,
            upstream_origin_proven=False, native_mobile_proven=False), checks={})
    if table:
        value["kind"] = "overmorrow-synthetic-native-table-contract"
        value["scope"].update(ordered_table_contract=True, joined_delivery_proven=False,
            cold_transfer_proven=False, origin_acquisition_proven=False)
        value["checks"] = dict(weather_requests=2, air_quality_requests=2,
            exact_current_v3_extractor=True, exact_current_v3_observed_products=True,
            actual_pointer_refresh=True, ordered_four_weather_five_air_quality_rows=True)
        value["table_phases"] = [dict(row_counts=dict(weather=4, air_quality=5),
            exact_ordered_rows_and_metadata=True, browser_requests_each=i, provider_requests_each=i) for i in (1, 2)]
    else:
        value["checks"] = {name: True for name in ("actual_refresh", "weather_failure_and_stale_preserve_air_quality",
            "air_quality_failure_and_stale_preserve_weather", "weather_idle_expiry_without_request",
            "air_quality_idle_expiry_without_request", "existing_aq_detail_without_new_request")}
        value["checks"].update(provider_requests=10, air_quality_provider_requests=10)
    return value


class HostedOvermorrow(unittest.TestCase):
    def test_explicit_workflow_guard_rejects_development_or_other_workflow(self):
        env = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
            GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW=W["WORKFLOW"],
            GITHUB_WORKSPACE=str(ROOT), GITHUB_SHA="a" * 40)
        for key in ("GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_ENVIRONMENT", "GITHUB_REPOSITORY", "GITHUB_WORKFLOW"):
            with self.subTest(key=key), patch.object(os, "geteuid", return_value=1000), \
                    patch.object(os, "getuid", return_value=1000), \
                    patch.object(H, "policy_helper", side_effect=AssertionError("not reached")), \
                    self.assertRaisesRegex(ValueError, "EXPLICIT_DISPOSABLE_CI"):
                W["guards"](dict(env, **{key: "wrong"}))

    def test_no_arbitrary_command_cli(self):
        with patch.object(sys, "argv", ["helper", "--run", "anything"]), \
                patch.dict(G, guards=Mock(side_effect=AssertionError("not reached"))), \
                self.assertRaisesRegex(ValueError, "NO_ARGUMENTS_ALLOWED"):
            W["main"]()

    def test_fixed_new_direct_children_and_private_helper(self):
        for key in ("OUTPUT", "STAGE", "DEPLOY", "PROOF", "TABLE_PROOF", "SDK"):
            self.assertEqual(W[key].parent, ROOT / "build")
        self.assertNotEqual(W["PROOF"], W["TABLE_PROOF"])
        old = runpy.run_path(str(ROOT / "scripts/prepare_hosted_clients_ci.py"))
        self.assertEqual(old["STAGE"].name, "drizzli-hosted-ci")
        self.assertEqual(old["PROOF"].name, "drizzli-hosted-browser-ci")
        self.assertNotEqual(H.OUTPUT, old["OUTPUT"])
        self.assertEqual(H.PROFILE_SHA, old["PROFILE_SHA"])

    def test_environment_has_no_host_credentials_or_sdk_options(self):
        with patch.dict(os.environ, HOME="/private", GH_TOKEN="secret", HTTPS_PROXY="http://proxy",
                        DART_VM_OPTIONS="--evil", PUB_HOSTED_URL="https://evil", PUB_CACHE="/private/cache"):
            env = W["environment"]()
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("DART_VM_OPTIONS", env)
        self.assertEqual(env["HOME"], "/home/runner")
        self.assertEqual(env["PUB_CACHE"], "/state/pub-cache")
        self.assertEqual(env["PUB_HOSTED_URL"], "https://pub.dev")
        self.assertEqual(env["PATH"], f'{W["SDK"]}/bin:/tools:/usr/bin:/bin')
        self.assertEqual(env["FLUTTER_SUPPRESS_ANALYTICS"], "true")
        self.assertEqual(env["DART_SUPPRESS_ANALYTICS"], "true")
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")

    def test_only_acquisition_can_use_external_network(self):
        for mode in ("acquire", "compile", "browser"):
            proof = W["PROOF"] if mode == "browser" else None
            argv = W["sandbox"](["/usr/bin/true"], mode=mode, proof=proof)
            self.assertEqual("--unshare-net" in argv, mode != "acquire")
            self.assertEqual("/etc/resolv.conf" in argv, mode == "acquire")
            self.assertEqual("/etc/ssl/certs" in argv, mode == "acquire")
            sources = [argv[i+1] for i, arg in enumerate(argv) if arg in ("--bind", "--ro-bind")]
            self.assertNotIn("/", sources)
            self.assertNotIn("/home/runner", sources)
            self.assertNotIn(str(Path.home()), sources)
            self.assertIn("--unshare-user", argv)
            self.assertIn("--unshare-pid", argv)
            self.assertIn("--die-with-parent", argv)

    def test_compile_has_only_exact_declared_writable_host_mounts(self):
        argv = W["sandbox"](["/usr/bin/true"], mode="compile")
        writes = [argv[i+1:i+3] for i, arg in enumerate(argv) if arg == "--bind"]
        self.assertEqual(writes, [[str(W["PRIVATE"]), "/state"], [str(W["STAGE"]), str(W["STAGE"])],
            [str(W["SDK"] / "bin/cache"), str(W["SDK"] / "bin/cache")],
            [str(W["SDK_TOOL_STATE"]), str(W["SDK_TOOL_MOUNT"])]])
        self.assertNotIn(["--remount-ro", "/home/runner"], [argv[i:i+2] for i in range(len(argv))])
        self.assertIn(["--remount-ro", "/"], [argv[i:i+2] for i in range(len(argv))])
        self.assertLess(argv.index("/home/runner"), argv.index(str(ROOT)))
        self.assertIn("--cpu=900", argv)

    def test_tool_state_uses_private_persistent_mount_not_writable_sdk_sources(self):
        for mode in ("acquire", "compile"):
            argv = W["sandbox"](["/usr/bin/true"], mode=mode)
            writes = [argv[i+1:i+3] for i, arg in enumerate(argv) if arg == "--bind"]
            self.assertIn([str(W["SDK_TOOL_STATE"]), str(W["SDK_TOOL_MOUNT"])], writes)
            self.assertNotIn([str(W["SDK"]), str(W["SDK"])], writes)
            self.assertFalse(any("pubspec.lock" in item for item in argv))
        self.assertIn("os.statvfs(tool_state.parent/'pubspec.lock').f_flag & os.ST_RDONLY", W["PROBE"])
        self.assertIn("os.stat(tool_state).st_ino==os.stat('/state/flutter-tool-state').st_ino", W["PROBE"])

    def tool_fixture(self, temporary):
        root = Path(temporary)
        parent, state = root / "sdk/packages/flutter_tools", root / "private/flutter-tool-state"
        parent.mkdir(parents=True, mode=0o700)
        state.parent.mkdir(mode=0o700)
        return parent / ".dart_tool", state

    def test_tool_state_is_fresh_and_receipt_contains_only_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            mount, state = self.tool_fixture(temporary)
            with patch.dict(G, SDK_TOOL_MOUNT=mount, SDK_TOOL_STATE=state):
                W["prepare_tool_state"]()
                metadata = b'{"rootUri":"private-cache-path"}'
                H.write(state / "package_config.json", metadata)
                receipt = W["tool_state_binding"]()
                self.assertEqual(receipt["files"], {"package_config.json": dict(bytes=len(metadata),
                    sha256=hashlib.sha256(metadata).hexdigest())})
                self.assertNotIn("private-cache-path", str(receipt))
                self.assertTrue(receipt["stored_outside_sdk"])
                self.assertEqual(list(mount.iterdir()), [])
                with self.assertRaises(FileExistsError):
                    W["prepare_tool_state"]()

    def test_tool_state_rejects_links_executables_and_nonempty_original_mount(self):
        for change in ("link", "executable", "original", "hardlink"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                mount, state = self.tool_fixture(temporary)
                with patch.dict(G, SDK_TOOL_MOUNT=mount, SDK_TOOL_STATE=state):
                    W["prepare_tool_state"]()
                    item = state / "package_config.json"
                    if change == "link":
                        item.symlink_to(mount)
                    else:
                        H.write(item, b"{}")
                        if change == "executable":
                            item.chmod(0o700)
                        elif change == "hardlink":
                            os.link(item, state / "other.json")
                        else:
                            H.write(mount / "unexpected", b"{}")
                    with self.assertRaisesRegex(ValueError, "SDK_TOOL_(STATE_TYPE|MOUNT_NOT_EMPTY)"):
                        W["tool_state_binding"]()

    def test_tool_state_bounds_empty_directories_as_well_as_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            mount, state = self.tool_fixture(temporary)
            with patch.dict(G, SDK_TOOL_MOUNT=mount, SDK_TOOL_STATE=state):
                W["prepare_tool_state"]()
                for index in range(65):
                    (state / f"dir-{index}").mkdir(mode=0o700)
                with self.assertRaisesRegex(ValueError, "SDK_TOOL_STATE_BOUND"):
                    W["tool_state_binding"]()

    def test_browser_sources_read_only_and_fresh_scratch_each_time(self):
        for proof in (W["PROOF"], W["TABLE_PROOF"]):
            argv = W["sandbox"](["/usr/bin/true"], mode="browser", proof=proof)
            writes = [argv[i+1:i+3] for i, arg in enumerate(argv) if arg == "--bind"]
            self.assertEqual(writes, [[str(proof), str(proof)], [str(proof / "appdata"), "/home/runner/.mozilla"]])
            self.assertIn(["--remount-ro", "/home/runner"], [argv[i:i+2] for i in range(len(argv))])
            self.assertIn(["--ro-bind", "/etc/fonts", "/etc/fonts"], [argv[i:i+3] for i in range(len(argv))])
            self.assertNotIn("/state", argv)
            self.assertNotIn("/tools/which", argv)
        with self.assertRaisesRegex(ValueError, "BROWSER_OUTPUT_REQUIRED"):
            W["sandbox"]([], mode="browser", proof=Path("/arbitrary"))

    def test_build_which_alias_is_exact_readonly_and_never_mounts_alternatives(self):
        for mode in ("acquire", "compile"):
            argv = W["sandbox"](["/usr/bin/true"], mode=mode)
            self.assertIn(["--symlink", "/usr/bin/which.debianutils", "/tools/which"],
                [argv[i:i+3] for i in range(len(argv))])
            self.assertLess(argv.index("/tools/which"), argv.index("--remount-ro"))
            self.assertNotIn("/etc/alternatives", argv)
        self.assertIn("os.statvfs('/tools').f_flag & os.ST_RDONLY", W["PROBE"])

    def test_system_which_record_rejects_changed_origin_ownership_or_permissions(self):
        raw = b"#!/bin/sh\n# inert test script\n"
        good = dict(st_mode=stat.S_IFREG | 0o755, st_uid=0, st_nlink=1)
        with patch.object(Path, "resolve", return_value=W["WHICH"]), \
                patch.object(Path, "lstat", return_value=SimpleNamespace(**good)), \
                patch.object(H, "read", return_value=raw) as read:
            value = W["system_tools"]()
        read.assert_called_once_with(W["WHICH"], 32768)
        self.assertEqual(value["which"], dict(path="/usr/bin/which.debianutils", bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), sandbox_alias="/tools/which"))
        for change in (dict(st_uid=1000), dict(st_nlink=2), dict(st_mode=stat.S_IFREG | 0o777),
                       dict(st_mode=stat.S_IFREG | 0o644), dict(st_mode=stat.S_IFLNK | 0o755)):
            with patch.object(Path, "resolve", return_value=W["WHICH"]), \
                    patch.object(Path, "lstat", return_value=SimpleNamespace(**(good | change))), \
                    patch.object(H, "read") as read, self.assertRaisesRegex(ValueError, "UNSAFE_WHICH"):
                W["system_tools"]()
            read.assert_not_called()
        with patch.object(Path, "resolve", return_value=Path("/unreviewed/which")), \
                self.assertRaisesRegex(ValueError, "CANONICAL_WHICH_REQUIRED"):
            W["system_tools"]()

    def test_flutter_actions_are_exact_existing_contract_not_arbitrary_shell(self):
        actions = W["build_contract"]()["ACTIONS"]
        for action in ("dependencies", "dependencies-offline", "test", "build"):
            with patch.object(os, "sched_getaffinity", return_value={3, 7, 9}):
                argv = W["flutter_command"](action)
            self.assertEqual(argv[:6], ["/usr/bin/nice", "-n", "10", "/usr/bin/taskset", "-c", "3,7"])
            self.assertEqual(argv[6:], [str(W["SDK"] / "bin/flutter"), "--no-version-check", "--suppress-analytics", *actions[action]])
        self.assertIn("--enforce-lockfile", actions["dependencies"])
        self.assertIn("--offline", actions["dependencies-offline"])
        self.assertIn("--no-pub", actions["test"])
        self.assertIn("--concurrency=2", actions["test"])
        self.assertIn("--no-pub", actions["build"])
        self.assertIn("--no-wasm-dry-run", actions["build"])
        with self.assertRaisesRegex(ValueError, "FLUTTER_ACTION"):
            W["flutter_command"]("arbitrary")

    def test_fixed_browser_drivers_retain_inside_and_distinct_outputs(self):
        for proof, driver in ((W["PROOF"], "smoke_browser.py"), (W["TABLE_PROOF"], "smoke_table_browser.py")):
            argv = W["browser_command"](proof, "net:[123]")
            self.assertEqual(argv[:3], ["/usr/bin/python3", "-B", str(W["HERE"] / driver)])
            self.assertEqual(argv[argv.index("--output")+1], str(proof))
            self.assertEqual(argv[argv.index("--static-root")+1], str(W["DEPLOY"]))
            self.assertEqual(argv[argv.index("--node")+1], str(H.NODE))
            self.assertEqual(argv[-3:], ["--inside", "--host-netns", "net:[123]"])

    def test_full_browser_requires_all_real_checks_and_ten_requests(self):
        value = report()
        W["verify_browser_report"](value)
        for key in value["checks"]:
            changed = copy.deepcopy(value)
            changed["checks"][key] = False if type(changed["checks"][key]) is bool else 9
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "FULL_UI_PROOF_FAILED"):
                W["verify_browser_report"](changed)

    def test_table_requires_two_distinct_exact_native_tables(self):
        value = report(True)
        W["verify_browser_report"](value, True)
        for field, replacement in (("row_counts", dict(weather=4, air_quality=4)),
                                  ("exact_ordered_rows_and_metadata", False), ("provider_requests_each", 1)):
            changed = copy.deepcopy(value)
            changed["table_phases"][1][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "TABLE_ROWS_OR_REFRESH_CHANGED"):
                W["verify_browser_report"](changed, True)

    def test_synthetic_proof_never_becomes_mobile_or_core_proof(self):
        for table in (False, True):
            for field in ("core_executed", "overlay_proven", "upstream_origin_proven", "native_mobile_proven"):
                value = report(table)
                value["scope"][field] = True
                with self.subTest(table=table, field=field), self.assertRaisesRegex(ValueError, "BROWSER_SCOPE_CHANGED"):
                    W["verify_browser_report"](value, table)

    def test_incomplete_browser_cleanup_never_passes(self):
        for field in report()["cleanup"]:
            value = report()
            value["cleanup"][field] = False
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "BROWSER_PROOF_FAILED"):
                W["verify_browser_report"](value)
        value = report()
        value["cleanup"] = {}
        with self.assertRaisesRegex(ValueError, "BROWSER_PROOF_FAILED"):
            W["verify_browser_report"](value)

    def test_profile_and_table_capture_residue_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary)
            self.assertTrue(W["proof_removed"](proof))
            (proof / "tmp").mkdir()
            (proof / "tmp/served-weather.json").write_text("{}")
            self.assertFalse(W["proof_removed"](proof))

    def test_preflight_script_is_inertly_parseable_and_checks_sdk_boundary(self):
        compile(W["PROBE"], "overmorrow-preflight", "exec")
        self.assertIn("sdk_source_read_only=True", W["PROBE"])
        self.assertIn("sdk_cache_writable=not browser", W["PROBE"])
        self.assertIn("NoNewPrivs", W["PROBE"])
        self.assertIn(".st_ino==", W["PROBE"])
        self.assertEqual(W["FLUTTER_MEMORY"], 3 * 1024**3)

    def test_phase_checks_keep_git_immutable_and_rebind_all_sdk_bytes(self):
        helper = Mock()
        pin = dict(pubspec_lock_sha256="a" * 64, flutter_commit="b" * 40)
        helper.process.side_effect = [(0, ("b" * 40).encode()), (0, b""), (0, b"")]
        verify = Mock(return_value={"inventory": "full"})
        with patch.object(H, "read", return_value=b"lock"), patch.object(H, "sha", return_value="a" * 64), \
                patch.object(H, "digest", return_value=dict(sha256="c" * 64)), \
                patch.dict(G, build_contract=lambda: {"SDK_FILES": {"bin/cache/dart-sdk/bin/dart": "c" * 64}},
                           sdk_inventory=verify):
            self.assertEqual(W["verify_phase_inputs"](helper, pin), {"inventory": "full"})
        verify.assert_called_once_with(allow_build_state=True)
        for call in helper.process.call_args_list:
            self.assertIn("--no-optional-locks", call.args[0])
        self.assertIn("diff.autoRefreshIndex=false", helper.process.call_args_list[1].args[0])

    def test_real_git_inspection_preserves_archive_index_and_rejects_source_edits(self):
        # Tiny text-only Git fixture, not an SDK/build/browser execution. Archive
        # extraction gives files old mtimes/new inodes: porcelain diff must not
        # rewrite the preserved index while checking otherwise clean contents.
        with tempfile.TemporaryDirectory(prefix="overmorrow-git-inspection-") as temporary:
            repository = Path(temporary) / "sdk"
            env = dict(H.BASE_ENV, HOME=temporary, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
            def git(*args):
                # The fixture owns the whole .git snapshot. Git 2.55 may detach
                # automatic maintenance after commit and remove a transient
                # lock during the mtime walk; keep this fixture single-writer.
                return subprocess.run(["/usr/bin/git", "-c", "maintenance.auto=false", *args], env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
            git("init", "--quiet", "--template=", "--initial-branch=main", str(repository))
            source = repository / "source.txt"
            source.write_text("original source\n")
            git("-C", str(repository), "add", "source.txt")
            git("-C", str(repository), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "fixture")
            for path in repository.rglob("*"):
                if path.is_file():
                    path.chmod(0o600)
                    os.utime(path, (1700000000, 1700000000))
            def snapshot():
                return {str(path.relative_to(repository)): (hashlib.sha256(path.read_bytes()).hexdigest(),
                    stat.S_IMODE(path.stat().st_mode)) for path in (repository / ".git").rglob("*") if path.is_file()}
            before = snapshot()
            with patch.dict(G, SDK=repository):
                command = W["sdk_diff_command"]()
            result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(snapshot(), before)
            source.write_text("changed source\n")
            result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertEqual(snapshot(), before)

    def test_changed_critical_sdk_file_stops_before_next_phase(self):
        helper = Mock()
        pin = dict(pubspec_lock_sha256="a" * 64, flutter_commit="b" * 40)
        helper.process.side_effect = [(0, ("b" * 40).encode()), (0, b""), (0, b"")]
        with patch.object(H, "read", return_value=b"lock"), patch.object(H, "sha", return_value="a" * 64), \
                patch.object(H, "digest", return_value=dict(sha256="d" * 64)), \
                patch.dict(G, build_contract=lambda: {"SDK_FILES": {"bin/cache/dart-sdk/bin/dart": "c" * 64}},
                           sdk_inventory=Mock(side_effect=AssertionError("not reached"))), \
                self.assertRaisesRegex(ValueError, "FLUTTER_EXECUTABLE_CHANGED"):
            W["verify_phase_inputs"](helper, pin)

    def test_full_original_sdk_inventory_is_checked_before_execution(self):
        verify = Mock(return_value={"inventory": "verified"})
        with patch.object(runpy, "run_path", return_value={"verify_materialized": verify}):
            self.assertEqual(W["sdk_inventory"](), {"inventory": "verified"})
        verify.assert_called_once_with(W["SDK"], allow_build_state=False)

    def test_failed_owned_process_keeps_policy_until_confirmed_drain(self):
        helper = Mock(DRAIN_CONFIRMED=True)
        helper.prechecks.return_value = {}
        helper.cleanup.return_value = {"complete": False}
        saved = {}
        with patch.dict(os.environ, GITHUB_SHA="a" * 40), \
                patch.object(H, "runtime_inventory", return_value={}), \
                patch.dict(G, sdk_inventory=lambda: {}, prepare_tool_state=lambda: None), \
                patch.object(H, "private_directory"), patch.object(H, "write"), \
                patch.object(H, "save", side_effect=lambda name, data: saved.update({name: data})), \
                patch.object(H, "run", side_effect=ValueError("CHILD_MEMORY_BOUND")), \
                patch.object(H, "DRAIN_CONFIRMED", False), \
                patch.object(W["signal"], "signal"), \
                self.assertRaisesRegex(ValueError, "CLEANUP_UNPROVEN"):
            W["execute"](helper, {})
        self.assertFalse(helper.DRAIN_CONFIRMED)
        self.assertEqual(helper.cleanup.call_args.args, ({}, True, True))
        self.assertEqual(saved["failure.json"]["code"], "CHILD_MEMORY_BOUND")
        self.assertFalse(saved["result.json"]["success"])
        self.assertFalse(saved["result.json"]["outer_cleanup"]["process_drain_confirmed"])
        self.assertFalse(saved["result.json"]["policy_cleanup_complete"])

    def test_missing_sdk_binding_fails_before_policy_install(self):
        helper = Mock(DRAIN_CONFIRMED=True)
        helper.prechecks.return_value = {}
        helper.cleanup.return_value = {"complete": True}
        saved = {}
        with patch.dict(os.environ, GITHUB_SHA="a" * 40), \
                patch.object(H, "runtime_inventory", return_value={}), \
                patch.dict(G, sdk_inventory=Mock(side_effect=ValueError("SDK file changed"))), \
                patch.object(H, "save", side_effect=lambda name, data: saved.update({name: data})), \
                patch.object(W["signal"], "signal"), \
                self.assertRaisesRegex(ValueError, "SDK file changed"):
            W["execute"](helper, {})
        helper.process.assert_not_called()
        self.assertEqual(helper.cleanup.call_args.args, ({}, False, False))
        self.assertFalse(saved["result.json"]["success"])


if __name__ == "__main__":
    unittest.main()
