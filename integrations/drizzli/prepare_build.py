#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Pin upstream Paraglide plugin bytes locally before executing build tools."""
import argparse
import base64
import hashlib
import io
import json
import pathlib
import subprocess
import tarfile
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LIMIT = 2 * 1024 * 1024


def prepare(stage):
    stage = pathlib.Path(stage).resolve(strict=True)
    if stage.parent != (ROOT / "build").resolve():
        raise ValueError("stage must be a direct child of the repository build directory")
    expected = json.loads((HERE / "upstream.json").read_text())["commit"]
    head = subprocess.check_output(["git", "-C", str(stage), "rev-parse", "HEAD"], text=True).strip()
    if head != expected:
        raise ValueError("stage has the wrong upstream revision")
    plugins = json.loads((HERE / "build-plugins.json").read_text())["plugins"]
    path = stage / "project.inlang/settings.json"
    settings = json.loads(path.read_text())
    modules = ["./volparossa-build-plugins/" + p["local_name"] + ".mjs" for p in plugins]
    if settings["modules"] not in [[p["upstream_module"] for p in plugins], modules]:
        raise ValueError("unreviewed upstream localization plugins")
    directory = stage / "volparossa-build-plugins"
    if directory.is_symlink():
        raise ValueError("plugin directory cannot be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    for plugin in plugins:
        with urllib.request.urlopen(plugin["url"], timeout=30) as response:
            data = response.read(LIMIT + 1)
        if len(data) > LIMIT or "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode() != plugin["integrity"]:
            raise ValueError("plugin archive integrity failed")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member_name, suffix in [("package/dist/index.js", ".mjs"), ("package/LICENSE", ".LICENSE")]:
                member = archive.getmember(member_name)
                if not member.isfile() or member.size > LIMIT:
                    raise ValueError("invalid plugin archive member")
                content = archive.extractfile(member).read(LIMIT + 1)
                if len(content) != member.size:
                    raise ValueError("invalid plugin member length")
                target = directory / (plugin["local_name"] + suffix)
                if target.is_symlink():
                    raise ValueError("plugin file cannot be a symlink")
                if target.exists():
                    if target.read_bytes() != content:
                        raise ValueError("existing plugin changed")
                else:
                    with target.open("xb") as output:
                        output.write(content)
    settings["modules"] = modules
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return {"schema": 1, "local_plugins": len(plugins), "sha512_verified": True,
            "license_notices_preserved": True, "plugin_execution": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage) if args.execute else
                     {"execute": False, "downloads": "two pinned npm plugin tarballs", "plugin_execution": False}))
