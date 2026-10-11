#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert joined-proof checks; no browser, server, SDK, core or weather requests."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("overmorrow_core_smoke", HERE / "smoke_core_browser.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def projected(expected):
    sections = []
    for name, product in expected["products"].items():
        display = product["display"]
        model, run = display["model_run"].split(" · ")
        labels = ["Native weather forecast" if name == "weather" else "Native particulate forecast",
            display["coordinates"], f"Model {model}; run {run}", "Acquired " + display["acquired_at"],
            "Expires " + display["expires_at"], display["attribution"], display["license"] + ": " + display["license_url"],
            display["changes"], "Core-cache delivery; schema and freshness checked. Origin authenticity is not attested.",
            ("AQI, pollen and health advice: not available" if name == "air_quality" else
             "Current observations, daily totals/extrema, UV, humidity and hourly interpolation: not available")]
        sections.append(dict(product=name, labels=labels, tables=[dict(headers=driver.HEADERS[name],
            rows=[[when, *row] for when, row in zip(display["native"], display["values"])])]))
    return dict(sections=sections, localOnly=True, weatherRequests=1, airQualityRequests=1,
                wasmLoaded=True, canvas=True, location="/")


class CoreBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get("VOLPAROSSA_TEST_NODE") or shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("set VOLPAROSSA_TEST_NODE to the existing verified Node binary")
        browser_root = os.environ.get("VOLPAROSSA_TEST_BROWSER_ROOT")
        if not browser_root:
            # Local worktrees are nested beneath weather/.git; bundle runtime
            # uses the normal sibling layout and does not need this test option.
            candidates = [driver.ROOT.parent / "volparossa-browser", driver.ROOT.parents[2] / "volparossa-browser"]
            browser_root = next((str(path) for path in candidates if (path / "scripts/smoke_privacy.py").is_file()), None)
        if not browser_root:
            raise unittest.SkipTest("set VOLPAROSSA_TEST_BROWSER_ROOT to existing browser helper source")
        with patch.object(sys, "argv", ["inert-test", "--browser-root", browser_root]):
            driver.core_helpers()
        result = subprocess.run([cls.node, str(HERE / "test_prepare_core_browser.mjs"), "--fixture"],
                                check=True, capture_output=True, text=True, timeout=10)
        value = json.loads(result.stdout)
        cls.expected, cls.config = value["expected"], value["config"]

    def test_expected_cross_language_hashes_and_raw_samples_match(self):
        self.assertIs(driver.validate_expected(self.expected, self.config), self.expected)
        products = driver.observed_products(projected(self.expected), self.expected, 1)
        self.assertEqual(driver.digest(products), self.expected["display_sha256"])
        self.assertEqual(len(products["weather"]["native"]), 4)
        self.assertEqual(len(products["air_quality"]["native"]), 5)
        self.assertNotEqual(products["weather"]["model_run"], products["air_quality"]["model_run"])
        self.assertNotEqual(products["weather"]["expires_at"], products["air_quality"]["expires_at"])

    def test_dart_redundant_decimal_zero_is_normalized_without_rounding(self):
        value = projected(self.expected)
        value["sections"][0]["tables"][0]["rows"][0][1] = "10.0"
        value["sections"][0]["tables"][0]["rows"][1][2] = "0.0"
        self.assertEqual(driver.digest(driver.observed_products(value, self.expected, 1)), self.expected["display_sha256"])
        for left, right in (("1.0000000000000001", "1"), ("NaN", "NaN"), ("Not available", "0"),
                            ("Infinity", "Infinity"), (True, "1"), ("216.9", "216.86989764584405")):
            self.assertFalse(driver.number_equal(left, right))

    def test_row_order_duplicate_drop_and_pm_column_swap_fail(self):
        def reorder(v): v["sections"][0]["tables"][0]["rows"].reverse()
        def duplicate(v): v["sections"][0]["tables"][0]["rows"][1] = v["sections"][0]["tables"][0]["rows"][0][:]
        def drop(v): v["sections"][1]["tables"][0]["rows"].pop()
        def transpose(v): v["sections"][1]["tables"][0]["rows"][0][1:] = v["sections"][1]["tables"][0]["rows"][0][:0:-1]
        for change in (reorder, duplicate, drop, transpose):
            value = projected(self.expected); change(value)
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                driver.observed_products(value, self.expected, 1)

    def test_missing_zero_window_and_rounding_are_not_interchangeable(self):
        for product, row, column, value in ((0, 0, 3, "216.9"), (0, 1, 1, "0"), (0, 1, 3, "0"),
                                          (0, 2, 4, "0"), (0, 0, 5, "Not available"), (1, 0, 1, "0")):
            observed = projected(self.expected)
            observed["sections"][product]["tables"][0]["rows"][row][column] = value
            with self.subTest(value=value, cell=(product, row, column)), self.assertRaises(ValueError):
                driver.observed_products(observed, self.expected, 1)

    def test_attribution_expiry_and_native_metadata_are_bound_to_the_product_section(self):
        for prefix in ("Model ", "Acquired ", "Expires ", "Public community area:", "ECMWF", "CC-BY-4.0"):
            observed = projected(self.expected)
            index = next(i for i, label in enumerate(observed["sections"][0]["labels"]) if label.startswith(prefix))
            # Merely having it somewhere else on the page must not pass.
            label = observed["sections"][0]["labels"].pop(index)
            observed["sections"][1]["labels"].append(label)
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                driver.observed_products(observed, self.expected, 1)

    def test_no_foreign_resources_extra_requests_wrong_route_or_fake_renderer(self):
        for key, value in (("localOnly", False), ("weatherRequests", 2), ("airQualityRequests", 0),
                           ("weatherRequests", True), ("canvas", False), ("wasmLoaded", False), ("location", "/demo")):
            observed = projected(self.expected); observed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                driver.observed_products(observed, self.expected, 1)

    def test_expected_rehashed_display_still_must_match_raw_forecast_and_source(self):
        for change in (
            lambda e: e["products"]["weather"]["display"]["values"][0].__setitem__(0, "11"),
            lambda e: e["products"]["air_quality"]["display"].__setitem__("attribution", "Different source"),
            lambda e: e["products"]["weather"]["display"].__setitem__("coordinates", "Public community area: 1, 2"),
            lambda e: e["products"]["weather"]["display"].__setitem__("acquired_at", "2020-01-01T00:00:00.000Z"),
        ):
            value = copy.deepcopy(self.expected); change(value)
            for product in value["products"].values(): product["display_sha256"] = driver.digest(product["display"])
            value["display_sha256"] = driver.digest({name: product["display"] for name, product in value["products"].items()})
            with self.assertRaises(ValueError): driver.validate_expected(value, self.config)

    def test_report_scope_remains_closed_and_not_browser_first_cold(self):
        source = dict(bundle_manifest_sha256="a" * 64, driver_sha256="b" * 64, preparer_sha256="c" * 64,
            built_tree_sha256="d" * 64, node_sha256="e" * 64, bridge_modules={name: "f" * 64 for name in driver.BRIDGE_MODULES})
        report = driver.report_base(source, self.expected)
        self.assertEqual(report["schema"], 3)
        self.assertNotIn("actual_drizzli_ui", report["scope"])
        self.assertFalse(report["scope"]["actual_overmorrow_ui"])
        self.assertFalse(report["scope"]["browser_triggered_cold_fetch"])
        self.assertFalse(report["scope"]["synthetic_weather"])
        self.assertEqual(set(report), {"schema", "passed", "phase", "source", "expected", "products", "scope", "checks", "cleanup"})
        # The retained report contains hashes/closed flags, never table/raw data.
        self.assertNotIn("Native valid time", json.dumps(report))
        self.assertLess(len(driver.canonical(report)) + 2048, 16384)

    def test_actual_semantic_table_extractor_preserves_rows_cell_ownership_and_repeated_values(self):
        observed = projected(self.expected)
        script = r"""
class Element {
  constructor(tag,id='',attrs={}) {this.tagName=tag;this.id=id;this.attrs=attrs;this.parentElement=null;
    this.childNodes=[];this.nodeType=1;this.hidden=false;}
  append(child){child.parentElement=this;this.childNodes.push(child);return child;}
  getAttribute(key){return this.attrs[key]??null;}
  get childElementCount(){return this.childNodes.filter(n=>n.nodeType===1).length;}
  get textContent(){return this.childNodes.map(n=>n.textContent).join('');}
  querySelectorAll(tag){const out=[];for(const c of this.childNodes)if(c.nodeType===1){
    if(c.tagName===tag)out.push(c);out.push(...c.querySelectorAll(tag));}return out;}
}
let next=1;const nodes=[],root=new Element('root');
function semantic(parent,role,label,kind='aria'){
  const e=parent.append(new Element('flt-semantics','flt-semantic-node-'+next++,role?{role}:{}));nodes.push(e);
  if(label!==undefined){if(kind==='aria')e.attrs['aria-label']=label;
    else if(kind==='text')e.append({nodeType:3,textContent:label});
    else e.append(new Element('span')).append({nodeType:3,textContent:label});}return e;}
for(const section of INPUT.sections){
  semantic(root,null,section.labels.slice(0,5).join('\n'));
  const table=semantic(root,'table');
  const all=[section.tables[0].headers,...section.tables[0].rows];
  for(const [i,row] of all.entries()){
    const r=semantic(table,'row');
    for(const [j,cell] of row.entries()){
      const c=semantic(r,i===0?'columnheader':'cell');
      // Exercise wrapped cell children, sized spans, direct text and aria labels.
      semantic(c,null,cell,['span','text','aria'][j%3]);
    }
  }
  for(const label of section.labels.slice(5))semantic(root,null,label,'text');
}
// Neither a hidden stale table nor unrelated HTML is part of the proof.
const hidden=semantic(root,'table');hidden.attrs['aria-hidden']='true';
root.append(new Element('h1')).append({nodeType:3,textContent:'not application data'});
nodes.push(new Element('canvas'));
const location={origin:'http://127.0.0.1:3210',pathname:'/'};
const resources=['/api/volparossa/forecast','/api/volparossa/air-quality','/canvaskit/canvaskit.wasm']
  .map(s=>({name:location.origin+s,responseEnd:1}));
const result=new Function('nodes','getComputedStyle','performance','location',EXTRACT)(nodes,
  ()=>({display:'block',visibility:'visible'}),{getEntriesByType:()=>resources},location);
process.stdout.write(JSON.stringify(result));
""".replace("INPUT", json.dumps(observed)).replace("EXTRACT", json.dumps(driver.TABLES_JS))
        result = subprocess.run([self.node, "--input-type=module", "-e", script],
                                check=True, capture_output=True, text=True, timeout=10)
        actual = json.loads(result.stdout)
        self.assertEqual(actual, observed)
        self.assertEqual(driver.digest(driver.observed_products(actual, self.expected, 1)), self.expected["display_sha256"])

    def test_no_synthetic_backend_or_drizzli_navigation_in_executable_driver(self):
        source = (HERE / "smoke_core_browser.py").read_text()
        self.assertIn('"--static-profile", "flutter-canvaskit"', source)
        self.assertIn('str(ROOT / "scripts/serve-provider.mjs")', source)
        self.assertNotIn('browser-fixture.mjs', source)
        self.assertNotIn('/en/weather/week/', source)
        self.assertIn('ui.pointer_activate(client', source)
        self.assertIn('core.boundary(args, args.inside)', source)
        self.assertIn('core.verify_core_binary(binary, expected["core_sha256"], args)', source)


if __name__ == "__main__":
    unittest.main()
