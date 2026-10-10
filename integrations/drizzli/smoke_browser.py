#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Actual Drizz.li hydration with synthetic data, in a disposable loopback-only sandbox.

No core, weather origin, host profile or host network mutation is used. Reuses the
reviewed Browser runtime validator, Marionette framing and isolated-home helper.
"""
import argparse
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
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BROWSER_ROOT = ROOT.parent / "volparossa-browser"
sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
from smoke_compute_model import validate_stage
from smoke_privacy import Marionette
from stage_firefox import isolated_browser_home, validate_isolated_browser_home

NODE_SHA256 = "bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12"
PROFILE_DIRS = ("profile", "config", "cache", "runtime", "tmp", "appdata")


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
    require(mode in ("status", "valid", "missing", "stale", "unavailable", "short-lived", "stop"))
    process.stdin.write((mode + "\n").encode())
    process.stdin.flush()
    return read_line(process)


def check_fixture_lifecycle(node, stage, work, environment, outcomes):
    for operation in ("stop", "eof", "signal"):
        process = None
        item = dict(ready=False, requested=False, normal_exit=False, exit_code=None, terminated=False)
        outcomes[operation] = item
        try:
            process = subprocess.Popen([str(node), "--max-old-space-size=256", str(HERE / "browser-fixture.mjs"),
                str(stage / "build"), str(work)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
    fixture = browser = client = connection = None
    normal_browser_stop = normal_fixture_stop = False
    try:
        report["phase"] = "fixture_lifecycle"
        report["checks"]["fixture_lifecycle"] = {}
        check_fixture_lifecycle(node, stage, work, environment, report["checks"]["fixture_lifecycle"])
        if args.fixture_only:
            normal_browser_stop = normal_fixture_stop = True
            report["passed"] = True
            report["phase"] = "fixture_lifecycle_complete"
            return
        report["phase"] = "fixture_start"
        fixture = subprocess.Popen([str(node), "--max-old-space-size=256", str(HERE / "browser-fixture.mjs"),
            str(stage / "build"), str(work)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        ready = read_line(fixture)
        require(ready["ready"] is True and ready["synthetic"] is True and ready["core_executed"] is False)
        origin = ready["origin"]
        require(origin.startswith("http://127.0.0.1:") and origin.rsplit(":", 1)[1].isdigit())
        report["phase"] = "browser_start"
        browser = subprocess.Popen([str(browser_stage / metadata["executable"]), "--headless", "--no-remote",
            "--new-instance", "--profile", str(work / "profile"), "--marionette",
            "--remote-allow-system-access", "about:blank"], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
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
            before = fixture_command(fixture, mode)["calls"]
            require(client.script('const b=document.querySelector("section[aria-label=\\"VOLPAROSSA forecast\\"] button"); if(!b||b.disabled)return false; b.click(); return true;'))
            wait_for(lambda: fixture_command(fixture, "status")["calls"] == before + 1)

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
        report["checks"].update(hydration=True, native_times=True, temperature_wind=True,
            explicit_missing_capabilities=True, attribution=True, fixed_location=True, no_external_resources=True)
        report["scope"]["actual_drizzli_ui"] = True
        report["phase"] = "refresh"
        click_refresh("valid"); wait_for(table)
        report["checks"]["actual_refresh"] = True
        report["phase"] = "missing_values"
        click_refresh("missing"); wait_for(table)
        require(client.script('return [...document.querySelectorAll("tbody tr:first-child td")].every(c=>c.textContent==="Not available");'))
        report["checks"]["missing_values_not_zero"] = True
        report["phase"] = "unavailable"
        click_refresh("unavailable")
        wait_for(lambda: client.script('return !!document.querySelector("[role=alert]") && !document.querySelector("tbody");'))
        require(client.script('return document.querySelector("[role=alert]").textContent.includes("No other weather service was contacted");'))
        report["checks"]["unavailable_closed"] = True
        report["phase"] = "stale"
        click_refresh("stale")
        wait_for(lambda: client.script('return !!document.querySelector("[role=alert]") && !document.querySelector("tbody");'))
        report["checks"]["stale_response_closed"] = True
        report["phase"] = "live_expiry"
        click_refresh("short-lived"); wait_for(table)
        wait_for(lambda: client.script('return document.querySelector("[role=alert]")?.textContent.includes("has expired") && !document.querySelector("tbody");'), timeout=6)
        report["checks"]["display_removed_at_expiry"] = True
        report["phase"] = "located_route"
        fixture_command(fixture, "valid")
        navigate("/en/weather/week/amsterdam/"); wait_for(table)
        require(client.script('return location.pathname === "/en/weather/week/" && !document.querySelector("h1").textContent.includes("Amsterdam");'))
        report["checks"]["located_route_redirects"] = True
        report["phase"] = "unsupported_maps"
        before = fixture_command(fixture, "status")["calls"]
        navigate("/en/weather/maps/")
        wait_for(lambda: client.script('return document.body.textContent.includes("No external weather service or map is loaded");'))
        require(client.script('return !document.querySelector("iframe") && !document.querySelector("tbody");'))
        require(fixture_command(fixture, "status")["calls"] == before)
        report["checks"]["unsupported_maps_not_mounted"] = True
        report["phase"] = "shutdown"
        client.command("Marionette:Quit", {"flags": ["eAttemptQuit"]})
        normal_browser_stop = browser.wait(timeout=15) == 0
        stopped = fixture_command(fixture, "stop")
        normal_fixture_stop = stopped["stopped"] is True and fixture.wait(timeout=10) == 0
        report["checks"]["provider_requests"] = stopped["calls"]
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
        browser_stopped, fixture_stopped = stop(browser), stop(fixture)
        if fixture is not None:
            for stream in (fixture.stdin, fixture.stdout):
                try:
                    stream.close()
                except OSError:
                    pass
        private_removed = remove_private(work, identity) if browser_stopped and fixture_stopped else False
        report["cleanup"] = dict(browser_exited=browser_stopped, fixture_exited=fixture_stopped,
            private_profile_removed=private_removed,
            normal_browser_stop=normal_browser_stop, normal_fixture_stop=normal_fixture_stop)
        report["passed"] = report["passed"] and all(report["cleanup"].values())
        save_report(work, report)


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stage", "browser-stage", "node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
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
