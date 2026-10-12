#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact v3 table verifier against actual Flutter and captured synthetic HTTP bodies.

Uses the existing headless sandbox, runtime/source validation, memory/deadline
gates and cleanup. Never calls or weakens the production core driver's main,
guest gates, cold-receipt checks or origin acquisition. No cold/core proof.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ui = load("synthetic_table_browser_ui", HERE / "smoke_browser.py")
tables = load("unchanged_core_table_verifier", HERE / "smoke_core_browser.py")


def captured(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        ui.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                   and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= 131072)
        raw = stream.read(131073)
        after = os.fstat(stream.fileno())
        ui.require(len(raw) == before.st_size and before.st_size == after.st_size
                   and before.st_mtime_ns == after.st_mtime_ns and before.st_ctime_ns == after.st_ctime_ns)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def expected_display(bodies):
    # Expectations come exclusively from the exact products passed to the HTTP
    # response serializer. Do not regenerate acquisition/expiry timestamps or
    # manufacture cold receipts, manifests or a core expected.json.
    products = {}
    for name, body in bodies.items():
        forecast, source = body["forecast"], body["forecast"]["source"]
        quality = name == "air_quality"
        values = []
        for sample in forecast["samples"]:
            numbers = [sample["pm2_5"], sample["pm10"]] if quality else [sample["temperature_2m"],
                sample["wind_10m"]["speed"], sample["wind_10m"]["direction_from"], sample["precipitation"]["amount"]]
            row = ["Not available" if number is None else str(number) for number in numbers]
            if not quality:
                row.append(sample["precipitation"]["start_at"] + " → " + sample["precipitation"]["end_at"])
            values.append(row)
        area = forecast["area"]
        display = dict(coordinates=f"Public community area: {area['latitude']}, {area['longitude']}",
            native=[sample["valid_at"] for sample in forecast["samples"]], values=values,
            model_run=source["model"] + " · " + source["model_run_at"], acquired_at=source["acquired_at"],
            expires_at=body["freshness"]["expires_at"], **{key: source[key] for key in tables.SOURCE_FIELDS})
        products[name] = dict(display=display, display_sha256=tables.digest(display))
    return dict(products=products, display_sha256=tables.digest({name: item["display"] for name, item in products.items()}))


def table_diagnostic(observed, expected):
    """Closed counts/positions/booleans only; never copy application text/data."""
    def count(value, maximum):
        return value if type(value) is int and 0 <= value <= maximum else None
    result = dict(shape_valid=False, local_only=False, wasm_loaded=False, canvas=False, root_route=False,
                  browser_weather=None, browser_air_quality=None, section_count=None, sections=[])
    if type(observed) is not dict:
        return result
    result.update(shape_valid=set(observed) == {"sections", "localOnly", "weatherRequests", "airQualityRequests",
        "wasmLoaded", "canvas", "location"}, local_only=observed.get("localOnly") is True,
        wasm_loaded=observed.get("wasmLoaded") is True, canvas=observed.get("canvas") is True,
        root_route=observed.get("location") == "/", browser_weather=count(observed.get("weatherRequests"), 4),
        browser_air_quality=count(observed.get("airQualityRequests"), 4))
    sections = observed.get("sections")
    if type(sections) is not list:
        return result
    result["section_count"] = count(len(sections), 4)
    for section in sections[:2]:
        if type(section) is not dict:
            result["sections"].append({"product": "invalid"})
            continue
        name = section.get("product")
        if type(name) is not str or name not in tables.HEADERS:
            result["sections"].append({"product": "unknown"})
            continue
        display = expected["products"][name]["display"]
        labels, native_tables = section.get("labels"), section.get("tables")
        item = dict(product=name, labels_valid=False, label_count=None, metadata_matches={}, expired_marker=False,
                    table_count=None, headers_match=False, row_count=None, cells_per_row=[], first_row_mismatch=None)
        result["sections"].append(item)
        if type(labels) is list and len(labels) <= 128 and all(type(label) is str and len(label) <= 8192 for label in labels):
            model, run = display["model_run"].split(" · ")
            metadata = dict(coordinates=display["coordinates"], model_run=f"Model {model}; run {run}",
                acquired_at="Acquired " + display["acquired_at"], expires_at="Expires " + display["expires_at"],
                attribution=display["attribution"], license=display["license"] + ": " + display["license_url"],
                changes=display["changes"], delivery_scope=
                "Core-cache delivery; schema and freshness checked. Origin authenticity is not attested.",
                unsupported=("AQI, pollen and health advice: not available" if name == "air_quality" else
                "Current observations, daily totals/extrema, UV, humidity and hourly interpolation: not available"))
            item.update(labels_valid=True, label_count=len(labels),
                metadata_matches={key: text in labels for key, text in metadata.items()},
                expired_marker=any("Expired —" in label or "unavailable or expired" in label for label in labels))
        if type(native_tables) is not list:
            continue
        item["table_count"] = count(len(native_tables), 4)
        if len(native_tables) != 1 or type(native_tables[0]) is not dict:
            continue
        table = native_tables[0]
        item["headers_match"] = table.get("headers") == tables.HEADERS[name]
        rows = table.get("rows")
        if type(rows) is not list:
            continue
        item["row_count"] = count(len(rows), 16)
        item["cells_per_row"] = [count(len(row), 6) if type(row) is list else None for row in rows[:16]]
        for index, (row, when, values) in enumerate(zip(rows[:16], display["native"], display["values"])):
            mismatch = None
            if type(row) is not list or len(row) != len(tables.HEADERS[name]):
                mismatch = dict(row=index, column=None, kind="cell_count")
            elif row[0] != when:
                mismatch = dict(row=index, column=0, kind="native_time")
            else:
                for column, (actual, target) in enumerate(zip(row[1:], values), 1):
                    kind = "missing" if target == "Not available" else "window" if name == "weather" and column == 5 else "number"
                    equal = actual == target if kind != "number" else tables.number_equal(actual, target)
                    if not equal:
                        mismatch = dict(row=index, column=column, kind=kind)
                        break
            if mismatch is not None:
                item["first_row_mismatch"] = mismatch
                break
    return result


def wait_tables(client, expected, ordinal, diagnostic, *, clock=time.monotonic, pause=time.sleep):
    # Same readiness policy as production wait_products: give rendering a
    # bounded opportunity to catch up, without accepting any partial/table
    # mismatch. Polling is observation only: it launches no HTTP requests.
    deadline = clock() + 60
    diagnostic["attempts"] = 0
    try:
        while clock() < deadline:
            client.socket.settimeout(min(15, max(0.1, deadline - clock())))
            observed = tables.snapshot(client)
            diagnostic["attempts"] += 1
            diagnostic["last"] = table_diagnostic(observed, expected)
            try:
                verified = tables.observed_products(observed, expected, ordinal)
            except (ValueError, KeyError, TypeError):
                verified = None
            ready = ui.button_ready(ui.button_state(client, "Refresh forecasts"))
            diagnostic["refresh_ready"] = ready
            if verified is not None and ready:
                return verified
            pause(min(0.1, max(0, deadline - clock())))
        raise TimeoutError("synthetic_native_tables_deadline")
    finally:
        client.socket.settimeout(15)


def run_tables(client, fixture, ready, support, report, work):
    report["kind"] = "overmorrow-synthetic-native-table-contract"
    report["scope"].update(ordered_table_contract=False, joined_delivery_proven=False,
                           cold_transfer_proven=False, origin_acquisition_proven=False)
    report["table_phases"] = []
    client.command("WebDriver:SetWindowRect", {"width": 2400, "height": 2600})
    report["phase"] = "navigation"
    client.command("WebDriver:Navigate", {"url": ready["origin"] + "/"})
    support.wait_for(lambda: ui.activate_semantics(client), timeout=35)
    for ordinal, phase in ((1, "initial_tables"), (2, "refreshed_tables")):
        report["phase"] = phase
        diagnostic = dict(subphase="activate_pointer" if ordinal == 2 else "wait_requests")
        report["table_diagnostic"] = diagnostic
        if ordinal == 2:
            ui.pointer_activate(client, ui.button_state(client, "Refresh forecasts"))
        diagnostic["subphase"] = "wait_requests"
        status = None
        def complete():
            nonlocal status
            status = support.fixture_command(fixture, "status")
            ui.require(set(status) == {"counts", "hashes"} and set(status["counts"]) == {"weather", "air_quality"}
                       and all(type(n) is int and 0 <= n <= ordinal for n in status["counts"].values()))
            observed = ui.snapshot(client)
            diagnostic["provider_counts"] = dict(status["counts"])
            diagnostic["browser_counts"] = {key: observed[field] if type(observed[field]) is int
                and 0 <= observed[field] <= 4 else None for key, field in
                (("weather", "weatherRequests"), ("air_quality", "airQualityRequests"))}
            return (all(n == ordinal for n in status["counts"].values())
                and observed["weatherRequests"] == observed["airQualityRequests"] == ordinal
                and ui.button_ready(ui.button_state(client, "Refresh forecasts")))
        support.wait_for(complete, timeout=30)
        diagnostic["subphase"] = "read_captured_bodies"
        bodies, body_hashes = {}, {}
        for name in ("weather", "air_quality"):
            bodies[name], body_hashes[name] = captured(work / "tmp" / f"served-{name}-{ordinal}.json")
            ui.require(body_hashes[name] == status["hashes"][name])
        diagnostic["subphase"] = "construct_expected"
        expected = expected_display(bodies)
        # Exact unchanged extraction + ordered-cell/metadata verifier used by
        # v3. A runtime mismatch is a failure, never a flat-label substitute.
        diagnostic["subphase"] = "wait_exact_tables"
        verified = wait_tables(client, expected, ordinal, diagnostic)
        diagnostic["subphase"] = "complete"
        report["table_phases"].append(dict(phase=phase, response_sha256=body_hashes,
            display_sha256=tables.digest(verified), row_counts={name: len(body["forecast"]["samples"])
                for name, body in bodies.items()}, browser_requests_each=ordinal,
            provider_requests_each=ordinal, exact_ordered_rows_and_metadata=True))
        ui.require(support.fixture_command(fixture, "status") == status)
    report["scope"].update(actual_overmorrow_ui=True, ordered_table_contract=True)
    report["checks"].update(exact_current_v3_extractor=True, exact_current_v3_observed_products=True,
        same_origin_loaded_resources=True, actual_pointer_refresh=True, exact_captured_response_bodies=True,
        ordered_four_weather_five_air_quality_rows=True, native_missing_calm_zero_and_precipitation_windows=True,
        weather_requests=2, air_quality_requests=2)


def main():
    # The existing harness parser validates every path and re-enters this same
    # wrapper in its disposable user/network namespace. No new sandbox variant.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path, required=True)
    args, _ = parser.parse_known_args()
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    source = dict(table_wrapper_sha256=digest(Path(__file__)), table_fixture_sha256=digest(HERE / "table-fixture.mjs"),
        exact_v3_verifier_sha256=digest(HERE / "smoke_core_browser.py"),
        extra_synthetic_modules={"tests/precipitation-fixtures.mjs": digest(HERE.parent.parent / "tests/precipitation-fixtures.mjs")})
    ui.main(entry_path=Path(__file__), fixture_entry=HERE / "table-fixture.mjs", source_extra=source,
            check_ui=lambda client, fixture, ready, support, report:
                run_tables(client, fixture, ready, support, report, args.output.resolve()))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("synthetic table-contract smoke failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
