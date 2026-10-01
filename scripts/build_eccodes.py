#!/usr/bin/env python3
"""Explicit, pinned source build. All downloads/build outputs stay in build/eccodes.

Requires existing Linux cmake, C/C++ compilers, make, Python and bubblewrap.
No package installation, system changes, model/data downloads or host networking
changes. Build subprocesses have no network and only this build tree writable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import signal
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "third_party/eccodes-sources.json"
BUILD = ROOT / "build/eccodes"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_archive(source, fetch):
    path = BUILD / "downloads" / source["archive"]
    if path.is_symlink():
        raise ValueError("Archive path must not be a symlink")
    if not path.exists():
        if not fetch:
            raise ValueError("Missing pinned archive; use --fetch explicitly")
        temporary = path.with_suffix(".partial")
        # Exclusive creation preserves partial/unrecognized files on failure.
        with temporary.open("xb") as output:
            with urllib.request.urlopen(source["url"], timeout=60) as response:
                if not response.url.startswith("https://codeload.github.com/"):
                    raise ValueError("Unexpected archive origin")
                total = 0
                started = time.monotonic()
                while chunk := response.read(262144):
                    total += len(chunk)
                    if total > source["bytes"] or time.monotonic() - started > 180:
                        raise ValueError("Archive download bound exceeded")
                    output.write(chunk)
        if temporary.stat().st_size != source["bytes"] or digest(temporary) != source["sha256"]:
            raise ValueError("Downloaded archive differs from pinned source")
        temporary.rename(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != source["bytes"]:
        raise ValueError("Invalid pinned archive")
    if digest(path) != source["sha256"]:
        raise ValueError("Archive SHA256 mismatch")
    return path


def source_tree(source, archive):
    directory = BUILD / (source["name"] + "-source")
    marker = directory / ".volparossa-archive-sha256"
    if directory.is_symlink() or marker.is_symlink():
        raise ValueError("Source ownership paths must not be symlinks")
    if directory.exists():
        if directory.is_symlink() or not marker.is_file() or marker.read_text() != source["sha256"]:
            raise ValueError("Existing source tree has no matching ownership marker")
        verify_source(directory, archive)
        return directory
    with tarfile.open(archive, "r:gz") as packed:
        members = packed.getmembers()
        if len(members) > 30000 or sum(m.size for m in members) > 128 * 1024**2:
            raise ValueError("Source archive expansion bound exceeded")
        prefix = source["name"] + "-" + source["commit"]
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != prefix or ".." in parts or member.size > 16 * 1024**2:
                raise ValueError("Unsafe source archive path or file size")
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("Unsupported source archive member")
            if member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute():
                    raise ValueError("Absolute archive symlink")
                depth = len(parts) - 2
                for segment in target.parts:
                    depth += -1 if segment == ".." else (0 if segment == "." else 1)
                    if depth < 0:
                        raise ValueError("Source symlink escapes its source tree")
        # Python's data filter also rejects links traversing through other links.
        staging = BUILD / (source["name"] + "-extract")
        staging.mkdir(mode=0o700)
        packed.extractall(staging, filter="data")
        (staging / prefix).rename(directory)
        staging.rmdir()
        marker.write_text(source["sha256"])
    return directory


def verify_source(directory, archive):
    """A marker never authorizes silently compiling locally changed source."""
    expected = {".volparossa-archive-sha256"}
    with tarfile.open(archive, "r:gz") as packed:
        for member in packed.getmembers():
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            if not relative.parts:
                continue
            expected.add(str(relative))
            path = directory / relative
            if member.issym():
                if not path.is_symlink() or os.readlink(path) != posixpath.normpath(member.linkname):
                    raise ValueError("Staged source symlink changed")
            elif member.isdir():
                if path.is_symlink() or not path.is_dir():
                    raise ValueError("Staged source directory changed")
            elif member.isfile():
                if path.is_symlink() or not path.is_file() or path.stat().st_size != member.size:
                    raise ValueError("Staged source file changed")
                with packed.extractfile(member) as original:
                    if digest(path) != hashlib.file_digest(original, "sha256").hexdigest():
                        raise ValueError("Staged source bytes changed")
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*")}
    if actual != expected:
        raise ValueError("Unknown files in staged source tree")


def run(name, command, timeout=1200):
    log = BUILD / (name + ".log")
    environment = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "CMAKE_BUILD_PARALLEL_LEVEL": "2", "CCACHE_DISABLE": "1",
        "SOURCE_DATE_EPOCH": "1756684800",
    }
    sandbox = [
        "/usr/bin/bwrap", "--die-with-parent", "--unshare-net", "--unshare-pid",
        "--ro-bind", "/", "/", "--bind", str(BUILD), str(BUILD),
        "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev",
        "--chdir", str(BUILD), "--",
    ]
    started = time.monotonic()
    print(json.dumps({"step": name, "status": "running"}), flush=True)
    with log.open("ab") as output:
        process = subprocess.Popen(sandbox + command, env=environment,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    if code != 0:
        raise ValueError(f"{name} failed ({code}); see build/eccodes/{name}.log")
    return {"step": name, "status": "passed", "seconds": round(time.monotonic() - started, 3),
            "log_sha256": digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download missing exact source archives")
    parser.add_argument("--build", action="store_true", help="Compile pinned sources offline in bubblewrap")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ValueError("Run as an ordinary user, never root")
    BUILD.mkdir(parents=True, exist_ok=True)
    if BUILD.resolve() != BUILD or BUILD.stat().st_uid != os.getuid():
        raise ValueError("Build directory must be canonical and owned by this user")
    pin = json.loads(PIN.read_text())
    owner = BUILD / ".volparossa-eccodes-build"
    if owner.is_symlink() or (BUILD / "downloads").is_symlink():
        raise ValueError("Build ownership paths must not be symlinks")
    if owner.exists():
        if owner.is_symlink() or owner.read_text() != digest(PIN):
            raise ValueError("Build ownership/source pin changed")
    else:
        if set(p.name for p in BUILD.iterdir()) - {"downloads"}:
            raise ValueError("Refusing to adopt an unknown build directory")
        owner.write_text(digest(PIN))
    (BUILD / "downloads").mkdir(exist_ok=True)
    sources = {s["name"]: source_tree(s, verified_archive(s, args.fetch)) for s in pin["sources"]}
    report = {"version": 1, "source_pin_sha256": digest(PIN), "compiled": False,
              "sources": [{k: s[k] for k in ("name", "version", "commit", "sha256")} for s in pin["sources"]]}
    if args.build:
        prefix = BUILD / "prefix"
        aec = BUILD / "libaec-build"
        ecc = BUILD / "eccodes-build"
        common = ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG",
                  "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG", "-DCMAKE_INSTALL_PREFIX=" + str(prefix),
                  "-DCMAKE_INSTALL_LIBDIR=lib", "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON",
                  "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", "-DBUILD_SHARED_LIBS=OFF"]
        steps = []
        steps.append(run("configure-libaec", ["cmake", "-S", str(sources["libaec"]), "-B", str(aec)] + common +
                         ["-DBUILD_STATIC_LIBS=ON", "-DBUILD_TESTING=ON"]))
        steps.append(run("compile-libaec", ["cmake", "--build", str(aec), "--parallel", "2"]))
        steps.append(run("test-libaec", ["ctest", "--test-dir", str(aec), "--output-on-failure", "--timeout", "60"], 300))
        steps.append(run("stage-libaec", ["cmake", "--install", str(aec)]))
        options = ["-Decbuild_DIR=" + str(sources["ecbuild"] / "cmake"),
                   "-DAEC_LIBRARY=" + str(prefix / "lib/libaec.a"), "-DAEC_INCLUDE_DIR=" + str(prefix / "include"),
                   "-DFETCHCONTENT_FULLY_DISCONNECTED=ON", "-DENABLE_AEC=ON", "-DENABLE_MEMFS=ON",
                   "-DENABLE_PRODUCT_GRIB=ON", "-DENABLE_PRODUCT_BUFR=OFF", "-DENABLE_GEOGRAPHY=ON",
                   "-DENABLE_ECKIT_GEO=OFF", "-DENABLE_FORTRAN=OFF", "-DENABLE_NETCDF=OFF",
                   "-DENABLE_JPG=OFF", "-DENABLE_PNG=OFF", "-DENABLE_EXAMPLES=OFF",
                   "-DENABLE_EXTRA_TESTS=OFF", "-DENABLE_TESTS=OFF"]
        steps.append(run("configure-eccodes", ["cmake", "-S", str(sources["eccodes"]), "-B", str(ecc)] + common + options))
        steps.append(run("compile-eccodes", ["cmake", "--build", str(ecc), "--target", "grib_ls", "codes_info", "--parallel", "2"]))
        steps.append(run("version-eccodes", [str(ecc / "bin/grib_ls"), "-V"], 30))
        for source in pin["sources"]:
            verify_source(sources[source["name"]], BUILD / "downloads" / source["archive"])
        report.update(compiled=True, steps=steps, required_environment={}, embedded_definitions=True,
                      static_libraries=["ecCodes", "ecCodes memfs", "libaec"],
                      system_runtime_libraries=True, grib_decode_proven=False,
                      original_sources_unchanged=True, build_script_sha256=digest(Path(__file__)))
        report["artifacts"] = [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": digest(p)}
                               for p in (ecc / "bin/grib_ls", ecc / "bin/codes_info", prefix / "lib/libaec.a")]
        (BUILD / "build-receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
