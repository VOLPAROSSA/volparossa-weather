#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Copy a bounded, self-hosted CanvasKit asset tree without altering build output.

The source is the actual Flutter web build. Unused Skwasm renderers, debug symbol
maps and the unregistered service worker are omitted; application assets,
CanvasKit variants and notices are retained. This does not launch a web service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MAX_FILE, MAX_TREE = 8 * 1024 * 1024, 32 * 1024 * 1024
ROOT_FILES = {"index.html", "version.json", "flutter.js", "main.dart.js", "favicon.png",
              "manifest.json", "flutter_bootstrap.js"}
RENDERER_FILES = {"canvaskit/canvaskit.js", "canvaskit/canvaskit.wasm",
                  "canvaskit/chromium/canvaskit.js", "canvaskit/chromium/canvaskit.wasm"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".ttf", ".otf", ".woff", ".woff2",
                    ".json", ".bin", ".frag"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(path, directory=False):
    info = path.lstat()
    if (path.resolve() != path or info.st_uid != os.getuid() or info.st_mode & 0o022
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and (info.st_nlink != 1 or info.st_size > MAX_FILE))):
        raise ValueError("unsafe or oversized build asset")
    return info


def eligible(relative):
    name = relative.as_posix()
    if name in (".last_build_id", "flutter_service_worker.js",
                "assets/packages/flutter_local_notifications_web/web/notifications_service_worker.js"):
        return False
    if name.startswith("canvaskit/") and (name.endswith(".symbols") or relative.name.startswith("skwasm")):
        return False
    if (name in ROOT_FILES | RENDERER_FILES or name == "assets/NOTICES"
            or relative.parts[0] == "assets" and relative.suffix in ASSET_EXTENSIONS
            or relative.parts[0] == "icons" and relative.suffix == ".png"):
        return True
    raise ValueError("unexpected Flutter output; review before publishing")


def deploy(stage, destination):
    stage, destination = Path(stage).absolute(), Path(destination).absolute()
    build = ROOT / "build"
    if (build.resolve() != build or stage.parent != build or stage.resolve() != stage
            or destination.parent != build or destination.exists() or destination.is_symlink()):
        raise ValueError("stage and new destination must be distinct direct workspace build children")
    source = stage / "build/web"
    checked(source, directory=True)
    files, omitted, total = {}, [], 0
    entries = sorted(source.rglob("*"))
    if len(entries) > 1024:
        raise ValueError("too many Flutter assets")
    for path in entries:
        info = checked(path, directory=path.is_dir())
        if stat.S_ISDIR(info.st_mode):
            continue
        relative = path.relative_to(source)
        if not eligible(relative):
            omitted.append(relative.as_posix())
            continue
        total += info.st_size
        if total > MAX_TREE:
            raise ValueError("bounded static bridge budget exceeded")
        files[relative.as_posix()] = (path, info.st_size, digest(path))
    if not ROOT_FILES | RENDERER_FILES | {"assets/NOTICES", "assets/AssetManifest.bin"} <= files.keys():
        raise ValueError("required application/renderer/notice asset missing")
    for name, path in (("LICENSE.txt", stage / "LICENSE"),
                       ("LICENSE.VOLPAROSSA.txt", stage / "LICENSE.VOLPAROSSA")):
        info = checked(path)
        total += info.st_size
        if total > MAX_TREE:
            raise ValueError("bounded static bridge budget exceeded")
        files[name] = (path, info.st_size, digest(path))
    destination.mkdir(mode=0o700)
    for name, (path, _, expected) in files.items():
        target = destination / name
        parent = destination
        for component in Path(name).parts[:-1]:
            parent /= component
            parent.mkdir(mode=0o700, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o600)
        if digest(target) != expected or digest(path) != expected:
            raise ValueError("build changed while copying; do not publish incomplete destination")
    manifest = {name: item[2] for name, item in sorted(files.items())}
    return {"schema": 1, "static_profile": "flutter-canvaskit", "files": len(files), "bytes": total,
            "tree_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                                      separators=(",", ":")).encode()).hexdigest(),
            "asset_sha256": manifest, "omitted": omitted, "browser_verified": False,
            "core_delivery_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(deploy(args.stage, args.destination) if args.execute else
                     {"execute": False, "action": "copy bounded self-hosted assets and notices"}, indent=2))
