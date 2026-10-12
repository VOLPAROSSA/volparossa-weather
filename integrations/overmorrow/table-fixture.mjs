// SPDX-License-Identifier: GPL-3.0-only
// TEST ONLY: actual bridge + captured synthetic response bodies. No core/origin.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, readlink, writeFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { syntheticProducts } from './test-fixtures.mjs';
import { responseProduct } from './browser-fixture.mjs';
import { fixtureQuery, fixtureAirQualityQuery } from '../drizzli/browser-fixture.mjs';
import { precipitationForecast } from '../../tests/precipitation-fixtures.mjs';
import { aqForecast } from '../../tests/air-quality-fixtures.mjs';
import { startProviderHttp } from '../../src/provider-http.mjs';

export function tableProducts(now) {
  const base = syntheticProducts(now);
  const query = { ...fixtureQuery(base.weather.forecast.source.model_run_at, true), steps: [3, 9, 24, 48] };
  base.weather.forecast = precipitationForecast(query, now, { value: 0.00001234 });
  base.weather.forecast.samples[1].temperature_2m = null;
  Object.assign(base.weather.forecast.samples[1].wind_10m,
    { eastward: 0, northward: 0, speed: 0, direction_from: null, status: 'calm' });
  Object.assign(base.weather.forecast.samples[2].precipitation, { amount: null, source_value: null });
  base.air_quality.forecast = aqForecast({ ...fixtureAirQualityQuery(query), steps: [3, 6, 12, 24, 48] }, now);
  return { base, query };
}

export function capturedResponse(base, quality, now) {
  const value = responseProduct(base, quality, 'valid', now);
  // This is exactly provider-http's JSON serialization, before returning the
  // same object to its real response path. The browser supplies completion proof.
  const bytes = Buffer.from(JSON.stringify(value));
  assert.ok(bytes.length > 0 && bytes.length <= 131072);
  return { value, bytes, sha256: createHash('sha256').update(bytes).digest('hex') };
}

async function main() {
  assert.equal(process.argv.length, 4);
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  const staticRoot = resolve(process.argv[2]), work = resolve(process.argv[3]);
  const { base, query } = tableProducts(new Date().toISOString());
  const core = { mode: 'core-cache', executable: `${work}/unused-core`, controlSocket: `${work}/unused.sock`,
    cache: `${work}/unused-cache`, scratchParent: work, publisherKey: '1'.repeat(64),
    name: 'synthetic-browser-forecast', minRevision: 1, query, reuseCache: true };
  const config = { core, variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation', 'air_quality'],
    airQuality: { core: { ...core, name: 'synthetic-browser-air-quality', query: {
      ...fixtureAirQualityQuery(query), steps: [3, 6, 12, 24, 48] } }, variables: ['pm2_5', 'pm10'] } };
  const counts = { weather: 0, air_quality: 0 }, hashes = {};
  async function product(quality) {
    const key = quality ? 'air_quality' : 'weather', ordinal = ++counts[key];
    assert.ok(ordinal <= 2); // Exactly initial loading and one real user refresh.
    const capture = capturedResponse(base, quality, new Date().toISOString());
    await writeFile(`${work}/tmp/served-${key}-${ordinal}.json`, capture.bytes, { flag: 'wx', mode: 0o600 });
    hashes[key] = capture.sha256;
    return capture.value;
  }
  const server = await startProviderHttp({ config, staticRoot, staticProfile: 'flutter-canvaskit', requestDeadlineMs: 5000 },
    { fetchProvider: () => product(false), fetchAirQualityProvider: () => product(true) });
  const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let stopPromise;
  function stop() {
    if (!stopPromise) stopPromise = Promise.resolve().then(async () => {
      input.close(); process.stdin.destroy(); await server.close();
    });
    return stopPromise;
  }
  function fail() { process.exitCode = 1; void stop().catch(() => {}); }
  process.on('SIGTERM', () => void stop().catch(fail));
  process.on('SIGINT', () => void stop().catch(fail));
  input.once('close', () => void stop().catch(fail));
  input.on('line', command => {
    void (async () => {
      assert.ok(!stopPromise && ['status', 'stop'].includes(command));
      if (command === 'stop') { await stop(); emit({ stopped: true, counts, hashes }); }
      else emit({ counts, hashes });
    })().catch(fail);
  });
  emit({ ready: true, origin: server.origin, synthetic: true, core_executed: false,
    valid_at: base.weather.forecast.samples.map(s => s.valid_at),
    air_quality_valid_at: base.air_quality.forecast.samples.map(s => s.valid_at),
    weather_run: query.run, air_quality_run: config.airQuality.core.query.run });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('synthetic table fixture failed\n'); process.exitCode = 1; });
}
