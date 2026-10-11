// SPDX-License-Identifier: GPL-3.0-only
// Actual loopback HTTP and synthetic assets; not a rendered Flutter/core proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import { request } from 'node:http';
import { once } from 'node:events';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, writeFile, chmod, open, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startProviderHttp } from '../src/provider-http.mjs';
import { QUERY } from './fixtures.mjs';

const DEFAULT_CSP = "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const INDEX = '<!doctype html><base href="/"><title>synthetic CanvasKit fixture</title>';
const WASM = Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]);
const MiB = 1024 * 1024;

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'weather-static-profile-'));
  await chmod(root, 0o700);
  const staticRoot = join(root, 'static');
  await mkdir(join(staticRoot, 'assets'), { mode: 0o700, recursive: true });
  await mkdir(join(staticRoot, 'canvaskit'), { mode: 0o700 });
  await mkdir(join(staticRoot, 'assets/shaders'), { mode: 0o700 });
  for (const [path, bytes] of [['index.html', INDEX], ['app.js', '// synthetic'],
    ['canvaskit/canvaskit.wasm', WASM], ['assets/AssetManifest.bin', Buffer.from([0, 255, 1])],
    ['assets/font.otf', Buffer.from([79, 84, 84, 79])], ['assets/shaders/ink_sparkle.frag', '{"sksl":{}}'],
    ['assets/NOTICES', 'Synthetic dependency notices.'], ['LICENSE.txt', 'Synthetic upstream license.'],
    ['LICENSE.VOLPAROSSA.txt', 'Synthetic integration license.'], ['assets/LICENSE.txt', 'NOT_PUBLIC_NESTED_LICENSE'],
    ['NOTICES', 'NOT_PUBLIC_ROOT_NOTICE'], ['assets/NOTICES.txt', 'NOT_PUBLIC_TEXT_FILE']]) {
    await writeFile(join(staticRoot, path), bytes, { mode: 0o600 });
  }
  const config = { variables: ['temperature_2m'], core: { mode: 'core-cache',
    executable: join(root, 'fake-core'), controlSocket: join(root, 'control.sock'), cache: join(root, 'cache'),
    scratchParent: root, publisherKey: 'c'.repeat(64), name: 'weather.fixture', minRevision: 1,
    query: { ...QUERY, includeWind: false, includePrecipitation: false }, reuseCache: true } };
  t.after(() => rm(root, { recursive: true, force: true }));
  async function start(options = {}) {
    const server = await startProviderHttp({ config, staticRoot, ...options }, {
      fetchProvider: async () => { throw Error('PRIVATE_SYNTHETIC_BACKEND_FAILURE'); },
    });
    t.after(() => server.close()); return server;
  }
  return { root, staticRoot, config, start };
}

function get(origin, path, options = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = request(origin, { path, ...options }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers,
        bytes: Buffer.concat(chunks) }));
    }); outgoing.once('error', reject); outgoing.end();
  });
}

test('default and explicit default preserve exact CSP and existing static MIME eligibility', async t => {
  const f = await fixture(t);
  for (const options of [{}, { staticProfile: 'default' }]) {
    const server = await f.start(options), index = await get(server.origin, '/');
    assert.equal(index.bytes.toString(), INDEX);
    assert.equal(index.headers['content-security-policy'], DEFAULT_CSP);
    assert.equal((await get(server.origin, '/app.js')).headers['content-type'], 'text/javascript; charset=utf-8');
    for (const path of ['/canvaskit/canvaskit.wasm', '/assets/AssetManifest.bin', '/assets/font.otf',
      '/assets/shaders/ink_sparkle.frag', '/LICENSE.txt', '/LICENSE.VOLPAROSSA.txt']) {
      assert.equal((await get(server.origin, path)).status, 404);
    }
    // Existing extensionless SPA fallback is unchanged, not notice-file access.
    const notice = await get(server.origin, '/assets/NOTICES');
    assert.equal(notice.headers['content-type'], 'text/html; charset=utf-8');
    assert.equal(notice.bytes.toString(), INDEX);
  }
});

test('explicit CanvasKit profile serves exact bytes and MIME with only two CSP changes', async t => {
  const f = await fixture(t), server = await f.start({ staticProfile: 'flutter-canvaskit' });
  for (const [path, type, bytes] of [
    ['/canvaskit/canvaskit.wasm', 'application/wasm', WASM],
    ['/assets/AssetManifest.bin', 'application/octet-stream', Buffer.from([0, 255, 1])],
    ['/assets/font.otf', 'font/otf', Buffer.from([79, 84, 84, 79])],
    ['/assets/shaders/ink_sparkle.frag', 'application/octet-stream', Buffer.from('{"sksl":{}}')],
    ['/assets/NOTICES', 'text/plain; charset=utf-8', Buffer.from('Synthetic dependency notices.')],
    ['/LICENSE.txt', 'text/plain; charset=utf-8', Buffer.from('Synthetic upstream license.')],
    ['/LICENSE.VOLPAROSSA.txt', 'text/plain; charset=utf-8', Buffer.from('Synthetic integration license.')],
  ]) {
    const result = await get(server.origin, path);
    assert.equal(result.status, 200); assert.equal(result.headers['content-type'], type);
    assert.deepEqual(result.bytes, bytes);
    assert.equal(result.headers['content-security-policy'], DEFAULT_CSP
      .replace("script-src 'self' 'unsafe-inline'", "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'")
      .replace("base-uri 'none'", "base-uri 'self'"));
    assert.equal(result.headers['content-security-policy'].includes("'unsafe-eval'"), false);
    assert.equal(result.headers['cache-control'], 'no-store');
    assert.equal(result.headers['x-content-type-options'], 'nosniff');
    assert.equal(result.headers['cross-origin-resource-policy'], 'same-origin');
    assert.equal(result.headers['referrer-policy'], 'no-referrer');
    assert.equal(result.headers['permissions-policy'], 'geolocation=(), camera=(), microphone=()');
    assert.equal(result.headers['access-control-allow-origin'], undefined);
  }
  assert.equal((await get(server.origin, '/NOTICES')).bytes.toString(), INDEX);
  assert.equal((await get(server.origin, '/assets/NOTICES.txt')).status, 404);
  assert.equal((await get(server.origin, '/assets/LICENSE.txt')).status, 404);
  assert.equal((await get(server.origin, '/assets/NOTICES/../NOTICES')).status, 400);
});

test('CanvasKit profile does not change fixed API, origin, method or query boundaries', async t => {
  const f = await fixture(t), server = await f.start({ staticProfile: 'flutter-canvaskit' });
  for (const [path, options, status] of [
    ['/canvaskit/canvaskit.wasm', { headers: { Origin: 'https://elsewhere.invalid' } }, 403],
    ['/assets/AssetManifest.bin', { headers: { Host: 'elsewhere.invalid' } }, 403],
    ['/assets/font.otf', { method: 'POST' }, 405],
    ['/?static-profile=default', {}, 400],
    ['/api/volparossa/forecast?latitude=0', {}, 400],
    ['/api/volparossa/forecast', {}, 503], ['/api/volparossa/air-quality', {}, 503],
  ]) {
    const result = await get(server.origin, path, options);
    assert.equal(result.status, status); assert.deepEqual(Object.keys(JSON.parse(result.bytes)), ['error']);
    assert.equal(result.bytes.includes('PRIVATE'), false);
  }
});

test('profile selection is closed and remains separate from data configuration', async t => {
  const f = await fixture(t);
  for (const staticProfile of ['', 'flutter', 'skwasm', 'constructor', '__proto__', null, false, ['flutter-canvaskit']]) {
    await assert.rejects(f.start({ staticProfile }), error => error.code === 'BRIDGE_CONFIG_INVALID');
  }
  await assert.rejects(f.start({ config: { ...f.config, staticProfile: 'flutter-canvaskit' } }),
    error => error.code === 'BRIDGE_CONFIG_INVALID');
});

async function sized(path, bytes) {
  const file = await open(path, 'w', 0o600);
  try { await file.truncate(bytes); } finally { await file.close(); }
}

test('both profiles keep the 8 MiB individual and 32 MiB aggregate asset limits', async t => {
  for (const [staticProfile, extension] of [['default', 'js'], ['flutter-canvaskit', 'wasm']]) {
    const f = await fixture(t), path = join(f.staticRoot, `large.${extension}`);
    await sized(path, 8 * MiB);
    const accepted = await f.start({ staticProfile }); await accepted.close();
    await sized(path, 8 * MiB + 1);
    await assert.rejects(f.start({ staticProfile }), error => error.code === 'STATIC_BUDGET_EXCEEDED');
    await sized(path, 8 * MiB);
    for (let i = 0; i < 3; i++) await sized(join(f.staticRoot, `more-${i}.${extension}`), 8 * MiB);
    await assert.rejects(f.start({ staticProfile }), error => error.code === 'STATIC_BUDGET_EXCEEDED');
  }
});

test('new asset types retain owner and no-symlink checks', async t => {
  const f = await fixture(t), asset = join(f.staticRoot, 'canvaskit/canvaskit.wasm');
  await chmod(asset, 0o666);
  await assert.rejects(f.start({ staticProfile: 'flutter-canvaskit' }), error => error.code === 'STATIC_ROOT_INVALID');
  await rm(asset); await symlink('/etc/passwd', asset);
  await assert.rejects(f.start({ staticProfile: 'flutter-canvaskit' }), error => error.code === 'STATIC_ROOT_INVALID');
});

test('serve CLI explicitly selects CanvasKit and rejects unknown profiles before listening', async t => {
  const f = await fixture(t), configPath = join(f.root, 'bridge.json');
  await writeFile(configPath, JSON.stringify(f.config), { mode: 0o600 });
  const script = fileURLToPath(new URL('../scripts/serve-provider.mjs', import.meta.url));
  const args = [script, '--config', configPath, '--static-root', f.staticRoot, '--port', '0', '--static-profile'];
  const child = spawn(process.execPath, [...args, 'flutter-canvaskit'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = ''; child.stderr.on('data', bytes => { stderr += bytes.toString(); });
  const exited = once(child, 'exit');
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM'); await exited; });
  const output = await Promise.race([once(child.stdout, 'data'), exited.then(() => { throw Error('early exit'); }),
    new Promise((_, reject) => { const timer = setTimeout(() => reject(Error('start timeout')), 3000); timer.unref(); })]);
  const started = JSON.parse(output[0]);
  assert.match(started.listening, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal(started.scope, 'fixed-public-community-forecast');
  const result = await get(started.listening, '/canvaskit/canvaskit.wasm');
  assert.equal(result.headers['content-type'], 'application/wasm'); assert.deepEqual(result.bytes, WASM);
  child.kill('SIGTERM'); assert.deepEqual(await exited, [0, null]); assert.equal(stderr, '');
  await assert.rejects(promisify(execFile)(process.execPath, [...args, 'unsafe-eval']), error => {
    assert.equal(error.stdout, ''); assert.equal(error.stderr, '{"error":"BRIDGE_START_FAILED"}\n');
    return error.code === 1;
  });
});
