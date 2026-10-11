// SPDX-License-Identifier: GPL-3.0-only
// Synthetic receipt/forecast binding tests, never real acquisition evidence.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, writeFile, open, rm, chmod } from 'node:fs/promises';
import { constants } from 'node:fs';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { precipitationForecast } from '../../tests/precipitation-fixtures.mjs';
import { aqForecast } from '../../tests/air-quality-fixtures.mjs';
import { prepareExpected, canonical } from './prepare_core_browser.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const bytes = value => Buffer.from(JSON.stringify(value));

function fixture() {
  const now = new Date().toISOString(), run = new Date(); run.setUTCHours(0, 0, 0, 0);
  const query = { latitude: 52.52, longitude: 13.41, model: 'ifs', run: run.toISOString(),
    steps: [3, 9, 24, 48], communityArea: true, includeWind: true, includePrecipitation: true };
  const forecast = precipitationForecast(query, now, { value: 0.00001234 });
  forecast.samples[1].temperature_2m = null;
  Object.assign(forecast.samples[1].wind_10m, { eastward: 0, northward: 0, speed: 0, direction_from: null, status: 'calm' });
  Object.assign(forecast.samples[2].precipitation, { amount: null, source_value: null });
  const aqQuery = { latitude: 52.52, longitude: 13.41, model: 'gefs-aerosols',
    run: new Date(run.getTime() - 12 * 3600000).toISOString(), steps: [3, 6, 12, 24, 48], communityArea: true };
  const aq = aqForecast(aqQuery, now);
  const config = { core: { mode: 'core-cache', executable: '/inert/core', controlSocket: '/inert/agent.sock',
    cache: '/inert/weather-cache', scratchParent: '/inert/scratch', publisherKey: 'a'.repeat(64), name: 'weather/test',
    minRevision: 1, query, reuseCache: true },
  variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation'] };
  config.airQuality = { core: { ...config.core, cache: '/inert/aq-cache', name: 'aq/test', query: aqQuery },
    variables: ['pm2_5', 'pm10'] };
  function receipt(raw, quality) {
    const core = quality ? config.airQuality.core : config.core;
    return { operation: 'named_content_download', publisher_key: core.publisherKey, name: core.name,
      revision: 1, manifest_id: (quality ? 'b' : 'c').repeat(64), sha256: sha(raw), bytes: raw.length,
      cache: core.cache, local_output: quality ? '/inert/aq.json' : '/inert/weather.json', local_delivery: true,
      output_mode: '0600', ownership_changed: false, origin_authenticated: false, globally_latest: false,
      cache_only: false, peer_bytes: raw.length, providers_used: 1, origin_body_bytes: 0, origin_range_requests: 0,
      publication_expires_unix_seconds: Math.floor(Date.now() / 1000) + (quality ? 500 : 600) };
  }
  const raw = bytes(forecast), aqRaw = bytes(aq);
  return { config, forecast, aq, raw, aqRaw, receipt: receipt(raw, false), aqReceipt: receipt(aqRaw, true) };
}

const prepare = f => prepareExpected(f.raw, bytes(f.receipt), f.aqRaw, bytes(f.aqReceipt), f.config, 'd'.repeat(64));

if (process.argv.includes('--fixture')) {
  // Bounded cross-language fixture for Python's exact verifier tests.
  const f = fixture(); process.stdout.write(JSON.stringify({ expected: prepare(f), config: f.config }) + '\n');
} else {
  test('v3 binds full precision, missing/calm/zero cells, four/five native points and both source terms', () => {
    const f = fixture(), value = prepare(f), { weather, air_quality: aq } = value.products;
    assert.equal(value.schema, 3);
    assert.deepEqual(weather.display.values[0].slice(0, 4), ['10', '5', String(f.forecast.samples[0].wind_10m.direction_from), '0.01234']);
    assert.ok(weather.display.values[0][2].length > 10); // Not Drizzli's single-decimal display.
    assert.deepEqual(weather.display.values[1].slice(0, 3), ['Not available', '0', 'Not available']);
    assert.equal(weather.display.values[2][3], 'Not available');
    assert.deepEqual(aq.display.values[0], ['Not available', '11.5959']);
    assert.deepEqual(aq.display.values[1], ['0', 'Not available']);
    assert.equal(weather.display.native.length, 4); assert.equal(aq.display.native.length, 5);
    assert.notEqual(weather.display.model_run, aq.display.model_run);
    assert.notEqual(weather.display.expires_at, aq.display.expires_at);
    for (const [product, forecast, receipt, raw] of [[weather, f.forecast, f.receipt, f.raw], [aq, f.aq, f.aqReceipt, f.aqRaw]]) {
      assert.equal(product.publication.sha256, sha(raw));
      assert.equal(product.cold_receipt_sha256, sha(bytes(receipt)));
      assert.equal(product.display.acquired_at, forecast.source.acquired_at);
      assert.equal(product.display.coordinates, 'Public community area: 52.52, 13.41');
      for (const key of ['attribution', 'license', 'license_url', 'changes']) assert.equal(product.display[key], forecast.source[key]);
      assert.equal(product.display_sha256, sha(canonical(product.display)));
    }
    assert.equal(value.display_sha256, sha(canonical({ weather: weather.display, air_quality: aq.display })));
  });

  test('cross-product, origin, cache, body, timeline and authority substitutions fail', () => {
    for (const change of [f => { f.aqReceipt = f.receipt; }, f => { f.aqReceipt.origin_body_bytes = 1; },
      f => { f.receipt.cache_only = true; }, f => { f.receipt.peer_bytes = 0; },
      f => { f.receipt.sha256 = 'e'.repeat(64); }, f => { f.aqReceipt.bytes++; },
      f => { f.aqReceipt.publication_expires_unix_seconds = 1; },
      f => { f.config.airQuality.core.query.steps = [3, 6]; },
      f => { f.config.airQuality.core.query.latitude = 20; },
      f => { f.config.airQuality.core.cache = f.config.core.cache; },
      f => { f.config.airQuality.core.controlSocket = '/inert/other'; },
      f => { f.config.core.query.includePrecipitation = false; }]) {
      const f = fixture(); change(f); assert.throws(() => prepare(f));
    }
  });

  test('CLI requires both private cold outputs, preserves source bytes and exclusively creates read-only expected', async () => {
    const build = resolve(import.meta.dirname, '../../build');
    await mkdir(build, { recursive: true, mode: 0o700 });
    const work = await mkdtemp(join(build, 'overmorrow-core-prepare-test-'));
    try {
      const f = fixture();
      const input = join(work, 'weather.json'), aq = join(work, 'aq.json'), receipt = join(work, 'receipt.json');
      const aqReceipt = join(work, 'aq-receipt.json'), config = join(work, 'config.json'), output = join(work, 'expected.json');
      await writeFile(input, f.raw, { mode: 0o600 }); await writeFile(aq, f.aqRaw, { mode: 0o600 });
      await writeFile(config, bytes(f.config), { mode: 0o600 });
      f.receipt.local_output = input;
      await writeFile(receipt, bytes(f.receipt), { mode: 0o600 });
      await writeFile(aqReceipt, bytes(f.aqReceipt), { mode: 0o600 });
      const args = [join(import.meta.dirname, 'prepare_core_browser.mjs'), '--forecast', input, '--receipt', receipt,
        '--config', config, '--core-sha256', 'd'.repeat(64), '--output', output];
      const invoke = extra => spawnSync(process.execPath, [...args, ...extra], {
        encoding: 'utf8', timeout: 10000, env: { LANG: 'C.UTF-8' }, maxBuffer: 4096 });
      assert.equal(invoke([]).status, 1);
      assert.equal(invoke(['--air-quality', aq]).status, 1);
      const more = ['--air-quality', aq, '--air-quality-receipt', aqReceipt];
      assert.equal(invoke(more).status, 1);
      f.aqReceipt.local_output = aq; await writeFile(aqReceipt, bytes(f.aqReceipt), { mode: 0o600 });
      await chmod(aq, 0o644); assert.equal(invoke(more).status, 1); await chmod(aq, 0o600);
      const result = invoke(more); assert.equal(result.status, 0, result.stderr);
      const handle = await open(output, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try {
        assert.equal((await handle.stat()).mode & 0o777, 0o400);
        const saved = await handle.readFile();
        assert.equal(JSON.parse(result.stdout).expected_sha256, sha(saved));
        assert.equal(JSON.parse(saved).schema, 3);
        assert.equal(invoke(more).status, 1);
      } finally { await handle.close(); }
    } finally { await rm(work, { recursive: true }); }
  });
}
