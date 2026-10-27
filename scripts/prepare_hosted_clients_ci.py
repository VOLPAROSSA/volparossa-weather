#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build the pinned Drizz.li overlay and exercise its real UI in disposable CI.

No arguments or operator-supplied commands. Public acquisition is a separate
phase; compiler and browser children have no external network or host home.
This proves synthetic UI behaviour, NOT an origin fetch or core delivery.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import selectors
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
RUNTIME = BUILD / "hosted-client-runtime"
BROWSER = BUILD / "hosted-browser-source"
BROWSER_COMMIT = "08bac388a0abfd06426bebe8f6fabd0157d2e709"
FIREFOX_VERSION = "140.16.0"
FIREFOX_SOURCE_STAMP = "d864999404b3032f682d74ccc60d1ce38c9ce609"
PROJECT_NPMRC_SHA256 = "7151cf397def0c2cb0ab65643701d27d335a72c90f775675b5f826bc7005818a"
FIREFOX = BROWSER / "build/firefox-hosted-ci"
STAGE = BUILD / "drizzli-hosted-ci"
PROOF = BUILD / "drizzli-hosted-browser-ci"
OUTPUT = BUILD / "hosted-clients-ci"
PRIVATE = OUTPUT / "private"
NODE = RUNTIME / "node/bin/node"
NPM = RUNTIME / "node/lib/node_modules/npm/bin/npm-cli.js"
PROFILE = ROOT / "scripts/hosted-clients-bwrap.apparmor"
PROFILE_SHA = "2a0af5d2379bae5d2751599afef96a48567c5f3100308b61fce8028569039705"
LIMIT = 2 * 1024**2
GIB = 1024**3
LOGS = []
DRAIN_CONFIRMED = True
BOUNDARY = None  # Explicit reviewed manual mode; historical execution is unchanged.
BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}


class Interrupted(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, maximum=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid in (0, os.getuid())
                and not info.st_mode & 0o022 and info.st_size <= maximum, "UNSAFE_OR_OVERSIZED_INPUT")
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "INPUT_BOUND")
    return raw


def digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                and not info.st_mode & 0o022 and info.st_size <= 192 * 1024**2, "UNSAFE_FILE")
        return dict(bytes=info.st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest())


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def document(path):
    return json.loads(read(path), object_pairs_hook=unique)


def write(path, raw):
    require(len(raw) <= LIMIT, "OUTPUT_BOUND")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def save(name, value):
    write(OUTPUT / name, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def private_directory(path):
    path.mkdir(mode=0o700)
    require(path.resolve() == path and stat.S_IMODE(path.stat().st_mode) == 0o700
            and path.stat().st_uid == os.getuid(), "PRIVATE_DIRECTORY_REQUIRED")


def require_runtime_boundary():
    # Only actual legacy events may use the preserved historical namespace.
    # A source-mode controller cannot silently fall back to the host /usr.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        event = os.environ.get("GITHUB_EVENT_PATH")
        require(event is not None, "BOUNDARY_EVENT_CONTEXT_REQUIRED")
        value = json.loads(read(Path(event), 256 * 1024), object_pairs_hook=unique)
        require(type(value) is dict and type(value.get("inputs", {})) is dict, "BOUNDARY_EVENT_SCHEMA")
        mode = value.get("inputs", {}).get("input_mode", "")
        require(type(mode) is str and len(mode) <= 80, "BOUNDARY_EVENT_SCHEMA")
        event_name = os.environ.get("GITHUB_EVENT_NAME")
        legacy_dispatch = event_name == "workflow_dispatch" and mode == "historical-v1"
        legacy_push = event_name == "push" and mode == "" and (os.environ.get("GITHUB_WORKFLOW"),
            os.environ.get("GITHUB_REF")) in (("Build hosted Weather clients", "refs/heads/feature/hosted-weather-clients"),
                ("Build hosted Overmorrow client", "refs/heads/feature/hosted-overmorrow"))
        require(legacy_dispatch or legacy_push or BOUNDARY is not None, "RUNTIME_BOUNDARY_REQUIRED")


def available_memory():
    return int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                    if line.startswith("MemAvailable:"))) * 1024


def rss_category(base):
    """Diagnostic name classification only; never executable trust or logging."""
    try:
        name = Path(os.readlink(base / "exe")).name
    except OSError:
        # A disappeared/inaccessible executable must not discard RSS already
        # read from status. Unknown names and unreadable names share 'other'.
        return "other"
    if name == "java":
        return "java"
    return "dart" if name in ("dart", "dartvm", "dartaotruntime") else "other"


def java_cpu_state():
    return dict(status="unknown", samples_observed=0, samples_unavailable=0,
        max_process_cpu_ms=None, soft_limit_seconds=None, hard_limit_seconds=None, sampled_lower_bound=True)


def observe_java_cpu(base, result):
    """Own utime+stime only; no child CPU, PIDs, paths or command lines retained."""
    def bounded(path):
        with path.open("rb") as source:
            raw = source.read(65537)
        require(len(raw) <= 65536, "JAVA_CPU_SOURCE_BOUND")
        return raw.decode("ascii")
    def process_stat():
        # comm may contain spaces/parentheses. Fields after its final ')' begin
        # at field 3; utime, stime and starttime are fields 14, 15 and 22.
        fields = bounded(base / "stat").rsplit(")", 1)[1].split()
        values = tuple(int(fields[i]) for i in (11, 12, 19))
        require(all(0 <= value < 2**64 for value in values), "JAVA_CPU_STAT")
        return values
    def executable():
        require(Path(os.readlink(base / "exe")).name == "java", "JAVA_CPU_EXECUTABLE")
        info = (base / "exe").stat()
        return info.st_dev, info.st_ino
    try:
        first, exe = process_stat(), executable()
        limits = re.findall(r"^Max cpu time\s+(unlimited|[0-9]+)\s+(unlimited|[0-9]+)\s+seconds\s*$",
            bounded(base / "limits"), re.MULTILINE)
        require(len(limits) == 1, "JAVA_CPU_LIMIT")
        second = process_stat()
        require(first[2] == second[2] and first[0] <= second[0] and first[1] <= second[1]
            and exe == executable(), "JAVA_CPU_IDENTITY_CHANGED")
        ticks = os.sysconf("SC_CLK_TCK")
        require(type(ticks) is int and ticks > 0, "JAVA_CPU_CLOCK")
        milliseconds = (second[0] + second[1]) * 1000 // ticks
        soft, hard = (value if value == "unlimited" else int(value) for value in limits[0])
        require(all(value == "unlimited" or value < 2**64 for value in (soft, hard)), "JAVA_CPU_LIMIT")
        result["samples_observed"] = min(2**32-1, result["samples_observed"] + 1)
        if result["max_process_cpu_ms"] is None or milliseconds > result["max_process_cpu_ms"]:
            result.update(status="observed", max_process_cpu_ms=milliseconds,
                soft_limit_seconds=soft, hard_limit_seconds=hard)
    except (OSError, ValueError, IndexError, UnicodeError):
        # An unavailable CPU sample must never discard already measured RSS or
        # stop traversal/admission/cancellation. Unknown is not zero CPU use.
        result["samples_unavailable"] = min(2**32-1, result["samples_unavailable"] + 1)


def owned_rss(pid, *, categories=None, java_cpu=None):
    """Bound the whole descendant tree, including subprocesses with new sessions.

    RSS counts shared pages more than once: conservative pressure cancellation,
    not a claim of exact accounting or a replacement for the Node heap bound.
    """
    pending, seen, total = [pid], set(), 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        require(len(seen) <= 512, "CHILD_PROCESS_BOUND")
        try:
            base = Path("/proc") / str(current)
            status = (base / "status").read_text()
            require(len(status) <= 65536, "CHILD_STATUS_BOUND")
            rss = sum(int(line.split()[1]) * 1024 for line in status.splitlines() if line.startswith("VmRSS:"))
            total += rss
            category = rss_category(base) if categories is not None or java_cpu is not None else None
            if categories is not None:
                value = categories[category]
                value["processes"] += 1
                value["rss_bytes"] += rss
            if java_cpu is not None and category == "java":
                observe_java_cpu(base, java_cpu)
            for task in (base / "task").iterdir():
                children = (task / "children").read_text()
                require(len(children) <= 65536, "CHILD_PROCESS_BOUND")
                pending.extend(int(child) for child in children.split())
        except (FileNotFoundError, ProcessLookupError):
            pass
    return total


def group_drained(pid, seconds=2):
    """A delivered kill signal alone is not confirmation of process removal."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def run(name, argv, seconds, *, env=None, cwd=None, memory=2 * GIB, reserve=True, memory_categories=False, java_cpu=False):
    """Retain bounded original logs; never remove policy before owned children drain."""
    global DRAIN_CONFIRMED
    require(re.fullmatch(r"[a-z0-9-]+", name), "STEP_NAME")
    require(type(memory_categories) is bool and (not memory_categories or reserve), "MEMORY_DIAGNOSTIC_SCOPE")
    require(type(java_cpu) is bool and (not java_cpu or memory_categories), "JAVA_CPU_DIAGNOSTIC_SCOPE")
    raw = bytearray()
    child = None
    returned = False
    peak = 0
    peak_categories = None
    cpu = java_cpu_state() if java_cpu else None
    def observe_memory(pid):
        nonlocal peak, peak_categories
        categories = {name: dict(processes=0, rss_bytes=0) for name in ("java", "dart", "other")} if memory_categories else None
        # Exactly one traversal supplies both admission/cancellation accounting
        # and optional peak attribution; never combine independent samples.
        rss = owned_rss(pid, categories=categories, java_cpu=cpu) if java_cpu else (
            owned_rss(pid, categories=categories) if memory_categories else owned_rss(pid))
        if rss > peak or (memory_categories and peak_categories is None):
            peak, peak_categories = rss, categories
        require(peak <= memory, "CHILD_MEMORY_BOUND")
    host_reserve = 2 * GIB if reserve else 0
    launch_minimum = max(3 * GIB, memory + host_reserve) if reserve else 0
    started = time.monotonic()
    deadline = started + seconds
    try:
        if reserve:
            require(available_memory() >= launch_minimum, "HOST_MEMORY_RESERVE")
        # Defer asynchronous cancellation only until the returned PID belongs to
        # this finally block. Do not block signals in children through sigmask.
        pending = []
        spawn_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        for sig in spawn_handlers:
            signal.signal(sig, lambda signum, _frame: pending.append(signum))
        try:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=BASE_ENV if env is None else env, cwd=cwd, start_new_session=True)
        finally:
            for sig, handler in spawn_handlers.items():
                signal.signal(sig, handler)
        if pending:
            raise Interrupted("CANCELLED_DURING_OWNED_SPAWN")
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, "PHASE_DEADLINE")
                if reserve:
                    require(available_memory() >= 2 * GIB, "HOST_MEMORY_RESERVE")
                    observe_memory(child.pid)
                for key, _ in selector.select(0.2):
                    part = os.read(key.fd, 65536)
                    if not part:
                        selector.unregister(key.fileobj)
                    else:
                        require(len(raw) + len(part) <= LIMIT, "LOG_BOUND")
                        raw.extend(part)
            while child.poll() is None:
                require(time.monotonic() < deadline, "PHASE_DEADLINE")
                if reserve:
                    require(available_memory() >= 2 * GIB, "HOST_MEMORY_RESERVE")
                    observe_memory(child.pid)
                try:
                    child.wait(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            returned = True
            require(child.returncode == 0, "CHILD_FAILED")
    finally:
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if child is not None:
                # Kill the owned process group even if its leader has exited.
                # For sandbox steps, reaping bwrap also reaps its PID namespace:
                # the kernel kills remaining namespace children when PID 1 exits.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if not group_drained(child.pid) or child.returncode is None or child.returncode < 0:
                    # A forced outer-wrapper death cannot itself prove that a
                    # separately sessioned browser child namespace drained.
                    DRAIN_CONFIRMED = False
                child.stdout.close()
        except BaseException:
            DRAIN_CONFIRMED = False
            raise
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            write(OUTPUT / (name + ".log"), bytes(raw))
            LOGS.append(dict(name=name, bytes=len(raw), sha256=sha(raw),
                exit_status=child.returncode if child else None, returned=returned,
                peak_descendant_rss=peak, elapsed_ms=int((time.monotonic()-started)*1000),
                memory_monitor_enabled=reserve, memory_limit_bytes=memory,
                host_reserve_bytes=host_reserve, launch_min_available_bytes=launch_minimum,
                process_drain_confirmed=DRAIN_CONFIRMED,
                **(dict(peak_memory_categories=peak_categories,
                    memory_category_method="executable-name-allowlist-unknown-as-other") if memory_categories else {}),
                **(dict(java_cpu=cpu) if java_cpu else {})))
    return bytes(raw)


def policy_helper():
    # A private module instance shares the already tested fixed lifecycle logic,
    # not decoder globals or its entrypoint. The decoder workflow is unchanged.
    spec = importlib.util.spec_from_file_location("_hosted_client_policy", ROOT / "scripts/prepare_hosted_decoder_ci.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.PROFILE = PROFILE
    helper.PROFILE_SHA = PROFILE_SHA
    helper.STAGED = Path("/run/volparossa-weather-clients.apparmor")
    helper.NAMES = ("volparossa_ci_weather_clients_bwrap", "volparossa_ci_weather_clients_child")
    return helper


def guards(environment):
    require(os.geteuid() == os.getuid() != 0, "ORDINARY_RUNNER_REQUIRED")
    required = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW="Build hosted Weather clients")
    require(all(environment.get(key) == value for key, value in required.items()), "EXPLICIT_DISPOSABLE_CI_REQUIRED")
    require(environment.get("GITHUB_WORKSPACE") == str(ROOT)
            and re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")), "CI_SOURCE_REQUIRED")
    helper = policy_helper()
    platform = runpy.run_path(str(ROOT / "scripts/prepare_hosted_decoder.py"))
    require(platform["platform"]()["os_id"] == "ubuntu", "UBUNTU_24_REQUIRED")
    require(sha(read(PROFILE)) == PROFILE_SHA
            and sha(read(ROOT / "third_party/apparmor-ci/LICENSE")) == helper.LICENSE_SHA, "POLICY_PROVENANCE")
    _, head = helper.process(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"], 10)
    require(head.decode().strip() == environment["GITHUB_SHA"], "SOURCE_COMMIT_CHANGED")
    helper.process(["/usr/bin/git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--"], 10)
    _, head = helper.process(["/usr/bin/git", "-C", str(BROWSER), "rev-parse", "HEAD"], 10)
    require(head.decode().strip() == BROWSER_COMMIT, "BROWSER_COMMIT_CHANGED")
    helper.process(["/usr/bin/git", "-C", str(BROWSER), "diff", "--quiet", "HEAD", "--"], 10)
    for root in (ROOT, BUILD, BROWSER, RUNTIME):
        info = root.lstat()
        require(root.resolve() == root and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and not info.st_mode & 0o022, "OWNED_SOURCE_REQUIRED")
    return helper, platform


def runtime_inventory():
    preparer = runpy.run_path(str(ROOT / "scripts/prepare_hosted_runtime.py"))
    pin, pin_sha = preparer["load_pin"]()
    npm, npm_sha = preparer["load_npm_pin"](pin)
    value = document(RUNTIME / "provenance.json")
    require(value.get("schema") == 2 and value.get("profile") == npm["profile"]
            and value.get("pin_sha256") == pin_sha
            and value.get("preparer_sha256") == sha(read(ROOT / "scripts/prepare_hosted_runtime.py"))
            and value.get("npm", {}).get("pin_sha256") == npm_sha, "RUNTIME_PROVENANCE_CHANGED")
    files = value["files"]
    require(type(files) is dict and 1 <= len(files) <= 4096, "RUNTIME_INVENTORY_BOUND")
    verify_runtime_closure(files)
    total = 0
    for relative, record in files.items():
        require(relative == preparer["safe_name"](relative)
                and relative.startswith(("node/", "firefox/", "licenses/")), "RUNTIME_PATH")
        path = RUNTIME / relative
        require(path.resolve() == path and record.get("path") == relative
                and record.get("mode") in (0o600, 0o700), "RUNTIME_RECORD")
        actual = digest(path)
        require(actual == {key: record[key] for key in ("bytes", "sha256")}
                and stat.S_IMODE(path.stat().st_mode) == record["mode"], "RUNTIME_BYTES_CHANGED")
        total += actual["bytes"]
    require(total <= 512 * 1024**2, "RUNTIME_SIZE_BOUND")
    for kind, entry in pin["artifacts"].items():
        require(value["inputs"][kind]["sha256"] == entry["sha256"], "RUNTIME_ARCHIVE_PIN")
        for name, expected in entry["expected_files"].items():
            require(digest(RUNTIME / kind / name) == expected, "EXECUTABLE_PIN_CHANGED")
    preparer["verify_npm"](RUNTIME, files, npm)
    return dict(provenance_sha256=sha(read(RUNTIME / "provenance.json")), files=len(files), bytes=total,
        full_inventory_sha256=preparer["inventory_sha256"](files), npm_version=npm["version"])


def verify_runtime_closure(files):
    actual, scanned = set(), 0
    for name in ("node", "firefox", "licenses"):
        root = RUNTIME / name
        require(root.resolve() == root and root.is_dir(), "RUNTIME_ROOT_TYPE")
        for path in root.rglob("*"):
            scanned += 1
            require(scanned <= 12000, "RUNTIME_TREE_BOUND")
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "RUNTIME_TREE_TYPE")
            if stat.S_ISREG(info.st_mode):
                actual.add(str(path.relative_to(RUNTIME)))
    require(actual == set(files), "RUNTIME_EXTRA_OR_MISSING_FILES")


def environment(network=False):
    # No inherited proxy, auth, npm, Node, HOME, Git credential or telemetry settings.
    value = dict(BASE_ENV, PATH=str(NODE.parent) + ":/usr/bin:/bin", HOME="/home/runner",
        npm_config_userconfig="/state/user.npmrc", npm_config_globalconfig="/state/global.npmrc",
        npm_config_cache="/state/npm-cache", npm_config_registry="https://registry.npmjs.org/",
        npm_config_ignore_scripts="true", npm_config_audit="false", npm_config_fund="false",
        npm_config_update_notifier="false", npm_config_fetch_retries="0",
        npm_config_fetch_timeout="30000", NODE_OPTIONS="--max-old-space-size=768",
        PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1", VITE_VOLPAROSSA_WEATHER="1",
        CI="true", NO_COLOR="1", DO_NOT_TRACK="1")
    if BOUNDARY is not None:
        value['XDG_CACHE_HOME'] = '/state/cache'
    return value


def sandbox(command, *, mode, writable=None):
    require_runtime_boundary()
    require(mode in ("acquire", "compile", "browser"), "SANDBOX_MODE")
    argv = ["/usr/bin/prlimit", "--core=0", "--cpu=300", "--nofile=1024", "--",
        "/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts", "--tmpfs", "/"]
    argv += BOUNDARY.system_mounts() if BOUNDARY is not None else ["--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--dir", "/etc", "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    argv += [
        "--ro-bind", str(OUTPUT / "passwd"), "/etc/passwd",
        "--ro-bind", str(OUTPUT / "group"), "/etc/group",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        # A separate private mount is needed for --remount-ro below. Create it
        # BEFORE the reviewed source bind: hosted checkout paths live beneath
        # /home/runner/work, and a later home mount would hide that source.
        "--dir", "/home", "--tmpfs", "/home/runner"]
    argv += BOUNDARY.source_mounts(mode) if BOUNDARY is not None else ["--ro-bind", str(ROOT), str(ROOT)]
    argv += ["--tmpfs", str(OUTPUT)]
    if mode == "acquire":
        argv += BOUNDARY.acquisition_mounts() if BOUNDARY is not None else [
            "--ro-bind", str(Path("/etc/resolv.conf").resolve()), "/etc/resolv.conf",
            "--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs"]
    else:
        argv += ["--unshare-net"]
    if mode == "browser":
        require(writable == PROOF, "BROWSER_OUTPUT_REQUIRED")
        argv += ([] if BOUNDARY is not None else ["--ro-bind", "/etc/fonts", "/etc/fonts"])
        argv += ["--bind", str(PROOF), str(PROOF),
                 "--dir", "/home/runner/.mozilla", "--bind", str(PROOF / "appdata"), "/home/runner/.mozilla"]
    else:
        require(writable in (None, STAGE), "BUILD_OUTPUT_REQUIRED")
        argv += ["--bind", str(PRIVATE), "/state"]
        if writable is not None:
            argv += ["--bind", str(writable), str(writable)]
    if BOUNDARY is not None:
        argv += ["--remount-ro", "/home/runner/work"]
    argv += ["--remount-ro", "/home/runner", "--remount-ro", "/",
             "--chdir", str(STAGE if writable == STAGE else ROOT), "--", *command]
    return argv


PROBE = r'''
import json, os, socket, stat, sys
from pathlib import Path
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
mode=sys.argv[5]
network=mode=='acquire'
assert os.getuid()==int(sys.argv[1])!=0
assert int(status['CapEff'],16)==int(status['CapPrm'],16)==0 and int(status['NoNewPrivs'])==1
assert 'volparossa_ci_weather_clients_child' in Path('/proc/self/attr/current').read_text()
assert (os.readlink('/proc/self/ns/net')==sys.argv[2])==network
if not network:
 assert [name for _,name in socket.if_nameindex()]==['lo']
assert not any(Path(p).exists() for p in ['/root','/run'])
assert Path('/etc/resolv.conf').exists()==network
assert not any('TOKEN' in name or 'PROXY' in name or 'AUTH' in name for name in os.environ)
assert list(Path('/home').iterdir())==[Path('/home/runner')]
assert Path.home()==Path('/home/runner')
assert os.statvfs('/').f_flag & os.ST_RDONLY and os.statvfs('/usr').f_flag & os.ST_RDONLY
assert os.statvfs(sys.argv[3]).f_flag & os.ST_RDONLY
allowed={sys.argv[4],'/home/runner/.mozilla'} if mode=='browser' else {sys.argv[4],'/state'}
assert not os.statvfs(sys.argv[4]).f_flag & os.ST_RDONLY
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 f=line.split(); fs=f[f.index('-')+1]; p=f[4]
 if fs not in ('tmpfs','proc','devpts') and p not in allowed and not p.startswith('/dev/'):
  assert 'ro' in f[5].split(',')
print(json.dumps(dict(schema=1,kind='hosted-client-sandbox-preflight',mode=mode,unprivileged=True,
 capabilities_zero=True,no_new_privileges=True,capability_denied_child=True,empty_root=True,
 loopback_only=not network,separate_network_namespace=not network,external_acquisition=network,
 private_home=True,read_only_source=True,only_declared_host_writes=True,auth_environment_absent=True)))
'''


def preflight(mode):
    require_runtime_boundary()
    if BOUNDARY is not None:
        return BOUNDARY.preflight(mode)
    work = PROOF if mode == "browser" else STAGE
    raw = run("preflight-" + mode, sandbox(["/usr/bin/python3", "-I", "-c", PROBE,
        str(os.getuid()), os.readlink("/proc/self/ns/net"), str(ROOT), str(work), mode],
        mode=mode, writable=work), 20, env=environment())
    value = json.loads(raw, object_pairs_hook=unique)
    fields = {"unprivileged", "capabilities_zero", "no_new_privileges", "capability_denied_child",
              "empty_root", "private_home", "read_only_source", "only_declared_host_writes", "auth_environment_absent"}
    require(set(value) == fields | {"schema", "kind", "mode", "loopback_only", "separate_network_namespace", "external_acquisition"}
            and type(value["schema"]) is int and value["schema"] == 1 and value["mode"] == mode
            and value["kind"] == "hosted-client-sandbox-preflight"
            and value["loopback_only"] is (mode != "acquire")
            and value["separate_network_namespace"] is (mode != "acquire")
            and value["external_acquisition"] is (mode == "acquire")
            and all(value[key] is True for key in fields), "PREFLIGHT_FAILED")
    save("preflight-" + mode + ".json", value)


def locked_dependencies():
    metadata = document(ROOT / "integrations/drizzli/upstream.json")
    require(sha(read(STAGE / "package-lock.json")) == metadata["package_lock_sha256"], "DEPENDENCY_LOCK_CHANGED")
    value = document(STAGE / "package-lock.json")
    require(value.get("lockfileVersion") == 3 and type(value.get("packages")) is dict
            and len(value["packages"]) <= 4096, "LOCKFILE_SCHEMA")
    for name, entry in value["packages"].items():
        if not name:
            continue
        require(name.startswith("node_modules/") and not entry.get("link")
                and isinstance(entry.get("resolved"), str)
                and entry["resolved"].startswith("https://registry.npmjs.org/")
                and re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", entry.get("integrity", "")), "DEPENDENCY_ORIGIN_OR_INTEGRITY")
    project_npm_config()
    return metadata


def project_npm_config():
    # Exact unchanged upstream d2a6839 configuration, not permission to import
    # arbitrary npm settings. This only enforces declared engine requirements;
    # registry/auth/proxy and lifecycle-script overrides remain unadmitted.
    raw = read(STAGE / ".npmrc", 256)
    require(raw == b"engine-strict=true\n" and sha(raw) == PROJECT_NPMRC_SHA256,
            "PROJECT_NPM_CONFIG_NOT_ADMITTED")
    return PROJECT_NPMRC_SHA256


def npm_command():
    return [str(NODE), str(NPM), "ci", "--ignore-scripts", "--no-audit", "--no-fund",
            "--cache", "/state/npm-cache"]


def compile_commands():
    return (
        ("localization", "paraglide-js", ["compile", "--project", "./project.inlang", "--outdir", "./src/lib/paraglide"], 120),
        ("svelte-sync", "svelte-kit", ["sync"], 120),
        ("typecheck", "svelte-check", ["--tsconfig", "./tsconfig.json"], 120),
        ("production-build", "vite", ["build"], 180),
    )


def compilation_memory(name):
    require(name in {step[0] for step in compile_commands()}, "UNKNOWN_COMPILE_PHASE")
    # Vite's sequential SSR/client build retains a parent graph while its
    # SvelteKit prerender worker starts. The hosted run measured 1,696,092,160
    # bytes of aggregate descendant RSS, not a Node heap-limit violation.
    # Give ONLY this phase 2 GiB; retain per-Node 768 MiB and host headroom.
    return 2 * GIB if name == "production-build" else 1536 * 1024**2


def installed_cli(name):
    entries = {"paraglide-js": "@inlang/paraglide-js/bin/run.js", "svelte-kit": "@sveltejs/kit/svelte-kit.js",
               "svelte-check": "svelte-check/bin/svelte-check", "vite": "vite/bin/vite.js"}
    require(name in entries, "UNEXPECTED_BUILD_CLI")
    path = (STAGE / "node_modules/.bin" / name).resolve(strict=True)
    # The lock-pinned svelte-check CLI is extensionless JavaScript. Every CLI is
    # invoked via our exact Node, never its shebang or a shell shim.
    require(path == STAGE / "node_modules" / entries[name] and not path.is_symlink(), "UNEXPECTED_BUILD_CLI")
    digest(path)
    return path


def verify_firefox_copy(files, *, root=None):
    root = root if root is not None else (BOUNDARY.firefox_copy if BOUNDARY is not None else FIREFOX)
    expected = {"volparossa-staging.json", "volparossa.cfg", "defaults/pref/volparossa-autoconfig.js"}
    for relative, entry in files.items():
        if relative.startswith("firefox/"):
            name = relative.removeprefix("firefox/")
            expected.add(name)
            path = root / name
            require(digest(path) == {key: entry[key] for key in ("bytes", "sha256")}, "FIREFOX_COPY_CHANGED")
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), "FIREFOX_COPY_LINK")
        if not path.is_dir():
            actual.add(str(path.relative_to(root)))
            require(len(actual) <= 4096, "FIREFOX_COPY_BOUND")
    require(actual == expected, "FIREFOX_COPY_EXTRA_OR_MISSING")
    require(not (root / "browser/defaults/syspref").exists()
            and not (root / "distribution").exists(), "HOST_PREFERENCES_IMPORTED")


def browser_command(netns):
    return ["/usr/bin/python3", "-B", str(ROOT / "integrations/drizzli/smoke_browser.py"),
        "--stage", str(STAGE), "--browser-root", str(BROWSER), "--browser-stage", str(FIREFOX),
        "--node", str(NODE), "--output", str(PROOF), "--precipitation", "--air-quality",
        "--inside", "--host-netns", netns]


def execute(helper, platform):
    require_runtime_boundary()
    installed = attempted = success = False
    phase = "baseline"
    start = time.monotonic()
    runtime = None
    outer = dict(process_drain_confirmed=False, private_profile_removed=False, host_netns_unchanged=False)
    netns = os.readlink("/proc/self/ns/net")
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_sig, _frame):
        raise Interrupted("HOSTED_CLIENTS_INTERRUPTED")
    for sig in previous:
        signal.signal(sig, interrupted)
    try:
        baseline = helper.prechecks(platform)
        baseline["kind"] = "hosted-clients-sandbox-baseline"
        save("baseline.json", baseline)
        runtime = runtime_inventory()
        save("runtime-binding.json", runtime)
        if BOUNDARY is None:
            private_directory(PRIVATE)
        write(OUTPUT / "passwd", f"runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n".encode())
        write(OUTPUT / "group", f"runner:x:{os.getgid()}:\n".encode())
        if BOUNDARY is None:
            write(PRIVATE / "user.npmrc", b"")
            write(PRIVATE / "global.npmrc", b"")
        phase = "policy-install"
        print("Disposable hosted CI only: install scoped bwrap setup/denied-capability child profiles; remove after namespace drain; do not change userns sysctls.", flush=True)
        installed = True
        helper.process(["/usr/bin/sudo", "-n", "/usr/bin/install", "-o", "root", "-g", "root", "-m", "0600", "--", str(PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(["/usr/bin/sudo", "-n", helper.PARSER, "--add", "--skip-cache", str(helper.STAGED)], 10)
        if BOUNDARY is not None:
            if BOUNDARY.view.cache_sha is None:
                BOUNDARY.prepare_cache()
            else:
                BOUNDARY.check()
            private_directory(PRIVATE)
            private_directory(PRIVATE / "cache")
            write(PRIVATE / "user.npmrc", b"")
            write(PRIVATE / "global.npmrc", b"")
        phase = "public-acquisition"
        # Reviewed standard-library staging only, with sanitized credential-free
        # environment. No downloaded source is executed in these two steps.
        run("source-stage", ["/usr/bin/python3", "-B", str(ROOT / "integrations/drizzli/stage.py"),
            "--execute", "--destination", str(STAGE)], 270)
        run("localization-plugins", ["/usr/bin/python3", "-B", str(ROOT / "integrations/drizzli/prepare_build.py"),
            "--execute", "--stage", str(STAGE)], 90)
        metadata = locked_dependencies()
        preflight("acquire")
        run("npm-acquisition", sandbox(npm_command(), mode="acquire", writable=STAGE),
            300, env=environment(True), memory=1536 * 1024**2)
        require(sha(read(STAGE / "package-lock.json")) == metadata["package_lock_sha256"], "LOCK_CHANGED_BY_INSTALL")
        project_npm_config()
        phase = "offline-compilation"
        preflight("compile")
        cli_bindings = {}
        for name, cli, args, seconds in compile_commands():
            require(time.monotonic() - start < 1200, "WHOLE_BUILD_DEADLINE")
            executable = installed_cli(cli)
            cli_bindings[cli] = dict(path=str(executable.relative_to(STAGE)), **digest(executable))
            run(name, sandbox([str(NODE), str(executable), *args], mode="compile", writable=STAGE),
                seconds, env=environment(), memory=compilation_memory(name))
        run("client-render-tests", sandbox([str(NODE), "--test", str(ROOT / "integrations/drizzli/test-client.mjs"),
            str(ROOT / "integrations/drizzli/test-render.mjs")], mode="compile", writable=STAGE),
            120, env=dict(environment(), DRIZZLI_STAGE=str(STAGE)), memory=1536 * 1024**2)
        # Upstream static files can carry group-write archive mode bits. Tighten
        # ONLY this newly generated public output, never a host source directory.
        for path in (STAGE / "build").rglob("*"):
            require(not path.is_symlink() and path.stat().st_uid == os.getuid(), "BUILT_ASSET_TYPE")
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o022)
        phase = "firefox-staging"
        if BOUNDARY is None:
            run("firefox-stage", ["/usr/bin/python3", "-B", str(BROWSER / "scripts/stage_firefox.py"),
                "--firefox", str(RUNTIME / "firefox/firefox-esr"), "--output", str(FIREFOX),
                "--expected-version", FIREFOX_VERSION, "--expected-source-stamp", FIREFOX_SOURCE_STAMP,
                "--without-extensions"], 90)
        elif not BOUNDARY.firefox_ready:
            BOUNDARY.stage_firefox()
        files = document(RUNTIME / "provenance.json")["files"]
        verify_firefox_copy(files)
        private_directory(PROOF)
        private_directory(PROOF / "appdata")
        for name in ("firefox", "firefox-esr"):
            private_directory(PROOF / "appdata" / name)
        preflight("browser")
        phase = "synthetic-browser"
        run("browser-smoke", sandbox(browser_command(netns), mode="browser", writable=PROOF),
            120, env=BASE_ENV, memory=2 * GIB)
        report = document(PROOF / "report.json")
        require(report.get("passed") is True and report.get("phase") == "complete"
                and report.get("scenario") == "precipitation" and report.get("air_quality_scenario") is True
                and all(report["cleanup"].values()) and report["scope"]["core_executed"] is False
                and report["scope"]["overlay_proven"] is False
                and report["scope"]["synthetic_weather"] is True and report["scope"]["synthetic_air_quality"] is True,
                "BROWSER_PROOF_FAILED")
        require(runtime_inventory() == runtime, "RUNTIME_CHANGED_DURING_BUILD")
        verify_firefox_copy(files)
        save("build.json", dict(schema=1, kind="hosted-drizzli-build", weather_commit=os.environ["GITHUB_SHA"],
            browser_commit=BROWSER_COMMIT, upstream_commit=metadata["commit"],
            lock_sha256=metadata["package_lock_sha256"], cli_bindings=cli_bindings,
            project_npmrc_sha256=project_npm_config(),
            plugin_files={str(p.relative_to(STAGE)): digest(p) for p in sorted((STAGE / "volparossa-build-plugins").iterdir())},
            runtime=runtime, browser_report_sha256=sha(read(PROOF / "report.json")),
            compiled_networkless=True, dependency_lifecycle_scripts=False, mutable_assets_prehook=False,
            actual_synthetic_ui=True, core_delivery=False, weather_origin=False,
            source=report["source"], copyright_notices_preserved=True))
        phase = "complete"
        success = True
    except BaseException as error:
        save("failure.json", dict(schema=1, phase=phase, category=type(error).__name__,
             code=str(error) if isinstance(error, (ValueError, Interrupted)) else "HOSTED_CLIENTS_FAILURE"))
        raise
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            outer["process_drain_confirmed"] = DRAIN_CONFIRMED
            outer["host_netns_unchanged"] = os.readlink("/proc/self/ns/net") == netns
            # The actual browser helper removes private profiles on success or
            # failure. If aborted before its finally, retain scratch for runner
            # disposal rather than delete uncertain data or claim cleanup.
            outer["private_profile_removed"] = not any((PROOF / name).exists() for name in
                ("profile", "config", "cache", "runtime", "tmp", "appdata"))
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed)
            cleaning["kind"] = "hosted-clients-sandbox-cleanup"
            save("cleanup.json", cleaning)
            save("steps.json", dict(schema=1, steps=LOGS))
            save("result.json", dict(schema=1, kind="hosted-client-build-and-synthetic-ui", phase=phase,
                success=success and cleaning["complete"] and all(outer.values()),
                weather_commit=os.environ["GITHUB_SHA"], browser_commit=BROWSER_COMMIT,
                outer_cleanup=outer, policy_cleanup_complete=cleaning["complete"],
                driver="existing-smoke-browser-inside-under-hosted-empty-root-wrapper",
                synthetic_weather=True, synthetic_air_quality=True,
                origin_acquisition=False, core_delivery=False, production_authority=False))
            require(cleaning["complete"] and (not success or all(outer.values())), "CLEANUP_UNPROVEN")
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    require(len(sys.argv) == 1, "NO_ARGUMENTS_ALLOWED")
    os.umask(0o077)
    helper, platform = guards(os.environ)
    private_directory(OUTPUT)
    execute(helper, platform)


if __name__ == "__main__":
    try:
        main()
    except (Interrupted, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("HOSTED_CLIENTS_CI_FAILED; inspect closed diagnostics", file=sys.stderr)
        sys.exit(1)
