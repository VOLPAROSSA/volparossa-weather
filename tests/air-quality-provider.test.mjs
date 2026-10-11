// SPDX-License-Identifier: GPL-3.0-only
// Pure projections of explicit synthetic data, not live NOAA or overlay evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import { AIR_QUALITY_PROVIDER_SCHEMA, toAirQualityProviderForecast } from '../src/air-quality-provider.mjs';
import { fetchCachedAirQualityProvider } from '../src/provider-core.mjs';
import { AQ_NOW, AQ_QUERY, aqForecast } from './air-quality-fixtures.mjs';

test('AQ projection retains the original NOAA native timeline, provenance and concentration units', () => {
  const original = aqForecast(), result = toAirQualityProviderForecast(original, { now: AQ_NOW });
  assert.equal(result.schema, AIR_QUALITY_PROVIDER_SCHEMA);
  assert.equal(result.kind, 'forecast'); assert.deepEqual(result.forecast, original);
  assert.notEqual(result.forecast, original); assert.equal(result.delivery, null);
  assert.deepEqual(result.timeline, { time_zone: 'UTC', lead_hours: [3, 6, 12],
    valid_at: original.samples.map(sample => sample.valid_at) });
  assert.deepEqual(result.series.map(series => series.variable), ['pm2_5', 'pm10']);
  assert.deepEqual(result.series.map(series => series.unit), ['ug/m3', 'ug/m3']);
  assert.deepEqual(result.series.map(series => series.statistic), ['instant', 'instant']);
  assert.equal(result.verification_scope, 'forecast-schema-and-freshness-only');
  assert.deepEqual(result.capabilities, { implemented_variables: ['pm2_5', 'pm10'],
    available_variables: ['pm2_5', 'pm10'], time_axis: 'native-model-valid-times',
    interpolation: false, current_observations: false, trained_corrections: false });
});

test('missing concentration, actual zero and unsupported AQI/pollutants remain distinct', () => {
  const result = toAirQualityProviderForecast(aqForecast(), { now: AQ_NOW,
    variables: ['pm2_5', 'pm10', 'aqi', 'ozone', 'temperature_2m'] });
  assert.deepEqual(result.series[0].values, [null, 0, 5.53071]);
  assert.deepEqual(result.series[0].value_status, ['missing', 'available', 'available']);
  assert.deepEqual(result.series[1].values, [11.5959, null, 0]);
  assert.deepEqual(result.series[1].value_status, ['available', 'missing', 'available']);
  for (const series of result.series.slice(2)) assert.deepEqual(series, {
    variable: series.variable, availability: 'unavailable', reason: 'unsupported_variable',
    unit: null, values: null, value_status: null,
  });
});

test('AQ projection cannot rejuvenate acquisition, model or publication freshness', () => {
  const original = aqForecast(), publicationExpires = '2026-10-11T01:05:00.000Z';
  const result = toAirQualityProviderForecast(original, { now: '2026-10-11T01:04:59.000Z', publicationExpires });
  assert.equal(result.freshness.age_seconds, 299); assert.equal(result.freshness.model_age_seconds, 90299);
  assert.equal(result.freshness.expires_at, publicationExpires);
  assert.equal(result.forecast.source.acquired_at, AQ_NOW);
  for (const options of [{ now: publicationExpires, publicationExpires },
    { now: '2026-10-11T01:30:00.000Z' }, { now: '2026-10-11T00:59:59.000Z' },
    { now: AQ_NOW, publicationExpires: 'not-a-time' }]) {
    assert.throws(() => toAirQualityProviderForecast(original, options));
  }
  const edge = aqForecast(AQ_QUERY, '2026-10-12T23:59:59.000Z');
  assert.equal(toAirQualityProviderForecast(edge, { now: edge.source.acquired_at }).freshness.expires_at,
    '2026-10-13T00:00:00.000Z');
});

test('source/unit/statistic/lead tampering is rejected by the original AQ schema', () => {
  for (const change of [f => f.source.provider = 'ecmwf', f => f.kind = 'observation',
    f => f.units.pm10 = 'AQI', f => f.samples[0].evidence.pm2_5.statistic = 'average',
    f => f.samples[0].evidence.pm10.parameter = 'PMTF', f => f.samples[0].pm2_5 = -1,
    f => f.samples[0].valid_at = AQ_NOW, f => f.aqi = 0]) {
    const input = aqForecast(); change(input);
    assert.throws(() => toAirQualityProviderForecast(input, { now: AQ_NOW }));
  }
});

test('variable selection is bounded, preserved in order and checked before core work', async () => {
  for (const variables of [[], ['pm10', 'pm10'], ['bad/path'], new Array(1), ['__proto__'],
    Array.from({ length: 17 }, (_, i) => `v_${i}`), 'pm10']) {
    assert.throws(() => toAirQualityProviderForecast(aqForecast(), { variables, now: AQ_NOW }),
      error => error.code === 'PROVIDER_VARIABLES_INVALID');
    await assert.rejects(fetchCachedAirQualityProvider(undefined, { variables }),
      error => error.code === 'PROVIDER_VARIABLES_INVALID');
  }
  const variables = ['pm10', 'pm2_5'], original = aqForecast();
  const result = toAirQualityProviderForecast(original, { variables, now: AQ_NOW });
  variables.reverse(); result.forecast.samples[0].pm10 = 0; result.series[0].values[0] = 1;
  assert.deepEqual(result.series.map(series => series.variable), ['pm10', 'pm2_5']);
  assert.equal(original.samples[0].pm10, 11.5959);
});
