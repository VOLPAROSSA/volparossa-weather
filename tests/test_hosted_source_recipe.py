# SPDX-License-Identifier: GPL-3.0-only
"""Inert source exports using disposable real Git repositories, never runtimes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_recipe", ROOT / "scripts/prepare_hosted_source_recipe.py")
RECIPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECIPE)
REAL_RUN = subprocess.run


class SourceRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir(mode=0o700)
        (self.root / "build").mkdir(mode=0o700)
        for name in set().union(*RECIPE.PROFILES.values()):
            path = self.root / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
            path.chmod(0o600)
        for directory in self.root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o700)
        self.git("init", "--quiet")
        self.commit()

    def git(self, *args):
        environment = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C",
                       "GIT_AUTHOR_NAME": "Source fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                       "GIT_COMMITTER_NAME": "Source fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
        # Disposable repositories must not leave auto-maintenance writers behind
        # when TemporaryDirectory removes their object directories.
        return REAL_RUN(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                         "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                         "-c", "gc.autoDetach=false",
                         "-C", str(self.root), *args], env=environment, check=True,
                        capture_output=True, text=True, timeout=10).stdout.strip()

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Inert source fixture")
        self.commit_id = self.git("rev-parse", "HEAD")

    def output(self, name="recipe"):
        return self.root / "build" / name

    def prepare(self, profile="drizzli", name="recipe"):
        return RECIPE.prepare(self.root, profile, self.commit_id, self.output(name))

    def assert_rejected(self, profile="drizzli", exception=(ValueError, OSError)):
        with self.assertRaises(exception):
            self.prepare(profile)
        self.assertFalse(self.output().exists())

    def test_fixed_profiles_and_self_inclusion(self):
        self.assertEqual(set(RECIPE.PROFILES), {"drizzli", "overmorrow"})
        self.assertEqual(len(RECIPE.source_paths("drizzli")), 59)
        self.assertEqual(len(RECIPE.source_paths("overmorrow")), 67)
        self.assertEqual(len(set().union(*RECIPE.PROFILES.values())), 82)
        for profile in RECIPE.PROFILES:
            self.assertIn(RECIPE.HELPER, RECIPE.source_paths(profile))
            self.assertIn("scripts/prepare_hosted_decoder_environment.py", RECIPE.source_paths(profile))
            self.assertFalse(any("environment-v1.json" in name for name in RECIPE.source_paths(profile)))

    def test_both_profiles_copy_exact_bytes_modes_hidden_workflows_and_licenses(self):
        for profile in RECIPE.PROFILES:
            with self.subTest(profile=profile):
                output = self.prepare(profile, profile)
                manifest = json.loads((output / "manifest.json").read_bytes())
                self.assertEqual(manifest["expected_weather_commit"], self.commit_id)
                self.assertEqual(manifest["actual_weather_commit"], self.commit_id)
                self.assertEqual(manifest["kind"], "volparossa-weather-source-recipe")
                self.assertEqual(manifest["schema"], 1)
                self.assertEqual(manifest["helper"]["sha256"],
                                 hashlib.sha256((self.root / RECIPE.HELPER).read_bytes()).hexdigest())
                selected = set(RECIPE.source_paths(profile))
                actual = {path.relative_to(output / "source").as_posix()
                          for path in (output / "source").rglob("*") if path.is_file()}
                self.assertEqual(actual, selected)
                self.assertEqual(set(manifest["source_files"]), actual)
                self.assertTrue(any(name.startswith(".github/") for name in actual))
                self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()},
                                 {"manifest.json"} | {"source/" + name for name in actual})
                for name in selected:
                    data = (self.root / name).read_bytes()
                    self.assertEqual((output / "source" / name).read_bytes(), data)
                    self.assertEqual(manifest["source_files"][name],
                                     {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                for path in [output, *output.rglob("*")]:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
                for name in ("LICENSE", "third_party/apparmor-ci/LICENSE"):
                    self.assertEqual((output / "source" / name).read_bytes(), (ROOT / name).read_bytes())
                self.assertEqual(manifest["scope"], {
                    "source_recipe_only": True, "upstream_sources_included": False,
                    "dependency_sources_included": False, "binary_outputs_included": False,
                    "historical_admission_compatible": False, "runtime_verified": False,
                    "redistribution_cleared": False, "complete_build_recipe_proven": False,
                    "bit_reproducibility_proven": False,
                })
                self.assertTrue(all(ref["delivery"] == "references_only"
                                    for ref in manifest["external_references"].values()))
                self.assertNotIn(str(self.root), (output / "manifest.json").read_text())

    def test_deterministic_manifest_and_sources(self):
        first, second = self.prepare(name="one"), self.prepare(name="two")
        for path in first.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (second / path.relative_to(first)).read_bytes())

    def test_unselected_runtime_cache_git_and_compiled_files_are_never_read(self):
        extras = ("build/node/bin/node", "build/firefox/firefox", "build/client/app.wasm",
                  "build/client/compiled.js", "build/profile/cookies.sqlite", "build/cache/binary",
                  "unselected.elf")
        for name in extras:
            path = self.root / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(b"\x7fELF\x00dummy not executable")
        reads = []
        original_read = RECIPE.read_source

        def source_read(root, name):
            reads.append(name)
            return original_read(root, name)

        def only_read_only_git(argv, **kwargs):
            self.assertEqual(argv[:5], ["git", "-c", "core.hooksPath=/dev/null", "-C", str(self.root)])
            self.assertTrue(argv[5:] == ["rev-parse", "--verify", "HEAD"]
                            or argv[5:10] == ["ls-tree", "-l", "-z", self.commit_id, "--"])
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(kwargs["timeout"], 10)
            return REAL_RUN(argv, **kwargs)

        with mock.patch.object(RECIPE, "read_source", side_effect=source_read), \
                mock.patch.object(subprocess, "run", side_effect=only_read_only_git), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("Network forbidden")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")):
            output = self.prepare()
        self.assertEqual(set(reads), set(RECIPE.source_paths("drizzli")))
        self.assertFalse(any(path.name in ("node", "firefox", "cookies.sqlite", "app.wasm", ".git")
                             for path in output.rglob("*")))

    def test_unknown_profile_and_unsafe_or_duplicate_selection(self):
        self.assert_rejected("unknown")
        for paths in (("LICENSE", "LICENSE"), ("/etc/passwd",), ("../LICENSE",),
                      ("src//forecast.mjs",), ("src/./forecast.mjs",), ("src/../../LICENSE",)):
            with self.subTest(paths=paths), mock.patch.dict(RECIPE.PROFILES, {"invalid": paths}):
                self.assert_rejected("invalid")

    def test_wrong_and_malformed_expected_commit(self):
        for commit in ("0" * 40, "HEAD", "a" * 41, True, "A" * 40):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                RECIPE.prepare(self.root, "drizzli", commit, self.output())
        self.assertFalse(self.output().exists())

    def test_selected_dirty_source_fails_without_claiming_old_commit(self):
        (self.root / "LICENSE").write_text("changed")
        self.assert_rejected()

    def test_missing_and_untracked_selected_sources(self):
        path = self.root / "LICENSE"
        original = path.read_bytes()
        path.unlink()
        self.assert_rejected()
        self.commit()
        path.write_bytes(original)
        self.assert_rejected()

    def test_source_symlink_hardlink_fifo_and_unsafe_mode(self):
        path = self.root / "LICENSE"
        original = path.read_bytes()
        target = self.root / "original"
        target.write_bytes(original)
        for kind in ("symlink", "hardlink", "fifo", "mode"):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == "symlink":
                    path.symlink_to(target)
                elif kind == "hardlink":
                    os.link(target, path)
                elif kind == "fifo":
                    os.mkfifo(path)
                else:
                    path.write_bytes(original)
                    path.chmod(0o666)
                self.assert_rejected()

    def test_unsafe_source_directory_and_symlinked_parent(self):
        directory = self.root / "src"
        directory.chmod(0o777)
        self.assert_rejected()
        directory.chmod(0o700)
        moved = self.root / "moved-src"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assert_rejected()

    def test_unsafe_source_ownership(self):
        with mock.patch.object(RECIPE.os, "getuid", return_value=os.getuid() + 1):
            self.assert_rejected()

    def test_symlink_in_source_root_is_rejected(self):
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            RECIPE.prepare(alias, "drizzli", self.commit_id, alias / "build/recipe")
        self.assertFalse(self.output().exists())

    def test_source_mutation_while_reading_is_rejected(self):
        original_fstat = os.fstat
        regular_calls = 0

        def changing_fstat(fd):
            nonlocal regular_calls
            info = original_fstat(fd)
            if stat.S_ISREG(info.st_mode):
                regular_calls += 1
                if regular_calls == 2:
                    with (self.root / "LICENSE").open("ab") as stream:
                        stream.write(b"changed during read")
                    info = original_fstat(fd)
            return info

        with mock.patch.object(RECIPE.os, "fstat", side_effect=changing_fstat):
            with self.assertRaisesRegex(ValueError, "changed while reading"):
                RECIPE.read_source(self.root, "LICENSE")

    def test_output_must_be_new_child_of_existing_safe_build(self):
        for output in (self.root / "elsewhere", self.output() / "nested", self.root / "build/../other"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                RECIPE.prepare(self.root, "drizzli", self.commit_id, output)
        (self.root / "build").chmod(0o777)
        self.assert_rejected()
        (self.root / "build").chmod(0o700)
        (self.root / "build").rmdir()
        self.assert_rejected()

    def test_existing_output_is_preserved(self):
        self.output().mkdir()
        marker = self.output() / "keep"
        marker.write_text("original")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(marker.read_text(), "original")
        self.assertEqual(list(self.output().iterdir()), [marker])

    def test_symlinked_build_and_output_are_rejected_without_touching_target(self):
        build = self.root / "build"
        build.rmdir()
        target = self.root / "other"
        target.mkdir(mode=0o700)
        build.symlink_to(target, target_is_directory=True)
        self.assert_rejected()
        build.unlink()
        build.mkdir(mode=0o700)
        self.output().symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertTrue(self.output().is_symlink())
        self.assertEqual(list(target.iterdir()), [])

    def test_file_count_file_total_and_manifest_size_limits(self):
        for limit in ("MAX_FILES", "MAX_FILE", "MAX_TOTAL", "MAX_MANIFEST"):
            with self.subTest(limit=limit), mock.patch.object(RECIPE, limit, 1):
                self.assert_rejected()

    def test_actual_oversized_tracked_source_is_rejected(self):
        (self.root / "LICENSE").write_bytes(b"x" * (RECIPE.MAX_FILE + 1))
        self.commit()
        self.assert_rejected()

    def test_duplicate_json_keys_types_and_changed_pins_fail(self):
        path = self.root / "integrations/drizzli/upstream.json"
        original = path.read_bytes()
        for data in (b'{"schema":1,"schema":1}', b'[]', b'{"schema":true}',
                     b'{"schema":NaN}', original.replace(b'"schema": 1', b'"schema": 2')):
            with self.subTest(data=data[:40]):
                path.write_bytes(data)
                self.commit()
                self.assert_rejected()

    def test_all_reviewed_pin_bytes_are_validated(self):
        for name in RECIPE.PIN_SHA256:
            profile = "overmorrow" if "/overmorrow/" in name else "drizzli"
            files = RECIPE.snapshot(self.root, profile, self.commit_id)
            files[name] += b" "
            with self.subTest(name=name), self.assertRaises(ValueError):
                RECIPE.manifest_bytes(profile, self.commit_id, files)

    def test_patch_and_exact_four_weather_module_hashes_are_checked(self):
        for name in ("integrations/drizzli/upstream.patch", "src/forecast.mjs", "src/provider.mjs",
                     "src/air-quality.mjs", "src/air-quality-provider.mjs",
                     "integrations/overmorrow/upstream.patch"):
            profile = "overmorrow" if "/overmorrow/" in name else "drizzli"
            files = RECIPE.snapshot(self.root, profile, self.commit_id)
            files[name] += b"modified"
            with self.subTest(name=name), self.assertRaises(ValueError):
                RECIPE.manifest_bytes(profile, self.commit_id, files)

    def test_weather_modules_cannot_omit_or_add_a_path(self):
        name = "integrations/drizzli/upstream.json"
        for extra in (False, True):
            files = RECIPE.snapshot(self.root, "drizzli", self.commit_id)
            pin = json.loads(files[name])
            if extra:
                pin["weather_modules"]["src/unselected.mjs"] = "0" * 64
            else:
                pin["weather_modules"].pop("src/forecast.mjs")
            files[name] = json.dumps(pin).encode()
            # Even a separately reviewed pin-byte update must satisfy the fixed
            # four-module contract. Production has no pin override argument.
            with mock.patch.dict(RECIPE.PIN_SHA256, {name: hashlib.sha256(files[name]).hexdigest()}):
                with self.assertRaisesRegex(ValueError, "exactly four"):
                    RECIPE.manifest_bytes("drizzli", self.commit_id, files)

    def test_flutter_constant_consistency_without_executing_helper(self):
        files = RECIPE.snapshot(self.root, "overmorrow", self.commit_id)
        files["scripts/prepare_hosted_flutter.py"] = files["scripts/prepare_hosted_flutter.py"].replace(
            b'VERSION = "3.38.5"', b'VERSION = "0.0.0"')
        with self.assertRaisesRegex(ValueError, "Flutter"):
            RECIPE.manifest_bytes("overmorrow", self.commit_id, files)

    def test_extra_or_missing_manifest_source_is_rejected(self):
        files = RECIPE.snapshot(self.root, "drizzli", self.commit_id)
        files["unselected.elf"] = b"dummy"
        with self.assertRaises(ValueError):
            RECIPE.manifest_bytes("drizzli", self.commit_id, files)
        files.pop("unselected.elf")
        files.pop("LICENSE")
        with self.assertRaises(ValueError):
            RECIPE.manifest_bytes("drizzli", self.commit_id, files)

    def test_copy_failure_cleans_only_own_output(self):
        keep = self.output("keep")
        keep.write_text("unrelated")
        original_write = RECIPE.write_private
        count = 0

        def interrupted(path, data, **kwargs):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("Simulated interrupted copy")
            original_write(path, data, **kwargs)

        with mock.patch.object(RECIPE, "write_private", side_effect=interrupted):
            self.assert_rejected()
        self.assertEqual(keep.read_text(), "unrelated")

    def test_source_and_head_are_rechecked_before_success_manifest(self):
        original_write = RECIPE.write_private
        for change in ("bytes", "head"):
            with self.subTest(change=change):
                changed = False

                def mutate_after_first_copy(path, data, **kwargs):
                    nonlocal changed
                    original_write(path, data, **kwargs)
                    if not changed:
                        changed = True
                        (self.root / "LICENSE").write_text("source changed during copy")
                        if change == "head":
                            self.commit()

                expected = self.commit_id
                with mock.patch.object(RECIPE, "write_private", side_effect=mutate_after_first_copy):
                    with self.assertRaises(ValueError):
                        RECIPE.prepare(self.root, "drizzli", expected, self.output())
                self.assertFalse(self.output().exists())
                (self.root / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
                self.commit()

    def test_head_aba_cannot_bind_other_commit_source_to_expected_commit(self):
        expected = self.commit_id
        name = "scripts/prepare_hosted_clients_ci.py"
        (self.root / name).write_bytes((self.root / name).read_bytes() + b"\n# fixture B source\n")
        self.commit()
        other = self.commit_id
        self.git("update-ref", "HEAD", expected)
        original_git_read = RECIPE.git_read
        swaps = []

        def raced(root, args, limit):
            if args[:3] == ["ls-tree", "-l", "-z"]:
                self.git("update-ref", "HEAD", other)
                try:
                    result = original_git_read(root, args, limit)
                    swaps.append((self.git("rev-parse", "HEAD"), args[3]))
                    return result
                finally:
                    self.git("update-ref", "HEAD", expected)
            return original_git_read(root, args, limit)

        with mock.patch.object(RECIPE, "git_read", side_effect=raced):
            with self.assertRaisesRegex(ValueError, "source differs from HEAD"):
                RECIPE.prepare(self.root, "drizzli", expected, self.output())
        self.assertEqual(swaps, [(other, expected)])
        self.assertEqual(self.git("rev-parse", "HEAD"), expected)
        self.assertFalse(self.output().exists())

    def test_replaced_output_is_preserved_on_copy_failure_and_before_finish(self):
        original_write = RECIPE.write_private
        for raise_after_replacement in (True, False):
            with self.subTest(raise_after_replacement=raise_after_replacement):
                output = self.output("replacement-" + str(raise_after_replacement))
                moved = self.output("moved-" + str(raise_after_replacement))
                replaced = False

                def replace_after_first_copy(path, data, **kwargs):
                    nonlocal replaced
                    original_write(path, data, **kwargs)
                    if not replaced:
                        replaced = True
                        output.rename(moved)
                        output.mkdir(mode=0o700)
                        (output / "FOREIGN_KEEP").write_bytes(b"unrelated replacement data")
                        if raise_after_replacement:
                            raise OSError("Fixture replaced output and interrupted copy")

                with mock.patch.object(RECIPE, "write_private", side_effect=replace_after_first_copy):
                    with self.assertRaises((ValueError, OSError)):
                        RECIPE.prepare(self.root, "drizzli", self.commit_id, output)
                self.assertEqual((output / "FOREIGN_KEEP").read_bytes(), b"unrelated replacement data")
                self.assertEqual([path.name for path in output.iterdir()], ["FOREIGN_KEEP"])
                self.assertTrue(moved.is_dir())
                self.assertFalse((moved / "manifest.json").exists())
                self.assertTrue(any(path.is_file() for path in moved.rglob("*")))

    def test_replacement_between_mkdir_and_open_never_acquires_cleanup_ownership(self):
        original_open = os.open
        moved = self.output("created-original")
        replaced = False

        def replace_before_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if not replaced and path == self.output().name and flags & os.O_DIRECTORY \
                    and kwargs.get("dir_fd") is not None:
                replaced = True
                self.output().rename(moved)
                self.output().mkdir(mode=0o700)
                (self.output() / "FOREIGN_KEEP").write_bytes(b"preexisting replacement data")
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(RECIPE.os, "open", side_effect=replace_before_open), \
                mock.patch.object(RECIPE, "write_private", side_effect=OSError("Fixture copy failure")) as write:
            with self.assertRaisesRegex(ValueError, "not empty"):
                self.prepare()
        self.assertTrue(replaced)
        write.assert_not_called()
        self.assertEqual((self.output() / "FOREIGN_KEEP").read_bytes(), b"preexisting replacement data")
        self.assertEqual([path.name for path in self.output().iterdir()], ["FOREIGN_KEEP"])
        self.assertTrue(moved.is_dir())
        self.assertEqual(list(moved.iterdir()), [])

    def test_cleanup_stays_on_owned_descriptor_if_root_is_replaced_during_cleanup(self):
        original_write = RECIPE.write_private
        original_rmtree = RECIPE.shutil.rmtree
        writes = 0

        def interrupted(path, data, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 3:
                raise OSError("Fixture copy interruption")
            original_write(path, data, **kwargs)

        def replace_before_recursive_cleanup(path, **kwargs):
            self.assertIn("dir_fd", kwargs)
            self.output().rename(self.output("moved"))
            self.output().mkdir(mode=0o700)
            (self.output() / "FOREIGN_KEEP").write_bytes(b"preserve during cleanup")
            return original_rmtree(path, **kwargs)

        with mock.patch.object(RECIPE, "write_private", side_effect=interrupted), \
                mock.patch.object(RECIPE.shutil, "rmtree", side_effect=replace_before_recursive_cleanup):
            with self.assertRaisesRegex(OSError, "copy interruption"):
                self.prepare()
        self.assertEqual((self.output() / "FOREIGN_KEEP").read_bytes(), b"preserve during cleanup")
        self.assertTrue(self.output("moved").is_dir())


if __name__ == "__main__":
    unittest.main()
