#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Pure/inert tests only: no package installation, browser, bwrap or build."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "scripts/prepare_hosted_clients_ci.py"))
G = H["main"].__globals__


class HostedClients(unittest.TestCase):
    def test_profile_is_separately_pinned_and_capability_denied_child(self):
        raw = H["PROFILE"].read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), H["PROFILE_SHA"])
        self.assertIn("volparossa_ci_weather_clients_bwrap /usr/bin/bwrap", raw.decode())
        child = raw.decode().split("profile volparossa_ci_weather_clients_child", 1)[1]
        self.assertIn("audit deny capability,", child)
        self.assertNotIn("allow capability,", child)
        helper = H["policy_helper"]()
        self.assertEqual(helper.STAGED, Path("/run/volparossa-weather-clients.apparmor"))
        decoder = runpy.run_path(str(ROOT / "scripts/prepare_hosted_decoder_ci.py"))
        self.assertNotEqual(decoder["STAGED"], helper.STAGED)
        self.assertNotEqual(decoder["PROFILE_SHA"], helper.PROFILE_SHA)
        self.assertIn("/run/volparossa-weather-decoder", str(decoder["STAGED"]))

    def test_development_host_and_other_workflow_rejected_before_mutation(self):
        valid = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
            GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW="Build hosted Weather clients",
            GITHUB_WORKSPACE=str(ROOT), GITHUB_SHA="a" * 40)
        for key in ("GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_ENVIRONMENT", "GITHUB_REPOSITORY", "GITHUB_WORKFLOW"):
            with self.subTest(key=key), patch.dict(G, policy_helper=Mock(side_effect=AssertionError("not reached"))), \
                    self.assertRaisesRegex(ValueError, "DISPOSABLE_CI"):
                H["guards"](dict(valid, **{key: "wrong"}))
        with patch.object(os, "geteuid", return_value=0), self.assertRaisesRegex(ValueError, "ORDINARY_RUNNER"):
            H["guards"](valid)

    def test_no_freeform_cli(self):
        with patch.object(sys, "argv", ["helper", "--anything"]), \
                patch.dict(G, guards=Mock(side_effect=AssertionError("not reached"))), \
                self.assertRaisesRegex(ValueError, "NO_ARGUMENTS"):
            H["main"]()

    def test_environment_is_allowlisted_and_uses_explicit_runtime(self):
        with patch.dict(os.environ, HOME="/private", GH_TOKEN="secret", npm_config_registry="https://evil",
                        NODE_OPTIONS="--require=/private/input.js", HTTPS_PROXY="http://proxy"):
            env = H["environment"]()
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual(env["HOME"], "/home/runner")
        self.assertEqual(env["NODE_OPTIONS"], "--max-old-space-size=768")
        self.assertEqual(env["npm_config_userconfig"], "/state/user.npmrc")
        self.assertEqual(env["npm_config_globalconfig"], "/state/global.npmrc")
        self.assertEqual(env["npm_config_ignore_scripts"], "true")
        self.assertEqual(env["PATH"], str(H["NODE"].parent) + ":/usr/bin:/bin")
        self.assertEqual(H["npm_command"]()[:2], [str(H["NODE"]), str(H["NPM"])])
        self.assertIn("--ignore-scripts", H["npm_command"]())

    def test_only_acquisition_gets_external_network_dns_and_certificates(self):
        for mode in ("acquire", "compile", "browser"):
            writable = H["PROOF"] if mode == "browser" else H["STAGE"]
            command = H["sandbox"](["/usr/bin/true"], mode=mode, writable=writable)
            self.assertEqual("--unshare-net" in command, mode != "acquire")
            self.assertEqual("/etc/resolv.conf" in command, mode == "acquire")
            self.assertEqual("/etc/ssl/certs" in command, mode == "acquire")
            self.assertIn("--unshare-user", command)
            self.assertIn("--unshare-pid", command)
            self.assertIn("--die-with-parent", command)
            self.assertIn("--new-session", command)
            self.assertEqual(command[command.index("--tmpfs") + 1], "/")
            self.assertNotIn(["--ro-bind", "/", "/"], [command[i:i+3] for i in range(len(command))])
            self.assertNotIn("/root", command)
            # GitHub's real home has the same spelling as the empty synthetic
            # home. A --dir/--remount-ro destination is not a host bind source.
            host_sources = [command[i+1] for i, arg in enumerate(command)
                            if arg in ("--bind", "--ro-bind")]
            for host_home in (str(Path.home()), "/home/runner"):
                self.assertNotIn(host_home, host_sources)
            self.assertIn(["--tmpfs", "/home/runner"], [command[i:i+2] for i in range(len(command))])
            self.assertIn(["--remount-ro", "/"], [command[i:i+2] for i in range(len(command))])

    def test_browser_only_writable_host_mount_is_private_proof(self):
        command = H["sandbox"](["/usr/bin/true"], mode="browser", writable=H["PROOF"])
        writable = [command[i+1:i+3] for i, arg in enumerate(command) if arg == "--bind"]
        self.assertEqual(writable, [[str(H["PROOF"]), str(H["PROOF"])],
                                   [str(H["PROOF"] / "appdata"), "/home/runner/.mozilla"]])
        self.assertNotIn("/state", command)
        with self.assertRaisesRegex(ValueError, "BROWSER_OUTPUT"):
            H["sandbox"]([], mode="browser", writable=Path("/unknown"))

    def test_private_home_is_a_mount_created_before_nested_hosted_checkout(self):
        hosted = Path("/home/runner/work/volparossa-weather/volparossa-weather")
        for mode in ("acquire", "compile", "browser"):
            with self.subTest(mode=mode), patch.dict(G, ROOT=hosted):
                command = H["sandbox"]([], mode=mode,
                    writable=H["PROOF"] if mode == "browser" else H["STAGE"])
            pairs = [command[i:i+2] for i in range(len(command))]
            triples = [command[i:i+3] for i in range(len(command))]
            mounted = pairs.index(["--tmpfs", "/home/runner"])
            source = triples.index(["--ro-bind", str(hosted), str(hosted)])
            readonly = pairs.index(["--remount-ro", "/home/runner"])
            self.assertLess(mounted, source)
            self.assertLess(source, readonly)
            self.assertNotIn(["--dir", "/home/runner"], pairs)
            self.assertNotIn(["--ro-bind", "/home/runner", "/home/runner"], triples)

    def test_compilation_uses_only_fixed_clis_without_upstream_prehook(self):
        commands = H["compile_commands"]()
        self.assertEqual([item[1] for item in commands], ["paraglide-js", "svelte-kit", "svelte-check", "vite"])
        self.assertEqual(commands[-1][2], ["build"])
        self.assertEqual([item[3] for item in commands], [120, 120, 120, 180])
        self.assertNotIn("npm", repr(commands))
        self.assertNotIn("prebuild", repr(commands))
        self.assertNotIn("npx", repr(commands))

    def test_client_fixture_scratch_uses_private_tmp_without_writable_checkout(self):
        source = (ROOT / "integrations/drizzli/test-client.mjs").read_text()
        self.assertIn("import { tmpdir } from 'node:os';", source)
        self.assertIn("const work = await mkdtemp(join(tmpdir(), 'drizzli-client-test-'));", source)
        self.assertNotIn("await mkdir(join(root, 'build')", source)
        self.assertNotIn("mkdtemp(join(root", source)
        self.assertLess(source.index("after(() => rm(work, { recursive: true }));"),
                        source.index("await cp("))
        command = H["sandbox"]([], mode="compile", writable=H["STAGE"])
        self.assertIn(["--tmpfs", "/tmp"], [command[i:i+2] for i in range(len(command))])
        self.assertNotIn(["--bind", str(ROOT / "build"), str(ROOT / "build")],
                         [command[i:i+3] for i in range(len(command))])

    def test_only_production_build_receives_larger_aggregate_budget(self):
        for name, _cli, _arguments, seconds in H["compile_commands"]():
            self.assertEqual(H["compilation_memory"](name),
                2 * H["GIB"] if name == "production-build" else 1536 * 1024**2)
            if name == "production-build":
                self.assertEqual(seconds, 180)
        with self.assertRaisesRegex(ValueError, "UNKNOWN_COMPILE_PHASE"):
            H["compilation_memory"]("npm-acquisition")
        self.assertEqual(H["environment"]()["NODE_OPTIONS"], "--max-old-space-size=768")

    def test_only_exact_upstream_engine_strict_config_is_admitted_unchanged(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, STAGE=Path(directory)):
            path = Path(directory) / ".npmrc"
            original = b"engine-strict=true\n"
            path.write_bytes(original)
            path.chmod(0o600)
            self.assertEqual(H["project_npm_config"](), hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(), original)
            for config in (b"", b"engine-strict=false\n", b"engine-strict=true",
                    original + b"registry=https://example.invalid/\n",
                    original + b"//registry.npmjs.org/:_authToken=secret\n",
                    original + b"ignore-scripts=false\n", original + b"script-shell=/bin/sh\n"):
                with self.subTest(config=config):
                    path.write_bytes(config)
                    with self.assertRaisesRegex(ValueError, "PROJECT_NPM_CONFIG_NOT_ADMITTED"):
                        H["project_npm_config"]()

    def test_project_config_missing_and_symlinked_are_not_admitted(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, STAGE=Path(directory)):
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                H["project_npm_config"]()
            (root / "other").write_bytes(b"engine-strict=true\n")
            (root / ".npmrc").symlink_to("other")
            with self.assertRaises(OSError):
                H["project_npm_config"]()

    def test_extensionless_locked_svelte_check_cli_is_accepted_not_arbitrary_target(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, STAGE=Path(directory)):
            stage = Path(directory)
            target = stage / "node_modules/svelte-check/bin/svelte-check"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"#!/usr/bin/env node\nrequire('../dist/src/index.js');\n")
            target.chmod(0o600)
            links = stage / "node_modules/.bin"
            links.mkdir()
            (links / "svelte-check").symlink_to("../svelte-check/bin/svelte-check")
            self.assertEqual(H["installed_cli"]("svelte-check"), target)
            (links / "vite").symlink_to("../svelte-check/bin/svelte-check")
            with self.assertRaisesRegex(ValueError, "UNEXPECTED_BUILD_CLI"):
                H["installed_cli"]("vite")

    def test_browser_uses_existing_driver_and_both_product_flags(self):
        args = H["browser_command"]("net:[123]")
        self.assertEqual(args[:2], ["/usr/bin/python3", "-B"])
        self.assertIn("--inside", args)
        self.assertIn("--precipitation", args)
        self.assertIn("--air-quality", args)
        self.assertEqual(args[-2:], ["--host-netns", "net:[123]"])
        self.assertEqual(args[args.index("--browser-root")+1], str(H["BROWSER"]))
        self.assertEqual(H["FIREFOX_VERSION"], "140.16.0")
        self.assertEqual(H["FIREFOX_SOURCE_STAMP"], "d864999404b3032f682d74ccc60d1ce38c9ce609")

    def test_identity_files_are_not_in_writable_state(self):
        command = H["sandbox"]([], mode="compile", writable=H["STAGE"])
        mounts = [command[i+1:i+3] for i, arg in enumerate(command) if arg == "--ro-bind"]
        self.assertIn([str(H["OUTPUT"] / "passwd"), "/etc/passwd"], mounts)
        self.assertIn([str(H["OUTPUT"] / "group"), "/etc/group"], mounts)
        self.assertNotIn([str(H["PRIVATE"] / "passwd"), "/etc/passwd"], mounts)

    def test_each_phase_preflight_uses_its_actual_mounts_and_network(self):
        fields = {key: True for key in ("unprivileged", "capabilities_zero", "no_new_privileges",
            "capability_denied_child", "empty_root", "private_home", "read_only_source",
            "only_declared_host_writes", "auth_environment_absent")}
        for mode in ("acquire", "compile", "browser"):
            value = dict(fields, schema=1, kind="hosted-client-sandbox-preflight", mode=mode,
                loopback_only=mode != "acquire", separate_network_namespace=mode != "acquire",
                external_acquisition=mode == "acquire")
            command = Mock(return_value=json.dumps(value).encode())
            with patch.dict(G, run=command, save=Mock()):
                H["preflight"](mode)
            argv = command.call_args.args[1]
            writable = H["PROOF"] if mode == "browser" else H["STAGE"]
            self.assertIn(["--bind", str(writable), str(writable)], [argv[i:i+3] for i in range(len(argv))])
            self.assertEqual("--unshare-net" in argv, mode != "acquire")
            value["auth_environment_absent"] = False
            with patch.dict(G, run=Mock(return_value=json.dumps(value).encode()), save=Mock()), \
                    self.assertRaisesRegex(ValueError, "PREFLIGHT_FAILED"):
                H["preflight"](mode)

    def test_regular_file_reader_rejects_links_and_duplicate_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data"
            path.write_bytes(b'{"x":1,"x":2}')
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "DUPLICATE"):
                H["document"](path)
            (root / "link").symlink_to(path)
            with self.assertRaises(OSError):
                H["read"](root / "link")
            os.link(path, root / "hard")
            with self.assertRaisesRegex(ValueError, "UNSAFE"):
                H["read"](path)

    def test_runtime_closure_rejects_unlisted_npm_configuration_and_links(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, RUNTIME=Path(directory)):
            runtime = Path(directory)
            for name in ("node", "firefox", "licenses"):
                (runtime / name).mkdir()
            (runtime / "node/npm.js").write_text("expected")
            H["verify_runtime_closure"]({"node/npm.js": {}})
            (runtime / "node/npmrc").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "EXTRA_OR_MISSING"):
                H["verify_runtime_closure"]({"node/npm.js": {}})
            (runtime / "node/link").symlink_to("npm.js")
            with self.assertRaisesRegex(ValueError, "TREE_TYPE"):
                H["verify_runtime_closure"]({"node/npm.js": {}, "node/npmrc": {}})

    def test_group_drain_is_observed_not_assumed_from_sent_signal(self):
        with patch.object(os, "killpg", side_effect=ProcessLookupError):
            self.assertTrue(H["group_drained"](999999, seconds=0))
        with patch.object(os, "killpg", return_value=None):
            self.assertFalse(H["group_drained"](999999, seconds=0))

    def test_guarded_write_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result"
            H["write"](path, b"original")
            with self.assertRaises(FileExistsError):
                H["write"](path, b"replacement")
            self.assertEqual(path.read_bytes(), b"original")

    def test_inert_process_keeps_original_output_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True):
            raw = H["run"]("inert", [sys.executable, "-I", "-c", "print('bounded')"], 5, reserve=False)
            self.assertEqual(raw, b"bounded\n")
            self.assertEqual((Path(directory) / "inert.log").read_bytes(), raw)
            self.assertEqual(G["LOGS"][0]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(G["LOGS"][0]["exit_status"], 0)
            self.assertTrue(G["DRAIN_CONFIRMED"])
            self.assertNotIn("peak_memory_categories", G["LOGS"][0])
            self.assertNotIn("memory_category_method", G["LOGS"][0])

    def test_failed_process_is_not_a_success_or_empty_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True):
            with self.assertRaisesRegex(ValueError, "CHILD_FAILED"):
                H["run"]("failed", [sys.executable, "-I", "-c", "print('bad'); raise SystemExit(7)"], 5, reserve=False)
            self.assertEqual(G["LOGS"][0]["exit_status"], 7)
            self.assertEqual((Path(directory) / "failed.log").read_bytes(), b"bad\n")

    def test_log_bound_drains_owned_inert_process(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True, LIMIT=128):
            with self.assertRaisesRegex(ValueError, "LOG_BOUND"):
                H["run"]("oversized", [sys.executable, "-I", "-c", "print('x'*256)"], 5, reserve=False)
            self.assertEqual(G["DRAIN_CONFIRMED"], G["LOGS"][0]["exit_status"] >= 0)
            self.assertLessEqual((Path(directory) / "oversized.log").stat().st_size, 128)

    def test_memory_reserve_fails_before_popen(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                available_memory=lambda: 2 * H["GIB"]), patch.object(subprocess, "Popen") as command:
            with self.assertRaisesRegex(ValueError, "HOST_MEMORY_RESERVE"):
                H["run"]("reserve", ["not-executed"], 5)
            command.assert_not_called()

    def test_prelaunch_requires_actual_budget_plus_unchanged_host_reserve(self):
        for budget in (1536 * 1024**2, 2 * H["GIB"], 4 * H["GIB"]):
            needed = budget + 2 * H["GIB"]
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(G, OUTPUT=Path(directory), LOGS=[], available_memory=lambda: needed - 1), \
                    patch.object(subprocess, "Popen") as command:
                with self.assertRaisesRegex(ValueError, "HOST_MEMORY_RESERVE"):
                    H["run"]("headroom", ["not-executed"], 5, memory=budget)
                command.assert_not_called()
                record = G["LOGS"][0]
                self.assertTrue(record["memory_monitor_enabled"])
                self.assertEqual(record["memory_limit_bytes"], budget)
                self.assertEqual(record["host_reserve_bytes"], 2 * H["GIB"])
                self.assertEqual(record["launch_min_available_bytes"], needed)

    def test_categories_use_same_rss_with_vanished_and_unreadable_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            # 105 vanishes before status. 104 has status but no executable;
            # 106 is a zero-RSS zombie. None may discard an observed RSS value.
            for pid, rss, exe in ((101, 1024, "java"), (102, 2048, "dartvm"),
                    (103, 12, "private-name-never-exported"), (104, 7, None), (106, None, None)):
                base = proc / str(pid)
                (base / "task" / str(pid)).mkdir(parents=True)
                (base / "status").write_text("State: Z\n" if rss is None else f"VmRSS: {rss} kB\n")
                (base / "task" / str(pid) / "children").write_text("102 103 104 105 106 102" if pid == 101 else "")
                if exe is not None:
                    (base / "exe").symlink_to("/inert-not-executed/" + exe)
            categories = {k: dict(processes=0, rss_bytes=0) for k in ("java", "dart", "other")}
            with patch.dict(G, Path=lambda value: proc if value == "/proc" else Path(value)):
                total = H["owned_rss"](101, categories=categories)
                with patch.object(os, "readlink", side_effect=AssertionError("default must not inspect names")):
                    self.assertEqual(H["owned_rss"](101), total)
            self.assertEqual(categories, dict(java=dict(processes=1, rss_bytes=1024**2),
                dart=dict(processes=1, rss_bytes=2*1024**2), other=dict(processes=3, rss_bytes=19*1024)))
            self.assertEqual(total, sum(v["rss_bytes"] for v in categories.values()))
            self.assertNotIn("private-name", json.dumps(categories))
        for executable in ("dart", "dartvm", "dartaotruntime"):
            with patch.object(os, "readlink", return_value="/not-exported/" + executable):
                self.assertEqual(H["rss_category"](Path("/inert")), "dart")
        with patch.object(os, "readlink", side_effect=PermissionError):
            self.assertEqual(H["rss_category"](Path("/inert")), "other")

    def test_four_gib_inert_child_uses_six_gib_admission_and_closed_peak_sample(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                DRAIN_CONFIRMED=True, available_memory=lambda: 6 * H["GIB"]):
            raw = H["run"]("categories", [sys.executable, "-I", "-c", "print('small inert child')"],
                5, memory=4*H["GIB"], memory_categories=True)
            self.assertEqual(raw, b"small inert child\n")
            record = G["LOGS"][0]
            self.assertEqual(record["launch_min_available_bytes"], 6*H["GIB"])
            self.assertEqual(record["host_reserve_bytes"], 2*H["GIB"])
            self.assertEqual(record["memory_limit_bytes"], 4*H["GIB"])
            self.assertEqual(set(record["peak_memory_categories"]), {"java", "dart", "other"})
            for value in record["peak_memory_categories"].values():
                self.assertEqual(set(value), {"processes", "rss_bytes"})
                self.assertTrue(all(type(v) is int and v >= 0 for v in value.values()))
            self.assertEqual(sum(v["rss_bytes"] for v in record["peak_memory_categories"].values()), record["peak_descendant_rss"])
            self.assertTrue(record["returned"])

    def test_same_peak_sample_is_retained_when_cap_stops_real_inert_child(self):
        # A tiny bound, not a multi-GiB allocation. The same real Python child
        # and ordinary /proc traversal exercise the actual stop/evidence path.
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                DRAIN_CONFIRMED=True, available_memory=lambda: 6*H["GIB"]):
            with self.assertRaisesRegex(ValueError, "CHILD_MEMORY_BOUND"):
                H["run"]("cap", [sys.executable, "-I", "-c", "import time;time.sleep(10)"],
                    5, memory=1, memory_categories=True)
            record = G["LOGS"][0]
            self.assertGreater(record["peak_descendant_rss"], 1)
            self.assertEqual(sum(v["rss_bytes"] for v in record["peak_memory_categories"].values()), record["peak_descendant_rss"])
            self.assertLess(record["exit_status"], 0)
            self.assertFalse(record["returned"])
            self.assertFalse(record["process_drain_confirmed"])

    def test_breakdown_is_one_peak_snapshot_not_sum_of_independent_category_peaks(self):
        samples = []
        def sample(_pid, *, categories):
            kind, rss = ("java", 100) if not samples else ("dart", 50)
            categories[kind] = dict(processes=1, rss_bytes=rss)
            samples.append(rss)
            return rss
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                DRAIN_CONFIRMED=True, available_memory=lambda: 6*H["GIB"], owned_rss=sample):
            H["run"]("one-sample", [sys.executable, "-I", "-c", "import time;print('ready',flush=True);time.sleep(0.02)"],
                5, memory=4*H["GIB"], memory_categories=True)
            self.assertGreaterEqual(len(samples), 2)
            record = G["LOGS"][0]
            self.assertEqual(record["peak_descendant_rss"], 100)
            self.assertEqual(record["peak_memory_categories"], dict(java=dict(processes=1, rss_bytes=100),
                dart=dict(processes=0, rss_bytes=0), other=dict(processes=0, rss_bytes=0)))

    def test_four_gib_profile_still_stops_when_running_host_reserve_falls(self):
        available = iter((6*H["GIB"], 2*H["GIB"]-1))
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                DRAIN_CONFIRMED=True, available_memory=lambda: next(available)):
            with self.assertRaisesRegex(ValueError, "HOST_MEMORY_RESERVE"):
                H["run"]("reserve-fall", [sys.executable, "-I", "-c", "import time;time.sleep(10)"],
                    5, memory=4*H["GIB"], memory_categories=True)
            record = G["LOGS"][0]
            self.assertEqual(record["host_reserve_bytes"], 2*H["GIB"])
            self.assertLess(record["exit_status"], 0)
            self.assertFalse(record["process_drain_confirmed"])
            self.assertIsNone(record["peak_memory_categories"])

    def test_category_diagnostics_require_active_memory_monitor(self):
        for enabled, reserve in ((True, False), (1, True), ("yes", True)):
            with patch.object(subprocess, "Popen") as spawn, self.assertRaisesRegex(ValueError, "MEMORY_DIAGNOSTIC_SCOPE"):
                H["run"]("bad-scope", ["not-executed"], 5, reserve=reserve, memory_categories=enabled)
            spawn.assert_not_called()

    def test_prelaunch_retains_three_gib_minimum_for_small_probe_budget(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[],
                available_memory=lambda: 3 * H["GIB"] - 1), patch.object(subprocess, "Popen") as command:
            with self.assertRaisesRegex(ValueError, "HOST_MEMORY_RESERVE"):
                H["run"]("small-probe", ["not-executed"], 5, memory=H["GIB"] // 2)
            command.assert_not_called()
            self.assertEqual(G["LOGS"][0]["launch_min_available_bytes"], 3 * H["GIB"])

    def test_signal_cancellation_drains_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True):
            fake = Mock()
            fake.stdout = Mock()
            fake.pid = 123456789
            fake.returncode = 0
            with patch.object(subprocess, "Popen", return_value=fake), \
                    patch.object(H["selectors"], "DefaultSelector", side_effect=H["Interrupted"]("cancelled")), \
                    patch.object(os, "killpg") as kill, patch.dict(G, group_drained=lambda pid: True):
                with self.assertRaises(H["Interrupted"]):
                    H["run"]("cancel", ["not-executed"], 5, reserve=False)
                self.assertEqual(kill.call_args_list[0].args, (fake.pid, signal.SIGTERM))
                self.assertEqual(kill.call_args_list[1].args, (fake.pid, signal.SIGKILL))
                fake.wait.assert_called_once_with(timeout=5)
                fake.stdout.close.assert_called_once()
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_signal_during_spawn_is_deferred_until_process_is_owned(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True):
            fake = Mock(pid=123456789, returncode=0, stdout=Mock())
            def spawn(*args, **kwargs):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return fake
            with patch.object(subprocess, "Popen", side_effect=spawn), patch.object(os, "killpg"), \
                    patch.dict(G, group_drained=lambda pid: True):
                with self.assertRaisesRegex(H["Interrupted"], "DURING_OWNED_SPAWN"):
                    H["run"]("spawn-cancel", ["not-executed"], 5, reserve=False)
            fake.wait.assert_called_once_with(timeout=5)
            fake.stdout.close.assert_called_once()
            self.assertTrue(G["DRAIN_CONFIRMED"])

    def test_unconfirmed_group_or_signal_killed_wrapper_retains_policy_authority(self):
        for code, drained in ((0, False), (-9, True)):
            with self.subTest(code=code, drained=drained), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(G, OUTPUT=Path(directory), LOGS=[], DRAIN_CONFIRMED=True):
                fake = Mock(pid=123456789, returncode=code, stdout=Mock())
                with patch.object(subprocess, "Popen", return_value=fake), patch.object(os, "killpg"), \
                        patch.object(H["selectors"], "DefaultSelector", side_effect=H["Interrupted"]("cancelled")), \
                        patch.dict(G, group_drained=lambda pid: drained):
                    with self.assertRaises(H["Interrupted"]):
                        H["run"]("uncertain", ["not-executed"], 5, reserve=False)
                    self.assertFalse(G["DRAIN_CONFIRMED"])


if __name__ == "__main__":
    unittest.main()
