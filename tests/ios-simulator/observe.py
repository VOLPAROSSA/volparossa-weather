# SPDX-License-Identifier: GPL-3.0-only
"""Open the regular source-built app on a fresh iPhone, serve a synthetic pair and read its screen."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
ROUTES = {'/api/volparossa/forecast': 'weather', '/api/volparossa/air-quality': 'air'}
BUNDLE = 'com.marotidev.overmorrow'


def remaining(deadline):
    return max(.1, deadline - time.monotonic())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        kind = ROUTES.get(self.path)
        if self.client_address[0] != '127.0.0.1' or self.headers.get_all('Host') != ['127.0.0.1:43210'] or not kind:
            self.send_error(403)
            return
        with self.server.lock:
            self.server.calls.append(kind)
            allowed = self.server.calls == ['weather'] or self.server.calls == ['weather', 'air']
        if not allowed:
            self.send_error(409)
            return
        raw = self.server.bodies[kind]
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)
        self.wfile.flush()
        if kind == 'air':
            self.server.complete.set()


def sim(*args, deadline):
    return subprocess.check_output(['xcrun', 'simctl', *args], text=True, timeout=remaining(deadline)).strip()


def capture(app, device, directory, setup_deadline):
    # CoreSimulator starts system services and installs a full upstream debug
    # bundle on the same runner. Give setup one bounded budget. The time
    # available to the running application is measured separately below.
    started = time.monotonic()
    sim('bootstatus', device, '-b', deadline=setup_deadline)
    booted = time.monotonic()
    print(f'iPhone simulator booted in {booted - started:.1f}s', flush=True)
    sim('install', device, str(app.resolve(strict=True)), deadline=setup_deadline)
    print(f'Original app installed in {time.monotonic() - booted:.1f}s', flush=True)
    # Start this short-lived pair only after installation, within the same setup budget.
    pair = json.loads(subprocess.check_output(['node', HERE / 'fixture.mjs'], timeout=remaining(setup_deadline)))
    frames = []
    with ThreadingHTTPServer(('127.0.0.1', 43210), Handler) as server:
        server.calls, server.lock, server.complete = [], threading.Lock(), threading.Event()
        server.bodies = {k: json.dumps(v, separators=(',', ':')).encode() for k, v in pair.items()}
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            assert re.fullmatch(re.escape(BUNDLE) + r': [1-9][0-9]*', sim('launch', device, BUNDLE, deadline=setup_deadline))
            deadline = time.monotonic() + 100
            assert server.complete.wait(85), 'iPhone did not finish both product requests'
            # Capture the actual running screen while Flutter renders the arrived
            # products. Vision runs after simulator removal to avoid competing
            # with its large working set on the hosted Apple VM.
            for i in range(3):
                path = directory / f'forecast-{i}.png'
                if i:
                    time.sleep(2)
                sim('io', device, 'screenshot', str(path), deadline=deadline)
                frames.append(path)
        finally:
            server.shutdown()
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert server.calls == ['weather', 'air']
        return frames, {k: hashlib.sha256(v).hexdigest() for k, v in server.bodies.items()}


def observe(app, screen, output):
    runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
    device_type = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max'
    with tempfile.TemporaryDirectory(prefix='weather-screen-') as directory:
        setup_deadline = time.monotonic() + 480
        device = sim('create', 'VOLPAROSSA Weather trial', device_type, runtime, deadline=setup_deadline)
        assert re.fullmatch(r'[0-9A-Fa-f-]{36}', device)
        try:
            frames, hashes = capture(app, device, Path(directory), setup_deadline)
        finally:
            cleanup_deadline = time.monotonic() + 240
            try:
                sim('shutdown', device, deadline=cleanup_deadline)
            finally:
                sim('delete', device, deadline=cleanup_deadline)
        devices = json.loads(sim('list', 'devices', '--json', deadline=cleanup_deadline))['devices']
        assert all(d['udid'] != device for group in devices.values() for d in group)
        deadline = time.monotonic() + 65
        for path in reversed(frames):
            observations = json.loads(subprocess.check_output([screen, path], timeout=remaining(deadline)))
            if all(observations.get(key) for key in ('provider_header', 'native_forecast', 'ifs_model')):
                break
        else:
            raise RuntimeError(f'iPhone forecast could not be recognized in the captured frames: {observations}')
        result = dict(runtime=runtime, device=device_type, app_bundle=BUNDLE, installed=True, launched=True,
                      product_requests=['weather', 'air'], screen=observations, screenshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      captured_frames=len(frames), source_sha256=hashes, synthetic_products=True, core_executed=False)
    result['simulator_removed'] = True
    result['weather_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    result['upstream_revision'] = subprocess.check_output(
        ['git', '-C', 'build/ios-source', 'rev-parse', 'HEAD'], text=True).strip()
    result['flutter_revision'] = 'f6ff1529fd6d8af5f706051d9251ac9231c83407'
    for binary in (app / 'Runner', app / 'Frameworks/App.framework/App'):
        with binary.open('rb') as stream:
            result[binary.stem.lower() + '_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    output.write_text(json.dumps(result, sort_keys=True) + '\n')


if __name__ == '__main__':
    observe(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
