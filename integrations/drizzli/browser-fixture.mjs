// SPDX-License-Identifier: GPL-3.0-only
// TEST ONLY: synthetic weather through the real HTTP boundary, never a core/origin claim.
import { createInterface } from 'node:readline';
import { readFile, readlink } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { startProviderHttp } from '../../src/provider-http.mjs';
import { toProviderForecast } from '../../src/provider.mjs';
import { freshness } from '../../src/forecast.mjs';
import { QUERY, windForecast } from '../../tests/fixtures.mjs';
import { airQualityRequest, airQualityFreshness } from '../../src/air-quality.mjs';
import { toAirQualityProviderForecast } from '../../src/air-quality-provider.mjs';
import { aqForecast } from '../../tests/air-quality-fixtures.mjs';

// These inert constructors are exported for contract tests. Importing this
// module must not open a socket or install process/shutdown handlers.
export function fixtureQuery(run, precipitation = false) {
  assert.equal(typeof precipitation, 'boolean');
  return { ...QUERY, run, steps: [3, 9, 24], includeWind: true,
    ...(precipitation ? { includePrecipitation: true } : {}) };
}

export function fixtureForecast(query, now, mode = 'valid') {
  assert.ok(['valid', 'missing', 'short-lived', 'stale'].includes(mode));
  const original = windForecast({ ...query, includePrecipitation: false }, now);
  if (query.includePrecipitation === true) {
    assert.equal(query.model, 'ifs');
    assert.deepEqual(query.steps, [3, 9, 24]);
    original.units.precipitation = 'mm';
    for (const [i, sample] of original.samples.entries()) {
      const start = [0, 0, 6][i], source = [null, 0, 0.00001][i];
      sample.precipitation = {
        amount: source === null ? null : source * 1000, source_value: source,
        start_lead_hours: start, end_lead_hours: sample.lead_hours,
        start_at: new Date(Date.parse(query.run) + start * 3600000).toISOString(), end_at: sample.valid_at,
        evidence: { ...sample.evidence, parameter: 'tp', param_id: 228, unit: 'm', statistic: 'accum',
          range_start: sample.evidence.range_start + 3 * sample.evidence.range_length },
      };
    }
  }
  if (mode === 'missing') {
    original.samples[0].temperature_2m = null;
    Object.assign(original.samples[0].wind_10m, {
      eastward: null, northward: null, speed: null, direction_from: null, status: 'missing',
    });
  }
  return original;
}

export function fixtureAirQualityQuery(weatherQuery) {
  return airQualityRequest({ latitude: weatherQuery.latitude, longitude: weatherQuery.longitude,
    run: new Date(Date.parse(weatherQuery.run) - 6 * 3600000).toISOString(),
    steps: [3, 6, 12], communityArea: true });
}

async function main() {
  const flags = process.argv.slice(4);
  assert.ok(process.argv.length >= 4 && flags.length <= 2 && new Set(flags).size === flags.length
    && flags.every(flag => ['--precipitation', '--air-quality'].includes(flag)));
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  const staticRoot = resolve(process.argv[2]), work = resolve(process.argv[3]);
  const run = new Date(); run.setUTCHours(0, 0, 0, 0);
  const query = fixtureQuery(run.toISOString(), flags.includes('--precipitation'));
  const config = { core: { mode: 'core-cache', executable: `${work}/unused-core`,
    controlSocket: `${work}/unused.sock`, cache: `${work}/unused-cache`, scratchParent: work,
    publisherKey: '1'.repeat(64), name: 'synthetic-browser-forecast', minRevision: 1,
    query, reuseCache: true }, variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m',
    'precipitation', 'air_quality'] };
  if (flags.includes('--air-quality')) config.airQuality = {
    core: { ...config.core, name: 'synthetic-browser-air-quality', query: fixtureAirQualityQuery(query) },
    variables: ['pm2_5', 'pm10'],
  };
  let mode = 'valid', calls = 0, airQualityMode = 'valid', airQualityCalls = 0;
  const server = await startProviderHttp({ config, staticRoot, requestDeadlineMs: 5000 }, {
    fetchProvider: async () => {
      ++calls;
      if (mode === 'unavailable') throw new Error('SYNTHETIC_UNAVAILABLE');
      const now = new Date().toISOString(), original = fixtureForecast(query, now, mode);
      const publicationExpires = new Date(Date.now() + (mode === 'short-lived' ? 2500
        : mode === 'stale' ? -1000 : 120000)).toISOString();
      const projection = toProviderForecast(original, { variables: config.variables, now, publicationExpires });
      return { ...projection, delivery: { mode: 'core-cache', publisher_key: config.core.publisherKey,
        name: config.core.name, revision: 1, manifest_id: '2'.repeat(64), sha256: '3'.repeat(64),
        publication_expires_at: publicationExpires, freshness: freshness(original, now, publicationExpires),
        upstream_origin_attested: false, manifest_media_type_checked: false } };
    },
    fetchAirQualityProvider: async () => {
      ++airQualityCalls;
      assert.ok(config.airQuality);
      if (airQualityMode === 'unavailable') throw new Error('SYNTHETIC_UNAVAILABLE');
      const now = new Date().toISOString(), original = aqForecast(config.airQuality.core.query, now);
      const publicationExpires = new Date(Date.now() + (airQualityMode === 'short-lived' ? 2500
        : airQualityMode === 'stale' ? -1000 : 120000)).toISOString();
      const projection = toAirQualityProviderForecast(original, {
        variables: config.airQuality.variables, now, publicationExpires });
      return { ...projection, delivery: { mode: 'core-cache', publisher_key: config.airQuality.core.publisherKey,
        name: config.airQuality.core.name, revision: 1, manifest_id: '4'.repeat(64), sha256: '5'.repeat(64),
        publication_expires_at: publicationExpires, freshness: airQualityFreshness(original, now, publicationExpires),
        upstream_origin_attested: false, manifest_media_type_checked: false } };
    },
  });
  const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let stopping = false, stopPromise;
  function stop() {
    if (!stopPromise) {
      stopping = true;
      stopPromise = Promise.resolve().then(async () => {
        input.close(); process.stdin.destroy();
        await server.close();
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
      assert.equal(stopping, false);
      assert.ok(command.length <= 32);
      if (command === 'stop') { await stop(); emit({ stopped: true, calls, airQualityCalls }); return; }
      if (command !== 'status') {
        if (command.startsWith('aq-')) {
          assert.ok(config.airQuality && ['aq-valid', 'aq-unavailable', 'aq-short-lived', 'aq-stale'].includes(command));
          airQualityMode = command.slice(3);
        } else {
          assert.ok(['valid', 'unavailable', 'short-lived', 'stale', 'missing'].includes(command));
          mode = command;
        }
      }
      emit({ mode, calls, airQualityMode, airQualityCalls });
    })().catch(fail);
  });
  // Readiness means both the HTTP server and every shutdown/control handler exist.
  emit({ ready: true, origin: server.origin, synthetic: true, core_executed: false,
    ...(query.includePrecipitation ? { scenario: 'precipitation' } : {}),
    ...(config.airQuality ? { air_quality: true, air_quality_valid_at: config.airQuality.core.query.steps
      .map(step => new Date(Date.parse(config.airQuality.core.query.run) + step * 3600000).toISOString()) } : {}),
    valid_at: query.steps.map(step => new Date(Date.parse(query.run) + step * 3600000).toISOString()) });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('synthetic browser fixture failed\n'); process.exitCode = 1; });
}
