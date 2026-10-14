// SPDX-License-Identifier: GPL-3.0-only
// Real Linux Unix-domain HTTP, synthetic products/core children. This is not
// proof of a real protected core transfer, upstream data, or Android execution.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { createServer, createConnection } from 'node:net';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, chmod, writeFile, readFile, readdir, rm, lstat, symlink, rename, open } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startProviderHttp } from '../src/provider-http.mjs';
import { toProviderForecast } from '../src/provider.mjs';
import { toAirQualityProviderForecast } from '../src/air-quality-provider.mjs';
import { request, freshness, WeatherError } from '../src/forecast.mjs';
import { airQualityRequest, airQualityFreshness } from '../src/air-quality.mjs';
import { forecast } from './fixtures.mjs';
import { aqForecast } from './air-quality-fixtures.mjs';
import { startLiveFixture } from '../integrations/overmorrow/native-android-live-fixture.mjs';

const ORIGIN = 'http://127.0.0.1:43210', HOST = '127.0.0.1:43210';
const WEATHER = '/api/volparossa/forecast', AQ = '/api/volparossa/air-quality';
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
async function absent(path) {
  await assert.rejects(lstat(path), error => error.code === 'ENOENT');
}
function get(socketPath, path = WEATHER, options = {}) {
  return new Promise((resolve, reject) => {
    const req = httpRequest({ socketPath, path, method: 'GET', ...options,
      headers: { Host: HOST, Origin: ORIGIN, ...options.headers } }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.once('error', reject);
      response.once('end', () => resolve({ status: response.statusCode, headers: response.headers,
        body: JSON.parse(Buffer.concat(chunks).toString()) }));
    });
    req.once('error', reject); req.end();
  });
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'w-unix-'));
  await chmod(root, 0o700);
  const parent = join(root, 'socket'); await mkdir(parent, { mode: 0o700 });
  const socketPath = join(parent, 'api.sock');
  const run = new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString();
  const core = { mode: 'core-cache', executable: join(root, 'synthetic-core'),
    controlSocket: join(root, 'control.sock'), cache: join(root, 'weather-cache'), scratchParent: root,
    publisherKey: 'c'.repeat(64), name: 'synthetic.weather', minRevision: 2, reuseCache: true,
    query: request({ latitude: 52.52, longitude: 13.41, run, steps: [12], communityArea: true }) };
  const config = { core, variables: ['temperature_2m'], airQuality: {
    core: { ...core, cache: join(root, 'aq-cache'), name: 'synthetic.air-quality',
      query: airQualityRequest({ latitude: 52.52, longitude: 13.41, run, steps: [3, 9, 24], communityArea: true }) },
    variables: ['pm2_5', 'pm10'] } };
  const servers = [];
  t.after(async () => {
    for (const server of servers) await server.close().catch(() => {});
    await rm(root, { recursive: true, force: true });
  });
  function provider(quality = false) {
    const selected = quality ? config.airQuality : config, now = new Date().toISOString();
    const value = (quality ? aqForecast : forecast)(selected.core.query, now);
    const expiry = new Date(Math.floor(Date.now() / 1000) * 1000 + 1200000).toISOString();
    return { ...(quality ? toAirQualityProviderForecast : toProviderForecast)(value,
      { variables: selected.variables, now, publicationExpires: expiry }), delivery: {
      mode: 'core-cache', publisher_key: selected.core.publisherKey, name: selected.core.name,
      revision: 2, manifest_id: 'b'.repeat(64), sha256: 'd'.repeat(64), publication_expires_at: expiry,
      freshness: (quality ? airQualityFreshness : freshness)(value, now, expiry),
      upstream_origin_attested: false, manifest_media_type_checked: false } };
  }
  async function start(options = {}, injected = {}) {
    const server = await startProviderHttp({ config, socketPath, ...options }, {
      fetchProvider: async () => provider(), fetchAirQualityProvider: async () => provider(true), ...injected });
    servers.push(server); return server;
  }
  return { root, parent, socketPath, config, provider, start };
}

test('Unix API-only listener delivers exact weather/AQ at one fixed origin and removes only its socket', async t => {
  const f = await fixture(t), expected = [f.provider(), f.provider(true)], calls = [];
  const server = await f.start({}, {
    fetchProvider: async (core, { signal }) => { calls.push(core); assert.equal(signal.aborted, false); return expected[0]; },
    fetchAirQualityProvider: async core => { calls.push(core); return expected[1]; },
  });
  assert.equal(server.origin, ORIGIN); assert.equal(server.socketPath, f.socketPath);
  const stat = await lstat(f.socketPath);
  assert.equal(stat.isSocket(), true); assert.equal(stat.mode & 0o7777, 0o600);
  assert.equal(stat.uid, process.getuid()); assert.equal(stat.nlink, 1);
  assert.deepEqual(await readdir(f.parent), ['api.sock']);
  for (const [path, value] of [[WEATHER, expected[0]], [AQ, expected[1]]]) {
    const result = await get(f.socketPath, path);
    assert.equal(result.status, 200); assert.deepEqual(result.body, value);
    assert.equal(result.headers['cache-control'], 'no-store');
    assert.equal(result.headers['access-control-allow-origin'], undefined);
  }
  assert.deepEqual(calls, [f.config.core, f.config.airQuality.core]);
  await server.close(); await server.close();
  assert.deepEqual(await readdir(f.parent), []);
});

test('live HTTP doorway composes with the production Unix bridge without response rewriting or early backend requests', async t => {
  const f = await fixture(t), expected = { weather: f.provider(), air_quality: f.provider(true) }, calls = [];
  const server = await f.start({}, {
    fetchProvider: async core => { calls.push(['weather', core]); return expected.weather; },
    fetchAirQualityProvider: async core => { calls.push(['air_quality', core]); return expected.air_quality; },
  });
  const doorway = await startLiveFixture({ upstreamSocket: f.socketPath, apiPort: 0, controlPort: 0 });
  t.after(() => doorway.close());
  assert.deepEqual(calls, []);
  assert.deepEqual(doorway.status().completed, { weather: 0, air_quality: 0 });
  for (let attempt = 0; attempt < 3; attempt++) {
    for (const [path, kind] of [[WEATHER, 'weather'], [AQ, 'air_quality']]) {
      const reply = await fetch(`http://127.0.0.1:${doorway.apiPort}${path}`);
      assert.equal(reply.status, 200);
      assert.equal(await reply.text(), JSON.stringify(expected[kind]));
    }
  }
  const status = doorway.status();
  assert.deepEqual(status.products, expected);
  assert.deepEqual(status.completed, { weather: 3, air_quality: 3 });
  assert.deepEqual(status.calls, status.completed);
  assert.equal(status.active, false); assert.equal(status.terminal_failure, null);
  assert.equal(status.core_executed, false); assert.equal(status.overlay_proven, false);
  assert.deepEqual(calls, Array.from({ length: 3 }, () => [
    ['weather', f.config.core], ['air_quality', f.config.airQuality.core],
  ]).flat());
  await doorway.close(); await server.close();
  await absent(f.socketPath); assert.deepEqual(await readdir(f.parent), []);
});

test('Unix requests cannot select origins, assets, bodies, methods, query parameters or backend authority', async t => {
  const f = await fixture(t); let calls = 0;
  await f.start({}, { fetchProvider: async () => { calls++; return f.provider(); } });
  for (const [path, options, status] of [
    ['/', {}, 404], ['/index.html', {}, 404], ['/assets/private', {}, 404],
    [WEATHER, { method: 'POST' }, 405], [WEATHER, { headers: { Host: 'localhost:43210' } }, 403],
    [WEATHER, { headers: { Host: '127.0.0.1:43211' } }, 403],
    [WEATHER, { headers: { Origin: 'https://127.0.0.1:43210' } }, 403],
    [WEATHER, { headers: { 'Sec-Fetch-Site': 'cross-site' } }, 403],
    [WEATHER, { headers: { 'Content-Length': '1' } }, 400],
    [`${WEATHER}?latitude=1`, {}, 400], ['/bad%zz', {}, 400], ['/%2e%2e/private', {}, 400],
  ]) {
    const result = await get(f.socketPath, path, options);
    assert.equal(result.status, status); assert.deepEqual(Object.keys(result.body), ['error']);
    assert.equal(JSON.stringify(result.body).includes(f.root), false);
  }
  const raw = createConnection(f.socketPath), received = [];
  raw.on('data', chunk => received.push(chunk));
  const ended = once(raw, 'close');
  raw.end(`GET ${WEATHER} HTTP/1.1\r\nHost: ${HOST}\r\nHost: ${HOST}\r\nConnection: close\r\n\r\n`);
  await ended;
  assert.match(Buffer.concat(received).toString(), /403 Forbidden/);
  assert.equal(calls, 0);
});

test('Unix selection is exclusive and path validation uses bounded canonical UTF-8 bytes', async t => {
  const f = await fixture(t);
  for (const options of [{ port: 0 }, { port: 43210 }, { staticRoot: f.root },
    { staticProfile: 'flutter-canvaskit' }, { socketPath: null }, { socketPath: true },
    { socketPath: 'relative.sock' }, { socketPath: `${f.parent}/../api.sock` },
    { socketPath: `${f.parent}/nul\0.sock` }, { socketPath: `${f.parent}/${'é'.repeat(55)}` },
    { socketPath: `/${'s'.repeat(104)}` }]) await assert.rejects(f.start(options));
  assert.deepEqual(await readdir(f.parent), []);
});

test('Unix parent must already be canonical same-owner 0700 and is not created or chmodded', async t => {
  const f = await fixture(t), missing = join(f.root, 'missing');
  await assert.rejects(f.start({ socketPath: join(missing, 'api.sock') })); await absent(missing);
  const alias = join(f.root, 'alias'); await symlink(f.parent, alias);
  await assert.rejects(f.start({ socketPath: join(alias, 'api.sock') }));
  for (const mode of [0o750, 0o770, 0o777, 0o1700]) {
    await chmod(f.parent, mode); await assert.rejects(f.start());
    assert.equal((await lstat(f.parent)).mode & 0o7777, mode);
  }
  await chmod(f.parent, 0o700); assert.deepEqual(await readdir(f.parent), []);
});

test('existing regular files, dangling symlinks and live sockets are rejected unchanged without adoption', async t => {
  for (const kind of ['file', 'symlink', 'socket']) {
    const f = await fixture(t); let existing;
    if (kind === 'file') await writeFile(f.socketPath, 'do not overwrite', { mode: 0o600, flag: 'wx' });
    if (kind === 'symlink') await symlink(join(f.root, 'missing-target'), f.socketPath);
    if (kind === 'socket') {
      existing = createServer(); existing.listen(f.socketPath); await once(existing, 'listening');
    }
    const before = await lstat(f.socketPath);
    await assert.rejects(f.start(), error => error.code === 'BRIDGE_SOCKET_EXISTS');
    const after = await lstat(f.socketPath);
    assert.equal(after.ino, before.ino); assert.equal(after.mode, before.mode);
    assert.deepEqual(await readdir(f.parent), ['api.sock']);
    if (existing) await new Promise(done => existing.close(done));
  }
});

test('concurrent startup publishes exactly one socket without overwrite or staged-directory leaks', async t => {
  const f = await fixture(t), results = await Promise.allSettled([f.start(), f.start()]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.filter(result => result.status === 'rejected').length, 1);
  assert.deepEqual(await readdir(f.parent), ['api.sock']);
  assert.equal((await get(f.socketPath)).status, 200);
});

test('close preserves replacement file, symlink and socket rather than libuv unlinking an unrelated pathname', async t => {
  for (const kind of ['file', 'symlink', 'socket']) {
    const f = await fixture(t), server = await f.start(), old = join(f.parent, 'moved-owned.sock');
    await rename(f.socketPath, old);
    let replacement, replacementFile;
    if (kind === 'file') {
      replacementFile = await open(f.socketPath, 'wx+', 0o600);
      t.after(() => replacementFile.close());
      await replacementFile.writeFile('replacement remains');
    }
    if (kind === 'symlink') await symlink(join(f.root, 'unrelated'), f.socketPath);
    if (kind === 'socket') {
      replacement = createServer(); replacement.listen(f.socketPath); await once(replacement, 'listening');
    }
    const before = await lstat(f.socketPath);
    await assert.rejects(server.close(), /BRIDGE_SOCKET_CLEANUP_UNCONFIRMED/);
    const after = await lstat(f.socketPath); assert.equal(after.ino, before.ino); assert.equal(after.mode, before.mode);
    if (kind === 'file') {
      const opened = await replacementFile.stat();
      assert.equal(opened.isFile(), true); assert.equal(opened.dev, before.dev); assert.equal(opened.ino, before.ino);
      const bytes = Buffer.alloc(64);
      const { bytesRead } = await replacementFile.read(bytes, 0, bytes.length, 0);
      assert.equal(bytes.subarray(0, bytesRead).toString('utf8'), 'replacement remains');
    }
    assert.equal((await lstat(old)).isSocket(), true);
    if (replacement) await new Promise(done => replacement.close(done));
  }
});

test('pinned parent cleanup cannot remove a replacement-parent entry and reports changed ownership scope', async t => {
  const f = await fixture(t), server = await f.start(), moved = join(f.root, 'moved-parent');
  await rename(f.parent, moved); await mkdir(f.parent, { mode: 0o700 });
  await writeFile(f.socketPath, 'unrelated new parent', { mode: 0o600, flag: 'wx' });
  await assert.rejects(server.close(), /BRIDGE_SOCKET_CLEANUP_UNCONFIRMED/);
  assert.equal(await readFile(f.socketPath, 'utf8'), 'unrelated new parent');
  assert.deepEqual(await readdir(moved), []);
});

test('Unix disconnect aborts one owned operation and keeps both API admissions busy through joined cleanup', async t => {
  const f = await fixture(t), entered = deferred(), aborted = deferred(), release = deferred();
  let weatherCalls = 0, aqCalls = 0;
  t.after(release.resolve);
  await f.start({}, {
    fetchProvider: async (_core, { signal }) => {
      weatherCalls++; entered.resolve();
      await new Promise(done => signal.addEventListener('abort', done, { once: true }));
      aborted.resolve(); await release.promise; throw new Error('PRIVATE_CANCELLED');
    },
    fetchAirQualityProvider: async () => { aqCalls++; return f.provider(true); },
  });
  const req = httpRequest({ socketPath: f.socketPath, path: WEATHER, headers: { Host: HOST } });
  req.on('error', () => {}); req.end(); await entered.promise;
  req.destroy(); await aborted.promise;
  for (const path of [AQ, WEATHER]) {
    const busy = await get(f.socketPath, path); assert.equal(busy.status, 429);
    assert.equal(busy.headers['retry-after'], '1');
  }
  assert.equal(weatherCalls, 1); assert.equal(aqCalls, 0);
  release.resolve(); await new Promise(done => setImmediate(done));
  assert.equal((await get(f.socketPath, AQ)).status, 200); assert.equal(aqCalls, 1);
});

test('Unix shutdown joins aborted backend cleanup and sticky cleanup uncertainty never becomes success', async t => {
  const f = await fixture(t), entered = deferred(), aborted = deferred(), release = deferred();
  t.after(release.resolve);
  const server = await f.start({}, { fetchProvider: async (_core, { signal }) => {
    entered.resolve(); await new Promise(done => signal.addEventListener('abort', done, { once: true }));
    aborted.resolve(); await release.promise; throw new Error('cancelled');
  } });
  const pending = get(f.socketPath).catch(() => null); await entered.promise;
  let closed = false; const stopping = server.close().then(() => { closed = true; });
  await aborted.promise; assert.equal(closed, false); release.resolve();
  await stopping; await pending; assert.deepEqual(await readdir(f.parent), []);
  const next = await f.start({}, { fetchProvider: async () => { throw new WeatherError('CORE_CLEANUP_UNCONFIRMED'); } });
  assert.equal((await get(f.socketPath)).status, 503);
  assert.equal((await get(f.socketPath, AQ)).status, 503);
  await assert.rejects(next.close(), /BRIDGE_CLEANUP_UNCONFIRMED/); await absent(f.socketPath);
});

test('Unix cache-mode selection still performs one create-or-open decision per actual API GET', async t => {
  const f = await fixture(t), config = structuredClone(f.config), choices = [];
  for (const core of [config.core, config.airQuality.core]) { delete core.reuseCache; core.cacheMode = 'create-or-open'; }
  await f.start({ config }, { fetchProvider: async core => {
    choices.push(core.reuseCache);
    if (!core.reuseCache) await mkdir(core.cache, { mode: 0o700 });
    return f.provider();
  } });
  assert.deepEqual(choices, []); await absent(config.core.cache);
  assert.equal((await get(f.socketPath)).status, 200);
  assert.equal((await get(f.socketPath)).status, 200);
  assert.deepEqual(choices, [false, true]);
});

test('Unix deadline reaches the actual synthetic core child and joins owned scratch cleanup', async t => {
  const f = await fixture(t), control = createServer();
  control.listen(f.config.core.controlSocket); await once(control, 'listening');
  t.after(() => new Promise(done => control.close(done)));
  await writeFile(f.config.core.executable, `#!${process.execPath}\nsetInterval(() => {}, 1000);\n`, { mode: 0o700, flag: 'wx' });
  const server = await startProviderHttp({ config: f.config, socketPath: f.socketPath, requestDeadlineMs: 150 });
  t.after(() => server.close());
  assert.equal((await get(f.socketPath)).status, 503);
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  await server.close(); await absent(f.socketPath);
});

async function startCli(t, f, extra = [], mask) {
  const configPath = join(f.root, 'bridge.json');
  await writeFile(configPath, JSON.stringify(f.config), { mode: 0o600, flag: 'wx' });
  const script = new URL('../scripts/serve-provider.mjs', import.meta.url);
  const args = [fileURLToPath(script), '--config', configPath, '--socket', f.socketPath, ...extra];
  const child = spawn(process.execPath, mask === undefined ? args : ['--input-type=module', '-e',
    `process.umask(${mask});process.argv=${JSON.stringify([process.execPath, ...args])};await import(${JSON.stringify(script.href)});`],
  { stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  const ready = deferred();
  child.stdout.on('data', bytes => { stdout += bytes; if (stdout.includes('\n')) ready.resolve(); });
  child.stderr.on('data', bytes => { stderr += bytes; });
  const exited = once(child, 'exit');
  const timer = setTimeout(() => { child.kill('SIGKILL'); }, 5000);
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
    await exited; clearTimeout(timer); });
  return { child, ready: Promise.race([ready.promise, exited]), exited,
    output: () => ({ stdout, stderr }) };
}

test('explicit CLI socket starts without static root, advertises only fixed origin and SIGTERM removes owned socket', async t => {
  const f = await fixture(t), cli = await startCli(t, f);
  await cli.ready;
  assert.deepEqual(JSON.parse(cli.output().stdout), { listening: ORIGIN, transport: 'unix', scope: 'fixed-public-community-forecast' });
  assert.equal(cli.output().stdout.includes(f.socketPath), false);
  assert.equal((await get(f.socketPath, '/')).status, 404);
  cli.child.kill('SIGTERM'); assert.deepEqual(await cli.exited, [0, null]);
  assert.equal(cli.output().stderr, ''); await absent(f.socketPath);
});

test('CLI refuses a simultaneous TCP port or static root without binding or leaking configuration', async t => {
  for (const extra of [['--port', '43210'], ['--static-root', '/private/path']]) {
    const f = await fixture(t), cli = await startCli(t, f, extra);
    assert.deepEqual(await cli.exited, [1, null]);
    assert.deepEqual(cli.output(), { stdout: '', stderr: '{"error":"BRIDGE_START_FAILED"}\n' });
    assert.deepEqual(await readdir(f.parent), []);
  }
});

test('failed startup under an over-restrictive child umask removes its own empty staging directory only', async t => {
  const f = await fixture(t), cli = await startCli(t, f, [], 0o777);
  assert.deepEqual(await cli.exited, [1, null]);
  assert.deepEqual(cli.output(), { stdout: '', stderr: '{"error":"BRIDGE_START_FAILED"}\n' });
  assert.deepEqual(await readdir(f.parent), []);
  assert.equal((await lstat(f.parent)).mode & 0o7777, 0o700);
});
