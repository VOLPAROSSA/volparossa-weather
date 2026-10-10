#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Stage pinned Drizz.li plus reviewed local integration, without installing dependencies.

python3 integrations/drizzli/stage.py --execute --destination build/drizzli-volparossa
An optional --source-clone reads Git objects from an existing local checkout; its
working-tree changes are not imported. Without it, only the exact upstream SHA
is fetched. Failures leave the new directory for inspection, never erase it.
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


def git(destination, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(destination), *args],
                          check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=240).stdout.strip()


def stage(destination, source=None):
    metadata = json.loads((HERE / "upstream.json").read_text())
    destination = pathlib.Path(destination).absolute()
    build = (ROOT / "build").resolve()
    if destination.exists() or destination.is_symlink() or destination.parent.resolve() != build:
        raise ValueError("destination must be a new direct child of the repository build directory")
    if digest(HERE / "upstream.patch") != metadata["upstream_patch_sha256"]:
        raise ValueError("integration patch hash changed; review and update provenance")
    for relative, sha in metadata["weather_modules"].items():
        if digest(ROOT / relative) != sha:
            raise ValueError("Weather module changed; review client validation before updating provenance")
    origin = metadata["origin"]
    if source:
        origin = str(pathlib.Path(source).resolve(strict=True))
        if git(origin, "rev-parse", metadata["commit"] + "^{commit}") != metadata["commit"]:
            raise ValueError("local clone does not contain pinned commit")
    destination.mkdir(mode=0o700)
    git(destination, "init", "--quiet")
    git(destination, "remote", "add", "origin", metadata["origin"])
    fetch_options = ["--depth=1"] if source else ["--depth=1", "--filter=blob:none"]
    git(destination, "fetch", *fetch_options, origin, metadata["commit"])
    git(destination, "checkout", "--detach", metadata["commit"])
    if git(destination, "rev-parse", "HEAD^{tree}") != metadata["tree"]:
        raise ValueError("unexpected upstream tree")
    instructions = [name for name in git(destination, "ls-files").splitlines()
                    if pathlib.PurePosixPath(name).name.lower() == "agents.md"]
    if instructions != metadata["upstream_agents_files"]:
        raise ValueError("unreviewed upstream agent instructions")
    for path, expected in [("LICENSE", metadata["license_sha256"]),
                           ("package-lock.json", metadata["package_lock_sha256"])]:
        if digest(destination / path) != expected:
            raise ValueError("unexpected upstream license or dependency lock")
    git(destination, "apply", "--check", str(HERE / "upstream.patch"))
    git(destination, "apply", str(HERE / "upstream.patch"))
    overlay = HERE / "overlay"
    for source_file in sorted(overlay.rglob("*")):
        if source_file.is_symlink():
            raise ValueError("overlay symlinks are not supported")
        if not source_file.is_file():
            continue
        target = destination / source_file.relative_to(overlay)
        if target.exists():
            raise ValueError("overlay cannot overwrite upstream files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
    modules = destination / "src/lib/services/volparossa"
    for relative in metadata["weather_modules"]:
        target = modules / pathlib.Path(relative).name
        if target.exists():
            raise ValueError("unexpected Weather module target")
        shutil.copyfile(ROOT / relative, target)
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE.VOLPAROSSA")
    git(destination, "diff", "--check")
    return {"schema": 1, "upstream_commit": metadata["commit"], "staged": True,
            "dependencies_installed": False, "built": False, "browser_tested": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--source-clone")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"execute": False, "action": "stage exact upstream source and local patches only",
                          "install_dependencies": False, "run_upstream_scripts": False}))
    else:
        print(json.dumps(stage(args.destination, args.source_clone)))
