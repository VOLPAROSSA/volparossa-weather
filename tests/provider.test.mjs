// SPDX-License-Identifier: GPL-3.0-only
// Synthetic forecast projection and real inert CLI preview; no live weather requests.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { PROVIDER_SCHEMA, providerVariables, toProviderForecast } from '../src/provider.mjs';
import { windVector } from '../src/forecast.mjs';
import { NOW, QUERY, forecast, windForecast } from './fixtures.mjs';

const code = value => error => error.code === value;
const all = ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m'];

test('provider v1 preserves full provenance, actual non-hourly steps and fixed units', () => {
  const input = windForecast({ ...QUERY, steps: [12, 15, 24] });
  const result = toProviderForecast(input, { variables: all, now: NOW });
  assert.equal(result.schema, PROVIDER_SCHEMA);
  assert.equal(result.kind, 'forecast');
  assert.deepEqual(result.forecast, input);
  assert.notEqual(result.forecast, input);
  assert.deepEqual(result.timeline.lead_hours, [12, 15, 24]);
  assert.deepEqual(result.timeline.valid_at, input.samples.map(sample => sample.valid_at));
  assert.equal(result.timeline.time_zone, 'UTC');
  assert.deepEqual(result.series.map(series => series.unit), ['degC', 'm/s', 'degree']);
  assert.deepEqual(result.series[1].values, [5, 5, 5]);
  assert.deepEqual(result.series[2].values, input.samples.map(sample => sample.wind_10m.direction_from));
  assert.equal(result.forecast.source.model_run_at, QUERY.run);
  assert.equal(result.forecast.source.issued_at, null);
  assert.equal(result.forecast.source.acquired_at, NOW);
  assert.equal(result.capabilities.interpolation, false);
  assert.equal(result.capabilities.current_observations, false);
  assert.equal(result.capabilities.trained_corrections, false);
  assert.equal(result.verification_scope, 'forecast-schema-and-freshness-only');
  assert.equal(result.delivery, null);
});

test('unsupported variables and supported-but-unrequested forecast fields are distinct', () => {
  const result = toProviderForecast(forecast(), { now: NOW,
    variables: ['precipitation', 'wind_speed_10m', 'temperature_2m', 'aqi', 'weather_code'] });
  assert.deepEqual(result.capabilities.available_variables, ['temperature_2m']);
  for (const index of [0, 1, 3, 4]) {
    assert.equal(result.series[index].availability, 'unavailable');
    assert.equal(result.series[index].values, null);
    assert.equal(result.series[index].value_status, null);
    assert.equal(result.series[index].unit, null);
    assert.equal(result.series[index].reason, index <= 1 ? 'field_not_in_forecast' : 'unsupported_variable');
  }
  assert.deepEqual(result.series[2].values, [10]);
  assert.equal(result.series[2].availability, 'supported');
});

test('null temperature, missing wind and actual calm remain different from invented zero values', () => {
  for (const [eastward, northward, status, speed] of [[null, 2, 'missing', null], [0, 0, 'calm', 0]]) {
    const input = windForecast();
    input.samples[0].temperature_2m = null;
    Object.assign(input.samples[0].wind_10m, windVector(eastward, northward));
    const result = toProviderForecast(input, { variables: all, now: NOW });
    assert.deepEqual(result.series[0].values, [null]);
    assert.deepEqual(result.series[0].value_status, ['missing']);
    assert.deepEqual(result.series[1].values, [speed]);
    assert.deepEqual(result.series[1].value_status, [status]);
    assert.deepEqual(result.series[2].values, [null]);
    assert.deepEqual(result.series[2].value_status, [status]);
  }
});

test('publication expiry and acquisition/run expiry are independently preserved and enforced', () => {
  const input = forecast();
  const result = toProviderForecast(input, { now: '2026-09-30T21:04:59.000Z',
    publicationExpires: '2026-09-30T21:05:00.000Z' });
  assert.equal(result.freshness.expires_at, '2026-09-30T21:05:00.000Z');
  assert.equal(result.forecast.freshness.expires_at, '2026-09-30T21:30:00.000Z');
  assert.equal(result.freshness.age_seconds, 299);
  assert.equal(result.forecast.source.acquired_at, NOW);
  assert.throws(() => toProviderForecast(input, { now: '2026-09-30T21:05:00.000Z',
    publicationExpires: '2026-09-30T21:05:00.000Z' }), code('STALE_FORECAST'));
  assert.throws(() => toProviderForecast(input, { now: '2026-09-30T21:30:00.000Z',
    publicationExpires: '2026-09-30T22:00:00.000Z' }), code('STALE_FORECAST'));
  assert.throws(() => toProviderForecast(input, { now: '2026-09-30T20:59:59.000Z' }), code('CLOCK_BEFORE_ACQUISITION'));
  assert.throws(() => toProviderForecast(input, { now: NOW, publicationExpires: 'tomorrow' }), code('TIME_INVALID'));
});

test('projection cannot bypass malformed units/source, changed derivation or mismatched time evidence', () => {
  for (const change of [data => data.units.temperature_2m = 'K', data => data.units.wind_10m = 'km/h',
    data => data.source.provider = '', data => data.source.license = 'unknown',
    data => data.source.acquisition = 'trained-model', data => data.samples[0].wind_10m.speed = 999,
    data => data.samples[0].valid_at = NOW, data => data.samples[0].evidence.parameter = 'tp']) {
    const data = windForecast(); change(data);
    assert.throws(() => toProviderForecast(data, { variables: all, now: NOW }));
  }
});

test('provider requests are bounded unique variable identifiers and snapshots do not alias inputs', () => {
  for (const variables of [[], ['temperature_2m', 'temperature_2m'], ['bad/path'], ['__proto__'], ['x'.repeat(65)],
    Array.from({ length: 17 }, (_, i) => `variable_${i}`), new Array(1), [null], 'temperature_2m']) {
    assert.throws(() => providerVariables(variables), code('PROVIDER_VARIABLES_INVALID'));
  }
  const requested = ['temperature_2m'];
  const frozen = providerVariables(requested);
  requested.push('aqi');
  assert.deepEqual(frozen, ['temperature_2m']);
  assert.ok(Object.isFrozen(frozen));
  const input = forecast(); const result = toProviderForecast(input, { now: NOW });
  result.forecast.source.provider = 'changed'; result.series[0].values[0] = 99;
  assert.equal(input.source.provider, 'ecmwf');
  assert.equal(input.samples[0].temperature_2m, 10);
});

const script = fileURLToPath(new URL('../scripts/forecast.mjs', import.meta.url));
const args = ['core-cache', '--latitude', '52.52', '--longitude', '13.41', '--run', QUERY.run, '--steps', '12'];
const preview = extra => JSON.parse(execFileSync(process.execPath, [script, ...args, ...extra],
  { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 5000 }));
test('actual CLI provider preview stays inert and legacy default output stays unchanged', () => {
  const legacy = preview([]);
  assert.deepEqual(preview(['--output-contract', 'forecast']), legacy);
  assert.equal(Object.hasOwn(legacy, 'output_contract'), false);
  const provider = preview(['--output-contract', 'provider', '--variables', 'temperature_2m,precipitation']);
  assert.equal(provider.output_contract, PROVIDER_SCHEMA);
  assert.deepEqual(provider.variables, ['temperature_2m', 'precipitation']);
  assert.equal(provider.executed, false);
  assert.equal(provider.auto_fallback, false);
  assert.deepEqual(provider.index_urls, []);
  assert.deepEqual(provider.query, legacy.query);
  const wind = ['--output-contract', 'provider', '--variables', 'wind_speed_10m'];
  assert.equal(preview(wind).query.includeWind, false);
  assert.equal(preview([...wind, '--include-wind']).query.includeWind, true);
});

test('actual CLI refuses malformed provider options with closed errors before execution', () => {
  for (const options of [['--output-contract', 'other'], ['--variables', 'temperature_2m'],
    ['--output-contract', 'provider', '--variables', 'private/path'],
    ['--execute', '--output-contract', 'provider', '--variables', 'temperature_2m,temperature_2m'],
    ['--execute', '--output-contract', 'provider', '--variables', Array.from({ length: 17 }, (_, i) => `v_${i}`).join(',')]]) {
    assert.throws(() => preview(options), error => {
      const result = JSON.parse(error.stderr.toString());
      assert.ok(['OUTPUT_CONTRACT_INVALID', 'PROVIDER_VARIABLES_INVALID'].includes(result.error));
      assert.equal(error.stdout.toString(), '');
      assert.equal(error.stderr.toString().includes('private/path'), false);
      return error.status === 1;
    });
  }
});
