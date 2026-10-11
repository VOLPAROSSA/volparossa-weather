#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline build-driver contracts; never invoke Git, SDK, sandbox or network."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent


class BuildContracts(unittest.TestCase):
    def setUp(self):
        self.api = runpy.run_path(str(HERE / "build.py"))
        self.globals = self.api["build_command"].__globals__
        self.pin = json.loads((HERE / "upstream.json").read_text())
        self.temporary = self.enterContext(tempfile.TemporaryDirectory(prefix=".build-test-", dir=HERE))
        self.root = Path(self.temporary) / "repository"
        self.build = self.root / "build"
        self.build.mkdir(parents=True)
        self.sdk, self.stage, self.work = (self.build / name for name in ("sdk", "stage", "work"))
        self.sdk.mkdir()
        self.stage.mkdir()
        self.common_name = ".git"
        self.hashes = {self.sdk / relative: expected for relative, expected in self.api["SDK_FILES"].items()}
        self.hashes[self.stage / "pubspec.lock"] = self.pin["pubspec_lock_sha256"]
        self.git = Mock(side_effect=self.git_answer)
        self.digest = Mock(side_effect=lambda path: self.hashes[Path(path)])
        # This is a mock module environment, not a change to the process HOME.
        self.environment = dict(HOME=os.environ["HOME"], USER="fixture", LOGNAME="fixture", LANG="C.UTF-8",
            AWS_SECRET_ACCESS_KEY="private-canary", GITHUB_TOKEN="private-canary",
            HTTP_PROXY="private-proxy", LD_PRELOAD="/private/library", PYTHONPATH="/private/code")
        fake_os = SimpleNamespace(environ=self.environment, getuid=os.getuid,
                                  sched_getaffinity=lambda _: {7, 3, 5})
        self.enterContext(patch.dict(self.globals, ROOT=self.root, git=self.git, digest=self.digest, os=fake_os))
        # Any forgotten subprocess mock fails before it could execute anything.
        self.run = self.enterContext(patch.object(subprocess, "run", side_effect=AssertionError("unexpected execution")))

    def git_answer(self, path, *args):
        if Path(path) == self.root and args == ("rev-parse", "--git-common-dir"):
            return self.common_name
        self.assertIn(Path(path), (self.sdk, self.stage))
        if args == ("rev-parse", "HEAD"):
            return self.pin["flutter_commit" if Path(path) == self.sdk else "commit"]
        if Path(path) == self.sdk and args in (("status", "--porcelain", "--untracked-files=no"),
                                               ("ls-files", "--others", "bin/internal")):
            return ""
        self.fail(f"unhandled Git query in offline fixture: {args!r}")

    def command(self, action="version", **paths):
        return self.api["build_command"](paths.get("sdk", self.sdk), paths.get("stage", self.stage),
                                         paths.get("work", self.work), action)

    def test_actions_have_exact_offline_or_locked_dependency_arguments(self):
        expected = {
            "version": ["--version", "--machine"],
            "dependencies": ["pub", "get", "--enforce-lockfile"],
            "build": ["build", "web", "--release", "--no-pub", "--no-wasm-dry-run",
                      "--dart-define=VOLPAROSSA_WEATHER=true"],
            "test": ["test", "--no-pub", "--reporter=expanded", "--concurrency=2",
                     "--dart-define=VOLPAROSSA_WEATHER=true", "test/volparossa_products_test.dart",
                     "test/volparossa_provider_test.dart", "test/volparossa_ui_test.dart"],
        }
        self.assertEqual(self.api["ACTIONS"], expected)
        for action, suffix in expected.items():
            with self.subTest(action=action):
                command, environment = self.command(action)
                self.assertEqual(command[:7], ["nice", "-n", "10", "taskset", "-c", "3,5", "bwrap"])
                self.assertEqual("--unshare-net" in command, action != "dependencies")
                self.assertEqual(command[-len(suffix)-3:],
                    [str(self.sdk / "bin/flutter"), "--no-version-check", "--suppress-analytics", *suffix])
                self.assertEqual(environment["CI"], "true")
        self.run.assert_not_called()

    def test_only_explicit_workspace_roots_are_writable_and_home_is_isolated(self):
        command, environment = self.command()
        writable = [command[index+1:index+3] for index, flag in enumerate(command) if flag == "--bind"]
        self.assertEqual(writable, [[str(path), str(path)] for path in (self.sdk, self.stage, self.work)]
            + [[str(self.work / "home"), self.environment["HOME"]]])
        readonly = [command[index+1:index+3] for index, flag in enumerate(command) if flag == "--ro-bind"]
        self.assertIn(["/usr", "/usr"], readonly)
        self.assertIn(["/etc/alternatives", "/etc/alternatives"], readonly)
        self.assertTrue(all(source == target for source, target in readonly))
        self.assertFalse(any(source == self.environment["HOME"] for source, _ in writable + readonly))
        self.assertNotIn(["/", "/"], readonly + writable)
        for flag in ("--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts"):
            self.assertIn(flag, command)
        self.assertEqual(environment["HOME"], self.environment["HOME"])
        self.assertEqual(environment["PATH"], f"{self.sdk}/bin:/usr/bin:/bin")
        self.assertEqual(environment["PUB_CACHE"], str(self.work / "pub-cache"))
        self.assertEqual(environment["XDG_CONFIG_HOME"], str(self.work / "config"))
        self.assertEqual(environment["XDG_CACHE_HOME"], str(self.work / "cache"))
        self.assertTrue(all(value not in environment.values() for value in
            ("private-canary", "private-proxy", "/private/library", "/private/code")))
        self.assertTrue(all(name not in environment for name in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "HTTP_PROXY", "LD_PRELOAD", "PYTHONPATH")))
        for path in (self.work, *(self.work / name for name in ("home", "config", "cache", "pub-cache"))):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_commit_and_executable_or_lock_mismatch_fail_before_state_creation(self):
        for target in (self.sdk, self.stage):
            with self.subTest(commit=target.name):
                self.git.side_effect = lambda path, *args: "0"*40 if Path(path) == target else self.git_answer(path, *args)
                with self.assertRaises(ValueError): self.command()
                self.assertFalse(self.work.exists())
        self.git.side_effect = self.git_answer
        for target, original in list(self.hashes.items()):
            with self.subTest(digest=target.name):
                self.hashes[target] = "0"*64
                with self.assertRaises(ValueError): self.command()
                self.assertFalse(self.work.exists())
                self.hashes[target] = original

    def test_symlink_inputs_and_work_or_outside_stage_are_rejected(self):
        alias = self.build / "alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        with self.assertRaises(ValueError): self.command(sdk=alias)
        alias.unlink()
        alias.symlink_to(self.stage, target_is_directory=True)
        with self.assertRaises(ValueError): self.command(stage=alias)
        with self.assertRaises(ValueError): self.command(work=alias)
        outside = Path(self.temporary) / "outside-stage"
        outside.mkdir()
        with self.assertRaises(ValueError): self.command(stage=outside)
        with self.assertRaises(ValueError): self.command(work=outside)
        with self.assertRaises(ValueError): self.command(work=self.stage)
        with self.assertRaises(ValueError): self.command(work=self.sdk)
        self.assertFalse(self.work.exists())
        self.assertTrue(all(call.args[0] == self.root for call in self.git.call_args_list))

    def test_sdk_outside_workspace_is_rejected_and_relative_common_dir_uses_root(self):
        original_sdk = self.sdk
        outside = Path(self.temporary) / "external-sdk"
        outside.mkdir()
        with self.assertRaisesRegex(ValueError, "SDK must remain"): self.command(sdk=outside)
        # A normal checkout returns relative .git; never resolve it against the
        # test caller's cwd when deciding which sibling core workspace is allowed.
        self.sdk = Path(self.temporary) / "Volparossa" / "pinned-sdk"
        self.sdk.mkdir(parents=True)
        for relative, expected in self.api["SDK_FILES"].items(): self.hashes[self.sdk / relative] = expected
        for name in (".git", str(self.root / ".git")):
            self.common_name = name
            command, _ = self.command()
            self.assertIn(str(self.sdk / "bin/flutter"), command)
        self.assertNotIn(str(original_sdk / "bin/flutter"), command)

    def test_modified_sdk_source_and_unreviewed_bootstrap_files_are_rejected(self):
        for query, value in (
            (("status", "--porcelain", "--untracked-files=no"), " M bin/flutter"),
            (("ls-files", "--others", "bin/internal"), "bin/internal/new-bootstrap.sh"),
        ):
            self.git.side_effect = lambda path, *args: value if Path(path) == self.sdk and args == query else self.git_answer(path, *args)
            with self.subTest(query=query), self.assertRaises(ValueError): self.command()
            self.assertFalse(self.work.exists())
        self.run.assert_not_called()

    def test_preexisting_work_and_state_must_be_private_and_owned(self):
        self.work.mkdir(mode=0o755)
        self.work.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "private"): self.command()
        self.work.chmod(0o700)
        target = self.work / "home"
        target.mkdir(mode=0o755)
        target.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "state"): self.command()
        target.chmod(0o700)
        fake_os = self.globals["os"]
        with patch.object(fake_os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, "owned"): self.command()

    def test_build_directory_symlink_cannot_redirect_workspace_writes(self):
        moved = self.root / "redirected-build"
        self.build.rename(moved)
        self.build.symlink_to(moved, target_is_directory=True)
        # Canonical SDK in the sibling core keeps this focused on the build
        # root guard, rather than rejecting an SDK symlink first.
        self.sdk = Path(self.temporary) / "Volparossa" / "pinned-sdk"
        self.sdk.mkdir(parents=True)
        self.stage = moved / "stage"
        with self.assertRaisesRegex(ValueError, "direct children"): self.command(work=moved / "work")
        self.assertFalse((moved / "work").exists())

    def test_preexisting_symlinked_state_and_invalid_home_are_rejected(self):
        for home in ("relative", "/", "/home"):
            self.environment["HOME"] = home
            with self.subTest(home=home), self.assertRaises(ValueError): self.command()
            self.assertFalse(self.work.exists())
        self.environment["HOME"] = os.environ["HOME"]
        self.work.mkdir(mode=0o700)
        target = self.work / "home"
        target.symlink_to(self.stage, target_is_directory=True)
        with self.assertRaises(ValueError): self.command()
        self.assertEqual(list(self.stage.iterdir()), [])

    def main(self, action="version", execute=False):
        args = [str(HERE / "build.py"), "--sdk", str(self.sdk), "--stage", str(self.stage),
                "--work", str(self.work), "--action", action]
        if execute: args += ["--execute"]
        with patch("sys.argv", args): self.api["main"]()

    def test_preview_neither_checks_tools_nor_reads_inputs_or_creates_state(self):
        output = io.StringIO()
        with patch.object(self.globals["shutil"], "which", side_effect=AssertionError("unexpected tool check")):
            with contextlib.redirect_stdout(output): self.main("dependencies")
        self.assertEqual(json.loads(output.getvalue()), dict(execute=False, action="dependencies", network=True,
                                                            global_installation=False))
        self.assertFalse(self.work.exists())
        self.git.assert_not_called()
        self.digest.assert_not_called()
        self.run.assert_not_called()

    def test_missing_sandbox_or_affinity_tool_never_falls_back(self):
        for missing in ("bwrap", "taskset"):
            with patch.object(self.globals["shutil"], "which", side_effect=lambda name: None if name == missing else f"/usr/bin/{name}"):
                with self.assertRaises(ValueError): self.main(execute=True)
        self.assertFalse(self.work.exists())
        self.run.assert_not_called()

    def test_executed_command_status_and_post_run_lock_are_checked(self):
        with patch.object(self.globals["shutil"], "which", return_value="/usr/bin/mock-tool"):
            for status in (0, 23):
                self.run.side_effect = None
                self.run.return_value = SimpleNamespace(returncode=status)
                with self.assertRaises(SystemExit) as raised: self.main("dependencies", execute=True)
                self.assertEqual(raised.exception.code, status)
                args, options = self.run.call_args
                self.assertIn("bwrap", args[0])
                self.assertEqual(options["timeout"], 1200)
                self.assertIs(options["check"], False)
                self.assertEqual(options["umask"], 0o077)
                self.assertNotIn("GITHUB_TOKEN", options["env"])
            def changed_lock(*args, **kwargs):
                self.hashes[self.stage / "pubspec.lock"] = "0"*64
                return SimpleNamespace(returncode=0)
            self.run.side_effect = changed_lock
            with self.assertRaisesRegex(ValueError, "lockfile"): self.main("dependencies", execute=True)

    def test_timeout_propagates_without_unsandboxed_retry(self):
        self.run.side_effect = subprocess.TimeoutExpired("mock sandbox", 1200)
        with patch.object(self.globals["shutil"], "which", return_value="/usr/bin/mock-tool"):
            with self.assertRaises(subprocess.TimeoutExpired): self.main(execute=True)
        self.assertEqual(self.run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
