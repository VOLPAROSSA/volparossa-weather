// SPDX-License-Identifier: GPL-3.0-only
// Real subprocess/UDS/file lifecycle with a synthetic CLI fixture, NOT a real overlay proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { mkdtemp, chmod, writeFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fetchCachedForecast } from '../src/core-cache.mjs';
import { forecast, QUERY } from './fixtures.mjs';

const query = { ...QUERY, run: new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString() };

async function fixture(t, { receipt = {}, forecast: suppliedForecast = null, hang = false, badHash = false, huge = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'weather-'));
  await chmod(root, 0o700);
  const socket = join(root, 'control.sock');
  const server = createServer(); server.listen(socket); await once(server, 'listening');
  t.after(async () => { server.close(); await rm(root, { recursive: true, force: true }); });
  const now = new Date().toISOString();
  const data = suppliedForecast ?? forecast(query, now);
  const executable = join(root, 'fake-core');
  const source = `#!${process.execPath}
const fs = require('node:fs'), crypto = require('node:crypto');
const args = process.argv.slice(2), read = key => args[args.indexOf(key)+1];
if (args[2] !== 'content' || args[3] !== 'fetch-name' || args.includes('--cache-only')) process.exit(9);
if (${hang}) { setInterval(() => {}, 1000); } else if (${huge}) { process.stdout.write('x'.repeat(20000)); }
else {
 const bytes = Buffer.from(JSON.stringify(${JSON.stringify(data)})), output = read('--local-output');
 fs.writeFileSync(output, bytes, {mode: 0o600, flag: 'wx'});
 const result = {operation:'named_content_download',publisher_key:read('--publisher-key'),name:read('--name'),revision:2,
 manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
 sha256:${badHash}?'f'.repeat(64):crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,
 local_delivery:true,output_mode:'0600',ownership_changed:false,origin_authenticated:false,globally_latest:false,
 local_output:output,cache:read('--cache'),cache_only:false,...${JSON.stringify(receipt)}};
 process.stdout.write(JSON.stringify(result));
}`;
  await writeFile(executable, source, { mode: 0o700 });
  return { root, data, options: { mode: 'core-cache', executable, controlSocket: socket,
    cache: join(root, 'agent-cache'), scratchParent: root, publisherKey: 'c'.repeat(64),
    name: 'weather.berlin.hourly', minRevision: 2, query } };
}

test('real subprocess contract checks trusted receipt/hash/query and retains original age; temporary output cleaned', async t => {
  const { root, data, options } = await fixture(t);
  const result = await fetchCachedForecast(options);
  assert.equal(result.forecast.source.acquired_at, data.source.acquired_at);
  assert.equal(result.delivery.mode, 'core-cache');
  assert.equal(result.delivery.upstream_origin_attested, false);
  assert.equal(result.delivery.manifest_media_type_checked, false);
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
});

test('wrong signer/name/revision/expiry/hash/type never becomes a forecast or origin retry', async t => {
  for (const bad of [{ receipt: { publisher_key: 'd'.repeat(64) } }, { receipt: { name: 'other' } },
    { receipt: { revision: 1 } }, { receipt: { bytes: 999999 } }, { receipt: { local_delivery: false } },
    { receipt: { publication_expires_unix_seconds: 1 } }, { badHash: true },
    { forecast: { schema: 'other', kind: 'forecast' } }]) {
    const { root, options } = await fixture(t, bad);
    await assert.rejects(fetchCachedForecast(options));
    assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
  }
});

test('stale public forecast remains stale despite newly signed publication and fresh retrieval', async t => {
  const base = await fixture(t);
  const old = structuredClone(base.data);
  old.source.acquired_at = new Date(Date.now() - 3600000).toISOString();
  old.freshness.expires_at = new Date(Date.now() - 1800000).toISOString();
  // Choose an older run too, so this stays valid if the test crosses a run boundary.
  old.source.model_run_at = new Date(Date.parse(query.run) - 21600000).toISOString();
  old.samples[0].valid_at = new Date(Date.parse(old.source.model_run_at) + old.samples[0].lead_hours * 3600000).toISOString();
  const { options } = await fixture(t, { forecast: old });
  await assert.rejects(fetchCachedForecast({ ...options, query: { ...query, run: old.source.model_run_at } }), error => error.code === 'STALE_FORECAST');
});

test('location publicity/query binding is explicit and private work directory is enforced', async t => {
  const { root, options } = await fixture(t);
  await assert.rejects(fetchCachedForecast({ ...options, query: { ...query, communityArea: false } }),
    error => error.code === 'PUBLIC_COMMUNITY_AREA_REQUIRED');
  await assert.rejects(fetchCachedForecast({ ...options, query: { ...query, latitude: 1 } }),
    error => error.code === 'FORECAST_QUERY_MISMATCH');
  await chmod(root, 0o755);
  await assert.rejects(fetchCachedForecast(options), error => error.code === 'PRIVATE_PARENT_REQUIRED');
});

test('cancellation joins CLI process and removes only own temporary output; oversized receipt fails', async t => {
  const { root, options } = await fixture(t, { hang: true });
  const controller = new AbortController();
  const operation = fetchCachedForecast(options, { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(), 100);
  try { await assert.rejects(operation, error => error.code === 'CANCELLED'); }
  finally { clearTimeout(timer); }
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
  const oversized = await fixture(t, { huge: true });
  await assert.rejects(fetchCachedForecast(oversized.options), error => error.code === 'CORE_REPORT_TOO_LARGE');
});
