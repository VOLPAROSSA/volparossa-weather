#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run the pinned Flutter toolchain in a workspace-only Linux build sandbox.

No SDK acquisition or global installation is performed. Only the dependencies
action has Internet access; pub must honor the reviewed upstream lockfile.
HOME keeps its original value but resolves to an isolated workspace directory
inside the mount namespace. Host credentials/configuration are not mounted.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SDK_FILES = {
    "bin/cache/dart-sdk/bin/dart": "f3fbfdaace334c5a2f5f6612d4b9b98f8798839ef6af6ef5a8c4bdb0ae28c053",
    "bin/cache/flutter_tools.snapshot": "8274c6df84b0acd7023e2242c32b9b13f25186857181506526a2d363900aebc1",
}
ACTIONS = {
    "version": ["--version", "--machine"],
    "dependencies": ["pub", "get", "--enforce-lockfile"],
    "dependencies-offline": ["pub", "get", "--offline", "--enforce-lockfile"],
    "build": ["build", "web", "--release", "--no-pub", "--no-wasm-dry-run",
              "--dart-define=VOLPAROSSA_WEATHER=true"],
    "test": ["test", "--no-pub", "--reporter=expanded", "--concurrency=2",
             "--dart-define=VOLPAROSSA_WEATHER=true", "test/volparossa_products_test.dart",
             "test/volparossa_provider_test.dart", "test/volparossa_ui_test.dart"],
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(path, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(path), *args],
                          check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def build_command(sdk, stage, work, action):
    pin = json.loads((HERE / "upstream.json").read_text())
    sdk, stage, work = (pathlib.Path(p).absolute() for p in (sdk, stage, work))
    for path in (sdk, stage):
        if path.resolve(strict=True) != path or not path.is_dir():
            raise ValueError("SDK and stage must be real absolute directories")
    build = ROOT / "build"
    common_name = pathlib.Path(git(ROOT, "rev-parse", "--git-common-dir"))
    common = (common_name if common_name.is_absolute() else ROOT / common_name).resolve()
    core_workspace = common.parent.parent / "Volparossa"
    if not (sdk.is_relative_to(build) or sdk.is_relative_to(core_workspace)):
        raise ValueError("SDK must remain in the application build directory or sibling core workspace")
    if (build.resolve() != build or stage.parent != build or work.parent != build
            or work.parent.resolve() != build):
        raise ValueError("stage/work must be direct children of this repository's build directory")
    if work.exists() and (work.resolve() != work or not work.is_dir()):
        raise ValueError("invalid work directory")
    if stage == work or sdk == work or sdk in work.parents or work in sdk.parents:
        raise ValueError("build inputs and work directory must be separate")
    if git(sdk, "rev-parse", "HEAD") != pin["flutter_commit"]:
        raise ValueError("unexpected Flutter commit")
    if git(sdk, "status", "--porcelain", "--untracked-files=no") or git(sdk, "ls-files", "--others", "bin/internal"):
        raise ValueError("modified Flutter source or unreviewed bootstrap files")
    for relative, expected in SDK_FILES.items():
        if digest(sdk / relative) != expected:
            raise ValueError("Flutter archive executable mismatch")
    if (git(stage, "rev-parse", "HEAD") != pin["commit"]
            or digest(stage / "pubspec.lock") != pin["pubspec_lock_sha256"]):
        raise ValueError("unexpected upstream commit or dependency lock")
    original_home = pathlib.Path(os.environ["HOME"])
    if not original_home.is_absolute() or str(original_home) in ("/", "/home"):
        raise ValueError("invalid existing home directory")
    work.mkdir(mode=0o700, exist_ok=True)
    if work.stat().st_uid != os.getuid() or stat.S_IMODE(work.stat().st_mode) != 0o700:
        raise ValueError("sandbox work directory must be private and owned by this user")
    for name in ("home", "config", "cache", "pub-cache"):
        target = work / name
        target.mkdir(mode=0o700, exist_ok=True)
        if (target.resolve() != target or target.stat().st_uid != os.getuid()
                or stat.S_IMODE(target.stat().st_mode) != 0o700):
            raise ValueError("invalid sandbox state directory")
    command = ["bwrap", "--die-with-parent", "--new-session", "--unshare-user",
               "--unshare-pid", "--unshare-ipc", "--unshare-uts",
               "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
               "--symlink", "usr/sbin", "/sbin", "--symlink", "usr/lib", "/lib",
               "--symlink", "usr/lib64", "/lib64", "--proc", "/proc",
               "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/etc/ssl", "/etc/alternatives", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
                 "/etc/passwd", "/etc/group"):
        command += ["--ro-bind", path, path]
    command += ["--bind", str(sdk), str(sdk), "--bind", str(stage), str(stage),
                "--bind", str(work), str(work), "--bind", str(work / "home"), str(original_home),
                "--chdir", str(stage)]
    if action != "dependencies":
        command += ["--unshare-net"]
    command += [str(sdk / "bin/flutter"), "--no-version-check", "--suppress-analytics", *ACTIONS[action]]
    # Keep the original HOME value, never redirect the developer's own config.
    environment = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "LANG") if key in os.environ}
    environment.update({"PATH": f"{sdk}/bin:/usr/bin:/bin", "CI": "true", "BOT": "true",
                        "FLUTTER_SUPPRESS_ANALYTICS": "true", "DART_SUPPRESS_ANALYTICS": "true",
                        "XDG_CONFIG_HOME": str(work / "config"), "XDG_CACHE_HOME": str(work / "cache"),
                        "PUB_CACHE": str(work / "pub-cache"), "TZ": "UTC"})
    cpus = sorted(os.sched_getaffinity(0))[:2]
    command = ["nice", "-n", "10", "taskset", "-c", ",".join(map(str, cpus)), *command]
    return command, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--action", choices=ACTIONS, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"execute": False, "action": args.action,
                          "network": args.action == "dependencies", "global_installation": False}))
        return
    if not shutil.which("bwrap") or not shutil.which("taskset"):
        raise ValueError("Linux bubblewrap and taskset are required; no unsandboxed fallback")
    command, environment = build_command(args.sdk, args.stage, args.work, args.action)
    result = subprocess.run(command, env=environment, timeout=1200, check=False, umask=0o077)
    pin = json.loads((HERE / "upstream.json").read_text())
    if digest(pathlib.Path(args.stage) / "pubspec.lock") != pin["pubspec_lock_sha256"]:
        raise ValueError("dependency action changed the pinned lockfile")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
