#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Joined-proof boundaries. No browser, core or external network execution.

One optional, bounded bwrap regression only reads an existing public executable
in a fresh loopback-only namespace. Other cases are inert filesystem/unit tests.
"""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
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


def products_fixture():
    weather, config = fixture()
    for key in ("schema", "core_sha256"):
        weather.pop(key)
    config["core"].update(executable="/inert/core", controlSocket="/inert/agent.sock", scratchParent="/inert/scratch",
                          cache="/inert/weather-cache")
    config["core"]["query"]["includePrecipitation"] = True
    config["variables"] = ["temperature_2m", "wind_speed_10m", "wind_direction_10m", "precipitation"]
    weather["forecast"]["units"]["precipitation"] = "mm"
    for sample, row in zip(weather["forecast"]["samples"], weather["display"]["values"]):
        sample["precipitation"] = dict(amount=0.01234, start_at=config["core"]["query"]["run"], end_at=sample["valid_at"])
        row.extend(["0.01234", sample["precipitation"]["start_at"] + " → " + sample["valid_at"]])
    weather["display_sha256"] = digest(smoke.canonical(weather["display"]))
    aq = copy.deepcopy(weather)
    aq["cold_receipt_sha256"] = "f" * 64
    aq["publication"].update(name="aq/test", manifest_id="1" * 64, sha256="2" * 64,
                            expires_unix_seconds=weather["publication"]["expires_unix_seconds"] - 100)
    aq_core = copy.deepcopy(config["core"])
    aq_core.update(name="aq/test", cache="/inert/aq-cache")
    aq_core["query"].pop("includeWind"); aq_core["query"].pop("includePrecipitation")
    run = datetime.datetime.fromtimestamp(smoke.stamp(config["core"]["query"]["run"]) - 6 * 3600, datetime.timezone.utc)
    stamp = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    aq_core["query"].update(model="gefs-aerosols", run=stamp(run), steps=[3, 6, 12])
    aq["forecast"].update(schema="volparossa.air-quality.forecast.v1", units={"pm2_5": "ug/m3", "pm10": "ug/m3"},
        source=dict(model="gefs-aerosols", model_run_at=stamp(run), provider="noaa", attribution="NOAA/NWS GEFS-Aerosols",
                    license="LicenseRef-NOAA-NODD", license_url="https://registry.opendata.aws/noaa-gefs/", changes="Inert test processing"),
        samples=[dict(lead_hours=step, valid_at=stamp(run + datetime.timedelta(hours=step))) for step in [3, 6, 12]])
    aq["display"].update(native=[sample["valid_at"] for sample in aq["forecast"]["samples"]],
        values=[["Not available", "11.5959"], ["0", "Not available"], ["5.53071", "0"]],
        model_run="gefs-aerosols · " + stamp(run),
        expires_at=stamp(datetime.datetime.fromtimestamp(aq["publication"]["expires_unix_seconds"], datetime.timezone.utc)),
        **{key: aq["forecast"]["source"][key] for key in ("attribution", "license", "license_url", "changes")})
    aq["display_sha256"] = digest(smoke.canonical(aq["display"]))
    config["airQuality"] = dict(core=aq_core, variables=["pm2_5", "pm10"])
    products = dict(weather=weather, air_quality=aq)
    expected = dict(schema=2, core_sha256="c" * 64, products=products,
        display_sha256=digest(smoke.canonical({name: p["display"] for name, p in products.items()})))
    return expected, config


def products_dom(expected, requests=1):
    output = dict(refreshReady=True)
    for name, product in expected["products"].items():
        display = product["display"]
        output[name] = dict(native=display["native"], values=display["values"],
            details=[display["coordinates"], display["model_run"], display["expires_at"]],
            apiRequests=requests, missing=True, localOnly=True)
    output["weather"].update(attribution=True, licence=True, accumulation=True,
        headers=["Valid time", "Temperature (°C)", "Wind (m/s)", "Wind from (°)",
                 "Accumulated precipitation (mm)", "Accumulation window (UTC)"])
    output["air_quality"].update(nativeScope=True, noEndorsement=True, headers=["Valid time", "PM2.5 (µg/m³)", "PM10 (µg/m³)"],
        **{key: expected["products"]["air_quality"]["display"][key] for key in ("attribution", "license", "license_url", "changes")})
    return output


class BindingTests(unittest.TestCase):
    def test_two_product_expected_binds_independent_queries_expiries_and_combined_display(self):
        expected, config = products_fixture()
        self.assertIs(smoke.validate_expected(expected, config), expected)
        for change in [lambda e, c: e["products"]["air_quality"].update(publication=e["products"]["weather"]["publication"]),
                lambda e, c: c["airQuality"]["core"]["query"].update(run=c["core"]["query"]["run"]),
                lambda e, c: c["airQuality"]["core"].update(cache=c["core"]["cache"]),
                lambda e, c: c["airQuality"]["core"].update(executable="/other/core"),
                lambda e, c: c["airQuality"]["core"]["query"].update(latitude=0),
                lambda e, c: c["airQuality"]["variables"].append("aqi"),
                lambda e, c: c["core"]["query"].update(includePrecipitation=False),
                lambda e, c: e.update(display_sha256="0" * 64),
                lambda e, c: e["products"]["air_quality"]["forecast"]["units"].update(pm10="AQI"),
                lambda e, c: e["products"]["air_quality"]["publication"].update(expires_unix_seconds=1),
                lambda e, c: e["products"]["weather"]["display"]["values"][0].pop()]:
            e, c = copy.deepcopy(expected), copy.deepcopy(config); change(e, c)
            with self.subTest(change=change), self.assertRaises(ValueError):
                smoke.validate_expected(e, c)

    def test_two_product_dom_waits_for_both_native_panels_and_ready_refresh_with_exact_units_source_and_windows(self):
        expected, _ = products_fixture()
        observed = products_dom(expected)
        self.assertTrue(smoke.check_products_dom(observed, expected, 1))
        self.assertFalse(smoke.check_products_dom(observed, expected, 2))
        for change in [lambda o: o.update(refreshReady=False), lambda o: o.pop("air_quality"),
                lambda o: o["weather"].update(accumulation=False), lambda o: o["air_quality"].update(apiRequests=0),
                lambda o: o["air_quality"].update(native=o["weather"]["native"]),
                lambda o: o["air_quality"].update(headers=["Valid time", "AQI", "PM10"]),
                lambda o: o["air_quality"].update(license="CC BY 4.0"),
                lambda o: o["air_quality"].update(changes="Made up"),
                lambda o: o["air_quality"].update(noEndorsement=False),
                lambda o: o["air_quality"].update(localOnly=False),
                lambda o: o["weather"]["values"][0].__setitem__(3, "0.0"),
                lambda o: o["air_quality"]["values"][0].__setitem__(0, "0")]:
            changed = copy.deepcopy(observed); change(changed)
            with self.subTest(change=change):
                self.assertFalse(smoke.check_products_dom(changed, expected, 1))

    def test_two_product_wait_hashes_actual_displays_and_report_cannot_claim_unrun_work(self):
        expected, _ = products_fixture()
        report = smoke.report_base({}, expected)
        self.assertEqual(report["schema"], 2)
        self.assertEqual(set(report["products"]), {"weather", "air_quality"})
        self.assertTrue(all(value is False for value in report["scope"].values()))
        self.assertEqual(report["products"]["air_quality"]["checks"], {})
        connection = Mock()
        with patch.object(smoke, "dom_products", return_value=products_dom(expected, 2)), \
             patch.object(smoke.time, "monotonic", side_effect=[0, 59, 59]):
            combined, products = smoke.wait_products_dom(Mock(), connection, expected, 2)
        self.assertEqual(combined, expected["display_sha256"])
        self.assertEqual(products, {name: p["display_sha256"] for name, p in expected["products"].items()})
        self.assertEqual(connection.settimeout.call_args_list[0].args, (1,))
        with patch.object(smoke.time, "monotonic", side_effect=[0, 60]), self.assertRaises(TimeoutError):
            smoke.wait_products_dom(Mock(), Mock(), expected, 1)

    def test_aq_endpoint_checks_its_own_publication_forecast_timeline_and_expiry(self):
        expected, _ = products_fixture()
        product = expected["products"]["air_quality"]
        publication = product["publication"]
        result = dict(schema="volparossa.air-quality.provider.v1", kind="forecast", forecast=product["forecast"],
            delivery={**{key: publication[key] for key in ("publisher_key", "name", "revision", "manifest_id", "sha256")},
                "mode": "core-cache", "upstream_origin_attested": False, "manifest_media_type_checked": False,
                "publication_expires_at": product["display"]["expires_at"]},
            freshness=dict(expires_at=product["display"]["expires_at"]), timeline=dict(valid_at=product["display"]["native"]))
        smoke.check_api(result, product, "air_quality")
        for change in [lambda r: r.update(schema="volparossa.weather.provider.v1"),
                lambda r: r["timeline"].update(valid_at=expected["products"]["weather"]["display"]["native"]),
                lambda r: r["freshness"].update(expires_at=expected["products"]["weather"]["display"]["expires_at"])]:
            changed = copy.deepcopy(result); change(changed)
            with self.assertRaises(ValueError): smoke.check_api(changed, product, "air_quality")
        connection, response = Mock(), Mock()
        response.status = 200
        response.getheader.side_effect = lambda name: {"Cache-Control": "no-store", "Content-Type": "application/json"}[name]
        raw = json.dumps(result).encode(); response.read.return_value = raw
        connection.getresponse.return_value = response
        with patch.object(smoke.http.client, "HTTPConnection", return_value=connection):
            self.assertEqual(smoke.api("http://127.0.0.1:1234", product, "air_quality"), digest(raw))
        self.assertEqual(connection.request.call_args.args, ("GET", "/api/volparossa/air-quality"))
        connection.close.assert_called_once()

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
    def test_core_exception_requires_verified_inner_boundary_and_distinct_user_namespace(self):
        binary = Path("/usr/bin/true")
        current = os.readlink("/proc/self/ns/user")
        with self.assertRaises(ValueError): smoke.readonly_core_hash(binary, "a" * 64, current)
        with self.assertRaises(ValueError): smoke.readonly_core_hash(binary, "a" * 64, None)
        inner = SimpleNamespace(inside=True, outer_userns=current)
        with patch.object(smoke, "boundary", side_effect=ValueError("closed")), \
             patch.object(smoke, "readonly_core_hash") as read, self.assertRaises(ValueError):
            smoke.verify_core_binary(binary, "a" * 64, inner)
        read.assert_not_called()
        outer = SimpleNamespace(inside=False, outer_userns="user:[123]")
        with self.assertRaises(ValueError): smoke.verify_core_binary(binary, "a" * 64, outer)

    def test_outer_core_verifier_preserves_strict_file_owner_and_hash_checks(self):
        args = SimpleNamespace(inside=False, outer_userns=None)
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            binary = Path(directory) / "core"
            binary.write_bytes(b"not executed"); binary.chmod(0o500)
            expected = digest(b"not executed")
            self.assertEqual(smoke.verify_core_binary(binary, expected, args), (expected, 12))
            with self.assertRaises(ValueError): smoke.verify_core_binary(binary, "f" * 64, args)
            binary.chmod(0o520)
            with self.assertRaises(ValueError): smoke.verify_core_binary(binary, expected, args)
            binary.chmod(0o400)
            with self.assertRaises(ValueError): smoke.verify_core_binary(binary, expected, args)
            with patch.object(smoke, "file_hash", side_effect=ValueError("owner rejected")), \
                 patch.object(smoke, "readonly_core_hash") as relaxed, self.assertRaises(ValueError):
                smoke.verify_core_binary(binary, expected, args)
            relaxed.assert_not_called()

    def test_readonly_core_descriptor_rejects_writable_mount_and_changed_inode(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            binary = Path(directory) / "core"
            binary.write_bytes(b"not executed"); binary.chmod(0o500)
            expected = digest(b"not executed")
            with patch.object(smoke.os, "readlink", return_value="user:[456]"), \
                 patch.object(smoke.Path, "read_text", return_value=f"{os.getuid()} {os.getuid()} 1\n"):
                # Namespace shape alone cannot authorize a writable executable.
                with patch.object(smoke.os, "fstatvfs", return_value=SimpleNamespace(f_flag=0)), self.assertRaises(ValueError):
                    smoke.readonly_core_hash(binary, expected, "user:[123]")
                original_stat = binary.stat()
                changed = copy.copy(original_stat)
                with patch.object(smoke.os, "fstatvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                     patch.object(smoke.os, "fstat", side_effect=[original_stat, changed]), \
                     patch.object(smoke.Path, "stat", return_value=SimpleNamespace(
                         **{name: getattr(original_stat, name) for name in ("st_dev", "st_uid", "st_gid", "st_mode",
                             "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}, st_ino=original_stat.st_ino + 1)), \
                     self.assertRaises(ValueError):
                    smoke.readonly_core_hash(binary, expected, "user:[123]")

    @unittest.skipUnless(Path("/usr/bin/bwrap").is_file() and os.getuid() != 0, "requires unprivileged Linux bwrap")
    def test_real_bwrap_root_owned_binary_keeps_strict_generic_guard_but_exact_readonly_core_verifies(self):
        binary = Path("/usr/bin/true")
        self.assertEqual(binary.stat().st_uid, 0)
        expected, size = smoke.verify_core_binary(binary, digest(binary.read_bytes()),
                                                  SimpleNamespace(inside=False, outer_userns=None))
        outer = os.readlink("/proc/self/ns/user")
        # The lower descriptor helper is exercised here, not the UID985/KVM
        # browser runner. No executable from this test is ever run as the core.
        code = """
import json, os, sys
from pathlib import Path
import smoke_core_browser as smoke
binary, expected, outer = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
def rejected(call):
    try: call()
    except (ValueError, OSError): return True
    return False
generic_rejected = rejected(lambda: smoke.file_hash(binary, 1024*1024))
result = smoke.readonly_core_hash(binary, expected, outer)
wrong_hash_rejected = rejected(lambda: smoke.readonly_core_hash(binary, 'f'*64, outer))
same_namespace_rejected = rejected(lambda: smoke.readonly_core_hash(binary, expected, os.readlink('/proc/self/ns/user')))
print(json.dumps(dict(generic_rejected=generic_rejected, exact_readonly_core_verified=result[0]==expected,
                     bytes=result[1], wrong_hash_rejected=wrong_hash_rejected,
                     same_namespace_rejected=same_namespace_rejected)))
"""
        helpers = Path(sys.modules["smoke_compute_model"].__file__).resolve().parent
        environment = {**smoke.shared.clean_environment(), "PYTHONPATH": os.pathsep.join((str(HERE), str(helpers)))}
        completed = subprocess.run(["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-user",
            "--unshare-net", "--unshare-pid", "--ro-bind", "/", "/", "--ro-bind", str(binary), str(binary),
            "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--", sys.executable, "-B", "-c", code,
            str(binary), expected, outer], env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, "isolated core-descriptor probe failed")
        self.assertEqual(json.loads(completed.stdout), dict(generic_rejected=True, exact_readonly_core_verified=True,
            bytes=size, wrong_hash_rejected=True, same_namespace_rejected=True))

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
        for version in (1, 2):
            with self.subTest(version=version):
                self.check_manifest(version)

    def check_manifest(self, version):
        with tempfile.TemporaryDirectory(prefix="drizzli-core-test-", dir=smoke.ROOT / "build") as directory:
            root = Path(directory)
            assets = {"index.html": digest(b"test asset")}
            retained = json.dumps({"source": {"built_tree_sha256": digest(smoke.canonical(assets))}}).encode()
            inputs = {
                "volparossa-weather/integrations/drizzli/smoke_core_browser.py": b"inert driver",
                "volparossa-weather/integrations/drizzli/prepare-core-browser.mjs": b"inert preparer",
                ("volparossa-weather/integrations/drizzli/browser-smoke.json" if version == 1
                    else "volparossa-weather/integrations/drizzli/air-quality-browser-smoke.json"): retained,
                "volparossa-weather/scripts/serve-provider.mjs": b"inert bridge",
                **{f"volparossa-weather/src/{name}.mjs": b"inert source" for name in ("provider-http", "provider-core", "core-cache")},
                "volparossa-weather/build/drizzli-volparossa/build/index.html": b"test asset",
                "runtime/node": b"not an executable runtime",
            }
            if version == 2:
                inputs.update({f"volparossa-weather/src/{name}.mjs": b"inert AQ source"
                               for name in ("air-quality", "air-quality-provider", "air-quality-core")})
            records = {}
            for name, raw in inputs.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw); path.chmod(0o400)
                records[name] = dict(bytes=len(raw), mode=0o400, sha256=digest(raw))
            manifest = smoke.canonical(dict(version=version, kind="volparossa-weather-client-inputs", files=records)) + b"\n"
            (root / "INPUTS.json").write_bytes(manifest); (root / "INPUTS.json").chmod(0o400)
            for path in [root, *root.rglob("*")]:
                if path.is_dir(): path.chmod(0o500)
            try:
                with patch.object(smoke, "ROOT", root / "volparossa-weather"), \
                     patch.object(smoke.shared, "NODE_SHA256", digest(inputs["runtime/node"])), \
                     patch.object(smoke.shared, "validate_stage", return_value={"test": "inert"}):
                    result = smoke.validate_bundle(root, digest(manifest), version)
                    self.assertEqual(result[3]["built_tree_sha256"], digest(smoke.canonical(assets)))
                    self.assertEqual(len(result[3]["bridge_modules"]), 4 if version == 1 else 7)
                    with self.assertRaises(ValueError): smoke.validate_bundle(root, digest(manifest), 3 - version)
                    with self.assertRaises(ValueError): smoke.validate_bundle(root, "f" * 64)
                    path = root / "runtime/node"; path.chmod(0o600); path.write_bytes(b"changed"); path.chmod(0o400)
                    with self.assertRaises(ValueError): smoke.validate_bundle(root, digest(manifest))
            finally:
                for path in [root, *root.rglob("*")]:
                    if path.is_dir(): path.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
