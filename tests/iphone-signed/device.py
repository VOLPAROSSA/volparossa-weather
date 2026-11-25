# SPDX-License-Identifier: GPL-3.0-only
"""Reserve a fresh simulator and announce readiness only after installing the ordinary app."""
from pathlib import Path
import json
import os
import plistlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios-simulator'))
from observe import BUNDLE, sim

RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max'


def identifier(reservation):
    value = reservation.read_text().strip()
    assert re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value)
    return value


def remove(reservation):
    if not reservation.exists():
        return
    device = identifier(reservation)
    deadline = time.monotonic() + 240
    try:
        sim('shutdown', device, deadline=deadline)
    except subprocess.CalledProcessError:
        devices = json.loads(sim('list', 'devices', '--json', deadline=deadline))['devices']
        existing = [d for group in devices.values() for d in group if d['udid'] == device]
        if existing and existing[0]['state'] != 'Shutdown':
            raise
        if not existing:
            reservation.unlink()
            return
    sim('delete', device, deadline=deadline)
    devices = json.loads(sim('list', 'devices', '--json', deadline=deadline))['devices']
    assert all(d['udid'] != device for group in devices.values() for d in group)
    reservation.unlink()


def install(app, witness, reservation, ready):
    deadline = time.monotonic() + 480
    device = sim('create', 'Signed VOLPAROSSA Weather', DEVICE, RUNTIME, deadline=deadline)
    with reservation.open('x') as output:
        output.write(device + '\n')
    assert identifier(reservation) == device
    sim('bootstatus', device, '-b', deadline=deadline)
    # FrontBoard must know both bundle IDs before this simulator signals the publisher.
    runner_id = 'org.volparossa.test.weather-witness.xctrunner'
    for bundle, expected in ((app, BUNDLE), (witness, runner_id)):
        with (bundle / 'Info.plist').open('rb') as stream:
            assert plistlib.load(stream)['CFBundleIdentifier'] == expected, 'unexpected simulator bundle'
        sim('install', device, str(bundle.resolve(strict=True)), deadline=deadline)
        location = Path(sim('get_app_container', device, expected, 'app', deadline=deadline))
        with (location / 'Info.plist').open('rb') as stream:
            assert plistlib.load(stream)['CFBundleIdentifier'] == expected, 'simulator registration mismatch'
    with ready.open('x') as stream:
        json.dump(dict(run=os.environ['GITHUB_RUN_ID'], attempt=os.environ['GITHUB_RUN_ATTEMPT'],
                       weather=os.environ['GITHUB_SHA'], app_installed=True), stream)


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1] == 'install':
        install(*(Path(v) for v in sys.argv[2:]))
    elif sys.argv[1] == 'remove':
        remove(Path(sys.argv[2]))
    else:
        raise ValueError('unknown simulator operation')
