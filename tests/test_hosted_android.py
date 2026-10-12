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
        self.assertEqual(len(p), 8)
        self.assertEqual(p["gradle"]["algorithm"], "sha256")
        self.assertEqual(p["system-image"]["destination"], "sdk/system-images/android-36/default/x86_64")
        self.assertTrue(all(v["algorithm"] == "sha1" and v["url"].startswith(M["GOOGLE"])
            for k, v in p.items() if k != "gradle"))
        self.assertEqual(p["ndk"]["revision"], "28.2.13676358")

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
