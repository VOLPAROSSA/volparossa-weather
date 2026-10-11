# SPDX-License-Identifier: GPL-3.0-only
"""Pure harness checks; importing must not load Firefox helpers or start a server."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("overmorrow_smoke", Path(__file__).with_name("smoke_browser.py"))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class BrowserHarnessTests(unittest.TestCase):
    def test_canonical_hash_is_order_independent(self):
        self.assertEqual(driver.canonical_hash({"a": 1, "b": 2}), driver.canonical_hash({"b": 2, "a": 1}))

    def test_actual_semantic_labels_can_be_merged(self):
        value = {"labels": ["Native weather forecast\n2026-10-11T03:00:00.000Z\n0.01"]}
        self.assertTrue(driver.labels_contain(value, "Native weather forecast", "0.01"))
        self.assertFalse(driver.labels_contain(value, "Native particulate forecast"))

    def test_malformed_semantic_labels_fail(self):
        for value in (None, [], {}, {"labels": "Native"}, {"labels": [None]}):
            self.assertFalse(driver.labels_contain(value, "Native"))

    def test_snapshot_bounds_and_real_semantics_are_explicit(self):
        class Client:
            source = None
            def script(self, source):
                self.source = source
                return {"labels": []}
        client = Client()
        driver.snapshot(client)
        for expected in ("flt-semantics", "unique.length>600", "s.length>8192", ">32768", "resources.length>256"):
            self.assertIn(expected, client.source)
        self.assertNotIn("document.body.textContent", client.source)

    def test_interactions_only_allow_known_actual_app_buttons(self):
        class Client:
            def script(self, source):
                return True
        self.assertTrue(driver.click_label(Client(), "Refresh forecasts"))
        with self.assertRaises(ValueError):
            driver.click_label(Client(), "arbitrary injected text" )


if __name__ == "__main__":
    unittest.main()
