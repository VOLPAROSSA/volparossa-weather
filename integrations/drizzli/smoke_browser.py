#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual Drizz.li hydration with synthetic data, in a disposable loopback-only sandbox.

No core, weather origin, host profile or host network mutation is used. Reuses the
reviewed Browser runtime validator, Marionette framing and isolated-home helper.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def browser_root_argument(arguments, default):
    """Only explicit operator configuration overrides the normal sibling layout."""
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--browser-root")
    selected, _ = parser.parse_known_args(arguments)
    if selected.browser_root is None:
        return default
    root = Path(selected.browser_root)
    if (str(root) != selected.browser_root or not root.is_absolute()
            or root.resolve(strict=True) != root or not root.is_dir()):
        raise ValueError("browser_root_invalid")
    for name in ("smoke_compute_model.py", "smoke_privacy.py", "stage_firefox.py"):
        helper = root / "scripts" / name
        if helper.resolve(strict=True) != helper or not helper.is_file():
            raise ValueError("browser_root_invalid")
    return root


try:
    BROWSER_ROOT = browser_root_argument(sys.argv[1:], ROOT.parent / "volparossa-browser")
except (OSError, ValueError, argparse.ArgumentError):
    print("invalid explicit browser helper root", file=sys.stderr)
    raise SystemExit(1) from None
sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
from smoke_compute_model import validate_stage
from smoke_privacy import Marionette
from stage_firefox import isolated_browser_home, validate_isolated_browser_home

NODE_SHA256 = "bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12"
PROFILE_DIRS = ("profile", "config", "cache", "runtime", "tmp", "appdata")
MAX_STARTUP_STDERR = 2048


class StartupStderr:
    """Bounded about:blank diagnostics, never page/navigation logging.

    Continue draining after the capture freezes so a verbose child cannot
    deadlock on stderr. Only a failed startup exports the captured prefix.
    """
    def __init__(self, stream):
        self.stream = stream
        self.data = bytearray()
        self.observed = 0
        self.capture = True
        self.eof = False
        self.failed = False
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._drain, name="browser-startup-stderr", daemon=True)
        os.set_blocking(stream.fileno(), False)
        self.thread.start()

    def _drain(self):
        stop_deadline = None
        try:
            while True:
                if self.stopping.is_set() and stop_deadline is None:
                    stop_deadline = time.monotonic() + 0.5
                if stop_deadline is not None and time.monotonic() >= stop_deadline:
                    return
                readable, _, _ = select.select([self.stream], [], [], 0.05)
                if not readable:
                    if stop_deadline is not None:
                        return
                    continue
                try:
                    raw = os.read(self.stream.fileno(), 4096)
                except BlockingIOError:
                    continue
                if not raw:
                    self.eof = True
                    return
                with self.lock:
                    if self.capture:
                        self.observed += len(raw)
                        self.data.extend(raw[:max(0, MAX_STARTUP_STDERR - len(self.data))])
        except (OSError, ValueError):
            self.failed = True

    def freeze(self):
        # Called before WebDriver creates a session, well before any navigation.
        with self.lock:
            self.capture = False

    def finish(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        finished = not self.thread.is_alive()
        if finished:
            self.stream.close()
        return finished and self.eof and not self.failed

    def diagnostic(self, exit_code, exit_code_before_cleanup=None):
        with self.lock:
            raw = bytes(self.data)
            observed = self.observed
        return dict(scope="startup-about-blank-before-webdriver-navigation", exit_code=exit_code,
            exit_code_before_cleanup=exit_code_before_cleanup,
            observed_elapsed_ms=int((time.monotonic() - self.started) * 1000),
            encoding="base64", stderr_prefix=base64.b64encode(raw).decode("ascii"),
            captured_bytes=len(raw), observed_bytes=observed, limit_bytes=MAX_STARTUP_STDERR,
            truncated=observed > len(raw), prefix_sha256=hashlib.sha256(raw).hexdigest(),
            stream_eof=self.eof, read_failed=self.failed)


def require(condition):
    if not condition:
        raise ValueError("drizzli_browser_smoke_failed")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def stop(process):
    if process is None:
        return True
    try:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        return process.poll() is not None
    except (OSError, subprocess.SubprocessError):
        return False


def clean_environment():
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1"}


def work_identity(work):
    require(work.resolve() == work and work.parent == ROOT / "build")
    info = work.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
    return info.st_dev, info.st_ino


def remove_private(work, expected):
    try:
        require(work_identity(work) == expected)
    except (OSError, ValueError):
        return False
    removed = True
    for name in PROFILE_DIRS:
        path = work / name
        try:
            if path.exists() or path.is_symlink():
                info = path.lstat()
                require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and info.st_uid == os.getuid())
                shutil.rmtree(path)
        except (OSError, ValueError):
            removed = False
    return removed and all(not (work / name).exists() for name in PROFILE_DIRS)


def save_report(work, report):
    fd = os.open(work / "report.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(report, output, indent=2); output.write("\n")


def validate_client_stage(stage):
    metadata = json.loads((HERE / "upstream.json").read_text())
    require(digest(HERE / "upstream.patch") == metadata["upstream_patch_sha256"])
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(stage), *args],
            text=True, timeout=20, env=clean_environment())
    require(git("rev-parse", "HEAD").strip() == metadata["commit"])
    require(git("rev-parse", "HEAD^{tree}").strip() == metadata["tree"])
    for name, key in (("LICENSE", "license_sha256"), ("package-lock.json", "package_lock_sha256")):
        require(digest(stage / name) == metadata[key])
    patch = (HERE / "upstream.patch").read_text()
    patched = [line[6:] for line in patch.splitlines() if line.startswith("+++ b/")]
    require(git("diff", "--no-ext-diff", "--binary", "--", *patched) == patch)
    changed = set(git("diff", "--name-only").splitlines())
    require(changed == set(patched) | {"project.inlang/settings.json"})
    copied = {}
    for path in sorted((HERE / "overlay").rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(HERE / "overlay"))
            require(not path.is_symlink() and digest(stage / relative) == digest(path))
            copied[relative] = digest(path)
    for relative, expected in metadata["weather_modules"].items():
        require(digest(ROOT / relative) == expected)
        require(digest(stage / "src/lib/services/volparossa" / Path(relative).name) == expected)
    built = stage / "build"
    entries = sorted(built.rglob("*"))
    require(len(entries) <= 1024 and (built / "index.html").is_file())
    hashes, total = {}, 0
    for path in [built, *entries]:
        info = path.lstat()
        require(not path.is_symlink() and info.st_uid == os.getuid() and not info.st_mode & 0o022)
        if path.is_dir():
            continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 8 * 1024 * 1024)
        total += info.st_size
        require(total <= 32 * 1024 * 1024)
        hashes[str(path.relative_to(built))] = digest(path)
    artifact = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(upstream=metadata["commit"], tree=metadata["tree"], patch_sha256=digest(HERE / "upstream.patch"),
        overlay_sha256=copied, weather_modules=metadata["weather_modules"],
        bridge_modules={name: digest(ROOT / name) for name in
            ("src/provider-http.mjs", "src/provider-core.mjs", "src/core-cache.mjs", "src/air-quality-core.mjs")},
        fixture_modules={name: digest(ROOT / name) for name in
            ("tests/fixtures.mjs", "src/ecmwf.mjs", "tests/air-quality-fixtures.mjs")},
        built_tree_sha256=artifact, built_files=len(hashes), built_bytes=total,
        browser_helpers={name: digest(BROWSER_ROOT / name) for name in
            ("scripts/smoke_compute_model.py", "scripts/smoke_privacy.py", "scripts/stage_firefox.py")},
        browser_revision=subprocess.check_output(["git", "-C", str(BROWSER_ROOT), "rev-parse", "HEAD"],
            text=True, timeout=10, env=clean_environment()).strip(),
        driver_sha256=digest(Path(__file__)), fixture_sha256=digest(HERE / "browser-fixture.mjs"))


def read_line(process, timeout=10):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        if not select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))[0]:
            break
        char = os.read(process.stdout.fileno(), 1)
        require(bool(char) and len(data) < 4096)
        if char == b"\n":
            return json.loads(data)
        data.extend(char)
    raise TimeoutError("fixture_reply_timeout")


def fixture_command(process, mode):
    require(mode in ("status", "valid", "missing", "stale", "unavailable", "short-lived", "stop",
                     "aq-valid", "aq-unavailable", "aq-stale", "aq-short-lived"))
    process.stdin.write((mode + "\n").encode())
    process.stdin.flush()
    return read_line(process)


def fixture_arguments(node, stage, work, precipitation=False, air_quality=False):
    return [str(node), "--max-old-space-size=256", str(HERE / "browser-fixture.mjs"),
            str(stage / "build"), str(work), *(["--precipitation"] if precipitation else []),
            *(["--air-quality"] if air_quality else [])]


def check_fixture_lifecycle(node, stage, work, environment, outcomes, precipitation=False, air_quality=False):
    for operation in ("stop", "eof", "signal"):
        process = None
        item = dict(ready=False, requested=False, normal_exit=False, exit_code=None, terminated=False)
        outcomes[operation] = item
        try:
            process = subprocess.Popen(fixture_arguments(node, stage, work, precipitation, air_quality), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
            require(read_line(process)["ready"] is True)
            item["ready"] = True
            if operation == "stop":
                require(fixture_command(process, "stop")["stopped"] is True)
            elif operation == "eof":
                process.stdin.close()
            else:
                process.send_signal(signal.SIGTERM)
            item["requested"] = True
            require(process.wait(timeout=10) == 0)
            item["normal_exit"] = True
        finally:
            terminated = stop(process)
            item["terminated"] = terminated
            item["exit_code"] = process.poll() if process is not None else None
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    try:
                        stream.close()
                    except OSError:
                        pass
            require(terminated)


def wait_for(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise TimeoutError("browser_condition_timeout")


def refresh_idle(client):
    return client.script('''
      return document.querySelector('section[aria-label="VOLPAROSSA forecast"] button')?.disabled === false
        && !document.querySelector('section[aria-label="VOLPAROSSA forecast"] [role="status"]')
        && !document.querySelector('section[aria-label="VOLPAROSSA air quality"] [role="status"]');
    ''') is True


def precipitation_rows(valid_at, missing=False):
    """Independent expected display for the fixed synthetic 3/9/24-hour query."""
    require(type(valid_at) is list and len(valid_at) == 3 and all(type(value) is str for value in valid_at))
    parsed = [datetime.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in valid_at]
    run = parsed[0] - datetime.timedelta(hours=3)
    stamp = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    require(run.tzinfo == datetime.timezone.utc
            and valid_at == [stamp(run + datetime.timedelta(hours=step)) for step in (3, 9, 24)])
    rows = []
    for i, (start, amount) in enumerate(zip((0, 0, 6), ("Not available", "0", "0.01"))):
        values = ["Not available"] * 3 if missing and i == 0 else ["10.0", "5.0", "216.9"]
        rows.append([*values, amount, f"{stamp(run + datetime.timedelta(hours=start))} → {valid_at[i]}"])
    return rows


def precipitation_dom(client):
    return client.script('''
      const area=document.querySelector('section[aria-label="VOLPAROSSA forecast"]');
      if (!area) return null;
      const rows=[...area.querySelectorAll('tbody tr')];
      const text=area.textContent;
      const missing=area.querySelector('[data-testid="unsupported-capabilities"]')?.textContent || '';
      const explanation=area.querySelector('[data-testid="precipitation-accumulation"]')?.textContent || '';
      return {native: rows.map(r=>r.children[0].textContent.trim()),
        values: rows.map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent.trim())),
        headings: [...area.querySelectorAll('thead th')].map(c=>c.textContent.trim()),
        explicitWindows: explanation.includes('not an hourly rain rate') && explanation.includes('Windows may overlap'),
        noRate: !/mm\\s*\\/\\s*h\\b/i.test(text),
        airQualitySeparate: missing.includes('Air quality has its own separately configured panel') && !missing.includes('Precipitation'),
        notLoading: area.querySelector('button')?.disabled === false && !area.querySelector('[role="status"]'),
        completedRequests: performance.getEntriesByType('resource').filter(e=>e.name===location.origin+'/api/volparossa/forecast' && e.responseEnd>0).length,
        localOnly: performance.getEntriesByType('resource').every(e=>e.name.startsWith(location.origin+'/') && !e.name.includes('/api/geo'))};
    ''')


def precipitation_dom_matches(value, valid_at, minimum_requests, missing=False):
    return (type(value) is dict and value.get("native") == valid_at
            and value.get("values") == precipitation_rows(valid_at, missing)
            and value.get("headings") == ["Valid time", "Temperature (°C)", "Wind (m/s)", "Wind from (°)",
                                            "Accumulated precipitation (mm)", "Accumulation window (UTC)"]
            and all(value.get(key) is True for key in
                    ("explicitWindows", "noRate", "airQualitySeparate", "notLoading", "localOnly"))
            and type(value.get("completedRequests")) is int and value["completedRequests"] >= minimum_requests)


def wait_precipitation(client, valid_at, minimum_requests, missing=False):
    observed = None
    def accepted():
        nonlocal observed
        observed = precipitation_dom(client)
        return precipitation_dom_matches(observed, valid_at, minimum_requests, missing)
    wait_for(accepted)
    # Hash the actual observed five-cell display, not a generated expected table.
    return hashlib.sha256(json.dumps({"native": observed["native"], "values": observed["values"]},
                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def air_quality_dom(client):
    return client.script('''
      const area=document.querySelector('section[aria-label="VOLPAROSSA air quality"]');
      if (!area) return null;
      const rows=[...area.querySelectorAll('tbody tr')], text=area.textContent;
      return {native: rows.map(r=>r.children[0].textContent.trim()),
        values: rows.map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent.trim())),
        headings: [...area.querySelectorAll('thead th')].map(c=>c.textContent.trim()),
        noObservation: text.includes('not AQI or current observations'),
        noAqi: text.includes('not AQI'),
        source: text.includes('NOAA/NWS GEFS-Aerosols') && text.includes('gefs-aerosols'),
        license: !!area.querySelector('a[href="https://registry.opendata.aws/noaa-gefs/"]'),
        notLoading: !area.querySelector('[role="status"]') &&
          document.querySelector('section[aria-label="VOLPAROSSA forecast"] button')?.disabled === false,
        completedRequests: performance.getEntriesByType('resource').filter(e=>e.name===location.origin+'/api/volparossa/air-quality' && e.responseEnd>0).length,
        localOnly: performance.getEntriesByType('resource').every(e=>e.name.startsWith(location.origin+'/') && !e.name.includes('/api/geo'))};
    ''')


def air_quality_dom_matches(value, valid_at, minimum_requests):
    return (type(value) is dict and value.get('native') == valid_at
            and value.get('values') == [['Not available', '11.5959'], ['0', 'Not available'], ['5.53071', '0']]
            and value.get('headings') == ['Valid time', 'PM2.5 (µg/m³)', 'PM10 (µg/m³)']
            and all(value.get(key) is True for key in
                    ('noObservation', 'noAqi', 'source', 'license', 'notLoading', 'localOnly'))
            and type(value.get('completedRequests')) is int and value['completedRequests'] >= minimum_requests)


def wait_air_quality(client, valid_at, minimum_requests):
    observed = None
    def accepted():
        nonlocal observed
        observed = air_quality_dom(client)
        return air_quality_dom_matches(observed, valid_at, minimum_requests)
    wait_for(accepted)
    return hashlib.sha256(json.dumps({'native': observed['native'], 'values': observed['values']},
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inside(args, stage, work, node, browser_stage, metadata, source):
    require(args.host_netns and os.readlink("/proc/self/ns/net") != args.host_netns)
    require(all(os.statvfs(path).f_flag & os.ST_RDONLY for path in (Path("/"), ROOT, stage, browser_stage)))
    require(not os.statvfs(work).f_flag & os.ST_RDONLY)
    require(stat.S_IMODE(work.stat().st_mode) == 0o700 and work.stat().st_uid == os.getuid())
    validate_isolated_browser_home(work)
    links = json.loads(subprocess.check_output(["/usr/bin/ip", "-j", "link", "show"], text=True))
    require([item["ifname"] for item in links] == ["lo"] and "UP" in links[0]["flags"])
    for name in PROFILE_DIRS[:-1]:
        (work / name).mkdir(mode=0o700)
    with (work / "profile/prefs.js").open("x") as prefs:
        prefs.write('user_pref("remote.prefs.recommended", false);\n')
    identity = work_identity(work)
    environment = clean_environment()
    environment.update(MOZ_NO_REMOTE="1", MOZ_CRASHREPORTER_DISABLE="1",
        XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
        XDG_RUNTIME_DIR=str(work / "runtime"), TMPDIR=str(work / "tmp"),
        VOLPAROSSA_TEST_HOST_NETNS=args.host_netns)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS"):
        environment.pop(name, None)
    report = dict(schema=1, passed=False, phase="fixture_start",
        scope=dict(actual_drizzli_ui=False, synthetic_weather=True, actual_http_bridge=False,
                   core_executed=False, overlay_proven=False, upstream_origin_proven=False),
        isolation=dict(host_read_only=True, separate_user_netns=True, interfaces=["lo"],
                       fresh_private_profile=True),
        runtime=dict(version=metadata["version"], source_stamp=metadata["source_stamp"],
                     sha256=metadata["runtime_sha256"], node_sha256=NODE_SHA256),
        source=source,
        checks={}, cleanup={})
    if args.precipitation:
        report["scenario"] = "precipitation"
    if args.air_quality:
        report['air_quality_scenario'] = True
        report['scope']['synthetic_air_quality'] = True
    fixture = browser = client = connection = startup_stderr = None
    normal_browser_stop = normal_fixture_stop = False
    try:
        report["phase"] = "fixture_lifecycle"
        report["checks"]["fixture_lifecycle"] = {}
        check_fixture_lifecycle(node, stage, work, environment, report["checks"]["fixture_lifecycle"], args.precipitation, args.air_quality)
        if args.fixture_only:
            normal_browser_stop = normal_fixture_stop = True
            report["passed"] = True
            report["phase"] = "fixture_lifecycle_complete"
            return
        report["phase"] = "fixture_start"
        fixture = subprocess.Popen(fixture_arguments(node, stage, work, args.precipitation, args.air_quality), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        ready = read_line(fixture)
        require(ready["ready"] is True and ready["synthetic"] is True and ready["core_executed"] is False)
        require((ready.get("scenario") == "precipitation") == args.precipitation)
        require((ready.get('air_quality') is True) == args.air_quality)
        if args.air_quality:
            require(ready['air_quality_valid_at'] != ready['valid_at'])
        origin = ready["origin"]
        require(origin.startswith("http://127.0.0.1:") and origin.rsplit(":", 1)[1].isdigit())
        report["phase"] = "browser_start"
        browser = subprocess.Popen([str(browser_stage / metadata["executable"]), "--headless", "--no-remote",
            "--new-instance", "--profile", str(work / "profile"), "--marionette",
            "--remote-allow-system-access", "about:blank"], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        startup_stderr = StartupStderr(browser.stderr)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            require(browser.poll() is None)
            try:
                connection = socket.create_connection(("127.0.0.1", 2828), timeout=1)
                connection.settimeout(15)
                client = Marionette(connection)
                break
            except (ConnectionRefusedError, TimeoutError):
                if connection:
                    connection.close()
                    connection = None
                time.sleep(0.1)
        require(client is not None)
        startup_stderr.freeze()
        report["phase"] = "browser_session"
        client.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})
        client.command("Marionette:SetContext", {"value": "chrome"})
        require(Path(client.script('return Services.dirsvc.get("GreD", Ci.nsIFile).path;')).resolve() == browser_stage)
        client.command("Marionette:SetContext", {"value": "content"})
        client.command("WebDriver:SetTimeouts", {"pageLoad": 15000, "script": 10000})

        def navigate(path):
            require(path in ("/en/weather/week/", "/en/weather/week/amsterdam/", "/en/weather/maps/"))
            client.command("WebDriver:Navigate", {"url": origin + path})

        def table():
            return client.script('return document.querySelectorAll("section[aria-label=\\"VOLPAROSSA forecast\\"] tbody tr").length === 3;')

        def click_refresh(mode):
            wait_for(lambda: refresh_idle(client))
            before = fixture_command(fixture, mode)
            require(client.script('const b=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] button"); if(!b||b.disabled)return false; b.click(); return true;'))
            wait_for(lambda: fixture_command(fixture, "status")["calls"] == before['calls'] + 1)
            wait_for(lambda: refresh_idle(client))
            after = fixture_command(fixture, 'status')
            require(after['calls'] == before['calls'] + 1)
            if args.air_quality:
                require(after['airQualityCalls'] == before['airQualityCalls'] + 1)

        report["phase"] = "hydration"
        navigate("/en/weather/week/")
        wait_for(table)
        require(fixture_command(fixture, "status")["calls"] == 1)
        initial = client.script('''
          const area=document.querySelector('section[aria-label="VOLPAROSSA forecast"]');
          const rows=[...area.querySelectorAll('tbody tr')];
          return {native: rows.map(r=>r.children[0].textContent),
            values: rows.map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent)),
            coords: area.textContent.includes('52.52° latitude, 13.41° longitude'),
            unavailable: area.textContent.includes('Missing does not mean dry, clear or clean air'),
            source: !!area.querySelector('a[href="https://www.ecmwf.int/en/forecasts/datasets/open-data"]'),
            licence: !!area.querySelector('a[href="https://creativecommons.org/licenses/by/4.0/"]'),
            footer: document.querySelector('footer').textContent.includes('Original Drizz.li application by Open-Meteo'),
            noCityLinks: !document.querySelector('footer a[href*="/weather/week/berlin"]'),
            localOnly: performance.getEntriesByType('resource').every(e=>e.name.startsWith(location.origin+'/') && !e.name.includes('/api/geo'))};
        ''')
        require(all(initial[key] for key in ("coords", "unavailable", "source", "licence", "footer", "noCityLinks", "localOnly")))
        require(initial["native"] == ready["valid_at"])
        require(all(row[:2] == ["10.0", "5.0"] for row in initial["values"]))
        if args.precipitation:
            report["checks"]["precipitation_initial_dom_sha256"] = wait_precipitation(client, ready["valid_at"], 1)
            report["checks"].update(precipitation_five_cells=True, precipitation_native_windows=True,
                precipitation_missing_zero_small_amount=True, precipitation_no_hourly_rate=True,
                air_quality_is_separate_product=True)
        report["checks"].update(hydration=True, native_times=True, temperature_wind=True,
            explicit_missing_capabilities=True, attribution=True, fixed_location=True, no_external_resources=True)
        report["scope"]["actual_drizzli_ui"] = True
        if args.air_quality:
            report['checks']['air_quality_initial_dom_sha256'] = wait_air_quality(client, ready['air_quality_valid_at'], 1)
            report['checks'].update(air_quality_native_times=True, air_quality_missing_zero_concentrations=True,
                air_quality_not_aqi_or_observations=True)
        report["phase"] = "refresh"
        click_refresh("valid"); wait_for(table)
        if args.precipitation:
            report["checks"]["precipitation_refresh_dom_sha256"] = wait_precipitation(client, ready["valid_at"], 2)
            require(report["checks"]["precipitation_refresh_dom_sha256"] == report["checks"]["precipitation_initial_dom_sha256"])
        report["checks"]["actual_refresh"] = True
        if args.air_quality:
            report['checks']['air_quality_refresh_dom_sha256'] = wait_air_quality(client, ready['air_quality_valid_at'], 2)
            require(report['checks']['air_quality_refresh_dom_sha256'] == report['checks']['air_quality_initial_dom_sha256'])
        report["phase"] = "missing_values"
        click_refresh("missing"); wait_for(table)
        if args.precipitation:
            report["checks"]["precipitation_missing_dom_sha256"] = wait_precipitation(client, ready["valid_at"], 3, missing=True)
        else:
            require(client.script('return [...document.querySelectorAll("section[aria-label=\\"VOLPAROSSA forecast\\"] tbody tr:first-child td")].every(c=>c.textContent==="Not available");'))
        report["checks"]["missing_values_not_zero"] = True
        report["phase"] = "unavailable"
        click_refresh("unavailable")
        wait_for(lambda: client.script('const a=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"]"); return !!a.querySelector("[role=alert]") && !a.querySelector("tbody");'))
        require(client.script('return document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] [role=alert]").textContent.includes("No other weather service was contacted");'))
        report["checks"]["unavailable_closed"] = True
        if args.air_quality:
            wait_air_quality(client, ready['air_quality_valid_at'], 4)
            report['checks']['weather_failure_preserves_air_quality'] = True
        report["phase"] = "stale"
        click_refresh("stale")
        wait_for(lambda: client.script('const a=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"]"); return !!a.querySelector("[role=alert]") && !a.querySelector("tbody");'))
        report["checks"]["stale_response_closed"] = True
        report["phase"] = "live_expiry"
        click_refresh("short-lived"); wait_for(table)
        wait_for(lambda: client.script('const a=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"]"); return a.querySelector("[role=alert]")?.textContent.includes("has expired") && !a.querySelector("tbody");'), timeout=6)
        report["checks"]["display_removed_at_expiry"] = True
        if args.air_quality:
            wait_air_quality(client, ready['air_quality_valid_at'], 6)
            report['checks']['weather_expiry_preserves_air_quality'] = True
            click_refresh('valid')
            wait_air_quality(client, ready['air_quality_valid_at'], 7)
            for mode in ('aq-unavailable', 'aq-stale'):
                report['phase'] = mode
                click_refresh(mode)
                wait_for(lambda: client.script('const a=document.querySelector("section[aria-label=\\"VOLPAROSSA air quality\\"]"); return !!a?.querySelector("[role=alert]") && !a.querySelector("tbody") && document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] button")?.disabled === false;'))
                require(client.script('return document.querySelector("section[aria-label=\\"VOLPAROSSA air quality\\"] [role=alert]").textContent.includes("No other air-quality service was contacted");'))
                require(table())
                report['checks'][mode.replace('-', '_') + '_weather_preserved'] = True
            report['phase'] = 'air_quality_expiry'
            click_refresh('aq-short-lived')
            wait_air_quality(client, ready['air_quality_valid_at'], 10)
            wait_for(lambda: client.script('const a=document.querySelector("section[aria-label=\\"VOLPAROSSA air quality\\"]"); return a?.querySelector("[role=alert]")?.textContent.includes("has expired") && !a.querySelector("tbody");'), timeout=6)
            require(table())
            report['checks']['air_quality_expiry_preserves_weather'] = True
            fixture_command(fixture, 'aq-valid')
        report["phase"] = "located_route"
        fixture_command(fixture, "valid")
        navigate("/en/weather/week/amsterdam/"); wait_for(table)
        wait_for(lambda: refresh_idle(client))
        if args.air_quality:
            wait_air_quality(client, ready['air_quality_valid_at'], 1)
        require(client.script('return location.pathname === "/en/weather/week/" && !document.querySelector("h1").textContent.includes("Amsterdam");'))
        report["checks"]["located_route_redirects"] = True
        report["phase"] = "unsupported_maps"
        before = fixture_command(fixture, "status")
        navigate("/en/weather/maps/")
        wait_for(lambda: client.script('return document.body.textContent.includes("No external weather service or map is loaded");'))
        require(client.script('return !document.querySelector("iframe") && !document.querySelector("tbody");'))
        after = fixture_command(fixture, 'status')
        require(after['calls'] == before['calls'] and after['airQualityCalls'] == before['airQualityCalls'])
        report["checks"]["unsupported_maps_not_mounted"] = True
        report["phase"] = "shutdown"
        client.command("Marionette:Quit", {"flags": ["eAttemptQuit"]})
        normal_browser_stop = browser.wait(timeout=15) == 0
        stopped = fixture_command(fixture, "stop")
        normal_fixture_stop = stopped["stopped"] is True and fixture.wait(timeout=10) == 0
        report["checks"]["provider_requests"] = stopped["calls"]
        if args.air_quality:
            report['checks']['air_quality_provider_requests'] = stopped['airQualityCalls']
        require(normal_browser_stop and normal_fixture_stop)
        report["phase"] = "complete"
        report["passed"] = True
    finally:
        report["scope"]["actual_http_bridge"] = any(item["ready"] for item in
            report["checks"].get("fixture_lifecycle", {}).values())
        try:
            if connection:
                connection.close()
        except OSError:
            pass
        browser_exit_before_cleanup = browser.poll() if browser is not None else None
        browser_stopped, fixture_stopped = stop(browser), stop(fixture)
        stderr_drained = True
        if startup_stderr is not None:
            stderr_drained = startup_stderr.finish()
        elif browser is not None and browser.stderr is not None:
            # Preserve cleanup even if reader construction failed after Popen.
            browser.stderr.close()
            stderr_drained = False
        if startup_stderr is not None and report["phase"] in ("browser_start", "browser_session"):
            report["startup_diagnostics"] = startup_stderr.diagnostic(browser.poll(), browser_exit_before_cleanup)
        report["browser_process_exit_code"] = browser.poll() if browser is not None else None
        if fixture is not None:
            for stream in (fixture.stdin, fixture.stdout):
                try:
                    stream.close()
                except OSError:
                    pass
        private_removed = remove_private(work, identity) if browser_stopped and fixture_stopped else False
        report["cleanup"] = dict(browser_exited=browser_stopped, fixture_exited=fixture_stopped,
            private_profile_removed=private_removed,
            normal_browser_stop=normal_browser_stop, normal_fixture_stop=normal_fixture_stop,
            startup_stderr_drained=stderr_drained)
        report["passed"] = report["passed"] and all(report["cleanup"].values())
        save_report(work, report)


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "browser-stage", "node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--browser-root", type=Path, help="explicit canonical Browser checkout for helper imports")
    parser.add_argument("--precipitation", action="store_true", help="separate synthetic accumulated-precipitation scenario")
    parser.add_argument('--air-quality', action='store_true', help='separate synthetic native NOAA particulate forecast scenario')
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fixture-only", action="store_true", help="test only child stop/EOF/signal, without Firefox")
    parser.add_argument("--host-netns", help=argparse.SUPPRESS)
    args = parser.parse_args()
    stage, work, node, browser_stage = (path.resolve(strict=flag) for path, flag in
        ((args.stage, True), (args.output, False), (args.node, True), (args.browser_stage, True)))
    require(stage.parent == ROOT / "build" and work.parent == ROOT / "build" and stage != work)
    require(browser_stage.is_relative_to(BROWSER_ROOT / "build") and digest(node) == NODE_SHA256)
    metadata = validate_stage(browser_stage)
    source = validate_client_stage(stage)
    if args.inside:
        inside(args, stage, work, node, browser_stage, metadata, source)
        return
    available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))) * 1024
    require(available >= 3 * 1024 * 1024 * 1024)
    require(not work.exists() and not work.is_symlink())
    work.mkdir(mode=0o700)
    identity = work_identity(work)
    host_netns = os.readlink("/proc/self/ns/net")
    wrapper = None
    completed = False
    try:
        home_mounts = isolated_browser_home(work)
        command = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user", "--unshare-net",
            "--unshare-pid", "--ro-bind", "/", "/", *home_mounts, "--bind", str(work), str(work),
            "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--", sys.executable, "-B",
            str(Path(__file__).resolve()), *sys.argv[1:], "--inside", "--host-netns", host_netns]
        wrapper = subprocess.Popen(command, env=clean_environment(), start_new_session=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                completed = wrapper.wait(timeout=1) == 0
                break
            except subprocess.TimeoutExpired:
                available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                     if line.startswith("MemAvailable:"))) * 1024
                require(available >= 2 * 1024 * 1024 * 1024)
        require(completed)
    finally:
        stopped = stop(wrapper)
        removed = remove_private(work, identity) if stopped else False
        report_path = work / "report.json"
        report = dict(schema=1, passed=False, phase="wrapper_failed", source=source,
            scope=dict(actual_drizzli_ui=False, synthetic_weather=True, actual_http_bridge=False,
                       core_executed=False, overlay_proven=False, upstream_origin_proven=False))
        if args.precipitation:
            report["scenario"] = "precipitation"
        if args.air_quality:
            report['air_quality_scenario'] = True
            report['scope']['synthetic_air_quality'] = True
        if report_path.exists():
            try:
                require(not report_path.is_symlink() and report_path.stat().st_size <= 16384)
                report = json.loads(report_path.read_text())
            except (OSError, ValueError):
                pass
        report["outer_cleanup"] = dict(namespace_wrapper_exited=stopped,
            private_profile_removed=removed, host_netns_unchanged=os.readlink("/proc/self/ns/net") == host_netns)
        report["wrapper_outcome"] = "completed" if completed else "failed_or_timed_out"
        report["passed"] = completed and report["passed"] and all(report["outer_cleanup"].values())
        save_report(work, report)
    require(report["passed"])
    print(json.dumps({"passed": True, "report": str(work / "report.json"), "synthetic_weather": True,
                      "actual_ui": not args.fixture_only, "overlay_proven": False}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, TimeoutError, RuntimeError,
            subprocess.SubprocessError, KeyboardInterrupt):
        print("isolated Drizz.li browser smoke failed; inspect its closed report if created", file=sys.stderr)
        raise SystemExit(1) from None
