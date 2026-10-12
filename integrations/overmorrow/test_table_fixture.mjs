// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { tableProducts, capturedResponse } from './table-fixture.mjs';
import { toProviderForecast } from '../../src/provider.mjs';
import { toAirQualityProviderForecast } from '../../src/air-quality-provider.mjs';

test('inert table fixture captures exact independently timestamped products with four/five native rows', () => {
  const { base } = tableProducts('2026-10-12T01:00:00.000Z');
  for (const [quality, at] of [[false, '2026-10-12T01:00:01.001Z'], [true, '2026-10-12T01:00:02.002Z']]) {
    const result = capturedResponse(base, quality, at);
    assert.deepEqual(JSON.parse(result.bytes), result.value);
    assert.equal(result.sha256, createHash('sha256').update(result.bytes).digest('hex'));
    assert.equal(result.value.forecast.source.acquired_at, at);
    assert.equal(result.value.freshness.expires_at, new Date(Date.parse(at) + 120000).toISOString());
    assert.equal(result.value.forecast.samples.length, quality ? 5 : 4);
    const project = quality ? toAirQualityProviderForecast : toProviderForecast;
    assert.deepEqual(result.value, { ...project(result.value.forecast, {
      variables: quality ? ['pm2_5', 'pm10'] : ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation', 'air_quality'],
      now: at, publicationExpires: result.value.delivery.publication_expires_at }), delivery: result.value.delivery });
  }
  assert.notEqual(base.weather.forecast.source.model_run_at, base.air_quality.forecast.source.model_run_at);
  const samples = base.weather.forecast.samples;
  assert.equal(samples[1].temperature_2m, null);
  assert.equal(samples[1].wind_10m.speed, 0);
  assert.equal(samples[1].wind_10m.direction_from, null);
  assert.equal(samples[2].precipitation.amount, null);
  assert.equal(samples[0].precipitation.amount, 0.01234);
});
