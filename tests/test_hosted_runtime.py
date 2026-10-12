"""Offline format/fault tests only: no real runtime, download, browser or package install."""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import signal
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hosted_runtime", ROOT / "scripts/prepare_hosted_runtime.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def tar_bytes(members):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, value, kind, mode in members:
            entry = tarfile.TarInfo(name)
            entry.mode = mode
            if kind == "file":
                entry.size = len(value)
                archive.addfile(entry, io.BytesIO(value))
            else:
                entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                              "directory": tarfile.DIRTYPE, "fifo": tarfile.FIFOTYPE}[kind]
                if kind in ("symlink", "hardlink"):
                    entry.linkname = value
                archive.addfile(entry)
    return data.getvalue()


def ar_bytes(members):
    value = b"!<arch>\n"
    for name, data in members:
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
        assert len(header) == 60
        value += header + data + (b"\n" if len(data) % 2 else b"")
    return value


def deb_bytes(members):
    # This malicious-looking maintainer script is inert envelope content. The
    # materializer never decompresses or launches the control archive.
    control = lzma.compress(tar_bytes([("preinst", b"exit 99\n", "file", 0o755)]))
    return ar_bytes([("debian-binary", b"2.0\n"), ("control.tar.xz", control),
                     ("data.tar.xz", lzma.compress(tar_bytes(members)))])


def fixture():
    pin = json.loads((ROOT / "third_party/hosted-runtime-inputs.json").read_text())
    members = {
        "node": [("node-v24.19.0-linux-x64/bin/node", b"not an executable", "file", 0o755),
                 ("node-v24.19.0-linux-x64/LICENSE", b"Original Node license\n", "file", 0o644),
                 ("node-v24.19.0-linux-x64/bin/npm", "../lib/node_modules/npm/bin/npm-cli.js", "symlink", 0o777)],
        "firefox": [("./usr/lib/firefox-esr/" + name, ("fixture " + name).encode(), "file",
                     0o755 if name == "firefox-esr" else 0o644)
                    for name in pin["artifacts"]["firefox"]["expected_files"]] + [
                        ("./usr/lib/firefox-esr/firefox-bin", "firefox-esr", "symlink", 0o777),
                        ("./usr/lib/firefox-esr/browser/defaults/syspref", "/etc/firefox-esr", "symlink", 0o777),
                        ("./usr/lib/firefox-esr/distribution/policies.json", b"host settings", "file", 0o644),
                        ("./usr/share/doc/firefox-esr/copyright", b"Original Debian/Mozilla copyright\n", "file", 0o644)],
    }
    for kind in ("node", "firefox"):
        by_name = {name.removeprefix("./"): value for name, value, typ, _ in members[kind] if typ == "file"}
        for name in pin["artifacts"][kind]["expected_files"]:
            value = by_name[pin["artifacts"][kind]["prefix"] + "/" + name]
            pin["artifacts"][kind]["expected_files"][name] = {"bytes": len(value), "sha256": sha(value)}
    return pin, members


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-runtime-unit-")
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir(mode=0o700)
        self.output = self.root / "output"
        self.output.mkdir(mode=0o700)
        self.pin, self.members = fixture()

    def tearDown(self):
        self.temporary.cleanup()

    def archives(self):
        for kind, item in self.pin["artifacts"].items():
            data = (lzma.compress(tar_bytes(self.members[kind])) if kind == "node"
                    else deb_bytes(self.members[kind]))
            item.update(bytes=len(data), sha256=sha(data))
            path = self.cache / item["archive"]
            path.write_bytes(data)
            path.chmod(0o600)

    def run_prepare(self):
        self.archives()
        with patch.object(urllib.request, "urlopen", side_effect=AssertionError("network prohibited")):
            return R.prepare(self.output, self.pin, "a" * 64, self.cache)

    def test_committed_pins_are_closed_and_historical(self):
        pin, digest = R.load_pin()
        self.assertEqual(pin["artifacts"]["node"]["bytes"], 31633904)
        self.assertEqual(pin["artifacts"]["firefox"]["bytes"], 71994716)
        self.assertEqual(pin["artifacts"]["node"]["expected_files"]["bin/node"]["sha256"],
                         "bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12")
        self.assertTrue(R.hex64(digest))

    def test_offline_materialization_hashes_licenses_modes_and_scope(self):
        report = self.run_prepare()
        self.assertTrue(report["scope"]["expected_runtime_hashes_verified"])
        self.assertTrue(report["scope"]["licenses_preserved"])
        for name in ("runtime_executed", "host_installed", "source_build", "host_abi_verified",
                     "browser_proof_performed", "legacy_bundle_equivalent", "current_update_authority"):
            self.assertFalse(report["scope"][name])
        self.assertEqual((self.output / "firefox/firefox-esr").read_bytes(),
                         (self.output / "firefox/firefox-bin").read_bytes())
        self.assertEqual((self.output / "licenses/firefox-copyright").read_bytes(), b"Original Debian/Mozilla copyright\n")
        self.assertEqual((self.output / "node/LICENSE").read_bytes(), b"Original Node license\n")
        self.assertFalse((self.output / "firefox/browser/defaults/syspref").exists())
        self.assertFalse((self.output / "firefox/distribution").exists())
        for path in self.output.rglob("*"):
            self.assertFalse(path.is_symlink())
            self.assertFalse(path.stat().st_mode & 0o077)
        self.assertEqual(stat.S_IMODE((self.output / "node/bin/node").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.output / "provenance.json").stat().st_mode), 0o600)

    def test_no_fetch_by_default(self):
        opener = Mock(side_effect=AssertionError("must not contact network"))
        with self.assertRaisesRegex(ValueError, "--fetch"):
            R.acquire(self.pin["artifacts"]["node"], self.output, self.cache, False, opener)
        opener.assert_not_called()

    def test_archive_mismatch_prevents_extraction(self):
        self.archives()
        self.pin["artifacts"]["node"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256"):
            R.prepare(self.output, self.pin, "a" * 64, self.cache)
        self.assertFalse((self.output / "node").exists())
        self.assertFalse((self.output / "provenance.json").exists())

    def test_extracted_mismatch_leaves_both_runtimes_nonexecutable(self):
        self.pin["artifacts"]["firefox"]["expected_files"]["libxul.so"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "executable/library"):
            self.run_prepare()
        self.assertFalse((self.output / "node/bin/node").stat().st_mode & 0o111)
        self.assertFalse((self.output / "firefox/firefox-esr").stat().st_mode & 0o111)
        self.assertFalse((self.output / "provenance.json").exists())

    def test_existing_output_and_nonprivate_output_rejected(self):
        (self.output / "existing").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "fresh private"):
            R.prepare(self.output, self.pin, "a" * 64, self.cache)
        self.assertEqual((self.output / "existing").read_text(), "preserve")
        self.output.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "fresh private"):
            R.prepare(self.output, self.pin, "a" * 64, self.cache)

    def test_output_must_be_new_canonical_build_child(self):
        with patch.object(R, "ROOT", self.root):
            output = R.new_output("build/new")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            with self.assertRaises(FileExistsError):
                R.new_output("build/new")
            for value in ("build", "other/new", "build/nested/new", "build/../outside"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    R.new_output(value)

    def test_group_writable_or_symlink_build_parent_rejected(self):
        build = self.root / "build"
        build.mkdir(mode=0o770)
        build.chmod(0o770)
        with patch.object(R, "ROOT", self.root), self.assertRaisesRegex(ValueError, "Build parent"):
            R.new_output("build/new")
        build.rmdir()
        build.symlink_to(self.cache, target_is_directory=True)
        with patch.object(R, "ROOT", self.root), self.assertRaisesRegex(ValueError, "Build parent"):
            R.new_output("build/new")

    def test_cache_symlinks_hardlinks_and_writable_files_rejected(self):
        source = self.root / "source"
        source.write_bytes(b"cache")
        source.chmod(0o600)
        link = self.root / "symlink"
        link.symlink_to(source)
        with self.assertRaises(OSError):
            R.regular_input(link)
        link.unlink()
        os.link(source, link)
        with self.assertRaises(ValueError):
            R.regular_input(source)
        link.unlink()
        source.chmod(0o666)
        with self.assertRaises(ValueError):
            R.regular_input(source)

    def test_cache_fifo_without_writer_is_rejected_without_blocking(self):
        fifo = self.cache / "fifo"
        os.mkfifo(fifo, 0o600)
        # A missing O_NONBLOCK becomes a deterministic timeout failure, not a
        # test-suite hang. The expected path is immediate regular-file rejection.
        with R.deadline(1), self.assertRaisesRegex(ValueError, "regular file"):
            R.regular_input(fifo)

    def test_reject_traversal_duplicate_special_and_setuid_members(self):
        for member in [("../escape", b"x", "file", 0o644),
                       ("/escape", b"x", "file", 0o644),
                       ("node-v24.19.0-linux-x64/bin/node", b"duplicate", "file", 0o644),
                       ("pipe", b"", "fifo", 0o600),
                       ("setuid", b"x", "file", 0o4755)]:
            with self.subTest(member=member[0]):
                root = self.output / str(len(list(self.output.iterdir())))
                root.mkdir(mode=0o700)
                source = io.BytesIO(lzma.compress(tar_bytes(self.members["node"] + [member])))
                with self.assertRaises(ValueError):
                    R.extract(source, root, "node", self.pin["artifacts"]["node"])

    def test_forward_hardlinks_are_materialized_without_linking(self):
        self.members["firefox"].insert(0, ("./usr/lib/firefox-esr/second", "./usr/lib/firefox-esr/firefox-bin", "hardlink", 0o644))
        self.run_prepare()
        path = self.output / "firefox/second"
        self.assertEqual(path.read_bytes(), (self.output / "firefox/firefox-esr").read_bytes())
        self.assertEqual(path.stat().st_nlink, 1)

    def test_link_escape_cycle_and_missing_target_rejected(self):
        for target in ("../../../../etc/passwd", "/etc/passwd", "missing", "firefox-bin"):
            with self.subTest(target=target):
                root = self.output / str(len(list(self.output.iterdir())))
                root.mkdir(mode=0o700)
                members = [entry if entry[0] != "./usr/lib/firefox-esr/firefox-bin"
                           else (entry[0], target, "symlink", 0o777) for entry in self.members["firefox"]]
                with self.assertRaises(ValueError):
                    R.extract(io.BytesIO(lzma.compress(tar_bytes(members))), root, "firefox", self.pin["artifacts"]["firefox"])

    def test_missing_original_license_rejected(self):
        for kind in ("node", "firefox"):
            root = self.output / kind
            root.mkdir(mode=0o700)
            members = [entry for entry in self.members[kind] if not entry[0].endswith(("LICENSE", "copyright"))]
            with self.assertRaisesRegex(ValueError, "license"):
                R.extract(io.BytesIO(lzma.compress(tar_bytes(members))), root, kind, self.pin["artifacts"][kind])

    def test_xz_truncation_trailing_data_and_expansion_cap(self):
        valid = lzma.compress(b"x" * 1000)
        for data in (valid[:-4], valid + b"extra"):
            with self.subTest(data=data[-6:]), self.assertRaises(ValueError):
                reader = R.BoundedXZ(io.BytesIO(data))
                while reader.read(64):
                    pass
        with patch.object(R, "MAX_EXPANDED", 99), self.assertRaisesRegex(ValueError, "Expanded archive"):
            R.BoundedXZ(io.BytesIO(valid)).read(100)

    def test_member_size_bound(self):
        with patch.object(R, "MAX_FILE", 3), self.assertRaisesRegex(ValueError, "size"):
            R.extract(io.BytesIO(lzma.compress(tar_bytes(self.members["node"]))),
                      self.output, "node", self.pin["artifacts"]["node"])

    def test_deb_envelope_rejects_extra_truncation_and_wrong_version(self):
        valid = deb_bytes(self.members["firefox"])
        for number, data in enumerate((b"badmagic" + valid[8:], valid[:-3], valid + b"extra",
                                      ar_bytes([("debian-binary", b"1.0\n"), ("control.tar.xz", b"x"), ("data.tar.xz", b"x")]))):
            path = self.cache / str(number)
            path.write_bytes(data)
            with path.open("rb") as source, self.assertRaises(ValueError):
                R.deb_data(source)

    def fake_fetch(self, *, body=b"archive", status=200, url=None, headers=None, item=None):
        item = deepcopy(item or self.pin["artifacts"]["node"])
        item.update(bytes=7, sha256=sha(b"archive"))
        response = io.BytesIO(body)
        response.status = status
        response.url = url or item["url"]
        response.headers = {"Content-Length": "7"} if headers is None else headers
        opener = Mock()
        opener.open.return_value = response
        factory = Mock(return_value=opener)
        return item, response, opener, factory

    def test_explicit_fetch_once_without_range_cookie_or_execution(self):
        item, response, opener, factory = self.fake_fetch()
        result = R.acquire(item, self.output, None, True, factory)
        self.assertEqual(result.read_bytes(), b"archive")
        self.assertTrue(response.closed)
        self.assertEqual(opener.open.call_count, 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, item["url"])
        self.assertEqual(request.header_items(), [("Accept-encoding", "identity")])
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o400)

    def test_fetch_rejects_status_url_length_encoding_and_body_faults(self):
        cases = [dict(status=429), dict(status=206), dict(url="https://unapproved.invalid/archive"),
                 dict(headers={"Content-Length": "8"}), dict(headers={"Content-Encoding": "gzip"}),
                 dict(body=b"archiv"), dict(body=b"archivex"), dict(body=b"tampered"[:7])]
        for number, kwargs in enumerate(cases):
            with self.subTest(kwargs=kwargs):
                directory = self.output / str(number)
                directory.mkdir(mode=0o700)
                item, response, opener, factory = self.fake_fetch(**kwargs)
                with self.assertRaises(ValueError):
                    R.acquire(item, directory, None, True, factory)
                self.assertTrue(response.closed)
                self.assertEqual(opener.open.call_count, 1)

    def test_http_error_body_is_closed_without_reading(self):
        body = Mock()
        error = urllib.error.HTTPError(self.pin["artifacts"]["node"]["url"], 429, "limited", {}, body)
        opener = Mock()
        opener.open.side_effect = error
        with self.assertRaises(urllib.error.HTTPError) as raised:
            R.acquire(self.pin["artifacts"]["node"], self.output, None, True, Mock(return_value=opener))
        self.assertIs(raised.exception, error)
        body.close.assert_called_once()
        body.read.assert_not_called()

    def test_only_one_exact_redirect_permitted(self):
        url = self.pin["artifacts"]["firefox"]["redirect_url"]
        request = urllib.request.Request(self.pin["artifacts"]["firefox"]["url"])
        handler = R.ExactRedirect(url)
        first = io.BytesIO()
        self.assertEqual(handler.redirect_request(request, first, 302, "redirect", {}, url).full_url, url)
        second = io.BytesIO()
        with self.assertRaises(ValueError):
            handler.redirect_request(request, second, 302, "redirect", {}, url)
        self.assertTrue(second.closed)
        rejected = io.BytesIO()
        with self.assertRaises(ValueError):
            R.ExactRedirect(url).redirect_request(request, rejected, 302, "redirect", {}, "http://snapshot.debian.org/file/a")
        self.assertTrue(rejected.closed)

    def test_absolute_deadline_restores_signal_state(self):
        original = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError):
            with R.deadline(0.005):
                signal.pause()
        self.assertEqual(signal.getsignal(signal.SIGALRM), original)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
