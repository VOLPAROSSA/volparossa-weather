// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import test from 'node:test';
import { syntheticProducts } from './test-fixtures.mjs';
import { responseProduct } from './browser-fixture.mjs';

const base = syntheticProducts();
test('synthetic fixture preserves independent native runs and projections', () => {
  for (const quality of [false, true]) {
    const prior = base[quality ? 'air_quality' : 'weather'];
    const result = responseProduct(base, quality, 'valid', base.now);
    assert.deepEqual(result.forecast.samples, prior.forecast.samples);
    assert.equal(result.forecast.source.model_run_at, prior.forecast.source.model_run_at);
    assert.equal(result.freshness.stale, false);
    assert.equal(result.delivery.upstream_origin_attested, false);
    assert.equal(result.delivery.manifest_media_type_checked, false);
  }
  assert.notEqual(base.weather.forecast.source.model_run_at, base.air_quality.forecast.source.model_run_at);
});
test('synthetic fixture explicit missing values do not become zero', () => {
  const value = responseProduct(base, false, 'missing', base.now);
  assert.equal(value.forecast.samples[0].temperature_2m, null);
  assert.equal(value.forecast.samples[0].wind_10m.speed, null);
  assert.equal(value.forecast.samples[1].precipitation.amount, 0);
  assert.equal(value.forecast.samples[2].precipitation.amount, 0.01);
  assert.equal(base.weather.forecast.samples[0].temperature_2m, 10);
});
test('products have independent short-lived publication expiry', () => {
  const weather = responseProduct(base, false, 'short-lived', base.now);
  const quality = responseProduct(base, true, 'valid', base.now);
  assert.equal(Date.parse(weather.freshness.expires_at) - Date.parse(base.now), 4500);
  assert.equal(Date.parse(quality.freshness.expires_at) - Date.parse(base.now), 120000);
  assert.notEqual(weather.freshness.expires_at, quality.freshness.expires_at);
});
test('stale and invalid modes cannot enter the HTTP bridge as valid products', () => {
  for (const quality of [false, true]) {
    assert.throws(() => responseProduct(base, quality, 'stale', base.now));
    assert.throws(() => responseProduct(base, quality, 'unavailable', base.now));
    assert.throws(() => responseProduct(base, quality, 'unknown', base.now));
  }
});
