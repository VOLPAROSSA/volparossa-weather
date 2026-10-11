// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic inputs for inert preparation tests, not origin/overlay evidence.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, copyFile, writeFile, readFile, stat, rm } from 'node:fs/promises';
import { join, resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { windForecast, QUERY } from '../../tests/fixtures.mjs';
import { canonical, prepareExpected } from './prepare-core-browser.mjs';

const root = resolve(import.meta.dirname, '../..');
const work = await mkdtemp(join(root, 'build/drizzli-core-prepare-test-'));
after(() => rm(work, { recursive: true }));
const client = join(work, 'build/drizzli-volparossa/src/lib/services/volparossa');
await mkdir(client, { recursive: true, mode: 0o700 });
await copyFile(join(import.meta.dirname, 'overlay/src/lib/services/volparossa/client.mjs'), join(client, 'client.mjs'));
for (const name of ['provider', 'forecast']) await copyFile(join(root, `src/${name}.mjs`), join(client, `${name}.mjs`));
const { displayValue } = await import(pathToFileURL(join(client, 'client.mjs')));
const sha = value => createHash('sha256').update(value).digest('hex');
const bytes = value => Buffer.from(JSON.stringify(value));

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
    ...['provider-http', 'provider-core', 'core-cache', 'provider', 'forecast'].map(name => `src/${name}.mjs`)]) {
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
  assert.equal((await stat(output)).mode & 0o777, 0o400);
  const saved = await readFile(output), response = JSON.parse(result.stdout);
  assert.equal(response.expected_sha256, sha(saved));
  assert.equal(response.prepared, true);
  assert.equal(JSON.parse(saved).publication.sha256, sha(raw));
  result = invoke(); assert.equal(result.status, 1); // Never replace an earlier expected publication.
  assert.deepEqual(await readFile(output), saved);
});
