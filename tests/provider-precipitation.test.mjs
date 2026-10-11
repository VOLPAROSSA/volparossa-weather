// SPDX-License-Identifier: GPL-3.0-only
// Synthetic projection and actual inert CLI; no live acquisition/overlay proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { toProviderForecast } from '../src/provider.mjs';
import { precipitationForecast } from './precipitation-fixture.mjs';
import { forecast, QUERY, NOW } from './fixtures.mjs';

test('provider retains native accumulation windows independently of the selected time spacing', () => {
  const source = precipitationForecast({ ...QUERY, steps: [3, 9, 24], includeWind: true });
  source.samples[2].precipitation.start_lead_hours = 6;
  source.samples[2].precipitation.start_at = '2026-09-30T18:00:00.000Z';
  const projected = toProviderForecast(source, { now: NOW,
    variables: ['temperature_2m', 'wind_speed_10m', 'precipitation', 'air_quality'] });
  const rain = projected.series[2];
  assert.equal(rain.availability, 'supported');
  assert.equal(rain.unit, 'mm');
  assert.equal(rain.statistic, 'accumulation');
  assert.deepEqual(rain.values, [1, 2, 3]);
  assert.deepEqual(rain.value_status, ['available', 'available', 'available']);
  assert.deepEqual(rain.accumulation_windows, source.samples.map(sample => ({
    start_at: sample.precipitation.start_at, end_at: sample.precipitation.end_at })));
  assert.equal(rain.accumulation_windows[2].start_at, '2026-09-30T18:00:00.000Z');
  assert.deepEqual(projected.timeline.lead_hours, [3, 9, 24]);
  assert.equal(projected.capabilities.interpolation, false);
  assert.equal(projected.series[3].reason, 'unsupported_variable');
  assert.equal(projected.series[3].values, null);
  assert.deepEqual(projected.forecast, source);
  rain.accumulation_windows[0].start_at = 'changed';
  assert.equal(source.samples[0].precipitation.start_at, QUERY.run);
});

test('missing precipitation and genuine dry accumulation stay distinct without rate derivation', () => {
  const source = precipitationForecast({ ...QUERY, steps: [3, 9] });
  source.samples[0].precipitation.amount = source.samples[0].precipitation.source_value = null;
  source.samples[1].precipitation.amount = source.samples[1].precipitation.source_value = 0;
  const series = toProviderForecast(source, { now: NOW, variables: ['precipitation'] }).series[0];
  assert.deepEqual(series.values, [null, 0]);
  assert.deepEqual(series.value_status, ['missing', 'available']);
  assert.equal(series.statistic, 'accumulation');
  assert.equal(Object.hasOwn(series, 'rate'), false);
  assert.equal(series.accumulation_windows.length, 2);
  const absent = toProviderForecast(forecast(), { now: NOW, variables: ['precipitation'] }).series[0];
  assert.equal(absent.reason, 'field_not_in_forecast');
  assert.equal(absent.values, null);
  assert.equal(absent.unit, null);
  assert.equal(Object.hasOwn(absent, 'accumulation_windows'), false);
});

test('actual CLI opts into precipitation separately from selected display variables', () => {
  const script = fileURLToPath(new URL('../scripts/forecast.mjs', import.meta.url));
  const args = [script, 'core-cache', '--latitude', '52.52', '--longitude', '13.41',
    '--run', QUERY.run, '--steps', '3,9,24', '--output-contract', 'provider', '--variables', 'precipitation'];
  const preview = extra => JSON.parse(execFileSync(process.execPath, [...args, ...extra],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 5000 }));
  const explicit = preview(['--include-precipitation']);
  assert.equal(explicit.executed, false);
  assert.equal(explicit.auto_fallback, false);
  assert.equal(explicit.query.includePrecipitation, true);
  assert.equal(explicit.query.includeWind, false);
  assert.deepEqual(explicit.variables, ['precipitation']);
  assert.deepEqual(explicit.index_urls, []);
  assert.equal(preview([]).query.includePrecipitation, false);
});
