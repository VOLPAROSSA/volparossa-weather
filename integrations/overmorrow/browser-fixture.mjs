// SPDX-License-Identifier: GPL-3.0-only
// TEST ONLY: actual shared HTTP bridge, synthetic products, no core/source access.
import assert from 'node:assert/strict';
import { readFile, readlink } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { syntheticProducts } from './test-fixtures.mjs';
import { fixtureQuery, fixtureAirQualityQuery } from '../drizzli/browser-fixture.mjs';
import { startProviderHttp } from '../../src/provider-http.mjs';
import { toProviderForecast } from '../../src/provider.mjs';
import { freshness } from '../../src/forecast.mjs';
import { toAirQualityProviderForecast } from '../../src/air-quality-provider.mjs';
import { airQualityFreshness } from '../../src/air-quality.mjs';

export function responseProduct(base, quality, mode, now = new Date().toISOString()) {
  assert.ok(['valid', 'missing', 'short-lived', 'stale'].includes(mode));
  const prior = base[quality ? 'air_quality' : 'weather'];
  const original = structuredClone(prior.forecast);
  original.source.acquired_at = now;
  original.freshness.expires_at = new Date(Math.min(Date.parse(now) + 1800000,
    Date.parse(original.source.model_run_at) + 72 * 3600000)).toISOString();
  if (mode === 'missing' && !quality) {
    original.samples[0].temperature_2m = null;
    Object.assign(original.samples[0].wind_10m, {
      eastward: null, northward: null, speed: null, direction_from: null, status: 'missing',
    });
  }
  const publicationExpires = new Date(Date.parse(now) + (mode === 'stale' ? -1000
    : mode === 'short-lived' ? 4500 : 120000)).toISOString();
  const projection = (quality ? toAirQualityProviderForecast : toProviderForecast)(original, {
    variables: quality ? ['pm2_5', 'pm10'] : ['temperature_2m', 'wind_speed_10m',
      'wind_direction_10m', 'precipitation', 'air_quality'], now, publicationExpires });
  return { ...projection, delivery: { ...prior.delivery, publication_expires_at: publicationExpires,
    freshness: (quality ? airQualityFreshness : freshness)(original, now, publicationExpires) } };
}

async function main() {
  assert.equal(process.argv.length, 4);
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  const staticRoot = resolve(process.argv[2]), work = resolve(process.argv[3]);
  const base = syntheticProducts(new Date().toISOString());
  const query = fixtureQuery(base.weather.forecast.source.model_run_at, true);
  const core = { mode: 'core-cache', executable: `${work}/unused-core`,
    controlSocket: `${work}/unused.sock`, cache: `${work}/unused-cache`, scratchParent: work,
    publisherKey: '1'.repeat(64), name: 'synthetic-browser-forecast', minRevision: 1,
    query, reuseCache: true };
  const config = { core, variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m',
    'precipitation', 'air_quality'], airQuality: {
      core: { ...core, name: 'synthetic-browser-air-quality', query: fixtureAirQualityQuery(query) },
      variables: ['pm2_5', 'pm10'],
    } };
  let mode = 'valid', calls = 0, airQualityMode = 'valid', airQualityCalls = 0;
  const server = await startProviderHttp({ config, staticRoot, staticProfile: 'flutter-canvaskit',
    requestDeadlineMs: 5000 }, {
    fetchProvider: async () => {
      ++calls;
      if (mode === 'unavailable') throw new Error('SYNTHETIC_UNAVAILABLE');
      return responseProduct(base, false, mode);
    },
    fetchAirQualityProvider: async () => {
      ++airQualityCalls;
      if (airQualityMode === 'unavailable') throw new Error('SYNTHETIC_UNAVAILABLE');
      return responseProduct(base, true, airQualityMode);
    },
  });
  const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let stopping = false, stopPromise;
  function stop() {
    if (!stopPromise) {
      stopping = true;
      stopPromise = Promise.resolve().then(async () => {
        input.close(); process.stdin.destroy(); await server.close();
      });
    }
    return stopPromise;
  }
  function fail() { process.exitCode = 1; void stop().catch(() => {}); }
  process.on('SIGTERM', () => void stop().catch(fail));
  process.on('SIGINT', () => void stop().catch(fail));
  input.once('close', () => void stop().catch(fail));
  input.on('line', command => {
    void (async () => {
      assert.equal(stopping, false); assert.ok(command.length <= 32);
      if (command === 'stop') { await stop(); emit({ stopped: true, calls, airQualityCalls }); return; }
      if (command !== 'status') {
        if (command.startsWith('aq-')) {
          assert.ok(['aq-valid', 'aq-unavailable', 'aq-short-lived', 'aq-stale'].includes(command));
          airQualityMode = command.slice(3);
        } else {
          assert.ok(['valid', 'unavailable', 'short-lived', 'stale', 'missing'].includes(command));
          mode = command;
        }
      }
      emit({ mode, calls, airQualityMode, airQualityCalls });
    })().catch(fail);
  });
  emit({ ready: true, origin: server.origin, synthetic: true, core_executed: false,
    valid_at: base.weather.forecast.samples.map(item => item.valid_at),
    air_quality_valid_at: base.air_quality.forecast.samples.map(item => item.valid_at),
    weather_run: query.run, air_quality_run: config.airQuality.core.query.run });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('synthetic Overmorrow fixture failed\n'); process.exitCode = 1; });
}
