# SPDX-License-Identifier: GPL-3.0-only
"""Inert archive/contract tests: no Android/Java/Flutter process is executed."""
import hashlib
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import signal
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

M = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/prepare_hosted_android.py"))


def archive(items):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, raw, mode in items:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            z.writestr(info, raw)
    out.seek(0)
    return out


class AndroidInputs(unittest.TestCase):
    def extract(self, items):
        with tempfile.TemporaryDirectory() as root:
            return M["extract"](archive(items), Path(root) / "sdk")

    def test_exact_official_pins(self):
        p = M["pins"]()
        self.assertEqual(len(p), 11)
        self.assertEqual(p["gradle"]["algorithm"], "sha256")
        self.assertEqual(p["system-image"]["destination"], "sdk/system-images/android-36/default/x86_64")
        self.assertTrue(all(v["algorithm"] == "sha1" and v["url"].startswith(M["GOOGLE"])
            for k, v in p.items() if k != "gradle"))
        self.assertEqual(p["ndk"]["revision"], "28.2.13676358")

    def test_cmake_is_one_exact_official_rootless_input(self):
        pins = M["pins"]()
        self.assertEqual(pins["cmake"], dict(url=M["GOOGLE"] + "cmake-3.22.1-linux.zip",
            bytes=22308647, algorithm="sha1", digest="fd0a48b4a758310df8c7aa51f59840ed48fe7ed8",
            destination="sdk/cmake/3.22.1", revision="3.22.1", checksum_source=M["REPOSITORY"],
            archive_layout="cmake-3.22.1"))
        self.assertEqual([name for name, pin in pins.items() if "archive_layout" in pin], ["cmake"])

    def test_cmake_real_materialization_preserves_tools_notices_and_readonly_inventory(self):
        # Model the observed official ZIP's rootless layout with inert bytes.
        # The real download/hash/extract/revision/inventory path runs, no tool does.
        data = archive([
            ("source.properties", b"Pkg.Revision = 3.22.1\nPkg.Path = cmake;3.22.1\nPkg.Desc = CMake 3.22.1\n", 0o600),
            ("bin/cmake", b"inert CMake", 0o100755),
            ("bin/ninja", b"inert Ninja", 0o100755),
            ("doc/ninja/LICENSE", b"original Ninja notice", 0o100644),
            ("share/cmake-3.22/Modules/fixture.cmake", b"inert module", 0o100644),
        ]).getvalue()
        pin = dict(M["pins"]()["cmake"], bytes=len(data), digest=hashlib.sha1(data).hexdigest())
        class Response(io.BytesIO):
            status = 200
            headers = {"Content-Length": str(len(data))}
        class Opener:
            def open(self, url, timeout):
                return Response(data)
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            old_umask = os.umask(0o077)
            try:
                with patch.dict(M["materialize"].__globals__, pins=lambda: {"cmake": pin}), \
                        patch.object(M["urllib"].request, "build_opener", return_value=Opener()):
                    report = M["materialize"](output)
                    self.assertEqual(report["files"], 5)
                    self.assertFalse(report["runtime_executed"])
                    sdk = output / pin["destination"]
                    self.assertEqual((sdk / "bin/cmake").read_bytes(), b"inert CMake")
                    self.assertEqual(stat.S_IMODE((sdk / "bin/ninja").stat().st_mode), 0o700)
                    self.assertEqual((sdk / "doc/ninja/LICENSE").read_bytes(), b"original Ninja notice")
                    provenance = json.loads((output / "provenance.json").read_bytes())
                    self.assertEqual(provenance["inputs"]["cmake"],
                        dict(pin, observed_sha256=hashlib.sha256(data).hexdigest()))
                    self.assertFalse((output / ".cmake.zip").exists())
                    (sdk / "bin/cmake").write_bytes(b"changed")
                    with self.assertRaisesRegex(ValueError, "TREE_BYTES"):
                        M["verify"](output)
            finally:
                os.umask(old_umask)

    def test_cmake_layout_is_not_an_unrestricted_rootless_archive_policy(self):
        items = [("source.properties", b"Pkg.Revision=3.22.1\n", 0o600),
            ("bin/cmake", b"inert", 0o100755), ("doc/LICENSE", b"notice", 0o100644),
            ("share/module", b"inert", 0o100644)]
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "sdk"
            with self.assertRaisesRegex(ValueError, "ARCHIVE_ROOT"):
                M["extract"](archive(items), output)
            for extra in (("unexpected/file", b"inert", 0o100644),
                    ("bin/../../escape", b"inert", 0o100644),
                    ("bin/fifo", b"", 0o010600),
                    ("bin/escape", b"../../outside", 0o120777)):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    M["extract"](archive(items + [extra]), output, layout="cmake-3.22.1")
                self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, "ARCHIVE_LAYOUT"):
                M["extract"](archive(items), output, layout="arbitrary-rootless")

    def test_digest_failure_records_actual_short_or_wrong_bytes_without_extracting(self):
        expected = b"original inert bytes"
        for received in (expected[:-3], b"x" * len(expected)):
            with self.subTest(received=received), tempfile.TemporaryDirectory() as root:
                output = Path(root)
                pin = dict(M["pins"]()["platform"], bytes=len(expected), digest=hashlib.sha1(expected).hexdigest())
                class Response(io.BytesIO):
                    status = 200
                    headers = {"Content-Length": str(len(expected)), "private-header": "not-exported"}
                class Opener:
                    requests = 0
                    def open(self, url, timeout):
                        self.requests += 1
                        return Response(received)
                opener = Opener()
                with patch.dict(M["materialize"].__globals__, pins=lambda: {"platform": pin}), \
                        patch.object(M["urllib"].request, "build_opener", return_value=opener), \
                        patch.dict(M["materialize"].__globals__, extract=unittest.mock.Mock()) as scope:
                    with self.assertRaisesRegex(M["ArchiveDigestError"], "^ARCHIVE_DIGEST$"):
                        M["materialize"](output)
                    scope["extract"].assert_not_called()
                self.assertEqual(opener.requests, 1)
                receipt = output / "download-failure.json"
                self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
                raw = receipt.read_bytes()
                self.assertLessEqual(len(raw), 1024)
                self.assertEqual(json.loads(raw), dict(schema=1, kind="hosted-android-download-failure",
                    code="ARCHIVE_DIGEST", package="platform", algorithm="sha1",
                    expected_bytes=len(expected), received_bytes=len(received),
                    expected_digest=hashlib.sha1(expected).hexdigest(), observed_digest=hashlib.sha1(received).hexdigest(),
                    observed_sha256=hashlib.sha256(received).hexdigest(), archive_accepted=False, runtime_executed=False))
                self.assertNotIn(b"http", raw)
                self.assertNotIn(b"not-exported", raw)
                self.assertEqual((output / ".platform.zip").read_bytes(), received)
                self.assertFalse((output / "provenance.json").exists())
                self.assertFalse((output / "sdk").exists())

    def test_digest_diagnostic_failure_never_replaces_rejection(self):
        pin = M["pins"]()["platform"]
        error = M["ArchiveDigestError"](1, "a" * 40, "b" * 64)
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            existing = output / "download-failure.json"
            existing.write_bytes(b"existing receipt remains unchanged")
            with patch.dict(M["materialize"].__globals__, pins=lambda: {"platform": pin},
                    download=unittest.mock.Mock(side_effect=error), extract=unittest.mock.Mock()) as scope:
                with self.assertRaises(M["ArchiveDigestError"]) as caught:
                    M["materialize"](output)
                self.assertIs(caught.exception, error)
                scope["extract"].assert_not_called()
                scope["download"].assert_called_once()
            self.assertEqual(existing.read_bytes(), b"existing receipt remains unchanged")

    def test_download_failure_receipt_only_admits_fixed_labels_pins_and_closed_hashes(self):
        pin = M["pins"]()["platform"]
        for name, candidate, size, digest, sha256 in (
                ("url?secret", pin, 1, "a" * 40, "b" * 64),
                ("platform", dict(pin, digest="c" * 40), 1, "a" * 40, "b" * 64),
                ("platform", pin, True, "a" * 40, "b" * 64),
                ("platform", pin, pin["bytes"] + 1, "a" * 40, "b" * 64),
                ("platform", pin, pin["bytes"], pin["digest"], "b" * 64),
                ("platform", pin, 1, "private body", "b" * 64),
                ("platform", pin, 1, "a" * 40, "b" * 65),
                ("gradle", M["pins"]()["gradle"], 1, "a" * 64, "b" * 64)):
            with self.subTest(name=name, size=size), tempfile.TemporaryDirectory() as root:
                output = Path(root)
                with self.assertRaises(ValueError):
                    M["save_download_failure"](output, name, candidate, M["ArchiveDigestError"](size, digest, sha256))
                self.assertFalse((output / "download-failure.json").exists())

    def test_gradle_failure_uses_sha256_identity_not_an_assumed_google_package(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            M["save_download_failure"](output, "gradle", M["pins"]()["gradle"],
                M["ArchiveDigestError"](10, "a" * 64, "a" * 64))
            value = json.loads((output / "download-failure.json").read_bytes())
            self.assertEqual(value["package"], "gradle")
            self.assertEqual(value["algorithm"], "sha256")
            self.assertEqual(value["expected_digest"], M["GRADLE"]["digest"])

    def test_locked_plugin_platforms_have_independent_official_archive_pins(self):
        pins = M["pins"]()
        expected = {
            "platform-34": ("platform-34-ext7_r03.zip", 63180081, "1f2e9478d6a7601425ceaa553311dc43191f103d", "3"),
            "platform-35": ("platform-35_r02.zip", 64273788, "0bb560a90a7a2cbd0dd8348224d518b638fe7949", "2"),
        }
        for name, (archive_name, size, sha1, revision) in expected.items():
            self.assertEqual(pins[name], dict(url=M["GOOGLE"] + archive_name, bytes=size,
                algorithm="sha1", digest=sha1, destination="sdk/platforms/android-" + name[-2:],
                revision=revision, checksum_source=M["REPOSITORY"]))
        self.assertEqual({pins[name]["destination"] for name in ("platform", *expected)},
            {"sdk/platforms/android-34", "sdk/platforms/android-35", "sdk/platforms/android-36"})
        self.assertEqual(pins["platform"]["digest"], "2c1a80dd4d9f7d0e6dd336ec603d9b5c55a6f576")

    def test_multiple_platform_archives_remain_separate_verified_inputs_with_notices(self):
        # Tiny inert archives use the real acquisition/hash/extract/verify path.
        # No Google archive, SDK program or Gradle auto-install is executed.
        inputs, payloads = {}, {}
        for name in ("platform", "platform-34", "platform-35"):
            pin = M["pins"]()[name]
            raw = archive([("fixture/source.properties", ("Pkg.Revision=" + pin["revision"] + "\n").encode(), 0o100644),
                ("fixture/android.jar", ("inert " + name).encode(), 0o100644),
                ("fixture/NOTICE.txt", b"original fixture notice", 0o100644)]).getvalue()
            inputs[name] = dict(pin, bytes=len(raw), digest=hashlib.sha1(raw).hexdigest())
            payloads[pin["url"]] = raw
        class Response(io.BytesIO):
            status = 200
            def __init__(self, raw):
                super().__init__(raw)
                self.headers = {"Content-Length": str(len(raw))}
        class Opener:
            def open(self, url, timeout):
                return Response(payloads[url])
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "output"
            output.mkdir(mode=0o700)
            old_umask = os.umask(0o077)
            try:
                with patch.dict(M["materialize"].__globals__, pins=lambda: inputs), \
                        patch.object(M["urllib"].request, "build_opener", return_value=Opener()):
                    result = M["materialize"](output)
                    self.assertFalse(result["runtime_executed"])
                    self.assertEqual(result["files"], 9)
                    provenance = json.loads((output / "provenance.json").read_bytes())
                    self.assertEqual(set(provenance["inputs"]), set(inputs))
                    self.assertFalse(provenance["independent_sha256_authority"])
                    for name, pin in inputs.items():
                        self.assertEqual((output / pin["destination"] / "android.jar").read_bytes(), ("inert " + name).encode())
                        self.assertEqual((output / pin["destination"] / "NOTICE.txt").read_bytes(), b"original fixture notice")
                    (output / inputs["platform-34"]["destination"] / "android.jar").unlink()
                    with self.assertRaisesRegex(ValueError, "TREE_CLOSURE"):
                        M["verify"](output)
            finally:
                os.umask(old_umask)

    def test_extract_preserves_license_and_mode(self):
        result = self.extract([("root/bin/tool", b"inert", 0o100755), ("root/LICENSE", b"original", 0o100644)])
        self.assertEqual(result["bin/tool"]["mode"], 0o700)
        self.assertEqual(result["LICENSE"]["sha256"], hashlib.sha256(b"original").hexdigest())

    def test_safe_internal_links(self):
        result = self.extract([("root/bin/tool", b"inert", 0o100755), ("root/bin/alias", b"tool", 0o120777)])
        self.assertEqual(result["bin/alias"], dict(kind="link", target="tool"))

    def test_no_escape_or_cycle(self):
        for target in ("../../outside", "/etc/passwd", "alias", "absent"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.extract([("root/bin/alias", target.encode(), 0o120777)])

    def test_no_link_as_write_parent(self):
        with self.assertRaises(ValueError):
            self.extract([("root/real/", b"", 0o40755), ("root/a", b"real", 0o120777), ("root/a/file", b"x", 0o100644)])

    def test_malformed_paths_types_roots(self):
        for items in ([('root/../bad', b'x', 0o100644)], [('root/fifo', b'', 0o010600)],
            [('root/a', b'x', 0o104755)], [('root/a', b'x', 0o100644), ('other/b', b'x', 0o100644)],
            [('root/a', b'x', 0o100644), ('root/a', b'x', 0o100644)]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                self.extract(items)

    def test_entry_and_expansion_bounds(self):
        scope = M["extract"].__globals__
        with patch.dict(scope, MAX_MEMBERS=1), self.assertRaises(ValueError):
            self.extract([('root/a', b'x', 0o100644), ('root/b', b'x', 0o100644)])
        with patch.dict(scope, MAX_EXPANDED=1), self.assertRaises(ValueError):
            self.extract([('root/a', b'xx', 0o100644)])

    def test_redirects_do_not_authorize_arbitrary_hosts(self):
        handler = M["Redirects"](M["GOOGLE"] + "platform-36_r02.zip")
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, '', {}, 'https://example.com/x')
        handler = M["Redirects"](M["GRADLE"]["url"])
        for value in ('http://release-assets.githubusercontent.com/a', 'https://evil.github.com/a',
                      'https://user:password@release-assets.githubusercontent.com/a'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, '', {}, value)

    def test_inventory_bytes_links_and_extra_file(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "output"
            root.mkdir(mode=0o700)
            raw = b"not executable"
            (root / "tool").write_bytes(raw)
            (root / "tool").chmod(0o600)
            record = dict(kind="file", bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), mode=0o600)
            inv = M["canonical"]({"tool": record})
            (root / "inventory.json").write_bytes(inv)
            value = dict(schema=1, kind="hosted-android-materialization", inputs={}, files=1,
                inventory_sha256=hashlib.sha256(inv).hexdigest(), runtime_executed=False, independent_sha256_authority=False)
            (root / "provenance.json").write_bytes(M["canonical"](value))
            for path in root.iterdir():
                path.chmod(0o600)
            with patch.dict(M["verify"].__globals__, pins=lambda: {}):
                self.assertFalse(M["verify"](root)["runtime_executed"])
                (root / "tool").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "TREE_BYTES"):
                    M["verify"](root)
                (root / "tool").write_bytes(raw)
                (root / "extra").write_bytes(b"x")
                with self.assertRaisesRegex(ValueError, "TREE_CLOSURE"):
                    M["verify"](root)

    def test_actual_orchestration_uses_sequential_clipped_alarms(self):
        # Tiny inert bytes through the REAL download/extract/verify flow; the
        # opener is fake, no Android archive or executable is acquired/run.
        data = archive([("fixture/source.properties", b"Pkg.Revision=1\n", 0o100644),
                        ("fixture/LICENSE", b"unchanged fixture notice", 0o100644)]).getvalue()
        gradle = b"inert distribution fixture"
        pin = dict(url="https://dl.google.com/android/repository/inert.zip", bytes=len(data),
            algorithm="sha1", digest=hashlib.sha1(data).hexdigest(), destination="sdk/inert", revision="1", checksum_source="fixture")
        gp = dict(url="https://services.gradle.org/distributions/inert.zip", bytes=len(gradle),
            algorithm="sha256", digest=hashlib.sha256(gradle).hexdigest(), checksum_source="fixture")
        observed = []
        original_deadline = M["deadline"]
        @contextmanager
        def measured(seconds):
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
            observed.append(seconds)
            with original_deadline(seconds):
                yield
        class Response(io.BytesIO):
            status = 200
            def __init__(self, raw):
                super().__init__(raw)
                self.headers = {"Content-Length": str(len(raw))}
        class Opener:
            def open(self, url, timeout):
                self_timer = signal.getitimer(signal.ITIMER_REAL)[0]
                if not 0 < self_timer <= 600:
                    raise AssertionError("real download alarm not armed")
                return Response(data if url == pin["url"] else gradle)
        handler = signal.getsignal(signal.SIGALRM)
        globals_ = M["materialize"].__globals__
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            (root / "build").mkdir(mode=0o700)
            out = root / "build/output"
            old_umask = os.umask(0o077)
            try:
                with patch.dict(globals_, ROOT=root, pins=lambda: {"fixture": pin, "gradle": gp}, deadline=measured), \
                        patch.object(M["urllib"].request, "build_opener", return_value=Opener()), \
                        patch.object(M["time"], "monotonic", side_effect=[100, 200, 400, 2490, 2499]), \
                        patch("sys.argv", ["prepare", "--fetch", "--output", str(out)]), redirect_stdout(io.StringIO()) as printed:
                    M["main"]()
                self.assertFalse(json.loads(printed.getvalue())["runtime_executed"])
                self.assertEqual(observed, [600, 240, 10, 1])
                self.assertEqual((out / "sdk/inert/LICENSE").read_bytes(), b"unchanged fixture notice")
                self.assertFalse((out / ".fixture.zip").exists())
            finally:
                os.umask(old_umask)
        self.assertEqual(signal.getsignal(signal.SIGALRM), handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_old_nested_alarm_reproduces_actual_hosted_failure(self):
        with tempfile.TemporaryDirectory() as parent, M["deadline"](2400):
            with self.assertRaisesRegex(ValueError, "outer process alarm is already active"):
                # Guard fails before any opener request, precisely as hosted.
                M["download"](M["GRADLE"], Path(parent) / "inert.zip")
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_expired_whole_budget_prevents_next_phase(self):
        with patch.object(M["time"], "monotonic", return_value=100):
            for end in (99, 100):
                with self.subTest(end=end), self.assertRaisesRegex(ValueError, "MATERIALIZATION_DEADLINE"):
                    M["phase_budget"](end, 600)
            self.assertEqual(M["phase_budget"](105, 600), 5)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_real_alarm_expiration_restores_original_handler(self):
        handler = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError), M["deadline"](0.01):
            time.sleep(0.03)
        self.assertEqual(signal.getsignal(signal.SIGALRM), handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_download_failure_also_restores_alarm(self):
        handler = signal.getsignal(signal.SIGALRM)
        class Failing:
            def open(self, *args, **kwargs):
                raise OSError("inert network failure")
        with tempfile.TemporaryDirectory() as parent, patch.object(M["urllib"].request, "build_opener", return_value=Failing()), \
                self.assertRaises(OSError):
            M["download"](M["GRADLE"], Path(parent) / "inert.zip", seconds=1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
