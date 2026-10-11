#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Stage the exact upstream Overmorrow tree plus the reviewed provider/UI patch.

This does not install dependencies, download a toolchain, build, run the app or
acquire weather. An existing local source clone may supply the pinned Git object;
its worktree changes are never copied. Failed stages remain for inspection.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(path, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(path), *args],
                          check=True, text=True, capture_output=True, timeout=240,
                          umask=0o077).stdout.strip()


def stage(destination, source=None):
    pin = json.loads((HERE / "upstream.json").read_text())
    destination = pathlib.Path(destination).absolute()
    build = (ROOT / "build").resolve()
    if destination.exists() or destination.is_symlink() or destination.parent.resolve() != build:
        raise ValueError("destination must be a new direct child of the repository build directory")
    if digest(HERE / "upstream.patch") != pin["upstream_patch_sha256"]:
        raise ValueError("patch changed; review and update provenance")
    origin = pin["origin"]
    if source:
        origin = str(pathlib.Path(source).resolve(strict=True))
        if git(origin, "rev-parse", pin["commit"] + "^{commit}") != pin["commit"]:
            raise ValueError("local source does not contain the pinned upstream commit")
    destination.mkdir(mode=0o700)
    git(destination, "init", "--quiet")
    git(destination, "remote", "add", "origin", pin["origin"])
    git(destination, "fetch", "--depth=1", origin, pin["commit"])
    git(destination, "checkout", "--detach", pin["commit"])
    if git(destination, "rev-parse", "HEAD^{tree}") != pin["tree"]:
        raise ValueError("upstream tree mismatch")
    instructions = [p for p in git(destination, "ls-files").splitlines()
                    if pathlib.PurePosixPath(p).name.lower() == "agents.md"]
    if instructions != pin["upstream_agents_files"]:
        raise ValueError("unreviewed upstream instructions")
    for relative, expected in [("LICENSE", pin["license_sha256"]),
                               ("pubspec.lock", pin["pubspec_lock_sha256"])]:
        if digest(destination / relative) != expected:
            raise ValueError("upstream license or lock mismatch")
    git(destination, "apply", "--check", str(HERE / "upstream.patch"))
    git(destination, "apply", str(HERE / "upstream.patch"))
    overlay = HERE / "overlay"
    for source_file in sorted(overlay.rglob("*")):
        if source_file.is_symlink():
            raise ValueError("overlay symlink forbidden")
        if not source_file.is_file():
            continue
        target = destination / source_file.relative_to(overlay)
        if target.exists() or target.is_symlink():
            raise ValueError("overlay may not overwrite upstream files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
        target.chmod(0o600)
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE.VOLPAROSSA")
    (destination / "LICENSE.VOLPAROSSA").chmod(0o600)
    git(destination, "diff", "--check")
    return {"schema": 1, "upstream_commit": pin["commit"], "staged": True,
            "dependencies_installed": False, "built": False, "browser_tested": False,
            "native_clients_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--source-clone")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"execute": False, "action": "stage pinned upstream and reviewed overlay only",
                          "install_dependencies": False, "run_upstream_scripts": False}))
    else:
        print(json.dumps(stage(args.destination, args.source_clone)))
