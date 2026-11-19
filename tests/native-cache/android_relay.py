# SPDX-License-Identifier: GPL-3.0-only
"""Forward only actual emulator API reads to the offline guest over virtio."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import socket
import sys
import time

from android_channel import ROUTES


def wait_for(check, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    raise TimeoutError('android handoff timeout')


def relay(channel, work):
    with socket.socket(socket.AF_UNIX) as connection, HTTPServer(('127.0.0.1', 43210), Handler) as server:
        wait_for(channel.exists, 450)
        connection.settimeout(240)
        connection.connect(str(channel))
        with connection.makefile('rwb', buffering=0) as device:
            server.timeout = 60
            for phase in ('initial', 'refused', 'recovered'):
                assert device.readline(40) == (phase + '\n').encode(), phase
                (work / (phase + '.ready')).touch(exist_ok=False)
                receipts = {}
                for route in ROUTES:
                    server.route, server.device, server.received = route, device, None
                    server.handle_request()
                    assert server.received is not None, (phase, route)
                    receipts[route] = server.received
                temporary = work / (phase + '.part')
                temporary.write_text(json.dumps(receipts))
                temporary.rename(work / (phase + '.json'))
                wait_for((work / (phase + '.observed')).is_file, 35)
                device.write((phase + '-observed\n').encode())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        if (self.client_address[0] != '127.0.0.1' or self.headers.get_all('Host') != ['127.0.0.1:43210']
                or self.path != ROUTES[server.route]):
            self.send_error(403)
            return
        server.device.write((server.route + '\n').encode())
        raw = server.device.readline(262145)
        assert raw.endswith(b'\n') and len(raw) < 262144
        status, body = json.loads(raw)
        assert status in (200, 503)
        response = json.dumps(body, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(response)
        server.received = [status, body]


if __name__ == '__main__':
    relay(Path(sys.argv[1]), Path(sys.argv[2]))
