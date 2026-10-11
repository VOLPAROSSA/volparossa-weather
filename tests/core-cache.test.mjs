// SPDX-License-Identifier: GPL-3.0-only
// Real subprocess/UDS/file lifecycle with a synthetic CLI fixture, NOT a real overlay proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { once } from 'node:events';
import fsPromises, { mkdtemp, chmod, writeFile, readdir, rm } from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fetchCachedForecast } from '../src/core-cache.mjs';
import { fetchCachedProvider } from '../src/provider-core.mjs';
import { MAX_AGE_SECONDS, validateForecast } from '../src/forecast.mjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { forecast, windForecast, NOW, QUERY } from './fixtures.mjs';
import { precipitationForecast } from './precipitation-fixture.mjs';

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

test('cache consumption accepts wind only for the explicitly requested field set', async t => {
  const data = windForecast({ ...query, includeWind: true }, new Date().toISOString());
  const { options } = await fixture(t, { forecast: data });
  const result = await fetchCachedForecast({ ...options, query: { ...query, includeWind: true } });
  assert.equal(result.forecast.samples[0].wind_10m.speed, 5);
  await assert.rejects(fetchCachedForecast(options), error => error.code === 'FORECAST_QUERY_MISMATCH');
  const temperature = await fixture(t);
  await assert.rejects(fetchCachedForecast({ ...temperature.options, query: { ...query, includeWind: true } }),
    error => error.code === 'FORECAST_QUERY_MISMATCH');
});

test('precipitation cache consumption binds the exact field set and preserves accumulated amounts', async t => {
  const now = new Date().toISOString();
  const data = precipitationForecast(query, now);
  const { root, options } = await fixture(t, { forecast: data });
  const selected = { ...options, query: { ...query, includePrecipitation: true } };
  const result = await fetchCachedProvider(selected, { variables: ['precipitation'] });
  assert.equal(result.series[0].statistic, 'accumulation');
  assert.deepEqual(result.series[0].values, [1]);
  assert.deepEqual(result.forecast.samples[0].precipitation, data.samples[0].precipitation);
  await assert.rejects(fetchCachedForecast(options), error => error.code === 'FORECAST_QUERY_MISMATCH');
  const temperature = await fixture(t);
  await assert.rejects(fetchCachedForecast({ ...temperature.options, query: selected.query }),
    error => error.code === 'FORECAST_QUERY_MISMATCH');
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

function staleForecast(data) {
  // One clock sample: a later expiry read could exceed the maximum validity by
  // even one millisecond and test malformed input instead of a stale forecast.
  const now = Date.now(), old = structuredClone(data);
  old.source.acquired_at = new Date(now - 3600000).toISOString();
  old.freshness.expires_at = new Date(now - 1800000).toISOString();
  // Choose an older run too, so this stays valid if the test crosses a run boundary.
  old.source.model_run_at = new Date(Date.parse(data.source.model_run_at) - 21600000).toISOString();
  for (const sample of old.samples) {
    sample.valid_at = new Date(Date.parse(old.source.model_run_at) + sample.lead_hours * 3600000).toISOString();
  }
  return old;
}

test('stale fixture stays structurally valid when the wall clock advances between reads', t => {
  const data = forecast(QUERY, NOW);
  let reads = 0;
  const clock = t.mock.method(Date, 'now', () => Date.parse(NOW) + reads++);
  let old;
  try { old = staleForecast(data); } finally { clock.mock.restore(); }
  assert.equal(reads, 1);
  assert.equal(Date.parse(old.freshness.expires_at) - Date.parse(old.source.acquired_at), MAX_AGE_SECONDS * 1000);
  assert.strictEqual(validateForecast(old), old);
  assert.ok(Date.parse(old.freshness.expires_at) < Date.parse(NOW));
  const overlong = structuredClone(old);
  overlong.freshness.expires_at = new Date(Date.parse(old.freshness.expires_at) + 1).toISOString();
  assert.throws(() => validateForecast(overlong), error => error.code === 'EXPIRY_INVALID');
});

test('stale public forecast remains stale despite newly signed publication and fresh retrieval', async t => {
  const base = await fixture(t);
  const old = staleForecast(base.data);
  const { root, options } = await fixture(t, { forecast: old });
  await assert.rejects(fetchCachedForecast({ ...options, query: { ...query, run: old.source.model_run_at } }), error => error.code === 'STALE_FORECAST');
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
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

test('unconfirmed process cleanup survives a second scratch error; ordinary scratch errors are not swallowed', async t => {
  for (const processUnconfirmed of [true, false]) {
    const { root, options } = await fixture(t, { badHash: !processUnconfirmed });
    let cleanupCalls = 0;
    const scratchError = Object.assign(new Error('PRIVATE_SYNTHETIC_SCRATCH_FAILURE'), { code: 'EACCES' });
    const rmMock = t.mock.method(fsPromises, 'rm', async (path, removal) => {
      assert.ok(path.startsWith(join(root, 'forecast-')));
      assert.deepEqual(removal, { recursive: true, force: false });
      cleanupCalls++; throw scratchError;
    });
    // The real synthetic child has already exited before groupExists runs.
    // Simulate a still-visible group without leaving or signaling descendants.
    const groups = new Set();
    const killMock = processUnconfirmed ? t.mock.method(process, 'kill', (pid, signal) => {
      assert.ok(Number.isInteger(pid) && pid < 0);
      assert.ok([0, 'SIGTERM', 'SIGKILL'].includes(signal));
      groups.add(pid); return true;
    }) : null;
    syncBuiltinESMExports();
    try {
      await assert.rejects(fetchCachedForecast(options), error => processUnconfirmed
        ? error.code === 'CORE_CLEANUP_UNCONFIRMED' : error === scratchError);
      assert.equal(cleanupCalls, 1, 'owned scratch cleanup is still attempted');
      assert.equal(groups.size, processUnconfirmed ? 1 : 0);
    } finally {
      rmMock.mock.restore(); killMock?.mock.restore(); syncBuiltinESMExports();
    }
  }
});

test('provider wrapper uses actual core-cache process checks and retains publisher limits and expiry', async t => {
  const { root, data, options } = await fixture(t);
  const result = await fetchCachedProvider(options, { variables: ['temperature_2m', 'precipitation'] });
  assert.equal(result.schema, 'volparossa.weather.provider.v1');
  assert.deepEqual(result.forecast, data);
  assert.equal(result.delivery.publisher_key, options.publisherKey);
  assert.equal(result.delivery.name, options.name);
  assert.equal(result.delivery.upstream_origin_attested, false);
  assert.equal(result.delivery.manifest_media_type_checked, false);
  assert.equal(result.freshness.expires_at, result.delivery.publication_expires_at);
  assert.equal(result.series[1].reason, 'field_not_in_forecast');
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
});

test('provider wrapper never projects failed receipts or bypasses cancellation', async t => {
  await assert.rejects(fetchCachedProvider(null, { variables: [] }), error => error.code === 'PROVIDER_VARIABLES_INVALID');
  for (const bad of [{ badHash: true }, { receipt: { publisher_key: 'f'.repeat(64) } },
    { receipt: { publication_expires_unix_seconds: 1 } }]) {
    const { root, options } = await fixture(t, bad);
    await assert.rejects(fetchCachedProvider(options));
    assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
  }
  const { root, options } = await fixture(t, { hang: true });
  const controller = new AbortController();
  const operation = fetchCachedProvider(options, { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(), 100);
  try { await assert.rejects(operation, error => error.code === 'CANCELLED'); }
  finally { clearTimeout(timer); }
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
});

test('real CLI provider execute joins synthetic core subprocess; legacy execute envelope unchanged', async t => {
  const { root, options } = await fixture(t);
  const script = fileURLToPath(new URL('../scripts/forecast.mjs', import.meta.url));
  const args = [script, 'core-cache', '--latitude', String(query.latitude), '--longitude', String(query.longitude),
    '--run', query.run, '--model', query.model, '--steps', query.steps.join(','), '--community-area',
    '--executable', options.executable, '--control-socket', options.controlSocket, '--cache', options.cache,
    '--scratch-parent', options.scratchParent, '--publisher-key', options.publisherKey, '--name', options.name,
    '--min-revision', String(options.minRevision), '--execute'];
  const run = promisify(execFile);
  const legacy = JSON.parse((await run(process.execPath, args)).stdout);
  assert.deepEqual(Object.keys(legacy).sort(), ['delivery', 'forecast']);
  const actual = await run(process.execPath, [...args, '--output-contract', 'provider', '--variables', 'temperature_2m,aqi']);
  assert.equal(actual.stderr, '');
  const provider = JSON.parse(actual.stdout);
  assert.equal(provider.schema, 'volparossa.weather.provider.v1');
  assert.deepEqual(provider.forecast, legacy.forecast);
  assert.equal(provider.series[1].availability, 'unavailable');
  assert.equal(provider.delivery.upstream_origin_attested, false);
  assert.deepEqual((await readdir(root)).sort(), ['control.sock', 'fake-core']);
});
