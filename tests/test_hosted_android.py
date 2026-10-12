# SPDX-License-Identifier: GPL-3.0-only
"""Inert archive/contract tests: no Android/Java/Flutter process is executed."""
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


if __name__ == "__main__":
    unittest.main()
