# SPDX-License-Identifier: GPL-3.0-only
"""Boot the already verified Android runtime, install the same APK and observe the real app."""
from contextlib import ExitStack
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time

from android_relay import wait_for

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SDK = ROOT / 'build/hosted-android-inputs/sdk'
APK = ROOT / 'build/overmorrow-hosted-android-ci/build/app/outputs/flutter-apk/app-debug.apk'
ADB = SDK / 'platform-tools/adb'


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(work, node, host_netns, app_source):
    assert os.getuid() != 0 and host_netns != os.readlink('/proc/self/ns/net')
    assert [name for _, name in socket.if_nameindex()] == ['lo']
    product = json.loads((ROOT / 'build/hosted-android-ci/build.json').read_text())
    assert product['source_commit'] == app_source and product['actual_installed_app'] and product['final_build_networkless']
    with APK.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert product['apk']['sha256'] == digest
    driver = runpy.run_path(str(ROOT / 'scripts/prepare_hosted_android_ci.py'))
    original_env = driver['environment']()
    os.environ.update({key: original_env[key] for key in ('ANDROID_EMULATOR_USE_SYSTEM_LIBS', 'QT_QPA_PLATFORM')})
    os.environ.update(ANDROID_HOME=str(SDK), ANDROID_SDK_ROOT=str(SDK),
        ANDROID_AVD_HOME=str(work / 'avd'), ANDROID_USER_HOME=str(work / 'android'),
        XDG_RUNTIME_DIR=str(work / 'runtime'), JAVA_TOOL_OPTIONS='-Duser.home=' + str(work / 'java'),
        XDG_CONFIG_HOME=str(work / 'config'), TMPDIR=str(work / 'tmp'), JAVA_HOME='/usr/lib/jvm/java-17-openjdk-amd64')
    for directory in ('avd', 'android', 'runtime', 'config', 'tmp', 'java'):
        (work / directory).mkdir(mode=0o700)
    avd = work / 'avd/device.avd'
    subprocess.run([SDK / 'cmdline-tools/19.0/bin/avdmanager', 'create', 'avd', '--name', 'weather_cache',
        '--package', 'system-images;android-36;default;x86_64', '--path', avd],
        input=b'no\n', check=True, timeout=50)
    with (avd / 'config.ini').open('a') as stream:
        stream.write('\nhw.lcd.width=1080\nhw.lcd.height=1920\nhw.lcd.density=420\nhw.keyboard=yes\n')
    def adb(*args, seconds=20):
        return subprocess.check_output([ADB, '-s', 'emulator-5554', *args], timeout=seconds, stderr=subprocess.PIPE)
    with ExitStack() as stack:
        log = stack.enter_context((work / 'emulator.log').open('xb'))
        def start(args, output=log):
            process = subprocess.Popen(args, stdout=output, stderr=output)
            stack.callback(stop, process)
            return process
        server = driver['start_adb_server'](ADB, start)
        emulator = start([SDK / 'emulator/emulator', '-avd', 'weather_cache', '-port', '5554', '-accel', 'on',
            '-cores', '2', '-memory', '1536', '-no-window', '-no-audio', '-no-snapshot', '-no-boot-anim',
            '-gpu', 'swiftshader_indirect', '-no-metrics', '-camera-back', 'none', '-camera-front', 'none'])
        def booted():
            if server.poll() is not None or emulator.poll() is not None:
                # This is before APK installation. Keep only bounded startup errors.
                with (work / 'emulator.log').open('rb') as source:
                    source.seek(max(0, source.seek(0, 2) - 12288))
                    lines = source.read().decode(errors='replace').splitlines()
                for line in [line for line in lines if re.search(r'panic|error|fatal|cannot|failed|space|kvm', line, re.I)][-8:]:
                    print('AVD startup:', line[:240], file=sys.stderr)
                raise RuntimeError(f'AVD startup stopped: adb={server.returncode} emulator={emulator.returncode}')
            try:
                return adb('shell', 'getprop', 'sys.boot_completed', seconds=3).strip() == b'1'
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return False
        wait_for(booted, 180)
        assert adb('shell', 'getprop', 'ro.build.version.sdk').strip() == b'36'
        assert adb('shell', 'getprop', 'ro.product.cpu.abi').strip() == b'x86_64'
        boundary = driver['GuestNetworkUnlinkedObserver']().enforce(adb, time.monotonic() + 60)
        assert boundary['guest_no_usable_egress']
        adb('install', '--no-streaming', str(APK), seconds=50)
        assert driver['package_uid_probe'](adb)['verified']
        adb('reverse', 'tcp:43210', 'tcp:43210')
        relay = start([sys.executable, '-B', HERE / 'android_relay.py', work.parent / 'mobile.sock', work], None)
        (work / 'booted').touch(exist_ok=False)
        wait_for(lambda: (work / 'initial.ready').is_file() or relay.poll() is not None, 460)
        assert relay.poll() is None and (work / 'initial.ready').is_file()
        subprocess.run([node, HERE / 'android-observe.mjs', ADB, work], check=True, timeout=215)
        assert relay.wait(timeout=15) == 0
        adb('reverse', '--remove', 'tcp:43210')
    result = json.loads((work / 'installed.json').read_text())
    result.update(apk_sha256=digest, weather_source=app_source, android_api=36, android_abi='x86_64',
        isolated_host_interfaces=['lo'], guest_no_usable_egress=True, emulator_and_adb_stopped=True)
    (work.parent / 'installed.json').write_text(json.dumps(result, sort_keys=True) + '\n')


if __name__ == '__main__':
    os.umask(0o077)
    run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
