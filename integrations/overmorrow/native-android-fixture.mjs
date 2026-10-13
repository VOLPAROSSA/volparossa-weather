// SPDX-License-Identifier: GPL-3.0-only
// Synthetic-only public fixture. The emulator receives ONLY API_PORT via adb
// reverse; CONTROL_PORT belongs to the external observer, never the app.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { lstat, mkdir, readFile, readlink, realpath, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { startProviderHttp } from '../../src/provider-http.mjs';
import { tableProducts } from './table-fixture.mjs';
import { responseProduct } from './browser-fixture.mjs';
import { fixtureAirQualityQuery } from '../drizzli/browser-fixture.mjs';

export const API_PORT = 43210, CONTROL_PORT = 43211;
export const PHASES = Object.freeze(['initial', 'refresh', 'short-lived']);

export function nativeFixtureState(now = new Date().toISOString()) {
  const { base, query } = tableProducts(now);
  let phase = null, prepared;
  const calls = { weather: 0, air_quality: 0 }, products = { weather: null, air_quality: null };
  return {
    base, query,
    setPhase(next, at = new Date().toISOString()) {
      assert.ok(PHASES.includes(next));
      assert.equal(PHASES.indexOf(next), PHASES.indexOf(phase) + 1, 'fixture phase order');
      assert.deepEqual(calls, { weather: PHASES.indexOf(next), air_quality: PHASES.indexOf(next) });
      // Reserve this one preparation even if acquisition fails. Neither a GET
      // nor a retry may recreate products, backdate acquisition or extend TTL.
      phase = next;
      prepared = null;
      const pair = {};
      for (const quality of [false, true]) {
        const name = quality ? 'air_quality' : 'weather';
        const mode = phase === 'short-lived' ? 'short-lived' : phase === 'refresh' && !quality ? 'missing' : 'valid';
        pair[name] = JSON.stringify(responseProduct(base, quality, mode, at));
      }
      prepared = pair;
      for (const name of Object.keys(products)) products[name] = JSON.parse(prepared[name]);
    },
    product(quality) {
      const name = quality ? 'air_quality' : 'weather';
      assert.ok(prepared && calls[name] === PHASES.indexOf(phase), 'one prepared response per phase');
      calls[name] += 1;
      // A private serialized pair is immutable even if a caller changes its
      // returned object. Request counters still count only actual API requests.
      return JSON.parse(prepared[name]);
    },
    status() { return structuredClone({ schema: 2, phase, calls, products,
      synthetic_weather: true, synthetic_air_quality: true, core_executed: false, overlay_proven: false }); },
  };
}

async function main() {
  assert.equal(process.argv.length, 4); assert.equal(process.argv[2], '--work');
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  const work = resolve(process.argv[3]);
  assert.equal(await realpath(work), work);
  const info = await lstat(work);
  assert.ok(info.isDirectory() && info.uid === process.getuid() && !(info.mode & 0o077));
  const staticRoot = `${work}/native-fixture-static`;
  await mkdir(staticRoot, { mode: 0o700 });
  await writeFile(`${staticRoot}/index.html`, '<!doctype html><title>Synthetic Android trial</title>', { flag: 'wx', mode: 0o600 });
  const state = nativeFixtureState();
  const query = state.query;
  const core = { mode: 'core-cache', executable: `${work}/unused-core`, controlSocket: `${work}/unused.sock`,
    cache: `${work}/unused-cache`, scratchParent: work, publisherKey: '1'.repeat(64),
    name: 'synthetic-browser-forecast', minRevision: 1, query, reuseCache: true };
  const config = { core, variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m',
    'precipitation', 'air_quality'], airQuality: {
    core: { ...core, name: 'synthetic-browser-air-quality', query: {
      ...fixtureAirQualityQuery(query), steps: [3, 6, 12, 24, 48] } },
    variables: ['pm2_5', 'pm10'] } };
  let api, control, stopping;
  async function stop() {
    if (!stopping) stopping = (async () => {
      process.stdin.destroy();
      if (control) await new Promise((done, reject) => {
        control.close(error => error ? reject(error) : done()); control.closeAllConnections();
      });
      if (api) await api.close();
    })();
    return stopping;
  }
  const fail = () => { process.exitCode = 1; void stop().catch(() => {}); };
  try {
    api = await startProviderHttp({ config, staticRoot, port: API_PORT, requestDeadlineMs: 5000 }, {
      fetchProvider: async () => state.product(false), fetchAirQualityProvider: async () => state.product(true) });
    control = createServer({ maxHeaderSize: 2048, requestTimeout: 2000, headersTimeout: 2000,
      keepAliveTimeout: 1 }, (request, response) => {
      try {
        assert.equal(request.socket.remoteAddress, '127.0.0.1');
        assert.equal(request.headers.host, `127.0.0.1:${CONTROL_PORT}`);
        assert.equal(request.headers['transfer-encoding'], undefined);
        assert.ok(request.headers['content-length'] === undefined || request.headers['content-length'] === '0');
        if (request.method === 'POST') {
          assert.ok(PHASES.map(phase => `/phase/${phase}`).includes(request.url));
          state.setPhase(request.url.slice('/phase/'.length));
        } else { assert.equal(request.method, 'GET'); assert.equal(request.url, '/state'); }
        const body = JSON.stringify(state.status()); assert.ok(Buffer.byteLength(body) <= 65536);
        response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
          Connection: 'close', 'Content-Length': Buffer.byteLength(body) }); response.end(body);
      } catch {
        response.writeHead(400, { Connection: 'close' }); response.end('invalid fixture operation');
      }
    });
    await new Promise((done, reject) => { control.once('error', reject); control.listen(CONTROL_PORT, '127.0.0.1', done); });
    process.once('SIGTERM', () => void stop().catch(fail));
    process.once('SIGINT', () => void stop().catch(fail));
    process.stdin.on('data', fail); process.stdin.once('end', () => void stop().catch(fail)); process.stdin.resume();
    process.stdout.write(JSON.stringify({ ready: true, api_port: API_PORT, control_port: CONTROL_PORT,
      synthetic_weather: true, synthetic_air_quality: true, core_executed: false }) + '\n');
  } catch { await stop(); throw new Error('native fixture start failed'); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('native synthetic fixture failed\n'); process.exitCode = 1; });
}
