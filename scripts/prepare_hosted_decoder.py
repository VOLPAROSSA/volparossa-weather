#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Separate hosted ecCodes build recipe; does not authorize a decoder or alter legacy pins.

No downloads or installation. `capture-toolchain` inventories the hosting
workflow's existing trusted tools; `build` checks that same manifest and the
three original archives. Captured hashes are consistency/provenance, not trust
or decoder admission. `plan` is inert; execution uses an offline namespace.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "third_party/eccodes-sources.json"
PIN_SHA = "f136020562a6ff0d2a83b948189c31f839afb8a00ea87565469f38640fb0dc86"
LEGACY_SHA = "5bcb6d58b34e5b45647feae836bfd086ff0adce0e30487430f5c50941f579827"
TEMPLATE_SHA = "36a0cabd0a826d462ea21b309da695fe34ad4ef9a5e95c824ae8000e0351eab8"
EPOCH = 1756684800
JOBS, DEADLINE_SECONDS, MAX_LOG = 2, 1800, 16 * 1024**2
TOOLS = {"cc", "cxx", "cc1", "cc1plus", "collect2", "lto_wrapper", "as", "ld", "ar",
         "ranlib", "cmake", "ctest", "make", "python", "bwrap", "sh", "git"}
VERSION_ARGS = {key: ["--version"] for key in TOOLS - {"cc1", "cc1plus", "collect2", "lto_wrapper", "sh"}}
DATE_SHIM = b'''#!/bin/sh
set -eu
[ "$#" -eq 1 ] || exit 64
case "$1" in
  +%d/%m/%Y) printf '01/09/2025\\n' ;;
  +%Y/%m/%d/%H/%M/%S) printf '2025/09/01/00/00/00\\n' ;;
  *) exit 64 ;;
esac
'''
ENV = {"PATH": "/build/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
       "TZ": "UTC", "SOURCE_DATE_EPOCH": str(EPOCH), "CCACHE_DISABLE": "1",
       "CMAKE_BUILD_PARALLEL_LEVEL": str(JOBS)}
NORMAL_FLAGS = "-ffile-prefix-map=/build=/volparossa-decoder -fmacro-prefix-map=/build=/volparossa-decoder"
SCOPE = dict(network_during_build=False, downloaded_executables=False, original_sources_unchanged=True,
             decoder_authorized=False, origin_acquisition_proven=False, browser_proven=False,
             fully_hermetic_toolchain=False, bit_reproducibility_proven=False, debian13_abi_proven=False)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_KEY")
        result[key] = value
    return result


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_file(path, maximum=1024**2):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid in (0, os.getuid()) and not before.st_mode & 0o022
                and 0 < before.st_size <= maximum, "UNSAFE_INPUT")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require(len(raw) == before.st_size and (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns), "INPUT_CHANGED")
        return raw


def write_new(path, raw, mode=0o600):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def platform():
    raw = read_file(Path("/etc/os-release").resolve(), 16384)
    values = {}
    for line in raw.decode().splitlines():
        match = re.fullmatch(r'(ID|VERSION_ID)=(?:"([^"]*)"|([^"\n]*))', line)
        if match:
            require(match[1] not in values, "PLATFORM_DUPLICATE")
            values[match[1]] = match[2] if match[2] is not None else match[3]
    require((values.get("ID"), values.get("VERSION_ID")) in {("debian", "13"), ("ubuntu", "24.04")}
            and os.uname().machine == "x86_64", "UNSUPPORTED_BUILD_PLATFORM")
    return dict(os_id=values["ID"], version_id=values["VERSION_ID"], architecture="x86_64", os_release_sha256=sha(raw))


def load_toolchain(path, expected):
    require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected), "TOOLCHAIN_PIN_REQUIRED")
    raw = read_file(path)
    require(sha(raw) == expected, "TOOLCHAIN_PIN_MISMATCH")
    value = json.loads(raw, object_pairs_hook=unique)
    require(type(value) is dict and set(value) == {"schema", "kind", "platform", "provenance_only", "tools"}
            and type(value["schema"]) is int and value["schema"] == 1
            and value["kind"] == "volparossa-hosted-decoder-toolchain"
            and value["platform"] == platform() and value["provenance_only"] is True
            and type(value["tools"]) is dict and set(value["tools"]) == TOOLS, "TOOLCHAIN_SCHEMA")
    for name, item in value["tools"].items():
        require(type(item) is dict and set(item) == {"path", "bytes", "sha256", "version_sha256"}, "TOOLCHAIN_TOOL")
        path = Path(item["path"])
        require(path.is_absolute() and path.resolve() == path and str(path).startswith("/usr/")
                and type(item["bytes"]) is int and 0 < item["bytes"] <= 128 * 1024**2
                and type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "TOOLCHAIN_TOOL")
        version = item["version_sha256"]
        require((name not in VERSION_ARGS and version is None) or
                (name in VERSION_ARGS and type(version) is str and re.fullmatch(r"[0-9a-f]{64}", version)),
                "TOOLCHAIN_VERSION_PIN")
        raw_tool = read_file(path, 128 * 1024**2)
        require(len(raw_tool) == item["bytes"] and sha(raw_tool) == item["sha256"]
                and path.stat().st_mode & 0o111, "TOOLCHAIN_BINARY_MISMATCH")
    return value


def plan():
    return dict(schema=1, kind="volparossa-hosted-decoder-plan", ready=False, compiled=False,
        missing=["captured-trusted-runner-toolchain-manifest"], source_pin_sha256=PIN_SHA,
        legacy_decoder_reused=False, tool_names=sorted(TOOLS), jobs=JOBS, deadline_seconds=DEADLINE_SECONDS,
        namespace_build_path="/build", source_date_epoch=EPOCH, date_shim_sha256=sha(DATE_SHIM),
        scope=dict(SCOPE), requires_existing_source_archives=True)


def new_output(output, prefix):
    require(output.is_absolute() and output.parent == ROOT / "build" and output.parent.resolve() == output.parent
            and re.fullmatch(prefix + r"[a-z0-9-]{1,48}", output.name)
            and not output.exists() and not output.is_symlink(), "NEW_PRIVATE_OUTPUT_REQUIRED")


def create_output(output):
    output.parent.mkdir(mode=0o700, exist_ok=True)
    info = output.parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022 and output.parent.resolve() == output.parent,
            "UNSAFE_OUTPUT_PARENT")
    output.mkdir(mode=0o700)
    for name in ("bin", "home"):
        (output/name).mkdir(mode=0o700)
    write_new(output/"bin/date", DATE_SHIM, 0o700)


def sandbox(output, tools, command):
    # Empty namespace root: no host home, repository, secrets or network devices.
    # System /usr and its dynamic libraries remain read-only; not a hermetic SDK.
    return [tools["bwrap"]["path"], "--die-with-parent", "--unshare-net", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts", "--new-session", "--tmpfs", "/",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--dir", "/etc", "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--bind", str(output), "/build", "--chdir", "/build", "--", *command]


def run_step(output, tools, name, command, deadline, maximum=MAX_LOG):
    require(re.fullmatch(r"[a-z0-9-]+", name), "STEP_NAME")
    require(time.monotonic() < deadline, "BUILD_DEADLINE")
    command = sandbox(output, tools, command)
    log = output / (name + ".log")
    process = None
    try:
        with log.open("xb") as stream, selectors.DefaultSelector() as selector:
            process = subprocess.Popen(command, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            selector.register(process.stdout, selectors.EVENT_READ)
            total = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "BUILD_DEADLINE")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    require(total <= maximum, "BUILD_OUTPUT_BOUND")
                    stream.write(chunk)
            code = process.wait(timeout=max(0.001, deadline-time.monotonic()))
            require(code == 0, "BUILD_STEP_FAILED")
            stream.flush()
        return dict(step=name, status="passed", argv=command[command.index("--")+1:],
                    log_sha256=sha(log.read_bytes()), log_bytes=log.stat().st_size)
    finally:
        if process is not None:
            # End the whole private build group even if the command exited but
            # left a descendant; bwrap's PID namespace also dies with its parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()


def tool_record(path):
    path = Path(path).resolve()
    require(str(path).startswith("/usr/") and path.stat().st_mode & 0o111, "TOOL_PATH")
    raw = read_file(path, 128*1024**2)
    return dict(path=str(path), bytes=len(raw), sha256=sha(raw), version_sha256=None)


def captured_program(output, tools, name, driver, program, deadline):
    label = "resolve-" + name.replace("_", "-")
    step = run_step(output, tools, label, [tools[driver]["path"], "-print-prog-name=" + program], deadline, 4096)
    actual = Path(read_file(output/(label+".log"), 4096).decode().strip())
    if not actual.is_absolute():
        require(len(actual.parts) == 1, "COMPILER_PROGRAM_CHANGED")
        actual = Path("/usr/bin") / actual
    return actual.resolve(), step


COMPILER_PROGRAMS = (("cc1", "cc", "cc1"), ("cc1plus", "cxx", "cc1plus"),
    ("collect2", "cc", "collect2"), ("lto_wrapper", "cc", "lto-wrapper"), ("as", "cc", "as"), ("ld", "cc", "ld"))


def capture_toolchain(output):
    require(os.geteuid() != 0, "UNPRIVILEGED_AMD64_REQUIRED")
    os.umask(0o077)
    new_output(output, "hosted-toolchain-")
    actual_platform = platform()
    aliases = dict(cc="gcc", cxx="g++", python="python3", bwrap="bwrap", sh="sh",
                   ar="ar", ranlib="ranlib", cmake="cmake", ctest="ctest", make="make", git="git")
    tools = {}
    for name, executable in aliases.items():
        path = shutil.which(executable, path="/usr/bin:/bin")
        require(path is not None, "TOOL_MISSING")
        tools[name] = tool_record(path)
    create_output(output)
    deadline = time.monotonic() + 60
    for name, driver, program in COMPILER_PROGRAMS:
        path, _ = captured_program(output, tools, name, driver, program, deadline)
        tools[name] = tool_record(path)
    for name, args in sorted(VERSION_ARGS.items()):
        step = run_step(output, tools, "version-"+name, [tools[name]["path"], *args], deadline, 16384)
        tools[name]["version_sha256"] = step["log_sha256"]
    value = dict(schema=1, kind="volparossa-hosted-decoder-toolchain", platform=actual_platform,
                 provenance_only=True, tools=tools)
    raw = (json.dumps(value, sort_keys=True, indent=2)+"\n").encode()
    path = output/"toolchain.json"
    write_new(path, raw)
    require(load_toolchain(path, sha(raw)) == value, "TOOLCHAIN_CHANGED")
    return dict(schema=1, kind="volparossa-hosted-decoder-toolchain-capture", compiled=False,
                toolchain_manifest=str(path), toolchain_manifest_sha256=sha(raw), tools=len(tools),
                platform=actual_platform, provenance_only=True, decoder_authorized=False)


def commands(tools):
    tool = lambda name: tools[name]["path"]
    common = ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS=" + NORMAL_FLAGS,
        "-DCMAKE_CXX_FLAGS=" + NORMAL_FLAGS, "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG",
        "-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG", "-DCMAKE_INSTALL_PREFIX=/build/prefix",
        "-DCMAKE_INSTALL_LIBDIR=lib", "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON",
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_C_COMPILER=" + tool("cc"), "-DCMAKE_CXX_COMPILER=" + tool("cxx"),
        "-DCMAKE_AR=" + tool("ar"), "-DCMAKE_RANLIB=" + tool("ranlib"),
        "-DCMAKE_LINKER=" + tool("ld"), "-DCMAKE_MAKE_PROGRAM=" + tool("make"),
        "-DPYTHON_EXECUTABLE=" + tool("python"), "-DGIT_EXECUTABLE=" + tool("git")]
    options = ["-Decbuild_DIR=/build/ecbuild-source/cmake", "-DAEC_LIBRARY=/build/prefix/lib/libaec.a",
        "-DAEC_INCLUDE_DIR=/build/prefix/include", "-DFETCHCONTENT_FULLY_DISCONNECTED=ON",
        "-DENABLE_AEC=ON", "-DENABLE_MEMFS=ON", "-DENABLE_PRODUCT_GRIB=ON",
        "-DENABLE_PRODUCT_BUFR=OFF", "-DENABLE_GEOGRAPHY=ON", "-DENABLE_ECKIT_GEO=OFF",
        "-DENABLE_FORTRAN=OFF", "-DENABLE_NETCDF=OFF", "-DENABLE_JPG=OFF", "-DENABLE_PNG=OFF",
        "-DENABLE_EXAMPLES=OFF", "-DENABLE_EXTRA_TESTS=OFF", "-DENABLE_TESTS=OFF"]
    cmake = tool("cmake")
    return [
        ("configure-libaec", [cmake, "-S", "/build/libaec-source", "-B", "/build/libaec-build", *common,
                              "-DBUILD_STATIC_LIBS=ON", "-DBUILD_TESTING=ON"]),
        ("compile-libaec", [cmake, "--build", "/build/libaec-build", "--parallel", str(JOBS)]),
        ("test-libaec", [tool("ctest"), "--test-dir", "/build/libaec-build", "--output-on-failure", "--timeout", "60"]),
        ("stage-libaec", [cmake, "--install", "/build/libaec-build"]),
        ("configure-eccodes", [cmake, "-S", "/build/eccodes-source", "-B", "/build/eccodes-build", *common, *options]),
        ("compile-eccodes", [cmake, "--build", "/build/eccodes-build", "--target", "grib_ls", "grib_filter", "codes_info",
                             "--parallel", str(JOBS)]),
        ("version-eccodes", ["/build/eccodes-build/bin/grib_ls", "-V"]),
        ("encode-ccsds", ["/build/eccodes-build/bin/grib_filter", "-o", "/build/probe.grib2", "/build/probe.filter",
                          "/build/eccodes-source/samples/ccsds_grib2.tmpl"]),
        *[("decode-ccsds-" + name, ["/build/eccodes-build/bin/grib_ls", "-j", "-l", coordinates + ",1", "-p",
            "edition:i,packingType:s,bitsPerValue:i,numberOfPoints:i", "/build/probe.grib2"])
          for name, coordinates in (("first", "60,0"), ("last", "0,30"))]]


def verify_compiler_programs(output, tools, deadline):
    require(Path("/bin/sh").resolve() == Path(tools["sh"]["path"]), "SHELL_BINDING_CHANGED")
    steps = []
    for name, driver, program in COMPILER_PROGRAMS:
        actual, step = captured_program(output, tools, name, driver, program, deadline)
        steps.append(step)
        require(actual == Path(tools[name]["path"]), "COMPILER_PROGRAM_CHANGED")
    return steps


def validate_decode(raw, latitude, longitude, expected_value):
    value = json.loads(raw, object_pairs_hook=unique)
    require(type(value) is list and len(value) == 1, "CCSDS_DECODE_COUNT")
    message = value[0]
    require(message["keys"] == dict(edition=2, packingType="grid_ccsds", bitsPerValue=16, numberOfPoints=496)
            and message["method"] == "nearest" and len(message["neighbours"]) == 1, "CCSDS_DECODE_IDENTITY")
    point = message["neighbours"][0]
    for key, expected in (("latitude", latitude), ("longitude", longitude), ("value", expected_value), ("distance", 0)):
        require(type(point[key]) in (int, float) and math.isfinite(point[key]) and point[key] == expected,
                "CCSDS_DECODE_VALUE")
    require(point["distance_unit"] == "km", "CCSDS_DECODE_DISTANCE")


def build(archives, output, manifest_path, manifest_sha):
    require(os.geteuid() != 0 and os.uname().machine == "x86_64", "UNPRIVILEGED_AMD64_REQUIRED")
    os.umask(0o077)
    new_output(output, "hosted-decoder-")
    require(archives.is_absolute() and archives.resolve() == archives and archives.is_dir(), "ARCHIVE_DIRECTORY")
    pin_raw = read_file(PIN)
    require(sha(pin_raw) == PIN_SHA, "SOURCE_PIN_CHANGED")
    legacy_path = ROOT / "scripts/build_eccodes.py"
    require(sha(read_file(legacy_path)) == LEGACY_SHA, "SOURCE_HELPERS_CHANGED")
    toolchain = load_toolchain(manifest_path, manifest_sha)
    pin = json.loads(pin_raw, object_pairs_hook=unique)
    # Check every archive before creating the output. No network fallback exists.
    inputs = []
    for source in pin["sources"]:
        raw = read_file(archives / source["archive"], source["bytes"])
        require(len(raw) == source["bytes"] and sha(raw) == source["sha256"], "SOURCE_ARCHIVE_MISMATCH")
        inputs.append((source, raw))
    create_output(output)
    (output/"downloads").mkdir(mode=0o700)
    write_new(output/"probe.filter", ("set bitsPerValue=16; set values={" +
              ",".join(map(str, range(496))) + "}; write;\n").encode())
    helper = runpy.run_path(str(legacy_path))
    helper["source_tree"].__globals__["BUILD"] = output
    sources = {}
    for source, raw in inputs:
        archive = output/"downloads"/source["archive"]
        write_new(archive, raw)
        sources[source["name"]] = helper["source_tree"](source, archive)
    require(sha(read_file(sources["eccodes"]/"samples/ccsds_grib2.tmpl")) == TEMPLATE_SHA, "CCSDS_TEMPLATE_PIN")
    deadline = time.monotonic() + DEADLINE_SECONDS
    steps = []
    versions = {}
    tools = toolchain["tools"]
    for name, args in sorted(VERSION_ARGS.items()):
        step = run_step(output, tools, "version-" + name, [tools[name]["path"], *args], deadline, 16384)
        require(step["log_sha256"] == tools[name]["version_sha256"], "TOOLCHAIN_VERSION_MISMATCH")
        steps.append(step)
        versions[name] = read_file(output/("version-"+name+".log"), 16384).decode()
    steps.extend(verify_compiler_programs(output, tools, deadline))
    for name, command in commands(tools):
        steps.append(run_step(output, tools, name, command, deadline))
    require((output/"version-eccodes.log").read_bytes().strip() == b"ecCodes Version 2.44.0", "DECODER_VERSION")
    generated = read_file(output/"eccodes-build/src/eccodes/grib_api_version.cc").decode()
    require('return "2025.09.01";' in generated, "EMBEDDED_BUILD_DATE_CHANGED")
    validate_decode(read_file(output/"decode-ccsds-first.log"), 60, 0, 0)
    validate_decode(read_file(output/"decode-ccsds-last.log"), 0, 30, 495)
    for source, _ in inputs:
        helper["verify_source"](sources[source["name"]], output/"downloads"/source["archive"])
    # Do not attest mutable system tool binaries merely because they matched once.
    require(load_toolchain(manifest_path, manifest_sha) == toolchain, "TOOLCHAIN_CHANGED")
    artifacts = []
    for name in ("eccodes-build/bin/grib_ls", "eccodes-build/bin/grib_filter", "eccodes-build/bin/codes_info",
                 "prefix/lib/libaec.a", "probe.grib2"):
        raw = read_file(output/name, 128*1024**2)
        artifacts.append(dict(path=name, bytes=len(raw), sha256=sha(raw)))
    flags = {name: read_file(output/name).decode() for name in (
        "libaec-build/src/CMakeFiles/aec-static-objects.dir/flags.make",
        "eccodes-build/tools/CMakeFiles/grib_ls.dir/flags.make",
        "eccodes-build/src/eccodes/CMakeFiles/eccodes.dir/flags.make",
        "eccodes-build/tools/CMakeFiles/grib_ls.dir/link.txt")}
    require(all("-O3 -DNDEBUG" in value and NORMAL_FLAGS in value for value in flags.values()), "EFFECTIVE_FLAGS_CHANGED")
    licenses = []
    notices = [(sources[item["name"]], name) for item in pin["sources"] for name in item["notices"]]
    notices.append((sources["eccodes"], "third_party/expected/COPYING"))
    for source_root, name in notices:
        path = source_root/name
        resolved = path.resolve()
        require(resolved.is_relative_to(source_root), "LICENSE_PATH_CHANGED")
        raw = read_file(resolved)
        licenses.append(dict(path=str(path.relative_to(output)), bytes=len(raw), sha256=sha(raw),
                             symlink_target=os.readlink(path) if path.is_symlink() else None))
    report = dict(schema=1, kind="volparossa-hosted-decoder-build", compiled=True, tests_passed=True,
        source_pin_sha256=PIN_SHA, recipe_sha256=sha(read_file(Path(__file__))),
        source_helper_sha256=LEGACY_SHA, toolchain_manifest_sha256=manifest_sha, toolchain=toolchain,
        observed_tool_versions=versions,
        sources=pin["sources"], scope=dict(SCOPE), source_date_epoch=EPOCH, namespace_build_path="/build",
        jobs=JOBS, deadline_seconds=DEADLINE_SECONDS, environment=ENV, date_shim_sha256=sha(DATE_SHIM),
        effective_flags=flags, steps=steps, artifacts=artifacts, licenses=licenses,
        tests=dict(version=True, ccsds_nonconstant_nearest_points=True, source_template_sha256=TEMPLATE_SHA,
                   values_generated_for_test=True, origin_data=False))
    write_new(output/"hosted-build-receipt.json", (json.dumps(report, sort_keys=True, indent=2)+"\n").encode())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands_parser = parser.add_subparsers(dest="action", required=True)
    commands_parser.add_parser("plan")
    capture = commands_parser.add_parser("capture-toolchain")
    capture.add_argument("--output-dir", required=True, type=Path)
    builder = commands_parser.add_parser("build")
    for name in ("archives", "output", "toolchain-manifest"):
        builder.add_argument("--" + name, required=True, type=Path)
    builder.add_argument("--toolchain-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "plan":
            result = plan()
        elif args.action == "capture-toolchain":
            result = capture_toolchain(args.output_dir)
        else:
            result = build(args.archives, args.output, args.toolchain_manifest, args.toolchain_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("HOSTED_DECODER_PREPARATION_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
