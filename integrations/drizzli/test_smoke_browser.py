#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert fixture-boundary tests; no Firefox, namespace or network launch."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("drizzli_smoke", HERE / "smoke_browser.py")
SMOKE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SMOKE)


class Boundaries(unittest.TestCase):
    def test_environment_excludes_runtime_injection_and_host_secrets(self):
        with patch.dict(os.environ, {"LD_PRELOAD": "private", "NODE_OPTIONS": "--import=private", "TOKEN": "private"}):
            self.assertEqual(set(SMOKE.clean_environment()), {"PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"})

    def test_process_exit_race_is_reaped_and_does_not_abort_cleanup(self):
        process = Mock(pid=123)
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        with patch.object(SMOKE.os, "killpg", side_effect=ProcessLookupError):
            self.assertTrue(SMOKE.stop(process))
        process.wait.assert_called_once_with(timeout=5)

    def test_failed_termination_is_reported_not_raised(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("test", 5)
        with patch.object(SMOKE.os, "killpg"):
            self.assertFalse(SMOKE.stop(process))

    def test_cleanup_refuses_replaced_work_identity_and_continues_after_bad_child(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-cleanup-test-", dir=SMOKE.ROOT / "build") as directory:
            work = Path(directory)
            (work / "profile").mkdir(mode=0o700)
            identity = SMOKE.work_identity(work)
            self.assertFalse(SMOKE.remove_private(work, (identity[0], identity[1] + 1)))
            self.assertTrue((work / "profile").is_dir())
            # Do not follow or remove the bad child; still clean the separate owned profile.
            (work / "cache").symlink_to(work / "outside")
            self.assertFalse(SMOKE.remove_private(work, identity))
            self.assertFalse((work / "profile").exists())
            self.assertTrue((work / "cache").is_symlink())


if __name__ == "__main__":
    unittest.main()
