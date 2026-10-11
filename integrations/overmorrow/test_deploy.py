#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline public-tree copier tests; synthetic bytes, no SDK/build/web server."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import stat
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


class DeployContracts(unittest.TestCase):
    def setUp(self):
        self.api = runpy.run_path(str(HERE / "deploy.py"))
        self.globals = self.api["deploy"].__globals__
        self.temporary = self.enterContext(tempfile.TemporaryDirectory(prefix=".deploy-test-", dir=HERE))
        self.root = Path(self.temporary) / "repository"
        self.build = self.root / "build"
        self.stage = self.build / "stage"
        self.source = self.stage / "build/web"
        self.destination = self.build / "public"
        self.source.mkdir(parents=True, mode=0o700)
        self.enterContext(patch.dict(self.globals, ROOT=self.root))
        required = self.api["ROOT_FILES"] | self.api["RENDERER_FILES"] | {"assets/NOTICES", "assets/AssetManifest.bin"}
        self.expected = {name: ("synthetic " + name).encode() for name in required}
        self.expected.update({"assets/nested/icon.png": b"\x89PNG\0fixture", "assets/fonts/local.otf": b"OTTO\0fixture",
            "assets/shaders/local.frag": b"synthetic shader", "icons/icon.png": b"synthetic icon"})
        for name, value in self.expected.items(): self.write(name, value)
        for name, output in (("LICENSE", "LICENSE.txt"), ("LICENSE.VOLPAROSSA", "LICENSE.VOLPAROSSA.txt")):
            value = f"Synthetic {name}; not a legal source fixture.".encode()
            path = self.stage / name
            path.write_bytes(value)
            path.chmod(0o600)
            self.expected[output] = value

    def write(self, name, value=b"fixture"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mkdir(parents=True) applies its mode only to the leaf; make every
        # synthetic parent deterministic under both developer and CI umasks.
        parent = path.parent
        while parent != self.source:
            parent.chmod(0o700)
            parent = parent.parent
        path.write_bytes(value)
        path.chmod(0o600)
        return path

    def deploy(self, **kwargs):
        return self.api["deploy"](kwargs.get("stage", self.stage), kwargs.get("destination", self.destination))

    def test_exact_bytes_manifest_licenses_modes_and_source_preservation(self):
        omitted = [".last_build_id", "flutter_service_worker.js", "canvaskit/canvaskit.js.symbols",
                   "canvaskit/skwasm.js", "canvaskit/skwasm.wasm", "canvaskit/skwasm_heavy.js"]
        for name in omitted: self.write(name)
        before = {path.relative_to(self.source).as_posix(): path.read_bytes()
                  for path in self.source.rglob("*") if path.is_file()}
        value = self.deploy()
        actual = {path.relative_to(self.destination).as_posix(): path.read_bytes()
                  for path in self.destination.rglob("*") if path.is_file()}
        self.assertEqual(actual, self.expected)
        self.assertEqual(value["omitted"], sorted(omitted))
        self.assertEqual(value["files"], len(self.expected))
        self.assertEqual(value["bytes"], sum(map(len, self.expected.values())))
        manifest = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(self.expected.items())}
        self.assertEqual(value["asset_sha256"], manifest)
        self.assertEqual(value["tree_sha256"], hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual((value["schema"], value["static_profile"]), (1, "flutter-canvaskit"))
        self.assertIs(value["browser_verified"], False)
        self.assertIs(value["core_delivery_verified"], False)
        for path in (self.destination, *self.destination.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        self.assertEqual(before, {path.relative_to(self.source).as_posix(): path.read_bytes()
                                 for path in self.source.rglob("*") if path.is_file()})

    def test_every_required_asset_and_both_licenses_are_mandatory(self):
        required = self.api["ROOT_FILES"] | self.api["RENDERER_FILES"] | {"assets/NOTICES", "assets/AssetManifest.bin"}
        for name in sorted(required):
            path = self.source / name
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(ValueError): self.deploy()
            self.assertFalse(self.destination.exists())
            self.write(name, raw)
        for name in ("LICENSE", "LICENSE.VOLPAROSSA"):
            path = self.stage / name
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(OSError): self.deploy()
            self.assertFalse(self.destination.exists())
            path.write_bytes(raw)
            path.chmod(0o600)

    def test_nested_destination_directories_stay_private_under_umask_0002(self):
        name = "assets/000_nested/more/deep/icon.png"
        raw = b"synthetic deeply nested asset"
        self.write(name, raw)
        previous_umask = os.umask(0o002)
        try:
            self.deploy()
            self.assertEqual(os.umask(0o002), 0o002, "deployment changed the process umask")
        finally:
            os.umask(previous_umask)
        self.assertEqual((self.destination / name).read_bytes(), raw)
        for path in (self.destination, *self.destination.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)

    def test_unknown_output_is_rejected_without_creating_a_destination(self):
        for name in ("unexpected.js", "credentials.json", "assets/private.pem", "canvaskit/unknown.wasm", "icons/private.json"):
            path = self.write(name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unexpected"): self.deploy()
            self.assertFalse(self.destination.exists())
            path.unlink()

    def test_symlinks_hardlinks_and_writable_assets_are_never_copied(self):
        ordinary = self.source / "index.html"
        aliases = [self.source / "assets/alias.png", self.source / "canvaskit/skwasm-alias.js"]
        for alias in aliases:
            alias.symlink_to(ordinary)
            with self.assertRaises(ValueError): self.deploy()
            self.assertFalse(self.destination.exists())
            alias.unlink()
        directory = self.source / "assets/alias-directory"
        directory.symlink_to(self.source / "icons", target_is_directory=True)
        with self.assertRaises(ValueError): self.deploy()
        directory.unlink()
        linked = self.source / "assets/hardlink.png"
        os.link(ordinary, linked)
        with self.assertRaises(ValueError): self.deploy()
        linked.unlink()
        ordinary.chmod(0o666)
        with self.assertRaises(ValueError): self.deploy()
        self.assertFalse(self.destination.exists())

    def test_owner_mismatch_is_rejected_without_changing_real_file_ownership(self):
        with patch.object(self.globals["os"], "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ValueError): self.deploy()
        self.assertFalse(self.destination.exists())

    def test_file_size_and_complete_tree_budget_include_licenses(self):
        self.assertEqual((self.api["MAX_FILE"], self.api["MAX_TREE"]), (8*1024*1024, 32*1024*1024))
        # Synthetic tiny thresholds exercise the exact checks without reading or
        # allocating megabytes. Production constants above stay unchanged.
        largest = max(map(len, self.expected.values()))
        total = sum(map(len, self.expected.values()))
        with patch.dict(self.globals, MAX_FILE=largest - 1):
            with self.assertRaisesRegex(ValueError, "oversized"): self.deploy()
        self.assertFalse(self.destination.exists())
        with patch.dict(self.globals, MAX_TREE=total - 1):
            with self.assertRaisesRegex(ValueError, "budget"): self.deploy()
        self.assertFalse(self.destination.exists())
        with patch.dict(self.globals, MAX_TREE=total, MAX_FILE=largest):
            self.assertEqual(self.deploy()["bytes"], total)

    def test_existing_or_outside_destinations_and_stage_aliases_are_rejected(self):
        self.destination.mkdir(mode=0o700)
        canary = self.destination / "preserve"
        canary.write_bytes(b"existing user data")
        with self.assertRaises(ValueError): self.deploy()
        self.assertEqual(canary.read_bytes(), b"existing user data")
        alias = self.build / "stage-alias"
        alias.symlink_to(self.stage, target_is_directory=True)
        fresh = self.build / "another-output"
        with self.assertRaises(ValueError): self.deploy(stage=alias, destination=fresh)
        dangling = self.build / "dangling-output"
        dangling.symlink_to(self.build / "missing-directory")
        with self.assertRaises(ValueError): self.deploy(destination=dangling)
        with self.assertRaises(ValueError): self.deploy(destination=Path(self.temporary) / "outside-output")
        self.assertFalse(fresh.exists())
        self.assertFalse((Path(self.temporary) / "outside-output").exists())

    def test_tree_budget_is_checked_before_hashing_assets_and_licenses(self):
        with patch.dict(self.globals, MAX_TREE=1,
                        digest=lambda _: self.fail("hashed an over-budget source asset")):
            with self.assertRaisesRegex(ValueError, "budget"): self.deploy()
        self.assertFalse(self.destination.exists())
        source_total = sum(len(raw) for name, raw in self.expected.items()
                           if name not in ("LICENSE.txt", "LICENSE.VOLPAROSSA.txt"))
        original = self.globals["digest"]
        hashed = []
        def checked_digest(path):
            self.assertTrue(path.is_relative_to(self.source), "hashed an over-budget license")
            hashed.append(path)
            return original(path)
        with patch.dict(self.globals, MAX_TREE=source_total, digest=checked_digest):
            with self.assertRaisesRegex(ValueError, "budget"): self.deploy()
        self.assertEqual(len(hashed), len(self.expected) - 2)
        self.assertFalse(self.destination.exists())

    def test_more_than_1024_entries_rejected_before_hashing_or_copying(self):
        with patch.object(Path, "rglob", return_value=iter([self.source / "index.html"] * 1025)):
            with patch.dict(self.globals, digest=lambda _: self.fail("must not hash over-budget tree")):
                with self.assertRaisesRegex(ValueError, "too many"): self.deploy()
        self.assertFalse(self.destination.exists())

    def test_copy_or_source_changes_do_not_return_a_successful_manifest(self):
        original = self.globals["shutil"].copyfile
        def corrupt_copy(source, target):
            original(source, target)
            Path(target).write_bytes(b"corrupted destination")
        with patch.object(self.globals["shutil"], "copyfile", side_effect=corrupt_copy):
            with self.assertRaisesRegex(ValueError, "changed while copying"): self.deploy()
        # Failure retains an inspectable partial directory; it cannot be reused
        # as a newly authorized destination on a second attempt.
        self.assertTrue(self.destination.exists())
        with self.assertRaises(ValueError): self.deploy()

    def test_preview_is_inert_even_when_supplied_paths_do_not_exist(self):
        output = io.StringIO()
        with patch("sys.argv", [str(HERE / "deploy.py"), "--stage", "/unread/stage",
                                 "--destination", "/unread/output"]):
            with patch.object(Path, "rglob", side_effect=AssertionError("preview traversed files")):
                with contextlib.redirect_stdout(output): runpy.run_path(str(HERE / "deploy.py"), run_name="__main__")
        self.assertEqual(json.loads(output.getvalue()), dict(execute=False,
                         action="copy bounded self-hosted assets and notices"))
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
