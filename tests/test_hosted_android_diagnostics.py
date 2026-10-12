# SPDX-License-Identifier: GPL-3.0-only
"""Inert diagnostic fixtures only: no Gradle, JVM, SDK or namespaces executed."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("android_diag_tests", ROOT / "scripts/prepare_hosted_android_diagnostics.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def events(**changes):
    values = {key: 0 for key in D.COUNTERS}
    values.update(changes)
    return "".join(f"{key} {value}\n" for key, value in values.items()).encode()


class DiagnosticLogs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)

    def write(self, name, raw):
        path = self.path / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def capture(self):
        return D.Logs(self.path, r"daemon-[0-9]{1,10}\.out\.log")

    def test_only_new_phase_bytes_and_closed_categories_are_retained(self):
        old = self.write("daemon-1.out.log", b"java.lang.OutOfMemoryError: Java heap space\n")
        capture = self.capture()
        with old.open("ab") as out:
            out.write(b"ordinary end\n")
        self.write("daemon-2.out.log", b"secret_token=private/path\nGradle build daemon disappeared unexpectedly\n")
        self.write("unrelated.log", b"java.lang.OutOfMemoryError: Java heap space")
        value = capture.finish(True)
        self.assertEqual(value["status"], "observed")
        self.assertEqual(value["files_observed"], 2)
        self.assertEqual(value["markers"]["daemon_disappeared"], "observed")
        self.assertEqual(value["markers"]["java_heap_exhausted"], "not_observed")
        encoded = json.dumps(value)
        for private in ("secret", "private", "daemon-", str(self.path)):
            self.assertNotIn(private, encoded)
        self.assertIsNone(capture.fd)

    def test_missing_empty_and_unconfirmed_drain_remain_unknown(self):
        self.assertEqual(self.capture().finish(True), D.unknown_source("missing"))
        capture = self.capture()
        self.write("daemon-1.out.log", b"java.lang.OutOfMemoryError")
        self.assertEqual(capture.finish(False), D.unknown_source())
        self.assertIsNone(capture.fd)

    def test_fatal_heap_and_native_oom_indications(self):
        for key, needles in D.MARKERS.items():
            capture = self.capture()
            path = self.write("daemon-7.out.log", needles[0])
            self.assertEqual(capture.finish(True)["markers"][key], "observed")
            path.unlink()

    def test_truncated_tail_cannot_claim_unobserved_marker_absent(self):
        capture = self.capture()
        self.write("daemon-7.out.log", b"x" * (D.MAX_BYTES+1) + b"java.lang.OutOfMemoryError")
        value = capture.finish(True)
        self.assertEqual(value["status"], "bounded")
        self.assertEqual(value["bytes_observed"], D.MAX_BYTES)
        self.assertEqual(value["markers"]["java_oom"], "observed")
        self.assertEqual(value["markers"]["jvm_fatal"], "unknown")

    def test_short_gradle_heap_cause_without_java_class_prefix(self):
        # Exact short cause from hosted run 38256253721, without copying any
        # dependency path or private text into the closed diagnostic receipt.
        for raw, expected in (
                (b"Execution failed for task ':app:compileDebugKotlin'.\n            > Java heap space\n", True),
                (b"\t> GC overhead limit exceeded\r\n", True),
                (b"> Java heap space", True),
                (b"example: > Java heap space\n", False),
                (b"> Java heap space may be relevant\n", False)):
            with self.subTest(raw=raw):
                capture = self.capture()
                path = self.write("daemon-7.out.log", raw)
                value = capture.finish(True)
                self.assertEqual(value["markers"]["java_heap_exhausted"],
                    "observed" if expected else "not_observed")
                self.assertNotIn("compileDebugKotlin", json.dumps(value))
                path.unlink()

    def test_same_fd_type_owner_mode_links_and_mutation(self):
        for kind in ("symlink", "fifo", "hardlink", "writable", "foreign", "changed"):
            with self.subTest(kind=kind):
                capture = self.capture()
                path = self.path / "daemon-7.out.log"
                if kind == "symlink":
                    path.symlink_to("not-followed")
                elif kind == "fifo":
                    os.mkfifo(path, 0o600)
                else:
                    self.write(path.name, b"java.lang.OutOfMemoryError")
                if kind == "hardlink":
                    os.link(path, self.path / "other")
                if kind == "writable":
                    path.chmod(0o622)
                if kind == "foreign":
                    with patch.object(D.os, "getuid", return_value=os.getuid()+1):
                        value = capture.finish(True)
                elif kind == "changed":
                    original = os.pread
                    def read(fd, size, offset):
                        raw = original(fd, size, offset)
                        with path.open("ab") as out: out.write(b"changed")
                        return raw
                    with patch.object(D.os, "pread", side_effect=read):
                        value = capture.finish(True)
                else:
                    value = capture.finish(True)
                self.assertEqual(value, D.unknown_source())
                self.assertIsNone(capture.fd)
                path.unlink()
                (self.path / "other").unlink(missing_ok=True)

    def test_directory_replacement_and_scan_bounds(self):
        capture = self.capture()
        alternate = self.path / "alternate"
        alternate.mkdir()
        capture.path = alternate
        self.assertEqual(capture.finish(True), D.unknown_source())
        capture = self.capture()
        for number in range(D.MAX_FILES+1):
            self.write(f"daemon-{number}.out.log", b"x")
        self.assertEqual(capture.finish(True), D.unknown_source())
        with patch.object(D, "MAX_ENTRIES", 1):
            capture = self.capture()
            self.assertEqual(capture.finish(True), D.unknown_source())
        for path in self.path.glob("daemon-*.out.log"):
            path.unlink()
        capture = self.capture()
        self.write("daemon-7.out.log", b"ordinary")
        with patch.object(D.time, "monotonic", side_effect=[0, 3]):
            self.assertEqual(capture.finish(True), D.unknown_source())

    def test_interrupted_source_constructor_closes_its_descriptor(self):
        opened = []
        original = D.directory
        def directory(path):
            fd = original(path)
            opened.append(fd)
            return fd
        with patch.object(D, "directory", side_effect=directory), patch.object(D, "entries", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.capture()
        with self.assertRaises(OSError): os.fstat(opened[0])

    def test_partial_constructor_failure_closes_all_open_descriptors(self):
        group, log = Mock(fd=os.open(self.path, os.O_RDONLY)), Mock(fd=os.open(self.path, os.O_RDONLY))
        descriptors = (group.fd, log.fd)
        with patch.object(D, "Cgroup", return_value=group), patch.object(D, "Logs", side_effect=[log, ValueError("inert")]):
            with self.assertRaises(ValueError):
                D.Capture(self.path, self.path, self.path, "android-acquisition-build")
        for fd in descriptors:
            with self.assertRaises(OSError): os.fstat(fd)


class CgroupObservations(unittest.TestCase):
    def test_counter_parser_rejects_malformed_duplicate_missing_overflow(self):
        self.assertEqual(D.counters(events()), {key: 0 for key in D.COUNTERS})
        self.assertIsNone(D.counters(events().replace(b"oom_group_kill 0\n", b""))["oom_group_kill"])
        for raw in (b"", events()+b"oom 1\n", events().replace(b"oom 0", b"oom -1"),
                events().replace(b"oom 0", b"oom 18446744073709551616"), events().replace(b"oom 0\n", b"")):
            with self.assertRaises(ValueError): D.counters(raw)

    def test_shared_counter_delta_reset_and_membership_change(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "events"
            for raw, membership, observed in ((events(oom=2, oom_kill=1), "/same", True),
                    (events(), "/same", False), (events(oom=2), "/other", False)):
                file.write_bytes(raw)
                observer = object.__new__(D.Cgroup)
                observer.fd = os.open(file, os.O_RDONLY)
                observer.before, observer.group = D.counters(events(oom=1)), "/same"
                with patch.object(D, "membership", return_value=membership):
                    value = observer.finish()
                self.assertEqual(value["status"], "observed" if observed else "unknown")
                self.assertFalse(value["child_attribution"])
                self.assertIsNone(observer.fd)
                if observed:
                    self.assertEqual(value["delta"]["oom"], 1)
                    self.assertEqual(value["delta"]["oom_kill"], 1)
                else:
                    self.assertIsNone(value["delta"])

    def test_missing_cgroup_never_means_no_oom(self):
        with patch.object(D, "membership", side_effect=OSError("inert private details")):
            value = D.Cgroup().finish()
        self.assertEqual(value["status"], "unknown")
        self.assertIsNone(value["delta"])
        self.assertNotIn("private", json.dumps(value))

    def test_membership_only_fixed_unified_path_and_bounded_read(self):
        # /proc/self/cgroup is opened read-only; only its inert contents vary.
        for raw, accepted in ((b"0::/system.slice/job.service\n", True), (b"0::/\n", True),
                (b"1:memory:/v1\n", False), (b"0::/../../private\n", False),
                (b"0::/private//file\n", False), (b"0::/job\n0::/other\n", False)):
            with patch.object(D, "small", return_value=raw):
                if accepted: self.assertTrue(D.membership().startswith("/"))
                else:
                    with self.assertRaises(ValueError): D.membership()
        with patch.object(D.os, "pread", return_value=b"x"*4097):
            with self.assertRaises(ValueError): D.small(-1)


if __name__ == "__main__":
    unittest.main()
