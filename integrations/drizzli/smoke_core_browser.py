#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual Drizz.li + production HTTP/core adapter in the disposable KVM trial.

No synthetic provider, origin request, cache seeding, installation or host run.
The enclosing core trial independently proves acquisition and the cold transfer.
"""
import argparse
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

import smoke_browser as shared

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRIVATE_DIRS = (*shared.PROFILE_DIRS, "scratch")
MAX_BUNDLE_BYTES = 512 * 1024**2
PHASES = {"inputs", "sandbox", "bridge_start", "provider", "browser_start", "hydration", "refresh", "shutdown", "complete"}


def require(value):
    if not value:
        raise ValueError("core_browser_check_failed")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def hex64(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def raw_file(path, maximum, mode=None):
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum
                and info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022)
        if mode is not None:
            require(stat.S_IMODE(info.st_mode) == mode)
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
        require(len(data) == info.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                == (info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return data


def file_hash(path, maximum, mode=None):
    """Hash bounded immutable inputs without materializing a large runtime."""
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum
                and info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022)
        require(mode is None or stat.S_IMODE(info.st_mode) == mode)
        digest, read = hashlib.sha256(), 0
        while data := source.read(1024 * 1024):
            read += len(data)
            require(read <= maximum)
            digest.update(data)
        after = os.fstat(source.fileno())
        require(read == info.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                == (info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return digest.hexdigest(), read


def read_json(path, maximum, mode=None):
    return json.loads(raw_file(path, maximum, mode), object_pairs_hook=pairs)


def stamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value))
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def validate_expected(value, config):
    require(type(value) is dict and set(value) == {"schema", "core_sha256", "cold_receipt_sha256", "publication",
            "forecast", "display", "display_sha256"} and type(value["schema"]) is int and value["schema"] == 1)
    require(all(hex64(value[key]) for key in ("core_sha256", "cold_receipt_sha256", "display_sha256")))
    publication, forecast, display = (value[key] for key in ("publication", "forecast", "display"))
    require(type(publication) is dict and set(publication) == {"publisher_key", "name", "revision", "manifest_id",
            "sha256", "bytes", "expires_unix_seconds"})
    require(all(hex64(publication[key]) for key in ("publisher_key", "manifest_id", "sha256")))
    require(type(publication["revision"]) is int and publication["revision"] >= 1
            and type(publication["bytes"]) is int and 0 < publication["bytes"] <= 131072
            and type(publication["expires_unix_seconds"]) is int and publication["expires_unix_seconds"] > time.time())
    require(type(config) is dict and set(config) == {"core", "variables"} and type(config["core"]) is dict)
    core, query = config["core"], config["core"]["query"]
    require(core["mode"] == "core-cache" and core["reuseCache"] is True
            and core["publisherKey"] == publication["publisher_key"] and core["name"] == publication["name"]
            and core["minRevision"] <= publication["revision"])
    require(forecast["schema"] == "volparossa.forecast.v1" and forecast["kind"] == "forecast"
            and forecast["area"]["sharing"] == "public-community"
            and forecast["area"]["latitude"] == query["latitude"] and forecast["area"]["longitude"] == query["longitude"]
            and forecast["source"]["model"] == query["model"] and forecast["source"]["model_run_at"] == query["run"]
            and query["communityArea"] is True and ("wind_10m" in forecast["units"]) == query["includeWind"])
    require(type(display) is dict and set(display) == {"coordinates", "native", "values", "model_run", "expires_at"}
            and hashlib.sha256(canonical(display)).hexdigest() == value["display_sha256"])
    require(type(display["native"]) is list and 1 <= len(display["native"]) <= 16
            and display["native"] == [sample["valid_at"] for sample in forecast["samples"]]
            and query["steps"] == [sample["lead_hours"] for sample in forecast["samples"]]
            and len(display["values"]) == len(display["native"]))
    for when, lead in zip(display["native"], query["steps"]):
        require(type(lead) is int and stamp(when) == stamp(query["run"]) + lead * 3600)
    require(all(type(row) is list and len(row) == 3 and all(type(cell) is str
                and (cell == "Not available" or re.fullmatch(r"-?\d{1,6}\.\d", cell)) for cell in row)
                for row in display["values"]))
    require(type(display["coordinates"]) is str and len(display["coordinates"]) <= 100
            and display["model_run"] == forecast["source"]["model"] + " · " + forecast["source"]["model_run_at"]
            and stamp(display["expires_at"]) == min(stamp(forecast["freshness"]["expires_at"]), publication["expires_unix_seconds"])
            and stamp(display["expires_at"]) > time.time())
    return value


def validate_bundle(root, expected):
    require(root.resolve(strict=True) == root and ROOT == root / "volparossa-weather" and hex64(expected))
    require(root.stat().st_uid == os.getuid() and stat.S_IMODE(root.stat().st_mode) == 0o500)
    raw = raw_file(root / "INPUTS.json", 131072, 0o400)
    require(hashlib.sha256(raw).hexdigest() == expected)
    manifest = json.loads(raw, object_pairs_hook=pairs)
    require(type(manifest) is dict and set(manifest) == {"version", "kind", "files"}
            and manifest["version"] == 1 and manifest["kind"] == "volparossa-weather-client-inputs"
            and type(manifest["files"]) is dict and 1 <= len(manifest["files"]) <= 1024)
    require(raw.isascii() and raw == canonical(manifest) + b"\n")
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
                and type(record["mode"]) is int and record["mode"] in (0o400, 0o500) and hex64(record["sha256"]))
        digest, size = file_hash(path, record["bytes"], record["mode"])
        require(size == record["bytes"] and digest == record["sha256"])
        total += size
        require(total <= MAX_BUNDLE_BYTES)
        found.add(relative)
    require(found == set(manifest["files"]))
    files = manifest["files"]
    required = ["volparossa-weather/integrations/drizzli/smoke_core_browser.py",
                "volparossa-weather/integrations/drizzli/prepare-core-browser.mjs",
                "volparossa-weather/scripts/serve-provider.mjs", "runtime/node"]
    require(all(name in files for name in required) and files["runtime/node"]["sha256"] == shared.NODE_SHA256)
    built = root / "volparossa-weather/build/drizzli-volparossa/build"
    hashes = {name.split("/build/drizzli-volparossa/build/", 1)[1]: record["sha256"]
              for name, record in files.items() if "/build/drizzli-volparossa/build/" in name}
    retained = read_json(ROOT / "integrations/drizzli/browser-smoke.json", 16384)
    require(hashlib.sha256(canonical(hashes)).hexdigest() == retained["source"]["built_tree_sha256"])
    browser = root / "volparossa-browser/build/firefox-esr-smoke-v3"
    metadata = shared.validate_stage(browser)
    return built, browser, metadata, dict(bundle_manifest_sha256=expected,
        driver_sha256=files[required[0]]["sha256"], preparer_sha256=files[required[1]]["sha256"],
        built_tree_sha256=retained["source"]["built_tree_sha256"], node_sha256=shared.NODE_SHA256,
        bridge_modules={name: files["volparossa-weather/" + name]["sha256"] for name in
            ("scripts/serve-provider.mjs", "src/provider-http.mjs", "src/provider-core.mjs", "src/core-cache.mjs")})


def available_memory():
    return int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                    if line.startswith("MemAvailable:"))) * 1024


def boundary(args, inner=False):
    require(os.getuid() == 985 and os.getgid() == args.control_gid and not os.getgroups()
            and socket.gethostname() == "volparossa-alpha")
    current = os.readlink("/proc/self/ns/net")
    require(re.fullmatch(r"net:\[\d+\]", args.parent_netns) and re.fullmatch(r"net:\[\d+\]", args.client_netns)
            and args.parent_netns != args.client_netns)
    if inner:
        require(current not in (args.parent_netns, args.client_netns))
    else:
        require(current == args.client_netns)
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
        require(int(status["NoNewPrivs"]) == 1 and all(int(status[name], 16) == 0
                for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")))
        require(subprocess.check_output(["systemd-detect-virt"], text=True,
                timeout=5, env=shared.clean_environment()).strip() == "kvm")


def identity(work):
    require(work.resolve(strict=True) == work)
    info = work.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
    return info.st_dev, info.st_ino


def cleanup(work, expected):
    try:
        require(identity(work) == expected)
    except (OSError, ValueError):
        return False
    success = True
    for name in PRIVATE_DIRS:
        path = work / name
        try:
            if path.exists() or path.is_symlink():
                info = path.lstat()
                require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and info.st_uid == os.getuid())
                shutil.rmtree(path)
        except (OSError, ValueError):
            success = False
    return success and not any((work / name).exists() or (work / name).is_symlink() for name in PRIVATE_DIRS)


def report_base(source, expected):
    return dict(schema=1, passed=False, phase="inputs", source=source,
        expected=dict(expected_sha256=None, cold_receipt_sha256=expected["cold_receipt_sha256"],
            core_sha256=expected["core_sha256"], display_sha256=expected["display_sha256"],
            forecast_sha256=expected["publication"]["sha256"], manifest_id=expected["publication"]["manifest_id"]),
        scope=dict(actual_drizzli_ui=False, actual_http_bridge=False, real_core_adapter=False,
            synthetic_weather=False, standalone_origin_proven=False, standalone_overlay_proven=False,
            browser_triggered_cold_fetch=False), checks={}, cleanup={})


def check_api(result, expected):
    publication = expected["publication"]
    require(result["schema"] == "volparossa.weather.provider.v1" and result["kind"] == "forecast"
            and result["forecast"] == expected["forecast"])
    delivery = result["delivery"]
    require(delivery["mode"] == "core-cache" and all(delivery[key] == publication[key]
            for key in ("publisher_key", "name", "revision", "manifest_id", "sha256"))
            and delivery["upstream_origin_attested"] is False and delivery["manifest_media_type_checked"] is False
            and stamp(delivery["publication_expires_at"]) == publication["expires_unix_seconds"]
            and result["freshness"]["expires_at"] == expected["display"]["expires_at"]
            and stamp(result["freshness"]["expires_at"]) > time.time()
            and result["timeline"]["valid_at"] == expected["display"]["native"])


def api(origin, expected):
    port = int(origin.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.request("GET", "/api/volparossa/forecast", headers={"Accept": "application/json"})
        response = connection.getresponse()
        require(response.status == 200 and response.getheader("Cache-Control") == "no-store"
                and response.getheader("Content-Type").startswith("application/json"))
        raw = response.read(524289)
        require(0 < len(raw) <= 524288)
        check_api(json.loads(raw, object_pairs_hook=pairs), expected)
        return hashlib.sha256(raw).hexdigest()
    finally:
        connection.close()


def dom(client):
    return client.script('''
      const area=document.querySelector('section[aria-label="VOLPAROSSA forecast"]');
      if(!area || !area.querySelector('tbody')) return null;
      return {native:[...area.querySelectorAll('tbody tr')].map(r=>r.children[0].textContent.trim()),
        values:[...area.querySelectorAll('tbody tr')].map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent.trim())),
        details:[...area.querySelectorAll('dl dd')].map(c=>c.textContent.trim()),
        attribution:!!area.querySelector('a[href="https://www.ecmwf.int/en/forecasts/datasets/open-data"]'),
        licence:!!area.querySelector('a[href="https://creativecommons.org/licenses/by/4.0/"]'),
        missing:area.textContent.includes('Missing does not mean dry, clear or clean air'),
        localOnly:performance.getEntriesByType('resource').every(e=>e.name.startsWith(location.origin+'/')&&!e.name.includes('/api/geo')),
        apiRequests:performance.getEntriesByType('resource').filter(e=>e.name===location.origin+'/api/volparossa/forecast').length};
    ''')


def check_dom(value, expected, requests):
    display = expected["display"]
    return (type(value) is dict and value.get("native") == display["native"] and value.get("values") == display["values"]
            and value.get("details") == [display["coordinates"], display["model_run"], display["expires_at"]]
            and value.get("apiRequests") == requests and all(value.get(name) is True
                for name in ("attribution", "licence", "missing", "localOnly")))


def wait_dom(client, connection, expected, requests):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection.settimeout(min(15, remaining))
        observed = dom(client)
        if check_dom(observed, expected, requests):
            connection.settimeout(15)
            display = dict(coordinates=observed["details"][0], model_run=observed["details"][1],
                expires_at=observed["details"][2], native=observed["native"], values=observed["values"])
            digest = hashlib.sha256(canonical(display)).hexdigest()
            require(digest == expected["display_sha256"])
            return digest
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise TimeoutError("dom_deadline")


def inside(args, built, browser_stage, metadata, source, expected, config):
    work = args.output
    boundary(args, True)
    require(all(os.statvfs(path).f_flag & os.ST_RDONLY for path in (Path("/"), args.bundle_root, built, browser_stage)))
    shared.validate_isolated_browser_home(work)
    links = json.loads(subprocess.check_output(["/usr/bin/ip", "-j", "link", "show"], text=True))
    require([row["ifname"] for row in links] == ["lo"] and "UP" in links[0]["flags"])
    owned = identity(work)
    for name in PRIVATE_DIRS:
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
            str(ROOT / "scripts/serve-provider.mjs"), "--config", str(args.config), "--static-root", str(built), "--port", "0"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True)
        ready = shared.read_line(bridge)
        require(set(ready) == {"listening", "scope"} and ready["scope"] == "fixed-public-community-forecast"
                and re.fullmatch(r"http://127\.0\.0\.1:[1-9]\d{0,4}", ready["listening"]))
        origin = ready["listening"]
        report["scope"]["actual_http_bridge"] = True
        report["phase"] = "provider"
        report["checks"]["api_response_sha256"] = api(origin, expected)
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
        client.command("WebDriver:SetTimeouts", {"pageLoad": 15000, "script": 10000})
        report["phase"] = "hydration"
        client.command("WebDriver:Navigate", {"url": origin + "/en/weather/week/"})
        report["checks"]["initial_dom_display_sha256"] = wait_dom(client, connection, expected, 1)
        report["scope"]["actual_drizzli_ui"] = True
        report["checks"]["initial_dom_matches_cold_publication"] = True
        report["phase"] = "refresh"
        require(client.script('const b=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] button"); if(!b||b.disabled)return false; b.click(); return true;'))
        report["checks"]["refresh_dom_display_sha256"] = wait_dom(client, connection, expected, 2)
        report["checks"].update(refresh_dom_matches_cold_publication=True, browser_api_requests=2,
            provider_requests_checked=1, exact_native_times_and_values=True, explicit_missing_capabilities=True,
            no_external_resources=True, source_attribution=True)
        report["phase"] = "shutdown"
        client.command("Marionette:Quit", {"flags": ["eForceQuit"]})
        normal_browser = browser.wait(timeout=10) == 0
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
        removed = cleanup(work, owned) if browser_stopped and bridge_stopped else False
        report["cleanup"] = dict(browser_exited=browser_stopped, bridge_exited=bridge_stopped,
            private_state_removed=removed, normal_browser_stop=normal_browser, normal_bridge_stop=normal_bridge)
        report["passed"] = report["passed"] and all(report["cleanup"].values())
        shared.save_report(work, report)


def main():
    deadline = time.monotonic() + 240
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    def interrupted(_signum, _frame):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    # A whole-driver wall bound also covers immutable-input validation. On expiry
    # raise through the same independent cleanup path, rather than abrupt exit.
    signal.signal(signal.SIGALRM, interrupted)
    signal.setitimer(signal.ITIMER_REAL, 240)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    for name in ("bundle-root", "config", "expected", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("bundle-manifest-sha256", "parent-netns", "client-netns"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--control-gid", type=int, required=True)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("bundle_root", "config", "expected", "output"):
        value = getattr(args, name)
        require(value.is_absolute() and value.resolve() == value)
    require(args.output.parent == args.config.parent == args.expected.parent
            and not args.output.is_relative_to(args.bundle_root))
    boundary(args, args.inside)
    built, browser, metadata, source = validate_bundle(args.bundle_root, args.bundle_manifest_sha256)
    config = read_json(args.config, 16384, 0o600)
    expected = validate_expected(read_json(args.expected, 192 * 1024, 0o400), config)
    require(config["core"]["scratchParent"] == str(args.output / "scratch"))
    binary = Path(config["core"]["executable"])
    require(file_hash(binary, 512 * 1024**2)[0] == expected["core_sha256"] and os.access(binary, os.X_OK))
    control = Path(config["core"]["controlSocket"])
    require(control.resolve(strict=True) == control and stat.S_ISSOCK(control.stat().st_mode))
    if args.inside:
        inside(args, built, browser, metadata, source, expected, config)
        return
    require(available_memory() >= 1536 * 1024**2 and not args.output.exists() and time.monotonic() < deadline)
    args.output.mkdir(mode=0o700)
    owned = identity(args.output)
    wrapper = None
    completed = False
    try:
        mounts = shared.isolated_browser_home(args.output)
        command = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user", "--unshare-net",
            "--unshare-pid", "--ro-bind", "/", "/", *mounts, "--bind", str(args.output), str(args.output),
            "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--", sys.executable, "-B",
            str(Path(__file__).resolve()), *sys.argv[1:], "--inside"]
        wrapper = subprocess.Popen(command, env=shared.clean_environment(), start_new_session=True)
        while time.monotonic() < deadline:
            try:
                completed = wrapper.wait(timeout=1) == 0
                break
            except subprocess.TimeoutExpired:
                require(available_memory() >= 768 * 1024**2)
    finally:
        stopped = shared.stop(wrapper)
        removed = cleanup(args.output, owned) if stopped else False
        report = report_base(source, expected)
        report["expected"]["expected_sha256"] = shared.digest(args.expected)
        if (args.output / "report.json").exists():
            try:
                candidate = read_json(args.output / "report.json", 16384, 0o600)
                require(candidate["phase"] in PHASES and candidate["source"] == source)
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
        print('{"passed":false,"failure":"core_browser_check_failed"}', file=sys.stderr)
        raise SystemExit(1) from None
