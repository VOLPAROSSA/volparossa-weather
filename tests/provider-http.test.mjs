// SPDX-License-Identifier: GPL-3.0-only
// Actual loopback HTTP and synthetic forecast/core subprocess; not an overlay/UI proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { mkdtemp, mkdir, chmod, writeFile, readdir, rm, symlink, link, rename } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { startProviderHttp, providerHttpConfiguration } from '../src/provider-http.mjs';
import { toProviderForecast } from '../src/provider.mjs';
import { freshness } from '../src/forecast.mjs';
import { forecast, QUERY } from './fixtures.mjs';

const currentQuery = () => ({ ...QUERY, includeWind: false,
  run: new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString() });
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'weather-http-'));
  await chmod(root, 0o700);
  const staticRoot = join(root, 'static'); await mkdir(staticRoot, { mode: 0o700 });
  await writeFile(join(staticRoot, 'index.html'), '<!doctype html><title>synthetic client</title>', { mode: 0o600 });
  await writeFile(join(staticRoot, 'app.js'), 'console.log("synthetic client");', { mode: 0o600 });
  await writeFile(join(staticRoot, '.private.json'), '{"secret":true}', { mode: 0o600 });
  t.after(() => rm(root, { recursive: true, force: true }));
  const config = { variables: ['temperature_2m', 'precipitation'], core: { mode: 'core-cache',
    executable: join(root, 'fake-core'), controlSocket: join(root, 'control.sock'), cache: join(root, 'cache'),
    scratchParent: root, publisherKey: 'c'.repeat(64), name: 'weather.fixture', minRevision: 2,
    query: currentQuery(), reuseCache: false } };
  function provider() {
    const data = forecast(config.core.query, new Date().toISOString());
    const expiry = new Date(Math.floor(Date.now() / 1000) * 1000 + 1200000).toISOString();
    const result = toProviderForecast(data, { variables: config.variables, publicationExpires: expiry });
    result.delivery = { mode: 'core-cache', publisher_key: config.core.publisherKey, name: config.core.name,
      revision: 2, manifest_id: 'b'.repeat(64), sha256: 'd'.repeat(64), publication_expires_at: expiry,
      freshness: freshness(data, result.freshness.checked_at, expiry),
      upstream_origin_attested: false, manifest_media_type_checked: false };
    return result;
  }
  async function start(options = {}, fetchProvider = async () => provider()) {
    const server = await startProviderHttp({ config, staticRoot, ...options }, { fetchProvider });
    t.after(() => server.close()); return server;
  }
  return { root, staticRoot, config, provider, start };
}

function get(origin, path = '/api/volparossa/forecast', options = {}) {
  return new Promise((done, reject) => {
    const req = httpRequest(origin, { method: 'GET', path, ...options }, response => {
      const data = []; response.on('data', part => data.push(part));
      response.on('end', () => done({ status: response.statusCode, headers: response.headers,
        body: Buffer.concat(data).toString('utf8') }));
    });
    req.once('error', reject); req.end();
  });
}

test('real HTTP delivers fixed provider unchanged, serves static app and blocks external resource policy', async t => {
  const f = await fixture(t), expected = f.provider(); let calls = 0;
  const server = await f.start({}, async (core, options) => {
    calls += 1; assert.deepEqual(core, f.config.core); assert.deepEqual(options.variables, f.config.variables);
    assert.ok(options.signal instanceof AbortSignal); return expected;
  });
  const result = await get(server.origin, undefined, { headers: { Origin: server.origin, 'Sec-Fetch-Site': 'same-origin' } });
  assert.equal(result.status, 200); assert.deepEqual(JSON.parse(result.body), expected);
  assert.equal(JSON.parse(result.body).series[1].values, null);
  assert.equal(result.headers['cache-control'], 'no-store');
  assert.equal(result.headers['access-control-allow-origin'], undefined);
  assert.match(result.headers['content-security-policy'], /connect-src 'self'/);
  assert.match(result.headers['content-security-policy'], /frame-src 'none'/);
  assert.match(result.headers['permissions-policy'], /geolocation=\(\)/);
  assert.equal((await get(server.origin, '/')).status, 200);
  assert.equal((await get(server.origin, '/weather/week/52/13/Berlin')).status, 200);
  assert.equal((await get(server.origin, '/app.js')).headers['content-type'], 'text/javascript; charset=utf-8');
  assert.equal((await get(server.origin, '/.private.json')).status, 404);
  assert.equal((await get(server.origin, '/missing.js')).status, 404);
  assert.equal((await get(server.origin, '/api/unknown')).status, 404);
  assert.equal(calls, 1);
});

test('HTTP cannot choose location, publisher, paths, method, foreign origin or host', async t => {
  const f = await fixture(t); let calls = 0;
  const server = await f.start({}, async () => { calls += 1; return f.provider(); });
  for (const [path, options, status] of [
    ['/api/volparossa/forecast?latitude=1', {}, 400], ['/api/volparossa/forecast?cache=/private', {}, 400],
    ['/api/volparossa/forecast', { method: 'POST' }, 405],
    ['/api/volparossa/forecast', { headers: { Host: 'attacker.invalid' } }, 403],
    ['/api/volparossa/forecast', { headers: { Origin: 'https://attacker.invalid' } }, 403],
    ['/api/volparossa/forecast', { headers: { Origin: 'null' } }, 403],
    ['/api/volparossa/forecast', { headers: { 'Sec-Fetch-Site': 'cross-site' } }, 403],
    ['/api/volparossa/forecast', { headers: { 'Content-Length': '1' } }, 400],
    ['/%2e%2e/private', {}, 400], ['/bad%zz', {}, 400],
  ]) {
    const result = await get(server.origin, path, options);
    assert.equal(result.status, status); assert.deepEqual(Object.keys(JSON.parse(result.body)), ['error']);
    assert.equal(result.body.includes('private'), false);
  }
  assert.equal(calls, 0);
});

test('fixed configuration is copied, exact, public-community-only and checked before listening', async t => {
  const f = await fixture(t), original = structuredClone(f.config);
  const config = providerHttpConfiguration(f.config);
  f.config.core.query.steps.push(24); f.config.variables.push('aqi');
  assert.deepEqual(config.core, original.core); assert.deepEqual(config.variables, original.variables);
  for (const change of [value => value.core.query.communityArea = false, value => value.core.url = 'https://elsewhere',
    value => value.core.executable = '/tmp/../file', value => value.core.minRevision = 0,
    value => value.core.query.extra = true, value => value.variables = []]) {
    const invalid = structuredClone(original); change(invalid);
    await assert.rejects(startProviderHttp({ config: invalid, staticRoot: f.staticRoot }));
  }
  await assert.rejects(startProviderHttp({ config: original, staticRoot: f.staticRoot, requestDeadlineMs: 180001 }));
});

test('static build root rejects symlinks and writable files rather than serving arbitrary paths', async t => {
  const f = await fixture(t);
  await symlink('/etc/passwd', join(f.staticRoot, 'passwd.json'));
  await assert.rejects(f.start(), error => error.code === 'STATIC_ROOT_INVALID');
  await rm(join(f.staticRoot, 'passwd.json'));
  await chmod(join(f.staticRoot, 'app.js'), 0o666);
  await assert.rejects(f.start(), error => error.code === 'STATIC_ROOT_INVALID');
});

test('static assets reject hardlinks and keep only the verified startup bytes after pathname replacement', async t => {
  const f = await fixture(t), asset = join(f.staticRoot, 'app.js');
  const original = 'console.log("synthetic client");';
  await link(asset, join(f.root, 'linked.js'));
  await assert.rejects(f.start(), error => error.code === 'STATIC_ROOT_INVALID');
  await rm(join(f.root, 'linked.js'));
  const server = await f.start();
  await rename(asset, join(f.root, 'original.js'));
  await symlink('/etc/passwd', asset);
  assert.equal((await get(server.origin, '/app.js')).body, original);
  await rm(asset);
  await writeFile(asset, 'unverified replacement', { mode: 0o666 });
  await chmod(asset, 0o666);
  assert.equal((await get(server.origin, '/app.js')).body, original);
  await assert.rejects(f.start(), error => error.code === 'STATIC_ROOT_INVALID');
});

test('one active retrieval, no queue; failures have closed errors and release the slot', async t => {
  const f = await fixture(t); let entered, release;
  const started = new Promise(done => { entered = done; });
  const held = new Promise(done => { release = done; });
  let calls = 0;
  const server = await f.start({}, async () => {
    calls += 1; if (calls === 1) { entered(); await held; }
    throw new Error('PRIVATE_PATH_AND_LOCATION');
  });
  const pending = get(server.origin); await started;
  assert.equal((await get(server.origin)).status, 429); assert.equal(calls, 1);
  release(); assert.deepEqual(JSON.parse((await pending).body), { error: 'FORECAST_UNAVAILABLE' });
  assert.equal((await get(server.origin)).status, 503); assert.equal(calls, 2);
});

test('synchronous backend failure does not strand the concurrency slot', async t => {
  const f = await fixture(t); let calls = 0;
  const server = await f.start({}, () => { calls += 1; throw new Error('private'); });
  assert.equal((await get(server.origin)).status, 503);
  assert.equal((await get(server.origin)).status, 503); assert.equal(calls, 2);
});

test('deadline and disconnected client abort actual retrieval signal', async t => {
  const f = await fixture(t); let aborts = 0, entered;
  let began = new Promise(done => { entered = done; });
  const server = await f.start({ requestDeadlineMs: 80 }, async (_core, { signal }) => {
    entered(); await new Promise((_, reject) => signal.addEventListener('abort', () => {
      aborts += 1; reject(new Error('CANCELLED'));
    }, { once: true }));
  });
  assert.equal((await get(server.origin)).status, 503); assert.equal(aborts, 1);
  began = new Promise(done => { entered = done; });
  const req = httpRequest(server.origin + '/api/volparossa/forecast'); req.on('error', () => {}); req.end();
  await began; req.destroy();
  for (let i = 0; i < 40 && aborts < 2; i++) await new Promise(done => setTimeout(done, 5));
  assert.equal(aborts, 2);
});

test('shutdown aborts and joins retrieval cleanup before returning', async t => {
  const f = await fixture(t); let entered, cleaned = false;
  const began = new Promise(done => { entered = done; });
  const server = await startProviderHttp({ config: f.config, staticRoot: f.staticRoot }, {
    fetchProvider: async (_core, { signal }) => {
      entered(); await new Promise(done => signal.addEventListener('abort', done, { once: true }));
      await new Promise(done => setTimeout(done, 30)); cleaned = true; throw new Error('cancelled');
    },
  });
  const pending = get(server.origin).catch(() => null); await began;
  await server.close(); await pending;
  assert.equal(cleaned, true);
});

test('stale, mismatched and embellished injected provider results fail closed', async t => {
  const f = await fixture(t); let change = value => value.forecast.area.latitude = 1;
  const server = await f.start({}, async () => { const data = f.provider(); change(data); return data; });
  const changes = [value => value.forecast.area.latitude = 1, value => value.delivery.name = 'wrong',
    value => value.delivery.secret = 'PRIVATE_SENTINEL', value => value.freshness.expires_at = '2099-01-01T00:00:00.000Z',
    value => value.series[1].values = [0], value => value.delivery.publication_expires_at = '2000-01-01T00:00:00.000Z'];
  for (change of changes) {
    const result = await get(server.origin);
    assert.equal(result.status, 503); assert.deepEqual(JSON.parse(result.body), { error: 'FORECAST_UNAVAILABLE' });
  }
});

test('default HTTP backend executes existing core-cache adapter and cleans synthetic process outputs', async t => {
  const f = await fixture(t), { core } = f.config;
  const socket = createServer(); socket.listen(core.controlSocket); await once(socket, 'listening');
  t.after(() => socket.close());
  const data = forecast(core.query, new Date().toISOString());
  await writeFile(core.executable, `#!${process.execPath}
const fs=require('node:fs'), crypto=require('node:crypto');
const args=process.argv.slice(2), read=key=>args[args.indexOf(key)+1];
if(args[2]!=='content'||args[3]!=='fetch-name'||args.includes('--cache-only'))process.exit(9);
const bytes=Buffer.from(JSON.stringify(${JSON.stringify(data)})),output=read('--local-output');
fs.writeFileSync(output,bytes,{mode:0o600,flag:'wx'});
process.stdout.write(JSON.stringify({operation:'named_content_download',publisher_key:read('--publisher-key'),name:read('--name'),revision:2,
manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
sha256:crypto.createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,local_delivery:true,output_mode:'0600',
ownership_changed:false,origin_authenticated:false,globally_latest:false,local_output:output,cache:read('--cache'),cache_only:false}));
`, { mode: 0o700 });
  const server = await startProviderHttp({ config: f.config, staticRoot: f.staticRoot }); t.after(() => server.close());
  const result = await get(server.origin);
  assert.equal(result.status, 200); assert.deepEqual(JSON.parse(result.body).forecast, data);
  assert.equal(JSON.parse(result.body).delivery.upstream_origin_attested, false);
  assert.deepEqual((await readdir(f.root)).sort(), ['control.sock', 'fake-core', 'static']);
});

test('HTTP deadline reaches actual core child cancellation and removes its owned work directory', async t => {
  const f = await fixture(t), { core } = f.config;
  const socket = createServer(); socket.listen(core.controlSocket); await once(socket, 'listening');
  t.after(() => socket.close());
  await writeFile(core.executable, `#!${process.execPath}\nsetInterval(() => {}, 1000);\n`, { mode: 0o700 });
  const server = await startProviderHttp({ config: f.config, staticRoot: f.staticRoot, requestDeadlineMs: 100 });
  const result = await get(server.origin);
  assert.equal(result.status, 503);
  await server.close();
  assert.deepEqual((await readdir(f.root)).sort(), ['control.sock', 'fake-core', 'static']);
});

test('actual serve CLI loads private fixed configuration, binds loopback, then shuts down on SIGTERM', async t => {
  const f = await fixture(t), configPath = join(f.root, 'bridge.json');
  await writeFile(configPath, JSON.stringify(f.config), { mode: 0o600 });
  const script = fileURLToPath(new URL('../scripts/serve-provider.mjs', import.meta.url));
  const args = [script, '--config', configPath, '--static-root', f.staticRoot, '--port', '0'];
  const child = spawn(process.execPath, args, { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = ''; child.stderr.on('data', chunk => { stderr += chunk.toString('utf8'); });
  const exited = once(child, 'exit');
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM'); await exited; });
  const output = await Promise.race([once(child.stdout, 'data'), exited.then(() => { throw new Error('early exit'); }),
    new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('start timeout')), 3000); timer.unref(); })]);
  const started = JSON.parse(output[0].toString('utf8'));
  assert.match(started.listening, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal(started.scope, 'fixed-public-community-forecast');
  assert.equal((await get(started.listening, '/')).status, 200);
  assert.equal((await get(started.listening)).status, 503); // No core/socket was installed by starting the bridge.
  child.kill('SIGTERM'); assert.deepEqual(await exited, [0, null]); assert.equal(stderr, '');
  await chmod(configPath, 0o644);
  await assert.rejects(promisify(execFile)(process.execPath, args), error => {
    assert.equal(error.stdout, ''); assert.equal(error.stderr, '{"error":"BRIDGE_START_FAILED"}\n'); return error.code === 1;
  });
});
