// SPDX-License-Identifier: GPL-3.0-only
// Real loopback HTTP and owned Node children with a deliberately synthetic
// cache format. These are bridge/argv/lifecycle tests, not Rust ChunkStore,
// signatures, protected-network or Android acceptance evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { mkdtemp, mkdir, chmod, writeFile, readFile, readdir, rm, symlink, lstat, rename } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { startProviderHttp, providerHttpConfiguration } from '../src/provider-http.mjs';
import { toProviderForecast } from '../src/provider.mjs';
import { toAirQualityProviderForecast } from '../src/air-quality-provider.mjs';
import { fetchCachedProvider } from '../src/provider-core.mjs';
import { freshness, request, WeatherError } from '../src/forecast.mjs';
import { airQualityFreshness, airQualityRequest } from '../src/air-quality.mjs';
import { forecast } from './fixtures.mjs';
import { aqForecast } from './air-quality-fixtures.mjs';

const WEATHER = '/api/volparossa/forecast', AQ = '/api/volparossa/air-quality';
function get(origin, path = WEATHER) {
  return new Promise((resolve, reject) => {
    const req = httpRequest(origin, { path }, response => {
      const parts = []; response.on('data', part => parts.push(part));
      response.on('end', () => resolve({ status: response.statusCode, body: JSON.parse(Buffer.concat(parts).toString()) }));
    });
    req.once('error', reject); req.end();
  });
}
async function until(check) {
  for (let i = 0; i < 250; i++) { if (await check()) return; await delay(10); }
  assert.fail('bounded synthetic child observation');
}
async function absent(path) {
  await assert.rejects(lstat(path), error => error.code === 'ENOENT');
}

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'weather-cache-lifecycle-'));
  await chmod(root, 0o700);
  const staticRoot = join(root, 'static'), cacheParent = join(root, 'caches');
  await mkdir(staticRoot, { mode: 0o700 }); await mkdir(cacheParent, { mode: 0o700 });
  await writeFile(join(staticRoot, 'index.html'), '<!doctype html><title>synthetic cache lifecycle</title>', { mode: 0o600 });
  const run = new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString();
  const core = { mode: 'core-cache', executable: join(root, 'synthetic-core'), controlSocket: join(root, 'control.sock'),
    cache: join(cacheParent, 'weather'), scratchParent: root, publisherKey: 'c'.repeat(64), name: 'synthetic.weather',
    minRevision: 2, cacheMode: 'create-or-open', query: request({ latitude: 52.52, longitude: 13.41,
      run, steps: [12], communityArea: true }) };
  const config = { core, variables: ['temperature_2m'], airQuality: {
    core: { ...core, cache: join(cacheParent, 'air-quality'), name: 'synthetic.air-quality', publisherKey: 'e'.repeat(64),
      query: airQualityRequest({ latitude: 52.52, longitude: 13.41, run, steps: [3, 9, 24], communityArea: true }) },
    variables: ['pm2_5', 'pm10'] } };
  const acquired = new Date().toISOString();
  const data = { weather: forecast(core.query, acquired), air_quality: aqForecast(config.airQuality.core.query, acquired) };
  const plan = join(root, 'synthetic-plan.json'), callsPath = join(root, 'calls.jsonl');
  await writeFile(plan, '{}', { mode: 0o600 });
  await writeFile(core.executable, `#!${process.execPath}
const fs=require('node:fs'),crypto=require('node:crypto'),path=require('node:path');
const args=process.argv.slice(2),read=key=>args[args.indexOf(key)+1];
const name=read('--name'),kind=name==='synthetic.weather'?'weather':'air_quality';
const cache=read('--cache'),reuse=args.includes('--reuse-cache'),marker=path.join(cache,'SYNTHETIC-NOT-A-CORE-CACHE');
fs.appendFileSync(${JSON.stringify(callsPath)},JSON.stringify({kind,reuse,cache})+'\\n',{mode:0o600});
if(args[2]!=='content'||args[3]!=='fetch-name'||args.includes('--cache-only'))process.exit(8);
const mode=JSON.parse(fs.readFileSync(${JSON.stringify(plan)},'utf8'))[kind]||'ok';
try{
 if(reuse){if(fs.readFileSync(marker,'utf8')!=='synthetic-owned')throw Error('synthetic rejected cache');}
 else{fs.mkdirSync(cache,{mode:0o700});fs.writeFileSync(marker,'synthetic-owned',{mode:0o600,flag:'wx'});}
 if(mode==='incomplete'){fs.writeFileSync(marker,'synthetic-incomplete');throw Error('private incomplete sentinel');}
 if(mode==='fail')throw Error('PRIVATE_SENTINEL/path/location');
 if(mode==='wait'){setInterval(()=>{},1000);}
 else{
 const bytes=Buffer.from(JSON.stringify(${JSON.stringify(data)}[kind])),output=read('--local-output');
 fs.writeFileSync(output,bytes,{mode:0o600,flag:'wx'});
 process.stdout.write(JSON.stringify({operation:'named_content_download',publisher_key:read('--publisher-key'),
 name,revision:2,manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
 sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,local_delivery:true,
 output_mode:'0600',ownership_changed:false,origin_authenticated:false,globally_latest:false,
 local_output:output,cache,cache_only:false}));
 }
}catch{process.stderr.write('PRIVATE_SYNTHETIC_CORE_ERROR');process.exitCode=9;}
`, { mode: 0o700 });
  const socket = createServer(); socket.listen(core.controlSocket); await once(socket, 'listening');
  const servers = [];
  t.after(async () => {
    for (const server of servers) await server.close().catch(() => {});
    await new Promise(resolve => socket.close(resolve));
    await chmod(cacheParent, 0o700).catch(() => {});
    await rm(root, { recursive: true, force: true });
  });
  async function start(options = {}, injected) {
    const server = await startProviderHttp({ config, staticRoot, ...options }, injected);
    servers.push(server); return server;
  }
  async function calls() {
    try { return (await readFile(callsPath, 'utf8')).trim().split('\n').filter(Boolean).map(line => JSON.parse(line)); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  }
  async function setPlan(value) { await writeFile(plan, JSON.stringify(value), { mode: 0o600 }); }
  function provider(quality = false) {
    const selected = quality ? config.airQuality : config, value = data[quality ? 'air_quality' : 'weather'];
    const expiry = new Date(Math.floor(Date.now() / 1000) * 1000 + 1200000).toISOString();
    const result = (quality ? toAirQualityProviderForecast : toProviderForecast)(value,
      { variables: selected.variables, publicationExpires: expiry });
    result.delivery = { mode: 'core-cache', publisher_key: selected.core.publisherKey, name: selected.core.name,
      revision: 2, manifest_id: 'b'.repeat(64), sha256: 'd'.repeat(64), publication_expires_at: expiry,
      freshness: (quality ? airQualityFreshness : freshness)(value, result.freshness.checked_at, expiry),
      upstream_origin_attested: false, manifest_media_type_checked: false };
    return result;
  }
  return { root, staticRoot, cacheParent, config, data, start, calls, setPlan, provider };
}

test('new owner mode is exact and detached; legacy true remains open-only and false remains rejected', async t => {
  const f = await fixture(t), fixed = providerHttpConfiguration(f.config);
  assert.equal(fixed.core.cacheMode, 'create-or-open'); assert.equal(Object.hasOwn(fixed.core, 'reuseCache'), false);
  assert.notEqual(fixed.core, f.config.core);
  for (const change of [c => c.core.cacheMode = 'open-or-create', c => c.core.cacheMode = true,
    c => c.core.cacheMode = null, c => c.core.reuseCache = true, c => delete c.core.cacheMode,
    c => c.airQuality.core.cacheMode = 'repair', c => c.airQuality.core.reuseCache = false]) {
    const invalid = structuredClone(f.config); change(invalid);
    assert.throws(() => providerHttpConfiguration(invalid));
  }
  const old = structuredClone(f.config); delete old.core.cacheMode; old.core.reuseCache = true;
  assert.deepEqual(providerHttpConfiguration(old).core, old.core);
  const server = await f.start({ config: old });
  assert.equal((await get(server.origin)).status, 503);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [true]);
  await absent(old.core.cache);
  old.core.reuseCache = false;
  assert.throws(() => providerHttpConfiguration(old), error => error.code === 'BRIDGE_REUSABLE_CACHE_REQUIRED');
});

test('first actual GET creates through the default child, refresh and fresh server reopen both exact caches', async t => {
  const f = await fixture(t), server = await f.start();
  assert.deepEqual(await f.calls(), []); await absent(f.config.core.cache); await absent(f.config.airQuality.core.cache);
  for (const path of [WEATHER, AQ, WEATHER, AQ]) assert.equal((await get(server.origin, path)).status, 200);
  const before = await lstat(f.config.core.cache);
  await server.close();
  const restarted = await f.start();
  for (const path of [WEATHER, AQ]) assert.equal((await get(restarted.origin, path)).status, 200);
  assert.deepEqual((await f.calls()).map(({ kind, reuse }) => [kind, reuse]), [
    ['weather', false], ['air_quality', false], ['weather', true], ['air_quality', true], ['weather', true], ['air_quality', true] ]);
  assert.equal((await lstat(f.config.core.cache)).ino, before.ino);
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  assert.deepEqual((await f.calls()).map(call => call.cache), [f.config.core.cache, f.config.airQuality.core.cache,
    f.config.core.cache, f.config.airQuality.core.cache, f.config.core.cache, f.config.airQuality.core.cache]);
});

test('joined failure after synthetic core creation never retries; restart reopens retained cache', async t => {
  const f = await fixture(t); await f.setPlan({ weather: 'fail' });
  const server = await f.start(), failed = await get(server.origin);
  assert.deepEqual(failed, { status: 503, body: { error: 'FORECAST_UNAVAILABLE' } });
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false]);
  const before = await lstat(f.config.core.cache); await server.close(); await f.setPlan({});
  const restarted = await f.start(); assert.equal((await get(restarted.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true]);
  assert.equal((await lstat(f.config.core.cache)).ino, before.ino);
});

test('a failed attempt before core creation leaves the next GET free to request creation exactly once', async t => {
  const f = await fixture(t), held = join(f.root, 'held-executable');
  await rename(f.config.core.executable, held);
  const server = await f.start(); assert.equal((await get(server.origin)).status, 503);
  await absent(f.config.core.cache); assert.deepEqual(await f.calls(), []);
  await rename(held, f.config.core.executable);
  assert.equal((await get(server.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false]);
});

test('create/EEXIST race fails once without fallback; only a later GET can ask core to reopen', async t => {
  const f = await fixture(t); let first = true;
  const server = await f.start({}, { fetchProvider: async (core, options) => {
    if (first) {
      first = false; assert.equal(core.reuseCache, false);
      // A synthetic competing creator wins after the bridge's lstat but
      // before its genuine adapter launches the one owned test child.
      await mkdir(core.cache, { mode: 0o700 });
      await writeFile(join(core.cache, 'SYNTHETIC-NOT-A-CORE-CACHE'), 'synthetic-owned', { mode: 0o600 });
    }
    return fetchCachedProvider(core, options);
  } });
  assert.equal((await get(server.origin)).status, 503);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false]);
  assert.equal((await get(server.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true]);
});

test('timeout after cache creation joins the real child; next GET opens without deleting retained data', async t => {
  const f = await fixture(t); await f.setPlan({ weather: 'wait' });
  const server = await f.start({ requestDeadlineMs: 300 });
  assert.equal((await get(server.origin)).status, 503);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false]);
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  await f.setPlan({}); assert.equal((await get(server.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true]);
});

test('shutdown cancels and joins a real first-fetch child; a fresh bridge can reopen its cache', async t => {
  const f = await fixture(t); await f.setPlan({ weather: 'wait' });
  const server = await f.start();
  const pending = get(server.origin).catch(() => null);
  await until(async () => (await f.calls()).length === 1 && (await readdir(f.cacheParent)).includes('weather'));
  await server.close(); await pending;
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  await f.setPlan({}); const restarted = await f.start();
  assert.equal((await get(restarted.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true]);
});

test('disconnected first GET cancels its child without deleting cache; later GET reopens after joined scratch cleanup', async t => {
  const f = await fixture(t); await f.setPlan({ weather: 'wait' });
  const server = await f.start(), req = httpRequest(server.origin, { path: WEATHER });
  req.on('error', () => {}); req.end();
  await until(async () => (await f.calls()).length === 1 && (await readdir(f.cacheParent)).includes('weather'));
  req.destroy();
  await until(async () => !(await readdir(f.root)).some(name => name.startsWith('forecast-')));
  await f.setPlan({}); assert.equal((await get(server.origin)).status, 200);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true]);
});

test('explicitly shared weather/AQ cache still has one creator and independent fixed query bindings', async t => {
  const f = await fixture(t); f.config.airQuality.core.cache = f.config.core.cache;
  const server = await f.start();
  assert.equal((await get(server.origin, WEATHER)).status, 200);
  assert.equal((await get(server.origin, AQ)).status, 200);
  assert.deepEqual((await f.calls()).map(({ kind, reuse }) => [kind, reuse]), [['weather', false], ['air_quality', true]]);
  assert.deepEqual(await readdir(f.cacheParent), ['weather']);
});

test('existing foreign/incomplete synthetic caches are passed only to open and are never repaired or removed', async t => {
  const f = await fixture(t), cache = f.config.core.cache, marker = join(cache, 'SYNTHETIC-NOT-A-CORE-CACHE');
  await mkdir(cache, { mode: 0o700 });
  const server = await f.start();
  for (const value of ['synthetic-foreign', 'synthetic-incomplete']) {
    await writeFile(marker, value, { mode: 0o600 }); const before = await lstat(cache);
    assert.equal((await get(server.origin)).status, 503);
    assert.equal(await readFile(marker, 'utf8'), value); assert.equal((await lstat(cache)).ino, before.ino);
  }
  assert.deepEqual((await f.calls()).map(call => call.reuse), [true, true]);
});

test('failed creation leaving an incomplete cache stays failed on subsequent open, including restart', async t => {
  const f = await fixture(t); await f.setPlan({ weather: 'incomplete' });
  const server = await f.start(); assert.equal((await get(server.origin)).status, 503);
  await f.setPlan({}); assert.equal((await get(server.origin)).status, 503); await server.close();
  const restarted = await f.start(); assert.equal((await get(restarted.origin)).status, 503);
  assert.deepEqual((await f.calls()).map(call => call.reuse), [false, true, true]);
  assert.equal(await readFile(join(f.config.core.cache, 'SYNTHETIC-NOT-A-CORE-CACHE'), 'utf8'), 'synthetic-incomplete');
});

test('cache symlink or regular file is rejected before any core call and left intact', async t => {
  const f = await fixture(t), cache = f.config.core.cache;
  await symlink(f.staticRoot, cache); const server = await f.start();
  assert.equal((await get(server.origin)).status, 503); assert.equal((await lstat(cache)).isSymbolicLink(), true);
  await rm(cache); await writeFile(cache, 'private sentinel', { mode: 0o600 });
  assert.equal((await get(server.origin)).status, 503); assert.equal(await readFile(cache, 'utf8'), 'private sentinel');
  assert.deepEqual(await f.calls(), []);
});

test('missing, symlinked, writable and non-searchable parents never become implicit creation authority', async t => {
  const f = await fixture(t), cases = [];
  const alias = join(f.root, 'alias'); await symlink(f.cacheParent, alias);
  cases.push(join(f.root, 'absent-parent/cache'), join(alias, 'cache'));
  for (const cache of cases) {
    const config = structuredClone(f.config); config.core.cache = cache;
    const server = await f.start({ config }); assert.equal((await get(server.origin)).status, 503);
  }
  await chmod(f.cacheParent, 0o777);
  const server = await f.start(); assert.equal((await get(server.origin)).status, 503);
  await chmod(f.cacheParent, 0o600);
  if (process.getuid() !== 0) assert.equal((await get(server.origin)).status, 503);
  assert.deepEqual(await f.calls(), []); await absent(join(f.root, 'absent-parent'));
});

test('serialized admission spans create selection and abort/join, across weather and AQ', async t => {
  const f = await fixture(t); let enter, release, aborted, settled = false; const modes = [];
  const entered = new Promise(resolve => { enter = resolve; });
  const joined = new Promise(resolve => { release = resolve; });
  const server = await f.start({}, {
    fetchProvider: async (core, { signal }) => {
      modes.push(core.reuseCache); assert.equal(Object.hasOwn(core, 'cacheMode'), false);
      await mkdir(core.cache, { mode: 0o700 });
      signal.addEventListener('abort', () => { aborted = true; }, { once: true }); enter();
      await joined; settled = true; throw new WeatherError('CANCELLED');
    },
    fetchAirQualityProvider: async core => { modes.push(core.reuseCache); return f.provider(true); },
  });
  const req = httpRequest(server.origin, { path: WEATHER }); req.on('error', () => {}); req.end(); await entered;
  assert.equal((await get(server.origin, AQ)).status, 429); req.destroy(); await until(() => aborted);
  assert.equal((await get(server.origin, AQ)).status, 429); assert.equal(settled, false);
  release(); await until(() => settled); await delay(10);
  assert.equal((await get(server.origin, AQ)).status, 200); assert.deepEqual(modes, [false, false]);
});

test('unconfirmed cleanup is sticky and blocks both cache selectors and subsequent backend calls', async t => {
  const f = await fixture(t); let calls = 0;
  const server = await f.start({}, { fetchProvider: async core => {
    calls++; await mkdir(core.cache, { mode: 0o700 }); throw new WeatherError('CORE_CLEANUP_UNCONFIRMED');
  }, fetchAirQualityProvider: async () => { calls++; return f.provider(true); } });
  assert.equal((await get(server.origin)).status, 503);
  for (const path of [WEATHER, AQ]) assert.equal((await get(server.origin, path)).status, 503);
  assert.equal(calls, 1); await absent(f.config.airQuality.core.cache);
  await assert.rejects(server.close(), /BRIDGE_CLEANUP_UNCONFIRMED/);
});
