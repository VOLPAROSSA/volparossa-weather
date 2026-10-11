// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { AQ_MAX_BYTES, airQualityRequest, airQualityForecastFromSamples, validateAirQualityForecast,
  parseAirQualityForecast, airQualityFreshness } from '../src/air-quality.mjs';
import { AQ_NOW, AQ_QUERY, aqForecast, aqSamples } from './air-quality-fixtures.mjs';

test('native particulate contract preserves null, zero and source identities without inventing AQI', () => {
  const forecast = aqForecast();
  assert.equal(validateAirQualityForecast(forecast), forecast);
  assert.deepEqual(parseAirQualityForecast(Buffer.from(JSON.stringify(forecast))), forecast);
  assert.deepEqual(forecast.samples.map(sample => sample.pm2_5), [null, 0, 5.53071]);
  assert.equal(forecast.samples[0].evidence.pm2_5.statistic, 'instant');
  assert.equal(forecast.samples[0].evidence.pm10.particle_size_upper_m, 1e-5);
  assert.deepEqual(forecast.units, { pm2_5: 'ug/m3', pm10: 'ug/m3' });
  assert.equal(forecast.source.issued_at, null);
  assert.equal(forecast.source.provider, 'noaa');
  assert.equal(forecast.source.license, 'LicenseRef-NOAA-NODD');
  assert.equal(Object.hasOwn(forecast, 'aqi'), false);
});
test('queries require supported model, run cycle, ordered bounded native steps and explicit sharing', () => {
  const query = airQualityRequest(AQ_QUERY);
  assert.equal(query.model, 'gefs-aerosols');
  assert(Object.isFrozen(query) && Object.isFrozen(query.steps));
  assert.equal(airQualityRequest({ ...AQ_QUERY, communityArea: undefined }).communityArea, false);
  for (const patch of [{ model: 'ifs' }, { steps: [1] }, { steps: [6, 3] }, { steps: [3, 3] },
    { steps: [] }, { steps: [123] }, { steps: Array.from({ length: 17 }, (_, i) => i * 3) },
    { communityArea: 'true' }, { latitude: Infinity }, { longitude: -181 },
    { run: '2026-10-10T01:00:00.000Z' }, { run: '2026-10-10T06:00:00Z' }]) {
    assert.throws(() => airQualityRequest({ ...AQ_QUERY, ...patch }));
  }
  assert.doesNotThrow(() => airQualityRequest({ ...AQ_QUERY, steps: [0, 3, 120] }));
});
test('closed schema rejects forged product, observations, unit, statistic, extra or missing fields', () => {
  const mutations = [f => f.kind = 'observation', f => f.source.model = 'ifs',
    f => f.source.issued_at = AQ_NOW, f => f.source.license = 'CC-BY-4.0',
    f => f.units.pm10 = 'AQI', f => f.units.ozone = 'ug/m3', f => f.aqi = 12,
    f => f.samples[0].evidence.pm2_5.statistic = 'average',
    f => f.samples[0].evidence.pm10.particle_size_upper_m = 2.5e-6,
    f => f.samples[0].evidence.pm2_5.param_id = 260374,
    f => delete f.samples[0].pm10, f => f.samples[0].pm2_5 = -1,
    f => f.samples[0].pm2_5 = Infinity, f => f.samples[0].pm10 = '0',
    f => f.samples[0].grid.method = 'interpolated', f => f.samples[0].grid.distance_km = 51,
    f => f.samples[0].valid_at = '2026-10-10T06:00:00.000Z'];
  for (const mutate of mutations) { const f = aqForecast(); mutate(f); assert.throws(() => validateAirQualityForecast(f)); }
});
test('provenance requires same index and decoder, safe bounded nonoverlapping distinct ranges', () => {
  for (const mutate of [e => e.pm10.index_sha256 = 'f'.repeat(64), e => e.pm10.decoder_sha256 = 'f'.repeat(64),
    e => e.pm10.range_start = e.pm2_5.range_start, e => e.pm10.range_length = 2097153,
    e => e.pm10.range_start = Number.MAX_SAFE_INTEGER, e => e.pm10.field_sha256 = 'invalid']) {
    const f = aqForecast(); mutate(f.samples[0].evidence); assert.throws(() => validateAirQualityForecast(f));
  }
});
test('freshness cannot be extended by cache use, publisher expiry or a nearly expired model run', () => {
  const f = aqForecast();
  assert.equal(airQualityFreshness(f, AQ_NOW).stale, false);
  assert.equal(airQualityFreshness(f, f.freshness.expires_at).stale, true);
  const earlier = '2026-10-11T01:05:00.000Z';
  assert.equal(airQualityFreshness(f, earlier, earlier).stale, true);
  assert.equal(airQualityFreshness(f, AQ_NOW, '2026-10-12T00:00:00.000Z').expires_at, f.freshness.expires_at);
  assert.throws(() => airQualityFreshness(f, '2026-10-11T00:59:59.999Z'), /CLOCK_BEFORE_ACQUISITION/);
  const edge = aqForecast(AQ_QUERY, '2026-10-12T23:59:50.000Z');
  assert.equal(edge.freshness.expires_at, '2026-10-13T00:00:00.000Z');
  assert.throws(() => aqForecast(AQ_QUERY, '2026-10-13T00:00:00.000Z'), /RUN_AGE_INVALID/);
  assert.throws(() => aqForecast(AQ_QUERY, '2026-10-09T23:00:00.000Z'), /RUN_AGE_INVALID/);
});
test('constructor requires exact requested lead sequence and detached source objects', () => {
  const samples = aqSamples();
  const f = airQualityForecastFromSamples({ query: AQ_QUERY, samples, acquiredAt: AQ_NOW });
  samples[0].pm2_5 = 999; samples[0].grid.latitude = 1;
  assert.equal(f.samples[0].pm2_5, null); assert.equal(f.samples[0].grid.latitude, 52.5);
  assert.throws(() => airQualityForecastFromSamples({ query: AQ_QUERY, samples: samples.slice(1), acquiredAt: AQ_NOW }), /AQ_QUERY_MISMATCH/);
  assert.throws(() => airQualityForecastFromSamples({ query: AQ_QUERY, samples, acquiredAt: AQ_NOW, maxAgeSeconds: 1801 }), /EXPIRY_INVALID/);
});
test('parsing is bounded and rejects malformed UTF8, JSON and wrong product', () => {
  for (const bytes of [new Uint8Array(AQ_MAX_BYTES + 1), new Uint8Array([0xff]), Buffer.from('{'), Buffer.from('{}')]) {
    assert.throws(() => parseAirQualityForecast(bytes));
  }
});
