// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEqualWeightTemperature, verifyTemperature } from '../src/forecast-verification.mjs';
import { MAX_BYTES } from '../src/forecast.mjs';
import { forecast, QUERY } from './fixtures.mjs';

function inputs() {
  // Explicit synthetic example. Forecasts were captured at 21:00 UTC; all
  // three observations are on the following day at their native valid times.
  const steps = [12, 18, 24];
  const ifs = forecast({ ...QUERY, steps }), aifs = forecast({ ...QUERY, steps, model: 'aifs-single' });
  const observations = { schema: 'volparossa.weather.observations.v1', source: 'Synthetic test',
    license: 'CC0-1.0', station: { id: 'synthetic', latitude: QUERY.latitude, longitude: QUERY.longitude },
    sharing: 'public', purpose: 'held-out-evaluation', variable: 'temperature_2m', unit: 'degC', statistic: 'instant',
    samples: ifs.samples.map((sample, i) => ({
      observed_at: sample.valid_at, temperature_2m: [8, null, 0][i], quality: 'accepted' })) };
  ifs.samples[2].temperature_2m = -4;
  aifs.samples[0].temperature_2m = 7;
  aifs.samples[2].temperature_2m = 1;
  return [ifs, aifs, observations];
}

test('paired synthetic example scores the same two temperatures and keeps a missing observation visible', () => {
  const data = inputs();
  const result = verifyTemperature(...data);
  assert.deepEqual(result.coverage, { candidate_times: 3, paired: 2, excluded: 1 });
  assert.deepEqual(result.models.ifs, { mean_error_degC: -1, mean_absolute_error_degC: 3 });
  assert.deepEqual(result.models['aifs-single'], { mean_error_degC: 0, mean_absolute_error_degC: 1 });
  assert.deepEqual(result.cases[1].excluded, ['missing_observation']);
  assert.equal(result.cases[2].observed_degC, 0);
  assert.ok(Math.abs(result.cases[0].grid.distance_km - 6.48) < 0.03);
  data[2].samples.reverse();
  assert.deepEqual(verifyTemperature(...data), result);
});

test('forecast availability, colocation and observation quality gate both models together', () => {
  const [ifs, aifs, obs] = inputs();
  ifs.samples[0].temperature_2m = null;
  obs.samples[1].temperature_2m = 4;
  obs.samples[1].quality = 'rejected';
  aifs.samples[2].grid.longitude += 0.25;
  const result = verifyTemperature(ifs, aifs, obs);
  assert.deepEqual(result.cases.map(row => row.excluded), [
    ['ifs_missing_forecast'], ['rejected_observation'], ['grid_mismatch']]);
  for (const metrics of Object.values(result.models)) {
    assert.deepEqual(metrics, { mean_error_degC: null, mean_absolute_error_degC: null });
  }
});

test('reported grid distance cannot place distant grids at the station, including near the dateline', () => {
  const [ifs, aifs, obs] = inputs();
  obs.station.latitude = 0;
  obs.station.longitude = 179.98;
  for (const model of [ifs, aifs]) {
    Object.assign(model.area, { latitude: 0, longitude: 179.98 });
    for (const sample of model.samples) Object.assign(sample.grid, { latitude: 0, longitude: 0, distance_km: 0 });
    model.samples[0].grid.longitude = -180;
  }
  const { cases, coverage } = verifyTemperature(ifs, aifs, obs);
  assert.equal(coverage.paired, 1);
  assert.ok(Math.abs(cases[0].grid.distance_km - 2.224) < 0.01);
  assert.deepEqual(cases[2].excluded, ['grid_outside_station_area']);
});

test('the candidate denominator includes every supplied time without nearest-time matching or hindsight', () => {
  const [ifs, aifs, obs] = inputs();
  aifs.samples.shift();
  obs.samples.shift();
  obs.samples[0].observed_at = '2026-10-01T06:00:01.000Z';
  ifs.source.acquired_at = ifs.samples[2].valid_at;
  ifs.freshness.expires_at = '2026-10-01T12:10:00.000Z';
  const result = verifyTemperature(ifs, aifs, obs);
  assert.deepEqual(result.coverage, { candidate_times: 4, paired: 0, excluded: 4 });
  assert.deepEqual(result.cases[0].excluded,
    ['missing_observation', 'ifs_not_acquired_in_advance', 'aifs-single_missing_forecast']);
  assert.ok(result.cases[2].excluded.includes('ifs_missing_forecast'));
  assert.deepEqual(result.cases[3].excluded, ['ifs_not_acquired_in_advance']);
});

test('rejects unlike runs, non-native leads, another station, ambiguous observations and unsupported units', () => {
  for (const [code, mutate] of [
    ['VERIFICATION_MODEL_INVALID', ([ifs]) => { ifs.source.provider = 'other'; }],
    ['VERIFICATION_STATION_MISMATCH', ([, aifs]) => { aifs.area.sharing = 'private'; }],
    ['VERIFICATION_STATION_MISMATCH', ([,, obs]) => { obs.station.longitude += 1; }],
    ['DUPLICATE_OBSERVATION', ([,, obs]) => { obs.samples.push(obs.samples[0]); }],
    ['OBSERVATION_CONTRACT_INVALID', ([,, obs]) => { obs.unit = 'K'; }],
    ['OBSERVATION_CONTRACT_INVALID', ([,, obs]) => { obs.sharing = 'private'; }],
    ['OBSERVATION_CONTRACT_INVALID', ([,, obs]) => { obs.purpose = 'training'; }],
    ['OBSERVATION_CONTRACT_INVALID', ([,, obs]) => { obs.statistic = 'daily-mean'; }],
    ['OBSERVATION_CONTRACT_INVALID', ([,, obs]) => { obs.variable = 'temperature_10m'; }],
    ['OBSERVATION_FORMAT_INVALID', ([,, obs]) => { obs.samples[0].unit = 'K'; }],
    ['OBSERVATION_QUALITY_INVALID', ([,, obs]) => { obs.samples[0].quality = 'unknown'; }],
    ['VERIFICATION_RUN_MISMATCH', data => {
      data[1] = forecast({ ...QUERY, run: '2026-09-30T06:00:00.000Z', model: 'aifs-single' });
    }],
    ['ECMWF_STEP_UNSUPPORTED', ([, aifs]) => {
      aifs.samples[0].lead_hours = 9;
      aifs.samples[0].valid_at = '2026-09-30T21:00:00.000Z';
    }],
  ]) {
    const data = inputs();
    mutate(data);
    assert.throws(() => verifyTemperature(...data), { code });
  }
});

test('local CLI reads the three supplied files, returning only closed errors for invalid input', async t => {
  const root = await mkdtemp(join(tmpdir(), 'weather-verification-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = ['ifs', 'aifs', 'observations'].map(name => join(root, name + '.json'));
  const data = inputs();
  await Promise.all(paths.map((path, i) => writeFile(path, JSON.stringify(data[i]))));
  const command = fileURLToPath(new URL('../scripts/verify-forecast.mjs', import.meta.url));
  const run = files => spawnSync(process.execPath, [command, ...files], { encoding: 'utf8', timeout: 5000 });
  const ok = run(paths);
  assert.equal(ok.status, 0, ok.stderr);
  assert.deepEqual(JSON.parse(ok.stdout), verifyTemperature(...data));
  const comparison = run(['--compare-blend', ...paths]);
  assert.equal(comparison.status, 0, comparison.stderr);
  const { verification, comparison: metrics } = JSON.parse(comparison.stdout);
  assert.deepEqual(verification, JSON.parse(ok.stdout));
  assert.deepEqual(metrics, { method: 'equal-weight-ifs-aifs-single', unit: 'degC', stations: 1,
    paired_station_times: 2, excluded_station_times: 1,
    ifs: verification.models.ifs, 'aifs-single': verification.models['aifs-single'],
    blend: { mean_error_degC: -0.5, mean_absolute_error_degC: 1 } });
  const leak = join(root, 'private-name');
  await symlink(paths[0], leak);
  for (const [files, code] of [[[leak, ...paths.slice(1)], 'VERIFICATION_INPUT_FAILED'],
    [[], 'EXPECTED_IFS_AIFS_OBSERVATIONS_FILES']]) {
    const failed = run(files);
    assert.equal(failed.status, 1);
    assert.deepEqual(JSON.parse(failed.stderr), { error: code });
    assert.equal(failed.stdout, '');
  }
  for (const [bytes, code] of [[Buffer.alloc(MAX_BYTES + 1), 'VERIFICATION_FILE_INVALID'],
    [Buffer.from([255]), 'JSON_INVALID']]) {
    await writeFile(paths[2], bytes);
    const failed = run(paths);
    assert.equal(failed.status, 1);
    assert.deepEqual(JSON.parse(failed.stderr), { error: code });
  }
});

test('equal weighting uses matched station-hours, including multiple stations on the same cell', async () => {
  const source = new URL('../third_party/ecmwf-dwd-archive-report.json', import.meta.url);
  const report = JSON.parse(await readFile(source, 'utf8'));
  const result = compareEqualWeightTemperature(report.stations);
  assert.equal(result.stations, 4);
  assert.equal(result.paired_station_times, 4);
  assert.equal(result.excluded_station_times, 0);
  assert.ok(Math.abs(result.blend.mean_absolute_error_degC - 0.37578125) < 1e-10);
  const empty = compareEqualWeightTemperature([{ cases: [{ excluded: ['missing_observation'] }] }]);
  assert.equal(empty.paired_station_times, 0);
  assert.equal(empty.excluded_station_times, 1);
  assert.deepEqual(empty.blend, { mean_error_degC: null, mean_absolute_error_degC: null });
});
