#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only, bounded indications around the two hosted Gradle app builds.

Never export log text, names, environment, process IDs, cgroup paths or dumps.
Markers are indications, not a causal verdict or proof of absence. The cgroup
is the wrapper's existing shared runner cgroup, not an exclusive build cgroup.
No resource, JVM, logging or cleanup policy is changed by this observer.
"""
import os
from pathlib import Path
import re
import stat
import time

MAX_ENTRIES = 512
MAX_FILES = 8
MAX_BYTES = 256 * 1024
SCAN_SECONDS = 2
COUNTERS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
MARKERS = {
    "daemon_disappeared": (b"daemon has disappeared", b"Gradle build daemon disappeared unexpectedly"),
    "java_oom": (b"java.lang.OutOfMemoryError",),
    "java_heap_exhausted": (b"java.lang.OutOfMemoryError: Java heap space", b"java.lang.OutOfMemoryError: GC overhead limit exceeded"),
    "jvm_fatal": (b"A fatal error has been detected by the Java Runtime Environment",),
    "native_allocation_failed": (b"There is insufficient memory for the Java Runtime Environment to continue", b"Native memory allocation (malloc) failed"),
}
SHORT_HEAP_ERROR = re.compile(
    rb"(?m)^[ \t]*>[ \t]+(?:Java heap space|GC overhead limit exceeded)[ \t]*\r?$")


def check(condition):
    if not condition:
        raise ValueError("DIAGNOSTIC_SOURCE_UNAVAILABLE")


def identity(info):
    return tuple(getattr(info, key) for key in
        ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def directory(path):
    """No symlink in the directory chain; retain the opened directory inode."""
    check(path.is_absolute() and path.resolve() == path)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        check(info.st_uid == os.getuid() and not info.st_mode & 0o022)
        return fd
    except BaseException:
        os.close(fd)
        raise


def file_info(info):
    check(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
        and info.st_nlink == 1 and not info.st_mode & 0o7022)


def entries(fd, pattern, deadline):
    found = {}
    with os.scandir(fd) as items:
        for count, item in enumerate(items, 1):
            check(count <= MAX_ENTRIES and time.monotonic() < deadline)
            if pattern.fullmatch(item.name):
                check(len(found) < MAX_FILES)
                info = item.stat(follow_symlinks=False)
                file_info(info)
                found[item.name] = identity(info)
    return found


def unknown_source(status="unavailable"):
    return dict(status=status, files_observed=0, bytes_observed=0,
        markers={key: "unknown" for key in MARKERS})


class Logs:
    """Only bytes added during this app step; earlier fixture logs do not count."""
    def __init__(self, path, pattern):
        self.fd = None
        self.path, self.pattern = path, re.compile(pattern)
        self.before = None
        self.status = "unavailable"
        try:
            self.fd = directory(path)
            self.before = entries(self.fd, self.pattern, time.monotonic() + SCAN_SECONDS)
        except FileNotFoundError:
            self.status = "missing"
            # A missing final directory may be created by the child. An unsafe
            # existing ancestor must never be silently treated as new input.
            if path.parent.resolve() == path.parent:
                try:
                    parent = directory(path.parent)
                    os.close(parent)
                    self.before = {}
                except (OSError, ValueError):
                    pass
        except (OSError, ValueError):
            pass
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise

    def finish(self, drained):
        result = unknown_source(self.status)
        try:
            if not drained or self.before is None:
                return result
            if self.fd is None:
                self.fd = directory(self.path)
            check(identity(os.stat(self.path, follow_symlinks=False))[:2] == identity(os.fstat(self.fd))[:2])
            deadline = time.monotonic() + SCAN_SECONDS
            after = entries(self.fd, self.pattern, deadline)
            bounded = False
            observed = {key: False for key in MARKERS}
            for name, info in sorted(after.items()):
                check(time.monotonic() < deadline)
                previous = self.before.get(name)
                if previous == info:
                    continue
                offset = 0
                if previous is not None:
                    check(previous[:5] == info[:5] and previous[5] <= info[5])
                    offset = previous[5]
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
                try:
                    opened = os.fstat(fd)
                    file_info(opened)
                    check(identity(opened) == info)
                    # The last bounded bytes are useful for a late daemon exit.
                    # A truncated scan never claims a marker was absent.
                    length = info[5] - offset
                    bounded |= length > MAX_BYTES
                    raw = os.pread(fd, min(length, MAX_BYTES), max(offset, info[5] - MAX_BYTES))
                    check(len(raw) == min(length, MAX_BYTES) and identity(os.fstat(fd)) == info)
                finally:
                    os.close(fd)
                result["files_observed"] += 1
                result["bytes_observed"] += len(raw)
                for key, needles in MARKERS.items():
                    observed[key] |= any(needle in raw for needle in needles) or (
                        key == "java_heap_exhausted" and SHORT_HEAP_ERROR.search(raw) is not None)
            result["status"] = "bounded" if bounded else "observed" if result["files_observed"] else "missing"
            result["markers"] = {key: "observed" if seen else
                "not_observed" if result["status"] == "observed" else "unknown" for key, seen in observed.items()}
            return result
        except (OSError, ValueError):
            return unknown_source()
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None


def small(fd):
    raw = os.pread(fd, 4097, 0)
    check(len(raw) <= 4096)
    return raw


def membership():
    fd = os.open("/proc/self/cgroup", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        raw = small(fd)
    finally:
        os.close(fd)
    # Unified hierarchy only. No caller-selected path and no v1 inference.
    match = re.fullmatch(rb"0::(/[^\r\n]*)\n?", raw)
    check(match is not None)
    path = match[1].decode("ascii")
    check(path == "/" or all(re.fullmatch(r"[A-Za-z0-9_.:@-]{1,255}", part)
        and part not in (".", "..") for part in path[1:].split("/")))
    return path


def counters(raw):
    result = {}
    for line in raw.decode("ascii").splitlines():
        match = re.fullmatch(r"([a-z_]+) ([0-9]{1,20})", line)
        check(match is not None and match[1] not in result and int(match[2]) < 2**64)
        result[match[1]] = int(match[2])
    check(all(key in result for key in COUNTERS[:-1]))
    return {key: result.get(key) for key in COUNTERS}


class Cgroup:
    """memory.events is normally hierarchical; shared counters do not name victims.

    See docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files.
    Missing root-cgroup counters, v1, denied reads or reset deltas remain unknown.
    """
    def __init__(self):
        self.fd = None
        self.before = None
        self.group = None
        try:
            self.group = membership()
            path = Path("/sys/fs/cgroup") / self.group.lstrip("/") / "memory.events"
            check(path.parent.resolve() == path.parent)
            self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            info = os.fstat(self.fd)
            check(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and not info.st_mode & 0o022)
            self.before = counters(small(self.fd))
        except (OSError, ValueError, UnicodeError):
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise

    def finish(self):
        result = dict(status="unknown", scope="shared-runner-cgroup-memory.events",
            child_attribution=False, delta=None)
        try:
            if self.fd is None or self.before is None or membership() != self.group:
                return result
            after = counters(small(self.fd))
            check(all(after[key] is not None and after[key] >= value
                for key, value in self.before.items() if value is not None))
            result.update(status="observed", delta={key: after[key] - value
                if value is not None else None for key, value in self.before.items()})
            return result
        except (OSError, ValueError, UnicodeError):
            return result
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None


class Capture:
    def __init__(self, private, stage, output, step):
        check(step in ("android-acquisition-build", "android-offline-build"))
        self.step = step
        self.cgroup = None
        self.logs = {}
        try:
            self.cgroup = Cgroup()
            for name, path, pattern in (
                    ("daemon", private / "gradle-home/daemon/8.13", r"daemon-[0-9]{1,10}\.out\.log"),
                    ("jvm_fatal", stage / "android", r"hs_err_pid[0-9]{1,10}\.log"),
                    ("step_log", output, re.escape(step + ".log"))):
                self.logs[name] = Logs(path, pattern)
        except BaseException:
            self.close()
            raise

    def close(self):
        for observer in [self.cgroup, *self.logs.values()]:
            if observer is not None and observer.fd is not None:
                os.close(observer.fd)
                observer.fd = None

    def finish(self, *, drained, java_cpu):
        try:
            return dict(schema=1, kind="hosted-android-gradle-diagnostics", step=self.step,
                indications_only=True, cause_established=False, raw_text_exported=False,
                jvm_fatal_scope="gradle-working-directory-only", process_drain_confirmed=drained,
                limits=dict(max_directory_entries=MAX_ENTRIES, max_files_per_source=MAX_FILES,
                    max_bytes_per_file=MAX_BYTES, scan_seconds_per_source=SCAN_SECONDS),
                cgroup=self.cgroup.finish(), java_cpu=java_cpu,
                sources={name: observer.finish(drained) for name, observer in self.logs.items()})
        finally:
            self.close()
