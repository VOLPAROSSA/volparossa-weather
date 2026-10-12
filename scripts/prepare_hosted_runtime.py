#!/usr/bin/env python3
"""Prepare pinned historical Node/Firefox, never install or execute either.

Use --fetch explicitly or supply --archives containing the exact archives.
Output is a NEW private direct child of this checkout's build/. On failure it
is retained for inspection, never reused or represented as successful. Only
Python's standard library is used; .deb control/maintainer scripts never run.
This is artifact preparation, not a browser proof or source-reproducible build.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import signal
import stat
import tarfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "third_party/hosted-runtime-inputs.json"
MAX_ARCHIVE = 96 * 1024**2
MAX_EXPANDED = 512 * 1024**2
MAX_FILE = 192 * 1024**2
MAX_MEMBERS = 30000
MAX_OUTPUT_FILES = 4096
MAX_PIN = 32768
CHUNK = 65536
DOWNLOAD_SECONDS = 180
EXTRACT_SECONDS = 120
# Exact layout of the checksum-pinned Debian package. These are relocations
# within the SAME archive, never permission to dereference a host filesystem
# symlink. In particular, browser/defaults/syspref remains excluded.
FIREFOX_DIRECTORIES = {
    "usr/lib/firefox-esr/browser/chrome": "usr/share/firefox-esr/browser/chrome",
    "usr/lib/firefox-esr/browser/defaults": "usr/share/firefox-esr/browser/defaults",
}
FIREFOX_ICONS = {
    f"usr/share/firefox-esr/browser/chrome/icons/default/default{size}.png":
        f"usr/share/icons/hicolor/{size}x{size}/apps/firefox-esr.png"
    for size in (16, 32, 48, 64, 128)
}
FIREFOX_ALIASES = {**FIREFOX_DIRECTORIES, **FIREFOX_ICONS}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def hex64(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def regular_input(path):
    # Open nonblocking until fstat proves this is a regular file: otherwise a
    # FIFO supplied as a cache entry could hang before any download deadline.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022,
                "Input must be a non-writable-by-others owned regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def load_pin():
    with regular_input(PIN) as stream:
        raw = stream.read(MAX_PIN + 1)
    require(len(raw) <= MAX_PIN, "Runtime pin is oversized")
    pin = json.loads(raw, object_pairs_hook=unique_pairs)
    require(type(pin) is dict and set(pin) == {"schema", "profile", "purpose", "artifacts"}
            and type(pin["schema"]) is int and pin["schema"] == 1
            and pin["profile"] == "historical-weather-linux-x64-2026-09"
            and isinstance(pin["purpose"], str) and len(pin["purpose"]) <= 256
            and type(pin["artifacts"]) is dict and set(pin["artifacts"]) == {"node", "firefox"},
            "Unsupported runtime pin")
    for name, item in pin["artifacts"].items():
        require(type(item) is dict and set(item) == {"version", "archive", "url", "redirect_url", "bytes",
                "sha256", "checksum_source", "prefix", "expected_files", "license_file", "abi"},
                "Unexpected runtime artifact fields")
        require(isinstance(item["archive"], str) and re.fullmatch(r"[a-zA-Z0-9._~-]+", item["archive"])
                and isinstance(item["version"], str) and re.fullmatch(r"[a-zA-Z0-9._~-]{1,80}", item["version"])
                and type(item["bytes"]) is int and 0 < item["bytes"] <= MAX_ARCHIVE
                and hex64(item["sha256"]), "Invalid archive pin")
        origin = "https://nodejs.org/" if name == "node" else "https://snapshot.debian.org/"
        for key in ("url", "checksum_source"):
            require(isinstance(item[key], str) and item[key].startswith(origin)
                    and not any(ord(c) < 33 for c in item[key]), "Unexpected artifact origin")
        require(item["redirect_url"] is None or name == "firefox"
                and isinstance(item["redirect_url"], str)
                and item["redirect_url"].startswith("https://snapshot.debian.org/file/")
                and not any(ord(c) < 33 for c in item["redirect_url"]), "Unexpected redirect pin")
        safe_name(item["prefix"])
        safe_name(item["license_file"])
        expected_names = ({"bin/node"} if name == "node" else
                          {"firefox-esr", "libxul.so", "omni.ja", "browser/omni.ja", "application.ini"})
        require(type(item["expected_files"]) is dict and set(item["expected_files"]) == expected_names,
                "Required runtime hashes missing")
        for entry in item["expected_files"].values():
            require(type(entry) is dict and set(entry) == {"bytes", "sha256"}
                    and type(entry["bytes"]) is int and 0 < entry["bytes"] <= MAX_FILE
                    and hex64(entry["sha256"]), "Invalid runtime file pin")
        require(type(item["abi"]) is dict and set(item["abi"]) == {"architecture", "glibc_min", "glibcxx_min"}
                and item["abi"]["architecture"] == "x86_64"
                and all(isinstance(item["abi"][key], str) and re.fullmatch(r"\d+(\.\d+){1,2}", item["abi"][key])
                        for key in ("glibc_min", "glibcxx_min")), "Invalid ABI metadata")
    return pin, hashlib.sha256(raw).hexdigest()


@contextmanager
def deadline(seconds):
    """A process-local absolute deadline also bounds blocking DNS/socket reads."""
    previous = signal.getsignal(signal.SIGALRM)
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "An outer process alarm is already active")

    def expired(_signal, _frame):
        raise TimeoutError("Runtime preparation phase deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class ExactRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, permitted):
        self.permitted = permitted
        self.count = 0

    def redirect_request(self, request, fp, code, message, headers, newurl):
        if self.count != 0 or newurl != self.permitted:
            fp.close()
            raise ValueError("Unexpected artifact redirect")
        self.count += 1
        return super().redirect_request(request, fp, code, message, headers, newurl)


def copy_verified(stream, path, item):
    total, checksum = 0, hashlib.sha256()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        while chunk := stream.read(min(CHUNK, item["bytes"] + 1 - total)):
            total += len(chunk)
            require(total <= item["bytes"], "Archive exceeds its pinned byte count")
            checksum.update(chunk)
            target.write(chunk)
        require(total == item["bytes"] and checksum.hexdigest() == item["sha256"],
                "Archive size or SHA256 differs from its pin")
        target.flush()
        os.fchmod(target.fileno(), 0o400)


def acquire(item, downloads, archives, fetch, opener_factory=urllib.request.build_opener):
    destination = downloads / item["archive"]
    if archives is not None:
        source = archives / item["archive"]
        try:
            stream = regular_input(source)
        except FileNotFoundError:
            stream = None
        if stream is not None:
            with stream:
                require(os.fstat(stream.fileno()).st_size == item["bytes"], "Cached archive size differs")
                copy_verified(stream, destination, item)
            return destination
    require(fetch, "Missing pinned archive; provide --archives or explicitly use --fetch")
    opener = opener_factory(ExactRedirect(item["redirect_url"]))
    request = urllib.request.Request(item["url"], headers={"Accept-Encoding": "identity"})
    with deadline(DOWNLOAD_SECONDS):
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            error.close()
            raise
        with response:
            require(response.status == 200 and response.url in (item["url"], item["redirect_url"]),
                    "Unexpected artifact response")
            require(response.headers.get("Content-Encoding", "identity") == "identity", "Encoded artifact response")
            length = response.headers.get("Content-Length")
            require(length is None or length == str(item["bytes"]), "Unexpected archive Content-Length")
            copy_verified(response, destination, item)
    return destination


def safe_name(name):
    require(isinstance(name, str) and len(name) <= 512 and "\\" not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name), "Unsafe archive name")
    if name.startswith("./"):
        name = name[2:]
    name = name.removesuffix("/")
    require(name not in ("", ".") and not name.startswith("/")
            and all(p not in ("", ".", "..") for p in name.split("/"))
            and len(name.split("/")) <= 32, "Unsafe archive path")
    return name


class BoundedXZ:
    """Streaming XZ with explicit decoder-memory and expanded-byte limits."""
    def __init__(self, stream):
        self.stream = stream
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=128 * 1024**2)
        self.total = 0
        self.done = False

    def read(self, size):
        require(0 < size <= MAX_EXPANDED + 1, "Invalid decompression read bound")
        if self.done:
            return b""
        output = bytearray()
        while len(output) < size and not self.done:
            compressed = self.stream.read(CHUNK) if self.decoder.needs_input else b""
            require(compressed or not self.decoder.needs_input, "Truncated XZ stream")
            value = self.decoder.decompress(compressed, max_length=min(size - len(output), MAX_EXPANDED + 1 - self.total))
            self.total += len(value)
            require(self.total <= MAX_EXPANDED, "Expanded archive exceeds bound")
            output.extend(value)
            if self.decoder.eof:
                require(not self.decoder.unused_data and not self.stream.read(1), "Trailing XZ data")
                self.done = True
        return bytes(output)


class ArSlice:
    def __init__(self, stream, start, size):
        self.stream, self.left = stream, size
        stream.seek(start)

    def read(self, size):
        value = self.stream.read(min(size, self.left))
        self.left -= len(value)
        return value


def deb_data(stream):
    """Read only the standard three-member Debian ar envelope, never control code."""
    require(stream.read(8) == b"!<arch>\n", "Invalid Debian archive magic")
    expected = ("debian-binary", "control.tar.xz", "data.tar.xz")
    data = None
    end = os.fstat(stream.fileno()).st_size
    for wanted in expected:
        header = stream.read(60)
        require(len(header) == 60 and header[58:] == b"`\n", "Invalid Debian ar header")
        name = header[:16].decode("ascii").strip().removesuffix("/")
        count = header[48:58].decode("ascii").strip()
        require(name == wanted and re.fullmatch(r"[0-9]{1,10}", count) is not None, "Unsupported Debian ar member")
        size, start = int(count), stream.tell()
        require(0 < size <= MAX_ARCHIVE and start + size <= end, "Invalid Debian ar member size")
        if wanted == "debian-binary":
            require(size == 4 and stream.read(size) == b"2.0\n", "Unsupported Debian package version")
        elif wanted == "data.tar.xz":
            data = (start, size)
        stream.seek(start + size)
        if size % 2:
            require(stream.read(1) == b"\n", "Invalid ar padding")
    require(stream.tell() == end, "Extra Debian ar member or bytes")
    return ArSlice(stream, *data)


def selected_path(name, kind, item):
    prefix = item["prefix"] + "/"
    if kind == "firefox" and name == item["license_file"]:
        return "licenses/firefox-copyright"
    if kind == "node":
        if not name.startswith(prefix):
            return None
        relative = name[len(prefix):]
        return "node/" + relative if relative in ("bin/node", item["license_file"]) else None
    relative = name[len(prefix):] if name.startswith(prefix) else None
    for source, target in FIREFOX_DIRECTORIES.items():
        if name.startswith(target + "/"):
            relative = source[len(prefix):] + name[len(target):]
    for source, target in FIREFOX_ICONS.items():
        if name == target:
            relative = "browser/chrome/" + source.removeprefix("usr/share/firefox-esr/browser/chrome/")
    if relative is None:
        return None
    if "distribution" in PurePosixPath(relative).parts or relative == "browser/defaults/syspref" or relative.startswith("browser/defaults/syspref/"):
        return None
    return "firefox/" + relative


def link_target(member, name):
    target = member.linkname
    require(isinstance(target, str) and 0 < len(target) <= 512 and not target.startswith("/")
            and "\\" not in target and not any(ord(c) < 32 or ord(c) == 127 for c in target),
            "Unsafe selected archive link")
    return safe_name(posixpath.normpath(posixpath.join(posixpath.dirname(name), target)
                     if member.issym() else target))


def private_parents(path, output):
    relative = path.parent.relative_to(output)
    current = output
    for part in relative.parts:
        current /= part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            info = current.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o700, "Unsafe output directory")


def extract(stream, output, kind, item):
    reader = BoundedXZ(stream)
    seen, records, links, aliases = set(), {}, {}, set()
    payload = 0
    with tarfile.open(fileobj=reader, mode="r|") as archive:
        for member in archive:
            if member.name in (".", "./") and member.isdir():
                continue
            name = safe_name(member.name)
            require(name not in seen and len(seen) < MAX_MEMBERS, "Duplicate or excessive archive members")
            seen.add(name)
            require(member.isdir() or member.isfile() or member.issym() or member.islnk(), "Unsupported archive member type")
            require(0 <= member.size <= MAX_FILE and not member.mode & 0o7000, "Unsafe archive size or mode")
            payload += member.size
            require(payload <= MAX_EXPANDED, "Archive payload exceeds bound")
            if kind == "firefox" and name in FIREFOX_ALIASES:
                require(member.issym() and link_target(member, name) == FIREFOX_ALIASES[name],
                        "Pinned Debian runtime alias changed")
                aliases.add(name)
                continue
            relative = selected_path(name, kind, item)
            if relative is None or member.isdir():
                continue
            require(len(records) + len(links) < MAX_OUTPUT_FILES, "Too many selected runtime files")
            path = output / relative
            private_parents(path, output)
            if member.issym() or member.islnk():
                normalized = link_target(member, name)
                # Only the exact aliases above may leave the GRE. Adding
                # relocation inputs must not broaden ordinary link authority.
                require(normalized.startswith(item["prefix"] + "/")
                        and selected_path(normalized, kind, item) is not None,
                        "Selected archive link escapes runtime")
                links[name] = (relative, normalized)
                continue
            checksum, total = hashlib.sha256(), 0
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with archive.extractfile(member) as source, os.fdopen(fd, "wb") as target:
                while chunk := source.read(CHUNK):
                    total += len(chunk)
                    require(total <= member.size, "Tar member exceeds declared size")
                    checksum.update(chunk)
                    target.write(chunk)
            require(total == member.size, "Truncated runtime file")
            records[name] = {"path": relative, "bytes": total, "sha256": checksum.hexdigest(),
                             "mode": 0o700 if member.mode & 0o111 else 0o600}
    while reader.read(CHUNK):
        pass
    if kind == "firefox":
        require(aliases == set(FIREFOX_ALIASES)
                and all(target in records for target in FIREFOX_ICONS.values()),
                "Pinned Debian runtime aliases or icon targets missing")
    for name, (relative, target) in links.items():
        visited = {name}
        while target in links:
            require(target not in visited and len(visited) < 16, "Cyclic or excessive runtime link chain")
            visited.add(target)
            target = links[target][1]
        require(target in records, "Runtime link target missing")
        original = records[target]
        payload += original["bytes"]
        require(payload <= MAX_EXPANDED, "Materialized runtime exceeds bound")
        # We create no symlinks/hardlinks. All targets are our own non-executable
        # regular files inside this fresh private output, verified again below.
        with regular_input(output / original["path"]) as source:
            copy_verified(source, output / relative, original)
        os.chmod(output / relative, 0o600)
        records[name] = dict(original, path=relative)
    by_path = {entry["path"]: entry for entry in records.values()}
    for relative, expected in item["expected_files"].items():
        actual = by_path.get(kind + "/" + relative)
        require(actual is not None and all(actual[key] == expected[key] for key in ("bytes", "sha256")),
                "Extracted runtime differs from expected executable/library hash")
    license_name = "node/" + item["license_file"] if kind == "node" else "licenses/firefox-copyright"
    require(license_name in by_path and 0 < by_path[license_name]["bytes"] <= 4 * 1024**2,
            "Required original runtime license missing or oversized")
    executable = by_path[kind + ("/bin/node" if kind == "node" else "/firefox-esr")]
    require(executable["mode"] == 0o700, "Pinned executable has no archive execute bit")
    return by_path


def new_output(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    build = ROOT / "build"
    require(path.parent == build and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", path.name),
            "Output must be a new direct child of this checkout's build/")
    try:
        build.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = build.lstat()
    require(build.resolve() == build and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022, "Build parent must be canonical, owned and not group/world writable")
    path.mkdir(mode=0o700)
    return path


def prepare(output, pin, pin_sha, archives=None, fetch=False):
    info = output.lstat()
    require(output.resolve() == output and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
            and not any(output.iterdir()), "Runtime output must be a fresh private owned directory")
    downloads = output / "archives"
    downloads.mkdir(mode=0o700)
    files, inputs = {}, {}
    for kind, item in pin["artifacts"].items():
        path = acquire(item, downloads, archives, fetch)
        with regular_input(path) as source, deadline(EXTRACT_SECONDS):
            files.update(extract(deb_data(source) if kind == "firefox" else source, output, kind, item))
        inputs[kind] = {key: item[key] for key in ("version", "url", "bytes", "sha256", "checksum_source", "abi")}
    # Neither runtime receives any execute permission before BOTH archive and
    # extracted-file checks succeed. No subprocess or runtime is ever launched.
    for relative, entry in files.items():
        os.chmod(output / relative, entry["mode"])
    report = {
        "schema": 1, "kind": "historical-public-weather-runtime-materialization", "profile": pin["profile"],
        "pin_sha256": pin_sha, "preparer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": inputs, "files": files,
        "scope": {"expected_runtime_hashes_verified": True, "licenses_preserved": True,
                  "runtime_executed": False, "host_installed": False, "source_build": False,
                  "host_abi_verified": False, "browser_proof_performed": False,
                  "legacy_bundle_equivalent": False, "current_update_authority": False},
    }
    raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    require(len(raw) <= 2 * 1024**2, "Runtime receipt exceeds bound")
    fd = os.open(output / "provenance.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New direct child of this checkout's build/")
    parser.add_argument("--archives", type=Path, help="Read-only local cache of the exact pinned archive filenames")
    parser.add_argument("--fetch", action="store_true", help="Explicitly fetch missing pinned public archives")
    args = parser.parse_args(argv)
    require(os.geteuid() != 0, "Use an ordinary user; never root")
    pin, pin_sha = load_pin()
    output = new_output(args.output)
    report = prepare(output, pin, pin_sha, args.archives, args.fetch)
    print(json.dumps({"schema": 1, "prepared": True, "profile": report["profile"],
                      "files": len(report["files"]), "runtime_executed": False}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, lzma.LZMAError) as error:
        raise SystemExit(f"Runtime preparation failed: {error}") from error
