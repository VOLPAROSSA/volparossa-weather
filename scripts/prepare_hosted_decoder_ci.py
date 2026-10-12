#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Temporary AppArmor setup for this explicit disposable GitHub build only.

No free-form command arguments, sysctl writes, root builds or isolation bypass.
The installed package's bwrap performs setup; its children deny capabilities.
The exact decoder sandbox must pass an inert preflight before capture/build.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import selectors
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DECODER = ROOT / "scripts/prepare_hosted_decoder.py"
PROFILE = ROOT / "scripts/hosted-decoder-bwrap.apparmor"
PROFILE_SHA = "d47872c2ad9a78f54b4cd118016224f111b4f92efae52651eda6ffd44ddc8007"
LICENSE_SHA = "a7e0cdcbea5c14927cedfc600d46526bdcbb1eb0a4d951e2ea53c2a6de159cb4"
STAGED = Path("/run/volparossa-weather-decoder.apparmor")
PARSER = "/usr/sbin/apparmor_parser"
NAMES = ("volparossa_ci_weather_bwrap", "volparossa_ci_weather_child")
RESTRICTION = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
LIMIT = 2 * 1024**2
DRAIN_CONFIRMED = True


class CIInterrupted(Exception):
    """Cancellation must not be swallowed by selectors' OSError handling."""


class CommandFailure(ValueError):
    def __init__(self, category, code=None, raw=b""):
        super().__init__(category)
        self.category, self.code = category, code
        self.output_bytes, self.output_sha256 = len(raw), digest(raw)
        self.setup_code = "bwrap-loopback-address-denied" if raw.strip() == (
            b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted") else "unclassified"

MOUNT_CHECK = r'''
def validate_mounts(raw, lookup):
    import stat
    devices = {"/dev/null": (1,3), "/dev/zero": (1,5), "/dev/full": (1,7),
               "/dev/random": (1,8), "/dev/urandom": (1,9), "/dev/tty": (5,0)}
    assert len(raw) <= 65536 and len(raw.splitlines()) <= 256
    seen = set()
    for line in raw.splitlines():
        fields = line.split()
        filesystem = fields[fields.index("-") + 1]
        path = fields[4]
        if path in devices:
            info = lookup(path)
            assert stat.S_ISCHR(info.st_mode)
            assert (os.major(info.st_rdev), os.minor(info.st_rdev)) == devices[path]
            seen.add(path)
        elif filesystem not in ("tmpfs", "proc", "devpts") and path != "/build":
            assert "ro" in fields[5].split(",")
    assert seen == set(devices)
'''

PROBE = 'import os\n' + MOUNT_CHECK + r'''
import errno, json, socket, sys
from pathlib import Path
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert os.getuid() == int(sys.argv[1]) != 0
assert int(status["CapEff"], 16) == int(status["CapPrm"], 16) == 0
assert int(status["NoNewPrivs"]) == 1
assert "volparossa_ci_weather_child" in Path("/proc/self/attr/current").read_text()
assert os.readlink("/proc/self/ns/net") != sys.argv[2]
assert [name for _, name in socket.if_nameindex()] == ["lo"]
assert all(not Path(path).exists() for path in ("/home", "/root", "/run", "/etc/resolv.conf"))
assert os.statvfs("/usr").f_flag & os.ST_RDONLY
assert os.statvfs("/etc/ld.so.cache").f_flag & os.ST_RDONLY
assert not os.statvfs("/build").f_flag & os.ST_RDONLY
validate_mounts(Path("/proc/self/mountinfo").read_text(), os.lstat)
try:
    os.open("/usr/volparossa-forbidden-write", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    assert error.errno in (errno.EROFS, errno.EACCES)
else:
    raise AssertionError("read-only toolchain write allowed")
p = Path("/build/preflight-write")
with p.open("xb") as f:
    f.write(b"owned-preflight")
assert p.read_bytes() == b"owned-preflight"
p.unlink()
print(json.dumps(dict(schema=1,kind="hosted-decoder-sandbox-preflight",unprivileged=True,
 capabilities_zero=True,no_new_privileges=True,capability_denied_child_profile=True,
 separate_network_namespace=True,loopback_only=True,host_private_paths_absent=True,
 toolchain_read_only=True,build_writable=True,only_build_host_writable=True)))
'''


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    require(len(raw) <= LIMIT, "DIAGNOSTIC_BOUND")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)


def process(argv, seconds, check=True):
    """Fixed trusted commands only, bounded output and owned process group cleanup."""
    global DRAIN_CONFIRMED
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=ENV, start_new_session=True)
    output = bytearray()
    decoder_command = argv[:3] == ["/usr/bin/python3", "-B", str(DECODER)]
    deadline = time.monotonic() + seconds
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CommandFailure("deadline", raw=bytes(output))
                for key, _ in selector.select(min(remaining, 0.2)):
                    raw = os.read(key.fd, 65536)
                    if not raw:
                        selector.unregister(key.fileobj)
                    else:
                        if len(output) + len(raw) > LIMIT:
                            raise CommandFailure("output-bound", raw=bytes(output))
                        output.extend(raw)
            code = child.wait(timeout=max(0.001, deadline-time.monotonic()))
            if code < 0 or (decoder_command and code == 125):
                DRAIN_CONFIRMED = False
            if check and code != 0:
                raise CommandFailure("exit-status", code, bytes(output))
            return code, bytes(output)
    finally:
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if child.poll() is None:
                # The decoder's CLI handles TERM by joining its owned sandbox
                # in run_step.finally. Never replace that unwind with immediate KILL.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    DRAIN_CONFIRMED = False
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
            if child.returncode is not None and (child.returncode < 0 or
                    (decoder_command and child.returncode == 125)):
                DRAIN_CONFIRMED = False
        except BaseException:
            DRAIN_CONFIRMED = False
            raise
        finally:
            child.stdout.close()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def guards(environment):
    require(os.geteuid() == os.getuid() != 0, "ORDINARY_RUNNER_REQUIRED")
    required = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "RUNNER_ENVIRONMENT": "github-hosted",
                "GITHUB_REPOSITORY": "VOLPAROSSA/volparossa-weather",
                "GITHUB_WORKFLOW": "Prepare hosted Weather inputs"}
    require(all(environment.get(key) == value for key, value in required.items()), "EXPLICIT_DISPOSABLE_CI_REQUIRED")
    require(environment.get("GITHUB_WORKSPACE") == str(ROOT)
            and re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")), "CI_SOURCE_REQUIRED")
    _, head = process(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"], 10)
    require(head.decode().strip() == environment["GITHUB_SHA"], "CI_SOURCE_CHANGED")
    process(["/usr/bin/git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--",
             "scripts/prepare_hosted_decoder.py", "scripts/prepare_hosted_decoder_ci.py",
             "scripts/hosted-decoder-bwrap.apparmor", "third_party/apparmor-ci"], 10)
    helper = runpy.run_path(str(DECODER))
    require(helper["platform"]()["os_id"] == "ubuntu", "UBUNTU_24_CI_REQUIRED")
    require(digest(helper["read_file"](PROFILE)) == PROFILE_SHA
            and digest(helper["read_file"](ROOT / "third_party/apparmor-ci/LICENSE")) == LICENSE_SHA,
            "POLICY_PROVENANCE_CHANGED")
    return helper


def inventory():
    _, raw = process(["/usr/bin/sudo", "-n", "/usr/bin/cat", "/sys/kernel/security/apparmor/profiles"], 10)
    names = [line.rsplit(" (", 1)[0] for line in raw.decode().splitlines()]
    require(all(name and len(name) <= 512 for name in names), "PROFILE_INVENTORY_INVALID")
    return names


def prechecks(helper):
    _, owner = process(["/usr/bin/dpkg-query", "-S", "/usr/bin/bwrap"], 10)
    require(owner == b"bubblewrap: /usr/bin/bwrap\n", "PACKAGED_BWRAP_REQUIRED")
    _, verification = process(["/usr/bin/dpkg", "--verify", "bubblewrap"], 10)
    require(not verification, "PACKAGE_VERIFICATION_FAILED")
    info = Path("/usr/bin/bwrap").lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o6022
            and info.st_mode & 0o111 and Path("/usr/bin/bwrap").resolve() == Path("/usr/bin/bwrap")
            and "security.capability" not in os.listxattr("/usr/bin/bwrap"), "BWRAP_PRIVILEGES_CHANGED")
    require(Path(PARSER).is_file() and os.access(PARSER, os.X_OK), "PARSER_REQUIRED")
    names = inventory()
    require(not any("bwrap" in name or "volparossa_ci_weather" in name for name in names), "EXISTING_POLICY_CONFLICT")
    restriction = RESTRICTION.read_text().strip()
    require(restriction == "1", "EXPECTED_USERNS_RESTRICTION_REQUIRED")
    require(not STAGED.exists() and not STAGED.is_symlink(), "STAGING_PATH_EXISTS")
    _, packages = process(["/usr/bin/dpkg-query", "-W", "-f=${Package} ${Version}\n", "apparmor", "bubblewrap"], 10)
    return dict(schema=1, kind="hosted-decoder-sandbox-baseline", platform=helper["platform"](),
        source_commit=os.environ["GITHUB_SHA"], kernel=os.uname().release,
        packages=packages.decode().splitlines(), bwrap_sha256=digest(helper["read_file"](Path("/usr/bin/bwrap"), 1024**2)),
        wrapper_profile=Path("/proc/self/attr/current").read_text().strip(),
        restricted_unprivileged_userns=True, conflicting_profiles=False,
        profile_sha256=PROFILE_SHA, license_sha256=LICENSE_SHA)


def validate_probe(value):
    fields = {"unprivileged", "capabilities_zero", "no_new_privileges", "capability_denied_child_profile",
              "separate_network_namespace", "loopback_only", "host_private_paths_absent",
              "toolchain_read_only", "build_writable", "only_build_host_writable"}
    require(type(value) is dict and set(value) == fields | {"schema", "kind"}
            and type(value["schema"]) is int and value["schema"] == 1
            and value["kind"] == "hosted-decoder-sandbox-preflight"
            and all(value[key] is True for key in fields), "SANDBOX_PREFLIGHT_FAILED")


def preflight(helper, output):
    tools = {"bwrap": {"path": "/usr/bin/bwrap"}}
    argv = helper["sandbox"](output, tools, ["/usr/bin/python3", "-I", "-c", PROBE,
                str(os.getuid()), os.readlink("/proc/self/ns/net")])
    _, raw = process(argv, 20)
    value = json.loads(raw, object_pairs_hook=helper["unique"])
    validate_probe(value)
    return value


def staged_owned(helper):
    info = STAGED.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1, "STAGED_POLICY_CHANGED")
    # The temporary root-owned 0600 policy is deliberately not readable by the
    # builder. Only this exact known pathname is inspected through sudo.
    _, checksum = process(["/usr/bin/sudo", "-n", "/usr/bin/sha256sum", "--", str(STAGED)], 10)
    after = STAGED.lstat()
    require(checksum.decode().strip() == PROFILE_SHA + "  " + str(STAGED)
            and (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns), "STAGED_POLICY_CHANGED")


def cleanup(helper, attempted, staged):
    checks = dict(process_drain_confirmed=DRAIN_CONFIRMED,
                  profile_removed=not attempted, staging_removed=not staged, restriction_unchanged=False)
    if not DRAIN_CONFIRMED:
        # Do not unconfine potentially surviving descendants. The disposable
        # runner must be discarded; retain exact owned policy and report failure.
        try:
            checks["restriction_unchanged"] = RESTRICTION.read_text().strip() == "1"
        except OSError:
            pass
        return dict(schema=1, kind="hosted-decoder-sandbox-cleanup", complete=False, **checks)
    if staged:
        try:
            if STAGED.exists() or STAGED.is_symlink():
                staged_owned(helper)
                if attempted:
                    process(["/usr/bin/sudo", "-n", PARSER, "--remove", "--skip-cache", str(STAGED)], 10)
                    checks["profile_removed"] = not any(name.startswith(NAMES) for name in inventory())
                process(["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", str(STAGED)], 10)
            checks["staging_removed"] = not STAGED.exists() and not STAGED.is_symlink()
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        checks["restriction_unchanged"] = RESTRICTION.read_text().strip() == "1"
    except OSError:
        pass
    return dict(schema=1, kind="hosted-decoder-sandbox-cleanup", complete=all(checks.values()), **checks)


def audit(output, since):
    # Only this short phase's bwrap/AppArmor denials; never arbitrary system logs.
    try:
        code, raw = process(["/usr/bin/sudo", "-n", "/usr/bin/journalctl", "-k", "--no-pager", "-n", "200",
                             "--since", "@" + str(since), "-o", "cat"], 10, check=False)
        lines = [line for line in raw.decode(errors="replace").splitlines()
                 if "apparmor=" in line and any(word in line for word in ("bwrap", "volparossa_ci_weather"))]
        require(len(lines) <= 100 and all(len(line) <= 4096 for line in lines), "AUDIT_BOUND")
        value = dict(schema=1, kind="hosted-decoder-sandbox-audit", available=code == 0,
                     matching_denials=lines if code == 0 else [])
    except (OSError, ValueError, subprocess.SubprocessError):
        value = dict(schema=1, kind="hosted-decoder-sandbox-audit", available=False, matching_denials=[])
    write_json(output/"audit.json", value)


def execute(helper, output):
    staged = attempted = False
    success = False
    stage = "baseline"
    since = int(time.time())
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(_signal, _frame):
        raise CIInterrupted("CI_INTERRUPTED")
    for sig in previous:
        signal.signal(sig, interrupted)
    try:
        write_json(output/"baseline.json", prechecks(helper))
        print("Disposable CI only: add exact temporary bwrap/child profiles; retain all sandbox isolation; remove owned policy after unprivileged build.", flush=True)
        stage = "policy-install"
        staged = True
        process(["/usr/bin/sudo", "-n", "/usr/bin/install", "-o", "root", "-g", "root", "-m", "0600", "--", str(PROFILE), str(STAGED)], 10)
        staged_owned(helper)
        attempted = True
        process(["/usr/bin/sudo", "-n", PARSER, "--add", "--skip-cache", str(STAGED)], 10)
        stage = "sandbox-preflight"
        write_json(output/"preflight.json", preflight(helper, output))
        stage = "capture-toolchain"
        _, raw = process(["/usr/bin/python3", "-B", str(DECODER), "capture-toolchain", "--output-dir",
                          str(ROOT/"build/hosted-toolchain-ci")], 90)
        capture = json.loads(raw, object_pairs_hook=helper["unique"])
        manifest = ROOT/"build/hosted-toolchain-ci/toolchain.json"
        require(capture["toolchain_manifest"] == str(manifest)
                and capture["decoder_authorized"] is False and capture["provenance_only"] is True
                and digest(helper["read_file"](manifest)) == capture["toolchain_manifest_sha256"], "CAPTURE_BINDING_FAILED")
        write_json(ROOT/"build/hosted-toolchain-capture.json", capture)
        stage = "offline-build"
        process(["/usr/bin/python3", "-B", str(DECODER), "build", "--archives", str(ROOT/"build/eccodes/downloads"),
                 "--output", str(ROOT/"build/hosted-decoder-ci"), "--toolchain-manifest", str(manifest),
                 "--toolchain-sha256", capture["toolchain_manifest_sha256"]], 1860)
        success = True
    except BaseException as error:
        category = error.category if isinstance(error, CommandFailure) else (
            "interrupted" if isinstance(error, (CIInterrupted, InterruptedError, KeyboardInterrupt)) else "validation-or-setup")
        write_json(output/"failure.json", dict(schema=1, kind="hosted-decoder-sandbox-failure", stage=stage,
            category=category, command_exit_status=error.code if isinstance(error, CommandFailure) else None,
            command_output_bytes=error.output_bytes if isinstance(error, CommandFailure) else None,
            command_output_sha256=error.output_sha256 if isinstance(error, CommandFailure) else None,
            setup_code=error.setup_code if isinstance(error, CommandFailure) else "unclassified"))
        raise
    finally:
        # Ignore repeated termination while draining/removing only this lifecycle's resources.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            receipt = cleanup(helper, attempted, staged)
            write_json(output/"cleanup.json", receipt)
            audit(output, since)
            write_json(output/"result.json", dict(schema=1, kind="hosted-decoder-sandbox-result",
                       stage=stage, build_returned_successfully=success, cleanup_complete=receipt["complete"],
                       decoder_authorized=False))
            require(receipt["complete"], "CI_POLICY_CLEANUP_FAILED")
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    require(len(sys.argv) == 1, "NO_COMMAND_ARGUMENTS")
    os.umask(0o077)
    helper = guards(os.environ)
    output = ROOT/"build/hosted-sandbox-ci"
    helper["new_output"](output, "hosted-sandbox-")
    helper["create_output"](output)
    execute(helper, output)


if __name__ == "__main__":
    try:
        main()
    except (CIInterrupted, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("HOSTED_DECODER_CI_FAILED", file=sys.stderr)
        sys.exit(1)
