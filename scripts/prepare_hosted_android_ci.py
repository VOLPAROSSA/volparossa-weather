#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Disposable hosted Android acquisition, offline APK rebuild and installed trial.

The first Gradle build executes with public dependency acquisition enabled.
Generated verification metadata is captured consistency evidence, not prior
review. Only the subsequent networkless rebuild supplies the tested debug APK.
No release signing, mobile core, live weather or physical-device proof.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import runpy
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_native_hosted", ROOT / "scripts/prepare_hosted_overmorrow_ci.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
H, require = W.H, W.require
spec = importlib.util.spec_from_file_location("_native_diagnostics", ROOT / "scripts/prepare_hosted_android_diagnostics.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
OUTPUT = ROOT / "build/hosted-android-ci"
PRIVATE = OUTPUT / "private"
STAGE = ROOT / "build/overmorrow-hosted-android-ci"
PROOF = ROOT / "build/overmorrow-hosted-android-proof"
INPUTS = ROOT / "build/hosted-android-inputs"
SDK = W.SDK
WORKFLOW = "Build hosted Android client"
JAVA = Path("/usr/lib/jvm/java-17-openjdk-amd64")
JAVA_LAUNCHER_LIMIT = 4 * 1024**2
ANDROID = Path("/tools/android-inputs/sdk")
SERIAL = "emulator-5554"
PACKAGE = "org.volparossa.weather.trial"
APK = STAGE / "build/app/outputs/flutter-apk/app-debug.apk"
GRADLE_STATE = (".gradle", "build", ".kotlin")
GIB = 1024**3
MEMORY = 3 * GIB
APP_MEMORY = 4 * GIB
APP_CPU_SECONDS = 1800
# The app Gradle JVM remains resident while Flutter starts its own compiler.
# Lower only the two app-build commands, not the shared aggregate RSS guard.
# Gradle 8.13 gives these CLI properties precedence over staged properties.
APP_GRADLE_WORKERS = 1
APP_GRADLE_JVM_ARGS = ("-Xmx1024m", "-XX:MaxMetaspaceSize=512m",
    "-XX:ReservedCodeCacheSize=128m", "-Dfile.encoding=UTF-8")
# Exact AGP 8.11.1 sources: IntegerOption.R8_THREAD_POOL_SIZE feeds
# R8D8ThreadPoolBuildService; DexMergingTask uses it for mergeExtDex's single
# bucket. Gradle --max-workers does not constrain this internal work-stealing
# pool. Source: https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/8.11.1/gradle-8.11.1-sources.jar
# This is a scoped concurrency candidate, not proof that the build fits.
APP_D8_THREADS = 1
H.OUTPUT, H.PRIVATE, H.STAGE, H.PROOF = OUTPUT, PRIVATE, STAGE, PROOF
W.OUTPUT, W.PRIVATE, W.STAGE = OUTPUT, PRIVATE, STAGE
W.SDK_TOOL_STATE = PRIVATE / "flutter-tool-state"


def environment():
    return dict(W.environment(), JAVA_HOME=str(JAVA), ANDROID_HOME=str(ANDROID), ANDROID_SDK_ROOT=str(ANDROID),
        ANDROID_USER_HOME="/state/android-home", ANDROID_AVD_HOME="/state/avd",
        GRADLE_USER_HOME="/state/gradle-home", JAVA_TOOL_OPTIONS="-Duser.home=/state/java-home",
        PATH=f"{SDK}/bin:{JAVA}/bin:{ANDROID}/platform-tools:/tools:/usr/bin:/bin",
        ANDROID_EMULATOR_USE_SYSTEM_LIBS="1", QT_QPA_PLATFORM="offscreen",
        NODE_OPTIONS="--max-old-space-size=256", GRADLE_OPTS="-Dorg.gradle.daemon=false")


def guards(env):
    required = dict(GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_REPOSITORY="VOLPAROSSA/volparossa-weather", GITHUB_WORKFLOW=WORKFLOW)
    require(os.geteuid() == os.getuid() != 0 and all(env.get(k) == v for k, v in required.items()), "DISPOSABLE_HOSTED_ONLY")
    require(env.get("GITHUB_WORKSPACE") == str(ROOT) and re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")), "EXACT_SOURCE")
    helper = H.policy_helper()
    platform = runpy.run_path(str(ROOT / "scripts/prepare_hosted_decoder.py"))
    require(platform["platform"]()["os_id"] == "ubuntu", "UBUNTU_24_REQUIRED")
    _, head = helper.process(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"], 10)
    require(head.decode().strip() == env["GITHUB_SHA"], "SOURCE_HEAD")
    helper.process(["/usr/bin/git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--"], 10)
    require(H.sha(H.read(H.PROFILE)) == H.PROFILE_SHA, "POLICY_CHANGED")
    for path in (ROOT, ROOT / "build", SDK, INPUTS, H.RUNTIME):
        info = path.lstat()
        require(path.resolve() == path and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022, "OWNED_INPUT_REQUIRED")
    kvm = Path("/dev/kvm").stat()
    require(stat.S_ISCHR(kvm.st_mode) and os.access("/dev/kvm", os.R_OK | os.W_OK), "KVM_REQUIRED_NO_TCG")
    require(H.available_memory() >= APP_MEMORY + 2 * GIB, "HOST_MEMORY_RESERVE")
    return helper, platform


def sandbox(command, mode):
    require(mode in ("acquire", "compile", "emulator"), "NATIVE_SANDBOX_MODE")
    argv = W.sandbox(command, mode="acquire" if mode == "acquire" else "compile")
    index = argv.index("--remount-ro")
    # Exact read-only distro Java configuration is required by Ubuntu's Java
    # symlinks; this never exposes the runner's home, credentials or whole /etc.
    extra = ["--ro-bind", str(INPUTS), "/tools/android-inputs",
        "--ro-bind", "/etc/java-17-openjdk", "/etc/java-17-openjdk"]
    if mode != "acquire":
        extra += ["--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs"]
    for name in GRADLE_STATE:
        extra += ["--bind", str(PRIVATE / ("flutter-gradle-" + name.lstrip("."))),
            str(SDK / "packages/flutter_tools/gradle" / name)]
    if mode == "emulator":
        extra += ["--dev-bind", "/dev/kvm", "/dev/kvm", "--bind", str(PROOF), str(PROOF)]
    argv[index:index] = extra
    return argv


PROBE = r'''
import json,os,socket,stat,sys
from pathlib import Path
s=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
mode=sys.argv[1]; online=mode=='acquire'
assert os.getuid()!=0 and int(s['CapEff'],16)==int(s['CapPrm'],16)==0 and int(s['NoNewPrivs'])==1
assert 'volparossa_ci_weather_clients_child' in Path('/proc/self/attr/current').read_text()
assert (os.readlink('/proc/self/ns/net')==sys.argv[2])==online
if not online: assert [n for _,n in socket.if_nameindex()]==['lo']
assert not Path('/root').exists() and not Path('/run').exists()
assert Path('/etc/resolv.conf').exists()==online
assert not any('TOKEN' in k or 'PROXY' in k or 'AUTH' in k for k in os.environ)
assert os.statvfs('/tools/android-inputs').f_flag & os.ST_RDONLY
assert os.statvfs(sys.argv[3]+'/packages/flutter_tools/gradle/src').f_flag & os.ST_RDONLY
assert os.statvfs(sys.argv[3]+'/.git').f_flag & os.ST_RDONLY
assert Path('/dev/kvm').exists()==(mode=='emulator')
print(json.dumps(dict(schema=1,mode=mode,unprivileged=True,capabilities_zero=True,
 no_new_privileges=True,source_read_only=True,toolchain_read_only=True,
 isolated_network=not online,public_acquisition=online,kvm_only=mode=='emulator')))
'''


def preflight(mode, netns):
    raw = H.run("preflight-" + mode, sandbox(["/usr/bin/python3", "-I", "-c", PROBE, mode, netns, str(SDK)], mode),
        20, env=environment(), memory=MEMORY)
    value = json.loads(raw, object_pairs_hook=H.unique)
    require(value == dict(schema=1, mode=mode, unprivileged=True, capabilities_zero=True,
        no_new_privileges=True, source_read_only=True, toolchain_read_only=True,
        isolated_network=mode != "acquire", public_acquisition=mode == "acquire", kvm_only=mode == "emulator"), "PREFLIGHT")
    H.save("preflight-" + mode + ".json", value)


def flutter(*args):
    return [str(SDK / "bin/flutter"), "--no-version-check", "--suppress-analytics", *args]


def app_gradle_resources():
    """Configured command limits, not observations of JVM or build success."""
    return dict(schema=2, kind="hosted-android-gradle-configured-limits",
        scope="acquisition-and-offline-app-build", max_workers=APP_GRADLE_WORKERS,
        d8_thread_pool_size=APP_D8_THREADS,
        cpu_soft_seconds=APP_CPU_SECONDS, cpu_hard_seconds=APP_CPU_SECONDS,
        jvm_args=list(APP_GRADLE_JVM_ARGS), child_rss_limit_bytes=APP_MEMORY,
        host_reserve_bytes=2 * GIB, launch_min_available_bytes=APP_MEMORY + 2 * GIB,
        step_timeout_seconds=900, runtime_measurement=False)


def gradle(acquire):
    # Equivalent properties emitted by pinned Flutter's Gradle builder. Config
    # generation itself is done first by maintained flutter --config-only.
    defines = ",".join(base64.b64encode(s.encode()).decode() for s in
        ("VOLPAROSSA_WEATHER=true", "VOLPAROSSA_CORE_ORIGIN=http://127.0.0.1:43210"))
    return [str(STAGE / "android/gradlew"), "-p", str(STAGE / "android"), "--no-daemon",
        f"--max-workers={APP_GRADLE_WORKERS}", "-Dorg.gradle.jvmargs=" + " ".join(APP_GRADLE_JVM_ARGS), "--console=plain",
        f"-Pandroid.r8.threadPoolSize={APP_D8_THREADS}",
        "--init-script", str(ROOT / "scripts/hosted-android-repositories.gradle"),
        *( ["--write-verification-metadata", "sha256"] if acquire else ["--offline", "--dependency-verification", "strict", "clean"]),
        "assembleDebug", "-Ptarget-platform=android-x64", "-Ptarget=" + str(STAGE / "lib/volparossa_native_trial.dart"),
        "-Pbase-application-name=android.app.Application", "-Pdart-defines=" + defines,
        "-Pdart-obfuscation=false", "-Ptrack-widget-creation=true", "-Ptree-shake-icons=false"]


def repository_fixture_command():
    return ["/state/repository-fixture/gradlew", "-p", "/state/repository-fixture", "--offline", "--no-daemon",
        "--max-workers=2", "--console=plain", "--init-script", str(ROOT / "scripts/hosted-android-repositories.gradle"),
        "verifyRepositoryContract"]


def run_app_gradle(acquire):
    """The larger finite RSS profile applies only to these two fixed steps."""
    require(type(acquire) is bool, "NATIVE_APP_BUILD_SCOPE")
    # The single outer prlimit lowers the new app process and its descendants,
    # not this wrapper. Never attempt a late raise inside an already limited
    # namespace, require privilege, or retry an inherited hard-limit failure.
    inherited_hard = resource.getrlimit(resource.RLIMIT_CPU)[1]
    require(inherited_hard == resource.RLIM_INFINITY or inherited_hard >= APP_CPU_SECONDS,
        "NATIVE_APP_CPU_PARENT_LIMIT")
    name, mode = ("android-acquisition-build", "acquire") if acquire else ("android-offline-build", "compile")
    observation = None
    try:
        observation = D.Capture(PRIVATE, STAGE, OUTPUT, name)
    except H.Interrupted:
        raise
    except Exception:
        # Optional diagnosis cannot replace resource admission or build errors.
        pass
    first_log = len(H.LOGS)
    try:
        return H.run(name, gradle_sandbox(gradle(acquire), mode), 900,
            env=environment(), cwd=STAGE / "android", memory=APP_MEMORY, memory_categories=True, java_cpu=True)
    finally:
        if observation is not None:
            try:
                records = [record for record in H.LOGS[first_log:] if record["name"] == name]
                cpu = records[0].get("java_cpu") if len(records) == 1 else None
                H.save(name + "-diagnostics.json", observation.finish(drained=H.DRAIN_CONFIRMED, java_cpu=cpu))
            except H.Interrupted:
                raise
            except Exception:
                # Missing receipt remains unknown. Preserve the original build
                # failure and the shared helper's conservative cleanup result.
                pass


def gradle_sandbox(command, mode):
    """Only these fixed Gradle invocations need the bounded 4096-descriptor profile."""
    require((mode == "acquire" and command == gradle(True)) or
        (mode == "compile" and command in (gradle(False), repository_fixture_command())),
        "NATIVE_GRADLE_RESOURCE_SCOPE")
    argv = sandbox(command, mode)
    require(argv[:6] == ["/usr/bin/prlimit", "--core=0", "--cpu=900", "--nofile=1024", "--", "/usr/bin/bwrap"],
        "NATIVE_GRADLE_RESOURCE_TEMPLATE")
    # This changes the new child only, never the caller/runner limits or the
    # shared Flutter/web/emulator/preflight sandbox's 1024-descriptor profile.
    argv[3] = "--nofile=4096:4096"
    if command in (gradle(True), gradle(False)):
        # Per-process CPU time can exceed wall time with multiple JVM threads.
        # Only these two bounded app builds receive this controlled experiment;
        # the observed ~903 s samples did not themselves prove a kill cause.
        argv[2] = f"--cpu={APP_CPU_SECONDS}:{APP_CPU_SECONDS}"
    return argv


def repository_fixture_report(raw):
    require(type(raw) is bytes and len(raw) <= H.LIMIT, "REPOSITORY_FIXTURE_OUTPUT_BOUND")
    prefix = b"NATIVE_REPOSITORY_FIXTURE "
    records = [line[len(prefix):] for line in raw.splitlines() if line.startswith(prefix)]
    require(len(records) == 1 and len(records[0]) <= 1024, "REPOSITORY_FIXTURE_RECEIPT")
    value = json.loads(records[0], object_pairs_hook=H.unique)
    expected = dict(schema=2, kind="gradle-repository-contract", gradle_version="8.13", plugin_wrappers=3,
        rejected=["artifact-url", "unadmitted", "http", "file", "ivy", "flatdir"], networkless=True, external_dependencies=False,
        nofile_soft=4096, nofile_hard=4096)
    require(value == expected and type(value.get("schema")) is int and type(value.get("plugin_wrappers")) is int
        and type(value.get("nofile_soft")) is int and type(value.get("nofile_hard")) is int
        and type(value.get("networkless")) is bool and type(value.get("external_dependencies")) is bool,
        "REPOSITORY_FIXTURE_PROOF")
    return value


def repository_fixture():
    """Hosted-only: one offline Gradle invocation with no external dependencies."""
    target = PRIVATE / "repository-fixture"
    for path in (target, target / "gradle", target / "gradle/wrapper"):
        H.private_directory(path)
    fixture = ROOT / "tests/fixtures/hosted-android-repositories"
    files = {name: H.read(fixture / name) for name in ("settings.gradle", "build.gradle", "gradle.properties")}
    wrapper = SDK / "bin/cache/artifacts/gradle_wrapper"
    files.update({name: H.read(wrapper / name) for name in ("gradlew", "gradle/wrapper/gradle-wrapper.jar")})
    # Reuse the native preparer's exact local distribution URL and published
    # checksum. No Gradle/npm/SDK download or code runs on the developer host.
    properties = H.read(STAGE / "android/gradle/wrapper/gradle-wrapper.properties")
    native = runpy.run_path(str(W.HERE / "prepare_native_android.py"))
    for key, expected in (("distributionUrl", native["GRADLE_URL"]), ("distributionSha256Sum", native["GRADLE_SHA"])):
        entries = [line for line in properties.decode("ascii").splitlines() if line.split("=", 1)[0].strip() == key]
        require(entries == [key + "=" + expected], "REPOSITORY_FIXTURE_DISTRIBUTION")
    files["gradle/wrapper/gradle-wrapper.properties"] = properties
    for name, raw in files.items():
        H.write(target / name, raw)
    (target / "gradlew").chmod(0o700)
    for name in ("gradlew", "gradle/wrapper/gradle-wrapper.jar"):
        require(H.digest(target / name) == H.digest(wrapper / name), "REPOSITORY_FIXTURE_WRAPPER_CHANGED")
    raw = H.run("gradle-repository-contract", gradle_sandbox(repository_fixture_command(), "compile"),
        120, env=environment(), memory=MEMORY)
    result = repository_fixture_report(raw)
    H.save("repository-contract.json", dict(result, fixture_files={name: H.sha(raw) for name, raw in files.items()},
        guard_sha256=H.sha(H.read(ROOT / "scripts/hosted-android-repositories.gradle"))))


def verification_metadata():
    path = STAGE / "android/gradle/verification-metadata.xml"
    raw = H.read(path, 4 * 1024**2)
    require(b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw, "GRADLE_METADATA_XML")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    hashes = [e.attrib.get("value", "") for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "sha256"]
    require(1 <= len(hashes) <= 30000 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes), "GRADLE_METADATA_HASHES")
    # Preserve original acquisition metadata, not just regenerated build output.
    return dict(schema=1, kind="captured-gradle-verification", bytes=len(raw), sha256=H.sha(raw),
        sha256_entries=len(hashes), captured_after_execution=True, independently_reviewed=False)


def apt_java_digest():
    """Only the fixed distro launcher, not the runner-owned artifact policy."""
    path = JAVA / "bin/java"
    require(path.resolve() == path, "JAVA_TOOL_PATH")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
            and before.st_mode & 0o111 and not before.st_mode & 0o7022
            and 0 < before.st_size <= JAVA_LAUNCHER_LIMIT, "JAVA_TOOL")
        digest, size = hashlib.sha256(), 0
        while True:
            block = os.read(fd, min(65536, JAVA_LAUNCHER_LIMIT + 1 - size))
            if not block:
                break
            size += len(block)
            require(size <= JAVA_LAUNCHER_LIMIT, "JAVA_TOOL_BOUND")
            digest.update(block)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
            "st_size", "st_mtime_ns", "st_ctime_ns")
        require(size == before.st_size and all(getattr(before, k) == getattr(after, k) for k in fields),
            "JAVA_TOOL_CHANGED")
        return dict(bytes=size, sha256=digest.hexdigest())
    finally:
        os.close(fd)


def java_provenance(helper):
    executable = apt_java_digest()
    _, version = helper.process([str(JAVA / "bin/java"), "-version"], 10)
    require(b'"17.' in version and len(version) < 8192, "JAVA_17_REQUIRED")
    require(apt_java_digest() == executable, "JAVA_TOOL_CHANGED")
    return dict(path=str(JAVA), executable=executable, version=version.decode().strip(),
        authority="signed-disposable-apt-package-inventory", independently_reproducible=False)


def validate_report(value):
    require(value.get("schema") == 1 and value.get("kind") == "overmorrow-installed-android-synthetic-trial"
        and value.get("passed") is True and value.get("phase") == "complete" and value.get("package") == PACKAGE,
        "INSTALLED_APP_PROOF")
    scope = value.get("scope", {})
    require(all(scope.get(k) is True for k in ("installed_android_app", "mounted_widget_tables", "real_adb_interaction",
        "synthetic_weather", "synthetic_air_quality")) and all(scope.get(k) is False for k in
        ("pixel_visibility_proven", "core_executed", "overlay_proven", "physical_device", "production_authority")), "INSTALLED_APP_SCOPE")
    require(value.get("observations", {}).get("requests") == {"weather": 3, "air_quality": 3}
        and value.get("cleanup") == dict(app_stopped=True, forward_removed=True, vm_closed=True), "INSTALLED_APP_COMPLETION")
    require(value.get("checks") == dict(initial_exact_native_rows=True, actual_tap_refresh_and_missing_values=True,
        real_android_background_resume=True, expired_products_hidden_without_network_refresh=True), "INSTALLED_APP_CHECKS")
    for phase in ("initial", "refresh"):
        products = value["observations"].get(phase, {})
        require(set(products) == {"weather", "air_quality"}, "INSTALLED_PRODUCT_PAIR")
        for key, rows in (("weather", 4), ("air_quality", 5)):
            item = products[key]
            require(set(item) == {"rows", "table_sha256", "product_sha256"} and type(item["rows"]) is int
                and item["rows"] == rows and all(re.fullmatch(r"[0-9a-f]{64}", item[k]) for k in
                ("table_sha256", "product_sha256")), "INSTALLED_PRODUCT_BINDING")


def native_sources(expected=None):
    raw = H.read(STAGE / "volparossa-native-profile.json")
    value = json.loads(raw, object_pairs_hook=H.unique)
    require(value.get("kind") == "overmorrow-native-android-trial-profile" and value.get("package") == PACKAGE
        and value.get("target") == "lib/volparossa_native_trial.dart"
        and value.get("origin") == "http://127.0.0.1:43210", "NATIVE_PROFILE")
    files = value["source_after"]
    require(type(files) is dict and 1 <= len(files) <= 16, "NATIVE_SOURCE_COUNT")
    for name, digest in files.items():
        require(re.fullmatch(r"(?:android|lib)/[A-Za-z0-9._/-]{1,180}", name) and ".." not in name.split("/")
            and re.fullmatch(r"[0-9a-f]{64}", digest), "NATIVE_SOURCE_NAME")
        require(H.sha(H.read(STAGE / name)) == digest, "NATIVE_SOURCE_CHANGED")
    overlay = W.HERE / "overlay"
    overlays = {}
    for path in overlay.rglob("*"):
        require(not path.is_symlink(), "OVERLAY_LINK")
        if path.is_file():
            relative = path.relative_to(overlay).as_posix()
            require(H.digest(path) == H.digest(STAGE / relative), "SHARED_OVERLAY_CHANGED")
            overlays[relative] = H.digest(path)
    binding = dict(profile_sha256=H.sha(raw), sources=files, shared_overlay=overlays)
    require(expected is None or binding == expected, "NATIVE_SOURCE_BINDING_CHANGED")
    return binding


def drain_children(children):
    """Reap each exact child even if another cleanup fails; no process search."""
    drained = True
    for child in reversed(children):
        try:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            drained = drained and child.poll() is not None
        except (OSError, subprocess.SubprocessError):
            drained = False
        finally:
            for pipe in (child.stdin, child.stdout):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        drained = False
    return drained


def no_guest_egress_routes(raw):
    require(len(raw) <= 65536, "GUEST_ROUTE_OUTPUT_BOUND")
    text = raw.decode("ascii")
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        # Connected routes matter too: 10.0.2.2 is reachable without a default
        # route on the emulator's normal 10.0.2.0/24 guest network. Only direct
        # loopback routes are admitted, in every IPv4/IPv6 table.
        if (any(w in ("default", "0.0.0.0/0", "::/0", "via", "nexthop") for w in words)
                or words.count("dev") != 1 or words.index("dev") + 1 >= len(words)
                or words[words.index("dev") + 1] != "lo"):
            return False
    return True


def execute(helper, platform):
    installed = attempted = success = False
    phase, netns = "baseline", os.readlink("/proc/self/ns/net")
    prior = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_s, _f):
        raise H.Interrupted("HOSTED_ANDROID_INTERRUPTED")
    for s in prior:
        signal.signal(s, interrupted)
    try:
        H.save("baseline.json", helper.prechecks(platform))
        runtime, sdk = H.runtime_inventory(), W.sdk_inventory()
        android = runpy.run_path(str(ROOT / "scripts/prepare_hosted_android.py"))["verify"](INPUTS)
        H.save("toolchain.json", dict(schema=1, android=android, flutter=sdk, runtime=runtime, java=java_provenance(helper)))
        H.private_directory(PRIVATE)
        for name in ("config", "cache", "pub-cache", "android-home", "avd", "gradle-home", "java-home"):
            H.private_directory(PRIVATE / name)
        W.prepare_tool_state()
        for name in GRADLE_STATE:
            H.private_directory(PRIVATE / ("flutter-gradle-" + name.lstrip(".")))
            H.private_directory(SDK / "packages/flutter_tools/gradle" / name)
        H.write(OUTPUT / "passwd", f"runner:x:{os.getuid()}:{os.getgid()}:CI:/home/runner:/bin/false\n".encode())
        H.write(OUTPUT / "group", f"runner:x:{os.getgid()}:\n".encode())
        phase = "policy-install"
        print("Disposable hosted CI: scoped AppArmor setup/child policy; owned offline emulator; remove policy only after confirmed process drain.", flush=True)
        installed = True
        helper.process(["/usr/bin/sudo", "-n", "/usr/bin/install", "-o", "root", "-g", "root", "-m", "0600", "--", str(H.PROFILE), str(helper.STAGED)], 10)
        helper.staged_owned(platform)
        attempted = True
        helper.process(["/usr/bin/sudo", "-n", helper.PARSER, "--add", "--skip-cache", str(helper.STAGED)], 10)
        phase = "stage"
        H.run("source-stage", ["/usr/bin/python3", "-B", str(W.HERE / "stage.py"), "--execute", "--destination", str(STAGE)], 270)
        H.run("native-stage", ["/usr/bin/python3", "-B", str(W.HERE / "prepare_native_android.py"), "--stage", str(STAGE), "--execute"], 30)
        native = native_sources()
        H.save("native-source.json", native)
        pin = H.document(W.HERE / "upstream.json")
        W.verify_phase_inputs(helper, pin)
        phase = "offline-contract-tests"
        preflight("compile", netns)
        H.run("native-contract-tests", sandbox([str(H.NODE), "--test", str(W.HERE / "test-native-android.mjs")], "compile"),
            60, env=environment(), memory=MEMORY)
        phase = "offline-repository-contract"
        repository_fixture()
        phase = "public-acquisition-build"
        preflight("acquire", netns)
        H.run("pub-acquisition", sandbox(flutter("pub", "get", "--enforce-lockfile"), "acquire"), 600, env=environment(), memory=MEMORY)
        H.run("flutter-android-config", sandbox(flutter("build", "apk", "--debug", "--config-only", "--no-pub",
            "--target-platform", "android-x64", "--target", "lib/volparossa_native_trial.dart"), "acquire"), 180, env=environment(), memory=MEMORY)
        # This wrapper was supplied by the reviewed Flutter archive, not fetched
        # by Gradle. Properties were separately pinned by the native preparer.
        require(H.digest(STAGE / "android/gradle/wrapper/gradle-wrapper.jar") ==
            H.digest(SDK / "bin/cache/artifacts/gradle_wrapper/gradle/wrapper/gradle-wrapper.jar"), "WRAPPER_CHANGED")
        H.save("gradle-resources.json", app_gradle_resources())
        run_app_gradle(True)
        metadata = verification_metadata()
        H.save("dependency-capture.json", metadata)
        H.save("acquisition-apk.json", dict(schema=1, artifact=H.digest(APK), network_enabled_build=True, production_authority=False))
        phase = "offline-rebuild"
        native_sources(native)
        W.verify_phase_inputs(helper, pin)
        H.run("pub-offline-lock", sandbox(flutter("pub", "get", "--offline", "--enforce-lockfile"), "compile"), 180, env=environment(), memory=MEMORY)
        # Gradle clean deletes only its configured disposable staged build tree.
        # Original acquisition hashes/logs remain outside it in OUTPUT.
        run_app_gradle(False)
        require(verification_metadata() == metadata, "DEPENDENCY_METADATA_CHANGED")
        native_sources(native)
        W.verify_phase_inputs(helper, pin)
        apk = H.digest(APK)
        H.save("offline-apk.json", dict(schema=1, artifact=apk, compiled_networkless=True,
            dependency_checksums="strict-captured-not-prior-reviewed", debug_signed=True, production_authority=False))
        phase = "installed-emulator-trial"
        H.private_directory(PROOF)
        preflight("emulator", netns)
        H.run("installed-android-trial", sandbox(["/usr/bin/python3", "-B", str(Path(__file__)), "--inside"], "emulator"),
            520, env=dict(environment(), VOLPAROSSA_TEST_HOST_NETNS=netns), memory=MEMORY)
        original = H.document(PROOF / "report.json")
        validate_report(original)
        H.save("build.json", dict(schema=1, kind="hosted-android-debug-trial", source_commit=os.environ["GITHUB_SHA"],
            apk=apk, runtime=runtime, sdk=sdk, android=android, native_sources=native, dependencies=metadata,
            gradle_configured_limits=app_gradle_resources(),
            installed_report_sha256=H.sha(H.read(PROOF / "report.json")), actual_installed_app=True,
            acquisition_build_network_enabled=True, final_build_networkless=True, emulator_networkless=True,
            core_delivery=False, weather_origin=False, release_authority=False))
        phase, success = "complete", True
    except BaseException as error:
        H.save("failure.json", dict(schema=1, phase=phase, category=type(error).__name__,
            code=str(error) if isinstance(error, (ValueError, H.Interrupted)) else "HOSTED_ANDROID_FAILURE"))
        raise
    finally:
        for s in prior:
            signal.signal(s, signal.SIG_IGN)
        try:
            helper.DRAIN_CONFIRMED = helper.DRAIN_CONFIRMED and H.DRAIN_CONFIRMED
            cleanup = helper.cleanup(platform, attempted, installed)
            H.save("cleanup.json", cleanup)
            H.save("steps.json", dict(schema=1, steps=H.LOGS))
            unchanged = os.readlink("/proc/self/ns/net") == netns
            H.save("result.json", dict(schema=1, kind="hosted-android-build-and-installed-trial", phase=phase,
                success=success and cleanup["complete"] and H.DRAIN_CONFIRMED and unchanged,
                process_drain_confirmed=H.DRAIN_CONFIRMED, policy_cleanup_complete=cleanup["complete"],
                host_netns_unchanged=unchanged,
                synthetic=True, mobile_core=False, production_authority=False))
            require(cleanup["complete"], "CLEANUP_UNCONFIRMED")
        finally:
            for s, handler in prior.items():
                signal.signal(s, handler)


def inside():
    require(os.getuid() != 0 and "volparossa_ci_weather_clients_child" in Path("/proc/self/attr/current").read_text()
        and [n for _, n in socket.if_nameindex()] == ["lo"] and not Path("/etc/resolv.conf").exists(), "OFFLINE_SANDBOX_ONLY")
    # Explicitly owned children only. All private raw logs/VM authentication
    # material remain under /state, never among uploaded public evidence.
    children, logs = [], []
    prior = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_s, _f):
        raise H.Interrupted("EMULATOR_INTERRUPTED")
    for s in prior:
        signal.signal(s, interrupted)
    stop = time.monotonic() + 480
    adb = str(ANDROID / "platform-tools/adb")
    def spawn(argv, **kwargs):
        pending = []
        handlers = {s: signal.getsignal(s) for s in prior}
        for s in handlers:
            signal.signal(s, lambda number, _frame: pending.append(number))
        try:
            child = subprocess.Popen(argv, **kwargs)
            children.append(child)
        finally:
            for s, handler in handlers.items():
                signal.signal(s, handler)
        if pending:
            raise H.Interrupted("NATIVE_OWNED_SPAWN_INTERRUPTED")
        return child
    def command(argv, seconds=20, data=None):
        require(time.monotonic() < stop, "EMULATOR_DEADLINE")
        end = min(stop, time.monotonic() + seconds)
        child = spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        raw = bytearray()
        try:
            if data:
                child.stdin.write(data)
            child.stdin.close()
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    require(time.monotonic() < end, "EMULATOR_COMMAND_DEADLINE")
                    for key, _ in selector.select(0.1):
                        part = os.read(key.fd, 4096)
                        if not part:
                            selector.unregister(key.fileobj)
                        raw.extend(part)
                        require(len(raw) <= 65536, "EMULATOR_COMMAND_OUTPUT")
            child.wait(timeout=max(0.1, end - time.monotonic()))
            if child.returncode:
                raise subprocess.CalledProcessError(child.returncode, "owned-native-command")
            return bytes(raw)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
            child.stdout.close()
    def start(name, argv):
        log = open("/state/" + name + ".log", "xb")
        logs.append(log)
        child = spawn(argv, stdin=subprocess.PIPE, stdout=log, stderr=log)
        return child
    def adb_command(*args, seconds=20):
        return command([adb, "-s", SERIAL, *args], seconds)
    complete = False
    try:
        command([str(ANDROID / "cmdline-tools/19.0/bin/avdmanager"), "create", "avd", "--name", "volparossa_trial",
            "--package", "system-images;android-36;default;x86_64", "--path", "/state/avd/trial.avd"], 30, b"no\n")
        config = Path("/state/avd/trial.avd/config.ini")
        with config.open("a") as out:
            out.write("\nhw.lcd.width=1080\nhw.lcd.height=1920\nhw.lcd.density=420\nhw.keyboard=yes\n")
        start("adb", [adb, "-L", "tcp:127.0.0.1:5037", "nodaemon", "server"])
        Path("/state/native-fixture").mkdir(mode=0o700)
        fixture = start("fixture", [str(H.NODE), str(W.HERE / "native-android-fixture.mjs"), "--work", "/state/native-fixture"])
        emulator = start("emulator", [str(ANDROID / "emulator/emulator"), "-avd", "volparossa_trial", "-port", "5554",
            "-accel", "on", "-cores", "2", "-memory", "1536", "-no-window", "-no-audio", "-no-snapshot",
            "-no-boot-anim", "-gpu", "swiftshader_indirect", "-no-metrics", "-camera-back", "none", "-camera-front", "none"])
        boot_end = min(stop, time.monotonic() + 180)
        while True:
            require(emulator.poll() is None and fixture.poll() is None and time.monotonic() < boot_end, "EMULATOR_BOOT_FAILED")
            try:
                if adb_command("shell", "getprop", "sys.boot_completed", seconds=3).strip() == b"1":
                    break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
            time.sleep(1)
        require(adb_command("shell", "getprop", "ro.build.version.sdk").strip() == b"36", "ANDROID_API")
        require(adb_command("shell", "getprop", "ro.product.cpu.abi").strip() == b"x86_64", "ANDROID_ABI")
        # Emulator 10.0.2.2 otherwise reaches namespace loopback, including the
        # observer-only fixture control port. Disable guest uplinks, then admit
        # only the explicit adbd reverse to the public fixture API.
        adb_command("shell", "svc", "wifi", "disable")
        adb_command("shell", "svc", "data", "disable")
        route_end = min(stop, time.monotonic() + 10)
        while True:
            if all(no_guest_egress_routes(adb_command("shell", "ip", family, "route", "show", "table", "all"))
                   for family in ("-4", "-6")):
                break
            require(time.monotonic() < route_end, "GUEST_NETWORK_STILL_ACTIVE")
            time.sleep(0.25)
        H.write(PROOF / "emulator-boundary.json", (json.dumps(dict(schema=1, api=36, architecture="x86_64",
            kvm_required=True, guest_wifi_disabled=True, guest_mobile_data_disabled=True, guest_default_routes_absent=True,
            guest_non_loopback_routes_absent=True,
            reverse_ports=[43210], fixture_control_reversed=False, host_network_namespace_isolated=True)) + "\n").encode())
        adb_command("install", "--no-streaming", str(APK), seconds=45)
        adb_command("reverse", "tcp:43210", "tcp:43210")
        # Driver creates a fresh directory; existing outer root only holds the
        # final original report copied byte-for-byte below.
        try:
            command([str(H.NODE), str(W.HERE / "native-android-driver.mjs"), "--adb", adb,
                "--serial", SERIAL, "--output", str(PROOF / "driver")], 190)
        finally:
            original = PROOF / "driver/report.json"
            if original.exists():
                H.write(PROOF / "report.json", H.read(original))
        complete = True
    finally:
        for s in prior:
            signal.signal(s, signal.SIG_IGN)
        drained = drain_children(children)
        for log in logs:
            log.close()
        # This namespace's PID1 and enclosing H.run additionally drain all
        # descendants. Never remove another runner's AVD or adb server.
        if drained:
            for path in (Path("/state/avd"), Path("/state/android-home"), Path("/state/native-fixture")):
                if path.exists():
                    require(path.resolve() == path and path.is_dir(), "PRIVATE_CLEANUP_PATH")
                    shutil.rmtree(path)
        H.write(PROOF / "emulator-cleanup.json", (json.dumps(dict(schema=1, direct_children_reaped=drained,
            private_avd_removed=not Path("/state/avd").exists(), private_android_home_removed=not Path("/state/android-home").exists(),
            trial_returned=complete, enclosing_namespace_cleanup_required=True)) + "\n").encode())
        require(drained, "EMULATOR_CLEANUP_UNCONFIRMED")
        for s, handler in prior.items():
            signal.signal(s, handler)


def main():
    os.umask(0o077)
    if sys.argv[1:] == ["--inside"]:
        inside()
        return
    require(len(sys.argv) == 1, "NO_ARBITRARY_COMMAND")
    helper, platform = guards(os.environ)
    H.private_directory(OUTPUT)
    execute(helper, platform)


if __name__ == "__main__":
    try:
        main()
    except (H.Interrupted, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("HOSTED_ANDROID_CI_FAILED; inspect bounded phase receipts", file=sys.stderr)
        sys.exit(1)
