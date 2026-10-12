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


def readonly_core_hash(path, expected_sha256, outer_userns):
    """Recheck one authorized core executable across a user-namespace boundary.

    Host-root ownership has no useful numeric representation in this single-UID
    namespace. Authority here is the independently supplied exact digest plus a
    read-only descriptor, not acceptance of an overflow UID. Generic input
    ownership checks intentionally remain unchanged.
    """
    require(hex64(expected_sha256) and type(outer_userns) is str
            and re.fullmatch(r"user:\[\d+\]", outer_userns)
            and os.readlink("/proc/self/ns/user") != outer_userns)
    mappings = [[int(value) for value in line.split()]
                for line in Path("/proc/self/uid_map").read_text().splitlines()]
    # bwrap may use an intermediate namespace where the outer unprivileged UID
    # is mapped to zero. Neither accepted single-ID map exposes host root here.
    require(mappings in ([[os.getuid(), os.getuid(), 1]], [[os.getuid(), 0, 1]]))
    require(path.is_absolute() and path.resolve(strict=True) == path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 512 * 1024**2
                and not info.st_mode & 0o022 and os.access(path, os.X_OK)
                and os.fstatvfs(source.fileno()).f_flag & os.ST_RDONLY)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_gid,
                                 value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        digest, size = hashlib.sha256(), 0
        while data := source.read(1024 * 1024):
            size += len(data)
            require(size <= info.st_size)
            digest.update(data)
        require(size == info.st_size and identity(os.fstat(source.fileno())) == identity(info)
                and identity(path.stat(follow_symlinks=False)) == identity(info)
                and digest.hexdigest() == expected_sha256)
    return digest.hexdigest(), size


def verify_core_binary(path, expected_sha256, args):
    if args.inside:
        # The namespace-specific exception is available only after the complete
        # guest/UID/group/inner-network boundary has passed again.
        boundary(args, True)
        return readonly_core_hash(path, expected_sha256, args.outer_userns)
    require(args.outer_userns is None)
    result = file_hash(path, 512 * 1024**2)
    require(result[0] == expected_sha256 and os.access(path, os.X_OK))
    return result


def read_json(path, maximum, mode=None):
    return json.loads(raw_file(path, maximum, mode), object_pairs_hook=pairs)


def stamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value))
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def validate_expected(value, config):
    require(type(value) is dict and type(value.get("schema")) is int)
    if value["schema"] in (2, 4):
        require(set(value) == {"schema", "core_sha256", "products", "display_sha256"}
                and hex64(value["core_sha256"]) and hex64(value["display_sha256"])
                and type(value["products"]) is dict and set(value["products"]) == {"weather", "air_quality"}
                and type(config) is dict and set(config) == {"core", "variables", "airQuality"}
                and type(config["airQuality"]) is dict and set(config["airQuality"]) == {"core", "variables"})
        weather, air_quality = value["products"]["weather"], value["products"]["air_quality"]
        for name, product, selected in (("weather", weather, config), ("air_quality", air_quality, config["airQuality"])):
            require(type(product) is dict and set(product) == {"cold_receipt_sha256", "publication", "forecast", "display", "display_sha256"})
            validate_product(product, selected, name)
        core, aq = config["core"], config["airQuality"]["core"]
        require(all(core[key] == aq[key] for key in ("executable", "controlSocket", "scratchParent"))
                and core["name"] != aq["name"] and core["cache"] != aq["cache"]
                and all(core["query"][key] == aq["query"][key] for key in ("latitude", "longitude"))
                and config["airQuality"]["variables"] == ["pm2_5", "pm10"]
                and {"temperature_2m", "wind_speed_10m", "wind_direction_10m", "precipitation"}.issubset(config["variables"])
                and hashlib.sha256(canonical({name: product["display"] for name, product in value["products"].items()})).hexdigest()
                    == value["display_sha256"])
        return value
    require(type(value) is dict and set(value) == {"schema", "core_sha256", "cold_receipt_sha256", "publication",
            "forecast", "display", "display_sha256"} and type(value["schema"]) is int and value["schema"] == 1)
    require(hex64(value["core_sha256"]) and type(config) is dict and set(config) == {"core", "variables"})
    validate_product(value, config)
    return value


def validate_product(value, config, product="legacy"):
    require(all(hex64(value[key]) for key in ("cold_receipt_sha256", "display_sha256")))
    publication, forecast, display = (value[key] for key in ("publication", "forecast", "display"))
    require(type(publication) is dict and set(publication) == {"publisher_key", "name", "revision", "manifest_id",
            "sha256", "bytes", "expires_unix_seconds"})
    require(all(hex64(publication[key]) for key in ("publisher_key", "manifest_id", "sha256")))
    require(type(publication["revision"]) is int and publication["revision"] >= 1
            and type(publication["bytes"]) is int and 0 < publication["bytes"] <= 131072
            and type(publication["expires_unix_seconds"]) is int and publication["expires_unix_seconds"] > time.time())
    require(type(config["core"]) is dict)
    core, query = config["core"], config["core"]["query"]
    require(core["mode"] == "core-cache" and core["reuseCache"] is True
            and core["publisherKey"] == publication["publisher_key"] and core["name"] == publication["name"]
            and core["minRevision"] <= publication["revision"])
    air_quality = product == "air_quality"
    require(forecast["schema"] == ("volparossa.air-quality.forecast.v1" if air_quality else "volparossa.forecast.v1")
            and forecast["kind"] == "forecast"
            and forecast["area"]["sharing"] == "public-community"
            and forecast["area"]["latitude"] == query["latitude"] and forecast["area"]["longitude"] == query["longitude"]
            and forecast["source"]["model"] == query["model"] and forecast["source"]["model_run_at"] == query["run"]
            and query["communityArea"] is True)
    if air_quality:
        require(forecast["units"] == {"pm2_5": "ug/m3", "pm10": "ug/m3"}
                and forecast["source"]["model"] == "gefs-aerosols"
                and forecast["source"]["provider"] == "noaa")
    else:
        require(("wind_10m" in forecast["units"]) == query["includeWind"]
                and ("precipitation" in forecast["units"]) == (product == "weather")
                and query.get("includePrecipitation", False) == (product == "weather")
                and (product != "weather" or query["includeWind"] is True))
    require(type(display) is dict and set(display) == {"coordinates", "native", "values", "model_run", "expires_at"}
            | ({"attribution", "license", "license_url", "changes"} if air_quality else set())
            and hashlib.sha256(canonical(display)).hexdigest() == value["display_sha256"])
    require(type(display["native"]) is list and 1 <= len(display["native"]) <= 16
            and display["native"] == [sample["valid_at"] for sample in forecast["samples"]]
            and query["steps"] == [sample["lead_hours"] for sample in forecast["samples"]]
            and len(display["values"]) == len(display["native"]))
    for when, lead in zip(display["native"], query["steps"]):
        require(type(lead) is int and stamp(when) == stamp(query["run"]) + lead * 3600)
    if product == "legacy":
        require(all(type(row) is list and len(row) == 3 and all(type(cell) is str
                and (cell == "Not available" or re.fullmatch(r"-?\d{1,6}\.\d", cell)) for cell in row)
                for row in display["values"]))
    else:
        for row, sample in zip(display["values"], forecast["samples"]):
            require(type(row) is list and len(row) == (2 if air_quality else 5))
            numbers = row if air_quality else row[:4]
            require(all(type(cell) is str and len(cell) <= 40 and (cell == "Not available"
                    or re.fullmatch(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", cell)) for cell in numbers))
            if not air_quality:
                require(row[4] == sample["precipitation"]["start_at"] + " → " + sample["precipitation"]["end_at"])
        if air_quality:
            require(all(display[key] == forecast["source"][key] for key in ("attribution", "license", "license_url", "changes"))
                    and display["attribution"] == "NOAA/NWS GEFS-Aerosols"
                    and display["license"] == "LicenseRef-NOAA-NODD"
                    and display["license_url"] == "https://registry.opendata.aws/noaa-gefs/")
    require(type(display["coordinates"]) is str and len(display["coordinates"]) <= 100
            and display["model_run"] == forecast["source"]["model"] + " · " + forecast["source"]["model_run_at"]
            and stamp(display["expires_at"]) == min(stamp(forecast["freshness"]["expires_at"]), publication["expires_unix_seconds"])
            and stamp(display["expires_at"]) > time.time())


def validate_bundle(root, expected, version=None):
    require(root.resolve(strict=True) == root and ROOT == root / "volparossa-weather" and hex64(expected))
    require(root.stat().st_uid == os.getuid() and stat.S_IMODE(root.stat().st_mode) == 0o500)
    raw = raw_file(root / "INPUTS.json", 131072, 0o400)
    require(hashlib.sha256(raw).hexdigest() == expected)
    manifest = json.loads(raw, object_pairs_hook=pairs)
    require(type(manifest) is dict and set(manifest) == {"version", "kind", "files"}
            and type(manifest["version"]) is int and manifest["version"] in (1, 2, 4)
            and manifest["kind"] == "volparossa-weather-client-inputs"
            and type(manifest["files"]) is dict and 1 <= len(manifest["files"]) <= 1024)
    require(version is None or manifest["version"] == version)
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
    proof_path = "integrations/drizzli/" + {1: "browser-smoke.json", 2: "air-quality-browser-smoke.json",
                                          4: "hosted-browser-proof.json"}[manifest["version"]]
    retained = read_json(ROOT / proof_path, 16384)
    if manifest["version"] == 4:
        # This unchanged receipt proves the admitted synthetic UI build only.
        # The current driver/preparer have their own manifest hashes below;
        # neither they nor real core delivery are retroactively proven by it.
        require(retained.get("passed") is True and retained.get("phase") == "complete"
                and retained.get("scenario") == "precipitation" and retained.get("air_quality_scenario") is True
                and retained.get("scope") == dict(actual_drizzli_ui=True, actual_http_bridge=True,
                    synthetic_weather=True, synthetic_air_quality=True, core_executed=False,
                    overlay_proven=False, upstream_origin_proven=False)
                and type(retained.get("cleanup")) is dict and bool(retained["cleanup"])
                and all(value is True for value in retained["cleanup"].values())
                and hex64(retained["source"]["driver_sha256"]))
    require(hashlib.sha256(canonical(hashes)).hexdigest() == retained["source"]["built_tree_sha256"])
    browser = root / "volparossa-browser/build/firefox-esr-smoke-v3"
    metadata = shared.validate_stage(browser)
    source = dict(bundle_manifest_sha256=expected,
        driver_sha256=files[required[0]]["sha256"], preparer_sha256=files[required[1]]["sha256"],
        built_tree_sha256=retained["source"]["built_tree_sha256"], node_sha256=shared.NODE_SHA256,
        bridge_modules={name: files["volparossa-weather/" + name]["sha256"] for name in
            ("scripts/serve-provider.mjs", "src/provider-http.mjs", "src/provider-core.mjs", "src/core-cache.mjs",
             *(("src/air-quality.mjs", "src/air-quality-provider.mjs", "src/air-quality-core.mjs") if manifest["version"] in (2, 4) else ()))})
    if manifest["version"] == 4:
        source["synthetic_ui_proof"] = dict(sha256=files["volparossa-weather/" + proof_path]["sha256"],
            driver_sha256=retained["source"]["driver_sha256"], core_executed=False, overlay_proven=False)
    return built, browser, metadata, source


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
    if expected["schema"] in (2, 4):
        return dict(schema=expected["schema"], passed=False, phase="inputs", source=source,
            expected=dict(expected_sha256=None, core_sha256=expected["core_sha256"], display_sha256=expected["display_sha256"]),
            products={name: dict(expected=dict(cold_receipt_sha256=product["cold_receipt_sha256"],
                display_sha256=product["display_sha256"], forecast_sha256=product["publication"]["sha256"],
                manifest_id=product["publication"]["manifest_id"]), checks={}) for name, product in expected["products"].items()},
            scope=dict(actual_drizzli_ui=False, actual_http_bridge=False, real_core_adapter=False,
                synthetic_weather=False, standalone_origin_proven=False, standalone_overlay_proven=False,
                browser_triggered_cold_fetch=False, synthetic_air_quality=False, separate_native_runs=False),
            checks={}, cleanup={})
    return dict(schema=1, passed=False, phase="inputs", source=source,
        expected=dict(expected_sha256=None, cold_receipt_sha256=expected["cold_receipt_sha256"],
            core_sha256=expected["core_sha256"], display_sha256=expected["display_sha256"],
            forecast_sha256=expected["publication"]["sha256"], manifest_id=expected["publication"]["manifest_id"]),
        scope=dict(actual_drizzli_ui=False, actual_http_bridge=False, real_core_adapter=False,
            synthetic_weather=False, standalone_origin_proven=False, standalone_overlay_proven=False,
            browser_triggered_cold_fetch=False), checks={}, cleanup={})


def check_api(result, expected, product="weather"):
    publication = expected["publication"]
    require(result["schema"] == ("volparossa.air-quality.provider.v1" if product == "air_quality" else "volparossa.weather.provider.v1")
            and result["kind"] == "forecast"
            and result["forecast"] == expected["forecast"])
    delivery = result["delivery"]
    require(delivery["mode"] == "core-cache" and all(delivery[key] == publication[key]
            for key in ("publisher_key", "name", "revision", "manifest_id", "sha256"))
            and delivery["upstream_origin_attested"] is False and delivery["manifest_media_type_checked"] is False
            and stamp(delivery["publication_expires_at"]) == publication["expires_unix_seconds"]
            and result["freshness"]["expires_at"] == expected["display"]["expires_at"]
            and stamp(result["freshness"]["expires_at"]) > time.time()
            and result["timeline"]["valid_at"] == expected["display"]["native"])


def api(origin, expected, product="weather"):
    port = int(origin.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.request("GET", "/api/volparossa/" + ("air-quality" if product == "air_quality" else "forecast"),
                           headers={"Accept": "application/json"})
        response = connection.getresponse()
        require(response.status == 200 and response.getheader("Cache-Control") == "no-store"
                and response.getheader("Content-Type").startswith("application/json"))
        raw = response.read(524289)
        require(0 < len(raw) <= 524288)
        check_api(json.loads(raw, object_pairs_hook=pairs), expected, product)
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


def dom_products(client):
    return client.script('''
      const weather=document.querySelector('section[aria-label="VOLPAROSSA forecast"]');
      const aq=document.querySelector('section[aria-label="VOLPAROSSA air quality"]');
      const button=weather?.querySelector('button');
      if(!weather?.querySelector('tbody') || !aq?.querySelector('tbody') || !button || button.disabled
        || weather.querySelector('[role="status"], [role="alert"]') || aq.querySelector('[role="status"], [role="alert"]'))return null;
      const entries=performance.getEntriesByType('resource');
      const common=(area,endpoint)=>({native:[...area.querySelectorAll('tbody tr')].map(r=>r.children[0].textContent.trim()),
        values:[...area.querySelectorAll('tbody tr')].map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent.trim())),
        details:[...area.querySelectorAll('dl dd')].map(c=>c.textContent.trim()),
        headers:[...area.querySelectorAll('thead th')].map(c=>c.textContent.trim()),
        localOnly:entries.every(e=>e.name.startsWith(location.origin+'/')&&!e.name.includes('/api/geo')),
        apiRequests:entries.filter(e=>e.name===location.origin+endpoint).length});
      const source=aq.querySelector('[data-testid="air-quality-source"]');
      const attribution=source?.querySelector('a[href="https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gefs_aero.php"]');
      const license=source?.querySelector('a[href="https://registry.opendata.aws/noaa-gefs/"]');
      const text=source?.textContent.replace(/\\s+/g,' ').trim() || '';
      const changes=text.match(/Processing: (.*?) This modified presentation is not an official NOAA product or endorsement\\./);
      return {weather:{...common(weather,'/api/volparossa/forecast'),
          attribution:!!weather.querySelector('a[href="https://www.ecmwf.int/en/forecasts/datasets/open-data"]'),
          licence:!!weather.querySelector('a[href="https://creativecommons.org/licenses/by/4.0/"]'),
          missing:weather.textContent.includes('Missing does not mean dry, clear or clean air'),
          accumulation:weather.textContent.includes('not an hourly rain rate')&&weather.textContent.includes('Windows may overlap')},
        air_quality:{...common(aq,'/api/volparossa/air-quality'),attribution:attribution?.textContent.trim(),
          license:license?.textContent.trim(),license_url:license?.getAttribute('href'),changes:changes?.[1],
          missing:aq.textContent.includes('Missing values mean not available, not zero or clean air'),
          nativeScope:aq.textContent.includes('not AQI or current observations')&&aq.textContent.includes('no time points are aligned or interpolated'),
          noEndorsement:text.includes('not an official NOAA product or endorsement')}, refreshReady:true};
    ''')


def check_products_dom(value, expected, requests):
    if type(value) is not dict or set(value) != {"weather", "air_quality", "refreshReady"} or value["refreshReady"] is not True:
        return False
    weather, aq = value["weather"], value["air_quality"]
    display = expected["products"]["air_quality"]["display"]
    return (check_dom(weather, expected["products"]["weather"], requests)
            and weather.get("accumulation") is True
            and weather.get("headers") == ["Valid time", "Temperature (°C)", "Wind (m/s)", "Wind from (°)",
                                           "Accumulated precipitation (mm)", "Accumulation window (UTC)"]
            and type(aq) is dict and aq.get("native") == display["native"] and aq.get("values") == display["values"]
            and aq.get("details") == [display["coordinates"], display["model_run"], display["expires_at"]]
            and aq.get("headers") == ["Valid time", "PM2.5 (µg/m³)", "PM10 (µg/m³)"]
            and all(aq.get(key) == display[key] for key in ("attribution", "license", "license_url", "changes"))
            and all(aq.get(key) is True for key in ("missing", "nativeScope", "noEndorsement", "localOnly"))
            and aq.get("apiRequests") == requests)


def observed_products(value):
    result = {}
    for name in ("weather", "air_quality"):
        observed = value[name]
        result[name] = dict(coordinates=observed["details"][0], model_run=observed["details"][1],
            expires_at=observed["details"][2], native=observed["native"], values=observed["values"])
        if name == "air_quality":
            result[name].update({key: observed[key] for key in ("attribution", "license", "license_url", "changes")})
    return result


def wait_products_dom(client, connection, expected, requests):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection.settimeout(min(15, remaining))
        observed = dom_products(client)
        if check_products_dom(observed, expected, requests):
            displays = observed_products(observed)
            hashes = {name: hashlib.sha256(canonical(display)).hexdigest() for name, display in displays.items()}
            require(all(digest == expected["products"][name]["display_sha256"] for name, digest in hashes.items()))
            combined = hashlib.sha256(canonical(displays)).hexdigest()
            require(combined == expected["display_sha256"])
            connection.settimeout(15)
            return combined, hashes
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise TimeoutError("dom_deadline")


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
    v2 = expected["schema"] in (2, 4)
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
        if v2:
            for name, product in expected["products"].items():
                report["products"][name]["checks"]["api_response_sha256"] = api(origin, product, name)
        else:
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
        if v2:
            combined, observed = wait_products_dom(client, connection, expected, 1)
            report["checks"]["initial_dom_display_sha256"] = combined
            for name, digest in observed.items():
                report["products"][name]["checks"].update(initial_dom_display_sha256=digest,
                    initial_dom_matches_cold_publication=True)
        else:
            report["checks"]["initial_dom_display_sha256"] = wait_dom(client, connection, expected, 1)
            report["checks"]["initial_dom_matches_cold_publication"] = True
        report["scope"]["actual_drizzli_ui"] = True
        report["phase"] = "refresh"
        require(client.script('const b=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] button"); if(!b||b.disabled)return false; b.click(); return true;'))
        if v2:
            combined, observed = wait_products_dom(client, connection, expected, 2)
            report["checks"].update(refresh_dom_display_sha256=combined,
                browser_api_requests=4, provider_requests_checked=2, no_external_resources=True)
            for name, digest in observed.items():
                report["products"][name]["checks"].update(refresh_dom_display_sha256=digest,
                    refresh_dom_matches_cold_publication=True, browser_api_requests=2, provider_requests_checked=1,
                    exact_native_times_and_values=True, explicit_missing_capabilities=True,
                    no_external_resources=True, source_attribution=True)
            report["scope"]["separate_native_runs"] = True
        else:
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
    parser.add_argument("--outer-userns", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("bundle_root", "config", "expected", "output"):
        value = getattr(args, name)
        require(value.is_absolute() and value.resolve() == value)
    require(args.output.parent == args.config.parent == args.expected.parent
            and not args.output.is_relative_to(args.bundle_root))
    boundary(args, args.inside)
    config = read_json(args.config, 16384, 0o600)
    raw_expected = raw_file(args.expected, 384 * 1024, 0o400)
    expected = validate_expected(json.loads(raw_expected, object_pairs_hook=pairs), config)
    require(len(raw_expected) <= (384 if expected["schema"] in (2, 4) else 192) * 1024)
    built, browser, metadata, source = validate_bundle(args.bundle_root, args.bundle_manifest_sha256, expected["schema"])
    require(config["core"]["scratchParent"] == str(args.output / "scratch"))
    binary = Path(config["core"]["executable"])
    verify_core_binary(binary, expected["core_sha256"], args)
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
            "--ro-bind", str(binary), str(binary),
            "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--", sys.executable, "-B",
            str(Path(__file__).resolve()), *sys.argv[1:], "--inside", "--outer-userns", os.readlink("/proc/self/ns/user")]
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
