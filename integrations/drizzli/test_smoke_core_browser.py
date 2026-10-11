#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert joined-proof boundaries. No browser, core, network or namespace launch."""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import smoke_core_browser as smoke


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture():
    # Minimal structures for Python's binding checks only. Actual forecast schema
    # validation belongs to the real preparation/bridge/client tests, not this fixture.
    run = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stamp = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    expires = int(time.time()) + 600
    query = dict(latitude=52.52, longitude=13.41, model="ifs", run=stamp(run), steps=[3, 9, 24],
                 includeWind=True, communityArea=True)
    times = [stamp(run + datetime.timedelta(hours=step)) for step in query["steps"]]
    forecast = dict(schema="volparossa.forecast.v1", kind="forecast", area=dict(latitude=52.52,
        longitude=13.41, sharing="public-community"), source=dict(model="ifs", model_run_at=query["run"]),
        units={"wind_10m": "m/s"}, freshness=dict(expires_at=stamp(run + datetime.timedelta(days=2))),
        samples=[dict(valid_at=when, lead_hours=step) for when, step in zip(times, query["steps"])])
    display = dict(coordinates="52.52° latitude, 13.41° longitude", native=times,
        values=[["10.0", "5.0", "216.9"] for _ in times], model_run="ifs · " + query["run"],
        expires_at=stamp(datetime.datetime.fromtimestamp(expires, datetime.timezone.utc)))
    expected = dict(schema=1, core_sha256="c" * 64, cold_receipt_sha256="d" * 64,
        publication=dict(publisher_key="a" * 64, name="weather/test", revision=1, manifest_id="b" * 64,
                         sha256="e" * 64, bytes=1000, expires_unix_seconds=expires),
        forecast=forecast, display=display, display_sha256=digest(smoke.canonical(display)))
    config = dict(core=dict(mode="core-cache", reuseCache=True, publisherKey="a" * 64,
                           name="weather/test", minRevision=1, query=query), variables=["temperature_2m"])
    return expected, config


class BindingTests(unittest.TestCase):
    def test_expected_binds_query_native_steps_publication_expiry_and_display_hash(self):
        expected, config = fixture()
        self.assertIs(smoke.validate_expected(expected, config), expected)
        self.assertEqual(smoke.canonical({"z": "° ·", "a": [2, 1]}), '{"a":[2,1],"z":"° ·"}'.encode())
        mutations = [
            lambda e: e["publication"].update(revision=0),
            lambda e: e["publication"].update(name="weather/different"),
            lambda e: e["publication"].update(expires_unix_seconds=1),
            lambda e: e["forecast"]["area"].update(sharing="private"),
            lambda e: e["forecast"]["area"].update(latitude=1),
            lambda e: e["display"]["native"].__setitem__(0, e["display"]["native"][1]),
            lambda e: e["display"]["values"][0].__setitem__(0, "99.0"),
            lambda e: e.update(core_sha256="unbound"),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(expected); mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                smoke.validate_expected(changed, config)
        config["core"]["reuseCache"] = False
        with self.assertRaises(ValueError):
            smoke.validate_expected(expected, config)

    def test_api_must_deliver_exact_cold_forecast_and_identity_not_renew_expiry(self):
        expected, _ = fixture()
        publication = expected["publication"]
        result = dict(schema="volparossa.weather.provider.v1", kind="forecast", forecast=expected["forecast"],
            delivery={**{key: publication[key] for key in ("publisher_key", "name", "revision", "manifest_id", "sha256")},
                      "mode": "core-cache", "upstream_origin_attested": False, "manifest_media_type_checked": False,
                      "publication_expires_at": expected["display"]["expires_at"]},
            freshness=dict(expires_at=expected["display"]["expires_at"]), timeline=dict(valid_at=expected["display"]["native"]))
        smoke.check_api(result, expected)
        for key, value in [("sha256", "f" * 64), ("manifest_id", "f" * 64), ("mode", "origin"),
                           ("upstream_origin_attested", True), ("publication_expires_at", "2099-01-01T00:00:00.000Z")]:
            changed = copy.deepcopy(result); changed["delivery"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                smoke.check_api(changed, expected)

    def test_real_dom_checks_values_times_location_and_second_fetch_not_just_a_label(self):
        expected, _ = fixture(); display = expected["display"]
        observed = dict(native=display["native"], values=display["values"],
            details=[display["coordinates"], display["model_run"], display["expires_at"]],
            apiRequests=1, attribution=True, licence=True, missing=True, localOnly=True)
        self.assertTrue(smoke.check_dom(observed, expected, 1))
        self.assertFalse(smoke.check_dom(observed, expected, 2))
        observed["apiRequests"] = 2
        self.assertTrue(smoke.check_dom(observed, expected, 2))
        for key, value in [("native", []), ("values", []), ("details", ["Amsterdam"]),
                           ("attribution", False), ("licence", False), ("missing", False), ("localOnly", False)]:
            self.assertFalse(smoke.check_dom({**observed, key: value}, expected, 2))

    def test_receipt_starts_without_execution_or_standalone_overlay_claims(self):
        report = smoke.report_base({}, fixture()[0])
        self.assertFalse(report["passed"])
        self.assertTrue(all(value is False for value in report["scope"].values()))

    def test_wait_hashes_observed_dom_and_caps_socket_wait_at_remaining_deadline(self):
        expected, _ = fixture(); display = expected["display"]
        observed = dict(native=display["native"], values=display["values"],
            details=[display["coordinates"], display["model_run"], display["expires_at"]],
            apiRequests=2, attribution=True, licence=True, missing=True, localOnly=True)
        connection = Mock()
        with patch.object(smoke, "dom", return_value=observed), \
             patch.object(smoke.time, "monotonic", side_effect=[0, 59, 59]):
            self.assertEqual(smoke.wait_dom(Mock(), connection, expected, 2), expected["display_sha256"])
        self.assertEqual(connection.settimeout.call_args_list[0].args, (1,))
        with patch.object(smoke.time, "monotonic", side_effect=[0, 60]), self.assertRaises(TimeoutError):
            smoke.wait_dom(Mock(), Mock(), expected, 1)


class FilesystemTests(unittest.TestCase):
    def test_owned_cleanup_preserves_receipt_and_refuses_swapped_identity_or_symlink(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            work = Path(directory); owned = smoke.identity(work)
            (work / "scratch").mkdir(mode=0o700)
            (work / "report.json").write_text("retained")
            self.assertFalse(smoke.cleanup(work, (owned[0], owned[1] + 1)))
            self.assertTrue((work / "scratch").exists())
            (work / "profile").symlink_to(work / "elsewhere")
            self.assertFalse(smoke.cleanup(work, owned))
            self.assertFalse((work / "scratch").exists())
            self.assertTrue((work / "profile").is_symlink())
            self.assertEqual((work / "report.json").read_text(), "retained")

    def test_descriptor_inputs_refuse_hardlinks_symlinks_size_and_permissions(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            work = Path(directory); value = work / "input"
            value.write_bytes(b"public"); value.chmod(0o400)
            self.assertEqual(smoke.file_hash(value, 6, 0o400), (digest(b"public"), 6))
            self.assertEqual(smoke.raw_file(value, 6, 0o400), b"public")
            with self.assertRaises(ValueError): smoke.file_hash(value, 5)
            value.chmod(0o620)
            with self.assertRaises(ValueError): smoke.raw_file(value, 6)
            value.chmod(0o400); (work / "symlink").symlink_to(value)
            with self.assertRaises(ValueError): smoke.raw_file(work / "symlink", 6)
            os.link(value, work / "hardlink")
            with self.assertRaises(ValueError): smoke.file_hash(value, 6)

    def test_manifest_binds_complete_immutable_tree_and_built_assets(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            root = Path(directory)
            assets = {"index.html": digest(b"test asset")}
            retained = json.dumps({"source": {"built_tree_sha256": digest(smoke.canonical(assets))}}).encode()
            inputs = {
                "volparossa-weather/integrations/drizzli/smoke_core_browser.py": b"inert driver",
                "volparossa-weather/integrations/drizzli/prepare-core-browser.mjs": b"inert preparer",
                "volparossa-weather/integrations/drizzli/browser-smoke.json": retained,
                "volparossa-weather/scripts/serve-provider.mjs": b"inert bridge",
                **{f"volparossa-weather/src/{name}.mjs": b"inert source" for name in ("provider-http", "provider-core", "core-cache")},
                "volparossa-weather/build/drizzli-volparossa/build/index.html": b"test asset",
                "runtime/node": b"not an executable runtime",
            }
            records = {}
            for name, raw in inputs.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw); path.chmod(0o400)
                records[name] = dict(bytes=len(raw), mode=0o400, sha256=digest(raw))
            manifest = smoke.canonical(dict(version=1, kind="volparossa-weather-client-inputs", files=records)) + b"\n"
            (root / "INPUTS.json").write_bytes(manifest); (root / "INPUTS.json").chmod(0o400)
            for path in [root, *root.rglob("*")]:
                if path.is_dir(): path.chmod(0o500)
            try:
                with patch.object(smoke, "ROOT", root / "volparossa-weather"), \
                     patch.object(smoke.shared, "NODE_SHA256", digest(inputs["runtime/node"])), \
                     patch.object(smoke.shared, "validate_stage", return_value={"test": "inert"}):
                    result = smoke.validate_bundle(root, digest(manifest))
                    self.assertEqual(result[3]["built_tree_sha256"], digest(smoke.canonical(assets)))
                    with self.assertRaises(ValueError): smoke.validate_bundle(root, "f" * 64)
                    path = root / "runtime/node"; path.chmod(0o600); path.write_bytes(b"changed"); path.chmod(0o400)
                    with self.assertRaises(ValueError): smoke.validate_bundle(root, digest(manifest))
            finally:
                for path in [root, *root.rglob("*")]:
                    if path.is_dir(): path.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
