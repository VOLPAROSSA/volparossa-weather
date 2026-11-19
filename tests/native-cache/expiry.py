# SPDX-License-Identifier: GPL-3.0-only
"""Run the real Weather HTTP bridge and Core daemon as an independent owner in a networkless Debian guest."""
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
import re
from pathlib import Path
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CLI = "/usr/bin/volparossa"
NODE = shutil.which("node")
NAME = "weather.public-community-cache-trial"


@contextmanager
def child(args, env=None):
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, start_new_session=True)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise
        proc.stdout.close()
        if proc.returncode not in (0, -signal.SIGTERM) and sys.exc_info()[0] is None:
            raise RuntimeError(f"child exited with status {proc.returncode}")


def opening(proc):
    with selectors.DefaultSelector() as ready:
        ready.register(proc.stdout, selectors.EVENT_READ)
        if not ready.select(10):
            raise RuntimeError("bridge readiness timeout")
        return urlsplit(json.loads(proc.stdout.readline(4096))["listening"])


def get(origin):
    assert origin.scheme == "http" and origin.hostname == "127.0.0.1" and origin.port
    conn = http.client.HTTPConnection(origin.hostname, origin.port, timeout=10)
    try:
        conn.request("GET", "/api/volparossa/forecast")
        res = conn.getresponse()
        raw = res.read(262145)
        assert len(raw) <= 262144 and res.getheader("Cache-Control") == "no-store"
        return res.status, json.loads(raw)
    finally:
        conn.close()


def run(root, source, publication):
    interfaces = sorted(name for _, name in socket.if_nameindex())
    assert os.getuid() and interfaces == ["lo"], "only the loopback interface may be present"
    cache = Path("/var/lib/volparossa/forecast-cache")
    assert not os.access(cache, os.R_OK), "owner must be separate from the daemon cache"
    control = Path("/run/volparossa/control/agent.sock")
    assert control.is_socket() and control.stat().st_uid != os.getuid()
    pub = json.loads(publication.read_bytes())
    assert pub["operation"] == "offline_content_publish" and pub["network_publication"] is False
    forecast = json.loads(source.read_bytes())
    wire_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    source.unlink()
    publication.unlink()
    for name in ("scratch", "www"):
        (root / name).mkdir(mode=0o700)
    (root / "www/index.html").write_text("<title>Weather cache trial</title>\n")
    query = dict(latitude=52.52, longitude=13.41, run=forecast["source"]["model_run_at"], model="ifs",
                 steps=[24], communityArea=True, includeWind=False, includePrecipitation=False)
    core = dict(mode="core-cache", executable=CLI, controlSocket=str(control), cache=str(cache),
                scratchParent=str(root/"scratch"), name=NAME, minRevision=1, cacheMode="cache-only",
                publisherKey=pub["publisher_key_hex"], query=query)
    cfg = root / "weather.json"
    cfg.write_text(json.dumps(dict(core=core, variables=["temperature_2m"])))
    bridge = [NODE, ROOT/"scripts/serve-provider.mjs", "--config", cfg, "--static-root", root/"www", "--port", "0"]
    signed_expiry = pub["expires_unix_seconds"]
    command = [CLI, "--control-socket", control, "content", "fetch-name", "--publisher-key",
               pub["publisher_key_hex"], "--name", NAME, "--min-revision", "1", "--cache", cache,
               "--quota-bytes", "131072", "--max-entries", "16", "--min-free-bytes", "67108864",
               "--reuse-cache", "--cache-only"]
    with child(bridge) as first:
        origin = opening(first)
        status, body = get(origin)
        if status != 200:
            # This extra offline call is used only on failure and only prints
            # closed error codes or cache mode and byte counters.
            raw = subprocess.run([*command, "--local-output", root / "diagnostic.json"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if raw.returncode == 0:
                report = json.loads(raw.stdout)
                detail = ",".join(f"{k}={report.get(k)}" for k in ("cache_only", "peer_bytes", "providers_used"))
            else:
                codes = re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{3,70}(?![A-Za-z0-9_])",
                                   raw.stderr[:4096].decode(errors="replace"))
                detail = ",".join(codes[:3]) or "CORE_REJECTED"
            print(f"WEATHER_API_DIAGNOSTIC=http={status},core={raw.returncode},{detail}", file=sys.stderr)
        assert status == 200 and body["forecast"] == forecast
        delivery = body["delivery"]
        assert delivery["cache_only"] is True and delivery["manifest_id"] == pub["manifest_id"]
        assert delivery["sha256"] == wire_hash and delivery["revision"] == 1
        assert int(time.time()) < signed_expiry and body["freshness"]["expires_at"] == delivery["publication_expires_at"]
    with child(bridge) as second:
        origin = opening(second)
        status, body = get(origin)
        assert status == 200 and body["forecast"] == forecast and body["delivery"]["manifest_id"] == pub["manifest_id"]
        remaining = signed_expiry - time.time()
        assert 0 < remaining < 61
        time.sleep(remaining + 0.05)
        observed = time.time()
        assert signed_expiry <= observed and get(origin) == (503, {"error": "FORECAST_UNAVAILABLE"})
        assert list((root/"scratch").iterdir()) == []
    expired_output = root / "expired-forecast.json"
    denied = subprocess.run([*command, "--local-output", expired_output],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert denied.returncode != 0 and not expired_output.exists()
    evidence = forecast["samples"][0]["evidence"]
    return dict(schema=1, core_sha=os.environ["CORE_SOURCE"], weather_sha=os.environ["GITHUB_SHA"],
                product_sha256=wire_hash, manifest_id=pub["manifest_id"], signed_expires_unix=signed_expiry,
                rejection_unix_ms=int(observed*1000), origin_field_sha256=evidence["field_sha256"],
                decoder_sha256=evidence["decoder_sha256"], model_run=forecast["source"]["model_run_at"],
                acquired_at=forecast["source"]["acquired_at"], valid_at=forecast["samples"][0]["valid_at"],
                temperature_c=forecast["samples"][0]["temperature_2m"], cache_seed="original signed local publication",
                distinct_weather_owner=True, cache_only=True, reads_before_expiry=2, bridge_restarted=True, http_after_expiry=503,
                network_interfaces=interfaces, core_refused_expired=True, original_plaintext_removed=True, scratch_empty=True)


if __name__ == "__main__":
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="weather-expiry-", dir="/tmp") as directory:
        evidence = run(Path(directory), Path(sys.argv[1]), Path(sys.argv[2]))
    assert not Path(directory).exists()
    print(json.dumps(dict(evidence, processes_joined=True, private_directory_removed=True), sort_keys=True))
