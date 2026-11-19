# SPDX-License-Identifier: GPL-3.0-only
"""One bidirectional virtio port. Only the two public application reads can cross it."""
import json
from pathlib import Path

PORT = Path('/dev/virtio-ports/weather.android')
ROUTES = {'weather': '/api/volparossa/forecast', 'air': '/api/volparossa/air-quality'}


def exchange(stream, phase, origin, get):
    stream.write((phase + '\n').encode())
    seen = []
    for expected in ('weather', 'air'):
        assert stream.readline(40) == (expected + '\n').encode()
        status, body = get(origin, ROUTES[expected])
        assert status == (503 if phase == 'refused' and expected == 'weather' else 200)
        if status == 200:
            assert body['delivery']['cache_only'] is True
            assert body['delivery']['revision'] == (2 if phase == 'recovered' and expected == 'weather' else 1)
        else:
            assert body == {'error': 'FORECAST_UNAVAILABLE'}
        raw = json.dumps([status, body], separators=(',', ':')).encode() + b'\n'
        assert len(raw) < 262144
        stream.write(raw)
        seen.append(status)
    # The host acknowledges after observing the actual mounted Android widgets.
    assert stream.readline(40) == (phase + '-observed\n').encode()
    return seen
