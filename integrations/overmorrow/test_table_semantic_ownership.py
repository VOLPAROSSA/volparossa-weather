# SPDX-License-Identifier: GPL-3.0-only
"""Typed-table v3 regressions: shared metadata labels precede table children.

Pure DOM only, not a claim that the retained browser report exposed this exact
ancestry. That report proves weather=0/AQ=2 assignment, but contains no raw DOM.
The contract is exact header-typed tables plus actual title-grouped metadata,
not an assertion of separate DOM containers. All ordered data checks remain.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("synthetic_table_test_inputs", HERE / "test_smoke_table_browser.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
driver = fixtures.driver


class SemanticOwnershipRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.SyntheticTableTests.setUpClass()
        cls.expected = driver.expected_display(fixtures.SyntheticTableTests.bodies)

    def extract(self, change=None):
        observed = fixtures.observation(self.expected)
        titles = {"weather": "Native weather forecast", "air_quality": "Native particulate forecast"}
        for section in observed["sections"]:
            section["labels"].insert(0, titles[section["product"]])
        if change is not None:
            change(observed)
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
function semantic(parent,role,label){
  const e=parent.append(new Element('flt-semantics','flt-semantic-node-'+next++,role?{role}:{}));nodes.push(e);
  if(label!==undefined)e.attrs['aria-label']=label;return e;}
// Important difference from the pre-existing regression: both metadata groups
// belong to one semantic node before either separate table child. No product
// container, synthetic aria owner, or expected-value match is invented here.
const shared=semantic(root,null,INPUT.sections.flatMap(s=>s.labels).join('\n'));
for(const section of INPUT.sections){
 for(const nativeTable of section.tables){
  const table=semantic(shared,'table');
  for(const [index,row] of [nativeTable.headers,...nativeTable.rows].entries()){
    const tr=semantic(table,'row');
    for(const value of row)semantic(tr,index===0?'columnheader':'cell',value);
  }
 }
}
nodes.push(new Element('canvas'));
const location={origin:'http://127.0.0.1:3210',pathname:'/'};
const resources=['/api/volparossa/forecast','/api/volparossa/air-quality','/canvaskit/canvaskit.wasm']
  .map(s=>({name:location.origin+s,responseEnd:1}));
const result=new Function('nodes','getComputedStyle','performance','location',EXTRACT)(nodes,
  ()=>({display:'block',visibility:'visible'}),{getEntriesByType:()=>resources},location);
process.stdout.write(JSON.stringify(result));
""".replace("INPUT", json.dumps(observed)).replace("EXTRACT", json.dumps(driver.tables.TABLES_JS))
        result = subprocess.run([os.environ["VOLPAROSSA_TEST_NODE"], "--input-type=module", "-e", script],
                                check=True, capture_output=True, text=True, timeout=10)
        actual = json.loads(result.stdout)
        return actual

    def test_merged_product_metadata_before_tables_must_not_assign_both_tables_to_air_quality(self):
        actual = self.extract()
        diagnostic = driver.table_diagnostic(actual, self.expected)
        # Metadata still matches each product, as observed in real browser02.
        self.assertTrue(all(all(item["metadata_matches"].values()) for item in diagnostic["sections"]))
        self.assertEqual([len(section["tables"]) for section in actual["sections"]], [1, 1],
                         "Every exact header type must have one table; preceding labels are not owners")
        verified = driver.tables.observed_products(actual, self.expected, 1)
        self.assertEqual(driver.tables.digest(verified), self.expected["display_sha256"])

    def test_reversed_table_dom_order_keeps_exact_typed_values_and_metadata(self):
        def reverse(value):
            value["sections"][0]["tables"], value["sections"][1]["tables"] = (
                value["sections"][1]["tables"], value["sections"][0]["tables"])
        actual = self.extract(reverse)
        verified = driver.tables.observed_products(actual, self.expected, 1)
        self.assertEqual(driver.tables.digest(verified), self.expected["display_sha256"])

    def test_unknown_and_duplicate_actual_header_types_fail_before_expected_value_matching(self):
        def unknown(value): value["sections"][0]["tables"][0]["headers"][1] = "Different field"
        def reordered(value): value["sections"][0]["tables"][0]["headers"].reverse()
        def duplicate(value): value["sections"][1]["tables"] = value["sections"][0]["tables"]
        for change in (unknown, reordered, duplicate):
            with self.subTest(change=change.__name__), self.assertRaises(subprocess.CalledProcessError):
                self.extract(change)

    def test_missing_typed_table_never_passes_the_exact_complete_contract(self):
        # Preserve metadata for both products while omitting one actual table.
        def missing(value): value["sections"][1]["tables"] = []
        actual = self.extract(missing)
        self.assertEqual([len(section["tables"]) for section in actual["sections"]], [1, 0])
        with self.assertRaises(ValueError): driver.tables.observed_products(actual, self.expected, 1)

    def test_typed_headers_do_not_waive_swapped_values_or_wrong_title_metadata(self):
        def swapped(value): value["sections"][1]["tables"][0]["rows"][0][1:] = value["sections"][1]["tables"][0]["rows"][0][:0:-1]
        def corrupt(value): value["sections"][0]["tables"][0]["rows"][0][1] = "999"
        def wrong_metadata(value):
            label = value["sections"][0]["labels"].pop(1)
            value["sections"][1]["labels"].append(label)
        for change in (swapped, corrupt, wrong_metadata):
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                driver.tables.observed_products(self.extract(change), self.expected, 1)


if __name__ == "__main__":
    unittest.main()
