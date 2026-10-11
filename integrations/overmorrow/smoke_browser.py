#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual Overmorrow CanvasKit UI over the shared bridge in a loopback-only netns.

Uses synthetic native products. This is not weather-origin, core/peer-delivery,
forecast-accuracy, Android/iOS or home-screen-widget evidence. All application
assets are the checked Flutter release build, not a surrogate HTML test page.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition):
    if not condition:
        raise ValueError("overmorrow_browser_smoke_failed")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_source(stage, static_root, support):
    deploy = load_module("overmorrow_deploy", HERE / "deploy.py")
    pin = json.loads((HERE / "upstream.json").read_text())
    require(support.digest(HERE / "upstream.patch") == pin["upstream_patch_sha256"])
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(stage), *args],
            text=True, timeout=20, env=support.clean_environment())
    require(git("rev-parse", "HEAD").strip() == pin["commit"])
    require(git("rev-parse", "HEAD^{tree}").strip() == pin["tree"])
    for name, key in (("LICENSE", "license_sha256"), ("pubspec.lock", "pubspec_lock_sha256")):
        require(support.digest(stage / name) == pin[key])
    require(support.digest(stage / "LICENSE.VOLPAROSSA") == support.digest(ROOT / "LICENSE"))
    patch = (HERE / "upstream.patch").read_text()
    patched = [line[6:] for line in patch.splitlines() if line.startswith("+++ b/")]
    require(git("diff", "--no-ext-diff", "--binary", "--", *patched) == patch)
    require(set(git("diff", "--name-only").splitlines()) == set(patched))
    overlay = {}
    for path in sorted((HERE / "overlay").rglob("*")):
        if path.is_file():
            name = path.relative_to(HERE / "overlay").as_posix()
            require(not path.is_symlink() and support.digest(stage / name) == support.digest(path))
            overlay[name] = support.digest(path)
    expected, actual, total = {}, {}, 0
    built = stage / "build/web"
    for path in sorted(built.rglob("*")):
        deploy.checked(path, directory=path.is_dir())
        if path.is_file() and deploy.eligible(path.relative_to(built)):
            expected[path.relative_to(built).as_posix()] = support.digest(path)
    expected.update({"LICENSE.txt": pin["license_sha256"],
                     "LICENSE.VOLPAROSSA.txt": support.digest(ROOT / "LICENSE")})
    entries = sorted(static_root.rglob("*"))
    require(len(entries) <= 1024)
    for path in [static_root, *entries]:
        info = deploy.checked(path, directory=path.is_dir())
        if path.is_file():
            total += info.st_size
            actual[path.relative_to(static_root).as_posix()] = support.digest(path)
    require(total <= deploy.MAX_TREE and actual == expected)
    require(deploy.ROOT_FILES | deploy.RENDERER_FILES | {"assets/NOTICES", "assets/AssetManifest.bin"} <= actual.keys())
    return dict(upstream=pin["commit"], tree=pin["tree"], patch_sha256=pin["upstream_patch_sha256"],
        overlay_sha256=overlay, deployed_tree_sha256=canonical_hash(actual),
        deployed_files=len(actual), deployed_bytes=total,
        bridge_modules={name: support.digest(ROOT / name) for name in
            ("src/provider-http.mjs", "src/provider-core.mjs", "src/core-cache.mjs",
             "src/provider.mjs", "src/forecast.mjs", "src/air-quality-core.mjs",
             "src/air-quality.mjs", "src/air-quality-provider.mjs")},
        fixture_modules={name: support.digest(ROOT / name) for name in
            ("integrations/overmorrow/test-fixtures.mjs", "integrations/drizzli/browser-fixture.mjs",
             "tests/fixtures.mjs", "tests/air-quality-fixtures.mjs", "src/ecmwf.mjs")},
        browser_helpers={name: support.digest(support.BROWSER_ROOT / name) for name in
            ("scripts/smoke_compute_model.py", "scripts/smoke_privacy.py", "scripts/stage_firefox.py")},
        isolation_helper_sha256=support.digest(ROOT / "integrations/drizzli/smoke_browser.py"),
        driver_sha256=support.digest(Path(__file__)), fixture_sha256=support.digest(HERE / "browser-fixture.mjs"))


# Read actual Flutter accessibility semantics. CanvasKit draws into a canvas;
# document.body.textContent alone does not describe the application UI.
NODES_JS = """
const nodes=[]; const visit=root=>{for(const n of root.querySelectorAll('*')){
  if(nodes.length>=3000)throw Error('semantic_node_bound'); nodes.push(n);
  if(n.shadowRoot)visit(n.shadowRoot);
}}; visit(document);
"""


def activate_semantics(client):
    return client.script(NODES_JS + """
const p=nodes.find(n=>n.tagName.toLowerCase()==='flt-semantics-placeholder');
if(p)p.click();
return nodes.some(n=>n.tagName.toLowerCase()==='flt-semantics');
""") is True


def snapshot(client):
    return client.script(NODES_JS + """
const labels=[];
for(const n of nodes){
  if(n.tagName.toLowerCase()==='flt-semantics'){
    const label=n.getAttribute('aria-label'); if(label)labels.push(label);
    for(const span of n.querySelectorAll('span'))
      if(span.closest('flt-semantics')===n&&span.childElementCount===0&&span.textContent)
        labels.push(span.textContent);
  }
}
// Flutter may merge a whole forecast card into one accessible label. Bound
// the entire snapshot as well as each label; do not mistake that normal merge
// for an oversized application response or truncate a native time/value.
const unique=[...new Set(labels)];
const largest=unique.reduce((size,s)=>Math.max(size,s.length),0);
const total=unique.reduce((sum,s)=>sum+s.length,0);
if(unique.length>600||unique.some(s=>s.length>8192)
  ||total>32768)throw Error('semantic_text_bound:'+unique.length+':'+largest+':'+total);
const resources=performance.getEntriesByType('resource');
if(resources.length>256)throw Error('resource_bound');
return {labels:unique,
  localOnly:resources.every(e=>e.name.startsWith(location.origin+'/')),
  weatherRequests:resources.filter(e=>e.name===location.origin+'/api/volparossa/forecast'&&e.responseEnd>0).length,
  airQualityRequests:resources.filter(e=>e.name===location.origin+'/api/volparossa/air-quality'&&e.responseEnd>0).length,
  wasmLoaded:resources.some(e=>e.name===location.origin+'/canvaskit/canvaskit.wasm'&&e.responseEnd>0),
  canvas: nodes.some(n=>n.tagName.toLowerCase()==='canvas'),
  location:location.pathname};
""")


def labels_contain(observed, *values):
    if (type(observed) is not dict or type(observed.get("labels")) is not list
            or not all(type(label) is str for label in observed["labels"])):
        return False
    labels = observed["labels"]
    return all(any(value in label for label in labels) for value in values)


def click_label(client, label):
    require(label in ("Refresh forecasts", "Air quality details", "Back"))
    encoded = json.dumps(label)
    return client.script(NODES_JS + f"""
const wanted={encoded};
const b=nodes.find(n=>(n.getAttribute('role')==='button'||n.tagName.toLowerCase()==='button')
  &&(n.getAttribute('aria-label')===wanted||n.textContent.trim()===wanted)
  &&n.getAttribute('aria-disabled')!=='true'&&!n.disabled);
if(!b)return false;b.click();return true;
""") is True


def run_ui(client, fixture, ready, support, report):
    def status(mode="status"):
        return support.fixture_command(fixture, mode)
    def wait_labels(*labels, absent=(), timeout=20):
        observed = None
        def check():
            nonlocal observed
            observed = snapshot(client)
            return (labels_contain(observed, *labels)
                    and all(not labels_contain(observed, item) for item in absent))
        support.wait_for(check, timeout=timeout)
        require(observed["localOnly"] and observed["canvas"])
        return observed
    def refresh(mode):
        before = status(mode)
        require(click_label(client, "Refresh forecasts"))
        support.wait_for(lambda: status()["calls"] == before["calls"] + 1
                        and status()["airQualityCalls"] == before["airQualityCalls"] + 1)
        support.wait_for(lambda: snapshot(client)["weatherRequests"] == before["calls"] + 1
                        and snapshot(client)["airQualityRequests"] == before["airQualityCalls"] + 1)
    def both():
        return wait_labels("Native weather forecast", "Native particulate forecast", "5.53071", "11.5959",
            "0.01", "Accumulation window (UTC)", "PM2.5 (µg/m³)", "PM10 (µg/m³)",
            *ready["valid_at"], *ready["air_quality_valid_at"])

    report["phase"] = "viewport"
    client.command("WebDriver:SetWindowRect", {"width": 2400, "height": 2600})
    report["phase"] = "navigation"
    client.command("WebDriver:Navigate", {"url": ready["origin"] + "/"})
    report["phase"] = "semantics_activation"
    support.wait_for(lambda: activate_semantics(client), timeout=35)
    report["phase"] = "hydration"
    observed = both()
    require(status()["calls"] == status()["airQualityCalls"] == 1)
    require(observed["wasmLoaded"] and observed["location"] == "/")
    require(labels_contain(observed, "Current observations: not available",
        "AQI, pollen and health advice: not available", "hourly interpolation: not available",
        "Origin authenticity is not attested", "52.52", "13.41", "CC-BY-4.0",
        "NOAA", ready["weather_run"], ready["air_quality_run"]))
    report["scope"]["actual_overmorrow_ui"] = True
    report["checks"].update(actual_canvas_and_semantics=True, independent_native_timelines=True,
        native_values_visible=True, no_fabricated_current_or_aqi=True, fixed_public_area=True,
        source_attribution=True, initial_semantics_sha256=canonical_hash(observed["labels"]))
    report["phase"] = "refresh"
    refresh("valid"); both()
    report["checks"]["actual_refresh"] = True

    for mode, error, preserved in (("unavailable", "Weather unavailable or expired", "5.53071"),
                                   ("stale", "Weather unavailable or expired", "5.53071")):
        report["phase"] = mode
        refresh(mode)
        wait_labels(error, preserved, absent=("0.01",))
    report["checks"]["weather_failure_and_stale_preserve_air_quality"] = True
    report["phase"] = "weather_idle_expiry"
    refresh("short-lived"); both()
    before = status()
    wait_labels("Expired — refresh required; values are hidden", "5.53071", absent=("0.01",), timeout=8)
    require(status() == before)
    report["checks"]["weather_idle_expiry_without_request"] = True
    refresh("valid"); both()
    for mode in ("aq-unavailable", "aq-stale"):
        report["phase"] = mode
        refresh(mode)
        wait_labels("Air quality unavailable or expired", "0.01", absent=("5.53071",))
    report["checks"]["air_quality_failure_and_stale_preserve_weather"] = True
    report["phase"] = "air_quality_idle_expiry"
    refresh("aq-short-lived"); both()
    before = status()
    wait_labels("Expired — refresh required; values are hidden", "0.01", absent=("5.53071",), timeout=8)
    require(status() == before)
    report["checks"]["air_quality_idle_expiry_without_request"] = True
    refresh("aq-valid"); both()
    report["phase"] = "actual_air_quality_detail_route"
    before = status()
    require(click_label(client, "Air quality details"))
    wait_labels("Air quality", "Native particulate forecast", "5.53071", absent=("Native weather forecast",))
    require(status() == before)
    report["checks"]["existing_aq_detail_without_new_request"] = True
    final = snapshot(client)
    require(final["localOnly"] and final["weatherRequests"] == before["calls"]
            and final["airQualityRequests"] == before["airQualityCalls"])
    report["checks"].update(same_origin_loaded_resources=True, provider_requests=before["calls"],
        air_quality_provider_requests=before["airQualityCalls"], final_semantics_sha256=canonical_hash(final["labels"]))


def inside(args, stage, static_root, work, node, browser_stage, metadata, source, support):
    require(args.host_netns and os.readlink("/proc/self/ns/net") != args.host_netns)
    require(all(os.statvfs(path).f_flag & os.ST_RDONLY for path in
                (Path("/"), ROOT, stage, static_root, browser_stage)))
    require(not os.statvfs(work).f_flag & os.ST_RDONLY)
    identity = support.work_identity(work)
    support.validate_isolated_browser_home(work)
    links = json.loads(subprocess.check_output(["/usr/bin/ip", "-j", "link", "show"], text=True))
    require([item["ifname"] for item in links] == ["lo"] and "UP" in links[0]["flags"])
    for name in support.PROFILE_DIRS[:-1]:
        (work / name).mkdir(mode=0o700)
    (work / "profile/prefs.js").write_text('user_pref("remote.prefs.recommended", false);\n')
    environment = support.clean_environment()
    environment.update(MOZ_NO_REMOTE="1", MOZ_CRASHREPORTER_DISABLE="1",
        XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
        XDG_RUNTIME_DIR=str(work / "runtime"), TMPDIR=str(work / "tmp"),
        VOLPAROSSA_TEST_HOST_NETNS=args.host_netns)
    report = dict(schema=1, passed=False, phase="fixture_start", source=source,
        scope=dict(actual_overmorrow_ui=False, synthetic_weather=True, synthetic_air_quality=True,
            actual_http_bridge=False, core_executed=False, overlay_proven=False,
            upstream_origin_proven=False, native_mobile_proven=False),
        isolation=dict(host_read_only=True, separate_user_netns=True, interfaces=["lo"], fresh_private_profile=True),
        runtime=dict(version=metadata["version"], source_stamp=metadata["source_stamp"],
            sha256=metadata["runtime_sha256"], node_sha256=support.NODE_SHA256), checks={}, cleanup={})
    fixture = browser = connection = client = None
    normal_browser_stop = normal_fixture_stop = False
    try:
        fixture = subprocess.Popen([str(node), "--max-old-space-size=256", str(HERE / "browser-fixture.mjs"),
            str(static_root), str(work)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True)
        ready = support.read_line(fixture)
        require(ready["ready"] is True and ready["synthetic"] is True and ready["core_executed"] is False)
        require(ready["valid_at"] != ready["air_quality_valid_at"] and ready["weather_run"] != ready["air_quality_run"])
        require(ready["origin"].startswith("http://127.0.0.1:") and ready["origin"].rsplit(":", 1)[1].isdigit())
        report["scope"]["actual_http_bridge"] = True
        report["phase"] = "browser_start"
        browser = subprocess.Popen([str(browser_stage / metadata["executable"]), "--headless", "--no-remote",
            "--new-instance", "--profile", str(work / "profile"), "--marionette",
            "--remote-allow-system-access", "about:blank"], env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            require(browser.poll() is None)
            try:
                connection = socket.create_connection(("127.0.0.1", 2828), timeout=1)
                connection.settimeout(15)
                client = support.Marionette(connection)
                break
            except (ConnectionRefusedError, TimeoutError):
                if connection: connection.close()
                connection = None
                time.sleep(0.1)
        require(client is not None)
        client.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})
        client.command("Marionette:SetContext", {"value": "chrome"})
        require(Path(client.script('return Services.dirsvc.get("GreD", Ci.nsIFile).path;')).resolve() == browser_stage)
        client.command("Marionette:SetContext", {"value": "content"})
        client.command("WebDriver:SetTimeouts", {"pageLoad": 20000, "script": 10000})
        run_ui(client, fixture, ready, support, report)
        report["phase"] = "shutdown"
        client.command("Marionette:Quit", {"flags": ["eAttemptQuit"]})
        normal_browser_stop = browser.wait(timeout=15) == 0
        normal_fixture_stop = support.fixture_command(fixture, "stop")["stopped"] is True and fixture.wait(timeout=10) == 0
        require(normal_browser_stop and normal_fixture_stop)
        report.update(passed=True, phase="complete")
    except Exception as error:
        report["failure_type"] = type(error).__name__
        if isinstance(error, RuntimeError) and " failed: " in str(error):
            try:
                frame = ast.literal_eval(str(error).split(" failed: ", 1)[1])
                code = frame[2].get("error")
                if code in ("javascript error", "unknown command", "invalid argument", "timeout", "no such window"):
                    report["marionette_error"] = code
                    # Only a bounded first line from this synthetic test page;
                    # never record a stack, browser profile or network payload.
                    report["marionette_message"] = str(frame[2].get("message", "")).splitlines()[0][:200]
            except (ValueError, SyntaxError, TypeError, IndexError, AttributeError):
                pass
        raise
    finally:
        if connection: connection.close()
        browser_stopped, fixture_stopped = support.stop(browser), support.stop(fixture)
        if fixture is not None:
            for stream in (fixture.stdin, fixture.stdout):
                try: stream.close()
                except OSError: pass
        removed = support.remove_private(work, identity) if browser_stopped and fixture_stopped else False
        report["cleanup"] = dict(browser_exited=browser_stopped, fixture_exited=fixture_stopped,
            private_profile_removed=removed, normal_browser_stop=normal_browser_stop, normal_fixture_stop=normal_fixture_stop)
        report["passed"] = report["passed"] and all(report["cleanup"].values())
        support.save_report(work, report)


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "static-root", "browser-stage", "browser-root", "node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host-netns", help=argparse.SUPPRESS)
    args = parser.parse_args()
    support = load_module("drizzli_browser_sandbox", ROOT / "integrations/drizzli/smoke_browser.py")
    stage, static_root, work, node, browser_stage = (path.resolve(strict=flag) for path, flag in
        ((args.stage, True), (args.static_root, True), (args.output, False), (args.node, True), (args.browser_stage, True)))
    require(all(path.parent == ROOT / "build" for path in (stage, static_root, work)))
    require(len({stage, static_root, work}) == 3)
    require(browser_stage.is_relative_to(support.BROWSER_ROOT / "build") and support.digest(node) == support.NODE_SHA256)
    metadata = support.validate_stage(browser_stage)
    source = validate_source(stage, static_root, support)
    if args.inside:
        inside(args, stage, static_root, work, node, browser_stage, metadata, source, support)
        return
    def memory_available():
        return int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                        if line.startswith("MemAvailable:"))) * 1024
    require(memory_available() >= 3 * 1024 ** 3)
    require(not work.exists() and not work.is_symlink())
    work.mkdir(mode=0o700)
    identity = support.work_identity(work)
    host_netns = os.readlink("/proc/self/ns/net")
    wrapper, completed = None, False
    try:
        command = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user", "--unshare-net",
            "--unshare-pid", "--ro-bind", "/", "/", *support.isolated_browser_home(work),
            "--bind", str(work), str(work), "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--",
            sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--inside", "--host-netns", host_netns]
        wrapper = subprocess.Popen(command, env=support.clean_environment(), start_new_session=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                completed = wrapper.wait(timeout=1) == 0
                break
            except subprocess.TimeoutExpired:
                require(memory_available() >= 2 * 1024 ** 3)
        require(completed)
    finally:
        stopped = support.stop(wrapper)
        removed = support.remove_private(work, identity) if stopped else False
        report = dict(schema=1, passed=False, phase="wrapper_failed", source=source)
        path = work / "report.json"
        if path.exists():
            require(not path.is_symlink() and path.stat().st_size <= 16384)
            report = json.loads(path.read_text())
        report["outer_cleanup"] = dict(namespace_wrapper_exited=stopped, private_profile_removed=removed,
            host_netns_unchanged=os.readlink("/proc/self/ns/net") == host_netns)
        report["wrapper_outcome"] = "completed" if completed else "failed_or_timed_out"
        report["passed"] = completed and report["passed"] and all(report["outer_cleanup"].values())
        support.save_report(work, report)
    require(report["passed"])
    print(json.dumps({"passed": True, "report": str(work / "report.json"),
                      "actual_overmorrow_ui": True, "synthetic_products": True, "overlay_proven": False}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, TimeoutError, RuntimeError,
            subprocess.SubprocessError, KeyboardInterrupt):
        print("isolated Overmorrow browser smoke failed; inspect its closed report if created", file=sys.stderr)
        raise SystemExit(1) from None
