#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual Overmorrow + production shared core bridge in the disposable KVM trial.

The parent trial proves acquisition and a prior cold peer transfer. This driver
proves subsequent API/UI use of those same publications, not browser-triggered
first-cold delivery, origin authenticity, accuracy or native/mobile packaging.
Tables are typed by their exact static headers; product metadata is grouped by
actual titles. This does not claim separate DOM-container ownership per product.
"""
import argparse
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
STATIC_PREFIX = "volparossa-weather/build/overmorrow-web/"
BRIDGE_MODULES = ("scripts/serve-provider.mjs", "src/provider-http.mjs", "src/provider-core.mjs", "src/core-cache.mjs",
                  "src/air-quality.mjs", "src/air-quality-provider.mjs", "src/air-quality-core.mjs")
HEADERS = {
    "weather": ["Native valid time (UTC)", "Temperature (°C)", "Wind (m/s)", "Wind from (°)",
                "Precipitation (mm)", "Accumulation window (UTC)"],
    "air_quality": ["Native valid time (UTC)", "PM2.5 (µg/m³)", "PM10 (µg/m³)"],
}
SOURCE_FIELDS = ("attribution", "license", "license_url", "changes")
_CORE = None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


# These imports are inert: no fixture/server, Firefox or SDK is started.
ui = load("overmorrow_semantics", HERE / "smoke_browser.py")


def core_helpers():
    """Reuse the existing VM/sandbox/API checks without import-name ambiguity."""
    global _CORE
    if _CORE is None:
        previous = sys.modules.get("smoke_browser")
        try:
            shared = load("smoke_browser", ROOT / "integrations/drizzli/smoke_browser.py")
            sys.modules["smoke_browser"] = shared
            _CORE = load("drizzli_core_boundaries", ROOT / "integrations/drizzli/smoke_core_browser.py")
        finally:
            if previous is None:
                sys.modules.pop("smoke_browser", None)
            else:
                sys.modules["smoke_browser"] = previous
    return _CORE


def require(value):
    if not value:
        raise ValueError("overmorrow_core_browser_check_failed")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def number_equal(left, right):
    """Permit num.toString's redundant .0, never rounding or a missing→0 cast."""
    if not all(type(item) is str and len(item) <= 40 and re.fullmatch(
            r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d{1,3})?", item) for item in (left, right)):
        return False
    try:
        return Decimal(left) == Decimal(right)
    except InvalidOperation:
        return False


def validate_expected(value, config):
    core = core_helpers()
    require(type(value) is dict and set(value) == {"schema", "core_sha256", "products", "display_sha256"}
            and type(value["schema"]) is int and value["schema"] == 3
            and type(value["products"]) is dict and set(value["products"]) == set(HEADERS))
    legacy = copy.deepcopy(value)
    legacy["schema"] = 2
    for name, product in value["products"].items():
        display, forecast = product["display"], product["forecast"]
        require(type(display) is dict and set(display) == {
            "coordinates", "native", "values", "model_run", "acquired_at", "expires_at", *SOURCE_FIELDS}
            and digest(display) == product["display_sha256"])
        require(all(type(display[key]) is str and 0 < len(display[key]) <= 4096
                    and display[key] == forecast["source"][key] for key in SOURCE_FIELDS)
                and display["acquired_at"] == forecast["source"]["acquired_at"]
                and core.stamp(display["acquired_at"]) <= time.time() < core.stamp(display["expires_at"]))
        area = forecast["area"]
        coordinate = re.fullmatch(r"Public community area: ([^,]+), ([^,]+)", display["coordinates"])
        require(coordinate and number_equal(coordinate[1], str(area["latitude"]))
                and number_equal(coordinate[2], str(area["longitude"])))
        require(len(display["values"]) == len(forecast["samples"]))
        for row, sample in zip(display["values"], forecast["samples"]):
            numbers = ([sample["pm2_5"], sample["pm10"]] if name == "air_quality" else
                [sample["temperature_2m"], sample["wind_10m"]["speed"], sample["wind_10m"]["direction_from"],
                 sample["precipitation"]["amount"]])
            require(type(row) is list and len(row) == (2 if name == "air_quality" else 5))
            require(all(cell == "Not available" if number is None else number_equal(cell, str(number))
                        for cell, number in zip(row, numbers)))
        old = legacy["products"][name]
        old["display"].pop("acquired_at")
        if name == "weather":
            for key in SOURCE_FIELDS:
                old["display"].pop(key)
        old["display_sha256"] = digest(old["display"])
    require(digest({name: product["display"] for name, product in value["products"].items()}) == value["display_sha256"])
    legacy["display_sha256"] = digest({name: product["display"] for name, product in legacy["products"].items()})
    # All existing receipt/publication/query/independent-run/expiry checks remain.
    core.validate_expected(legacy, config)
    return value


# Preserve actual semantic row order and cell ownership. Flutter can merge both
# products' metadata into a common label before the two table children, so a
# preceding title cannot establish table ownership. Type tables only by actual
# ordered static headers, independently of expected values/row counts. Never
# collect all body text or deduplicate rows: repeated/missing cells are data.
TABLES_JS = r"""
const typedHeaders=__NATIVE_TABLE_HEADERS__, typedTables=new Map();
const semanticNodes=nodes.filter(n=>/^flt-semantic-node-[0-9]+$/.test(n.id));
const semanticSet=new Set(semanticNodes);
const parent=n=>n.parentElement||n.getRootNode?.()?.host||null;
function closest(n,roles){for(let p=parent(n);p;p=parent(p))
  if(semanticSet.has(p)&&roles.includes(p.getAttribute('role')))return p;return null;}
function visible(n){for(let p=n;p;p=parent(p)){
  const s=getComputedStyle(p);if(p.hidden||p.getAttribute('aria-hidden')==='true'
    ||s.display==='none'||s.visibility==='hidden')return false;}return true;}
function ownLabels(n){const found=[],a=n.getAttribute('aria-label');if(a)found.push(a);
  for(const c of n.childNodes)if(c.nodeType===3&&c.textContent.trim())found.push(c.textContent);
  for(const span of n.querySelectorAll('span')){let p=parent(span);
    while(p&&!semanticSet.has(p))p=parent(p);
    if(p===n&&span.childElementCount===0&&span.textContent.trim())found.push(span.textContent);}
  return [...new Set(found.map(s=>s.trim()))];}
const sections=[];let active=null,total=0;
for(const n of semanticNodes){
  if(!visible(n)||closest(n,['table']))continue;
  if(n.getAttribute('role')==='table'){
    const rows=semanticNodes.filter(r=>r.getAttribute('role')==='row'&&closest(r,['table'])===n&&visible(r));
    if(rows.length<2||rows.length>17)throw Error('row_bound');
    const data=rows.map(r=>{
      const cells=semanticNodes.filter(c=>['cell','columnheader'].includes(c.getAttribute('role'))
        &&closest(c,['row'])===r&&visible(c));
      if(cells.length<3||cells.length>6)throw Error('cell_bound');
      return cells.map(c=>{
        const owners=semanticNodes.filter(x=>(x===c||closest(x,['cell','columnheader'])===c)&&visible(x));
        const texts=[...new Set(owners.flatMap(ownLabels))];
        if(texts.length!==1||texts[0].length>256)throw Error('ambiguous_cell');
        total+=texts[0].length;return texts[0];});});
    const kind=Object.keys(typedHeaders).find(k=>JSON.stringify(data[0])===JSON.stringify(typedHeaders[k]));
    if(!kind)throw Error('unknown_native_table_headers');
    if(typedTables.has(kind))throw Error('duplicate_native_table_type');
    typedTables.set(kind,{headers:data[0],rows:data.slice(1)});
  }else{
    for(const line of ownLabels(n).flatMap(s=>s.split('\n')).map(s=>s.trim()).filter(Boolean)){
      if(line==='Native weather forecast'||line==='Native particulate forecast'){
        active={product:line==='Native weather forecast'?'weather':'air_quality',labels:[],tables:[]};
        sections.push(active);if(sections.length>2)throw Error('section_bound');
      }
      if(active){if(line.length>8192||active.labels.length>=128)throw Error('metadata_bound');
        active.labels.push(line);total+=line.length;}
    }
  }
}
// Missing titles/tables remain empty and are rejected by observed_products;
// this permits its existing bounded wait to observe incomplete UI hydration.
for(const section of sections)if(typedTables.has(section.product))section.tables.push(typedTables.get(section.product));
if(total>32768)throw Error('text_bound');
const resources=performance.getEntriesByType('resource');
if(resources.length>256)throw Error('resource_bound');
return {sections,localOnly:resources.every(e=>e.name.startsWith(location.origin+'/')),
  weatherRequests:resources.filter(e=>e.name===location.origin+'/api/volparossa/forecast'&&e.responseEnd>0).length,
  airQualityRequests:resources.filter(e=>e.name===location.origin+'/api/volparossa/air-quality'&&e.responseEnd>0).length,
  wasmLoaded:resources.some(e=>e.name===location.origin+'/canvaskit/canvaskit.wasm'&&e.responseEnd>0),
  canvas:nodes.some(n=>n.tagName.toLowerCase()==='canvas'),location:location.pathname};
""".replace("__NATIVE_TABLE_HEADERS__", json.dumps(HEADERS, ensure_ascii=False))


def snapshot(client):
    return client.script(ui.NODES_JS + TABLES_JS)


def observed_products(observed, expected, requests):
    require(type(observed) is dict and set(observed) == {
        "sections", "localOnly", "weatherRequests", "airQualityRequests", "wasmLoaded", "canvas", "location"}
        and all(observed[key] is True for key in ("localOnly", "wasmLoaded", "canvas")) and observed["location"] == "/"
        and all(type(observed[key]) is int and observed[key] == requests for key in ("weatherRequests", "airQualityRequests"))
        and type(observed["sections"]) is list and len(observed["sections"]) == 2)
    result = {}
    for section in observed["sections"]:
        require(type(section) is dict and set(section) == {"product", "labels", "tables"})
        name = section["product"]
        require(type(name) is str and name in HEADERS and name not in result)
        display = expected["products"][name]["display"]
        labels = section["labels"]
        require(type(labels) is list and len(labels) <= 128 and all(type(label) is str and len(label) <= 8192 for label in labels))
        model, run = display["model_run"].split(" · ")
        required_labels = [display["coordinates"], f"Model {model}; run {run}",
            "Acquired " + display["acquired_at"], "Expires " + display["expires_at"], display["attribution"],
            display["license"] + ": " + display["license_url"], display["changes"],
            "Core-cache delivery; schema and freshness checked. Origin authenticity is not attested.",
            ("AQI, pollen and health advice: not available" if name == "air_quality" else
             "Current observations, daily totals/extrema, UV, humidity and hourly interpolation: not available")]
        require(all(label in labels for label in required_labels)
                and not any("Expired —" in label or "unavailable or expired" in label for label in labels))
        require(type(section["tables"]) is list and len(section["tables"]) == 1)
        table = section["tables"][0]
        require(type(table) is dict and set(table) == {"headers", "rows"} and table["headers"] == HEADERS[name]
                and type(table["rows"]) is list and len(table["rows"]) == len(display["native"]))
        normalized = []
        for row, when, wanted in zip(table["rows"], display["native"], display["values"]):
            require(type(row) is list and len(row) == len(HEADERS[name]) and row[0] == when)
            for index, (cell, target) in enumerate(zip(row[1:], wanted)):
                require(type(cell) is str and len(cell) <= 256)
                require(cell == target if target == "Not available" or name == "weather" and index == 4
                        else number_equal(cell, target))
            normalized.append(list(wanted))
        # Metadata matched its actual title group; values matched the exact
        # header-typed table and ordered row, not an asserted DOM container.
        # Only harmless numeric spellings (e.g. 0.0) normalize.
        result[name] = {**display, "native": [row[0] for row in table["rows"]], "values": normalized}
        require(digest(result[name]) == expected["products"][name]["display_sha256"])
    require(digest(result) == expected["display_sha256"])
    return result


def wait_products(client, connection, expected, requests):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        connection.settimeout(min(15, max(0.1, deadline - time.monotonic())))
        value = snapshot(client)
        try:
            products = observed_products(value, expected, requests)
        except (ValueError, KeyError, TypeError):
            products = None
        if products is not None and ui.button_ready(ui.button_state(client, "Refresh forecasts")):
            connection.settimeout(15)
            return digest(products), {name: digest(display) for name, display in products.items()}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise TimeoutError("native_tables_deadline")


def validate_bundle(root, expected):
    core = core_helpers()
    require(root.resolve(strict=True) == root and ROOT == root / "volparossa-weather" and core.hex64(expected)
            and root.stat().st_uid == os.getuid() and stat.S_IMODE(root.stat().st_mode) == 0o500)
    raw = core.raw_file(root / "INPUTS.json", 131072, 0o400)
    require(hashlib.sha256(raw).hexdigest() == expected)
    manifest = json.loads(raw, object_pairs_hook=core.pairs)
    require(type(manifest) is dict and set(manifest) == {"version", "kind", "files"}
            and type(manifest["version"]) is int and manifest["version"] == 3
            and manifest["kind"] == "volparossa-weather-client-inputs" and raw.isascii()
            and raw == canonical(manifest) + b"\n" and type(manifest["files"]) is dict
            and 1 <= len(manifest["files"]) <= 512)
    found, total = set(), 0
    for count, path in enumerate(root.rglob("*")):
        require(count < 2048)
        info = path.lstat()
        require(not path.is_symlink() and info.st_uid == os.getuid() and not info.st_mode & 0o022)
        if path.is_dir():
            require(stat.S_IMODE(info.st_mode) == 0o500)
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "INPUTS.json":
            continue
        require(relative in manifest["files"])
        record = manifest["files"][relative]
        require(type(record) is dict and set(record) == {"bytes", "mode", "sha256"}
                and type(record["bytes"]) is int and 0 < record["bytes"] <= 256 * 1024**2
                and type(record["mode"]) is int and record["mode"] in (0o400, 0o500) and core.hex64(record["sha256"]))
        actual, size = core.file_hash(path, record["bytes"], record["mode"])
        require(actual == record["sha256"] and size == record["bytes"])
        total += size
        require(total <= core.MAX_BUNDLE_BYTES)
        found.add(relative)
    require(found == set(manifest["files"]))
    files = manifest["files"]
    required = ("integrations/overmorrow/smoke_core_browser.py", "integrations/overmorrow/prepare_core_browser.mjs",
        "integrations/overmorrow/smoke_browser.py", "integrations/drizzli/smoke_core_browser.py",
        "integrations/drizzli/smoke_browser.py", "integrations/drizzli/prepare-core-browser.mjs", *BRIDGE_MODULES)
    require(all("volparossa-weather/" + name in files for name in required)
            and files["runtime/node"]["sha256"] == core.shared.NODE_SHA256)
    hashes = {name[len(STATIC_PREFIX):]: record["sha256"] for name, record in files.items() if name.startswith(STATIC_PREFIX)}
    retained = core.read_json(ROOT / "integrations/overmorrow/browser-proof.json", 16384)
    require(retained["passed"] is True and retained["phase"] == "complete"
            and retained["scope"]["actual_overmorrow_ui"] is True
            and retained["scope"]["synthetic_weather"] is True and retained["scope"]["synthetic_air_quality"] is True
            and digest(hashes) == retained["source"]["deployed_tree_sha256"])
    browser = root / "volparossa-browser/build/firefox-esr-smoke-v3"
    metadata = core.shared.validate_stage(browser)
    source = dict(bundle_manifest_sha256=expected,
        driver_sha256=files["volparossa-weather/" + required[0]]["sha256"],
        preparer_sha256=files["volparossa-weather/" + required[1]]["sha256"],
        built_tree_sha256=digest(hashes), node_sha256=core.shared.NODE_SHA256,
        bridge_modules={name: files["volparossa-weather/" + name]["sha256"] for name in BRIDGE_MODULES})
    return root / STATIC_PREFIX.rstrip("/"), browser, metadata, source


def report_base(source, expected):
    report = core_helpers().report_base(source, {**expected, "schema": 2})
    report["schema"] = 3
    report["scope"]["actual_overmorrow_ui"] = report["scope"].pop("actual_drizzli_ui")
    return report


def inside(args, built, browser_stage, metadata, source, expected):
    core, work = core_helpers(), args.output
    shared = core.shared
    core.boundary(args, True)
    require(all(os.statvfs(path).f_flag & os.ST_RDONLY for path in (Path("/"), args.bundle_root, built, browser_stage)))
    shared.validate_isolated_browser_home(work)
    links = json.loads(subprocess.check_output(["/usr/bin/ip", "-j", "link", "show"], text=True))
    require([row["ifname"] for row in links] == ["lo"] and "UP" in links[0]["flags"])
    owned = core.identity(work)
    for name in core.PRIVATE_DIRS:
        if name != "appdata":
            (work / name).mkdir(mode=0o700)
    with (work / "profile/prefs.js").open("x") as output:
        output.write('user_pref("remote.prefs.recommended", false);\n')
    environment = shared.clean_environment()
    environment.update(MOZ_NO_REMOTE="1", MOZ_CRASHREPORTER_DISABLE="1", XDG_CONFIG_HOME=str(work / "config"),
        XDG_CACHE_HOME=str(work / "cache"), XDG_RUNTIME_DIR=str(work / "runtime"), TMPDIR=str(work / "tmp"))
    report = report_base(source, expected)
    report["expected"]["expected_sha256"] = shared.digest(args.expected)
    browser = bridge = connection = client = None
    normal_browser = normal_bridge = False
    try:
        report["phase"] = "bridge_start"
        bridge = subprocess.Popen([str(args.bundle_root / "runtime/node"), "--max-old-space-size=256",
            str(ROOT / "scripts/serve-provider.mjs"), "--config", str(args.config), "--static-root", str(built),
            "--static-profile", "flutter-canvaskit", "--port", "0"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        ready = shared.read_line(bridge)
        require(set(ready) == {"listening", "scope"} and ready["scope"] == "fixed-public-community-forecast"
                and re.fullmatch(r"http://127\.0\.0\.1:[1-9]\d{0,4}", ready["listening"]))
        origin = ready["listening"]
        report["scope"]["actual_http_bridge"] = True
        report["phase"] = "provider"
        for name, product in expected["products"].items():
            report["products"][name]["checks"]["api_response_sha256"] = core.api(origin, product, name)
        report["scope"]["real_core_adapter"] = True
        report["phase"] = "browser_start"
        browser = subprocess.Popen([str(browser_stage / metadata["executable"]), "--headless", "--no-remote", "--new-instance",
            "--profile", str(work / "profile"), "--marionette", "--remote-allow-system-access", "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            require(browser.poll() is None)
            try:
                connection = socket.create_connection(("127.0.0.1", 2828), timeout=1)
                connection.settimeout(15)
                client = shared.Marionette(connection)
                break
            except (ConnectionRefusedError, TimeoutError):
                if connection:
                    connection.close(); connection = None
                time.sleep(0.1)
        require(client is not None)
        client.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})
        client.command("Marionette:SetContext", {"value": "chrome"})
        require(Path(client.script('return Services.dirsvc.get("GreD", Ci.nsIFile).path;')).resolve() == browser_stage)
        client.command("Marionette:SetContext", {"value": "content"})
        client.command("WebDriver:SetTimeouts", {"pageLoad": 20000, "script": 10000})
        client.command("WebDriver:SetWindowRect", {"width": 2400, "height": 2600})
        report["phase"] = "hydration"
        client.command("WebDriver:Navigate", {"url": origin + "/"})
        shared.wait_for(lambda: ui.activate_semantics(client), timeout=35)
        combined, observed = wait_products(client, connection, expected, 1)
        report["checks"]["initial_dom_display_sha256"] = combined
        for name, observed_hash in observed.items():
            report["products"][name]["checks"].update(initial_dom_display_sha256=observed_hash,
                initial_dom_matches_cold_publication=True)
        report["scope"]["actual_overmorrow_ui"] = True
        report["phase"] = "refresh"
        ui.pointer_activate(client, ui.button_state(client, "Refresh forecasts"))
        combined, observed = wait_products(client, connection, expected, 2)
        report["checks"].update(refresh_dom_display_sha256=combined,
            browser_api_requests=4, provider_requests_checked=2, no_external_resources=True)
        for name, observed_hash in observed.items():
            report["products"][name]["checks"].update(refresh_dom_display_sha256=observed_hash,
                refresh_dom_matches_cold_publication=True, browser_api_requests=2, provider_requests_checked=1,
                exact_native_times_and_values=True, explicit_missing_capabilities=True,
                no_external_resources=True, source_attribution=True)
        report["scope"]["separate_native_runs"] = True
        report["phase"] = "shutdown"
        client.command("Marionette:Quit", {"flags": ["eAttemptQuit"]})
        normal_browser = browser.wait(timeout=15) == 0
        bridge.terminate()
        normal_bridge = bridge.wait(timeout=10) == 0
        require(normal_browser and normal_bridge and not list((work / "scratch").iterdir()))
        report.update(passed=True, phase="complete")
    except BaseException as error:
        report["failure"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "check_or_runtime_failed"
    finally:
        if connection:
            try: connection.close()
            except OSError: pass
        browser_stopped, bridge_stopped = shared.stop(browser), shared.stop(bridge)
        if bridge and bridge.stdout:
            try: bridge.stdout.close()
            except OSError: pass
        removed = core.cleanup(work, owned) if browser_stopped and bridge_stopped else False
        report["cleanup"] = dict(browser_exited=browser_stopped, bridge_exited=bridge_stopped,
            private_state_removed=removed, normal_browser_stop=normal_browser, normal_bridge_stop=normal_bridge)
        report["passed"] = report["passed"] and all(report["cleanup"].values())
        shared.save_report(work, report)


def main():
    core = core_helpers()
    shared = core.shared
    deadline = time.monotonic() + 240
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    def interrupted(_signum, _frame):
        signal.setitimer(signal.ITIMER_REAL, 0)
        for selected in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
            signal.signal(selected, signal.SIG_IGN)
        raise KeyboardInterrupt()
    for selected in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(selected, interrupted)
    signal.setitimer(signal.ITIMER_REAL, 240)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    for name in ("bundle-root", "config", "expected", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("bundle-manifest-sha256", "parent-netns", "client-netns"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--control-gid", type=int, required=True)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--outer-userns", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("bundle_root", "config", "expected", "output"):
        path = getattr(args, name)
        require(path.is_absolute() and path.resolve() == path)
    require(args.output.parent == args.config.parent == args.expected.parent and not args.output.is_relative_to(args.bundle_root))
    core.boundary(args, args.inside)
    config = core.read_json(args.config, 16384, 0o600)
    raw = core.raw_file(args.expected, 384 * 1024, 0o400)
    expected = validate_expected(json.loads(raw, object_pairs_hook=core.pairs), config)
    built, browser, metadata, source = validate_bundle(args.bundle_root, args.bundle_manifest_sha256)
    require(config["core"]["scratchParent"] == str(args.output / "scratch"))
    binary = Path(config["core"]["executable"])
    core.verify_core_binary(binary, expected["core_sha256"], args)
    control = Path(config["core"]["controlSocket"])
    require(control.resolve(strict=True) == control and stat.S_ISSOCK(control.stat().st_mode))
    if args.inside:
        inside(args, built, browser, metadata, source, expected)
        return
    require(core.available_memory() >= 1536 * 1024**2 and not args.output.exists() and time.monotonic() < deadline)
    args.output.mkdir(mode=0o700)
    owned = core.identity(args.output)
    wrapper, completed = None, False
    try:
        mounts = shared.isolated_browser_home(args.output)
        command = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user", "--unshare-net",
            "--unshare-pid", "--ro-bind", "/", "/", *mounts, "--bind", str(args.output), str(args.output),
            "--ro-bind", str(binary), str(binary), "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--",
            sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--inside", "--outer-userns",
            os.readlink("/proc/self/ns/user")]
        wrapper = subprocess.Popen(command, env=shared.clean_environment(), start_new_session=True)
        while time.monotonic() < deadline:
            try:
                completed = wrapper.wait(timeout=1) == 0
                break
            except subprocess.TimeoutExpired:
                require(core.available_memory() >= 768 * 1024**2)
    finally:
        stopped = shared.stop(wrapper)
        removed = core.cleanup(args.output, owned) if stopped else False
        report = report_base(source, expected)
        report["expected"]["expected_sha256"] = shared.digest(args.expected)
        if (args.output / "report.json").exists():
            try:
                candidate = core.read_json(args.output / "report.json", 16384, 0o600)
                require(candidate["schema"] == 3 and candidate["phase"] in core.PHASES and candidate["source"] == source)
                report = candidate
            except (OSError, ValueError, KeyError):
                pass
        report["outer_cleanup"] = dict(namespace_wrapper_exited=stopped, private_state_removed=removed,
            client_namespace_unchanged=os.readlink("/proc/self/ns/net") == args.client_netns)
        report["passed"] = completed and report["passed"] and all(report["outer_cleanup"].values())
        shared.save_report(args.output, report)
    require(report["passed"])
    print(json.dumps({"passed": True, "synthetic_weather": False, "standalone_overlay_proven": False}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, KeyboardInterrupt, subprocess.SubprocessError):
        print('{"passed":false,"failure":"overmorrow_core_browser_check_failed"}', file=sys.stderr)
        raise SystemExit(1) from None
