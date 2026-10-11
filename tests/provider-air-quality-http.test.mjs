// SPDX-License-Identifier: GPL-3.0-only
// Real loopback HTTP / synthetic data and core process. Not an overlay/browser proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { mkdtemp, mkdir, chmod, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startProviderHttp, providerHttpConfiguration } from '../src/provider-http.mjs';
import { toAirQualityProviderForecast } from '../src/air-quality-provider.mjs';
import { toProviderForecast } from '../src/provider.mjs';
import { airQualityFreshness, airQualityRequest } from '../src/air-quality.mjs';
import { freshness, request } from '../src/forecast.mjs';
import { aqForecast } from './air-quality-fixtures.mjs';
import { forecast } from './fixtures.mjs';

const AQ_API = '/api/volparossa/air-quality', WEATHER_API = '/api/volparossa/forecast';
function get(origin, path = AQ_API, options = {}) {
  return new Promise((resolve, reject) => {
    const req = httpRequest(origin, { method: 'GET', path, ...options }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers,
        body: JSON.parse(Buffer.concat(chunks).toString()) }));
    }); req.once('error', reject); req.end();
  });
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'weather-aq-http-')); await chmod(root, 0o700);
  const staticRoot = join(root, 'static'); await mkdir(staticRoot, { mode: 0o700 });
  await writeFile(join(staticRoot, 'index.html'), '<!doctype html><title>synthetic fixture</title>', { mode: 0o600 });
  const nowRun = Math.floor(Date.now() / 21600000) * 21600000;
  const core = { mode: 'core-cache', executable: join(root, 'fake-core'), controlSocket: join(root, 'control.sock'),
    cache: join(root, 'cache'), scratchParent: root, publisherKey: 'c'.repeat(64), name: 'community.weather',
    minRevision: 2, reuseCache: true, query: request({ latitude: 52.52, longitude: 13.41,
      run: new Date(nowRun).toISOString(), steps: [12], communityArea: true }) };
  const config = { core, variables: ['temperature_2m'], airQuality: {
    core: { ...core, publisherKey: 'e'.repeat(64), name: 'community.particulates',
      query: airQualityRequest({ latitude: 52.52, longitude: 13.41, run: new Date(nowRun - 21600000).toISOString(),
        steps: [3, 9, 24], communityArea: true }) }, variables: ['pm2_5', 'pm10'] } };
  t.after(() => rm(root, { recursive: true, force: true }));
  function provider(airQuality = true, acquiredAt = new Date().toISOString()) {
    const selected = airQuality ? config.airQuality : config;
    const data = airQuality ? aqForecast(selected.core.query, acquiredAt) : forecast(selected.core.query, acquiredAt);
    const expiry = new Date(Math.floor(Date.now() / 1000) * 1000 + 1200000).toISOString();
    const result = (airQuality ? toAirQualityProviderForecast : toProviderForecast)(data,
      { variables: selected.variables, now: acquiredAt, publicationExpires: expiry });
    result.delivery = { mode: 'core-cache', publisher_key: selected.core.publisherKey, name: selected.core.name,
      revision: 2, manifest_id: 'b'.repeat(64), sha256: 'd'.repeat(64), publication_expires_at: expiry,
      freshness: (airQuality ? airQualityFreshness : freshness)(data, acquiredAt, expiry),
      upstream_origin_attested: false, manifest_media_type_checked: false };
    return result;
  }
  async function start(injected = {}, options = {}) {
    const server = await startProviderHttp({ config, staticRoot, ...options }, {
      fetchProvider: async () => provider(false), fetchAirQualityProvider: async () => provider(), ...injected });
    t.after(() => server.close()); return server;
  }
  return { root, staticRoot, config, provider, start };
}

test('optional AQ configuration is exact, detached, public and bound to weather coordinates but its own timeline', async t => {
  const f = await fixture(t), fixed = providerHttpConfiguration(f.config);
  assert.notEqual(fixed.airQuality.core.query.run, fixed.core.query.run);
  assert.deepEqual(fixed.airQuality.core.query.steps, [3, 9, 24]);
  assert.equal(fixed.airQuality.core.query.model, 'gefs-aerosols');
  f.config.airQuality.variables.push('aqi');
  assert.deepEqual(fixed.airQuality.variables, ['pm2_5', 'pm10']);
  assert.ok(Object.isFrozen(fixed.airQuality) && Object.isFrozen(fixed.airQuality.core.query));
  for (const change of [c => c.airQuality = null, c => c.airQuality.origin = 'https://private',
    c => c.airQuality.core.mode = 'origin', c => c.airQuality.core.reuseCache = false,
    c => c.airQuality.core.query.latitude = 1, c => c.airQuality.core.query.longitude = 1,
    c => c.airQuality.core.query.communityArea = false, c => c.airQuality.core.query.model = 'ifs',
    c => c.airQuality.core.query.includeWind = false, c => c.airQuality.core.query.steps = [1],
    c => c.airQuality.core.executable = '/private/../escape', c => c.airQuality.core.minRevision = 0,
    c => c.airQuality.variables = [], c => c.airQuality.core.publisherKey = 'invalid']) {
    const invalid = structuredClone(f.config); change(invalid);
    assert.throws(() => providerHttpConfiguration(invalid));
  }
  const legacy = structuredClone(f.config); delete legacy.airQuality;
  assert.deepEqual(Object.keys(providerHttpConfiguration(legacy)).sort(), ['core', 'variables']);
});

test('real HTTP keeps NOAA values/null/zero and run separate from ECMWF; fixed owner configuration reaches backend', async t => {
  const f = await fixture(t), expected = f.provider(); let calls = 0;
  const server = await f.start({ fetchAirQualityProvider: async (core, options) => {
    calls++; assert.deepEqual(core, f.config.airQuality.core);
    assert.deepEqual(options.variables, ['pm2_5', 'pm10']); assert.ok(options.signal instanceof AbortSignal);
    return expected;
  } });
  const result = await get(server.origin, AQ_API, { headers: { Origin: server.origin, 'Sec-Fetch-Site': 'same-origin' } });
  assert.equal(result.status, 200); assert.deepEqual(result.body, expected);
  assert.deepEqual(result.body.series[0].values, [null, 0, 5.53071]);
  assert.deepEqual(result.body.timeline.lead_hours, [3, 9, 24]);
  assert.equal(result.body.series[0].statistic, 'instant');
  assert.equal(result.headers['cache-control'], 'no-store');
  assert.equal(result.headers['access-control-allow-origin'], undefined);
  assert.match(result.headers['content-security-policy'], /connect-src 'self'/);
  const weather = await get(server.origin, WEATHER_API);
  assert.equal(weather.status, 200); assert.equal(weather.body.forecast.source.provider, 'ecmwf');
  assert.notEqual(weather.body.forecast.source.model_run_at, result.body.forecast.source.model_run_at);
  assert.equal(calls, 1);
});

test('weather-only deployment returns closed unavailable AQ and never calls either source as fallback', async t => {
  const f = await fixture(t); delete f.config.airQuality; let aq = 0, weather = 0;
  const server = await f.start({ fetchAirQualityProvider: () => { aq++; throw Error('not allowed'); },
    fetchProvider: () => { weather++; return f.provider(false); } });
  assert.deepEqual(await get(server.origin).then(({ status, body }) => ({ status, body })),
    { status: 503, body: { error: 'AIR_QUALITY_UNAVAILABLE' } });
  assert.equal(aq, 0); assert.equal(weather, 0);
  assert.equal((await get(server.origin, WEATHER_API)).status, 200); assert.equal(weather, 1);
});

test('AQ HTTP requests cannot change location, source, query, executable, host or origin authority', async t => {
  const f = await fixture(t); let calls = 0;
  const server = await f.start({ fetchAirQualityProvider: () => { calls++; return f.provider(); } });
  for (const [path, options, status] of [
    [`${AQ_API}?latitude=1`, {}, 400], [`${AQ_API}?publisher=private`, {}, 400],
    [AQ_API, { method: 'POST' }, 405], [AQ_API, { headers: { Host: 'attacker.invalid' } }, 403],
    [AQ_API, { headers: { Origin: 'https://attacker.invalid' } }, 403],
    [AQ_API, { headers: { 'Sec-Fetch-Site': 'cross-site' } }, 403],
    [AQ_API, { headers: { 'Content-Length': '1' } }, 400], ['/api/volparossa/air-quality/other', {}, 404],
  ]) { const result = await get(server.origin, path, options); assert.equal(result.status, status);
    assert.deepEqual(Object.keys(result.body), ['error']); }
  assert.equal(calls, 0);
});

test('AQ bridge validates source, exact projection/query/delivery and current freshness independently', async t => {
  const f = await fixture(t); let value = f.provider();
  const server = await f.start({ fetchAirQualityProvider: () => value });
  for (const change of [v => v.series[0].values[0] = 0, v => v.series[0].unit = 'AQI',
    v => v.series[0].statistic = 'average', v => v.timeline.lead_hours[0] = 1,
    v => v.capabilities.current_observations = true, v => v.delivery.name = 'other',
    v => v.delivery.publisher_key = 'f'.repeat(64), v => v.delivery.revision = 1,
    v => v.delivery.manifest_media_type_checked = true, v => v.delivery.private_path = '/private',
    v => v.delivery.upstream_origin_attested = true, v => v.delivery.freshness.expires_at = '2099-01-01T00:00:00.000Z',
    v => v.delivery.manifest_id = ['b'.repeat(64)], v => v.delivery.sha256 = ['d'.repeat(64)],
    v => v.delivery.publication_expires_at = '2000-01-01T00:00:00.000Z',
    v => v.forecast.area.latitude = 1, v => v.forecast.area.sharing = 'private',
    v => v.forecast.source.provider = 'ecmwf', v => v.forecast.samples[0].evidence.pm10.statistic = 'average',
    v => v.verification_scope = 'origin-authenticated']) {
    value = f.provider(); change(value);
    const result = await get(server.origin);
    assert.equal(result.status, 503); assert.deepEqual(result.body, { error: 'AIR_QUALITY_UNAVAILABLE' });
  }
  // A fully consistent projection for a wrong area also cannot pass the fixed owner query.
  value = f.provider(); value.forecast.area.latitude = 1;
  value = { ...toAirQualityProviderForecast(value.forecast, { publicationExpires: value.delivery.publication_expires_at }), delivery: value.delivery };
  assert.equal((await get(server.origin)).status, 503);
  // Publication lifetime is mandatory for delivered objects, even though pure
  // projection intentionally permits a local object without a publication.
  value = f.provider(); value.delivery.publication_expires_at = null;
  value = { ...toAirQualityProviderForecast(value.forecast), delivery: value.delivery };
  value.delivery.freshness = airQualityFreshness(value.forecast, value.freshness.checked_at);
  assert.equal((await get(server.origin)).status, 503);
  // A previously valid response is rechecked against the bridge's current clock.
  value = f.provider(true, new Date(Date.now() - 3600000).toISOString());
  assert.equal((await get(server.origin)).status, 503);
  value = f.provider(false); assert.equal((await get(server.origin)).status, 503);
});

test('AQ and weather share one active slot; synchronous failures release it without source fallback', async t => {
  const f = await fixture(t); let entered, release, calls = 0;
  const began = new Promise(done => { entered = done; }), held = new Promise(done => { release = done; });
  const server = await f.start({ fetchAirQualityProvider: async () => { calls++; entered(); await held; return f.provider(); } });
  const pending = get(server.origin); await began;
  for (const path of [AQ_API, WEATHER_API]) {
    const result = await get(server.origin, path); assert.equal(result.status, 429);
    assert.deepEqual(result.body, { error: 'FORECAST_BUSY' });
  }
  assert.equal(calls, 1); release(); assert.equal((await pending).status, 200);
  assert.equal((await get(server.origin, WEATHER_API)).status, 200);
  let failures = 0;
  const failing = await f.start({ fetchAirQualityProvider: () => { failures++; throw Error('PRIVATE_SENTINEL'); } });
  for (let i = 0; i < 2; i++) {
    const result = await get(failing.origin); assert.equal(result.status, 503);
    assert.deepEqual(result.body, { error: 'AIR_QUALITY_UNAVAILABLE' });
  }
  assert.equal(failures, 2); assert.equal((await get(failing.origin, WEATHER_API)).status, 200);
});

test('shared deadline, client disconnect and shutdown all abort AQ retrieval and join cleanup', async t => {
  const f = await fixture(t); let entered, aborts = 0, cleaned = false;
  let began = new Promise(done => { entered = done; });
  const server = await startProviderHttp({ config: f.config, staticRoot: f.staticRoot, requestDeadlineMs: 60 }, {
    fetchAirQualityProvider: async (_core, { signal }) => {
      entered(); await new Promise(done => signal.addEventListener('abort', done, { once: true })); aborts++;
      await new Promise(done => setTimeout(done, 10)); cleaned = true; throw Error('private cancelled');
    },
  });
  t.after(() => server.close());
  const awaitCleanup = async () => {
    for (let i = 0; i < 100 && !cleaned; i++) await new Promise(done => setTimeout(done, 5));
    assert.equal(cleaned, true);
  };
  const timedOut = await get(server.origin); assert.equal(timedOut.status, 503);
  assert.deepEqual(timedOut.body, { error: 'AIR_QUALITY_UNAVAILABLE' });
  await awaitCleanup();
  began = new Promise(done => { entered = done; }); cleaned = false;
  const req = httpRequest(server.origin + AQ_API); req.on('error', () => {}); req.end();
  await began; req.destroy();
  await awaitCleanup();
  assert.equal(aborts, 2);
  began = new Promise(done => { entered = done; }); cleaned = false;
  const pending = get(server.origin).catch(() => null); await began;
  await server.close(); await pending; assert.equal(cleaned, true); assert.equal(aborts, 3);
});

test('weather timeout responds only after abort cleanup so immediate AQ starts; late aborted result never succeeds', async t => {
  for (const lateResult of [false, true]) {
    const f = await fixture(t); let cleaned = false, weatherCalls = 0, aqCalls = 0;
    const server = await f.start({
      fetchProvider: async (_core, { signal }) => {
        weatherCalls++;
        await new Promise(done => signal.addEventListener('abort', done, { once: true }));
        await new Promise(done => setTimeout(done, 80)); cleaned = true;
        if (lateResult) return f.provider(false);
        throw Error('private cleanup completed');
      },
      fetchAirQualityProvider: () => { aqCalls++; assert.equal(cleaned, true); return f.provider(); },
    }, { requestDeadlineMs: 25 });
    const weather = await get(server.origin, WEATHER_API);
    assert.equal(weather.status, 503); assert.deepEqual(weather.body, { error: 'FORECAST_UNAVAILABLE' });
    // No extra cleanup wait/retry between the response and the next product.
    assert.equal(cleaned, true);
    const aq = await get(server.origin, AQ_API);
    assert.equal(aq.status, 200); assert.equal(aq.body.schema, 'volparossa.air-quality.provider.v1');
    assert.equal(weatherCalls, 1); assert.equal(aqCalls, 1);
  }
});

test('default AQ backend invokes the real subprocess boundary with fixed named object and cache reuse', async t => {
  const f = await fixture(t), core = f.config.airQuality.core;
  const socket = createServer(); socket.listen(core.controlSocket); await once(socket, 'listening');
  t.after(() => socket.close());
  const data = aqForecast(core.query, new Date().toISOString()), calls = join(f.root, 'calls');
  await writeFile(core.executable, `#!${process.execPath}
const fs=require('node:fs'),crypto=require('node:crypto');
const args=process.argv.slice(2), read=key=>args[args.indexOf(key)+1];
if(args[2]!=='content'||args[3]!=='fetch-name'||!args.includes('--reuse-cache')||args.includes('--cache-only')
 ||read('--cache')!==${JSON.stringify(core.cache)}||read('--publisher-key')!==${JSON.stringify(core.publisherKey)}
 ||read('--name')!==${JSON.stringify(core.name)}||read('--quota-bytes')!=='131072')process.exit(9);
fs.appendFileSync(${JSON.stringify(calls)},'reuse\\n',{mode:0o600});
const bytes=Buffer.from(JSON.stringify(${JSON.stringify(data)})),output=read('--local-output');
fs.writeFileSync(output,bytes,{mode:0o600,flag:'wx'});
process.stdout.write(JSON.stringify({operation:'named_content_download',publisher_key:read('--publisher-key'),name:read('--name'),revision:2,
 manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
 sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,local_delivery:true,output_mode:'0600',
 ownership_changed:false,origin_authenticated:false,globally_latest:false,local_output:output,cache:read('--cache'),cache_only:false}));
`, { mode: 0o700 });
  const server = await startProviderHttp({ config: f.config, staticRoot: f.staticRoot }); t.after(() => server.close());
  for (let i = 0; i < 2; i++) {
    const result = await get(server.origin); assert.equal(result.status, 200);
    assert.deepEqual(result.body.forecast, data); assert.equal(result.body.delivery.upstream_origin_attested, false);
    assert.deepEqual(result.body.series[0].values, [null, 0, 5.53071]);
  }
  assert.equal(await readFile(calls, 'utf8'), 'reuse\nreuse\n');
  assert.deepEqual((await readdir(f.root)).sort(), ['calls', 'control.sock', 'fake-core', 'static']);
});
