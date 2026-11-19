# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the ordinary iOS app against an independently signed, live Debian Core cache."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import time

from media import CORE, DEBIAN, digest
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'native-cache'))
sys.path.insert(0, str(HERE.parent / 'ios-simulator'))
from android_relay import relay
from observe import BUNDLE, sim

RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max'
PHASES = ('initial', 'refused', 'recovered')
SCREENS = ('initial', 'expired', 'refused', 'recovered')


@contextmanager
def child(args, log):
    with log.open('xb') as stream:
        proc = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT)
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def run_guest(work, medium, stack):
    overlay = work / 'overlay.qcow2'
    subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'qcow2', '-b',
                    medium / 'base.qcow2', overlay, '8G'], check=True, timeout=30)
    forward = stack.enter_context(child([sys.executable, '-B', __file__, 'relay', work], work / 'relay.log'))
    vm = stack.enter_context(child(['qemu-system-x86_64', '-accel', 'tcg', '-cpu', 'max', '-m', '1536', '-smp', '2',
        '-nic', 'none', '-rtc', 'base=utc,clock=host', '-display', 'none', '-monitor', 'none', '-no-reboot',
        '-serial', 'file:' + str(work / 'console'), '-device', 'virtio-serial-pci',
        '-chardev', f'file,id=result,path={work}/result', '-device', 'virtserialport,chardev=result,name=weather.result',
        '-chardev', f'socket,id=mobile,path={work}/mobile.sock,server=on,wait=off',
        '-device', 'virtserialport,chardev=mobile,name=weather.iphone',
        '-drive', f'if=virtio,format=qcow2,file={overlay}',
        '-drive', f'if=virtio,format=raw,readonly=on,file={medium}/seed.img',
        '-drive', f'media=cdrom,format=raw,readonly=on,file={medium}/data.iso'], work / 'qemu.log'))
    return vm, forward


class Control(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(4)
        raw = self.rfile.readline(80)
        assert raw.endswith(b'\n') and self.client_address[0] == '127.0.0.1'
        command = raw[:-1].decode('ascii')
        reply = self.server.command(command)
        self.wfile.write((reply + '\n').encode())


def drive(work, medium, build, device):
    frames = {}
    expected = iter(SCREENS)
    with ExitStack() as stack, socketserver.TCPServer(('127.0.0.1', 43211), Control) as server:
        vm = forward = None

        def command(name):
            nonlocal vm, forward
            if name == 'start' and vm is None:
                vm, forward = run_guest(work, medium, stack)
                print('Apple UI test ready; started the live Debian guest', flush=True)
                return 'ok'
            if name.startswith('ready-') and name[6:] in PHASES:
                return 'ok' if (work / (name[6:] + '.ready')).is_file() else 'wait'
            if name.startswith('value-') and name[6:] in PHASES:
                receipt = work / (name[6:] + '.json')
                if not receipt.exists():
                    return 'wait'
                status, body = json.loads(receipt.read_bytes())['weather']
                if status == 503:
                    assert name == 'value-refused' and body == {'error': 'FORECAST_UNAVAILABLE'}
                    return 'unavailable'
                assert status == 200
                return str(body['forecast']['samples'][0]['temperature_2m'])
            if name.startswith('screen-') and name[7:] in SCREENS:
                phase = name[7:]
                assert phase == next(expected)
                picture = work / (phase + '.png')
                sim('io', device, 'screenshot', str(picture), deadline=time.monotonic() + 100)
                assert picture.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
                frames[phase] = digest(picture)
                if phase != 'expired':
                    (work / (phase + '.observed')).touch(exist_ok=False)
                print('Observed mounted iPhone interface:', phase, flush=True)
                return 'ok'
            raise ValueError('unexpected UI witness operation')

        server.command = command
        server.timeout = 1
        spec, = (build / 'Build/Products').glob('*.xctestrun')
        test = stack.enter_context(child(['xcodebuild', '-quiet', 'test-without-building', '-xctestrun', spec,
            '-destination', 'platform=iOS Simulator,id=' + device, '-parallel-testing-enabled', 'NO',
            '-maximum-concurrent-test-simulator-destinations', '1', '-resultBundlePath', work / 'screens.xcresult'],
            work / 'xcuitest.log'))
        deadline = time.monotonic() + 2100
        while test.poll() is None:
            assert time.monotonic() < deadline, 'UI test elapsed deadline'
            if vm is not None:
                assert vm.poll() in (0, None) and forward.poll() in (0, None)
                if vm.poll() == 0 and 'recovered' not in frames:
                    raise RuntimeError('Debian stopped before the recovered interface')
            server.handle_request()
        assert test.returncode == 0 and tuple(frames) == SCREENS, 'Apple UI test incomplete'
        assert forward.wait(timeout=90) == 0 and vm.wait(timeout=150) == 0
    return frames


def verify(work, frames):
    result = work / 'result'
    assert result.stat().st_size <= 8192
    guest = json.loads(result.read_bytes())
    assert guest['weather_sha'] == os.environ['GITHUB_SHA'] and guest['core_sha'] == CORE
    assert guest['network_interfaces'] == ['lo'] and guest['http_after_expiry'] == 503
    assert all(guest[key] is True for key in ('distinct_weather_owner', 'core_refused_expired', 'processes_joined',
        'private_directory_removed', 'drizzli_rejected_expired', 'drizzli_recovered', 'cache_only'))
    assert guest['revision_after_recovery'] == 2 and guest['replacement_manifest_id'] != guest['manifest_id']
    products = {}
    air_delivery = None
    for phase in PHASES:
        receipt = json.loads((work / (phase + '.json')).read_bytes())
        status, forecast = receipt['weather']
        air_status, quality = receipt['air']
        assert [status, air_status] == guest['iphone_requests'][phase] == ([503, 200] if phase == 'refused' else [200, 200])
        assert quality['delivery']['cache_only'] is True and quality['delivery']['revision'] == 1
        air = quality['forecast']['samples'][0]
        current_air = [quality['delivery']['manifest_id'], air['pm2_5'], air['pm10']]
        if air_delivery is None:
            air_delivery = current_air
        assert current_air == air_delivery
        if phase == 'refused':
            assert forecast == {'error': 'FORECAST_UNAVAILABLE'}
        else:
            delivery = forecast['delivery']
            assert delivery['cache_only'] is True and delivery['revision'] == (1 if phase == 'initial' else 2)
            assert delivery['manifest_id'] == guest['manifest_id' if phase == 'initial' else 'replacement_manifest_id']
            assert delivery['sha256'] == guest['product_sha256']
            assert forecast['forecast']['samples'][0]['temperature_2m'] == guest['temperature_c']
        products[phase] = [status, air_status]
    return dict(core=guest, product_requests=products, air_manifest=air_delivery[0], pm2_5=air_delivery[1], pm10=air_delivery[2],
                screenshots_sha256=frames, screenshot_witness='XCTest accessibility and CoreSimulator framebuffer')


def diagnostics(work):
    for filename in ('xcuitest.log', 'qemu.log', 'relay.log', 'result', 'console'):
        path = work / filename
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 32768))
            lines = stream.read().decode(errors='replace').splitlines()
        markers = r'error|fail|timeout|assert|qemu-system|WeatherTests.swift|WitnessError|WEATHER_GUEST|WEATHER_API|guest diagnostics|expiry.py|stage='
        for line in [line for line in lines if re.search(markers, line, re.I)][-10:]:
            print(filename, line[:300], file=sys.stderr, flush=True)


def session(app, medium, build, output):
    assert os.environ['RUNNER_ENVIRONMENT'] == 'github-hosted' and os.uname().machine == 'arm64'
    with tempfile.TemporaryDirectory(prefix='vpw-', dir='/tmp') as trial:
        work = Path(trial)
        deadline = time.monotonic() + 480
        device = sim('create', 'Signed VOLPAROSSA Weather', DEVICE, RUNTIME, deadline=deadline)
        assert re.fullmatch(r'[A-Fa-f0-9-]{36}', device)
        try:
            sim('bootstatus', device, '-b', deadline=deadline)
            sim('install', device, str(app.resolve(strict=True)), deadline=deadline)
            frames = drive(work, medium, build, device)
            report = verify(work, frames)
        except BaseException:
            diagnostics(work)
            raise
        finally:
            cleanup = time.monotonic() + 240
            try:
                sim('shutdown', device, deadline=cleanup)
            finally:
                sim('delete', device, deadline=cleanup)
        devices = json.loads(sim('list', 'devices', '--json', deadline=cleanup))['devices']
        assert all(d['udid'] != device for runtime in devices.values() for d in runtime)
    report.update(runtime=RUNTIME, device=DEVICE, app_bundle=BUNDLE, upstream_revision=subprocess.check_output(
        ['git', '-C', 'build/ios-source', 'rev-parse', 'HEAD'], text=True).strip(), flutter_revision='f6ff1529fd6d8af5f706051d9251ac9231c83407',
        runner_sha256=digest(app / 'Runner'), app_sha256=digest(app / 'Frameworks/App.framework/App'), guest_nics=0,
        debian13_sha512=DEBIAN, accelerator='tcg', simulator_removed=True, core_executed=True, physical_device=False,
        refresh_taps=2, foreground_expiry=True, media=json.loads((medium / 'media.json').read_bytes()))
    output.write_text(json.dumps(report, sort_keys=True) + '\n')


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1] == 'relay':
        work = Path(sys.argv[2])
        relay(work / 'mobile.sock', work, connection_wait=1000, request_wait=200, observation_wait=220)
    else:
        session(*(Path(arg) for arg in sys.argv[1:]))
