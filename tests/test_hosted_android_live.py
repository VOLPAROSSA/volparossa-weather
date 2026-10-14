# SPDX-License-Identifier: GPL-3.0-only
"""Inert live-runtime admission tests; no SDK, emulator, policy or core launch."""
import ast
from contextlib import ExitStack
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("android_live_tests", ROOT / "scripts/prepare_hosted_android_ci.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def report():
    products = dict(weather=dict(rows=4, table_sha256="a" * 64, product_sha256="b" * 64),
        air_quality=dict(rows=5, table_sha256="c" * 64, product_sha256="d" * 64))
    fetched = dict(products, response_sha256=dict(weather="1" * 64, air_quality="2" * 64))
    return dict(schema=2, kind="overmorrow-installed-android-protected-core-trial", profile="protected-core",
        joined_core_acceptance=False, passed=True, phase="complete", package=M.PACKAGE,
        scope=dict(installed_android_app=True, mounted_widget_tables=True, real_adb_interaction=True,
            synthetic_weather=False, synthetic_air_quality=False, pixel_visibility_proven=False, core_executed=False,
            overlay_proven=False, physical_device=False, production_authority=False, expiry_proven=False),
        observations=dict(requests=dict(weather=3, air_quality=3), initial=copy.deepcopy(fetched), refresh=copy.deepcopy(fetched),
            before_background=copy.deepcopy(fetched), after_resume=copy.deepcopy(products),
            bindings={k: dict(forecast_sha256="e" * 64, immutable_product_sha256="f" * 64) for k in products}),
        checks=dict(initial_exact_native_rows=True, actual_tap_refresh=True, third_refresh_exact_native_rows=True,
            real_android_background_resume=True, original_products_fresh_after_resume=True, no_extra_product_requests=True),
        cleanup=dict(app_stopped=True, forward_removed=True, vm_closed=True))


class LiveReport(unittest.TestCase):
    def test_valid_scope_is_not_promoted_to_overlay_or_expiry_proof(self):
        value = report()
        M.validate_live_report(value)
        with self.assertRaisesRegex(ValueError, "INSTALLED_APP_PROOF"):
            M.validate_report(value)
        for field in ("core_executed", "overlay_proven", "physical_device", "production_authority", "expiry_proven",
                "synthetic_weather", "synthetic_air_quality"):
            with self.subTest(field=field):
                changed = copy.deepcopy(value)
                changed["scope"][field] = True
                with self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_APP_SCOPE"):
                    M.validate_live_report(changed)

    def test_rejects_missing_checks_cleanup_and_extra_product_requests(self):
        for field in report()["checks"]:
            value = report()
            value["checks"][field] = False
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_APP_CHECKS"):
                M.validate_live_report(value)
        for field in report()["cleanup"]:
            value = report()
            value["cleanup"][field] = False
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_APP_COMPLETION"):
                M.validate_live_report(value)
        value = report()
        value["observations"]["requests"]["weather"] = 4
        with self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_APP_COMPLETION"):
            M.validate_live_report(value)

    def test_all_four_observations_bind_both_tables_and_products(self):
        for phase in ("initial", "refresh", "before_background", "after_resume"):
            for product in ("weather", "air_quality"):
                value = report()
                value["observations"][phase][product]["table_sha256"] = "not-a-hash"
                with self.subTest(phase=phase, product=product), self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_PRODUCT_BINDING"):
                    M.validate_live_report(value)
        value = report()
        value["observations"]["bindings"]["weather"]["forecast_sha256"] = ""
        with self.assertRaisesRegex(ValueError, "LIVE_FORECAST_BINDING"):
            M.validate_live_report(value)

    def test_response_bytes_are_bound_only_in_actual_fetch_observations(self):
        for phase in ("initial", "refresh", "before_background"):
            for malformed in ({}, {"weather": "1" * 64, "air_quality": "invalid"},
                    {"weather": "1" * 64, "air_quality": "2" * 64, "extra": "3" * 64}):
                value = report()
                value["observations"][phase]["response_sha256"] = malformed
                with self.subTest(phase=phase, malformed=malformed), self.assertRaisesRegex(ValueError, "LIVE_RESPONSE_BINDING"):
                    M.validate_live_report(value)
        value = report()
        value["observations"]["after_resume"]["response_sha256"] = dict(weather="1" * 64, air_quality="2" * 64)
        with self.assertRaisesRegex(ValueError, "LIVE_INSTALLED_PRODUCT_PAIR"):
            M.validate_live_report(value)


class SocketBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vpa-")
        self.root = Path(self.temp.name)
        self.path = self.root / "api.sock"
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(self.path))
        self.path.chmod(0o600)

    def tearDown(self):
        self.sock.close()
        self.temp.cleanup()

    def test_exact_private_socket_only_parent_and_readonly_mount(self):
        identity = M.upstream_binding(self.path)
        self.assertEqual(identity["socket"]["st_ino"], self.path.stat().st_ino)
        command = ["inert"]
        argv = M.sandbox(command, "emulator", upstream_socket=self.path)
        index = argv.index(str(self.root))
        self.assertEqual(argv[index - 1:index + 2], ["--ro-bind", str(self.root), "/tools/core-api"])
        self.assertIn("--unshare-net", argv)
        self.assertNotIn("--share-net", argv)
        self.assertEqual(argv[-1], "inert")
        for mode in ("acquire", "compile"):
            with self.assertRaisesRegex(ValueError, "SOCKET_EMULATOR_ONLY"):
                M.sandbox(command, mode, upstream_socket=self.path)

    def test_no_keys_or_any_other_file_in_exposed_directory(self):
        (self.root / "ssh-key").write_bytes(b"inert-not-a-real-key")
        with self.assertRaisesRegex(ValueError, "CORE_SOCKET_ONLY"):
            M.upstream_binding(self.path)

    def test_rejects_permissions_and_symlink(self):
        self.path.chmod(0o660)
        with self.assertRaisesRegex(ValueError, "CORE_SOCKET_ONLY"):
            M.upstream_binding(self.path)
        self.path.chmod(0o600)
        self.root.chmod(0o750)
        with self.assertRaisesRegex(ValueError, "CORE_SOCKET_PARENT"):
            M.upstream_binding(self.path)
        self.root.chmod(0o700)
        link = self.root / "other.sock"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "CORE_SOCKET_PATH"):
            M.upstream_binding(link)

    def test_inode_replacement_is_not_same_binding(self):
        before = M.upstream_binding(self.path)
        self.path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
            replacement.bind(str(self.path))
            self.path.chmod(0o600)
            self.assertNotEqual(M.upstream_binding(self.path), before)


class RuntimeAdmission(unittest.TestCase):
    def setUp(self):
        self.env = dict(VOLPAROSSA_WEATHER_SOURCE_SHA="a" * 40, GITHUB_SHA="b" * 40,
            GITHUB_RUN_ID="1234", GITHUB_RUN_ATTEMPT="1")
        self.value = dict(schema=1, kind="hosted-android-protected-core-preparation", identity=M.core_run_identity(self.env),
            actual_installed_app=False, core_delivery=False, release_authority=False,
            apk={"inert": "apk"}, native_sources={"inert": "native"}, runtime={"inert": "node"}, sdk={"inert": "sdk"},
            android={"inert": "android"}, dependencies={"inert": "dependencies"}, awk={"inert": "awk"}, java={"inert": "java"},
            receipts={name: M.H.sha(b"receipt") for name in ("offline-apk.json", "native-source.json", "toolchain.json",
                "dependency-capture.json", "emulator-preflight.json", "gradle-kotlin-config.json", "gradle-resources.json")})
        self.result = dict(schema=2, kind="hosted-android-protected-core-preparation", phase="prepared", success=True,
            process_drain_confirmed=True, policy_cleanup_complete=True, host_netns_unchanged=True,
            synthetic=False, mobile_core=False, production_authority=False)

    def invoke(self, *, changed=None, field=None):
        def document(path):
            if path.name == "prepared.json": return self.value
            if path.name == "result.json": return self.result
            if path.name == "cleanup.json": return dict(complete=True, process_drain_confirmed=True)
            return {"inert": "upstream"}
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.env))
            stack.enter_context(patch.object(M.H, "document", side_effect=document))
            stack.enter_context(patch.object(M.H, "read", return_value=b"receipt"))
            stack.enter_context(patch.object(M.H, "digest", return_value=changed if field == "apk" else self.value["apk"]))
            stack.enter_context(patch.object(M, "native_sources", return_value=changed if field == "native" else self.value["native_sources"]))
            stack.enter_context(patch.object(M.H, "runtime_inventory", return_value=changed if field == "runtime" else self.value["runtime"]))
            stack.enter_context(patch.object(M.W, "verify_phase_inputs", return_value=changed if field == "sdk" else self.value["sdk"]))
            stack.enter_context(patch.object(M.runpy, "run_path", return_value={"verify": lambda _: changed if field == "android" else self.value["android"]}))
            stack.enter_context(patch.object(M, "verification_metadata", return_value=changed if field == "dependencies" else self.value["dependencies"]))
            stack.enter_context(patch.object(M, "apt_awk_digest", return_value=changed if field == "awk" else self.value["awk"]))
            stack.enter_context(patch.object(M, "apt_java_digest", return_value=changed if field == "java" else self.value["java"]))
            return M.prepared_core_inputs(Mock())

    def test_readmission_retains_original_bindings(self):
        self.assertEqual(self.invoke(), self.value)

    def test_rejects_replaced_apk_sources_tools_and_dependencies(self):
        for field in ("apk", "native", "runtime", "sdk", "android", "dependencies", "awk", "java"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "PREPARED_"):
                self.invoke(field=field, changed={"changed": True})

    def test_rejects_prior_run_incomplete_cleanup_and_missing_receipts(self):
        self.value["identity"]["run_attempt"] = "2"
        with self.assertRaisesRegex(ValueError, "CORE_PREPARATION_IDENTITY"):
            self.invoke()
        self.value["identity"]["run_attempt"] = "1"
        for field in ("success", "process_drain_confirmed", "policy_cleanup_complete", "host_netns_unchanged"):
            self.result[field] = False
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "CORE_PREPARATION_COMPLETION"):
                self.invoke()
            self.result[field] = True
        self.value["receipts"].pop("offline-apk.json")
        with self.assertRaisesRegex(ValueError, "PREPARED_RECEIPT_SET"):
            self.invoke()


class Commands(unittest.TestCase):
    def test_live_cli_is_explicit_and_does_not_rebuild_or_accept_commands(self):
        for args, target in ((["--prepare-protected-core"], "execute"),
                (["--run-protected-core", "--upstream-socket", "/inert/api.sock"], "run_protected_core")):
            with patch.object(M.sys, "argv", ["runner", *args]), patch.object(M, "guards", return_value=("helper", "platform")) as guard, \
                    patch.object(M.H, "private_directory"), patch.object(M, "execute") as prepare, patch.object(M, "run_protected_core") as live:
                M.main()
                guard.assert_called_once_with(os.environ, protected_core=True)
                if target == "execute":
                    prepare.assert_called_once_with("helper", "platform", prepare_only=True)
                    live.assert_not_called()
                else:
                    live.assert_called_once_with("helper", "platform", "/inert/api.sock")
                    prepare.assert_not_called()
        with patch.object(M.sys, "argv", ["runner", "--run-protected-core", "--command", "anything"]), \
                self.assertRaisesRegex(ValueError, "NO_ARBITRARY_COMMAND"):
            M.main()

    def test_fixed_live_trial_retains_memory_time_guest_and_cleanup_guards(self):
        tree = ast.parse((ROOT / "scripts/prepare_hosted_android_ci.py").read_text())
        runner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_protected_core")
        calls = [n for n in ast.walk(runner) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "H" and n.func.attr == "run"]
        self.assertEqual(len(calls), 1)
        with patch.object(M.H, "run", return_value=b"inert") as run, patch.object(M, "upstream_binding", return_value={}):
            eval(compile(ast.Expression(calls[0]), "<live-runtime>", "eval"),
                dict(vars(M), netns="inert-netns", upstream_socket="/inert/api.sock"))
        args, kwargs = run.call_args
        self.assertEqual(args[0], "installed-android-protected-core-trial")
        self.assertEqual(args[2], 520)
        self.assertEqual(args[1][-3:], ["--inside-protected-core", "--upstream-socket", "/tools/core-api/api.sock"])
        self.assertEqual(kwargs["memory"], 4 * M.GIB)
        self.assertNotIn("reserve", kwargs)
        inside = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "inside")
        source = ast.get_source_segment((ROOT / "scripts/prepare_hosted_android_ci.py").read_text(), inside)
        self.assertIn('boundary = network.enforce(adb_command, stop)', source)
        self.assertIn('adb_command("reverse", "tcp:43210", "tcp:43210")', source)
        self.assertNotIn('"tcp:43211"', source)
        self.assertIn('drained = drain_children(children)', source)
        self.assertIn('"--profile", "protected-core"', source)
        self.assertIn('else 480)', source)

    def test_preparation_stops_before_installed_trial(self):
        tree = ast.parse((ROOT / "scripts/prepare_hosted_android_ci.py").read_text())
        prepare = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
        body = next(n for n in prepare.body if isinstance(n, ast.Try)).body
        conditional = next(n for n in body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "prepare_only")
        self.assertIsInstance(conditional.body[-1], ast.Return)
        source = ast.get_source_segment((ROOT / "scripts/prepare_hosted_android_ci.py").read_text(), prepare)
        self.assertLess(source.index("run_app_gradle(False)"), source.index("if prepare_only:"))
        self.assertLess(source.index("if prepare_only:"), source.index('phase = "installed-emulator-trial"'))
        self.assertIn('helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED', source)


class RuntimeLifecycle(unittest.TestCase):
    def run_inert(self, root, failure=False):
        """Execute the actual orchestration, with all executable seams inert."""
        live, proof, sdk = root / "live", root / "proof", root / "sdk"
        mount = sdk / "packages/flutter_tools/.dart_tool"
        mount.mkdir(mode=0o700, parents=True)
        for name in M.GRADLE_STATE:
            (sdk / "packages/flutter_tools/gradle" / name).mkdir(mode=0o700, parents=True)
        sock_dir = root / "socket"
        sock_dir.mkdir(mode=0o700)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        path = sock_dir / "api.sock"
        sock.bind(str(path))
        path.chmod(0o600)
        helper = SimpleNamespace(prechecks=Mock(return_value={}), process=Mock(), staged_owned=Mock(),
            STAGED=Path("/inert/policy"), PARSER="/inert/parser", DRAIN_CONFIRMED=True,
            cleanup=Mock(return_value=dict(complete=not failure, process_drain_confirmed=not failure)))
        prepared = dict(identity={"inert": "run"}, apk={"inert": "apk"}, native_sources={"inert": "native"})
        def run(name, _argv, _seconds, **_kwargs):
            self.assertEqual(name, "installed-android-protected-core-trial")
            if failure:
                M.H.DRAIN_CONFIRMED = False
                raise ValueError("INERT_CHILD_FAILED")
            for filename, value in (("report.json", report()), ("emulator-boundary.json", {"inert": "boundary"}),
                    ("emulator-cleanup.json", dict(schema=1, direct_children_reaped=True, private_avd_removed=True,
                        private_android_home_removed=True, trial_returned=True, enclosing_namespace_cleanup_required=True))):
                M.H.write(proof / filename, json.dumps(value).encode())
        try:
            with ExitStack() as stack:
                for obj, fields in ((M, ("OUTPUT", "PRIVATE", "PROOF", "LIVE_OUTPUT", "LIVE_PROOF", "SDK")),
                        (M.H, ("OUTPUT", "PRIVATE", "PROOF", "DRAIN_CONFIRMED", "LOGS")),
                        (M.W, ("OUTPUT", "PRIVATE", "SDK_TOOL_STATE", "SDK_TOOL_MOUNT"))):
                    for field in fields:
                        stack.enter_context(patch.object(obj, field, getattr(obj, field)))
                M.LIVE_OUTPUT, M.LIVE_PROOF, M.SDK, M.W.SDK_TOOL_MOUNT = live, proof, sdk, mount
                M.H.DRAIN_CONFIRMED, M.H.LOGS = True, []
                stack.enter_context(patch.object(M, "prepared_core_inputs", return_value=prepared))
                stack.enter_context(patch.object(M, "prepare_gradle_user_properties", return_value={}))
                stack.enter_context(patch.object(M, "preflight"))
                stack.enter_context(patch.object(M, "sandbox", side_effect=lambda command, *_a, **_k: command))
                stack.enter_context(patch.object(M, "native_sources", return_value=prepared["native_sources"]))
                stack.enter_context(patch.object(M.H, "digest", return_value=prepared["apk"]))
                original_read = M.H.read
                stack.enter_context(patch.object(M.H, "read", side_effect=lambda p, *a:
                    b"original-preparation" if p.parent == M.PREPARED_OUTPUT else original_read(p, *a)))
                stack.enter_context(patch.object(M.H, "run", side_effect=run))
                if failure:
                    with self.assertRaisesRegex(ValueError, "CLEANUP_UNCONFIRMED"):
                        M.run_protected_core(helper, {"inert": "platform"}, str(path))
                else:
                    M.run_protected_core(helper, {"inert": "platform"}, str(path))
        finally:
            sock.close()
        return live, proof, helper

    def test_actual_orchestration_joins_child_and_writes_distinct_original_receipts(self):
        with tempfile.TemporaryDirectory(prefix="vpa-") as raw:
            live, proof, helper = self.run_inert(Path(raw))
            result = json.loads((live / "result.json").read_text())
            self.assertTrue(result["success"])
            self.assertFalse(result["core_delivery"])
            self.assertFalse(result["joined_core_acceptance"])
            self.assertFalse(result["expiry_proven"])
            self.assertEqual(json.loads((proof / "report.json").read_text()), report())
            helper.cleanup.assert_called_once_with({"inert": "platform"}, True, True)
            self.assertEqual(len(helper.process.call_args_list), 2)
            self.assertTrue((live / "private").is_dir())
            self.assertFalse((live / "failure.json").exists())

    def test_actual_orchestration_cannot_launder_unconfirmed_child_drain(self):
        with tempfile.TemporaryDirectory(prefix="vpa-") as raw:
            live, _proof, helper = self.run_inert(Path(raw), failure=True)
            result = json.loads((live / "result.json").read_text())
            self.assertFalse(result["success"])
            self.assertFalse(result["process_drain_confirmed"])
            self.assertFalse(helper.DRAIN_CONFIRMED)
            helper.cleanup.assert_called_once_with({"inert": "platform"}, True, True)
            self.assertEqual(json.loads((live / "failure.json").read_text())["code"], "INERT_CHILD_FAILED")
            self.assertFalse((live / "installed.json").exists())


if __name__ == "__main__":
    unittest.main()
