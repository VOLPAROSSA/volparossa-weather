# SPDX-License-Identifier: GPL-3.0-only
"""Run the real Weather HTTP bridge and Core daemon inside a loopback-only namespace."""
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
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
BIN = ROOT / "build/core/target/debug"
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
        if proc.returncode not in (0, -signal.SIGTERM):
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


def run(root, source):
    interfaces = sorted(name for _, name in socket.if_nameindex())
    assert os.getuid() and interfaces == ["lo"], "only the loopback interface may be present"
    forecast = json.loads(source.read_bytes())
    for name in ("state", "control", "credentials", "scratch", "www"):
        (root / name).mkdir(mode=0o700)
    (root / "www/index.html").write_text("<title>Weather cache trial</title>\n")
    password = root / "credentials/identity-passphrase"
    password.write_text(secrets.token_hex(32))
    identity = root / "state/identity.key"
    cli = str(BIN / "volparossa")
    subprocess.run([cli, "init", "--identity", identity, "--passphrase-file", password],
                   check=True, stdout=subprocess.DEVNULL, timeout=30)
    config = root / "config.yaml"
    config.write_text("roles:\n  client: true\n  relay: false\n  exit: false\n"
                      "network:\n  listen_addresses: [/ip4/127.0.0.1/udp/0/quic-v1]\n  bootstrap_peers: []\n"
                      "privacy:\n  metrics_enabled: false\ncontent_contribution:\n  enabled: false\n"
                      "dns_cache:\n  enabled: false\nsharing:\n  enabled: false\ndownload_sharing:\n  enabled: false\n"
                      "wifi_mesh:\n  enabled: false\n")
    control = root / "control/agent.sock"
    env = dict(os.environ, VOLPAROSSA_CONFIG=str(config), VOLPAROSSA_STATE_DIRECTORY=str(root/"state"),
               VOLPAROSSA_CONTROL_SOCKET=str(control), CREDENTIALS_DIRECTORY=str(root/"credentials"),
               VOLPAROSSA_HELPER_SOCKET=str(root/"control/absent-helper.sock"),
               VOLPAROSSA_MPQUIC_SOCKET=str(root/"control/absent-mpquic.sock"))
    with child([BIN/"volparossa-agent"], env=env) as agent:
        deadline = time.monotonic() + 20
        while not control.is_socket():
            assert time.monotonic() < deadline and agent.poll() is None, "agent readiness"
            time.sleep(0.1)
        cache, manifest = root / "cache", root / "manifest"
        pub = json.loads(subprocess.check_output([cli, "content", "publish", "--input", source, "--cache", cache,
            "--identity", identity, "--passphrase-file", password, "--manifest", manifest, "--name", NAME,
            "--revision", "1", "--content-type", "application/vnd.volparossa.forecast.v1+json",
            "--lifetime-seconds", "25", "--quota-bytes", "131072", "--max-entries", "16",
            "--min-free-bytes", "67108864"], timeout=20))
        assert pub["operation"] == "offline_content_publish" and pub["network_publication"] is False
        subprocess.run([BIN/"examples/remember_weather_manifest", cache, manifest, pub["publisher_key_hex"]],
                       check=True, timeout=10)
        wire_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        source.unlink()
        manifest.unlink()
        assert not source.exists() and not manifest.exists()
        query = dict(latitude=52.52, longitude=13.41, run=forecast["source"]["model_run_at"], model="ifs",
                     steps=[24], communityArea=True, includeWind=False, includePrecipitation=False)
        core = dict(mode="core-cache", executable=cli, controlSocket=str(control), cache=str(cache),
                    scratchParent=str(root/"scratch"), name=NAME, minRevision=1, cacheMode="cache-only",
                    publisherKey=pub["publisher_key_hex"], query=query)
        cfg = root / "weather.json"
        cfg.write_text(json.dumps(dict(core=core, variables=["temperature_2m"])))
        bridge = [NODE, ROOT/"scripts/serve-provider.mjs", "--config", cfg, "--static-root", root/"www", "--port", "0"]
        signed_expiry = pub["expires_unix_seconds"]
        with child(bridge) as first:
            origin = opening(first)
            status, body = get(origin)
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
            assert 0 < remaining < 26
            time.sleep(remaining + 0.05)
            observed = time.time()
            assert signed_expiry <= observed and get(origin) == (503, {"error": "FORECAST_UNAVAILABLE"})
            assert list((root/"scratch").iterdir()) == []
    evidence = forecast["samples"][0]["evidence"]
    return dict(schema=1, core_sha=os.environ["CORE_SOURCE"], weather_sha=os.environ["GITHUB_SHA"],
                product_sha256=wire_hash, manifest_id=pub["manifest_id"], signed_expires_unix=signed_expiry,
                rejection_unix_ms=int(observed*1000), origin_field_sha256=evidence["field_sha256"],
                decoder_sha256=evidence["decoder_sha256"], model_run=forecast["source"]["model_run_at"],
                acquired_at=forecast["source"]["acquired_at"], valid_at=forecast["samples"][0]["valid_at"],
                temperature_c=forecast["samples"][0]["temperature_2m"], cache_seed="original signed local publication",
                cache_only=True, reads_before_expiry=2, bridge_restarted=True, http_after_expiry=503,
                network_interfaces=interfaces, original_plaintext_removed=True, scratch_empty=True)


if __name__ == "__main__":
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="weather-expiry-", dir="/tmp") as directory:
        evidence = run(Path(directory), Path(sys.argv[1]))
    assert not Path(directory).exists()
    print(json.dumps(dict(evidence, processes_joined=True, private_directory_removed=True), sort_keys=True))
