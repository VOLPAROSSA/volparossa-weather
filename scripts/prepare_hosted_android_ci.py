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
AWK = Path("/usr/bin/mawk")
AWK_LIMIT = 4 * 1024**2
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
# Bound only the two app-build commands, not the shared aggregate RSS guard.
# Gradle 8.13 gives these CLI properties precedence over staged properties.
APP_GRADLE_WORKERS = 1
# Run 38288008577 at 809cc44e exhausted the 1024 MiB Java heap during
# mergeExtDexDebug, below the unchanged 4 GiB aggregate guard (3299090432 B).
# The included-build Kotlin scope fix remains required; 1536 MiB is a bounded
# fit candidate, not a guarantee that the complete APK build will fit.
APP_GRADLE_JVM_ARGS = ("-Xmx1536m", "-XX:MaxMetaspaceSize=512m",
    "-XX:ReservedCodeCacheSize=128m", "-Dfile.encoding=UTF-8")
# Exact AGP 8.11.1 sources: IntegerOption.R8_THREAD_POOL_SIZE feeds
# R8D8ThreadPoolBuildService; DexMergingTask uses it for mergeExtDex's single
# bucket. Gradle --max-workers does not constrain this internal work-stealing
# pool. Source: https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/8.11.1/gradle-8.11.1-sources.jar
# This is a scoped concurrency candidate, not proof that the build fits.
APP_D8_THREADS = 1
# The app's gradle.properties does not configure Flutter's included plugin
# build. Use the already private Gradle user home, shared by both builds:
# https://raw.githubusercontent.com/gradle/gradle/v8.13.0/subprojects/core/src/main/java/org/gradle/initialization/DefaultGradlePropertiesLoader.java
# https://raw.githubusercontent.com/gradle/gradle/v8.13.0/subprojects/core-api/src/main/java/org/gradle/StartParameter.java
# https://raw.githubusercontent.com/flutter/flutter/f6ff1529fd6d8af5f706051d9251ac9231c83407/packages/flutter_tools/gradle/build.gradle.kts
# https://raw.githubusercontent.com/JetBrains/kotlin/v1.9.20/libraries/tools/kotlin-gradle-plugin/src/common/kotlin/org/jetbrains/kotlin/gradle/plugin/PropertiesProvider.kt
# No daemon-role/performance conclusion is inferred from this configuration.
GRADLE_USER_PROPERTIES = b"kotlin.compiler.execution.strategy=in-process\n"
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


def verify_gradle_user_properties():
    parent = PRIVATE / "gradle-home"
    info = parent.lstat()
    require(parent.resolve() == parent and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "GRADLE_USER_HOME_PRIVATE")
    fd = os.open(parent / "gradle.properties", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600
            and before.st_size == len(GRADLE_USER_PROPERTIES), "GRADLE_USER_PROPERTIES_PRIVATE")
        raw = stream.read(len(GRADLE_USER_PROPERTIES) + 1)
        after = os.fstat(stream.fileno())
        named = (parent / "gradle.properties").lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(raw == GRADLE_USER_PROPERTIES
        and all(getattr(before, k) == getattr(after, k) == getattr(named, k) for k in fields),
        "GRADLE_USER_PROPERTIES_CHANGED")
    return dict(schema=1, kind="hosted-android-kotlin-configured-scope", scopes=["main-build", "included-builds"],
        compiler_execution_strategy="in-process", bytes=len(raw), sha256=H.sha(raw), runtime_measurement=False)


def prepare_gradle_user_properties():
    H.write(PRIVATE / "gradle-home/gradle.properties", GRADLE_USER_PROPERTIES)
    return verify_gradle_user_properties()


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
        "--ro-bind", "/etc/java-17-openjdk", "/etc/java-17-openjdk",
        # The exact 19.0 launcher needs awk; /etc/alternatives stays absent.
        # /tools already exists for the reviewed which alias, and is remounted
        # read-only below. Never replace a host alias or modify the SDK.
        "--symlink", str(AWK), "/tools/awk",
        "--ro-bind", str(PRIVATE / "gradle-home/gradle.properties"), "/state/gradle-home/gradle.properties"]
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
import json,os,shutil,socket,stat,sys
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
assert Path('/tools/awk').is_symlink() and os.readlink('/tools/awk')=='/usr/bin/mawk'
assert Path('/tools/awk').resolve(strict=True)==Path('/usr/bin/mawk')
assert shutil.which('awk')=='/tools/awk' and os.access('/tools/awk',os.X_OK)
assert all(os.statvfs(p).f_flag & os.ST_RDONLY for p in ('/tools','/usr/bin/mawk'))
assert os.statvfs(sys.argv[3]+'/packages/flutter_tools/gradle/src').f_flag & os.ST_RDONLY
assert os.statvfs(sys.argv[3]+'/.git').f_flag & os.ST_RDONLY
properties=Path('/state/gradle-home/gradle.properties')
assert os.environ['GRADLE_USER_HOME']==str(properties.parent)
with properties.open('rb') as stream:
 assert stream.read(47)==b'kotlin.compiler.execution.strategy=in-process\n'
assert os.statvfs(properties).f_flag & os.ST_RDONLY
assert not os.statvfs(properties.parent).f_flag & os.ST_RDONLY
assert Path('/dev/kvm').exists()==(mode=='emulator')
print(json.dumps(dict(schema=1,mode=mode,unprivileged=True,capabilities_zero=True,
 no_new_privileges=True,source_read_only=True,toolchain_read_only=True,
 isolated_network=not online,public_acquisition=online,kvm_only=mode=='emulator')))
'''


def preflight(mode, netns, *, avd=False):
    require(type(avd) is bool and (not avd or mode == "emulator"), "PREFLIGHT_SCOPE")
    name = "preflight-avdmanager" if avd else "preflight-" + mode
    raw = H.run(name, sandbox(["/usr/bin/python3", "-I", "-c", PROBE, mode, netns, str(SDK)], mode),
        20, env=environment(), memory=MEMORY)
    value = json.loads(raw, object_pairs_hook=H.unique)
    require(value == dict(schema=1, mode=mode, unprivileged=True, capabilities_zero=True,
        no_new_privileges=True, source_read_only=True, toolchain_read_only=True,
        isolated_network=mode != "acquire", public_acquisition=mode == "acquire", kvm_only=mode == "emulator"), "PREFLIGHT")
    H.save(name + ".json", value)


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
    verify_gradle_user_properties()
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
    expected = dict(schema=3, kind="gradle-repository-contract", gradle_version="8.13", plugin_wrappers=3,
        rejected=["artifact-url", "unadmitted", "http", "file", "ivy", "flatdir"], networkless=True, external_dependencies=False,
        nofile_soft=4096, nofile_hard=4096, kotlin_property_scopes=["root", "included"])
    require(value == expected and type(value.get("schema")) is int and type(value.get("plugin_wrappers")) is int
        and type(value.get("nofile_soft")) is int and type(value.get("nofile_hard")) is int
        and type(value.get("networkless")) is bool and type(value.get("external_dependencies")) is bool,
        "REPOSITORY_FIXTURE_PROOF")
    return value


def repository_fixture():
    """Hosted-only: one offline Gradle invocation with no external dependencies."""
    target = PRIVATE / "repository-fixture"
    verify_gradle_user_properties()
    for path in (target, target / "gradle", target / "gradle/wrapper", target / "compiler-property"):
        H.private_directory(path)
    fixture = ROOT / "tests/fixtures/hosted-android-repositories"
    files = {name: H.read(fixture / name) for name in ("settings.gradle", "build.gradle", "gradle.properties",
        "compiler-property/settings.gradle", "compiler-property/build.gradle")}
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


def apt_awk_digest():
    """Only the canonical declared distro helper; never execute it here.

    Keep the existing Java and generic runner-owned input readers unchanged.
    Root ownership is checked outside the sandbox's UID mapping, before its
    read-only /usr bind is used. The named path must still refer to the same fd.
    """
    require(AWK.resolve() == AWK, "AWK_TOOL_PATH")
    fd = os.open(AWK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
            and before.st_mode & 0o111 and not before.st_mode & 0o7022
            and 0 < before.st_size <= AWK_LIMIT, "AWK_TOOL")
        digest, size = hashlib.sha256(), 0
        while True:
            block = os.read(fd, min(65536, AWK_LIMIT + 1 - size))
            if not block:
                break
            size += len(block)
            require(size <= AWK_LIMIT, "AWK_TOOL_BOUND")
            digest.update(block)
        after, named = os.fstat(fd), AWK.lstat()
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
            "st_size", "st_mtime_ns", "st_ctime_ns")
        require(size == before.st_size and all(getattr(before, k) == getattr(after, k) == getattr(named, k)
            for k in fields), "AWK_TOOL_CHANGED")
        return dict(bytes=size, sha256=digest.hexdigest())
    finally:
        os.close(fd)


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


class EmulatorDiagnostic:
    """Closed observations only; never persist command text, output or VM tokens."""
    MAX_OUTPUT = 65536  # The existing command reader's bound, not a larger log scan.
    MAX_RECEIPT = 1024
    PHASES = frozenset(("avd_create", "avd_configure", "service_start", "boot", "guest_identity",
        "guest_network", "apk_install", "port_reverse", "app_driver"))
    COMMANDS = frozenset(("avdmanager", "adb", "adb_server", "fixture", "emulator", "app_driver"))
    CHECKS = frozenset(("EMULATOR_DEADLINE", "EMULATOR_COMMAND_DEADLINE", "EMULATOR_COMMAND_OUTPUT",
        "EMULATOR_BOOT_FAILED", "ANDROID_API", "ANDROID_ABI", "GUEST_ROUTE_OUTPUT_BOUND",
        "GUEST_NETWORK_STILL_ACTIVE"))
    # These fixed SDK/JVM message forms are indications, not a claimed cause.
    # An unfamiliar message (including a new SDK version's wording) is unknown.
    MARKERS = {
        "java_version": rb'(?:^|\n)(?:Exception in thread "[A-Za-z0-9_-]{1,32}" )?java\.lang\.UnsupportedClassVersionError\b|(?:^|\n)Java version [0-9]{1,2} or higher is required\.|(?:^|\n)This tool requires JDK 17 or later\.',
        "java_home": rb'(?:^|\n)ERROR: JAVA_HOME is set to an invalid directory:',
        "java_classpath": rb'\bjava\.lang\.(?:ClassNotFoundException|NoClassDefFoundError)\b|(?:^|\n)Error: Could not find or load main class ',
        "java_initialization": rb'\bjava\.lang\.ExceptionInInitializerError\b|(?:^|\n)Error: Could not create the Java Virtual Machine\.',
        "launcher_helper": rb'(?:^|\n)/tools/android-inputs/sdk/cmdline-tools/19[.]0/bin/avdmanager: [0-9]{1,5}: (?:awk|sed|dirname|basename|uname|expr|ls): not found(?:\n|$)',
        "sdk_root": rb'(?:^|\n)(?:Error: )?Could not determine SDK root\.|(?:^|\n)Error: The tools directory property is not set,',
        "sdk_package": rb'(?:^|\n)Error: Package path is not valid\.',
        "sdk_image": rb'(?:^|\n)Error: Package [^\n]{1,512} contains no system images\.',
        "sdk_avd": rb'(?:^|\n)Error: AVD not created\.',
        "sdk_license": rb'\bcom\.android\.builder\.sdk\.LicenceNotAcceptedException\b',
    }
    # Exact standard throwable names only, grouped into closed indications.
    # Never export a class/message/path extracted from the SDK. Multiple
    # families (for example an initializer and its IO cause) remain ambiguous.
    JAVA_FAMILIES = {
        "version": ("java.lang.UnsupportedClassVersionError",),
        "classpath": ("java.lang.ClassNotFoundException", "java.lang.NoClassDefFoundError"),
        "initialization": ("java.lang.ExceptionInInitializerError",),
        "linkage": ("java.lang.UnsatisfiedLinkError", "java.lang.NoSuchMethodError",
            "java.lang.NoSuchFieldError", "java.lang.IncompatibleClassChangeError", "java.lang.LinkageError"),
        "invalid_operation": ("java.lang.IllegalArgumentException", "java.lang.NumberFormatException",
            "java.lang.UnsupportedOperationException"),
        "state": ("java.lang.IllegalStateException",),
        "null_reference": ("java.lang.NullPointerException",),
        "security": ("java.lang.SecurityException", "java.security.AccessControlException",
            "java.security.NoSuchAlgorithmException", "java.security.ProviderException",
            "java.security.InvalidKeyException", "java.security.cert.CertificateException"),
        "memory": ("java.lang.OutOfMemoryError", "java.lang.StackOverflowError"),
        "io": ("java.io.IOException", "java.io.FileNotFoundException", "java.nio.file.FileSystemException",
            "java.nio.file.NoSuchFileException", "java.nio.file.AccessDeniedException",
            "java.nio.file.ReadOnlyFileSystemException", "java.nio.file.FileAlreadyExistsException"),
        "network": ("java.net.UnknownHostException", "java.net.ConnectException", "java.net.SocketException"),
        "service_configuration": ("java.util.ServiceConfigurationError",),
        "internal": ("java.lang.InternalError", "java.lang.AssertionError"),
    }
    THROWABLE_PREFIX = rb'(?:^|\n)[ \t]*(?:(?:Exception in thread "[A-Za-z0-9_-]{1,32}"|Caused by:|Suppressed:) )?'
    FILESYSTEM_MARKERS = {
        "read_only": rb'\bRead-only file system\b|\bjava\.nio\.file\.ReadOnlyFileSystemException\b',
        # FileNotFoundException alone also covers permission errors; it is not
        # evidence of a missing file without this more specific observation.
        "missing": rb'\bNo such file or directory\b|\bjava\.nio\.file\.NoSuchFileException\b',
        "access_denied": rb'\bPermission denied\b|\bAccess is denied\b|\bOperation not permitted\b|\bjava\.nio\.file\.AccessDeniedException\b',
    }
    # Fixed fatal forms from commandlinetools 13114758 / 19.0, inspected as
    # data, never executed locally. Launcher SHA256 f2b7957ca635bbc1d4cf8def2fd5837153359f49f3043c7c02f020d77fc5cda0;
    # AvdManagerCli.class d379d9d22c004cbec8354e9930c6a9b518cfef2c1e595b563dd05d9c9a2776b7;
    # sdklib/util/CommandLineParser.class 434163bca64a5a58aa4c8de8d2ac1d98875e164448625f127ae4ec1541088c7a.
    # These are observations, not an exhaustive transitive-exception catalogue:
    # main() forwards Exception.getMessage(), which can legitimately be unknown.
    # Variables are bounded ASCII. Adjacent fields exclude their separators;
    # there are no unbounded wildcards or overlapping multi-variable repeats.
    _TOKEN = rb'[!-~]{1,256}'
    _FLAG = rb'[A-Za-z0-9_-]{1,64}'
    _QUOTED = rb"[\x20-\x26\x28-\x7e]{1,512}"
    _TAIL = rb'[ -~]{1,512}'
    _JAVA_LOCATION = (rb'\n\nPlease set the JAVA_HOME variable in your environment to match the\n'
        rb'location of your Java installation[.]')
    FATAL_TEMPLATES = {
        "java_home_invalid": rb'ERROR: JAVA_HOME is set to an invalid directory: ' + _TAIL + _JAVA_LOCATION,
        "java_not_found": rb"ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH[.]" + _JAVA_LOCATION,
        "jdk_too_old": rb'This tool requires JDK 17 or later[.] Your version was detected as ' + _TOKEN + rb'[.]\nTo override this check, set SKIP_JDK_VERSION_CHECK[.]',
        "tools_directory_unset": rb'Error: The tools directory property is not set, please make sure you are executing ' + _TOKEN,
        # The exact upstream format intentionally has no closing apostrophe.
        "working_directory_invalid": rb"Error: The working directory does not seem to be valid: '" + _QUOTED,
        "package_argument_missing": rb'Error: Package path \(-k\) not specified[.] Valid system image paths are:\n',
        "package_unrecognized": rb'Error: Package path is not valid[.] Valid system image paths are:\n',
        "package_has_no_images": rb'Error: Package [\x20-\x27\x29-\x7e]{1,256} \([\x20-\x28\x2a-\x7e]{1,256}\) contains no system images[.] Valid system image paths are:\n',
        "avd_name_invalid": rb"Error: AVD name '" + _QUOTED + rb"' contains invalid characters[.]\nAllowed characters are: a-z A-Z 0-9 [.] _ -",
        "avd_already_exists": rb"Error: Android Virtual Device '" + _QUOTED + rb"' already exists[.]\nUse --force if you want to replace it[.]",
        "tag_abi_conflict": rb'Error: --' + _FLAG + rb' ' + _TOKEN + rb' conflicts with --' + _FLAG + rb' ' + _TOKEN + rb'[.]',
        "abi_syntax_invalid": rb'Error: Invalid --' + _FLAG + rb' ' + _TOKEN + rb": expected format 'abi' or 'tag/abi'[.]",
        "tag_invalid": rb'Error: Invalid --' + _FLAG + rb' ' + _TOKEN + rb' for the selected package[.] Valid tags are:\n',
        "abi_ambiguous": rb'Error: This package has more than one ABI[.] Please specify one using --' + _FLAG + rb'[.]',
        "abi_invalid": rb'Error: Invalid --' + _FLAG + rb' ' + _TOKEN + rb' for the selected package[.]',
        "device_not_found": rb'Error: No device found matching --' + _FLAG + rb' ' + _TOKEN + rb'[.]',
        "skin_not_found": rb'Error: Skin ' + _TOKEN + rb' not found at ' + _TAIL,
        "emulator_package_missing": rb'Error: "emulator" package must be installed!',
        "hardware_properties_unreadable": rb'Error: "hardware-properties[.]ini" could not be read',
        # Exact sdklib AvdManager.createAvd catch wrapper, not the forwarded
        # exception's cause. AvdManager.class SHA256:
        # 8abda0fe084e78f935008b1285899d7e1ac6ff46663d5c5a01946c663f8f6643.
        "avd_create_exception": rb'Error: An error occurred while creating AVD: ' + _TAIL,
        "parser_global_flag": rb"Error: Flag '" + _QUOTED + rb"' is not a valid global flag[.] Did you mean to specify it after the verb/object name[?]",
        "parser_action_flag": rb"Error: Flag '" + _QUOTED + rb"' is not valid for '" + _TOKEN + rb' ' + _TOKEN + rb"'[.]",
        "parser_expected_verb": rb"Error: Expected verb after global parameters but found '" + _QUOTED + rb"' instead[.]",
        "parser_argument": rb"Error: Argument '" + _QUOTED + rb"' is not recognized[.]",
        "parser_missing_argument": rb'Error: Missing argument for flag ' + _FLAG + rb'[.]',
        "parser_argument_is_flag": rb"Error: Oops, it looks like you didn't provide an argument for '" + _QUOTED + rb"'[.]\n'" + _QUOTED + rb"' was found instead[.]",
        "parser_invalid_usage": rb'Error: Invalid usage for flag ' + _FLAG + rb': ' + _TAIL + rb'[.]',
        "parser_missing_verb": rb'Error: Missing verb name[.]',
        "parser_missing_object": rb"Error: Missing object name for verb '" + _QUOTED + rb"'[.]",
        "parser_required_parameters": rb'Error: The parameters? --' + _FLAG + rb'(?:, --' + _FLAG + rb'){0,15} must be defined for action ' + rb"'" + _TOKEN + rb' ' + _TOKEN + rb"'",
    }
    HARDWARE_PROMPT = b'Do you wish to create a custom hardware profile? [no] '
    MILESTONES = {
        "cli_usage": rb'Usage:\n  avdmanager \[global options\] (?:\[action\]|[A-Za-z_-]{1,64}(?: [A-Za-z_-]{1,64})?) \[action options\]\n\nGlobal options:',
        "local_repository": rb'(?:\[[= ]{39}\] (?:[0-9]{1,2}|100)% )?Loading local repository[.][.][.] {0,80}',
        "single_abi_selected": rb'Auto-selecting single ABI [A-Za-z0-9_/-]{1,64}',
        "hardware_question": re.escape(HARDWARE_PROMPT),
    }

    def fatal_observations(self, raw, complete):
        # Exact 19.0 promptForHardware emits this complete prompt with printf,
        # without a newline. The logger's next error may directly follow it.
        # AvdManagerCli$1.class SHA256:
        # 5ade58325c100f0cd55c0dfd8786957ae7530aa84e7c0700a5b0e91b2c9943d4.
        # Observe only the full literal at a real normalized line start.
        prompt = rb'(?m)^' + re.escape(self.HARDWARE_PROMPT)
        question_observed = re.search(prompt, raw) is not None
        # A prefix truncated in the middle of a variable must not masquerade
        # as a completed source line. Earlier terminated lines remain useful.
        if not complete:
            end = raw.rfind(b"\n")
            raw = raw[:end + 1] if end >= 0 else b""
        # Interpret only this known renderer boundary, without growing the
        # prefix or stripping arbitrary spaces/prefixes/ANSI. Original bytes,
        # completeness and counts in receipt() are untouched.
        fatal_lines = re.sub(prompt, self.HARDWARE_PROMPT[:-1] + b"\n", raw)
        def observed(pattern, source=raw):
            # List-bearing templates end at their fixed newline, without
            # interpreting or exporting the following SDK-controlled entries.
            end = b'' if pattern.endswith(rb'\n') else rb'(?=\n|\Z)'
            return re.search(rb'(?:^|\n)' + pattern + end, source) is not None
        milestones = {name: observed(pattern) for name, pattern in self.MILESTONES.items()}
        milestones["hardware_question"] = question_observed
        return (self.classify([name for name, pattern in self.FATAL_TEMPLATES.items()
            if observed(pattern, fatal_lines)]), milestones)

    @staticmethod
    def classify(matches):
        return matches[0] if len(matches) == 1 else "ambiguous" if matches else "unknown"

    def startup_markers(self, raw):
        families = [family for family, names in self.JAVA_FAMILIES.items()
            if any(re.search(self.THROWABLE_PREFIX + re.escape(name.encode()) + rb'(?=[:\r\n]|$)', raw)
                for name in names)]
        return self.classify(families), {name: re.search(pattern, raw) is not None
            for name, pattern in self.FILESYSTEM_MARKERS.items()}

    def __init__(self):
        self.phase = "unknown"
        self.error = None
        self.command = "none"
        self.status = None
        self.raw = b""
        self.complete = self.truncated = False

    def failed_command(self, error, category, status=None, raw=b"", complete=False):
        self.error = error
        self.command = category if category in self.COMMANDS else "unknown"
        self.status = status if type(status) is int and -255 <= status <= 255 else None
        self.raw = bytes(raw[:self.MAX_OUTPUT])
        self.truncated = len(raw) > self.MAX_OUTPUT
        self.complete = complete is True and not self.truncated

    def receipt(self, error):
        # A caught boot-poll error is not the cause of a later failed predicate.
        current = error is self.error
        raw = self.raw if current else b""
        # Pinned commandlinetools 13114758 / 19.0 ConsoleProgressIndicator emits
        # 80-column progress + CR; AvdManagerCli's logger then writes "Error: ".
        # tools.repository.jar SHA256:
        # ee7331131b6d80dc83ea7d78fb6600847300733f2964d18861709c4d23075e08
        # Normalize only line boundaries AFTER the existing raw-prefix cap.
        # Keep original byte counts; do not strip spaces, colors or other text.
        lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        markers = [name for name, pattern in self.MARKERS.items() if re.search(pattern, lines)]
        classification = self.classify(markers)
        java_family, filesystem = self.startup_markers(lines)
        fatal_template, milestones = self.fatal_observations(lines, current and self.complete)
        check = str(error) if isinstance(error, ValueError) and str(error) in self.CHECKS else "unknown"
        if isinstance(error, H.Interrupted): kind = "interrupted"
        elif isinstance(error, subprocess.CalledProcessError): kind = "command_exit"
        elif isinstance(error, subprocess.TimeoutExpired) or check in ("EMULATOR_DEADLINE", "EMULATOR_COMMAND_DEADLINE"): kind = "deadline"
        elif check == "EMULATOR_COMMAND_OUTPUT": kind = "output_bound"
        elif isinstance(error, FileNotFoundError): kind = "not_found"
        elif isinstance(error, PermissionError): kind = "permission_denied"
        elif isinstance(error, OSError): kind = "os_error"
        elif check != "unknown": kind = "check_failed"
        else: kind = "unknown"
        return dict(schema=3, kind="hosted-android-emulator-diagnostic",
            phase=self.phase if self.phase in self.PHASES else "unknown",
            command_category=self.command if current else "none", failure_kind=kind, check_code=check,
            exit_status=self.status if current else None, output_bytes=len(raw),
            output_complete=current and self.complete, output_truncated=current and self.truncated,
            sdk_error=classification, java_error_family=java_family, filesystem_markers=filesystem,
            fatal_template=fatal_template, milestones=milestones,
            raw_text_exported=False, cause_established=False)

    def publish_failure(self, error, *, avd=False):
        # Only called while re-raising the original failure. The inside OUTPUT
        # is an unexported tmpfs; PROOF is the existing explicit writable bind.
        name = "emulator-preflight-diagnostic" if avd else "emulator-diagnostic"
        part = PROOF / (name + ".part")
        try:
            raw = (json.dumps(self.receipt(error), sort_keys=True, separators=(",", ":")) + "\n").encode()
            require(len(raw) <= self.MAX_RECEIPT, "EMULATOR_DIAGNOSTIC_BOUND")
            H.write(part, raw)
            os.replace(part, PROOF / (name + ".json"))
        except BaseException:
            # Neither diagnostic IO nor another interruption may replace the
            # failure already being propagated into the existing cleanup.
            pass
        finally:
            try:
                part.unlink(missing_ok=True)
            except BaseException:
                pass


def avd_command():
    """One shared command for the early check and the complete installed trial."""
    return [str(ANDROID / "cmdline-tools/19.0/bin/avdmanager"), "create", "avd", "--name", "volparossa_trial",
        "--package", "system-images;android-36;default;x86_64", "--path", "/state/avd/trial.avd"]


def avd_input_identity(root):
    # This supplements the full materializer inventory verification before the
    # sandbox; it is not independent authorization of different SDK bytes.
    tools = root / "sdk/cmdline-tools/19.0"
    image = root / "sdk/system-images/android-36/default/x86_64"
    return dict(android_provenance=H.digest(root / "provenance.json"),
        launcher=H.digest(tools / "bin/avdmanager"), classpath=H.digest(tools / "lib/avdmanager-classpath.jar"),
        command_line_properties=H.digest(tools / "source.properties"),
        image_properties=H.digest(image / "source.properties"),
        image_package_xml=H.digest(image / "package.xml") if (image / "package.xml").exists() else None)


def avd_observations():
    # The exact pinned 13114758 / 19.0 launcher's Linux branch uses these fixed
    # POSIX helpers (including awk for its JDK check). Read-only archive review:
    # bin/avdmanager SHA256 f2b7957ca635bbc1d4cf8def2fd5837153359f49f3043c7c02f020d77fc5cda0.
    # Presence is an observation, not proof of execution or the previous cause.
    return dict(schema=1, kind="hosted-android-avd-preflight-inputs",
        inputs=avd_input_identity(Path("/tools/android-inputs")),
        posix_helpers={name: shutil.which(name) is not None
            for name in ("sh", "dirname", "basename", "uname", "sed", "awk", "expr", "ls")},
        sdk_read_only=bool(os.statvfs(ANDROID).f_flag & os.ST_RDONLY),
        raw_text_exported=False, cause_established=False)


def avd_preflight(netns, *, awk):
    expected = avd_input_identity(INPUTS)
    # Check distro ownership outside the user namespace, where its UID remains
    # meaningful. The existing /usr mount is read-only inside the sandbox.
    java = apt_java_digest()
    require(apt_awk_digest() == awk, "AWK_TOOL_CHANGED")
    preflight("emulator", netns, avd=True)
    # Thirty seconds of work, then only the existing owned-child cleanup.
    # The outer bound allows that cleanup before namespace teardown.
    H.run("avdmanager-preflight", sandbox(["/usr/bin/python3", "-B", str(Path(__file__)), "--inside-avd-preflight"], "emulator"),
        40, env=dict(environment(), VOLPAROSSA_TEST_HOST_NETNS=netns), memory=MEMORY)
    observed = H.document(PROOF / "emulator-preflight-inputs.json")
    require(set(observed) == {"schema", "kind", "inputs", "posix_helpers", "sdk_read_only", "raw_text_exported", "cause_established"}
        and observed["schema"] == 1 and observed["kind"] == "hosted-android-avd-preflight-inputs"
        and observed["inputs"] == expected == avd_input_identity(INPUTS)
        and apt_java_digest() == java
        and apt_awk_digest() == awk
        and set(observed["posix_helpers"]) == {"sh", "dirname", "basename", "uname", "sed", "awk", "expr", "ls"}
        and all(type(v) is bool for v in observed["posix_helpers"].values())
        and observed["posix_helpers"]["awk"] is True
        and observed["sdk_read_only"] is True and observed["raw_text_exported"] is False
        and observed["cause_established"] is False, "AVD_PREFLIGHT_INPUTS")
    cleanup = H.document(PROOF / "emulator-preflight-cleanup.json")
    require(cleanup == dict(schema=1, direct_children_reaped=True, private_avd_removed=True,
        private_android_home_removed=True, avd_creation_returned=True, installed_app_exercised=False,
        enclosing_namespace_cleanup_required=True), "AVD_PREFLIGHT_CLEANUP")
    # The complete trial must create a fresh AVD. Never reuse preflight state.
    for name in ("avd", "android-home"):
        H.private_directory(PRIVATE / name)
    H.save("emulator-preflight.json", dict(schema=1, kind="hosted-android-avd-preflight", success=True,
        inputs_sha256=H.sha(H.read(PROOF / "emulator-preflight-inputs.json")),
        cleanup_sha256=H.sha(H.read(PROOF / "emulator-preflight-cleanup.json")),
        java_launcher=java, awk=awk,
        creation_timeout_seconds=30, installed_app_exercised=False, production_authority=False))


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
        awk = apt_awk_digest()
        H.save("toolchain.json", dict(schema=1, android=android, flutter=sdk, runtime=runtime, java=java_provenance(helper),
            awk=dict(path=str(AWK), executable=awk, sandbox_alias="/tools/awk",
                authority="signed-disposable-apt-package-inventory", independently_reproducible=False)))
        H.private_directory(PRIVATE)
        for name in ("config", "cache", "pub-cache", "android-home", "avd", "gradle-home", "java-home"):
            H.private_directory(PRIVATE / name)
        H.save("gradle-kotlin-config.json", prepare_gradle_user_properties())
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
        phase = "avdmanager-preflight"
        H.private_directory(PROOF)
        avd_preflight(netns, awk=awk)
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
        require(apt_awk_digest() == awk, "AWK_TOOL_CHANGED")
        preflight("emulator", netns)
        H.run("installed-android-trial", sandbox(["/usr/bin/python3", "-B", str(Path(__file__)), "--inside"], "emulator"),
            520, env=dict(environment(), VOLPAROSSA_TEST_HOST_NETNS=netns), memory=MEMORY)
        require(apt_awk_digest() == awk, "AWK_TOOL_CHANGED")
        original = H.document(PROOF / "report.json")
        validate_report(original)
        H.save("build.json", dict(schema=1, kind="hosted-android-debug-trial", source_commit=os.environ["GITHUB_SHA"],
            apk=apk, runtime=runtime, sdk=sdk, android=android, native_sources=native, dependencies=metadata,
            gradle_configured_limits=app_gradle_resources(), awk=awk,
            avd_preflight_sha256=H.sha(H.read(OUTPUT / "emulator-preflight.json")),
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


def inside(*, avd_only=False):
    require(type(avd_only) is bool, "INSIDE_SCOPE")
    require(os.getuid() != 0 and "volparossa_ci_weather_clients_child" in Path("/proc/self/attr/current").read_text()
        and [n for _, n in socket.if_nameindex()] == ["lo"] and not Path("/etc/resolv.conf").exists(), "OFFLINE_SANDBOX_ONLY")
    # Explicitly owned children only. All private raw logs/VM authentication
    # material remain under /state, never among uploaded public evidence.
    children, logs = [], []
    diagnostic = EmulatorDiagnostic()
    prior = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_s, _f):
        raise H.Interrupted("EMULATOR_INTERRUPTED")
    for s in prior:
        signal.signal(s, interrupted)
    stop = time.monotonic() + (30 if avd_only else 480)
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
    def command(category, argv, seconds=20, data=None):
        try:
            require(time.monotonic() < stop, "EMULATOR_DEADLINE")
            end = min(stop, time.monotonic() + seconds)
            child = spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except BaseException as error:
            diagnostic.failed_command(error, category)
            raise
        raw = bytearray()
        output_complete = False
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
            output_complete = True
            child.wait(timeout=max(0.1, end - time.monotonic()))
            if child.returncode:
                raise subprocess.CalledProcessError(child.returncode, "owned-native-command")
            return bytes(raw)
        except BaseException as error:
            # Capture the observed status before TERM/KILL cleanup can change
            # it. Only this propagated error may consume its command context.
            diagnostic.failed_command(error, category, child.returncode, raw, output_complete)
            raise
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
        try:
            log = open("/state/" + name + ".log", "xb")
            logs.append(log)
            return spawn(argv, stdin=subprocess.PIPE, stdout=log, stderr=log)
        except BaseException as error:
            diagnostic.failed_command(error, "adb_server" if name == "adb" else name)
            raise
    def adb_command(*args, seconds=20):
        return command("adb", [adb, "-s", SERIAL, *args], seconds)
    complete = False
    try:
        diagnostic.phase = "avd_create"
        if avd_only:
            raw = (json.dumps(avd_observations(), sort_keys=True, separators=(",", ":")) + "\n").encode()
            require(len(raw) <= 4096, "AVD_PREFLIGHT_OBSERVATIONS_BOUND")
            H.write(PROOF / "emulator-preflight-inputs.json", raw)
        command("avdmanager", avd_command(), 30, b"no\n")
        if avd_only:
            require(time.monotonic() < stop, "EMULATOR_DEADLINE")
            complete = True
            return
        diagnostic.phase = "avd_configure"
        config = Path("/state/avd/trial.avd/config.ini")
        with config.open("a") as out:
            out.write("\nhw.lcd.width=1080\nhw.lcd.height=1920\nhw.lcd.density=420\nhw.keyboard=yes\n")
        diagnostic.phase = "service_start"
        start("adb", [adb, "-L", "tcp:127.0.0.1:5037", "nodaemon", "server"])
        Path("/state/native-fixture").mkdir(mode=0o700)
        fixture = start("fixture", [str(H.NODE), str(W.HERE / "native-android-fixture.mjs"), "--work", "/state/native-fixture"])
        emulator = start("emulator", [str(ANDROID / "emulator/emulator"), "-avd", "volparossa_trial", "-port", "5554",
            "-accel", "on", "-cores", "2", "-memory", "1536", "-no-window", "-no-audio", "-no-snapshot",
            "-no-boot-anim", "-gpu", "swiftshader_indirect", "-no-metrics", "-camera-back", "none", "-camera-front", "none"])
        diagnostic.phase = "boot"
        boot_end = min(stop, time.monotonic() + 180)
        while True:
            require(emulator.poll() is None and fixture.poll() is None and time.monotonic() < boot_end, "EMULATOR_BOOT_FAILED")
            try:
                if adb_command("shell", "getprop", "sys.boot_completed", seconds=3).strip() == b"1":
                    break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
            time.sleep(1)
        diagnostic.phase = "guest_identity"
        require(adb_command("shell", "getprop", "ro.build.version.sdk").strip() == b"36", "ANDROID_API")
        require(adb_command("shell", "getprop", "ro.product.cpu.abi").strip() == b"x86_64", "ANDROID_ABI")
        # Emulator 10.0.2.2 otherwise reaches namespace loopback, including the
        # observer-only fixture control port. Disable guest uplinks, then admit
        # only the explicit adbd reverse to the public fixture API.
        diagnostic.phase = "guest_network"
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
        diagnostic.phase = "apk_install"
        adb_command("install", "--no-streaming", str(APK), seconds=45)
        diagnostic.phase = "port_reverse"
        adb_command("reverse", "tcp:43210", "tcp:43210")
        # Driver creates a fresh directory; existing outer root only holds the
        # final original report copied byte-for-byte below.
        diagnostic.phase = "app_driver"
        try:
            command("app_driver", [str(H.NODE), str(W.HERE / "native-android-driver.mjs"), "--adb", adb,
                "--serial", SERIAL, "--output", str(PROOF / "driver")], 190)
        finally:
            original = PROOF / "driver/report.json"
            if original.exists():
                H.write(PROOF / "report.json", H.read(original))
        complete = True
    except BaseException as error:
        diagnostic.publish_failure(error, avd=avd_only)
        raise
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
        name = "emulator-preflight-cleanup.json" if avd_only else "emulator-cleanup.json"
        completion = dict(avd_creation_returned=complete, installed_app_exercised=False) if avd_only else dict(trial_returned=complete)
        H.write(PROOF / name, (json.dumps(dict(schema=1, direct_children_reaped=drained,
            private_avd_removed=not Path("/state/avd").exists(), private_android_home_removed=not Path("/state/android-home").exists(),
            **completion, enclosing_namespace_cleanup_required=True)) + "\n").encode())
        require(drained, "EMULATOR_CLEANUP_UNCONFIRMED")
        for s, handler in prior.items():
            signal.signal(s, handler)


def main():
    os.umask(0o077)
    if sys.argv[1:] == ["--inside"]:
        inside()
        return
    if sys.argv[1:] == ["--inside-avd-preflight"]:
        inside(avd_only=True)
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
