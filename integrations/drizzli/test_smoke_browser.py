#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inert fixture-boundary tests; no Firefox, namespace or network launch."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("drizzli_smoke", HERE / "smoke_browser.py")
SMOKE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SMOKE)


class Boundaries(unittest.TestCase):
    def test_refresh_waits_for_weather_and_air_quality_to_finish(self):
        client = Mock()
        client.script.side_effect = [False, False, True]
        self.assertFalse(SMOKE.refresh_idle(client))
        self.assertFalse(SMOKE.refresh_idle(client))
        self.assertTrue(SMOKE.refresh_idle(client))
        script = client.script.call_args.args[0]
        self.assertIn('VOLPAROSSA forecast', script)
        self.assertIn('VOLPAROSSA air quality', script)
        self.assertIn('disabled === false', script)
        client.script.return_value = 1
        client.script.side_effect = None
        self.assertFalse(SMOKE.refresh_idle(client))

    def test_browser_root_is_explicit_canonical_and_default_is_unchanged(self):
        default = Path('/unchanged/sibling/volparossa-browser')
        self.assertEqual(SMOKE.browser_root_argument([], default), default)
        self.assertEqual(SMOKE.browser_root_argument(['--precipitation', '--fixture-only'], default), default)
        with tempfile.TemporaryDirectory(prefix="drizzli-root-test-", dir=SMOKE.ROOT / "build") as directory:
            root = Path(directory)
            (root / 'child').mkdir()
            (root / 'alias').symlink_to(root / 'child', target_is_directory=True)
            with self.assertRaises(OSError):
                SMOKE.browser_root_argument(['--browser-root', str(root)], default)
            (root / 'scripts').mkdir()
            for name in ('smoke_compute_model.py', 'smoke_privacy.py', 'stage_firefox.py'):
                (root / 'scripts' / name).write_text('# inert helper path fixture\n')
            self.assertEqual(SMOKE.browser_root_argument(['--browser-root', str(root)], default), root)
            for value in ['relative/path', str(root) + '/', str(root) + '/./child',
                          str(root) + '/child/..', str(root / 'alias'), str(root / 'absent')]:
                with self.subTest(value=value), self.assertRaises((OSError, ValueError)):
                    SMOKE.browser_root_argument(['--browser-root', value], default)

    def test_precipitation_flag_is_explicit_and_fixed_for_every_fixture_launch(self):
        baseline = SMOKE.fixture_arguments(Path('/node'), Path('/stage'), Path('/work'))
        self.assertNotIn('--precipitation', baseline)
        self.assertEqual(SMOKE.fixture_arguments(Path('/node'), Path('/stage'), Path('/work'), True),
                         [*baseline, '--precipitation'])
        self.assertEqual(SMOKE.fixture_arguments(Path('/node'), Path('/stage'), Path('/work'), False, True),
                         [*baseline, '--air-quality'])
        self.assertEqual(SMOKE.fixture_arguments(Path('/node'), Path('/stage'), Path('/work'), True, True),
                         [*baseline, '--precipitation', '--air-quality'])

    def test_environment_excludes_runtime_injection_and_host_secrets(self):
        with patch.dict(os.environ, {"LD_PRELOAD": "private", "NODE_OPTIONS": "--import=private", "TOKEN": "private"}):
            self.assertEqual(set(SMOKE.clean_environment()), {"PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"})

    def test_process_exit_race_is_reaped_and_does_not_abort_cleanup(self):
        process = Mock(pid=123)
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        with patch.object(SMOKE.os, "killpg", side_effect=ProcessLookupError):
            self.assertTrue(SMOKE.stop(process))
        process.wait.assert_called_once_with(timeout=5)

    def test_failed_termination_is_reported_not_raised(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("test", 5)
        with patch.object(SMOKE.os, "killpg"):
            self.assertFalse(SMOKE.stop(process))

    def test_cleanup_refuses_replaced_work_identity_and_continues_after_bad_child(self):
        with tempfile.TemporaryDirectory(prefix="drizzli-cleanup-test-", dir=SMOKE.ROOT / "build") as directory:
            work = Path(directory)
            (work / "profile").mkdir(mode=0o700)
            identity = SMOKE.work_identity(work)
            self.assertFalse(SMOKE.remove_private(work, (identity[0], identity[1] + 1)))
            self.assertTrue((work / "profile").is_dir())
            # Do not follow or remove the bad child; still clean the separate owned profile.
            (work / "cache").symlink_to(work / "outside")
            self.assertFalse(SMOKE.remove_private(work, identity))
            self.assertFalse((work / "profile").exists())
            self.assertTrue((work / "cache").is_symlink())


class PrecipitationDisplay(unittest.TestCase):
    times = ['2026-09-30T03:00:00.000Z', '2026-09-30T09:00:00.000Z', '2026-10-01T00:00:00.000Z']

    def observed(self, missing=False, requests=1):
        return dict(native=self.times.copy(), values=SMOKE.precipitation_rows(self.times, missing),
            headings=['Valid time', 'Temperature (°C)', 'Wind (m/s)', 'Wind from (°)',
                      'Accumulated precipitation (mm)', 'Accumulation window (UTC)'],
            explicitWindows=True, noRate=True, airQualitySeparate=True, notLoading=True,
            localOnly=True, completedRequests=requests)

    def test_expected_amounts_and_native_overlapping_windows_are_not_inferred_hours(self):
        rows = SMOKE.precipitation_rows(self.times)
        self.assertEqual([row[3] for row in rows], ['Not available', '0', '0.01'])
        self.assertEqual([row[4] for row in rows], [
            '2026-09-30T00:00:00.000Z → 2026-09-30T03:00:00.000Z',
            '2026-09-30T00:00:00.000Z → 2026-09-30T09:00:00.000Z',
            '2026-09-30T06:00:00.000Z → 2026-10-01T00:00:00.000Z'])
        missing = SMOKE.precipitation_rows(self.times, missing=True)
        self.assertEqual(missing[0][:4], ['Not available'] * 4)
        self.assertEqual(missing[0][4], rows[0][4])
        with self.assertRaises(ValueError):
            SMOKE.precipitation_rows([self.times[0], '2026-09-30T04:00:00.000Z', self.times[2]])

    def test_actual_dom_match_requires_five_cells_native_times_units_and_completed_refresh(self):
        observed = self.observed()
        self.assertTrue(SMOKE.precipitation_dom_matches(observed, self.times, 1))
        self.assertFalse(SMOKE.precipitation_dom_matches(observed, self.times, 2))
        observed['completedRequests'] = 2
        self.assertTrue(SMOKE.precipitation_dom_matches(observed, self.times, 2))
        for mutate in [
            lambda v: v['values'][0].__setitem__(3, '0'),
            lambda v: v['values'][1].__setitem__(3, 'Not available'),
            lambda v: v['values'][2].__setitem__(3, '0.0'),
            lambda v: v['values'][2].__setitem__(4, self.times[1] + ' → ' + self.times[2]),
            lambda v: v['values'][0].pop(),
            lambda v: v['native'].__setitem__(1, self.times[0]),
            lambda v: v['headings'].__setitem__(4, 'Precipitation (mm/h)'),
        ]:
            changed = copy.deepcopy(observed); mutate(changed)
            self.assertFalse(SMOKE.precipitation_dom_matches(changed, self.times, 2))
        for field in ['explicitWindows', 'noRate', 'airQualitySeparate', 'notLoading', 'localOnly']:
            self.assertFalse(SMOKE.precipitation_dom_matches({**observed, field: False}, self.times, 2))
        self.assertFalse(SMOKE.precipitation_dom_matches({**observed, 'completedRequests': True}, self.times, 1))
        self.assertTrue(SMOKE.precipitation_dom_matches(self.observed(missing=True, requests=3), self.times, 3, missing=True))

    def test_wait_hashes_actual_matched_dom_and_not_the_expectation(self):
        observed = self.observed(requests=2)
        with patch.object(SMOKE, 'precipitation_dom', return_value=observed) as dom:
            actual = SMOKE.wait_precipitation(Mock(), self.times, 2)
        expected = SMOKE.hashlib.sha256(json.dumps({'native': observed['native'], 'values': observed['values']},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, expected)
        dom.assert_called_once()


class AirQualityDisplay(unittest.TestCase):
    times = ['2026-09-29T21:00:00.000Z', '2026-09-30T00:00:00.000Z', '2026-09-30T06:00:00.000Z']

    def observed(self):
        return dict(native=self.times.copy(), values=[['Not available', '11.5959'], ['0', 'Not available'], ['5.53071', '0']],
            headings=['Valid time', 'PM2.5 (µg/m³)', 'PM10 (µg/m³)'], noObservation=True, noAqi=True,
            source=True, license=True, notLoading=True, localOnly=True, completedRequests=2)

    def test_air_quality_requires_native_times_exact_concentrations_and_completed_refresh(self):
        observed = self.observed()
        self.assertTrue(SMOKE.air_quality_dom_matches(observed, self.times, 2))
        self.assertFalse(SMOKE.air_quality_dom_matches(observed, self.times, 3))
        for change in [lambda v: v['values'][0].__setitem__(0, '0'),
                       lambda v: v['values'][1].__setitem__(0, 'Not available'),
                       lambda v: v['values'][2].__setitem__(0, '5.5'),
                       lambda v: v['headings'].__setitem__(1, 'AQI'),
                       lambda v: v['native'].__setitem__(0, PrecipitationDisplay.times[0])]:
            changed = copy.deepcopy(observed); change(changed)
            self.assertFalse(SMOKE.air_quality_dom_matches(changed, self.times, 2))
        for field in ['noObservation', 'noAqi', 'source', 'license', 'notLoading', 'localOnly']:
            self.assertFalse(SMOKE.air_quality_dom_matches({**observed, field: False}, self.times, 2))
        self.assertFalse(SMOKE.air_quality_dom_matches({**observed, 'completedRequests': True}, self.times, 1))

    def test_hash_binds_actual_observed_air_quality_dom(self):
        observed = self.observed()
        with patch.object(SMOKE, 'air_quality_dom', return_value=observed) as dom:
            actual = SMOKE.wait_air_quality(Mock(), self.times, 2)
        expected = SMOKE.hashlib.sha256(json.dumps({'native': observed['native'], 'values': observed['values']},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, expected)
        dom.assert_called_once()


@unittest.skipUnless(os.environ.get('VOLPAROSSA_TEST_NODE'), 'explicit pinned Node needed for inert fixture test')
class FixtureData(unittest.TestCase):
    def test_inert_module_import_and_projection_preserve_baseline_and_precipitation(self):
        node = Path(os.environ['VOLPAROSSA_TEST_NODE'])
        self.assertEqual(SMOKE.digest(node), SMOKE.NODE_SHA256)
        script = '''
          import assert from 'node:assert/strict';
          import {fixtureQuery,fixtureForecast} from './integrations/drizzli/browser-fixture.mjs';
          import {toProviderForecast} from './src/provider.mjs';
          const run='2026-09-30T00:00:00.000Z', now='2026-09-30T09:00:00.000Z';
          const variables=['temperature_2m','wind_speed_10m','wind_direction_10m','precipitation','air_quality'];
          const baseline=fixtureForecast(fixtureQuery(run),now);
          assert.equal(Object.hasOwn(baseline.units,'precipitation'),false);
          assert.equal(Object.hasOwn(fixtureQuery(run),'includePrecipitation'),false);
          const query=fixtureQuery(run,true);
          assert.deepEqual(query.steps,[3,9,24]);
          assert.equal(query.includePrecipitation,true);
          for(const mode of ['valid','missing','stale','short-lived']) {
            const forecast=fixtureForecast(query,now,mode);
            const projection=toProviderForecast(forecast,{variables,now});
            const rain=projection.series[3];
            assert.deepEqual(rain.values,[null,0,0.01]);
            assert.deepEqual(rain.value_status,['missing','available','available']);
            assert.deepEqual(forecast.samples.map(s=>s.precipitation.start_lead_hours),[0,0,6]);
            assert.deepEqual(forecast.samples.map(s=>s.precipitation.end_lead_hours),[3,9,24]);
            assert.equal(rain.unit,'mm'); assert.equal(rain.statistic,'accumulation');
            assert.equal(projection.series[4].reason,'unsupported_variable');
            assert.equal(forecast.samples[0].temperature_2m,mode==='missing'?null:10);
          }
          assert.throws(()=>fixtureForecast(query,now,'invented'));
          const {fixtureAirQualityQuery}=await import('./integrations/drizzli/browser-fixture.mjs');
          const {aqForecast}=await import('./tests/air-quality-fixtures.mjs');
          const aqQuery=fixtureAirQualityQuery(query), aq=aqForecast(aqQuery,now);
          assert.equal(aqQuery.run,'2026-09-29T18:00:00.000Z');
          assert.deepEqual(aqQuery.steps,[3,6,12]);
          assert.equal(aq.area.latitude,query.latitude); assert.equal(aq.area.longitude,query.longitude);
          assert.deepEqual(aq.samples.map(s=>s.pm2_5),[null,0,5.53071]);
          assert.deepEqual(aq.samples.map(s=>s.pm10),[11.5959,null,0]);
          assert.notDeepEqual(aq.samples.map(s=>s.valid_at),baseline.samples.map(s=>s.valid_at));
          console.log(JSON.stringify({inert:true,baseline:true,precipitation:true}));
        '''
        result = subprocess.run([str(node), '--input-type=module', '-'], input=script,
            cwd=SMOKE.ROOT, text=True, capture_output=True, timeout=10, env=SMOKE.clean_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(inert=True, baseline=True, precipitation=True))
        self.assertEqual(result.stderr, '')


if __name__ == "__main__":
    unittest.main()
