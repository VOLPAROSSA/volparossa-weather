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


def sim(*args, timeout=60):
    return subprocess.check_output(['xcrun', 'simctl', *args], text=True, timeout=timeout).strip()


def observe(app, screen, output):
    runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
    device_type = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max'
    device = sim('create', 'VOLPAROSSA Weather trial', device_type, runtime)
    assert re.fullmatch(r'[0-9A-Fa-f-]{36}', device)
    try:
        sim('boot', device)
        sim('bootstatus', device, '-b', timeout=240)
        sim('install', device, str(app), timeout=90)
        assert sim('get_app_container', device, BUNDLE, 'app').endswith('/Runner.app')
        pair = json.loads(subprocess.check_output(['node', HERE / 'fixture.mjs'], timeout=15))
        with ThreadingHTTPServer(('127.0.0.1', 43210), Handler) as server:
            server.calls, server.lock = [], threading.Lock()
            server.bodies = {k: json.dumps(v, separators=(',', ':')).encode() for k, v in pair.items()}
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                assert re.fullmatch(re.escape(BUNDLE) + r': [1-9][0-9]*', sim('launch', device, BUNDLE))
                deadline = time.monotonic() + 100
                observations = {}
                with tempfile.TemporaryDirectory(prefix='weather-screen-') as directory:
                    path = Path(directory) / 'screen.png'
                    while time.monotonic() < deadline:
                        with server.lock:
                            calls = server.calls.copy()
                        if calls == ['weather', 'air']:
                            sim('io', device, 'screenshot', str(path))
                            observations = json.loads(subprocess.check_output([screen, path], timeout=20))
                            if all(observations.get(key) for key in ('provider_header', 'native_forecast', 'ifs_model')):
                                break
                        time.sleep(1)
                    else:
                        raise RuntimeError(f'iPhone screen did not show the loaded Weather profile: reads={calls}, screen={observations}')
                    screenshot_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                sim('terminate', device, BUNDLE)
            finally:
                server.shutdown()
                thread.join(timeout=10)
                assert not thread.is_alive()
            assert server.calls == ['weather', 'air']
            result = dict(runtime=runtime, device=device_type, app_bundle=BUNDLE, installed=True, launched=True,
                          product_requests=server.calls, screen=observations, screenshot_sha256=screenshot_sha,
                          source_sha256={k: hashlib.sha256(v).hexdigest() for k, v in server.bodies.items()},
                          synthetic_products=True, core_executed=False)
    finally:
        try:
            sim('shutdown', device)
        finally:
            sim('delete', device)
    remaining = json.loads(sim('list', 'devices', '--json'))['devices']
    assert all(d['udid'] != device for devices in remaining.values() for d in devices)
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
