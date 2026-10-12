# SPDX-License-Identifier: GPL-3.0-only
"""Pure wrapper regressions, not actual browser or core proof."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("table_smoke", HERE / "smoke_table_browser.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def observation(expected):
    sections = []
    for name, product in expected["products"].items():
        d = product["display"]
        model, run = d["model_run"].split(" · ")
        sections.append(dict(product=name, labels=[d["coordinates"], f"Model {model}; run {run}",
            "Acquired " + d["acquired_at"], "Expires " + d["expires_at"], d["attribution"],
            d["license"] + ": " + d["license_url"], d["changes"],
            "Core-cache delivery; schema and freshness checked. Origin authenticity is not attested.",
            "AQI, pollen and health advice: not available" if name == "air_quality" else
            "Current observations, daily totals/extrema, UV, humidity and hourly interpolation: not available"],
            tables=[dict(headers=list(driver.tables.HEADERS[name]), rows=[[when, *row]
                for when, row in zip(d["native"], d["values"])])]))
    return dict(sections=sections, localOnly=True, weatherRequests=1, airQualityRequests=1,
                wasmLoaded=True, canvas=True, location="/")


class FakeSocket:
    def __init__(self): self.timeouts = []
    def settimeout(self, value): self.timeouts.append(value)


class FakeClient:
    def __init__(self): self.socket = FakeSocket()


class FakeClock:
    def __init__(self): self.value = 0
    def now(self): return self.value
    def advance(self, _seconds): self.value += 10


class SyntheticTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = os.environ.get("VOLPAROSSA_TEST_NODE")
        if not node:
            raise RuntimeError("VOLPAROSSA_TEST_NODE must select the verified runtime")
        script = """
import { tableProducts, capturedResponse } from './integrations/overmorrow/table-fixture.mjs';
const {base}=tableProducts('2026-10-12T01:00:00.000Z');
console.log(JSON.stringify({weather:capturedResponse(base,false,'2026-10-12T01:00:01.001Z').value,
air_quality:capturedResponse(base,true,'2026-10-12T01:00:02.002Z').value}));
"""
        result = subprocess.run([node, "--input-type=module", "-e", script], cwd=HERE.parent.parent,
                                check=True, capture_output=True, text=True, timeout=10)
        cls.bodies = json.loads(result.stdout)

    def test_actual_body_timestamps_and_values_are_used_without_regeneration(self):
        value = driver.expected_display(self.bodies)
        weather, aq = [value["products"][key]["display"] for key in ("weather", "air_quality")]
        self.assertEqual(weather["acquired_at"], "2026-10-12T01:00:01.001Z")
        self.assertEqual(aq["acquired_at"], "2026-10-12T01:00:02.002Z")
        self.assertNotEqual(weather["expires_at"], aq["expires_at"])
        self.assertEqual(len(weather["native"]), 4)
        self.assertEqual(len(aq["native"]), 5)
        self.assertEqual(weather["values"][1][:3], ["Not available", "0", "Not available"])
        self.assertEqual(weather["values"][0][3], "0.01234")
        self.assertEqual(weather["values"][2][3], "Not available")
        self.assertNotIn("schema", value)  # Never pretend this is a cold-core expected.json.
        self.assertNotIn("cold_receipt_sha256", json.dumps(value))

    def test_each_timestamp_change_is_reflected_and_bound(self):
        original = driver.expected_display(self.bodies)
        changed = copy.deepcopy(self.bodies)
        changed["weather"]["forecast"]["source"]["acquired_at"] = "2026-10-12T01:00:03.003Z"
        result = driver.expected_display(changed)
        self.assertNotEqual(original["display_sha256"], result["display_sha256"])
        self.assertEqual(original["products"]["air_quality"], result["products"]["air_quality"])

    def test_private_capture_same_descriptor_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product.json"
            path.write_text(json.dumps(self.bodies["weather"]))
            path.chmod(0o600)
            value, _ = driver.captured(path)
            self.assertEqual(value, self.bodies["weather"])
            path.chmod(0o644)
            with self.assertRaises(ValueError): driver.captured(path)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError): driver.captured(link)

    def test_unchanged_verifier_and_existing_sandbox_are_the_only_runtime_route(self):
        source = (HERE / "smoke_table_browser.py").read_text()
        for literal in ("tables.snapshot(client)", "tables.observed_products(observed, expected, ordinal)",
                        "ui.pointer_activate(client", "ui.main(entry_path=Path(__file__)"):
            self.assertIn(literal, source)
        self.assertNotIn("tables.main(", source)
        self.assertNotIn("validate_expected(", source)
        self.assertNotIn("fetch(", source)

    def test_closed_diagnostics_identify_metadata_headers_times_and_values_without_raw_text(self):
        expected = driver.expected_display(self.bodies)
        observed = observation(expected)
        good = driver.table_diagnostic(observed, expected)
        self.assertTrue(all(good[key] for key in ("shape_valid", "local_only", "wasm_loaded", "canvas", "root_route")))
        self.assertEqual([s["row_count"] for s in good["sections"]], [4, 5])
        self.assertTrue(all(all(s["metadata_matches"].values()) for s in good["sections"]))
        observed["sections"][0]["labels"][0] = "private text must never be recorded"
        observed["sections"][0]["tables"][0]["headers"][0] = "sensitive header"
        observed["sections"][0]["tables"][0]["rows"][0][0] = "sensitive timestamp"
        value = driver.table_diagnostic(observed, expected)
        weather = value["sections"][0]
        self.assertFalse(weather["metadata_matches"]["coordinates"])
        self.assertFalse(weather["headers_match"])
        self.assertEqual(weather["first_row_mismatch"], dict(row=0, column=0, kind="native_time"))
        text = json.dumps(value)
        self.assertNotIn("private", text)
        self.assertNotIn("sensitive", text)
        self.assertNotIn("2026-", text)
        self.assertLess(len(text), 3000)
        for value in (None, [], {}, {"sections": [None, {"product": "private secret"}]}):
            self.assertNotIn("private secret", json.dumps(driver.table_diagnostic(value, expected)))

    def test_transient_render_gap_retries_exact_assertions_without_reissuing_requests(self):
        expected = driver.expected_display(self.bodies)
        final = observation(expected)
        initial = {**final, "sections": []}
        clock, client, diagnostic = FakeClock(), FakeClient(), {}
        with patch.object(driver.tables, "snapshot", side_effect=[initial, final]) as snapshot, \
             patch.object(driver.ui, "button_state", return_value={}), patch.object(driver.ui, "button_ready", return_value=True):
            actual = driver.wait_tables(client, expected, 1, diagnostic, clock=clock.now, pause=clock.advance)
        self.assertEqual(driver.tables.digest(actual), expected["display_sha256"])
        self.assertEqual(snapshot.call_count, 2)
        self.assertEqual(diagnostic["attempts"], 2)
        self.assertEqual(client.socket.timeouts[-1], 15)

    def test_permanent_row_mutation_never_passes_and_keeps_last_bounded_diagnostic(self):
        expected = driver.expected_display(self.bodies)
        observed = observation(expected)
        observed["sections"][0]["tables"][0]["rows"].reverse()
        clock, client, diagnostic = FakeClock(), FakeClient(), {}
        with patch.object(driver.tables, "snapshot", return_value=observed) as snapshot, \
             patch.object(driver.ui, "button_state", return_value={}), patch.object(driver.ui, "button_ready", return_value=True):
            with self.assertRaises(TimeoutError):
                driver.wait_tables(client, expected, 1, diagnostic, clock=clock.now, pause=clock.advance)
        self.assertEqual(snapshot.call_count, 6)
        self.assertEqual(diagnostic["last"]["sections"][0]["first_row_mismatch"]["kind"], "native_time")
        self.assertEqual(client.socket.timeouts[-1], 15)

    def test_exact_tables_still_wait_for_real_refresh_readiness(self):
        expected = driver.expected_display(self.bodies)
        clock, client, diagnostic = FakeClock(), FakeClient(), {}
        with patch.object(driver.tables, "snapshot", return_value=observation(expected)), \
             patch.object(driver.ui, "button_state", return_value={}), patch.object(driver.ui, "button_ready", side_effect=[False, True]):
            driver.wait_tables(client, expected, 1, diagnostic, clock=clock.now, pause=clock.advance)
        self.assertEqual(diagnostic["attempts"], 2)
        self.assertTrue(diagnostic["refresh_ready"])

    def test_extractor_runtime_error_is_not_hidden_or_retried(self):
        clock, client, diagnostic = FakeClock(), FakeClient(), {}
        with patch.object(driver.tables, "snapshot", side_effect=RuntimeError("extractor failed")) as snapshot:
            with self.assertRaises(RuntimeError):
                driver.wait_tables(client, driver.expected_display(self.bodies), 1, diagnostic,
                                   clock=clock.now, pause=clock.advance)
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(client.socket.timeouts[-1], 15)


if __name__ == "__main__":
    unittest.main()
