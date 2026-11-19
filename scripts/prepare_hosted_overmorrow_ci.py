#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build and exercise the real Overmorrow web overlay in disposable hosted CI.

Acquisition alone has external networking. Flutter tests/build and both existing
synthetic browser drivers run in empty-root, bounded namespaces. This is not a
native mobile, origin acquisition or core-delivery proof.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
HERE = ROOT / "integrations/overmorrow"
OUTPUT = BUILD / "hosted-overmorrow-ci"
PRIVATE = OUTPUT / "private"
SDK = BUILD / "hosted-flutter-sdk"
SDK_TOOL_STATE = PRIVATE / "flutter-tool-state"
SDK_TOOL_MOUNT = SDK / "packages/flutter_tools/.dart_tool"
STAGE = BUILD / "overmorrow-hosted-ci"
DEPLOY = BUILD / "overmorrow-hosted-web-ci"
PROOF = BUILD / "overmorrow-hosted-browser-ci"
TABLE_PROOF = BUILD / "overmorrow-hosted-table-ci"
WORKFLOW = "Build hosted Overmorrow client"
GIB = 1024**3
FLUTTER_MEMORY = 3 * GIB
FLUTTER_TEST_COUNT = 24
WHICH = Path("/usr/bin/which.debianutils")
PROFILE_DIRS = ("profile", "config", "cache", "runtime", "tmp", "appdata")

# Private module: reuse the independently reviewed process drain, AppArmor,
# runtime and Firefox-copy checks without changing the Drizz.li entrypoint.
spec = importlib.util.spec_from_file_location("_overmorrow_hosted_lifecycle", ROOT / "scripts/prepare_hosted_clients_ci.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)
H.OUTPUT, H.PRIVATE, H.STAGE, H.PROOF = OUTPUT, PRIVATE, STAGE, PROOF
require = H.require


def guards(environment):
    require(os.geteuid() == os.getuid() != 0, "ORDINARY_RUNNER_REQUIRED")
    required = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW=WORKFLOW)
    require(all(environment.get(key) == value for key, value in required.items()), "EXPLICIT_DISPOSABLE_CI_REQUIRED")
    require(environment.get("GITHUB_WORKSPACE") == str(ROOT)
            and re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")), "CI_SOURCE_REQUIRED")
    helper = H.policy_helper()
    platform = runpy.run_path(str(ROOT / "scripts/prepare_hosted_decoder.py"))
    require(platform["platform"]()["os_id"] == "ubuntu", "UBUNTU_24_REQUIRED")
    require(H.sha(H.read(H.PROFILE)) == H.PROFILE_SHA
            and H.sha(H.read(ROOT / "third_party/apparmor-ci/LICENSE")) == helper.LICENSE_SHA, "POLICY_PROVENANCE")
    for path, expected in ((ROOT, environment["GITHUB_SHA"]), (H.BROWSER, H.BROWSER_COMMIT)):
        _, head = helper.process(["/usr/bin/git", "-C", str(path), "rev-parse", "HEAD"], 10)
        require(head.decode().strip() == expected, "SOURCE_COMMIT_CHANGED")
        helper.process(["/usr/bin/git", "-C", str(path), "diff", "--quiet", "HEAD", "--"], 10)
    for path in (ROOT, BUILD, H.BROWSER, H.RUNTIME, SDK):
        info = path.lstat()
        require(path.resolve() == path and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and not info.st_mode & 0o022, "OWNED_SOURCE_REQUIRED")
    return helper, platform


def environment():
    # No inherited HOME/config, Dart options, proxy, registry or authentication.
    return dict(H.BASE_ENV, PATH=f"{SDK}/bin:/tools:/usr/bin:/bin", HOME="/home/runner",
        USER="runner", LOGNAME="runner", CI="true", BOT="true", TZ="UTC",
        FLUTTER_SUPPRESS_ANALYTICS="true", DART_SUPPRESS_ANALYTICS="true",
        PUB_CACHE="/state/pub-cache", PUB_HOSTED_URL="https://pub.dev",
        FLUTTER_STORAGE_BASE_URL="https://storage.googleapis.com",
        XDG_CONFIG_HOME="/state/config", XDG_CACHE_HOME="/state/cache",
        GIT_OPTIONAL_LOCKS="0", NO_COLOR="1", DO_NOT_TRACK="1")


def sandbox(command, *, mode, proof=None):
    require(mode in ("acquire", "compile", "browser"), "SANDBOX_MODE")
    if mode == "browser":
        require(proof in (PROOF, TABLE_PROOF), "BROWSER_OUTPUT_REQUIRED")
        argv = H.sandbox(command, mode=mode, writable=PROOF)
        # Both original drivers get separate fresh private scratch. There is no
        # shared profile and no rewritten/combined original browser report.
        return [str(proof) if item == str(PROOF) else
                str(proof / "appdata") if item == str(PROOF / "appdata") else item for item in argv]
    require(proof is None, "UNEXPECTED_BROWSER_OUTPUT")
    argv = H.sandbox(command, mode=mode, writable=STAGE)
    # Flutter also initializes its own PubDependencies before app commands.
    # Persist that generated .dart_tool state outside the verified SDK; the
    # SDK mountpoint stays empty on disk and source/.git/locks remain read-only.
    # HOME is an empty tmpfs made BEFORE the read-only checkout mount. Flutter
    # may write its own ephemeral metadata there, never the runner's real home.
    index = next(i for i in range(len(argv) - 1) if argv[i:i+2] == ["--remount-ro", "/home/runner"])
    require(argv[index:index+2] == ["--remount-ro", "/home/runner"], "SANDBOX_TEMPLATE_CHANGED")
    cache_mounts = H.BOUNDARY.sdk_metadata_mounts() if H.BOUNDARY is not None else [
        "--bind", str(SDK / "bin/cache"), str(SDK / "bin/cache")]
    argv[index:index+2] = [*cache_mounts, "--bind", str(SDK_TOOL_STATE), str(SDK_TOOL_MOUNT)]
    # Ubuntu's /usr/bin/which is an alternatives link through the deliberately
    # absent /etc/alternatives. Expose only the recorded canonical implementation
    # through an alias in the new root, not the runner's alternatives directory.
    argv[index:index] = ["--dir", "/tools", "--symlink", str(WHICH), "/tools/which"]
    argv[argv.index("--cpu=300")] = "--cpu=900"
    return argv


PROBE = r'''
import json, os, socket, sys
from pathlib import Path
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
mode=sys.argv[5]; network=mode=='acquire'; browser=mode=='browser'
assert os.getuid()==int(sys.argv[1])!=0
assert int(status['CapEff'],16)==int(status['CapPrm'],16)==0 and int(status['NoNewPrivs'])==1
assert 'volparossa_ci_weather_clients_child' in Path('/proc/self/attr/current').read_text()
assert (os.readlink('/proc/self/ns/net')==sys.argv[2])==network
if not network: assert [name for _,name in socket.if_nameindex()]==['lo']
assert not any(Path(p).exists() for p in ['/root','/run'])
assert Path('/etc/resolv.conf').exists()==network
assert not any('TOKEN' in key or 'PROXY' in key or 'AUTH' in key for key in os.environ)
assert list(Path('/home').iterdir())==[Path('/home/runner')]
assert Path.home()==Path('/home/runner')
assert all(os.statvfs(p).f_flag & os.ST_RDONLY for p in ['/', '/usr',sys.argv[3],sys.argv[6]])
tool_state=Path(sys.argv[6])/'packages/flutter_tools/.dart_tool'
allowed={sys.argv[4],'/home/runner/.mozilla'} if browser else {sys.argv[4],'/state',sys.argv[6]+'/bin/cache',str(tool_state)}
assert not os.statvfs(sys.argv[4]).f_flag & os.ST_RDONLY
if browser:
 assert os.stat('/home/runner/.mozilla').st_ino==os.stat(Path(sys.argv[4])/'appdata').st_ino
 assert os.statvfs('/home/runner').f_flag & os.ST_RDONLY
else:
 assert Path('/tools/which').is_symlink() and os.readlink('/tools/which')=='/usr/bin/which.debianutils'
 assert Path('/tools/which').resolve(strict=True)==Path('/usr/bin/which.debianutils')
 assert os.access('/tools/which',os.X_OK) and os.statvfs('/tools').f_flag & os.ST_RDONLY
 assert os.stat(tool_state).st_ino==os.stat('/state/flutter-tool-state').st_ino
 assert os.statvfs(tool_state.parent).f_flag & os.ST_RDONLY
 assert os.statvfs(tool_state.parent/'pubspec.lock').f_flag & os.ST_RDONLY
 for p in ['/state',sys.argv[6]+'/bin/cache','/home/runner',str(tool_state)]:
  assert not os.statvfs(p).f_flag & os.ST_RDONLY
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 f=line.split(); fs=f[f.index('-')+1]; p=f[4]
 if fs not in ('tmpfs','proc','devpts') and p not in allowed and not p.startswith('/dev/'):
  assert 'ro' in f[5].split(',')
print(json.dumps(dict(schema=1,kind='hosted-overmorrow-sandbox-preflight',mode=mode,
 unprivileged=True,capabilities_zero=True,no_new_privileges=True,capability_denied_child=True,
 empty_root=True,loopback_only=not network,separate_network_namespace=not network,
 external_acquisition=network,private_home=True,read_only_source=True,
 sdk_source_read_only=True,sdk_cache_writable=not browser,only_declared_host_writes=True,
 auth_environment_absent=True)))
'''


def preflight(mode, proof=None):
    H.require_runtime_boundary()
    if H.BOUNDARY is not None:
        from types import SimpleNamespace
        return H.BOUNDARY.preflight(mode, overmorrow=SimpleNamespace(
            sandbox=sandbox, environment=environment, SDK_TOOL_MOUNT=SDK_TOOL_MOUNT), proof=proof)
    work = proof if mode == "browser" else STAGE
    name = "preflight-" + ("table-browser" if proof == TABLE_PROOF else mode)
    raw = H.run(name, sandbox(["/usr/bin/python3", "-I", "-c", PROBE, str(os.getuid()),
        os.readlink("/proc/self/ns/net"), str(ROOT), str(work), mode, str(SDK)], mode=mode, proof=proof),
        20, env=environment())
    value = json.loads(raw, object_pairs_hook=H.unique)
    flags = {"unprivileged", "capabilities_zero", "no_new_privileges", "capability_denied_child",
        "empty_root", "private_home", "read_only_source", "sdk_source_read_only",
        "only_declared_host_writes", "auth_environment_absent"}
    require(set(value) == flags | {"schema", "kind", "mode", "loopback_only", "separate_network_namespace",
                "external_acquisition", "sdk_cache_writable"}
        and type(value["schema"]) is int and value["schema"] == 1
        and value["kind"] == "hosted-overmorrow-sandbox-preflight" and value["mode"] == mode
        and value["loopback_only"] is (mode != "acquire")
        and value["separate_network_namespace"] is (mode != "acquire")
        and value["external_acquisition"] is (mode == "acquire")
        and value["sdk_cache_writable"] is (mode != "browser")
        and all(value[key] is True for key in flags), "PREFLIGHT_FAILED")
    H.save(name + ".json", value)


def build_contract():
    return runpy.run_path(str(HERE / "build.py"))


def flutter_command(action):
    contract = build_contract()
    require(action in ("dependencies", "dependencies-offline", "test", "build"), "FLUTTER_ACTION")
    cpus = sorted(os.sched_getaffinity(0))[:2]
    require(cpus, "NO_BUILD_CPU")
    return ["/usr/bin/nice", "-n", "10", "/usr/bin/taskset", "-c", ",".join(map(str, cpus)),
        str(SDK / "bin/flutter"), "--no-version-check", "--suppress-analytics", *contract["ACTIONS"][action]]


def sdk_diff_command():
    # Git's porcelain diff may refresh .git/index even with optional locks off.
    # This is inspection of immutable archive bytes, not index maintenance.
    return ["/usr/bin/git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
            "-c", "diff.autoRefreshIndex=false", "-C", str(SDK), "diff", "--quiet", "HEAD", "--"]


def verify_phase_inputs(helper, pin):
    require(H.sha(H.read(STAGE / "pubspec.lock")) == pin["pubspec_lock_sha256"], "DEPENDENCY_LOCK_CHANGED")
    _, head = helper.process(["/usr/bin/git", "--no-optional-locks", "-C", str(SDK), "rev-parse", "HEAD"], 10)
    require(head.decode().strip() == pin["flutter_commit"], "FLUTTER_COMMIT_CHANGED")
    helper.process(sdk_diff_command(), 20)
    _, extra = helper.process(["/usr/bin/git", "--no-optional-locks", "-C", str(SDK), "ls-files", "--others", "bin/internal"], 10)
    require(not extra.strip(), "UNREVIEWED_FLUTTER_BOOTSTRAP")
    for relative, expected in build_contract()["SDK_FILES"].items():
        require(H.digest(SDK / relative)["sha256"] == expected, "FLUTTER_EXECUTABLE_CHANGED")
    # Recheck all original executable/source bytes, not just these two critical
    # files. The preparer admits only named mutable cache metadata, never a new
    # executable hidden in an otherwise writable SDK cache.
    return sdk_inventory(allow_build_state=True)


def sdk_inventory(allow_build_state=False):
    # The materializer owns archive/provenance validation; it never executes SDK
    # code. This full original inventory precedes any authorized cache writes.
    preparer = runpy.run_path(str(ROOT / "scripts/prepare_hosted_flutter.py"))
    return preparer["verify_materialized"](SDK, allow_build_state=allow_build_state)


def prepare_tool_state():
    # Called only after authenticating the full original SDK inventory. Never
    # replace an existing file, link or generated directory from another run.
    parent = SDK_TOOL_MOUNT.parent
    info = parent.lstat()
    require(parent.resolve(strict=True) == parent and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and not info.st_mode & 0o022, "SDK_TOOL_PARENT")
    H.private_directory(SDK_TOOL_STATE)
    H.private_directory(SDK_TOOL_MOUNT)


def tool_state_binding():
    # Generated package maps are build state, not a new SDK executable or
    # public artifact. Record only bounded relative names, sizes and hashes.
    records, pending, entries, total = {}, [SDK_TOOL_STATE], 0, 0
    for root in (SDK_TOOL_STATE, SDK_TOOL_MOUNT):
        info = root.lstat()
        require(root.resolve(strict=True) == root and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "SDK_TOOL_STATE_ROOT")
    require(not any(SDK_TOOL_MOUNT.iterdir()), "SDK_TOOL_MOUNT_NOT_EMPTY")
    while pending:
        with os.scandir(pending.pop()) as directory:
            for entry in directory:
                entries += 1
                require(entries <= 64, "SDK_TOOL_STATE_BOUND")
                path = Path(entry.path)
                relative = path.relative_to(SDK_TOOL_STATE).as_posix()
                require(len(relative) <= 256 and len(path.relative_to(SDK_TOOL_STATE).parts) <= 4
                        and re.fullmatch(r"[A-Za-z0-9._/-]+", relative), "SDK_TOOL_STATE_PATH")
                info = entry.stat(follow_symlinks=False)
                require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "SDK_TOOL_STATE_TYPE")
                require(info.st_uid == os.getuid() and not info.st_mode & 0o022, "SDK_TOOL_STATE_OWNER")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                            and not info.st_mode & 0o111, "SDK_TOOL_STATE_TYPE")
                    raw = H.read(path, 2 * 1024**2)
                    total += len(raw)
                    require(total <= 16 * 1024**2, "SDK_TOOL_STATE_BOUND")
                    records[relative] = dict(bytes=len(raw), sha256=H.sha(raw))
    return dict(schema=1, kind="hosted-flutter-tool-state", files=records, bytes=total,
                stored_outside_sdk=True, original_mountpoint_empty=True)


def system_tools():
    require(WHICH.resolve(strict=True) == WHICH, "CANONICAL_WHICH_REQUIRED")
    info = WHICH.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
            and not info.st_mode & 0o022 and info.st_mode & 0o111, "UNSAFE_WHICH")
    raw = H.read(WHICH, 32768)
    return dict(schema=1, kind="hosted-overmorrow-system-tools", which=dict(
        path=str(WHICH), bytes=len(raw), sha256=H.sha(raw), sandbox_alias="/tools/which"))


def browser_command(proof, netns):
    require(proof in (PROOF, TABLE_PROOF), "BROWSER_OUTPUT_REQUIRED")
    driver = "smoke_browser.py" if proof == PROOF else "smoke_table_browser.py"
    return ["/usr/bin/python3", "-B", str(HERE / driver), "--stage", str(STAGE),
        "--static-root", str(DEPLOY), "--browser-root", str(H.BROWSER), "--browser-stage", str(H.FIREFOX),
        "--node", str(H.NODE), "--output", str(proof), "--inside", "--host-netns", netns]


def verify_browser_report(value, table=False):
    require(value.get("schema") == 1 and value.get("passed") is True and value.get("phase") == "complete"
        and set(value.get("cleanup", {})) == {"browser_exited", "fixture_exited", "private_profile_removed",
            "normal_browser_stop", "normal_fixture_stop"}
        and all(flag is True for flag in value["cleanup"].values()), "BROWSER_PROOF_FAILED")
    scope, checks = value["scope"], value["checks"]
    require(all(scope.get(key) is True for key in ("actual_overmorrow_ui", "actual_http_bridge",
                "synthetic_weather", "synthetic_air_quality"))
        and all(scope.get(key) is False for key in ("core_executed", "overlay_proven",
                "upstream_origin_proven", "native_mobile_proven")), "BROWSER_SCOPE_CHANGED")
    if table:
        require(value.get("kind") == "overmorrow-synthetic-native-table-contract"
            and scope.get("ordered_table_contract") is True
            and all(scope.get(key) is False for key in
                    ("joined_delivery_proven", "cold_transfer_proven", "origin_acquisition_proven"))
            and checks.get("weather_requests") == checks.get("air_quality_requests") == 2
            and checks.get("exact_current_v3_extractor") is True
            and checks.get("exact_current_v3_observed_products") is True
            and checks.get("actual_pointer_refresh") is True
            and checks.get("ordered_four_weather_five_air_quality_rows") is True,
            "TABLE_PROOF_FAILED")
        phases = value["table_phases"]
        require(len(phases) == 2 and all(row["row_counts"] == {"weather": 4, "air_quality": 5}
            and row["exact_ordered_rows_and_metadata"] is True
            and row["browser_requests_each"] == row["provider_requests_each"] == i
            for i, row in enumerate(phases, 1)), "TABLE_ROWS_OR_REFRESH_CHANGED")
    else:
        require(checks.get("provider_requests") == checks.get("air_quality_provider_requests") == 10
            and all(checks.get(key) is True for key in ("actual_refresh", "weather_failure_and_stale_preserve_air_quality",
                "air_quality_failure_and_stale_preserve_weather", "weather_idle_expiry_without_request",
                "air_quality_idle_expiry_without_request", "existing_aq_detail_without_new_request")), "FULL_UI_PROOF_FAILED")


def proof_removed(proof):
    return not any((proof / name).exists() or (proof / name).is_symlink() for name in PROFILE_DIRS)


def private_directory_identity(info):
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, "BROWSER_DIRECTORY_IDENTITY")
    return info.st_dev, info.st_ino


def prepare_browser_output(proof, owned):
    require(proof in (PROOF, TABLE_PROOF), "BROWSER_OUTPUT_REQUIRED")
    for name in ("", "appdata", "appdata/firefox", "appdata/firefox-esr"):
        path = proof / name
        H.private_directory(path)
        owned.setdefault(proof, {})[name] = private_directory_identity(path.lstat())


def cleanup_empty_browser_output(proof, identities):
    # A source/preflight rejection can precede the browser driver's finally.
    # After confirmed drain, remove only our exact empty bootstrap directories,
    # never browser files, profiles, receipts, unknown entries or symlink targets.
    if not H.DRAIN_CONFIRMED:
        return False
    root_fd = appdata_fd = None
    try:
        require(proof in (PROOF, TABLE_PROOF) and proof.resolve() == proof, "BROWSER_OUTPUT_REQUIRED")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(proof, flags)
        require(private_directory_identity(os.fstat(root_fd)) == identities[""], "BROWSER_DIRECTORY_CHANGED")
        if "appdata" not in identities:
            return True
        try:
            appdata_fd = os.open("appdata", flags, dir_fd=root_fd)
        except FileNotFoundError:
            return True
        require(private_directory_identity(os.fstat(appdata_fd)) == identities["appdata"], "BROWSER_DIRECTORY_CHANGED")
        for name in ("firefox", "firefox-esr"):
            if "appdata/" + name not in identities:
                continue
            try:
                info = os.stat(name, dir_fd=appdata_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            require(private_directory_identity(info) == identities["appdata/" + name], "BROWSER_DIRECTORY_CHANGED")
            os.rmdir(name, dir_fd=appdata_fd)
        # No recursive deletion: any unexpected file leaves cleanup unproven.
        require(private_directory_identity(os.stat("appdata", dir_fd=root_fd, follow_symlinks=False))
                == identities["appdata"], "BROWSER_DIRECTORY_CHANGED")
        os.rmdir("appdata", dir_fd=root_fd)
        return True
    except (OSError, ValueError, KeyError):
        return False  # Preserve the original failure and expose remaining state.
    finally:
        if appdata_fd is not None:
            os.close(appdata_fd)
        if root_fd is not None:
            os.close(root_fd)


def execute(helper, platform):
    H.require_runtime_boundary()
    installed = attempted = success = False
    owned_browser_directories = {}
    phase = "baseline"
    started = time.monotonic()
    netns = os.readlink("/proc/self/ns/net")
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_sig, _frame):
        raise H.Interrupted("HOSTED_OVERMORROW_INTERRUPTED")
    for sig in previous:
        signal.signal(sig, interrupted)
    try:
        baseline = helper.prechecks(platform)
        baseline["kind"] = "hosted-overmorrow-sandbox-baseline"
        H.save("baseline.json", baseline)
        runtime = H.runtime_inventory()
        sdk = sdk_inventory(allow_build_state=True) if H.BOUNDARY is not None else sdk_inventory()
        tools = system_tools()
        H.save("runtime-binding.json", runtime)
        H.save("sdk-binding.json", sdk)
        H.save("system-tools.json", tools)
        if H.BOUNDARY is None:
            H.private_directory(PRIVATE)
            for name in ("config", "cache", "pub-cache"):
                H.private_directory(PRIVATE / name)
            prepare_tool_state()
        H.write(OUTPUT / "passwd", f"runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n".encode())
        H.write(OUTPUT / "group", f"runner:x:{os.getgid()}:\n".encode())
        phase = "policy-install"
        print("Disposable hosted CI: install scoped bwrap setup/denied-capability child profiles; remove only after process drain. No userns sysctl changes.", flush=True)
        installed = True
        helper.process(["/usr/bin/sudo", "-n", "/usr/bin/install", "-o", "root", "-g", "root", "-m", "0600",
                        "--", str(H.PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(["/usr/bin/sudo", "-n", helper.PARSER, "--add", "--skip-cache", str(helper.STAGED)], 10)
        if H.BOUNDARY is not None:
            if H.BOUNDARY.view.cache_sha is None:
                H.BOUNDARY.prepare_cache()
            else:
                H.BOUNDARY.check()
            H.private_directory(PRIVATE)
            for name in ("config", "cache", "pub-cache"):
                H.private_directory(PRIVATE / name)
            prepare_tool_state()
        phase = "public-acquisition"
        H.run("source-stage", ["/usr/bin/python3", "-B", str(HERE / "stage.py"), "--execute", "--destination", str(STAGE)], 270)
        pin = H.document(HERE / "upstream.json")
        verify_phase_inputs(helper, pin)
        require(system_tools() == tools, "SYSTEM_TOOLS_CHANGED")
        preflight("acquire")
        H.run("pub-acquisition", sandbox(flutter_command("dependencies"), mode="acquire"), 600,
              env=environment(), memory=FLUTTER_MEMORY)
        H.save("tool-state-acquired.json", tool_state_binding())
        phase = "offline-compilation"
        verify_phase_inputs(helper, pin)
        preflight("compile")
        H.run("pub-offline-lock", sandbox(flutter_command("dependencies-offline"), mode="compile"), 180,
              env=environment(), memory=FLUTTER_MEMORY)
        fixture = STAGE / "test/volparossa/fixtures/products.json"
        fixture.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        H.run("test-fixtures", sandbox([str(H.NODE), str(HERE / "test-fixtures.mjs"), str(fixture)], mode="compile"),
              30, env=environment())
        for name, action in (("flutter-tests", "test"), ("flutter-web-build", "build")):
            require(time.monotonic() - started < 2400, "WHOLE_BUILD_DEADLINE")
            verify_phase_inputs(helper, pin)
            raw = H.run(name, sandbox(flutter_command(action), mode="compile"), 900,
                        env=environment(), memory=FLUTTER_MEMORY)
            if action == "test":
                require(re.search(rb"\+" + str(FLUTTER_TEST_COUNT).encode() + rb": All tests passed!", raw),
                        "FLUTTER_TEST_COUNT_CHANGED")
        verify_phase_inputs(helper, pin)
        phase = "static-deploy"
        # Mode tightening applies solely to this new generated public build.
        for path in (STAGE / "build/web").rglob("*"):
            require(not path.is_symlink() and path.stat().st_uid == os.getuid(), "BUILT_ASSET_TYPE")
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o022)
        raw = H.run("static-deploy", ["/usr/bin/python3", "-B", str(HERE / "deploy.py"),
            "--execute", "--stage", str(STAGE), "--destination", str(DEPLOY)], 60)
        deployment = json.loads(raw, object_pairs_hook=H.unique)
        H.save("deployment.json", deployment)
        phase = "firefox-staging"
        if H.BOUNDARY is None:
            H.run("firefox-stage", ["/usr/bin/python3", "-B", str(H.BROWSER / "scripts/stage_firefox.py"),
                "--firefox", str(H.RUNTIME / "firefox/firefox-esr"), "--output", str(H.FIREFOX),
                "--expected-version", H.FIREFOX_VERSION, "--expected-source-stamp", H.FIREFOX_SOURCE_STAMP,
                "--without-extensions"], 90)
        elif not H.BOUNDARY.firefox_ready:
            H.BOUNDARY.stage_firefox()
        files = H.document(H.RUNTIME / "provenance.json")["files"]
        H.verify_firefox_copy(files)
        reports = {}
        for proof, table in ((PROOF, False), (TABLE_PROOF, True)):
            phase = "synthetic-table-browser" if table else "synthetic-browser"
            prepare_browser_output(proof, owned_browser_directories)
            preflight("browser", proof)
            H.run("table-browser-smoke" if table else "browser-smoke",
                sandbox(browser_command(proof, netns), mode="browser", proof=proof), 180,
                env=H.BASE_ENV, memory=2 * GIB)
            value = H.document(proof / "report.json")
            verify_browser_report(value, table)
            reports["table" if table else "ui"] = dict(sha256=H.sha(H.read(proof / "report.json")), source=value["source"])
        require(H.runtime_inventory() == runtime, "RUNTIME_CHANGED_DURING_BUILD")
        H.verify_firefox_copy(files)
        sdk_after = verify_phase_inputs(helper, pin)
        tool_state = tool_state_binding()
        H.save("tool-state-final.json", tool_state)
        require(system_tools() == tools, "SYSTEM_TOOLS_CHANGED")
        H.save("build.json", dict(schema=1, kind="hosted-overmorrow-build", weather_commit=os.environ["GITHUB_SHA"],
            browser_commit=H.BROWSER_COMMIT, upstream_commit=pin["commit"], lock_sha256=pin["pubspec_lock_sha256"],
            flutter_commit=pin["flutter_commit"], sdk_materialization=sdk, sdk_final_binding=sdk_after,
            system_tools=tools,
            tool_state=tool_state,
            sdk_executed_in_disposable_sandbox=True, runtime=runtime, reports=reports,
            deployment_sha256=H.sha(H.read(OUTPUT / "deployment.json")), flutter_tests=FLUTTER_TEST_COUNT,
            compiled_networkless=True, locked_dependencies=True, actual_synthetic_ui=True,
            actual_synthetic_tables=True, core_delivery=False, weather_origin=False, native_mobile=False,
            copyright_notices_preserved=True))
        phase, success = "complete", True
    except BaseException as error:
        H.save("failure.json", dict(schema=1, phase=phase, category=type(error).__name__,
            code=str(error) if isinstance(error, (ValueError, H.Interrupted)) else "HOSTED_OVERMORROW_FAILURE"))
        raise
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            empty_cleanup = {proof: cleanup_empty_browser_output(proof, identities)
                             for proof, identities in owned_browser_directories.items()}
            outer = dict(process_drain_confirmed=H.DRAIN_CONFIRMED,
                private_profile_removed=empty_cleanup.get(PROOF, True) and proof_removed(PROOF),
                private_table_profile_removed=empty_cleanup.get(TABLE_PROOF, True) and proof_removed(TABLE_PROOF),
                host_netns_unchanged=os.readlink("/proc/self/ns/net") == netns)
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED
            cleaning = helper.cleanup(platform, attempted, installed)
            cleaning["kind"] = "hosted-overmorrow-sandbox-cleanup"
            H.save("cleanup.json", cleaning)
            H.save("steps.json", dict(schema=1, steps=H.LOGS))
            H.save("result.json", dict(schema=1, kind="hosted-overmorrow-build-and-synthetic-ui", phase=phase,
                success=success and cleaning["complete"] and all(outer.values()),
                weather_commit=os.environ["GITHUB_SHA"], browser_commit=H.BROWSER_COMMIT,
                outer_cleanup=outer, policy_cleanup_complete=cleaning["complete"],
                driver="existing-overmorrow-browser-and-table-inside-under-hosted-empty-root-wrapper",
                synthetic_weather=True, synthetic_air_quality=True, origin_acquisition=False,
                core_delivery=False, native_mobile=False, production_authority=False))
            require(cleaning["complete"] and (not success or all(outer.values())), "CLEANUP_UNPROVEN")
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    require(len(sys.argv) == 1, "NO_ARGUMENTS_ALLOWED")
    os.umask(0o077)
    helper, platform = guards(os.environ)
    H.private_directory(OUTPUT)
    execute(helper, platform)


if __name__ == "__main__":
    try:
        main()
    except (H.Interrupted, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("HOSTED_OVERMORROW_CI_FAILED; inspect closed diagnostics", file=sys.stderr)
        sys.exit(1)
