# SPDX-License-Identifier: GPL-3.0-only
"""Run the real Weather HTTP bridge and Core daemon as an independent owner in a networkless Debian guest."""
from contextlib import contextmanager, nullcontext
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

import android_channel

ROOT = Path(__file__).resolve().parents[2]
CLI = "/usr/bin/volparossa"
NODE = shutil.which("node")
NAME = "weather.public-community-cache-trial"
# Software-emulated amd64 needs more time to start Node and the Core client.
CALL_TIMEOUT = 60 if Path('/dev/virtio-ports/weather.iphone').exists() else 10


@contextmanager
def child(args, env=None):
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, start_new_session=True)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=CALL_TIMEOUT)
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
        if not ready.select(CALL_TIMEOUT):
            raise RuntimeError("bridge readiness timeout")
        return urlsplit(json.loads(proc.stdout.readline(4096))["listening"])


def get(origin, path='/api/volparossa/forecast'):
    assert origin.scheme == "http" and origin.hostname == "127.0.0.1" and origin.port
    conn = http.client.HTTPConnection(origin.hostname, origin.port, timeout=CALL_TIMEOUT)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        raw = res.read(262145)
        assert len(raw) <= 262144 and res.getheader("Cache-Control") == "no-store"
        return res.status, json.loads(raw)
    finally:
        conn.close()


def read_client(origin):
    result = subprocess.run([NODE, ROOT / "tests/native-cache/read-client.mjs", origin.geturl()],
                            capture_output=True, check=True, timeout=CALL_TIMEOUT)
    return json.loads(result.stdout)


def bridge_config(core, forecast, quality=None):
    query = dict(latitude=52.52, longitude=13.41, run=forecast["source"]["model_run_at"], model="ifs",
                 steps=[24], communityArea=True, includeWind=False, includePrecipitation=False)
    config = dict(core=dict(core, query=query), variables=["temperature_2m"])
    if quality is not None:
        source = quality["source"]
        aq_query = dict(latitude=52.52, longitude=13.41, run=source["model_run_at"], model=source["model"],
                        steps=[24], communityArea=True)
        config["airQuality"] = dict(core=dict(core, cache="/var/lib/volparossa/air-quality-cache",
            name="weather.public-community-air-trial", query=aq_query), variables=["pm2_5", "pm10"])
    return config


def run(root, source, publication):
    interfaces = sorted(name for _, name in socket.if_nameindex())
    assert os.getuid() and interfaces == ["lo"], "only the loopback interface may be present"
    cache = Path("/var/lib/volparossa/forecast-cache")
    assert not os.access(cache, os.R_OK), "owner must be separate from the daemon cache"
    control = Path("/run/volparossa/control/agent.sock")
    assert control.is_socket() and control.stat().st_uid != os.getuid()
    pub = json.loads(publication.read_bytes())
    assert pub["operation"] == "offline_content_publish" and pub["network_publication"] is False
    next_file = publication.with_name("replacement.json")
    replacement = json.loads(next_file.read_bytes())
    next_file.unlink()
    assert replacement["operation"] == "offline_content_publish" and replacement["network_publication"] is False
    assert replacement["publisher_key_hex"] == pub["publisher_key_hex"]
    assert replacement["manifest_id"] != pub["manifest_id"] and replacement["expires_unix_seconds"] > pub["expires_unix_seconds"]
    forecast = json.loads(source.read_bytes())
    wire_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    source.unlink()
    publication.unlink()
    for name in ("scratch", "www"):
        (root / name).mkdir(mode=0o700)
    (root / "www/index.html").write_text("<title>Weather cache trial</title>\n")
    core = dict(mode="core-cache", executable=CLI, controlSocket=str(control), cache=str(cache),
                scratchParent=str(root/"scratch"), name=NAME, minRevision=1, cacheMode="cache-only",
                publisherKey=pub["publisher_key_hex"])
    cfg = root / "weather.json"
    iphone = Path('/dev/virtio-ports/weather.iphone')
    mobile_port = iphone if iphone.exists() else android_channel.PORT
    mobile = mobile_port.exists()
    mobile_responses = {}
    quality = None
    if mobile:
        aq_path = publication.with_name('air-quality.json')
        quality = json.loads(aq_path.read_bytes())
        aq_path.unlink()
    config = bridge_config(core, forecast, quality)
    cfg.write_text(json.dumps(config))
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
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=CALL_TIMEOUT)
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
    channel = mobile_port.open('r+b', buffering=0) if mobile else nullcontext()
    with child(bridge) as second, channel as port:
        origin = opening(second)
        status, body = get(origin)
        assert status == 200 and body["forecast"] == forecast and body["delivery"]["manifest_id"] == pub["manifest_id"]
        initial = read_client(origin)
        assert initial["manifest"] == pub["manifest_id"] and initial["expiry"] == body["freshness"]["expires_at"]
        assert initial["run"] == forecast["source"]["model_run_at"] and initial["valid"] == forecast["samples"][0]["valid_at"]
        assert abs(float(initial["display"]) - forecast["samples"][0]["temperature_2m"]) <= 0.051
        if mobile:
            mobile_responses['initial'] = android_channel.exchange(port, 'initial', origin, get)
        remaining = signed_expiry - time.time()
        assert 0 < remaining <= (240 if mobile_port == iphone else 60)
        time.sleep(remaining + 0.05)
        observed = time.time()
        assert signed_expiry <= observed and get(origin) == (503, {"error": "FORECAST_UNAVAILABLE"})
        assert list((root/"scratch").iterdir()) == []
        assert read_client(origin) == {"error": "FORECAST_UNAVAILABLE"}
        expired_output = root / "expired-forecast.json"
        denied = subprocess.run([*command, "--local-output", expired_output],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=CALL_TIMEOUT)
        assert denied.returncode != 0 and not expired_output.exists()
        if mobile:
            mobile_responses['refused'] = android_channel.exchange(port, 'refused', origin, get)
        # The separate publisher may now deliver its pre-signed revision. The Weather account
        # still has neither the publisher's keys nor filesystem access to its cache.
        Path("/run/weather-recovery/advance").write_bytes(b"1")
        stop = time.monotonic() + max(15, CALL_TIMEOUT)
        while True:
            recovered = read_client(origin)
            if recovered != {"error": "FORECAST_UNAVAILABLE"}:
                break
            assert time.monotonic() < stop, "client did not recover"
            time.sleep(.15)
        assert recovered["manifest"] == replacement["manifest_id"] and recovered["expiry"] > initial["expiry"]
        assert all(recovered[key] == initial[key] for key in ("display", "run", "valid"))
        status, body = get(origin)
        assert status == 200 and body["forecast"] == forecast and body["delivery"]["revision"] == 2
        assert body["delivery"]["manifest_id"] == recovered["manifest"] and body["delivery"]["cache_only"]
        assert list((root/"scratch").iterdir()) == []
        if mobile:
            mobile_responses['recovered'] = android_channel.exchange(port, 'recovered', origin, get)
    evidence = forecast["samples"][0]["evidence"]
    return dict(schema=1, core_sha=os.environ["CORE_SOURCE"], weather_sha=os.environ["GITHUB_SHA"],
                product_sha256=wire_hash, manifest_id=pub["manifest_id"], signed_expires_unix=signed_expiry,
                rejection_unix_ms=int(observed*1000), origin_field_sha256=evidence["field_sha256"],
                decoder_sha256=evidence["decoder_sha256"], model_run=forecast["source"]["model_run_at"],
                acquired_at=forecast["source"]["acquired_at"], valid_at=forecast["samples"][0]["valid_at"],
                temperature_c=forecast["samples"][0]["temperature_2m"], cache_seed="original signed local publication",
                distinct_weather_owner=True, cache_only=True, reads_before_expiry=3, bridge_restarted=True, http_after_expiry=503,
                drizzli_rejected_expired=True, drizzli_recovered=True, revision_after_recovery=2,
                replacement_manifest_id=recovered["manifest"], drizzli_displayed_temperature_c=recovered["display"],
                network_interfaces=interfaces, core_refused_expired=True, original_plaintext_removed=True, scratch_empty=True,
                **({('iphone_requests' if mobile_port == iphone else 'android_requests'): mobile_responses} if mobile else {}))


if __name__ == "__main__":
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="weather-expiry-", dir="/tmp") as directory:
        evidence = run(Path(directory), Path(sys.argv[1]), Path(sys.argv[2]))
    assert not Path(directory).exists()
    print(json.dumps(dict(evidence, processes_joined=True, private_directory_removed=True), sort_keys=True))
