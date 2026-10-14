// SPDX-License-Identifier: GPL-3.0-only
// Real owned Node children + Unix HTTP + private files, synthetic CLI receipts
// and forecasts. This proves observation/lifecycle, NOT core or Android delivery.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import fs from 'node:fs';
import { request as httpRequest } from 'node:http';
import { syncBuiltinESMExports } from 'node:module';
import { createServer } from 'node:net';
import { mkdtemp, mkdir, chmod, writeFile, readFile, readdir, lstat, rm, rename, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { fetchCachedForecast } from '../src/core-cache.mjs';
import { startProviderHttp } from '../src/provider-http.mjs';
import { openAndroidProofReceipts, ANDROID_PROOF_PROFILE } from '../src/android-proof-receipts.mjs';
import { request } from '../src/forecast.mjs';
import { airQualityRequest } from '../src/air-quality.mjs';
import { forecast } from './fixtures.mjs';
import { aqForecast } from './air-quality-fixtures.mjs';

const script = fileURLToPath(new URL('../scripts/serve-provider.mjs', import.meta.url));
const WEATHER = '/api/volparossa/forecast', AQ = '/api/volparossa/air-quality';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
async function absent(path) { await assert.rejects(lstat(path), error => error.code === 'ENOENT'); }
function get(socketPath, path = WEATHER) {
  return new Promise((resolve, reject) => {
    const req = httpRequest({ socketPath, path, headers: { Host: '127.0.0.1:43210', Origin: 'http://127.0.0.1:43210' } }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk));
      response.once('end', () => resolve({ status: response.statusCode, body: JSON.parse(Buffer.concat(chunks).toString()) }));
    });
    req.once('error', reject); req.end();
  });
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'weather-proof-')); await chmod(root, 0o700);
  const proof = join(root, 'proof'), socketParent = join(root, 'socket'), caches = join(root, 'caches');
  for (const path of [proof, socketParent, caches]) await mkdir(path, { mode: 0o700 });
  const control = createServer(); control.listen(join(root, 'control.sock')); await once(control, 'listening');
  const run = new Date(Math.floor(Date.now() / 21600000) * 21600000).toISOString(), now = new Date().toISOString();
  const core = { mode: 'core-cache', executable: join(root, 'synthetic-core'), controlSocket: join(root, 'control.sock'),
    cache: join(caches, 'weather'), scratchParent: root, publisherKey: 'c'.repeat(64), name: 'synthetic.weather',
    minRevision: 2, cacheMode: 'create-or-open', query: request({ latitude: 52.52, longitude: 13.41,
      run, steps: [12], communityArea: true }) };
  const config = { core, variables: ['temperature_2m'], airQuality: { core: { ...core, cache: join(caches, 'air_quality'),
    name: 'synthetic.air_quality', query: airQualityRequest({ latitude: 52.52, longitude: 13.41, run, steps: [3, 9, 24], communityArea: true }) },
  variables: ['pm2_5', 'pm10'] } };
  const data = { weather: forecast(core.query, now), air_quality: aqForecast(config.airQuality.core.query, now) };
  const plan = join(root, 'synthetic-plan.json'), calls = join(root, 'calls.jsonl');
  await writeFile(plan, '{}', { mode: 0o600 });
  await writeFile(core.executable, `#!${process.execPath}
const fs=require('node:fs'),crypto=require('node:crypto');
const args=process.argv.slice(2),read=key=>args[args.indexOf(key)+1],reuse=args.includes('--reuse-cache');
if(args[2]!=='content'||args[3]!=='fetch-name'||args.includes('--cache-only'))process.exit(9);
const product=read('--name').endsWith('air_quality')?'air_quality':'weather',cache=read('--cache'),output=read('--local-output');
fs.appendFileSync(${JSON.stringify(calls)},JSON.stringify({product,reuse})+'\\n',{mode:0o600});
if(reuse){if(!fs.statSync(cache).isDirectory())process.exit(8);}else fs.mkdirSync(cache,{mode:0o700});
const bytes=Buffer.from(JSON.stringify(${JSON.stringify(data)}[product]));
fs.writeFileSync(output,bytes,{mode:0o600,flag:'wx'});
const value={operation:'named_content_download',bytes:bytes.length,chunks:1,publisher_key:read('--publisher-key'),
 name:read('--name'),revision:2,manifest_id:'b'.repeat(64),publication_expires_unix_seconds:Math.floor(Date.now()/1000)+1200,
 sha256:crypto.createHash('sha256').update(bytes).digest('hex'),local_delivery:true,output_mode:'0600',ownership_changed:false,
 origin_authenticated:false,globally_latest:false,peer_bytes:reuse?0:bytes.length,providers_used:reuse?0:1,
 origin_body_bytes:0,origin_range_requests:0,provider_peer_ids:reuse?[]:['12D3KooWAbcd'],control_relay_peer_id:reuse?'':'12D3KooWEfgh',
 cache_only:false,cache,local_output:output,...JSON.parse(fs.readFileSync(${JSON.stringify(plan)},'utf8'))};
process.stdout.write('  '+JSON.stringify(value,null,2)+'\\n');
`, { mode: 0o700 });
  const configPath = join(root, 'config.json'); await writeFile(configPath, JSON.stringify(config), { mode: 0o600 });
  const socketPath = join(socketParent, 'api.sock');
  const closers = [];
  t.after(async () => {
    for (const close of closers) await close();
    control.close(); await rm(root, { recursive: true, force: true });
  });
  return { root, proof, socketPath, config, configPath, plan, calls, data, closers };
}
async function launch(t, f, extras = [], unix = true) {
  const child = spawn(process.execPath, [script, '--config', f.configPath, ...(unix ? ['--socket', f.socketPath] : []), ...extras],
    { stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = ''; child.stdout.on('data', bytes => stdout += bytes); child.stderr.on('data', bytes => stderr += bytes);
  const exited = once(child, 'exit');
  f.closers.push(async () => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM'); await exited; });
  for (let i = 0; i < 300 && !stdout.includes('\n') && child.exitCode === null; i++) await delay(10);
  return { child, exited, stdout: () => stdout, stderr: () => stderr };
}

test('explicit CLI proof observes only actual GETs, exact raw receipts, cold then warm for both products', async t => {
  const f = await fixture(t);
  const server = await launch(t, f, ['--proof-profile', ANDROID_PROOF_PROFILE, '--private-receipt-directory', f.proof]);
  assert.equal(JSON.parse(server.stdout()).transport, 'unix');
  assert.deepEqual(await readdir(f.proof), []); await absent(f.calls);
  await absent(f.config.core.cache); await absent(f.config.airQuality.core.cache);
  assert.equal((await get(f.socketPath, '/proof/weather-1.receipt.json')).status, 404); await absent(f.calls);
  for (let ordinal = 1; ordinal <= 3; ordinal++) {
    for (const [path, product] of [[WEATHER, 'weather'], [AQ, 'air_quality']]) {
      const result = await get(f.socketPath, path); assert.equal(result.status, 200);
      assert.deepEqual(result.body.forecast, f.data[product]);
      const receiptPath = join(f.proof, `${product}-${ordinal}.receipt.json`), raw = await readFile(receiptPath);
      assert.ok(raw.toString().startsWith('  {\n')); assert.ok(raw.toString().endsWith('\n'));
      const receipt = JSON.parse(raw), metadata = JSON.parse(await readFile(join(f.proof, `${product}-${ordinal}.observation.json`)));
      assert.equal(receipt.peer_bytes, ordinal === 1 ? receipt.bytes : 0);
      assert.equal(receipt.providers_used, ordinal === 1 ? 1 : 0);
      assert.deepEqual(Object.keys(metadata).sort(), ['schema', 'kind', 'profile', 'product', 'ordinal', 'started_at_ms',
        'completed_at_ms', 'reuse_cache', 'stdout_bytes', 'stdout_sha256'].sort());
      assert.equal(metadata.schema, 1); assert.equal(metadata.profile, ANDROID_PROOF_PROFILE);
      assert.equal(metadata.product, product); assert.equal(metadata.ordinal, ordinal);
      assert.equal(metadata.stdout_sha256, hash(raw)); assert.equal(metadata.stdout_bytes, raw.length);
      assert.equal(metadata.reuse_cache, ordinal !== 1); assert.ok(metadata.completed_at_ms >= metadata.started_at_ms);
      assert.equal((await lstat(receiptPath)).mode & 0o777, 0o600);
      await absent(receipt.local_output);
    }
  }
  assert.equal((await readdir(f.proof)).length, 12);
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  server.child.kill('SIGTERM'); assert.deepEqual(await server.exited, [0, null]); assert.equal(server.stderr(), '');
  await absent(f.socketPath);
});

test('default provider has no proof writes and unknown HTTP configuration cannot activate observation', async t => {
  const f = await fixture(t), server = await startProviderHttp({ config: f.config, socketPath: f.socketPath });
  f.closers.push(() => server.close());
  assert.equal((await get(f.socketPath)).status, 200); assert.deepEqual(await readdir(f.proof), []);
  await assert.rejects(startProviderHttp({ config: { ...f.config, privateReceiptDirectory: f.proof }, socketPath: f.socketPath }));
  await assert.rejects(startProviderHttp({ config: f.config, staticRoot: f.proof }, { observeReceipt() {} }));
});

test('observer only receives validated receipts after scratch cleanup and respects original abort/deadline', async t => {
  const f = await fixture(t), options = { ...f.config.core, reuseCache: false };
  let seen = 0;
  const controller = new AbortController();
  await assert.rejects(fetchCachedForecast(options, { signal: controller.signal, receiptDeadline: performance.now() + 1000,
    observeReceipt: async event => {
      seen++; await absent(JSON.parse(event.stdout).local_output);
      assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
      controller.abort();
    } }), error => error.code === 'CANCELLED');
  assert.equal(seen, 1);
  await writeFile(f.plan, JSON.stringify({ sha256: 'f'.repeat(64) }));
  await assert.rejects(fetchCachedForecast({ ...options, reuseCache: true }, { observeReceipt() { seen++; } }),
    error => error.code === 'CORE_HASH_MISMATCH');
  assert.equal(seen, 1);
  await writeFile(f.plan, '{}');
  await assert.rejects(fetchCachedForecast({ ...options, reuseCache: true }, {
    receiptDeadline: performance.now() - 1, observeReceipt() { seen++; } }), error => error.code === 'CANCELLED');
  assert.equal(seen, 1);
});

test('original HTTP deadline includes joined observation and cancellation cannot create proof files', async t => {
  const f = await fixture(t), sink = await openAndroidProofReceipts(f.proof);
  let observed = 0;
  const start = performance.now();
  const server = await startProviderHttp({ config: f.config, socketPath: f.socketPath, requestDeadlineMs: 250 }, {
    observeReceipt: async (event, context) => {
      observed++; assert.ok(context.deadline <= performance.now() + 250);
      assert.equal(context.signal.aborted, false);
      await once(context.signal, 'abort');
      await sink.observeReceipt(event, context);
    },
  });
  f.closers.push(() => server.close(), () => sink.close());
  assert.equal((await get(f.socketPath)).status, 503);
  assert.equal(observed, 1); assert.ok(performance.now() - start >= 200);
  assert.deepEqual(await readdir(f.proof), []);
  assert.equal((await readdir(f.root)).some(name => name.startsWith('forecast-')), false);
  assert.equal((await readFile(f.calls, 'utf8')).trim().split('\n').length, 1, 'no retry');
});

async function sample(t) {
  const f = await fixture(t); let event;
  await fetchCachedForecast({ ...f.config.core, reuseCache: false }, { observeReceipt(value) { event = value; } });
  return { ...f, event };
}
test('private sink rejects unknown shapes/counters/oversize, expired or aborted writes without retaining anything', async t => {
  const f = await sample(t);
  for (const change of [v => ({ ...v, secret: 'must-not-persist' }), v => ({ ...v, providers_used: 2 }),
    v => ({ ...v, peer_bytes: -1 }), v => ({ ...v, origin_body_bytes: 1 }),
    v => ({ ...v, provider_peer_ids: ['invalid peer with space'] })]) {
    const sink = await openAndroidProofReceipts(f.proof);
    await assert.rejects(sink.observeReceipt({ ...f.event, stdout: Buffer.from(JSON.stringify(change(JSON.parse(f.event.stdout)))) },
      { deadline: performance.now() + 1000 }));
    await sink.close(); assert.deepEqual(await readdir(f.proof), []);
  }
  for (const [event, context] of [[{ ...f.event, stdout: Buffer.alloc(16385, 120) }, { deadline: performance.now() + 1000 }],
    [f.event, { deadline: performance.now() - 1 }], [f.event, { deadline: performance.now() + 1000, signal: AbortSignal.abort() }]]) {
    const sink = await openAndroidProofReceipts(f.proof);
    await assert.rejects(sink.observeReceipt(event, context)); await sink.close(); assert.deepEqual(await readdir(f.proof), []);
  }
});

test('sink allows only three receipts per fixed product and never overwrites earlier evidence', async t => {
  const f = await sample(t), sink = await openAndroidProofReceipts(f.proof);
  f.closers.push(() => sink.close());
  for (let i = 0; i < 3; i++) await sink.observeReceipt(f.event, { deadline: performance.now() + 1000 });
  const raw = await readFile(join(f.proof, 'weather-1.receipt.json'));
  await assert.rejects(sink.observeReceipt(f.event, { deadline: performance.now() + 1000 }), /PROOF_OBSERVATION_INVALID/);
  assert.equal((await readdir(f.proof)).length, 6); assert.deepEqual(await readFile(join(f.proof, 'weather-1.receipt.json')), raw);
  await assert.rejects(sink.observeReceipt({ ...f.event, product: 'air_quality' }, { deadline: performance.now() + 1000 }), /PROOF_SINK_UNAVAILABLE/);
});

test('proof directory must start empty/private/canonical; replacement does not receive evidence', async t => {
  const f = await sample(t);
  await chmod(f.proof, 0o755); await assert.rejects(openAndroidProofReceipts(f.proof)); await chmod(f.proof, 0o700);
  const link = join(f.root, 'proof-link'); await symlink(f.proof, link); await assert.rejects(openAndroidProofReceipts(link));
  const sink = await openAndroidProofReceipts(f.proof), moved = join(f.root, 'moved-proof');
  await rename(f.proof, moved); await mkdir(f.proof, { mode: 0o700 });
  await assert.rejects(sink.observeReceipt(f.event, { deadline: performance.now() + 1000 }), /PROOF_DIRECTORY_CHANGED/);
  await assert.rejects(sink.close(), /PROOF_DIRECTORY_CHANGED/);
  assert.deepEqual(await readdir(f.proof), []); assert.deepEqual(await readdir(moved), []);
  await writeFile(join(f.proof, 'existing'), 'preserve'); await assert.rejects(openAndroidProofReceipts(f.proof));
  assert.equal(await readFile(join(f.proof, 'existing'), 'utf8'), 'preserve');
});

test('retained receipt replacement is detected and preserved instead of overwritten or deleted', async t => {
  const f = await sample(t), sink = await openAndroidProofReceipts(f.proof);
  await sink.observeReceipt(f.event, { deadline: performance.now() + 1000 });
  const receipt = join(f.proof, 'weather-1.receipt.json');
  await rename(receipt, join(f.root, 'saved-receipt')); await writeFile(receipt, 'replacement', { mode: 0o600 });
  await assert.rejects(sink.observeReceipt(f.event, { deadline: performance.now() + 1000 }), /PROOF_FILE_CHANGED/);
  await assert.rejects(sink.close(), /PROOF_FILE_CHANGED/);
  assert.equal(await readFile(receipt, 'utf8'), 'replacement'); await absent(join(f.proof, 'weather-2.receipt.json'));
});

for (const timeoutClose of [false, true]) {
  test(`close preserves directory ownership during a delayed receipt open (timeout=${timeoutClose})`, async t => {
    const f = await sample(t), other = join(f.root, 'other');
    await mkdir(other, { mode: 0o700 });
    const originalOpen = fs.promises.open;
    let reachedOpen, resumeOpen, retired;
    const reached = new Promise(resolve => { reachedOpen = resolve; });
    const gate = new Promise(resolve => { resumeOpen = resolve; });
    const retirement = new Promise(resolve => { retired = resolve; });
    let pinned, pinnedFd, parentRetired = false, sink, writing, closing, otherHandle;
    fs.promises.open = async function (path, ...args) {
      if (typeof path === 'string' && path.endsWith('/weather-1.receipt.json')) {
        assert.equal(path, `/proc/self/fd/${pinnedFd}/weather-1.receipt.json`);
        reachedOpen(); await gate;
      }
      const handle = await originalOpen(path, ...args);
      if (path === f.proof) {
        pinned = handle; pinnedFd = handle.fd;
        const originalClose = handle.close.bind(handle);
        handle.close = async () => {
          try { await originalClose(); }
          finally { parentRetired = true; retired(); }
        };
      }
      return handle;
    };
    syncBuiltinESMExports();
    try {
      sink = await openAndroidProofReceipts(f.proof);
      writing = sink.observeReceipt(f.event, { deadline: performance.now() + 15000 })
        .then(() => null, error => error);
      await reached;
      closing = sink.close();
      // Install the rejection observer before deliberately holding the write for 5 s.
      closing.catch(() => {});
      assert.equal(sink.close(), closing, 'repeated close must not restart its deadline');
      await assert.rejects(sink.observeReceipt(f.event, { deadline: performance.now() + 1000 }), /PROOF_SINK_UNAVAILABLE/);
      otherHandle = await originalOpen(other, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY);
      assert.notEqual(otherHandle.fd, pinnedFd, 'active directory descriptor must not be reusable');
      if (timeoutClose) {
        await assert.rejects(closing, /PROOF_CLEANUP_UNCONFIRMED/);
      } else {
        await delay(0);
      }
      assert.equal(parentRetired, false, 'incomplete join must retain the owned handle');
      assert.equal(pinned.fd, pinnedFd);
      resumeOpen();
      assert.equal((await writing).code, 'CANCELLED');
      if (!timeoutClose) await assert.rejects(closing, /PROOF_FILE_CHANGED/);
      await retirement;
      assert.equal(pinned.fd, -1);
      assert.deepEqual(await readdir(other), [], 'no create/write may escape into a reused descriptor');
      assert.deepEqual(await readdir(f.proof), ['weather-1.receipt.json']);
      assert.equal((await lstat(join(f.proof, 'weather-1.receipt.json'))).size, 0,
        'close cancels before writing raw bytes; the partial owned file is not completion evidence');
    } finally {
      resumeOpen();
      await writing;
      await closing?.catch(() => {});
      await otherHandle?.close();
      await sink?.close().catch(() => {});
      fs.promises.open = originalOpen; syncBuiltinESMExports();
    }
  });
}

test('paired proof flags require exact profile and Unix-only/no-static configuration', async t => {
  for (const extras of [['--proof-profile', ANDROID_PROOF_PROFILE], ['--private-receipt-directory', '/tmp'],
    ['--proof-profile', 'other', '--private-receipt-directory', '/tmp'],
    ['--proof-profile', ANDROID_PROOF_PROFILE, '--private-receipt-directory', '/tmp', '--port', '8788'],
    ['--proof-profile', ANDROID_PROOF_PROFILE, '--private-receipt-directory', '/tmp', '--static-root', '/tmp']]) {
    const f = await fixture(t), server = await launch(t, f, extras);
    assert.deepEqual(await server.exited, [1, null]); assert.equal(server.stdout(), '');
    assert.equal(server.stderr(), '{"error":"BRIDGE_START_FAILED"}\n'); await absent(f.socketPath); await absent(f.calls);
  }
  const f = await fixture(t), tcp = await launch(t, f,
    ['--proof-profile', ANDROID_PROOF_PROFILE, '--private-receipt-directory', f.proof], false);
  assert.deepEqual(await tcp.exited, [1, null]); assert.equal(tcp.stdout(), '');
  assert.equal(tcp.stderr(), '{"error":"BRIDGE_START_FAILED"}\n'); assert.deepEqual(await readdir(f.proof), []);
});
