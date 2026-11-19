#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert recipe/validator tests; no compilation, downloads or native decoder execution."""
import json
import io
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT/"scripts/prepare_hosted_decoder.py"))


def toolchain():
    return dict(schema=1, kind="volparossa-hosted-decoder-toolchain", platform=H["platform"](), provenance_only=True,
        tools={key: dict(path="/usr/bin/"+key, bytes=4, sha256=H["sha"](b"tool"),
               version_sha256=H["sha"](b"version\n") if key in H["VERSION_ARGS"] else None)
               for key in H["TOOLS"]})


def decoded(latitude=60, longitude=0, value=0):
    return [dict(keys=dict(edition=2, packingType="grid_ccsds", bitsPerValue=16, numberOfPoints=496),
        method="nearest", neighbours=[dict(latitude=latitude, longitude=longitude, value=value,
        distance=0, distance_unit="km", unit="K")])]


class HostedDecoder(unittest.TestCase):
    def test_plan_is_inert_and_does_not_invent_authority_or_toolchain_pin(self):
        with patch.object(subprocess, "Popen", side_effect=AssertionError("must not execute")):
            value = H["plan"]()
        self.assertFalse(value["ready"])
        self.assertFalse(value["compiled"])
        self.assertEqual(value["missing"], ["captured-trusted-runner-toolchain-manifest"])
        self.assertFalse(value["scope"]["decoder_authorized"])
        self.assertFalse(value["scope"]["bit_reproducibility_proven"])
        self.assertFalse(value["scope"]["fully_hermetic_toolchain"])
        self.assertEqual((value["jobs"], value["deadline_seconds"]), (2, 1800))
        self.assertEqual(value["tool_names"], sorted(H["TOOLS"]))

    def test_legacy_source_and_builder_pins_are_unchanged(self):
        self.assertEqual(H["sha"]((ROOT/"third_party/eccodes-sources.json").read_bytes()), H["PIN_SHA"])
        self.assertEqual(H["sha"]((ROOT/"scripts/build_eccodes.py").read_bytes()), H["LEGACY_SHA"])

    def test_platform_capture_is_actual_and_does_not_claim_guest_abi(self):
        for os_id, version in (("debian", "13"), ("ubuntu", "24.04")):
            raw = f'ID={os_id}\nVERSION_ID="{version}"\n'.encode()
            with patch.dict(H["platform"].__globals__, read_file=lambda *args: raw):
                self.assertEqual(H["platform"](), dict(os_id=os_id, version_id=version,
                    architecture="x86_64", os_release_sha256=H["sha"](raw)))
        with patch.dict(H["platform"].__globals__, read_file=lambda *args: b'ID=ubuntu\nVERSION_ID="22.04"\n'):
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_BUILD_PLATFORM"):
                H["platform"]()
        self.assertFalse(H["SCOPE"]["debian13_abi_proven"])

    def test_date_shim_is_fixed_epoch_closed_and_does_not_call_host_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"date"
            path.write_bytes(H["DATE_SHIM"])
            for args, expected in ((["+%d/%m/%Y"], b"01/09/2025\n"),
                    (["+%Y/%m/%d/%H/%M/%S"], b"2025/09/01/00/00/00\n")):
                result = subprocess.run(["sh", str(path), *args], capture_output=True, timeout=2)
                self.assertEqual((result.returncode, result.stdout), (0, expected))
            for args in ([], ["-s", "tomorrow"], ["+%s"], ["+%d/%m/%Y", "extra"]):
                self.assertEqual(subprocess.run(["sh", str(path), *args], capture_output=True,
                                 timeout=2).returncode, 64)
        self.assertEqual(H["ENV"]["SOURCE_DATE_EPOCH"], "1756684800")
        self.assertEqual(H["ENV"]["TZ"], "UTC")

    def test_namespace_has_fixed_paths_readonly_toolchain_no_host_home_or_network(self):
        command = H["sandbox"](Path("/private/output"), toolchain()["tools"], ["cmake", "--version"])
        for flag in ("--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts"):
            self.assertIn(flag, command)
        self.assertIn(["--bind", "/private/output", "/build"], [command[i:i+3] for i in range(len(command))])
        self.assertEqual(command.count("--bind"), 1)
        readonly = [command[i+1:i+3] for i, word in enumerate(command) if word == "--ro-bind"]
        self.assertEqual(readonly, [["/usr", "/usr"], ["/etc/ld.so.cache", "/etc/ld.so.cache"]])
        self.assertNotIn(["--ro-bind", "/", "/"], [command[i:i+3] for i in range(len(command))])
        self.assertEqual(command[-3:], ["--", "cmake", "--version"])

    def test_build_commands_preserve_source_features_and_require_real_ccsds_test(self):
        steps = dict(H["commands"](toolchain()["tools"]))
        self.assertEqual(len(steps), 10)
        for name in ("configure-libaec", "configure-eccodes"):
            self.assertIn("-DCMAKE_C_FLAGS=" + H["NORMAL_FLAGS"], steps[name])
            self.assertIn("-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG", steps[name])
        for option in ("-DFETCHCONTENT_FULLY_DISCONNECTED=ON", "-DENABLE_MEMFS=ON", "-DENABLE_AEC=ON"):
            self.assertIn(option, steps["configure-eccodes"])
        self.assertEqual(steps["compile-eccodes"][-2:], ["--parallel", "2"])
        self.assertEqual(steps["test-libaec"], ["/usr/bin/ctest", "--test-dir", "/build/libaec-build",
                                             "--output-on-failure", "--timeout", "60"])
        self.assertIn("grib_filter", steps["compile-eccodes"])
        self.assertEqual(steps["encode-ccsds"][-1], "/build/eccodes-source/samples/ccsds_grib2.tmpl")
        self.assertIn("60,0,1", steps["decode-ccsds-first"])
        self.assertIn("0,30,1", steps["decode-ccsds-last"])
        self.assertEqual(steps["decode-ccsds-first"][-1], "/build/probe.grib2")

    def test_nonconstant_ccsds_points_are_required_not_just_version_or_constant_template(self):
        H["validate_decode"](json.dumps(decoded()), 60, 0, 0)
        H["validate_decode"](json.dumps(decoded(0, 30, 495)), 0, 30, 495)
        mutations = [lambda v: v[0]["keys"].update(bitsPerValue=0),
            lambda v: v[0]["keys"].update(packingType="grid_simple"),
            lambda v: v[0]["keys"].update(numberOfPoints=1),
            lambda v: v[0].update(method="interpolated"),
            lambda v: v[0]["neighbours"][0].update(value=None),
            lambda v: v[0]["neighbours"][0].update(value=True),
            lambda v: v[0]["neighbours"][0].update(value=float("nan")),
            lambda v: v[0]["neighbours"][0].update(longitude=1),
            lambda v: v[0]["neighbours"].append(v[0]["neighbours"][0]),
            lambda v: v.append(v[0])]
        for change in mutations:
            value = decoded()
            change(value)
            with self.assertRaises(ValueError):
                H["validate_decode"](json.dumps(value), 60, 0, 0)

    def test_same_descriptor_input_rejects_symlink_hardlink_mode_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"input"
            path.write_bytes(b"input")
            path.chmod(0o600)
            self.assertEqual(H["read_file"](path), b"input")
            with self.assertRaises(ValueError): H["read_file"](path, 4)
            path.chmod(0o666)
            with self.assertRaises(ValueError): H["read_file"](path)
            path.chmod(0o600)
            link = Path(directory)/"link"
            link.symlink_to(path)
            with self.assertRaises(OSError): H["read_file"](link)
            link.unlink()
            os.link(path, link)
            with self.assertRaises(ValueError): H["read_file"](path)

    def test_toolchain_manifest_requires_captured_hash_and_closed_tool_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"toolchain.json"
            path.write_text(json.dumps(toolchain()))
            with self.assertRaisesRegex(ValueError, "TOOLCHAIN_PIN_REQUIRED"):
                H["load_toolchain"](path, None)
            with self.assertRaisesRegex(ValueError, "TOOLCHAIN_PIN_MISMATCH"):
                H["load_toolchain"](path, "0"*64)
            value = toolchain()
            del value["tools"]["cc1plus"]
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "TOOLCHAIN_SCHEMA"):
                H["load_toolchain"](path, H["sha"](path.read_bytes()))
            path.write_text('{"schema":1,"schema":1}')
            with self.assertRaisesRegex(ValueError, "DUPLICATE_KEY"):
                H["load_toolchain"](path, H["sha"](path.read_bytes()))

    def test_existing_output_or_unpinned_toolchain_never_starts_build(self):
        with patch.object(os, "geteuid", return_value=1000), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("must not execute")):
            with self.assertRaisesRegex(ValueError, "NEW_PRIVATE_OUTPUT_REQUIRED"):
                H["build"](Path("/tmp"), ROOT, Path("/missing"), "0"*64)
            with self.assertRaisesRegex(ValueError, "NEW_PRIVATE_OUTPUT_REQUIRED"):
                H["build"](Path("/tmp"), Path("/tmp/hosted-decoder-test"), Path("/missing"), "0"*64)

    def test_output_is_exclusive_private_and_rejects_unsafe_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)/"build"
            output = parent/"hosted-decoder-test"
            H["create_output"](output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output/"bin/date").stat().st_mode & 0o777, 0o700)
            with self.assertRaises(FileExistsError): H["create_output"](output)
            parent.chmod(0o777)
            with self.assertRaisesRegex(ValueError, "UNSAFE_OUTPUT_PARENT"):
                H["create_output"](parent/"hosted-decoder-other")
            parent.chmod(0o700)

    def test_capture_has_fixed_tool_selection_and_no_decoder_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            versions = []
            def fake_record(path):
                return dict(path=str(path), bytes=4, sha256=H["sha"](b"tool"), version_sha256=None)
            def fake_program(output, tools, name, driver, program, deadline):
                calls.append((name, driver, program))
                return Path("/usr/bin")/name, {}
            def fake_run(output, tools, name, command, deadline, maximum):
                key = name.removeprefix("version-")
                self.assertEqual(command, [tools[key]["path"], *H["VERSION_ARGS"][key]])
                versions.append(command)
                return dict(log_sha256=H["sha"](b"version\n"))
            def read_manifest(path, expected):
                self.assertEqual(H["sha"](path.read_bytes()), expected)
                return json.loads(path.read_bytes())
            with patch.object(os, "geteuid", return_value=1000), \
                    patch.dict(H["capture_toolchain"].__globals__, ROOT=Path(directory),
                        tool_record=fake_record, captured_program=fake_program,
                        run_step=fake_run, load_toolchain=read_manifest), \
                    patch.object(H["shutil"], "which", side_effect=lambda name, path: "/usr/bin/"+name):
                value = H["capture_toolchain"](Path(directory)/"build/hosted-toolchain-test")
            self.assertEqual(calls, list(H["COMPILER_PROGRAMS"]))
            manifest = json.loads(Path(value["toolchain_manifest"]).read_bytes())
            self.assertEqual(set(manifest["tools"]), H["TOOLS"])
            self.assertIn(["/usr/bin/mawk", "-W", "version"], versions)
            self.assertEqual(manifest["tools"]["mawk"], dict(path="/usr/bin/mawk", bytes=4,
                sha256=H["sha"](b"tool"), version_sha256=H["sha"](b"version\n")))
            self.assertTrue(manifest["provenance_only"])
            self.assertFalse(value["compiled"])
            self.assertFalse(value["decoder_authorized"])

    def test_mawk_manifest_requires_canonical_binary_bytes_and_version(self):
        manifest_path = Path("/private/toolchain.json")
        value = toolchain()
        def load(value):
            raw = json.dumps(value).encode()
            def read(path, *_args):
                return raw if path == manifest_path else b"tool"
            with patch.dict(H["load_toolchain"].__globals__, read_file=read, platform=lambda: value["platform"]), \
                    patch.object(Path, "resolve", lambda path: path), \
                    patch.object(Path, "stat", return_value=SimpleNamespace(st_mode=0o100755)):
                return H["load_toolchain"](manifest_path, H["sha"](raw))
        self.assertEqual(load(value), value)
        for field, bad, code in (("path", "/usr/bin/awk", "MAWK_PATH_CHANGED"),
                ("sha256", "0"*64, "TOOLCHAIN_BINARY_MISMATCH"),
                ("bytes", 5, "TOOLCHAIN_BINARY_MISMATCH"),
                ("version_sha256", None, "TOOLCHAIN_VERSION_PIN")):
            changed = json.loads(json.dumps(value))
            changed["tools"]["mawk"][field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code): load(changed)
        del value["tools"]["mawk"]
        with self.assertRaisesRegex(ValueError, "TOOLCHAIN_SCHEMA"): load(value)

    def test_private_awk_alias_is_exclusive_fixed_and_checked_after_build(self):
        tools = toolchain()["tools"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"build/hosted-decoder-test"
            H["create_output"](output)
            H["create_awk_alias"](output, tools)
            alias = output/"bin/awk"
            self.assertEqual(os.readlink(alias), "/usr/bin/mawk")
            self.assertEqual(H["verify_awk_alias"](output, tools), {"/build/bin/awk": "/usr/bin/mawk"})
            self.assertEqual(H["ENV"]["PATH"].split(":")[0], "/build/bin")
            with self.assertRaises(FileExistsError): H["create_awk_alias"](output, tools)
            alias.unlink()
            alias.symlink_to("/usr/bin/awk")
            with self.assertRaisesRegex(ValueError, "AWK_ALIAS_CHANGED"): H["verify_awk_alias"](output, tools)
            alias.unlink()
            alias.write_text("replacement")
            with self.assertRaisesRegex(ValueError, "AWK_ALIAS_CHANGED"): H["verify_awk_alias"](output, tools)
            alias.unlink()
            tools["mawk"]["path"] = "/etc/alternatives/awk"
            with self.assertRaisesRegex(ValueError, "MAWK_PATH_CHANGED"): H["create_awk_alias"](output, tools)
            self.assertFalse(alias.exists())

    def test_build_rechecks_mawk_version_with_its_actual_flag(self):
        calls = []
        def step(output, tools, name, command, deadline, maximum):
            calls.append(command)
            self.assertEqual((deadline, maximum), (123, 16384))
            return dict(step=name, log_sha256=H["sha"](b"version\n"))
        tools = toolchain()["tools"]
        with patch.dict(H["verify_tool_versions"].__globals__, run_step=step, read_file=lambda *_args: b"version\n"):
            steps, versions = H["verify_tool_versions"](Path("/private/output"), tools, 123)
            self.assertEqual(len(steps), len(H["VERSION_ARGS"]))
            self.assertEqual(versions["mawk"], "version\n")
            self.assertIn(["/usr/bin/mawk", "-W", "version"], calls)
            tools["mawk"]["version_sha256"] = "0"*64
            with self.assertRaisesRegex(ValueError, "TOOLCHAIN_VERSION_MISMATCH"):
                H["verify_tool_versions"](Path("/private/output"), tools, 123)

    def run_inert(self, directory, code, *, maximum=1024, seconds=2):
        def command(_output, _tools, argv):
            return [sys.executable, "-c", code, "--", *argv]
        with patch.dict(H["run_step"].__globals__, sandbox=command):
            return H["run_step"](Path(directory), {}, "inert", ["inert-test"], time.monotonic()+seconds, maximum)

    def test_step_status_requires_actual_success_and_bounded_output(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.run_inert(directory, "print('ok')")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["log_sha256"], H["sha"](b"ok\n"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "BUILD_STEP_FAILED"):
                self.run_inert(directory, "raise SystemExit(7)")
            self.assertFalse((Path(directory)/"hosted-build-receipt.json").exists())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "BUILD_OUTPUT_BOUND"):
                self.run_inert(directory, "print('x'*2000)", maximum=1024)
            self.assertLessEqual((Path(directory)/"inert.log").stat().st_size, 1024)

    def test_deadline_kills_and_reaps_only_owned_inert_process(self):
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "BUILD_DEADLINE"):
                self.run_inert(directory, "import time; time.sleep(10)", seconds=0.05)
            self.assertLess(time.monotonic()-started, 2)
            self.assertFalse((Path(directory)/"hosted-build-receipt.json").exists())

    def test_cli_sigterm_unwinds_actual_inert_child_and_restores_handler(self):
        # Execute Python only, never bwrap/compiler/decoder. The real CLI signal
        # handler must reach the real run_step finally and reap its child.
        code = r'''
import os, runpy, signal, subprocess, sys, threading, time
from pathlib import Path
h = runpy.run_path(sys.argv[1])
g = h['cli'].__globals__
real_popen = subprocess.Popen
children = []
def popen(*args, **kwargs):
    child = real_popen(*args, **kwargs)
    children.append(child)
    return child
g['sandbox'] = lambda output, tools, argv: [sys.executable, '-c', 'import time; time.sleep(10)', '--', *argv]
g['subprocess'].Popen = popen
def main():
    timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        return h['run_step'](Path(sys.argv[2]), {}, 'inert', ['fixture'], time.monotonic()+5)
    finally:
        timer.cancel()
        timer.join()
g['main'] = main
before = signal.getsignal(signal.SIGTERM)
try:
    h['cli']()
except h['BuildInterrupted']:
    pass
else:
    raise AssertionError('signal not propagated')
assert signal.getsignal(signal.SIGTERM) == before
assert len(children) == 1 and children[0].poll() is not None
assert children[0].stdout.closed
print('owned-child-reaped')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT/"scripts/prepare_hosted_decoder.py"), directory],
                                    capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"owned-child-reaped\n")

    def test_cli_reports_cleanup_uncertainty_distinct_from_ordinary_failure(self):
        with patch.object(sys, "argv", ["recipe", "plan"]), patch.dict(H["main"].__globals__,
                plan=Mock(side_effect=H["CleanupUnconfirmed"]("unconfirmed"))):
            self.assertEqual(H["main"](), 125)

    def test_cli_emits_bounded_fixed_diagnostic_without_exception_or_path_details(self):
        canary = '/private/secret-argv-or-stderr'
        errors = (
            (ValueError('DEVELOPMENT_SSL_DATA_LINK'), 'ValueError', 'DEVELOPMENT_SSL_DATA_LINK'),
            (ValueError(canary), 'ValueError', 'PREPARATION_FAILED'),
            (OSError(2, canary, canary), 'OSError', 'PREPARATION_FAILED'),
            (KeyError(canary), 'KeyError', 'PREPARATION_FAILED'),
            (TypeError(canary), 'TypeError', 'PREPARATION_FAILED'),
            (subprocess.CalledProcessError(7, [canary], output=canary, stderr=canary),
                'SubprocessError', 'PREPARATION_FAILED'),
            (subprocess.TimeoutExpired([canary], 1, output=canary, stderr=canary),
                'SubprocessError', 'PREPARATION_FAILED'),
        )
        for error, category, code in errors:
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(error=type(error).__name__), \
                    patch.object(sys, 'argv', ['recipe', 'capture-source-toolchain', '--output-dir', canary]), \
                    patch.object(sys, 'stdout', stdout), patch.object(sys, 'stderr', stderr), \
                    patch.dict(H['main'].__globals__, capture_source_toolchain=Mock(side_effect=error)):
                self.assertEqual(H['main'](), 1)
            lines = stderr.getvalue().splitlines()
            self.assertEqual(lines[0], 'HOSTED_DECODER_PREPARATION_FAILED')
            self.assertEqual(len(lines), 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn(canary, stderr.getvalue())
            self.assertLess(len(lines[1]), 256)
            self.assertEqual(json.loads(lines[1]), dict(schema=1, kind='hosted-decoder-preparation-failure',
                action='capture-source-toolchain', category=category, code=code))

    def test_diagnostic_code_and_category_are_closed_even_for_custom_exception_text(self):
        class CustomValueError(ValueError):
            def __str__(self):
                raise AssertionError('exception text must not be inspected')
        for error in (ValueError('lowercase'), ValueError('BAD-CODE'), ValueError('CODE\n'),
                      ValueError('A' * 65), ValueError('CODE', '/private/path'), ValueError(42)):
            with self.subTest(args=error.args):
                self.assertEqual(H['preparation_failure']('build-source', error)['code'], 'PREPARATION_FAILED')
        self.assertEqual(H['preparation_failure']('build-source', ValueError('A' * 64))['code'], 'A' * 64)
        diagnostic = H['preparation_failure']('/private/action', CustomValueError('CODE_2'))
        self.assertEqual(diagnostic['category'], 'ValueError')
        self.assertEqual(diagnostic['action'], 'unknown')
        self.assertEqual(diagnostic['code'], 'CODE_2')

    def test_cli_interruption_and_unconfirmed_cleanup_keep_original_exit_and_marker(self):
        for error, code, marker in ((H['BuildInterrupted']('private detail'), 130, 'DECODER_BUILD_INTERRUPTED'),
                                   (H['CleanupUnconfirmed']('private detail'), 125, 'DECODER_CLEANUP_UNCONFIRMED')):
            stderr = io.StringIO()
            with self.subTest(code=code), patch.object(sys, 'argv', ['recipe', 'plan']), \
                    patch.object(sys, 'stderr', stderr), \
                    patch.dict(H['main'].__globals__, plan=Mock(side_effect=error)):
                self.assertEqual(H['main'](), code)
            self.assertEqual(stderr.getvalue(), marker + '\n')

    def test_signal_first_arriving_during_join_or_close_is_cleanup_unconfirmed(self):
        for location in ("wait", "close"):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                child = Mock(pid=123)
                child.wait.side_effect = ([0, H["BuildInterrupted"]("during cleanup")] if location == "wait" else [0, 0])
                if location == "close": child.stdout.close.side_effect = H["BuildInterrupted"]("during close")
                selector = Mock()
                selector.__enter__ = Mock(return_value=selector)
                selector.__exit__ = Mock(return_value=False)
                selector.get_map.return_value = {}
                with patch.object(subprocess, "Popen", return_value=child), patch.object(H["selectors"], "DefaultSelector", return_value=selector), \
                        patch.object(os, "killpg"), patch.dict(H["run_step"].__globals__, sandbox=lambda _out, _tools, argv: ["--", *argv]):
                    with self.assertRaises(H["CleanupUnconfirmed"]):
                        H["run_step"](Path(directory), {}, "inert", ["inert"], time.monotonic()+2)


if __name__ == "__main__":
    unittest.main()
