// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { displayValue, ENDPOINT, fetchProvider } from '../../src/drizzli-client.mjs';

const origin = new URL(process.argv[2]);
assert.ok(process.argv.length === 3 || (process.argv.length === 4 && process.argv[3] === '--software-emulation'));
const readTimeout = process.argv[3] ? 45000 : 8000;
assert.equal(origin.protocol, 'http:');
assert.equal(origin.hostname, '127.0.0.1');
const read = (pathname, options) => {
  assert.equal(pathname, ENDPOINT);
  return fetch(new URL(pathname, origin), options);
};
try {
  const forecast = await fetchProvider(read, AbortSignal.timeout(readTimeout));
  assert.equal(forecast.delivery.cache_only, true);
  console.log(JSON.stringify({
    manifest: forecast.delivery.manifest_id, expiry: forecast.freshness.expires_at,
    display: displayValue(forecast, 'temperature_2m', 0), run: forecast.forecast.source.model_run_at,
    valid: forecast.timeline.valid_at[0]
  }));
} catch (error) {
  if (error.message !== 'FORECAST_UNAVAILABLE') throw error;
  console.log(JSON.stringify({error: error.message}));
}
