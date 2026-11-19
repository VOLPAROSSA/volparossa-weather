# SPDX-License-Identifier: GPL-3.0-only
"""Wait for a named artifact from this exact workflow attempt and return its GitHub ID."""
import json
import os
import subprocess
import sys
import time


def api(path):
    try:
        response = subprocess.run(['gh', 'api', path], capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    return json.loads(response.stdout) if response.returncode == 0 else None


def wait(kind):
    assert kind in ('ready', 'inputs')
    run = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    name = f"iphone-{kind}-{os.environ['GITHUB_SHA']}-{attempt}"
    endpoint = f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run}"
    peer = 'iphone' if kind == 'ready' else 'media'
    deadline = time.monotonic() + 1800
    next_peer_check = 0
    while time.monotonic() < deadline:
        artifacts = api(endpoint + '/artifacts') or {}
        items = [a for a in artifacts.get('artifacts', []) if a['name'] == name and not a['expired']]
        if items:
            item, = items
            assert item['workflow_run']['id'] == int(run) and 0 < item['size_in_bytes'] < 512 * 1024**2
            assert isinstance(item['id'], int) and item['id'] > 0
            return item['id']
        if time.monotonic() >= next_peer_check:
            jobs = api(f'{endpoint}/attempts/{attempt}/jobs') or {}
            if any(j['name'] == peer and j['status'] == 'completed' and j['conclusion'] != 'success'
                   for j in jobs.get('jobs', [])):
                raise RuntimeError(f'The {peer} job stopped before sending its {kind} artifact')
            next_peer_check = time.monotonic() + 60
        time.sleep(12)
    raise TimeoutError(f'The {kind} artifact did not arrive from the current workflow attempt')


if __name__ == '__main__':
    print(wait(sys.argv[1]))
