"""Inert archive fixtures only: never fetch, unpack or execute the real SDK."""
import ast
from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hosted_flutter", ROOT / "scripts/prepare_hosted_flutter.py")
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def member(name, data=b"fixture\n", *, mode=0o644, kind=tarfile.REGTYPE, mtime=1700000000):
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.mtime = kind, mode, mtime
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        info.linkname = data.decode()
    return info, data


def members():
    return [member("flutter", kind=tarfile.DIRTYPE),
            member("flutter/LICENSE", b"original BSD license\n"),
            member("flutter/.git/HEAD", b"ref: refs/heads/stable\n"),
            member("flutter/bin/flutter", b"inert flutter shell fixture\n", mode=0o755),
            member("flutter/bin/cache/dart-sdk/bin/dart", b"inert Dart fixture\n", mode=0o755),
            member("flutter/bin/cache/flutter_tools.snapshot", b"inert snapshot\n"),
            member("flutter/bin/cache/engine.stamp", b"original stamp\n"),
            member("flutter/bin/cache/lockfile", b""),
            member("flutter/packages/flutter_tools/pubspec.lock", b"locked\n", mtime=1700000002),
            # Deliberately reverse extraction order: mtime must not reverse.
            member("flutter/packages/flutter_tools/pubspec.yaml", b"source\n", mtime=1700000001)]


def compressed(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, data in entries:
            archive.addfile(info, io.BytesIO(data) if info.isfile() else None)
    return lzma.compress(output.getvalue())


class Response(io.BytesIO):
    status = 200
    url = F.URL

    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = {} if headers is None else headers


class FlutterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-flutter-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = members()
        self.archive = compressed(self.original)
        by_name = {info.name.removeprefix("flutter/"): data for info, data in self.original}
        self.pins = {name: sha(by_name[name]) for name in F.SDK_FILES}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(F, "ROOT", self.root))
        self.stack.enter_context(patch.object(F, "ARCHIVE_BYTES", len(self.archive)))
        self.stack.enter_context(patch.object(F, "ARCHIVE_SHA", sha(self.archive)))
        self.stack.enter_context(patch.object(F, "SDK_FILES", self.pins))
        self.stack.enter_context(patch.object(F, "load_pin", return_value="a" * 64))
        self.output_number = 0

    def output(self):
        self.output_number += 1
        return F.new_output(f"build/sdk-{self.output_number}")

    def extract(self, entries, output=None):
        return F.extract(io.BytesIO(compressed(entries)), output or self.output())

    def prepared(self):
        output = self.output()

        def acquire(destination):
            path = destination / ".sdk-archive.tar.xz"
            path.write_bytes(self.archive)
            path.chmod(0o400)
            return path

        with patch.object(F, "acquire", side_effect=acquire):
            report = F.prepare(output, "a" * 64)
        return output, report

    def test_pinned_constants_match_existing_source_contract(self):
        tree = ast.parse((ROOT / "integrations/overmorrow/build.py").read_text())
        expected = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "SDK_FILES" for target in node.targets))
        # Read only the literal assignment: do not import/execute the builder.
        source = ast.parse((ROOT / "scripts/prepare_hosted_flutter.py").read_text())
        original = next(ast.literal_eval(node.value) for node in source.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "SDK_FILES" for target in node.targets))
        self.assertEqual(original, expected)
        self.assertEqual(F.URL, "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.38.5-stable.tar.xz")
        self.assertNotIn("/flutter/", F.URL)

    def test_prepare_compact_receipt_and_original_inventory(self):
        output, report = self.prepared()
        self.assertEqual(report["files"], 9)
        self.assertLess((output / "provenance.json").stat().st_size, 2048)
        self.assertFalse((output / ".sdk-archive.tar.xz").exists())
        self.assertEqual((output / "LICENSE").read_bytes(), b"original BSD license\n")
        self.assertEqual(stat.S_IMODE((output / "bin/flutter").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((output / "sdk-inventory.json").stat().st_mode), 0o600)
        binding = F.verify_materialized(output)
        self.assertEqual(binding["files"], report["files"])
        self.assertEqual(binding["inventory_sha256"], report["inventory_sha256"])
        self.assertFalse(binding["runtime_executed"])
        self.assertEqual(report["scope"]["current_update_authority"], False)

    def test_mtime_order_does_not_trigger_flutter_self_rebuild(self):
        output, _ = self.prepared()
        source = output / "packages/flutter_tools/pubspec.yaml"
        lock = output / "packages/flutter_tools/pubspec.lock"
        self.assertEqual(source.stat().st_mtime_ns, 1700000001000000000)
        self.assertEqual(lock.stat().st_mtime_ns, 1700000002000000000)
        self.assertLess(source.stat().st_mtime_ns, lock.stat().st_mtime_ns)

    def test_download_exact_origin_bytes_hash_and_identity(self):
        output = self.output()
        opener = Mock()
        opener.open.return_value = Response(self.archive, {"Content-Length": str(len(self.archive))})
        factory = Mock(return_value=opener)
        path = F.acquire(output, factory)
        self.assertEqual(path.read_bytes(), self.archive)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, F.URL)
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
        self.assertEqual(opener.open.call_count, 1)

    def test_download_rejects_status_origin_encoding_size_and_hash(self):
        for change in ("status", "origin", "encoding", "length", "hash", "short", "long"):
            with self.subTest(change=change):
                data = self.archive
                if change == "hash":
                    data = b"x" + data[1:]
                if change == "short":
                    data = data[:-1]
                if change == "long":
                    data += b"x"
                response = Response(data)
                if change == "status":
                    response.status = 206
                if change == "origin":
                    response.url = "https://example.invalid/sdk"
                if change == "encoding":
                    response.headers["Content-Encoding"] = "gzip"
                if change == "length":
                    response.headers["Content-Length"] = "3"
                opener = Mock(open=Mock(return_value=response))
                with self.assertRaises(ValueError):
                    F.acquire(self.output(), Mock(return_value=opener))
                self.assertEqual(opener.open.call_count, 1)

    def test_no_redirect_is_authorized(self):
        with self.assertRaisesRegex(ValueError, "redirect"):
            F.R["ExactRedirect"](None).redirect_request(
                urllib.request.Request(F.URL), io.BytesIO(), 302, "Found", {}, F.URL)

    def test_bad_paths_and_duplicate_members(self):
        for name in ("/flutter/escape", "flutter/../escape", "flutter/a/./b", "flutter/a\\b",
                     "other/file", "flutter/provenance.json", "flutter/sdk-inventory.json",
                     "flutter/.sdk-archive.tar.xz", "flutter/LICENSE"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract(self.original + [member(name)])

    def test_links_specials_and_privileged_modes_not_admitted(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.extract(self.original + [member("flutter/other", b"/etc/passwd", kind=kind)])
        for mode in (0o4755, 0o2755, 0o1644):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.extract(self.original + [member("flutter/other", mode=mode)])

    def test_invalid_mtime_and_metadata(self):
        for mtime in (-1, float("nan"), float("inf"), 4102444801):
            with self.subTest(mtime=mtime), self.assertRaises(ValueError):
                value = member("flutter/other")
                value[0].pax_headers = {"mtime": str(mtime)}
                self.extract(self.original + [value])
        value = member("flutter/other")
        value[0].pax_headers = {"SCHILY.xattr.security.capability": "unsafe"}
        with self.assertRaises(ValueError):
            self.extract(self.original + [value])

    def test_payload_file_member_and_metadata_bounds(self):
        for key, limit in (("MAX_FILE", 8), ("MAX_MEMBERS", 2), ("MAX_FILES", 2), ("MAX_EXPANDED", 4096)):
            with self.subTest(key=key), patch.object(F, key, limit), self.assertRaises(ValueError):
                self.extract(self.original)
        info = F.BoundedTarInfo("metadata")
        info.type, info.size = tarfile.XHDTYPE, 8193
        with self.assertRaisesRegex(ValueError, "Oversized"):
            info._proc_member(Mock())

    def test_truncation_and_concatenated_xz_fail(self):
        for data in (self.archive[:-10], self.archive + b"garbage", self.archive + self.archive):
            with self.subTest(size=len(data)), self.assertRaises((ValueError, EOFError, lzma.LZMAError)):
                F.extract(io.BytesIO(data), self.output())

    def test_critical_file_missing_or_changed_and_no_executable_failure(self):
        for path in ("flutter/LICENSE", "flutter/.git/HEAD", "flutter/bin/cache/dart-sdk/bin/dart"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.extract([row for row in self.original if row[0].name != path])
        output = self.output()
        altered = [(info, b"changed" if info.name.endswith("flutter_tools.snapshot") else data)
                   for info, data in self.original]
        # Adjust size so this is an actual hash mismatch, not a broken tar.
        for info, data in altered:
            if info.isfile():
                info.size = len(data)
        with self.assertRaisesRegex(ValueError, "build pin"):
            self.extract(altered, output)
        self.assertEqual(stat.S_IMODE((output / "bin/flutter").stat().st_mode), 0o600)
        self.assertFalse((output / "provenance.json").exists())

    def test_fresh_output_only_and_reject_unsafe_parent(self):
        output = self.output()
        with self.assertRaises(FileExistsError):
            F.new_output(output)
        for name in ("../escape", "build/a/b", "/tmp/foreign-flutter", "build/../other"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                F.new_output(name)
        (self.root / "build").chmod(0o770)
        with self.assertRaisesRegex(ValueError, "parent"):
            F.new_output("build/next")

    def test_symlink_parent_and_output_rejected(self):
        real = self.root / "real"
        real.mkdir(mode=0o700)
        (self.root / "build").symlink_to(real)
        with self.assertRaises(ValueError):
            F.new_output("build/sdk")

    def test_build_state_only_explicit_metadata_mutates(self):
        output, _ = self.prepared()
        (output / "bin/cache/engine.stamp").write_bytes(b"changed stamp\n")
        added = output / "bin/cache/flutter.version.json"
        added.write_text('{"version":"3.38.5"}')
        added.chmod(0o600)
        with self.assertRaises(ValueError):
            F.verify_materialized(output)
        F.verify_materialized(output, allow_build_state=True)
        added.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "metadata"):
            F.verify_materialized(output, allow_build_state=True)

    def test_build_state_never_allows_cache_binary_source_or_git_changes(self):
        for relative in ("bin/cache/dart-sdk/bin/dart", "bin/cache/flutter_tools.snapshot", ".git/HEAD",
                         "packages/flutter_tools/pubspec.yaml", "bin/flutter"):
            with self.subTest(relative=relative):
                output, _ = self.prepared()
                (output / relative).write_bytes(b"changed runtime\n")
                with self.assertRaisesRegex(ValueError, "file changed"):
                    F.verify_materialized(output, allow_build_state=True)

    def test_build_state_rejects_unknown_cache_files_and_oversized_metadata(self):
        for relative, data in (("bin/cache/new-tool", b"new executable"),
                               ("bin/cache/unreviewed.stamp", b"stamp"),
                               ("bin/cache/engine.stamp", b"x" * 65537)):
            with self.subTest(relative=relative):
                output, _ = self.prepared()
                path = output / relative
                path.write_bytes(data); path.chmod(0o600)
                with self.assertRaises(ValueError):
                    F.verify_materialized(output, allow_build_state=True)

    def test_build_state_bounds_empty_directories_and_depth(self):
        output, _ = self.prepared()
        entries = sum(1 for _ in output.rglob("*"))
        with patch.object(F, "MAX_MEMBERS", entries):
            F.verify_materialized(output, allow_build_state=True)
            (output / "bin/cache/empty-added-dir").mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, "entry count"):
                F.verify_materialized(output, allow_build_state=True)
        parent = output / "bin/cache"
        for _ in range(31):
            parent /= "nested"
            parent.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
            F.verify_materialized(output, allow_build_state=True)

    def test_inventory_provenance_and_mode_tampering_rejected(self):
        for change in ("inventory", "provenance", "symlink", "hardlink", "mode"):
            with self.subTest(change=change):
                output, _ = self.prepared()
                if change == "inventory":
                    (output / "sdk-inventory.json").write_bytes(b"{}\n")
                if change == "provenance":
                    value = json.loads((output / "provenance.json").read_bytes())
                    value["unexpected"] = "not allowed"
                    (output / "provenance.json").write_bytes(F.canonical(value))
                if change in ("symlink", "hardlink"):
                    path = output / "LICENSE"
                    path.unlink()
                    if change == "symlink":
                        path.symlink_to(output / "bin/flutter")
                    else:
                        os.link(output / "bin/flutter", path)
                if change == "mode":
                    (output / "bin/flutter").chmod(0o777)
                with self.assertRaises((ValueError, OSError)):
                    F.verify_materialized(output, allow_build_state=True)

    def test_changed_file_diagnostic_is_bounded_relative_path_and_kind_only(self):
        for kind in ("size", "mode", "sha256"):
            with self.subTest(kind=kind):
                output, _ = self.prepared()
                path = output / ".git/HEAD"
                original = path.read_bytes()
                if kind == "size":
                    path.write_bytes(original + b"x")
                elif kind == "mode":
                    path.chmod(0o400)
                else:
                    path.write_bytes(b"x" * len(original))
                with self.assertRaises(ValueError) as raised:
                    F.verify_materialized(output, allow_build_state=True)
                self.assertEqual(str(raised.exception), f"SDK file changed: .git/HEAD ({kind})")
                self.assertNotIn(str(output), str(raised.exception))
                self.assertNotIn(original.decode().strip(), str(raised.exception))

    def test_cli_requires_explicit_fetch_without_touching_output(self):
        with patch("sys.argv", ["prepare", "--output", "build/sdk"]), patch.object(F, "prepare") as prepare:
            with self.assertRaises(SystemExit) as result:
                F.main()
        self.assertEqual(result.exception.code, 2)
        prepare.assert_not_called()
        self.assertFalse((self.root / "build").exists())


if __name__ == "__main__":
    unittest.main()
