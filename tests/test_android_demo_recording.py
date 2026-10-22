#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert recording contracts and owned child I/O; no Android or network."""
import io
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/record_android_demo.py"))
G = M["Recording"].read.__globals__


class Pixels(unittest.TestCase):
    def test_checked_file_hash_rejects_symlink_hardlink_and_mode(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / "screen.png"; p.write_bytes(b"pixels"); p.chmod(0o600)
            self.assertEqual(M["fingerprint"](p, 6)["bytes"], 6)
            with self.assertRaises(ValueError): M["fingerprint"](p, 5)
            p.chmod(0o644)
            with self.assertRaises(ValueError): M["fingerprint"](p, 6)
            p.chmod(0o600); link = p.with_name("link"); link.symlink_to(p)
            with self.assertRaises(OSError): M["fingerprint"](link, 6)
            link.unlink(); os.link(p, link)
            with self.assertRaises(ValueError): M["fingerprint"](p, 6)

    def child(self, program):
        return subprocess.Popen([sys.executable, "-B", "-c", program], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_bounded_binary_transfer_and_exact_child_join(self):
        with tempfile.TemporaryDirectory() as name:
            child = self.child("import sys; sys.stdout.buffer.write(b'abc'*100)")
            recorder = M["Recording"]("/unused", name)
            with patch.object(G["subprocess"], "Popen", return_value=child):
                recorder.read(["exec-out", "unused"], 300, Path(name) / "pixels")
            self.assertEqual((Path(name) / "pixels").read_bytes(), b"abc" * 100)
            self.assertEqual(stat.S_IMODE((Path(name) / "pixels").stat().st_mode), 0o600)
            self.assertEqual(child.returncode, 0); self.assertTrue(child.stdout.closed)

    def test_oversized_output_kills_and_joins_instead_of_allocating(self):
        with tempfile.TemporaryDirectory() as name:
            child = self.child("import os;\nwhile True: os.write(1,b'x'*65536)")
            with patch.object(G["subprocess"], "Popen", return_value=child):
                with self.assertRaises(ValueError): M["Recording"]("/unused", name).read(["unused"], 32)
            self.assertIsNotNone(child.returncode); self.assertTrue(child.stderr.closed)

    def test_deadline_kills_and_joins(self):
        child = self.child("import time; time.sleep(20)")
        with patch.object(G["subprocess"], "Popen", return_value=child):
            with self.assertRaises(ValueError): M["Recording"]("/unused", "/unused").read(["unused"], seconds=0.01)
        self.assertIsNotNone(child.returncode)

    def test_process_failure_never_becomes_media(self):
        child = self.child("raise SystemExit(2)")
        with patch.object(G["subprocess"], "Popen", return_value=child):
            with self.assertRaises(ValueError): M["Recording"]("/unused", "/unused").read(["unused"])
        self.assertEqual(child.returncode, 2)

    def test_only_exact_owned_guest_recorder_is_signalled(self):
        from types import SimpleNamespace
        recorder = M["Recording"]("/unused", "/unused")
        calls = []
        child = SimpleNamespace(returncode=None, stdout=io.BytesIO())
        child.poll = lambda: child.returncode
        child.kill = lambda: setattr(child, "returncode", -9)
        child.wait = lambda **_: child.returncode
        recorder.process = child; recorder.pid = 42
        recorder.read = lambda args, **_: calls.append(args) or b"unrelated\0"
        with self.assertRaises(ValueError): recorder.stop()
        self.assertEqual(calls, [["shell", "cat", "/proc/42/cmdline"]])
        self.assertEqual(child.returncode, -9)

    def test_screenshot_is_real_png_and_has_no_invented_stage(self):
        import time
        with tempfile.TemporaryDirectory() as name:
            recorder = M["Recording"]("/unused", name); recorder.started = time.monotonic()
            def read(args, maximum, destination):
                self.assertEqual(args, ["exec-out", "/system/bin/screencap", "-p"])
                Path(destination).write_bytes(M["PNG"] + b"pixels"); Path(destination).chmod(0o600)
            recorder.read = read; recorder.screenshot()
            self.assertEqual(recorder.shots[0]["stage"], "unclassified")
            self.assertEqual(list(recorder.files), ["screen-001.png"])

    def test_capture_is_default_off_and_original_driver_is_unchanged(self):
        source = (ROOT / "scripts/prepare_hosted_android_ci.py").read_text()
        self.assertIn('record_demo=False', source)
        self.assertIn('if record_demo:', source)
        self.assertIn('record_demo=len(sys.argv) == 5', source)
        self.assertIn('"--record-demo", "NO_ARBITRARY_COMMAND"', source)
        self.assertIn('"--profile", "protected-core"] if upstream_socket is not None else []), 190)', source)
        self.assertLessEqual(M["MAX_VIDEO"] + M["MAX_SHOTS"] * M["MAX_PNG"], 256 * 1024**2)


if __name__ == "__main__": unittest.main()
