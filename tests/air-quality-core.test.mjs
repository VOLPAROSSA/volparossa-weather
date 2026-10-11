// SPDX-License-Identifier: GPL-3.0-only
// Actual subprocess/socket/file boundaries with synthetic CLI data, NOT overlay proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { mkdtemp, mkdir, chmod, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { fetchCachedAirQuality } from '../src/air-quality-core.mjs';
import { fetchCachedForecast } from '../src/core-cache.mjs';
import { AQ_MAX_BYTES } from '../src/air-quality.mjs';
import { aqForecast, AQ_QUERY } from './air-quality-fixtures.mjs';
import { forecast as weatherForecast } from './fixtures.mjs';

const query = { ...AQ_QUERY, steps: [3, 9, 24],
  run: new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString() };

async function fixture(t, { data = aqForecast(query, new Date().toISOString()), receipt = {},
  badHash = false, badMode = false, hang = false, huge = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'weather-aq-core-'));
  await chmod(root, 0o700);
  const socket = join(root, 'control.sock'), cache = join(root, 'agent-cache');
  await mkdir(cache, { mode: 0o700 });
  await writeFile(join(cache, 'retained'), 'agent-owned cache remains', { mode: 0o600, flag: 'wx' });
  const server = createServer(); server.listen(socket); await once(server, 'listening');
  t.after(async () => { server.close(); await rm(root, { recursive: true, force: true }); });
  const calls = join(root, 'calls');
  const executable = join(root, 'fake-core');
  const source = `#!${process.execPath}
const fs = require('node:fs'), crypto = require('node:crypto');
const args = process.argv.slice(2), read = key => args[args.indexOf(key)+1];
if (args[2] !== 'content' || args[3] !== 'fetch-name' || args.includes('--cache-only')
    || read('--quota-bytes') !== '${AQ_MAX_BYTES}' || read('--max-entries') !== '16'
    || read('--min-free-bytes') !== '67108864' || read('--cache') !== ${JSON.stringify(cache)}) process.exit(9);
fs.appendFileSync(${JSON.stringify(calls)}, args.includes('--reuse-cache') ? 'reuse\\n' : 'create\\n', {mode:0o600});
if (${hang}) { setInterval(() => {}, 1000); }
else if (${huge}) { process.stdout.write('x'.repeat(20000)); }
else {
 const bytes = Buffer.from(JSON.stringify(${JSON.stringify(data)})), output = read('--local-output');
 fs.writeFileSync(output, bytes, {mode:0o600, flag:'wx'});
 if (${badMode}) fs.chmodSync(output, 0o644);
 const result = {operation:'named_content_download',publisher_key:read('--publisher-key'),name:read('--name'),revision:2,
 manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
 sha256:${badHash}?'f'.repeat(64):crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,
 local_delivery:true,output_mode:'0600',ownership_changed:false,origin_authenticated:false,globally_latest:false,
 local_output:output,cache:read('--cache'),cache_only:false,...${JSON.stringify(receipt)}};
 process.stderr.write('private diagnostic canary: never expose this');
 process.stdout.write(JSON.stringify(result));
}`;
  await writeFile(executable, source, { mode: 0o700 });
  return { root, calls, data, options: { mode: 'core-cache', executable, controlSocket: socket, cache,
    scratchParent: root, publisherKey: 'c'.repeat(64), name: 'weather.public-area.particulates', minRevision: 2, query } };
}

async function cleaned(root) {
  assert.ok((await readdir(root)).every(name => ['agent-cache', 'calls', 'control.sock', 'fake-core'].includes(name)));
  assert.equal(await readFile(join(root, 'agent-cache', 'retained'), 'utf8'), 'agent-owned cache remains');
}

test('AQ core wrapper preserves exact native points, null/zero and source; receipt limits remain explicit', async t => {
  const data = aqForecast(query, new Date().toISOString());
  data.samples[0].pm2_5 = null; data.samples[0].pm10 = 0;
  data.samples[1].pm2_5 = 0; data.samples[1].pm10 = 0.01;
  const { root, calls, options } = await fixture(t, { data });
  const result = await fetchCachedAirQuality(options);
  assert.deepEqual(Object.keys(result).sort(), ['delivery', 'forecast']);
  assert.deepEqual(result.forecast, data);
  assert.deepEqual(result.forecast.samples.map(sample => sample.lead_hours), [3, 9, 24]);
  assert.equal(result.delivery.mode, 'core-cache');
  assert.equal(result.delivery.publisher_key, options.publisherKey);
  assert.equal(result.delivery.name, options.name);
  assert.equal(result.delivery.revision, 2);
  assert.equal(result.delivery.upstream_origin_attested, false);
  assert.equal(result.delivery.manifest_media_type_checked, false);
  assert.equal(result.delivery.freshness.expires_at, result.delivery.publication_expires_at);
  assert.equal(await readFile(calls, 'utf8'), 'create\n');
  await cleaned(root);
});

test('repeated explicit reuse passes the same agent cache without recreating or consuming it', async t => {
  const { root, calls, options } = await fixture(t);
  const first = await fetchCachedAirQuality({ ...options, reuseCache: true });
  const second = await fetchCachedAirQuality({ ...options, reuseCache: true });
  assert.deepEqual(second.forecast, first.forecast);
  assert.equal(await readFile(calls, 'utf8'), 'reuse\nreuse\n');
  await cleaned(root);
});

test('AQ retrieval binds exact public area, initialization and native requested lead times', async t => {
  const { root, calls, options } = await fixture(t);
  for (const changed of [{ latitude: 1 }, { longitude: 1 }, { steps: [3] },
    { run: new Date(Date.parse(query.run) - 21600000).toISOString() }]) {
    await assert.rejects(fetchCachedAirQuality({ ...options, query: { ...query, ...changed } }),
      error => error.code === 'AQ_QUERY_MISMATCH');
    await cleaned(root);
  }
  assert.equal((await readFile(calls, 'utf8')).trim().split('\n').length, 4);
});

test('private requests, non-AQ models and wrong mode are refused before invoking core', async t => {
  const { root, calls, options } = await fixture(t);
  for (const [changed, code] of [
    [{ query: { ...query, communityArea: false } }, 'PUBLIC_COMMUNITY_AREA_REQUIRED'],
    [{ query: { ...query, model: 'ifs' } }, 'AQ_MODEL_UNSUPPORTED'],
    [{ mode: 'origin' }, 'CORE_MODE_REQUIRED'], [{ reuseCache: 'true' }, 'REUSE_INVALID'],
    [{ publisherKey: 'bad' }, 'PUBLISHER_INVALID'], [{ minRevision: 0 }, 'REVISION_INVALID'],
  ]) await assert.rejects(fetchCachedAirQuality({ ...options, ...changed }), error => error.code === code);
  await assert.rejects(readFile(calls), error => error.code === 'ENOENT');
  await chmod(root, 0o755);
  await assert.rejects(fetchCachedAirQuality(options), error => error.code === 'PRIVATE_PARENT_REQUIRED');
  await chmod(root, 0o700);
  await cleaned(root);
});

test('AQ and ECMWF are separate products; private bodies and fabricated AQI never cross the cache boundary', async t => {
  const weather = weatherForecast({ ...query, model: 'ifs' }, new Date().toISOString());
  const wrong = await fixture(t, { data: weather });
  await assert.rejects(fetchCachedAirQuality(wrong.options), error => error.code === 'SCHEMA_INVALID');
  const aq = await fixture(t);
  await assert.rejects(fetchCachedForecast({ ...aq.options, query: { ...query, model: 'ifs' } }),
    error => error.code === 'SCHEMA_INVALID');
  const privateData = structuredClone(aq.data); privateData.area.sharing = 'private';
  const privateBody = await fixture(t, { data: privateData });
  await assert.rejects(fetchCachedAirQuality(privateBody.options), error => error.code === 'AQ_QUERY_MISMATCH');
  const aqi = await fixture(t, { data: { ...aq.data, aqi: 0 } });
  await assert.rejects(fetchCachedAirQuality(aqi.options), error => error.code === 'AQ_FORECAST_INVALID');
  for (const value of [wrong, aq, privateBody, aqi]) await cleaned(value.root);
});

test('every core receipt authority/output claim remains enforced for AQ without fallback or diagnostics', async t => {
  const receipts = [
    { operation: 'other' }, { publisher_key: 'd'.repeat(64) }, { name: 'other' }, { revision: 1 },
    { manifest_id: 'invalid' }, { bytes: AQ_MAX_BYTES + 1 }, { publication_expires_unix_seconds: 0 },
    { local_delivery: false }, { output_mode: '0644' }, { ownership_changed: true },
    { origin_authenticated: true }, { globally_latest: true }, { cache_only: true },
    { local_output: '/private/diagnostic-canary' }, { cache: '/private/diagnostic-canary' },
  ];
  for (const receipt of receipts) {
    const { root, calls, options } = await fixture(t, { receipt });
    await assert.rejects(fetchCachedAirQuality(options), error => error.code === 'CORE_RECEIPT_INVALID'
      && error.message === 'CORE_RECEIPT_INVALID');
    assert.equal(await readFile(calls, 'utf8'), 'create\n');
    await cleaned(root);
  }
  for (const [mutation, code] of [[{ badHash: true }, 'CORE_HASH_MISMATCH'], [{ badMode: true }, 'OUTPUT_INVALID']]) {
    const { root, options } = await fixture(t, mutation);
    await assert.rejects(fetchCachedAirQuality(options), error => error.code === code && error.message === code);
    await cleaned(root);
  }
});

test('fresh publication and retrieval cannot reset expired AQ acquisition or publication', async t => {
  const oldQuery = { ...query, run: new Date(Date.parse(query.run) - 21600000).toISOString() };
  const data = aqForecast(oldQuery, new Date(Date.now() - 3600000).toISOString());
  const old = await fixture(t, { data });
  await assert.rejects(fetchCachedAirQuality({ ...old.options, query: oldQuery }), error => error.code === 'STALE_FORECAST');
  const expired = await fixture(t, { receipt: { publication_expires_unix_seconds: 1 } });
  await assert.rejects(fetchCachedAirQuality(expired.options), error => error.code === 'STALE_FORECAST');
  await cleaned(old.root); await cleaned(expired.root);
});

test('AQ abort and oversized CLI reports still join own child and remove only owned scratch', async t => {
  const { root, options } = await fixture(t, { hang: true });
  const controller = new AbortController();
  const pending = fetchCachedAirQuality(options, { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(), 100);
  try { await assert.rejects(pending, error => error.code === 'CANCELLED'); }
  finally { clearTimeout(timer); }
  await cleaned(root);
  const oversized = await fixture(t, { huge: true });
  await assert.rejects(fetchCachedAirQuality(oversized.options), error => error.code === 'CORE_REPORT_TOO_LARGE');
  await cleaned(oversized.root);
});

test('actual AQ core-cache CLI execute joins fixed adapter and retains closed errors with no fallback', async t => {
  const script = fileURLToPath(new URL('../scripts/air-quality.mjs', import.meta.url));
  const run = promisify(execFile);
  for (const bad of [false, true]) {
    const { root, calls, data, options } = await fixture(t, { receipt: bad ? { publisher_key: 'd'.repeat(64) } : {} });
    const args = [script, 'core-cache', '--latitude', String(query.latitude), '--longitude', String(query.longitude),
      '--run', query.run, '--steps', query.steps.join(','), '--community-area', '--execute', '--reuse-cache',
      '--executable', options.executable, '--control-socket', options.controlSocket, '--cache', options.cache,
      '--scratch-parent', options.scratchParent, '--publisher-key', options.publisherKey, '--name', options.name,
      '--min-revision', String(options.minRevision)];
    if (bad) {
      await assert.rejects(run(process.execPath, args, { timeout: 5000, maxBuffer: 32768 }), error =>
        error.code === 1 && error.stdout === ''
        && error.stderr === '{"error":"CORE_RECEIPT_INVALID"}\n');
    } else {
      const output = await run(process.execPath, args, { timeout: 5000, maxBuffer: 32768 });
      assert.equal(output.stderr, '');
      const result = JSON.parse(output.stdout);
      assert.deepEqual(Object.keys(result).sort(), ['delivery', 'forecast']);
      assert.deepEqual(result.forecast, data);
      assert.equal(result.delivery.publisher_key, options.publisherKey);
      assert.equal(result.delivery.upstream_origin_attested, false);
    }
    assert.equal(await readFile(calls, 'utf8'), 'reuse\n');
    await cleaned(root);
  }
});
