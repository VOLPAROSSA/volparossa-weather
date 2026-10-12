// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic inputs for inert preparation tests, not origin/overlay evidence.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { mkdtemp, mkdir, copyFile, writeFile, open, rm } from 'node:fs/promises';
import { join, resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { windForecast, QUERY } from '../../tests/fixtures.mjs';
import { precipitationForecast } from '../../tests/precipitation-fixtures.mjs';
import { aqForecast } from '../../tests/air-quality-fixtures.mjs';
import { canonical, prepareExpected, prepareExpectedV2, prepareExpectedV4, selectBundleVersion } from './prepare-core-browser.mjs';

const root = resolve(import.meta.dirname, '../..');
const work = await mkdtemp(join(root, 'build/drizzli-core-prepare-test-'));
after(() => rm(work, { recursive: true }));
const client = join(work, 'build/drizzli-volparossa/src/lib/services/volparossa');
await mkdir(client, { recursive: true, mode: 0o700 });
await copyFile(join(import.meta.dirname, 'overlay/src/lib/services/volparossa/client.mjs'), join(client, 'client.mjs'));
for (const name of ['provider', 'forecast', 'air-quality', 'air-quality-provider']) {
  await copyFile(join(root, `src/${name}.mjs`), join(client, `${name}.mjs`));
}
const { displayValue, displayAccumulationWindow } = await import(pathToFileURL(join(client, 'client.mjs')));
const sha = value => createHash('sha256').update(value).digest('hex');
const bytes = value => Buffer.from(JSON.stringify(value));

async function readExpected(path) {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await handle.stat();
    assert.equal(info.isFile(), true);
    assert.equal(info.mode & 0o777, 0o400);
    assert.equal(info.nlink, 1);
    return await handle.readFile();
  } finally { await handle.close(); }
}

function fixture() {
  const now = new Date().toISOString(), run = new Date(); run.setUTCHours(0, 0, 0, 0);
  const query = { ...QUERY, run: run.toISOString(), steps: [3, 9, 24], includeWind: true };
  const forecast = windForecast(query, now), raw = bytes(forecast);
  const config = { core: { mode: 'core-cache', executable: '/not-executed/volparossa',
    controlSocket: '/not-accessed/agent.sock', cache: '/not-accessed/owned-cache',
    scratchParent: '/not-accessed/scratch', publisherKey: 'a'.repeat(64), name: 'weather/test',
    minRevision: 1, query, reuseCache: true },
  variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation', 'air_quality'] };
  const receipt = { operation: 'named_content_download', publisher_key: config.core.publisherKey,
    name: config.core.name, revision: 1, manifest_id: 'b'.repeat(64), sha256: sha(raw), bytes: raw.length,
    cache: config.core.cache, local_output: '/not-accessed/cold.json', local_delivery: true, output_mode: '0600',
    ownership_changed: false, origin_authenticated: false, globally_latest: false, cache_only: false,
    peer_bytes: raw.length, providers_used: 1, origin_body_bytes: 0, origin_range_requests: 0,
    publication_expires_unix_seconds: Math.floor(Date.now() / 1000) + 600 };
  return { forecast, raw, config, receipt };
}

function productsFixture() {
  const current = fixture();
  current.config.core.query.includePrecipitation = true;
  current.forecast = precipitationForecast(current.config.core.query, new Date().toISOString(), { value: 0.00001234 });
  current.raw = bytes(current.forecast);
  Object.assign(current.receipt, { bytes: current.raw.length, peer_bytes: current.raw.length, sha256: sha(current.raw) });
  const run = new Date(Date.parse(current.config.core.query.run) - 6 * 3600000).toISOString();
  const query = { latitude: QUERY.latitude, longitude: QUERY.longitude, run, model: 'gefs-aerosols',
    steps: [3, 6, 12], communityArea: true };
  const forecast = aqForecast(query, new Date().toISOString()), raw = bytes(forecast);
  const core = { ...current.config.core, name: 'air-quality/test', cache: '/not-accessed/aq-cache', query };
  const receipt = { ...current.receipt, name: core.name, cache: core.cache, manifest_id: 'f'.repeat(64),
    sha256: sha(raw), bytes: raw.length, peer_bytes: raw.length, local_output: '/not-accessed/aq-cold.json',
    publication_expires_unix_seconds: current.receipt.publication_expires_unix_seconds - 100 };
  current.config.airQuality = { core, variables: ['pm2_5', 'pm10'] };
  return { ...current, aq: { forecast, raw, receipt } };
}

const prepareProducts = f => prepareExpectedV2(f.raw, bytes(f.receipt), f.aq.raw, bytes(f.aq.receipt),
  f.config, 'c'.repeat(64), displayValue, displayAccumulationWindow);

test('v4 is explicit and preserves the exact two-product cold-publication semantics', () => {
  const f = productsFixture();
  const expected = prepareExpectedV4(f.raw, bytes(f.receipt), f.aq.raw, bytes(f.aq.receipt),
    f.config, 'c'.repeat(64), displayValue, displayAccumulationWindow);
  assert.deepEqual(expected, { ...prepareProducts(f), schema: 4 });
  assert.equal(selectBundleVersion(undefined, false), 1);
  assert.equal(selectBundleVersion(undefined, true), 2);
  assert.equal(selectBundleVersion('1', false), 1);
  assert.equal(selectBundleVersion('2', true), 2);
  assert.equal(selectBundleVersion('4', true), 4);
  for (const [requested, products] of [['4', false], ['2', false], ['1', true], ['3', true],
    ['04', true], ['4.0', true], [4, true], ['4', 1]]) {
    assert.throws(() => selectBundleVersion(requested, products), /CORE_BROWSER_VERSION_INVALID/);
  }
  f.aq.receipt.origin_body_bytes = 1;
  assert.throws(() => prepareExpectedV4(f.raw, bytes(f.receipt), f.aq.raw, bytes(f.aq.receipt),
    f.config, 'c'.repeat(64), displayValue, displayAccumulationWindow));
});

test('v2 binds two cold publications and actual UI precision, accumulation windows and independent native timelines', () => {
  const f = productsFixture(), result = prepareProducts(f);
  assert.equal(result.schema, 2);
  assert.deepEqual(Object.keys(result.products), ['weather', 'air_quality']);
  const { weather, air_quality: aq } = result.products;
  assert.equal(weather.publication.sha256, sha(f.raw));
  assert.equal(aq.publication.sha256, sha(f.aq.raw));
  assert.deepEqual(aq.display.values, [['Not available', '11.5959'], ['0', 'Not available'], ['5.53071', '0']]);
  assert.equal(weather.display.values[0][3], '0.01234');
  assert.equal(weather.display.values[0][4], f.forecast.samples[0].precipitation.start_at + ' → '
    + f.forecast.samples[0].precipitation.end_at);
  assert.notEqual(aq.display.model_run, weather.display.model_run);
  assert.notDeepEqual(aq.display.native, weather.display.native);
  assert.notEqual(aq.display.expires_at, weather.display.expires_at);
  assert.equal(aq.display.attribution, 'NOAA/NWS GEFS-Aerosols');
  assert.equal(aq.display.license, 'LicenseRef-NOAA-NODD');
  assert.equal(result.display_sha256, sha(canonical({ weather: weather.display, air_quality: aq.display })));
  assert.throws(() => prepareExpected(f.raw, bytes(f.receipt), f.config, 'c'.repeat(64), displayValue));
});

test('v2 rejects cross-product receipt/query substitutions, missing precipitation, shared cache and extra authority', () => {
  for (const change of [f => { f.aq.receipt = f.receipt; }, f => { f.aq.receipt.origin_body_bytes = 1; },
    f => { f.aq.receipt.publication_expires_unix_seconds = 1; },
    f => { f.config.airQuality.core.query.run = f.config.core.query.run; },
    f => { f.config.airQuality.core.query.steps = [3, 9, 24]; },
    f => { f.config.airQuality.core.query.latitude = 1; },
    f => { f.config.airQuality.variables.push('aqi'); }, f => { f.config.core.query.includePrecipitation = false; },
    f => { f.config.airQuality.core.cache = f.config.core.cache; },
    f => { f.config.airQuality.core.controlSocket = '/not-accessed/other.sock'; },
    f => { f.config.airQuality.core.executable = '/not-executed/other'; },
    f => { f.config.airQuality.core.scratchParent = '/not-accessed/other'; }]) {
    const f = productsFixture(); change(f);
    assert.throws(() => prepareProducts(f));
  }
});

test('expected native DOM values derive from the actual client formatter and cold receipt', () => {
  const { raw, config, receipt, forecast } = fixture();
  const value = prepareExpected(raw, bytes(receipt), config, 'c'.repeat(64), displayValue);
  assert.deepEqual(value.forecast, forecast);
  assert.deepEqual(value.display.native, forecast.samples.map(sample => sample.valid_at));
  assert.deepEqual(value.display.values, Array(3).fill(['10.0', '5.0', '216.9']));
  assert.equal(value.display.coordinates, '52.52° latitude, 13.41° longitude');
  assert.equal(value.display.expires_at, new Date(receipt.publication_expires_unix_seconds * 1000).toISOString());
  assert.equal(value.display_sha256, sha(canonical(value.display)));
  assert.equal(value.cold_receipt_sha256, sha(bytes(receipt)));
  assert.equal(canonical({ z: '° ·', a: [2, 1] }), '{"a":[2,1],"z":"° ·"}');
});

test('wrong publication, cache, byte hash, origin substitution and warm-only receipts fail closed', () => {
  for (const mutate of [
    value => { value.publisher_key = 'd'.repeat(64); }, value => { value.sha256 = 'd'.repeat(64); },
    value => { value.bytes += 1; }, value => { value.revision = 0; }, value => { value.cache += '/other'; },
    value => { value.peer_bytes = 0; }, value => { value.providers_used = 0; },
    value => { value.origin_body_bytes = 1; }, value => { value.origin_range_requests = 1; },
    value => { value.cache_only = true; }, value => { value.origin_authenticated = true; },
    value => { value.publication_expires_unix_seconds = 1; },
  ]) {
    const { raw, config, receipt } = fixture(); mutate(receipt);
    assert.throws(() => prepareExpected(raw, bytes(receipt), config, 'c'.repeat(64), displayValue));
  }
});

test('mismatched location, run, native steps and non-reusable cache are refused', () => {
  for (const mutate of [
    value => { value.query.latitude = 1; }, value => { value.query.steps = [24]; },
    value => { value.query.run = '2020-01-01T00:00:00.000Z'; }, value => { value.reuseCache = false; },
  ]) {
    const { raw, config, receipt } = fixture(); mutate(config.core);
    assert.throws(() => prepareExpected(raw, bytes(receipt), config, 'c'.repeat(64), displayValue));
  }
});

test('CLI binds local_output, private modes and exclusive destination without executing core', async () => {
  for (const name of ['integrations/drizzli/prepare-core-browser.mjs',
    ...['provider-http', 'provider-core', 'core-cache', 'provider', 'forecast',
      'air-quality', 'air-quality-provider', 'air-quality-core'].map(name => `src/${name}.mjs`)]) {
    const target = join(work, name); await mkdir(dirname(target), { recursive: true, mode: 0o700 });
    await copyFile(join(root, name), target);
  }
  const input = join(work, 'cold.json'), receiptPath = join(work, 'receipt.json'), configPath = join(work, 'config.json');
  const output = join(work, 'expected.json'), { raw, receipt, config } = fixture();
  const args = [join(work, 'integrations/drizzli/prepare-core-browser.mjs'), '--forecast', input,
    '--receipt', receiptPath, '--config', configPath, '--core-sha256', 'c'.repeat(64), '--output', output];
  await writeFile(input, raw, { mode: 0o600 }); await writeFile(configPath, bytes(config), { mode: 0o600 });
  const invoke = () => spawnSync(process.execPath, args, { encoding: 'utf8', timeout: 10000,
    env: { LANG: 'C.UTF-8' }, maxBuffer: 4096 });
  await writeFile(receiptPath, bytes(receipt), { mode: 0o600 });
  let result = invoke();
  assert.equal(result.status, 1);
  assert.equal(result.stderr, '{"error":"CORE_BROWSER_PREPARATION_FAILED"}\n');
  receipt.local_output = input; await writeFile(receiptPath, bytes(receipt), { mode: 0o600 });
  result = invoke(); assert.equal(result.status, 0, result.stderr);
  const saved = await readExpected(output), response = JSON.parse(result.stdout);
  assert.equal(response.expected_sha256, sha(saved));
  assert.equal(response.prepared, true);
  assert.equal(JSON.parse(saved).publication.sha256, sha(raw));
  result = invoke(); assert.equal(result.status, 1); // Never replace an earlier expected publication.
  assert.deepEqual(await readExpected(output), saved);
});

for (const version of [2, 4]) test(`v${version} CLI requires both AQ inputs, binds both local outputs and keeps products separate`, async () => {
  for (const name of ['integrations/drizzli/prepare-core-browser.mjs',
    ...['provider-http', 'provider-core', 'core-cache', 'provider', 'forecast',
      'air-quality', 'air-quality-provider', 'air-quality-core'].map(name => `src/${name}.mjs`)]) {
    const target = join(work, name); await mkdir(dirname(target), { recursive: true, mode: 0o700 });
    await copyFile(join(root, name), target);
  }
  const f = productsFixture(), input = join(work, `weather-v${version}.json`), aq = join(work, `aq-v${version}.json`);
  const receipt = join(work, `receipt-v${version}.json`), aqReceipt = join(work, `aq-receipt-v${version}.json`);
  const config = join(work, `config-v${version}.json`), output = join(work, `expected-v${version}.json`);
  f.receipt.local_output = input;
  await writeFile(input, f.raw, { mode: 0o600 }); await writeFile(aq, f.aq.raw, { mode: 0o600 });
  await writeFile(receipt, bytes(f.receipt), { mode: 0o600 });
  await writeFile(aqReceipt, bytes(f.aq.receipt), { mode: 0o600 });
  await writeFile(config, bytes(f.config), { mode: 0o600 });
  const args = [join(work, 'integrations/drizzli/prepare-core-browser.mjs'), '--forecast', input,
    '--receipt', receipt, '--config', config, '--core-sha256', 'c'.repeat(64), '--output', output,
    ...(version === 4 ? ['--bundle-version', '4'] : [])];
  const invoke = more => spawnSync(process.execPath, [...args, ...more], { encoding: 'utf8', timeout: 10000,
    env: { LANG: 'C.UTF-8' }, maxBuffer: 4096 });
  assert.equal(invoke(['--air-quality', aq]).status, 1);
  assert.equal(invoke(['--air-quality-receipt', aqReceipt]).status, 1);
  assert.equal(invoke(['--air-quality', aq, '--air-quality-receipt', aqReceipt]).status, 1);
  f.aq.receipt.local_output = aq;
  await writeFile(aqReceipt, bytes(f.aq.receipt), { mode: 0o600 });
  const result = invoke(['--air-quality', aq, '--air-quality-receipt', aqReceipt]);
  assert.equal(result.status, 0, result.stderr);
  const saved = JSON.parse((await readExpected(output)).toString('utf8'));
  assert.equal(saved.schema, version);
  assert.equal(saved.products.weather.publication.sha256, sha(f.raw));
  assert.equal(saved.products.air_quality.publication.sha256, sha(f.aq.raw));
  assert.equal(invoke(['--air-quality', aq, '--air-quality-receipt', aqReceipt]).status, 1);
});
