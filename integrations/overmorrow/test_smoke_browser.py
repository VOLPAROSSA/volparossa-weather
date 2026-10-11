# SPDX-License-Identifier: GPL-3.0-only
"""Pure harness checks; importing must not load Firefox helpers or start a server."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
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
        for expected in ("flt-semantic-node-", "unique.length>600", "s.length>8192", ">32768", "resources.length>256"):
            self.assertIn(expected, client.source)
        self.assertNotIn("document.body.textContent", client.source)

    def test_all_actual_flutter_label_representations_without_body_text(self):
        node = os.environ.get("VOLPAROSSA_TEST_NODE") or shutil.which("node")
        if not node:
            self.skipTest("set VOLPAROSSA_TEST_NODE to the existing verified Node binary")
        # A small DOM model exercises the exact extraction JS; no browser,
        # sockets, dependency installation or external content is involved.
        script = r"""
class Element {
  constructor(tag,id='',attrs={}) { this.tagName=tag;this.id=id;this.attrs=attrs;
    this.childNodes=[];this.parentElement=null;this.nodeType=1; }
  append(child) { child.parentElement=this;this.childNodes.push(child);return child; }
  getAttribute(key) { return this.attrs[key]??null; }
  get childElementCount() { return this.childNodes.filter(n=>n.nodeType===1).length; }
  get textContent() { return this.childNodes.map(n=>n.textContent).join(''); }
  querySelectorAll(tag) { const out=[];for(const n of this.childNodes)if(n.nodeType===1){
    if(n.tagName===tag)out.push(n);out.push(...n.querySelectorAll(tag));}return out; }
}
const text=value=>({nodeType:3,textContent:value});
const aria=new Element('flt-semantics','flt-semantic-node-1',{'aria-label':'Native weather forecast'});
const direct=new Element('flt-semantics','flt-semantic-node-2');direct.append(text('Refresh forecasts'));
const heading=new Element('h1','flt-semantic-node-3');heading.append(text('Air quality'));
const header=new Element('header','flt-semantic-node-4');header.append(new Element('span')).append(text('Native particulate forecast'));
const nested=aria.append(new Element('flt-semantics','flt-semantic-node-5'));
nested.append(new Element('span')).append(text('5.53071'));
const unrelated=new Element('h1');unrelated.append(text('Not a Flutter semantic label'));
const nodes=[aria,direct,heading,header,nested,unrelated];
const labels=new Function('nodes',EXTRACTION+'\nreturn labels;')(nodes);
process.stdout.write(JSON.stringify(labels));
""".replace("EXTRACTION", json.dumps(driver.SEMANTIC_LABELS_JS))
        result = subprocess.run([node, "--input-type=module", "-e", script], check=True,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), ["Native weather forecast", "Refresh forecasts",
            "Air quality", "Native particulate forecast", "5.53071"])

    def test_button_lookup_only_allows_known_actual_app_buttons(self):
        class Client:
            source = None
            def script(self, source):
                self.source = source
                return {"found": False}
        client = Client()
        self.assertEqual(driver.button_state(client, "Refresh forecasts"), {"found": False})
        self.assertNotIn(".click()", client.source)
        self.assertIn("getBoundingClientRect", client.source)
        self.assertIn("aria-disabled", client.source)
        with self.assertRaises(ValueError):
            driver.button_state(client, "arbitrary injected text")

    @staticmethod
    def ready():
        return {"found": True, "count": 1, "enabled": True, "tappable": True,
                "in_viewport": True, "hit_target": True, "x": 80, "y": 400}

    def test_busy_missing_invisible_and_ambiguous_buttons_are_not_ready(self):
        state = self.ready()
        self.assertTrue(driver.button_ready(state))
        for key, value in (("enabled", False), ("found", False), ("in_viewport", False),
                           ("tappable", False), ("count", 2), ("x", -1), ("y", 4096), ("x", True)):
            self.assertFalse(driver.button_ready({**state, key: value}), (key, value))
        self.assertFalse(driver.button_ready({**state, "unexpected": 1}))
        self.assertFalse(driver.button_ready(None))

    def test_activation_is_one_real_pointer_press_and_release(self):
        class Client:
            def __init__(self): self.calls = []
            def command(self, name, parameters): self.calls.append((name, parameters))
        client = Client()
        driver.pointer_activate(client, self.ready())
        self.assertEqual([name for name, _ in client.calls],
                         ["WebDriver:PerformActions", "WebDriver:ReleaseActions"])
        pointer = client.calls[0][1]["actions"][0]
        self.assertEqual(pointer["parameters"], {"pointerType": "mouse"})
        self.assertEqual(pointer["actions"], [
            {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": 80, "y": 400},
            {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}])

    def test_failed_pointer_dispatch_still_releases_inputs(self):
        class Client:
            def __init__(self): self.calls = []
            def command(self, name, parameters):
                self.calls.append(name)
                if name == "WebDriver:PerformActions": raise RuntimeError("synthetic dispatch error")
        client = Client()
        with self.assertRaises(RuntimeError): driver.pointer_activate(client, self.ready())
        self.assertEqual(client.calls, ["WebDriver:PerformActions", "WebDriver:ReleaseActions"])

    def test_disabled_button_never_sends_pointer_commands(self):
        class Client:
            def command(self, *_): raise AssertionError("must not interact")
        with self.assertRaises(ValueError):
            driver.pointer_activate(Client(), {**self.ready(), "enabled": False})

    def test_request_diagnostics_have_only_four_bounded_counts(self):
        value = driver.request_counters({"calls": 2, "airQualityCalls": 2, "extra": "not retained"},
                                        {"weatherRequests": 2, "airQualityRequests": 1, "labels": ["not retained"]})
        self.assertEqual(value, {"provider_weather": 2, "provider_air_quality": 2,
                                 "browser_weather": 2, "browser_air_quality": 1})
        for invalid in (-1, 33, True, 1.5, None):
            with self.assertRaises(ValueError):
                driver.request_counters({"calls": invalid, "airQualityCalls": 1},
                                        {"weatherRequests": 1, "airQualityRequests": 1})

    def test_detail_diagnostics_retain_flags_not_raw_labels(self):
        class Client:
            def script(self, source):
                if "weatherNodes=0" in source:
                    return {"weather_nodes": 0, "hidden_weather_nodes": 0, "offscreen_weather_nodes": 0}
                return BrowserHarnessTests.ready()
        value = driver.detail_observation(Client(), {"labels": ["Air quality", "Native particulate forecast", "5.53071"],
            "weatherRequests": 10, "airQualityRequests": 10}, {"calls": 10, "airQualityCalls": 10})
        self.assertTrue(value["air_quality_title"])
        self.assertTrue(value["native_particulate"])
        self.assertTrue(value["native_concentration"])
        self.assertFalse(value["native_weather"])
        self.assertNotIn("labels", value)
        self.assertNotIn("5.53071", json.dumps(value))


if __name__ == "__main__":
    unittest.main()
