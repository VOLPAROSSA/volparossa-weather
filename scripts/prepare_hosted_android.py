#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Materialize fixed official Android inputs, without installing/executing them.

Google publishes SHA1 for these historical archives. That published checksum,
exact HTTPS URL and size are acquisition pins; the separately observed SHA256
is provenance, not an independently reviewed SHA256 or release authorization.
All archive notices are retained. Only the explicit --fetch action networks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import runpy
import stat
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
R = runpy.run_path(str(Path(__file__).with_name("prepare_hosted_runtime.py")))
require, regular, deadline = R["require"], R["regular_input"], R["deadline"]
GOOGLE = "https://dl.google.com/android/repository/"
REPOSITORY = GOOGLE + "repository2-3.xml"
SYSTEM_IMAGES = GOOGLE + "sys-img/android/sys-img2-3.xml"
# name: archive, bytes, published SHA1, installed path, source.properties revision
GOOGLE_INPUTS = {
    "platform": ("platform-36_r02.zip", 65878410, "2c1a80dd4d9f7d0e6dd336ec603d9b5c55a6f576", "sdk/platforms/android-36", "2"),
    # The locked plugins retain their own compileSdk: dynamic_system_colors
    # requires 34; home_widget, jni/jni_flutter and workmanager_android require
    # 35. Materialize these exact platforms instead of rewriting plugin source
    # or allowing Gradle/sdkmanager to install into the read-only SDK.
    "platform-34": ("platform-34-ext7_r03.zip", 63180081, "1f2e9478d6a7601425ceaa553311dc43191f103d", "sdk/platforms/android-34", "3"),
    "platform-35": ("platform-35_r02.zip", 64273788, "0bb560a90a7a2cbd0dd8348224d518b638fe7949", "sdk/platforms/android-35", "2"),
    "build-tools": ("build-tools_r35_linux.zip", 61958799, "2cfaa0bbb2336e9ec18ed3ecea84fa2e2af607bc", "sdk/build-tools/35.0.0", "35.0.0"),
    "ndk": ("android-ndk-r28c-linux.zip", 722261334, "a7b54a5de87fecd125a17d54f73c446199e72a64", "sdk/ndk/28.2.13676358", "28.2.13676358"),
    "command-line": ("commandlinetools-linux-13114758_latest.zip", 164760899, "5fdcc763663eefb86a5b8879697aa6088b041e70", "sdk/cmdline-tools/19.0", "19.0"),
    "platform-tools": ("platform-tools_r37.0.1-linux.zip", 9054187, "477254aa5f903c15cf51001717bdf347fb6b53e0", "sdk/platform-tools", "37.0.1"),
    "emulator": ("emulator-linux_x64-16428233.zip", 349654171, "cd7362ea55dfb86a418958138dc396e74165dd01", "sdk/emulator", "37.2.12"),
    "system-image": ("sys-img/android/x86_64-36_r02.zip", 844217077, "829c076e8ff448a336097ae25a355b495ba36e2c", "sdk/system-images/android-36/default/x86_64", "2"),
}
GRADLE = dict(url="https://services.gradle.org/distributions/gradle-8.13-all.zip", bytes=232036537,
    algorithm="sha256", digest="fba8464465835e74f7270bbf43d6d8a8d7709ab0a43ce1aa3323f73e9aa0c612",
    checksum_source="https://services.gradle.org/distributions/gradle-8.13-all.zip.sha256")
MAX_MEMBERS = 150000
MAX_FILE = 4 * 1024**3
MAX_EXPANDED = 12 * 1024**3
CHUNK = 1024**2


def pins():
    result = {name: dict(url=GOOGLE + row[0], bytes=row[1], algorithm="sha1", digest=row[2],
        destination=row[3], revision=row[4], checksum_source=SYSTEM_IMAGES if name == "system-image" else REPOSITORY)
        for name, row in GOOGLE_INPUTS.items()}
    return dict(result, gradle=GRADLE)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def safe(name):
    require(type(name) is str and 0 < len(name) <= 512 and "\\" not in name
        and not any(ord(c) < 32 or ord(c) > 126 for c in name), "ARCHIVE_PATH")
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in name.split("/"))
        and len(path.parts) <= 32, "ARCHIVE_PATH")
    return name


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, url):
        self.original, self.count = url, 0

    def redirect_request(self, request, fp, code, message, headers, url):
        self.count += 1
        parsed = urllib.parse.urlsplit(url)
        expected = "https://github.com/gradle/gradle-distributions/releases/download/v8.13.0/gradle-8.13-all.zip"
        require(self.original == GRADLE["url"] and self.count <= 2 and parsed.scheme == "https"
            and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and (url == expected or parsed.hostname == "release-assets.githubusercontent.com"), "UNEXPECTED_REDIRECT")
        return super().redirect_request(request, fp, code, message, headers, url)


def phase_budget(end, maximum):
    remaining = end - time.monotonic()
    require(remaining > 0, "MATERIALIZATION_DEADLINE")
    return min(maximum, remaining)


class ArchiveDigestError(ValueError):
    """Rejected bytes only; never carry a URL, response body or headers."""
    def __init__(self, size, digest, sha256):
        super().__init__("ARCHIVE_DIGEST")
        self.received_bytes = size
        self.observed_digest = digest
        self.observed_sha256 = sha256


def save_download_failure(output, name, pin, error):
    """One closed receipt for a known pin; failed archives remain unaccepted."""
    require(name in (*GOOGLE_INPUTS, "gradle") and pin == pins()[name], "DOWNLOAD_FAILURE_PIN")
    expected = 40 if pin["algorithm"] == "sha1" else 64
    require(isinstance(error, ArchiveDigestError) and type(error.received_bytes) is int
        and 0 <= error.received_bytes <= pin["bytes"]
        and re.fullmatch(r"[0-9a-f]{" + str(expected) + "}", error.observed_digest)
        and R["hex64"](error.observed_sha256)
        and (pin["algorithm"] != "sha256" or error.observed_digest == error.observed_sha256)
        and (error.received_bytes != pin["bytes"] or error.observed_digest != pin["digest"]), "DOWNLOAD_FAILURE_FIELDS")
    info = output.lstat()
    require(output.resolve() == output and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "DOWNLOAD_FAILURE_DIRECTORY")
    raw = canonical(dict(schema=1, kind="hosted-android-download-failure", code="ARCHIVE_DIGEST",
        package=name, algorithm=pin["algorithm"], expected_bytes=pin["bytes"], received_bytes=error.received_bytes,
        expected_digest=pin["digest"], observed_digest=error.observed_digest, observed_sha256=error.observed_sha256,
        archive_accepted=False, runtime_executed=False))
    require(len(raw) <= 1024, "DOWNLOAD_FAILURE_BOUND")
    fd = os.open(output / "download-failure.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def download(pin, target, *, seconds=600):
    sha = hashlib.sha256()
    published = hashlib.new(pin["algorithm"])
    size = 0
    # One request chain only: no mirror, rotation or automatic retry.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects(pin["url"]))
    require(0 < seconds <= 600, "DOWNLOAD_DEADLINE_BOUND")
    with deadline(seconds), opener.open(pin["url"], timeout=30) as response, target.open("xb") as out:
        os.chmod(target, 0o600)
        require(response.status == 200, "ARCHIVE_HTTP_STATUS")
        length = response.headers.get("Content-Length")
        require(length is None or length == str(pin["bytes"]), "ARCHIVE_HTTP_SIZE")
        while part := response.read(CHUNK):
            size += len(part)
            require(size <= pin["bytes"], "ARCHIVE_SIZE")
            sha.update(part)
            published.update(part)
            out.write(part)
    if size != pin["bytes"] or published.hexdigest() != pin["digest"]:
        raise ArchiveDigestError(size, published.hexdigest(), sha.hexdigest())
    return dict(pin, observed_sha256=sha.hexdigest())


def extract(stream, output):
    """Strip exactly one archive root; retain safe internal links without following them."""
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
        require(1 <= len(entries) <= MAX_MEMBERS, "ARCHIVE_ENTRIES")
        records, roots, total = {}, set(), 0
        for item in entries:
            name = safe(item.filename.rstrip("/"))
            roots.add(name.split("/")[0])
            relative = name.partition("/")[2]
            if not relative:
                require(item.is_dir(), "ARCHIVE_ROOT")
                continue
            require(relative not in records and not item.flag_bits & 1, "ARCHIVE_DUPLICATE_OR_ENCRYPTED")
            mode = item.external_attr >> 16
            kind = "directory" if item.is_dir() else "link" if stat.S_ISLNK(mode) else "file"
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)
                and not mode & 0o7000, "ARCHIVE_FILE_TYPE")
            require(0 <= item.file_size <= MAX_FILE and (kind != "link" or item.file_size <= 512), "ARCHIVE_FILE_SIZE")
            total += item.file_size
            require(total <= MAX_EXPANDED, "ARCHIVE_EXPANSION")
            records[relative] = (kind, item, mode)
        require(len(roots) == 1, "ARCHIVE_ROOTS")
        for name in records:
            for parent in PurePosixPath(name).parents:
                if str(parent) != "." and str(parent) in records:
                    require(records[str(parent)][0] == "directory", "ARCHIVE_NON_DIRECTORY_PARENT")
        links = {}
        for name, (kind, item, _) in records.items():
            if kind == "link":
                target = archive.read(item).decode("ascii")
                require(0 < len(target) <= 512 and not target.startswith("/") and "\\" not in target
                    and not any(ord(c) < 32 for c in target), "ARCHIVE_LINK")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                safe(resolved)
                require(resolved in records, "ARCHIVE_LINK_MISSING")
                links[name] = (target, resolved)
        for name in links:
            target, seen = name, set()
            while target in links:
                require(target not in seen and len(seen) < 16, "ARCHIVE_LINK_CYCLE")
                seen.add(target)
                target = links[target][1]
        output.mkdir(mode=0o700, parents=True)
        result = {}
        for name, (kind, item, mode) in sorted(records.items()):
            path = output / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if kind == "directory":
                path.mkdir(mode=0o700, exist_ok=True)
            elif kind == "file":
                sha, size = hashlib.sha256(), 0
                with archive.open(item) as source, path.open("xb") as out:
                    while part := source.read(CHUNK):
                        size += len(part)
                        require(size <= item.file_size, "ARCHIVE_FILE_EXPANSION")
                        sha.update(part)
                        out.write(part)
                require(size == item.file_size, "ARCHIVE_FILE_TRUNCATED")
                permissions = 0o700 if mode & 0o111 else 0o600
                os.chmod(path, permissions)
                result[name] = dict(kind="file", bytes=size, sha256=sha.hexdigest(), mode=permissions)
        # Create links last; no archive-controlled path is traversed during writes.
        for name, (target, _) in links.items():
            (output / name).symlink_to(target)
            result[name] = dict(kind="link", target=target)
        return result


def verify(output):
    output = Path(output)
    info = output.lstat()
    require(output.resolve() == output and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700, "INPUT_ROOT")
    with regular(output / "provenance.json") as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536, "PROVENANCE_BOUND")
    value = json.loads(raw, object_pairs_hook=R["unique_pairs"])
    require(set(value) == {"schema", "kind", "inputs", "inventory_sha256", "files", "runtime_executed", "independent_sha256_authority"}
        and type(value["schema"]) is int and value["schema"] == 1
        and value["kind"] == "hosted-android-materialization" and value["runtime_executed"] is False
        and value["independent_sha256_authority"] is False and set(value["inputs"]) == set(pins()), "PROVENANCE_SCHEMA")
    for name, pin in pins().items():
        item = value["inputs"][name]
        require(set(item) == set(pin) | {"observed_sha256"} and all(item[k] == v for k, v in pin.items())
            and R["hex64"](item["observed_sha256"]), "INPUT_PIN")
    with regular(output / "inventory.json") as stream:
        inventory = stream.read(48 * 1024**2 + 1)
    require(len(inventory) <= 48 * 1024**2 and hashlib.sha256(inventory).hexdigest() == value["inventory_sha256"], "INVENTORY_HASH")
    expected = json.loads(inventory, object_pairs_hook=R["unique_pairs"])
    require(type(expected) is dict and len(expected) == value["files"] and len(expected) <= MAX_MEMBERS, "INVENTORY_BOUND")
    actual, pending, count = set(), [output], 0
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                count += 1
                require(count <= MAX_MEMBERS * 2, "TREE_BOUND")
                name = safe(Path(child.path).relative_to(output).as_posix())
                info = child.stat(follow_symlinks=False)
                require(info.st_uid == os.getuid(), "TREE_OWNER")
                if stat.S_ISDIR(info.st_mode):
                    require(not info.st_mode & 0o022, "TREE_MODE")
                    pending.append(Path(child.path))
                elif name not in ("provenance.json", "inventory.json"):
                    actual.add(name)
    require(actual == set(expected), "TREE_CLOSURE")
    for name, item in expected.items():
        safe(name)
        path = output / name
        if item["kind"] == "link":
            require(set(item) == {"kind", "target"} and path.is_symlink() and os.readlink(path) == item["target"]
                and path.resolve().is_relative_to(output), "TREE_LINK")
        else:
            require(set(item) == {"kind", "bytes", "sha256", "mode"} and item["kind"] == "file", "TREE_RECORD")
            with regular(path) as stream:
                info = os.fstat(stream.fileno())
                require(info.st_size == item["bytes"] and stat.S_IMODE(info.st_mode) == item["mode"]
                    and hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"], "TREE_BYTES")
    return dict(schema=1, provenance_sha256=hashlib.sha256(raw).hexdigest(),
        inventory_sha256=value["inventory_sha256"], files=len(expected), runtime_executed=False)


def materialize(output):
    # One monotonic whole-operation budget; each sequential blocking phase
    # installs exactly ONE process alarm, clipped to the same absolute end.
    # The shared alarm helper deliberately rejects nesting and stays unchanged.
    end = time.monotonic() + 2400
    inputs, records = {}, {}
    for name, pin in pins().items():
        archive = output / ("gradle-8.13-all.zip" if name == "gradle" else "." + name + ".zip")
        try:
            inputs[name] = download(pin, archive, seconds=phase_budget(end, 600))
        except ArchiveDigestError as error:
            try:
                save_download_failure(output, name, pin, error)
            except (OSError, ValueError, TypeError):
                # Optional diagnostic failure must not replace the original
                # rejection or authorize extraction/execution/retry.
                pass
            raise
        if name == "gradle":
            records[archive.name] = dict(kind="file", bytes=pin["bytes"], sha256=pin["digest"], mode=0o600)
            continue
        with deadline(phase_budget(end, 240)):
            with regular(archive) as stream:
                entries = extract(stream, output / pin["destination"])
            source = output / pin["destination"] / "source.properties"
            with regular(source) as stream:
                properties = stream.read(65537).decode("utf-8")
            require(len(properties) <= 65536 and re.search(r"(?m)^Pkg.Revision\s*=\s*" + re.escape(pin["revision"]) + r"\s*$", properties), "PACKAGE_REVISION")
            records.update({pin["destination"] + "/" + k: v for k, v in entries.items()})
            require(len(records) <= MAX_MEMBERS, "TOTAL_FILE_BOUND")
            require(sum(v.get("bytes", 0) for v in records.values()) <= MAX_EXPANDED, "TOTAL_EXPANSION_BOUND")
            archive.unlink()
    with deadline(phase_budget(end, 2400)):
        inventory = canonical(records)
        (output / "inventory.json").write_bytes(inventory)
        (output / "provenance.json").write_bytes(canonical(dict(schema=1, kind="hosted-android-materialization",
            inputs=inputs, inventory_sha256=hashlib.sha256(inventory).hexdigest(), files=len(records),
            runtime_executed=False, independent_sha256_authority=False)))
        return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(args.fetch and args.output.is_absolute() and args.output.parent == ROOT / "build"
        and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", args.output.name), "EXPLICIT_NEW_OUTPUT_REQUIRED")
    info = args.output.parent.lstat()
    require(args.output.parent.resolve() == args.output.parent and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid() and not info.st_mode & 0o022, "PRIVATE_OUTPUT_PARENT")
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    print(json.dumps(materialize(args.output)))


if __name__ == "__main__":
    main()
