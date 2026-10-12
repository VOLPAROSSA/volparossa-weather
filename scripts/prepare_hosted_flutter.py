#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Materialize the exact official Flutter SDK; never execute or install it.

Only --fetch authorizes the single fixed HTTPS request. Partial outputs are
retained without success provenance and never reused. The build wrapper must
still verify the SDK Git commit/tracked source before any sandboxed execution.
"""
import argparse
import hashlib
import json
import lzma
import math
import os
from pathlib import Path
import runpy
import stat
import tarfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "integrations/overmorrow/upstream.json"
R = runpy.run_path(str(Path(__file__).with_name("prepare_hosted_runtime.py")))
require, regular_input, deadline = R["require"], R["regular_input"], R["deadline"]
VERSION = "3.38.5"
COMMIT = "f6ff1529fd6d8af5f706051d9251ac9231c83407"
ARCHIVE_SHA = "a264940cfc431c1778f34f7413fa6ab71443ad52c71f38c50b0284397a4039b0"
ARCHIVE_BYTES = 1464510340
URL = "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.38.5-stable.tar.xz"
METADATA_URL = "https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json"
SDK_FILES = {
    "bin/cache/dart-sdk/bin/dart": "f3fbfdaace334c5a2f5f6612d4b9b98f8798839ef6af6ef5a8c4bdb0ae28c053",
    "bin/cache/flutter_tools.snapshot": "8274c6df84b0acd7023e2242c32b9b13f25186857181506526a2d363900aebc1",
}
MAX_EXPANDED = 3 * 1024**3
MAX_FILE = 256 * 1024**2
MAX_MEMBERS = 40000
MAX_FILES = 25000
MAX_PROVENANCE = 32768
MAX_INVENTORY = 8 * 1024**2
CHUNK = 65536
DOWNLOAD_SECONDS = 600
EXTRACT_SECONDS = 300
RESERVED = frozenset(("provenance.json", "sdk-inventory.json", ".sdk-archive.tar.xz"))
# Flutter 3.38.5 shared.sh/update_engine_version.sh and cache.dart write these
# non-executable cache metadata files. All original binaries, libraries, source
# and .git bytes remain immutable, even in the subsequent build-state check.
MUTABLE_CACHE = frozenset("bin/cache/" + name for name in (
    "lockfile", ".dartignore", "engine.realm", "engine.stamp", "engine_stamp.json",
    "flutter.version.json", "flutter_tools.stamp", "libimobiledeviceglue.stamp",
    "ios-deploy.stamp", "libimobiledevice.stamp", "linux-sdk.stamp", "openssl.stamp",
    "windows-sdk.stamp", "macos-sdk.stamp", "gradle_wrapper.stamp", "engine_stamp.stamp",
    "libplist.stamp", "android-internal-build-artifacts.stamp", "font-subset.stamp",
    "libusbmuxd.stamp", "engine-dart-sdk.stamp", "flutter_web_sdk.stamp", "ios-sdk.stamp",
    "flutter_sdk.stamp", "material_fonts.stamp", "android-sdk.stamp",
))


def load_pin():
    with regular_input(PIN) as stream:
        raw = stream.read(32769)
    require(len(raw) <= 32768, "Overmorrow pin is oversized")
    pin = json.loads(raw, object_pairs_hook=R["unique_pairs"])
    require(type(pin) is dict and pin.get("flutter") == VERSION
            and pin.get("flutter_commit") == COMMIT and pin.get("flutter_archive_sha256") == ARCHIVE_SHA,
            "Flutter differs from reviewed Overmorrow pin")
    return hashlib.sha256(raw).hexdigest()


def new_output(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    build = ROOT / "build"
    require(path.parent == build and path.name not in ("", ".", "..")
            and R["re"].fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", path.name),
            "Output must be a new direct child of this checkout's build/")
    build.mkdir(mode=0o700, exist_ok=True)
    info = build.lstat()
    require(build.resolve() == build and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022, "Build parent must be canonical, owned and not writable by others")
    path.mkdir(mode=0o700)
    return path


def acquire(output, opener_factory=urllib.request.build_opener):
    destination = output / ".sdk-archive.tar.xz"
    opener = opener_factory(R["ExactRedirect"](None))
    request = urllib.request.Request(URL, headers={"Accept-Encoding": "identity"})
    with deadline(DOWNLOAD_SECONDS):
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            error.close()
            raise
        with response:
            require(response.status == 200 and response.url == URL, "Unexpected Flutter source response")
            require(response.headers.get("Content-Encoding", "identity") == "identity"
                    and response.headers.get("Content-Length") in (None, str(ARCHIVE_BYTES)),
                    "Unexpected Flutter encoding or size")
            R["copy_verified"](response, destination, dict(bytes=ARCHIVE_BYTES, sha256=ARCHIVE_SHA))
    return destination


class BoundedXZ:
    def __init__(self, stream):
        self.stream = stream
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=128 * 1024**2)
        self.total, self.done = 0, False

    def read(self, size):
        require(type(size) is int and 0 < size <= MAX_EXPANDED + 1, "Invalid archive read size")
        result = bytearray()
        while len(result) < size and not self.done:
            chunk = self.stream.read(CHUNK) if self.decoder.needs_input else b""
            require(chunk or not self.decoder.needs_input, "Truncated Flutter XZ")
            decoded = self.decoder.decompress(chunk, max_length=min(size - len(result), MAX_EXPANDED + 1 - self.total))
            self.total += len(decoded)
            require(self.total <= MAX_EXPANDED, "Flutter expanded archive exceeds bound")
            result.extend(decoded)
            if self.decoder.eof:
                require(not self.decoder.unused_data and not self.stream.read(1), "Trailing Flutter XZ bytes")
                self.done = True
        return bytes(result)


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        # Check metadata lengths BEFORE tarfile buffers GNU/PAX extension data.
        require(0 <= self.size <= (8192 if self.type in (tarfile.GNUTYPE_LONGNAME,
            tarfile.GNUTYPE_LONGLINK, tarfile.XHDTYPE, tarfile.XGLTYPE) else MAX_FILE), "Oversized tar member")
        return super()._proc_member(archive)


def extract(stream, output):
    reader = BoundedXZ(stream)
    seen, records, total = set(), {}, 0
    with tarfile.open(fileobj=reader, mode="r|", tarinfo=BoundedTarInfo) as archive:
        for member in archive:
            name = R["safe_name"](member.name)
            require(name not in seen and len(seen) < MAX_MEMBERS, "Duplicate or excessive SDK members")
            seen.add(name)
            require(name == "flutter" or name.startswith("flutter/"), "Unexpected SDK archive root")
            # This pinned official SDK has no links. Reject all links rather
            # than changing their meaning or dereferencing any host paths.
            require(member.isdir() or member.isfile(), "SDK links and special files are not admitted")
            require(not member.mode & 0o7000 and member.sparse is None
                    and set(member.pax_headers) <= {"path", "mtime", "atime", "ctime"}, "Unsupported tar metadata")
            require(0 <= member.size <= MAX_FILE, "Oversized SDK file")
            require(type(member.mtime) in (int, float) and math.isfinite(member.mtime)
                    and 0 <= member.mtime <= 4102444800, "Invalid SDK modification time")
            total += member.size
            require(total <= MAX_EXPANDED, "SDK payload exceeds bound")
            if name == "flutter":
                require(member.isdir(), "SDK root must be a directory")
                continue
            relative = name[len("flutter/"):]
            require(relative not in RESERVED, "SDK collides with preparer state")
            path = output / relative
            R["private_parents"](path, output)
            if member.isdir():
                path.mkdir(mode=0o700, exist_ok=True)
                require(stat.S_ISDIR(path.lstat().st_mode), "SDK directory conflicts with file")
                continue
            require(len(records) < MAX_FILES, "Too many SDK files")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            digest, count = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as target, archive.extractfile(member) as source:
                while chunk := source.read(CHUNK):
                    count += len(chunk)
                    require(count <= member.size, "Oversized SDK payload")
                    target.write(chunk); digest.update(chunk)
            require(count == member.size, "Truncated SDK file")
            # shared.sh compares pubspec.yaml -nt pubspec.lock before using the
            # pinned snapshot. Extraction order must not trigger a tool rebuild.
            os.utime(path, (member.mtime, member.mtime), follow_symlinks=False)
            records[relative] = dict(bytes=count, sha256=digest.hexdigest(), mode=0o700 if member.mode & 0o111 else 0o600)
    while reader.read(CHUNK):
        pass
    for name, digest in SDK_FILES.items():
        require(records.get(name, {}).get("sha256") == digest, "SDK executable differs from existing build pin")
    require(records.get("bin/flutter", {}).get("mode") == 0o700
            and records.get("bin/cache/dart-sdk/bin/dart", {}).get("mode") == 0o700
            and records.get(".git/HEAD", {}).get("bytes", 0) > 0
            and records.get("LICENSE", {}).get("bytes", 0) > 0, "SDK bootstrap/Git/license missing")
    return records


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def inventory_sha256(records):
    return hashlib.sha256(canonical(records)).hexdigest()


def read_json(path, bound):
    with regular_input(path) as stream:
        raw = stream.read(bound + 1)
    require(len(raw) <= bound, "SDK receipt oversized")
    return json.loads(raw, object_pairs_hook=R["unique_pairs"]), raw


def verify_materialized(output, *, allow_build_state=False):
    """Check materialized bytes; Git HEAD/clean tracked source remain build.py's checks.

    Only explicitly listed, bounded cache metadata may change after a build.
    No .git mutation or executable/library replacement is admitted by that mode.
    """
    output = Path(output)
    info = output.lstat()
    require(output.resolve() == output and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, "SDK must be private and canonical")
    value, raw = read_json(output / "provenance.json", MAX_PROVENANCE)
    require(type(value) is dict and set(value) == {"schema", "kind", "pin_sha256", "preparer_sha256", "input",
            "files", "bytes", "inventory_sha256", "sdk_files", "scope"}
            and type(value["schema"]) is int and value["schema"] == 1 and value["kind"] == "hosted-flutter-sdk-materialization"
            and value["pin_sha256"] == load_pin() and value["preparer_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            and value["input"] == input_record() and value["scope"] == scope()
            and type(value["files"]) is int and 1 <= value["files"] <= MAX_FILES
            and type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_EXPANDED
            and value["sdk_files"] == SDK_FILES, "SDK provenance differs")
    expected, inventory = read_json(output / "sdk-inventory.json", MAX_INVENTORY)
    require(type(expected) is dict and len(expected) == value["files"]
            and value["inventory_sha256"] == hashlib.sha256(inventory).hexdigest()
            and inventory == canonical(expected), "SDK inventory differs")
    total = 0
    for name, item in expected.items():
        require(R["safe_name"](name) == name and name not in RESERVED
                and type(item) is dict and set(item) == {"bytes", "sha256", "mode"}
                and type(item["bytes"]) is int and 0 <= item["bytes"] <= MAX_FILE and R["hex64"](item["sha256"])
                and type(item["mode"]) is int and item["mode"] in (0o600, 0o700), "Invalid SDK file inventory")
        total += item["bytes"]
    require(total == value["bytes"], "SDK byte count differs")
    actual, pending, entries = set(), [output], 0
    while pending:
        # Iterate entries rather than materializing an entire directory first:
        # writable build-cache state may contain arbitrarily many empty dirs.
        with os.scandir(pending.pop()) as directory:
            for entry in directory:
                entries += 1
                require(entries <= MAX_MEMBERS, "SDK entry count exceeds bound")
                path = Path(entry.path)
                relative = str(path.relative_to(output))
                require(R["safe_name"](relative) == relative, "Unsafe SDK tree path")
                info = entry.stat(follow_symlinks=False)
                require(info.st_uid == os.getuid() and not info.st_mode & 0o022
                        and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)), "Unsafe SDK tree")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif relative not in ("provenance.json", "sdk-inventory.json"):
                    actual.add(relative)
                    require(len(actual) <= MAX_FILES, "SDK file count exceeds bound")
    mutable = lambda name: allow_build_state and name in MUTABLE_CACHE
    require({n for n in actual if not mutable(n)} == {n for n in expected if not mutable(n)}, "SDK file closure changed")
    for name in actual:
        if mutable(name):
            with regular_input(output / name) as stream:
                info = os.fstat(stream.fileno())
                require(info.st_size <= 65536 and not info.st_mode & 0o111, "Unsafe cache metadata")
    for name, item in expected.items():
        if mutable(name):
            continue
        with regular_input(output / name) as stream:
            info = os.fstat(stream.fileno())
            # name is an already validated, bounded public archive-relative
            # path; never include host paths, file contents or actual hashes.
            require(info.st_size == item["bytes"], f"SDK file changed: {name} (size)")
            require(stat.S_IMODE(info.st_mode) == item["mode"], f"SDK file changed: {name} (mode)")
            require(hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"],
                    f"SDK file changed: {name} (sha256)")
    require(all(expected.get(name, {}).get("sha256") == digest for name, digest in SDK_FILES.items()), "SDK pins changed")
    return dict(schema=1, provenance_sha256=hashlib.sha256(raw).hexdigest(),
                inventory_sha256=value["inventory_sha256"], files=value["files"], bytes=value["bytes"],
                input=value["input"], sdk_files=value["sdk_files"], runtime_executed=False)


def input_record():
    return dict(version=VERSION, commit=COMMIT, url=URL, bytes=ARCHIVE_BYTES, sha256=ARCHIVE_SHA, metadata_url=METADATA_URL)


def scope():
    return dict(runtime_executed=False, current_update_authority=False, host_installed=False,
                expected_sdk_hashes_verified=True, licenses_preserved=True)


def prepare(output, pin_sha):
    info = output.lstat()
    require(output.resolve() == output and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700 and not any(output.iterdir()), "SDK output must be fresh and private")
    archive = acquire(output)
    with regular_input(archive) as stream, deadline(EXTRACT_SECONDS):
        records = extract(stream, output)
    archive.unlink()
    value = dict(schema=1, kind="hosted-flutter-sdk-materialization", pin_sha256=pin_sha,
        preparer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), input=input_record(),
        files=len(records), bytes=sum(item["bytes"] for item in records.values()),
        inventory_sha256=inventory_sha256(records), sdk_files=SDK_FILES, scope=scope())
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    require(len(raw) <= MAX_PROVENANCE, "SDK provenance oversized")
    inventory = canonical(records)
    require(len(inventory) <= MAX_INVENTORY, "SDK inventory oversized")
    for name, item in records.items():
        os.chmod(output / name, item["mode"])
    for name, data in (("sdk-inventory.json", inventory), ("provenance.json", raw)):
        with os.fdopen(os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
            stream.write(data)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    pin_sha = load_pin()
    output = new_output(args.output)
    result = prepare(output, pin_sha)
    print(json.dumps(dict(schema=1, kind=result["kind"], success=True, files=result["files"],
        bytes=result["bytes"], inventory_sha256=result["inventory_sha256"], runtime_executed=False)))


if __name__ == "__main__":
    main()
