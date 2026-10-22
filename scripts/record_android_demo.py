#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in, bounded pixels from the disposable protected-core Android trial.

This observer never drives the app, changes products or grants acceptance.
Its only guest writes are one fixed temporary MP4, removed before completion.
The enclosing runner owns this process and still drains the whole namespace.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

GUEST = "/data/local/tmp/volparossa-weather-demo.mp4"
SERIAL = "emulator-5554"
MAX_SECONDS = 180
MAX_VIDEO = 100 * 1024**2
MAX_PNG = 4 * 1024**2
MAX_SHOTS = 36
PNG = b"\x89PNG\r\n\x1a\n"
RECORD = ["/system/bin/screenrecord", "--time-limit", "180", "--bit-rate", "4000000",
    "--size", "720x1280", GUEST]


def require(value):
    if not value:
        raise ValueError("ANDROID_DEMO_RECORDING_REJECTED")


def fingerprint(path, maximum):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= maximum)
        digest, count = hashlib.sha256(), 0
        while block := stream.read(65536):
            count += len(block); require(count <= maximum); digest.update(block)
        after, named = os.fstat(stream.fileno()), Path(path).lstat()
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(count == before.st_size and all(getattr(before, k) == getattr(after, k) == getattr(named, k) for k in fields))
        return dict(bytes=count, sha256=digest.hexdigest())


class Recording:
    def __init__(self, adb, output):
        self.adb, self.output = adb, Path(output)
        self.process = None; self.pid = None; self.started = None; self.started_unix_ms = None
        self.files = {}; self.shots = []; self.guest_removed = False

    def argv(self, *args):
        return [self.adb, "-s", SERIAL, *args]

    def read(self, args, maximum=4096, destination=None, seconds=5):
        """Read both pipes with a byte bound; join the exact child on every exit."""
        child = subprocess.Popen(self.argv(*args), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        collected, count = bytearray(), 0
        output = None; selector = selectors.DefaultSelector(); deadline = time.monotonic() + seconds
        try:
            if destination is not None:
                output = open(destination, "xb"); os.chmod(destination, 0o600)
            for name in ("stdout", "stderr"):
                stream = getattr(child, name); os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                require(time.monotonic() < deadline)
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    raw = os.read(key.fileobj.fileno(), 65536)
                    if not raw:
                        selector.unregister(key.fileobj); continue
                    count += len(raw); require(count <= maximum)
                    if key.data == "stdout":
                        if output is not None: output.write(raw)
                        else: collected.extend(raw)
                    else:
                        # No raw command or device output enters the proof.
                        require(len(raw) <= 4096)
            require(child.wait(timeout=max(0.1, deadline - time.monotonic())) == 0)
            return bytes(collected)
        finally:
            try:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=3)
            finally:
                selector.close(); child.stdout.close(); child.stderr.close()
                if output is not None: output.close()

    def start(self):
        require(self.output.resolve(strict=True) == self.output and not any(self.output.iterdir()))
        info = self.output.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        # Never adopt an existing recorder or remove its guest file.
        require(self.read(["shell", "test ! -e " + GUEST + " && echo absent"]).strip() == b"absent")
        self.started = time.monotonic(); self.started_unix_ms = round(time.time() * 1000)
        # Fixed literal shell only: print the future recorder PID, then exec.
        # No caller text, paths or credentials are interpolated into this script.
        self.process = subprocess.Popen(self.argv("shell", "echo $$; exec " + " ".join(RECORD)),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
        os.set_blocking(self.process.stdout.fileno(), False)
        raw, deadline = bytearray(), time.monotonic() + 5
        while b"\n" not in raw:
            require(self.process.poll() is None and time.monotonic() < deadline)
            try: block = os.read(self.process.stdout.fileno(), 32)
            except BlockingIOError: block = b""
            raw.extend(block); require(len(raw) <= 32); time.sleep(0.02)
        require(re.fullmatch(rb"[1-9][0-9]{0,9}\r?\n", raw))
        self.pid = int(raw)
        while True:
            command = self.read(["shell", "cat", f"/proc/{self.pid}/cmdline"])
            if command == b"\0".join(x.encode() for x in RECORD) + b"\0": break
            require(self.process.poll() is None and time.monotonic() < deadline); time.sleep(0.02)

    def screenshot(self):
        require(len(self.shots) < MAX_SHOTS)
        name = f"screen-{len(self.shots) + 1:03d}.png"
        before = round((time.monotonic() - self.started) * 1000)
        self.read(["exec-out", "/system/bin/screencap", "-p"], MAX_PNG, self.output / name)
        with (self.output / name).open("rb") as stream: require(stream.read(8) == PNG)
        self.files[name] = fingerprint(self.output / name, MAX_PNG)
        self.shots.append(dict(file=name, started_elapsed_ms=before,
            completed_elapsed_ms=round((time.monotonic() - self.started) * 1000), stage="unclassified"))

    def stop(self):
        # Only the exact recorder we launched may receive a signal. Its guest
        # PID belongs to this trusted disposable image, never the host.
        try:
            if self.process is not None and self.process.poll() is None:
                require(self.pid is not None)
                command = self.read(["shell", "cat", f"/proc/{self.pid}/cmdline"])
                require(command == b"\0".join(x.encode() for x in RECORD) + b"\0")
                self.read(["shell", "kill", "-2", str(self.pid)])
                require(self.process.wait(timeout=8) == 0)
            if self.process is not None: require(self.process.returncode == 0)
        finally:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.kill(); self.process.wait(timeout=3)
                self.process.stdout.close()

    def finish(self):
        self.read(["exec-out", "cat", GUEST], MAX_VIDEO, self.output / "screen.mp4", seconds=10)
        with (self.output / "screen.mp4").open("rb") as stream:
            require(stream.read(12)[4:8] == b"ftyp")
        self.files["screen.mp4"] = fingerprint(self.output / "screen.mp4", MAX_VIDEO)

    def remove_guest(self):
        self.read(["shell", "rm", "--", GUEST]); self.guest_removed = True


def main(adb, output):
    require(os.getuid() != 0 and Path(adb) == Path("/tools/android-inputs/sdk/platform-tools/adb")
        and Path(output).name == "demo-media" and Path(output).parent.name == "overmorrow-hosted-android-live-proof"
        and "volparossa_ci_weather_clients_child" in Path("/proc/self/attr/current").read_text())
    recorder = Recording(adb, output); completed = False
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(*_): raise InterruptedError()
    for s in previous: signal.signal(s, interrupted)
    selector = selectors.DefaultSelector()
    try:
        recorder.start()
        print("ANDROID_DEMO_RECORDING_READY", flush=True)
        selector.register(sys.stdin, selectors.EVENT_READ)
        next_shot = time.monotonic()
        while True:
            elapsed = time.monotonic() - recorder.started
            require(elapsed < MAX_SECONDS and recorder.process.poll() is None)
            if selector.select(0.05):
                require(sys.stdin.buffer.readline(6) == b"stop\n"); break
            if time.monotonic() >= next_shot:
                recorder.screenshot(); next_shot += 5
        recorder.stop(); recorder.finish(); completed = True
    finally:
        for s in previous: signal.signal(s, signal.SIG_IGN)
        try:
            recorder.stop()
        finally:
            try:
                if recorder.pid is not None: recorder.remove_guest()
            finally:
                selector.close()
                for s, handler in previous.items(): signal.signal(s, handler)
    require(completed and recorder.guest_removed and 1 <= len(recorder.shots) <= MAX_SHOTS)
    value = dict(schema=1, kind="weather-demo-android-recording",
        started_unix_ms=recorder.started_unix_ms, completed_unix_ms=round(time.time() * 1000), elapsed_ms=round((time.monotonic() - recorder.started) * 1000),
        source="android-screenrecord-and-screencap", files=recorder.files, screenshots=recorder.shots,
        recorder_joined=True, guest_file_removed=True, stage_labels_verified=False,
        ui_values_verified=False, joined_core_acceptance=False, production_authority=False)
    with (Path(output) / "recording.json").open("x") as stream:
        os.chmod(stream.name, 0o600); json.dump(value, stream, sort_keys=True); stream.write("\n")


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 3); main(*sys.argv[1:])
    except BaseException:
        print("ANDROID_DEMO_RECORDING_FAILED", file=sys.stderr); sys.exit(1)
