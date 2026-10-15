// SPDX-License-Identifier: GPL-3.0-only
// Real local HTTP/Unix processes, synthetic responses and inert driver I/O.
// No Android, SDK, core binary, signed data or protected network is executed.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { createServer, request } from 'node:http';
import { chmod, mkdtemp, readFile, rename, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { startLiveFixture, socketBinding, LIVE_BODY_LIMIT, LIVE_CONTROL_LIMIT } from './native-android-live-fixture.mjs';
import { HEADERS, PACKAGE, COMPONENT, ObserverDiagnostic, adbFailure, validateSnapshot, validateLiveControl,
  readFixtureControl, exerciseLiveNativeProducts, nativeDriverProfile, recordDriverFailure,
  waitForObservation } from './native-android-driver.mjs';
import { nativeFixtureState } from './native-android-fixture.mjs';

const NOW = '2026-10-12T02:00:00.000Z', API = '/api/volparossa/forecast', AQ = '/api/volparossa/air-quality';
const PRIVATE = 'private-key-token-https://secret.invalid/path';
const hash = raw => createHash('sha256').update(raw).digest('hex');
function pair() {
  const fixture = nativeFixtureState(NOW); fixture.setPhase('initial', NOW);
  return { weather: fixture.product(false), air_quality: fixture.product(true) };
}
async function setup(t, handler, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'native-live-')), socket = join(root, 'api.sock');
  await chmod(root, 0o700);
  const seen = [], connections = new Set();
  const upstream = createServer((req, res) => { seen.push({ url: req.url, method: req.method, headers: req.headers }); handler(req, res); });
  upstream.on('connection', socket => { connections.add(socket); socket.once('close', () => connections.delete(socket)); });
  await new Promise(done => upstream.listen(socket, done)); await chmod(socket, 0o600);
  let doorway;
  t.after(async () => {
    if (doorway) await doorway.close();
    upstream.closeAllConnections(); await new Promise(done => upstream.close(done));
    await rm(root, { recursive: true });
  });
  doorway = await startLiveFixture({ upstreamSocket: socket, apiPort: 0, controlPort: 0, ...options });
  return { root, socket, upstream, seen, connections, doorway,
    api: `http://127.0.0.1:${doorway.apiPort}`, control: `http://127.0.0.1:${doorway.controlPort}` };
}
async function settled(condition) {
  for (let n = 0; n < 100; n++) { if (condition()) return; await delay(5); }
  assert.fail('bounded fixture condition not observed');
}
const json = (res, value) => { const raw = Buffer.from(JSON.stringify(value)); res.writeHead(200,
  { 'Content-Type': 'application/json', 'Content-Length': raw.length }); res.end(raw); };

test('doorway forwards exact response bytes and fixed headers, with read-only bounded state and no authority claim', async t => {
  const products = pair(), bytes = Object.fromEntries(Object.entries(products).map(([key, value]) => [key, Buffer.from(JSON.stringify(value, null, 2))]));
  const fixture = await setup(t, (req, res) => {
    const raw = bytes[req.url === API ? 'weather' : 'air_quality'];
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': raw.length }); res.end(raw);
  });
  for (const path of [API, AQ]) {
    const response = await fetch(fixture.api + path, { headers: { 'X-Private': PRIVATE } });
    assert.equal(response.status, 200);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes[path === API ? 'weather' : 'air_quality']);
  }
  const raw = await (await fetch(fixture.control + '/state')).text(); assert.ok(Buffer.byteLength(raw) <= LIVE_CONTROL_LIMIT);
  const status = validateLiveControl(JSON.parse(raw));
  assert.deepEqual(status.calls, { weather: 1, air_quality: 1 }); assert.deepEqual(status.completed, status.calls);
  assert.deepEqual(status.response_sha256, { weather: hash(bytes.weather), air_quality: hash(bytes.air_quality) });
  assert.equal(status.active, false); assert.equal(status.core_executed, false); assert.equal(status.overlay_proven, false);
  for (const seen of fixture.seen) {
    assert.equal(seen.method, 'GET'); assert.equal(seen.headers.host, '127.0.0.1:43210');
    assert.equal(seen.headers.origin, 'http://127.0.0.1:43210'); assert.equal(seen.headers['x-private'], undefined);
  }
  assert.deepEqual(status.products, products);
});

test('only exact bodyless API GETs are forwarded; no phases, static content, path decoding or origin override', async t => {
  const fixture = await setup(t, (_req, res) => json(res, pair().weather));
  for (const [path, options] of [
    ['/', {}], ['/index.html', {}], [API + '?x=1', {}], ['/api/volparossa/%66orecast', {}],
    [API, { method: 'POST' }], [API, { headers: { Origin: 'https://foreign.invalid' } }],
    [API, { headers: { Host: 'foreign.invalid' } }], [API, { headers: { 'Sec-Fetch-Site': 'cross-site' } }],
  ]) {
    // Use node:http: fetch owns/rewrites Host and Sec-Fetch-* headers, so it
    // cannot supply the deliberately invalid wire requests tested here.
    const status = await new Promise((done, reject) => {
      const req = request(fixture.api + path, options, res => { res.resume(); res.once('end', () => done(res.statusCode)); });
      req.once('error', reject); req.end();
    });
    assert.equal(status, 403);
  }
  for (const [path, options] of [['/phase/initial', { method: 'POST' }], ['/state', { method: 'POST' }], ['/', {}]]) {
    assert.equal((await fetch(fixture.control + path, options)).status, 403);
  }
  await new Promise((done, reject) => {
    const req = request(fixture.api + API, { method: 'GET', headers: { 'Content-Length': '1' } }, res => {
      assert.equal(res.statusCode, 403); res.resume(); res.once('end', done);
    }); req.once('error', reject); req.end('x');
  });
  assert.equal(fixture.seen.length, 0); assert.deepEqual(fixture.doorway.status().calls, { weather: 0, air_quality: 0 });
});

test('one active upstream gives no queue or retry and three calls are a hard per-product limit', async t => {
  let release;
  const fixture = await setup(t, (_req, res) => { release = () => json(res, pair().weather); });
  const first = fetch(fixture.api + API); await settled(() => Boolean(release));
  assert.equal((await fetch(fixture.api + AQ)).status, 429); assert.equal(fixture.seen.length, 1);
  release(); assert.equal((await first).status, 200); await settled(() => !fixture.doorway.status().active);
  for (let n = 0; n < 2; n++) {
    release = null; const pending = fetch(fixture.api + API); await settled(() => Boolean(release));
    release(); assert.equal((await pending).status, 200); await settled(() => !fixture.doorway.status().active);
  }
  assert.equal((await fetch(fixture.api + API)).status, 503); assert.equal(fixture.seen.length, 3);
  assert.equal(fixture.doorway.status().terminal_failure, 'request_limit');
});

test('non-200, malformed, compressed and oversized upstream replies fail closed without raw diagnostics', async t => {
  for (const mode of ['status', 'json', 'type', 'encoding', 'length', 'stream', 'utf8']) {
    await t.test(mode, async sub => {
      const fixture = await setup(sub, (_req, res) => {
        if (mode === 'status') { res.writeHead(502); res.end(PRIVATE); return; }
        const headers = { 'Content-Type': mode === 'type' ? 'text/plain' : 'application/json' };
        if (mode === 'encoding') headers['Content-Encoding'] = 'gzip';
        if (mode === 'length') headers['Content-Length'] = String(LIVE_BODY_LIMIT + 1);
        res.writeHead(200, headers);
        res.end(mode === 'stream' ? Buffer.alloc(LIVE_BODY_LIMIT + 1, 65)
          : mode === 'utf8' ? Buffer.from([0xff]) : mode === 'json' ? PRIVATE : '{}');
      });
      const response = await fetch(fixture.api + API);
      assert.equal(response.status, 503); assert.ok(!(await response.text()).includes(PRIVATE));
      await settled(() => !fixture.doorway.status().active);
      const status = fixture.doorway.status(); assert.notEqual(status.terminal_failure, null);
      assert.equal(status.completed.weather, 0); assert.equal(status.products.weather, null);
      assert.ok(!JSON.stringify(status).includes(PRIVATE)); assert.throws(() => validateLiveControl(status));
      assert.equal((await fetch(fixture.api + AQ)).status, 503); assert.equal(fixture.seen.length, 1);
    });
  }
});

test('deadline destroys and joins the actual upstream socket; no late response or replacement fetch', async t => {
  const fixture = await setup(t, () => {}, { requestDeadlineMs: 30 });
  assert.equal((await fetch(fixture.api + API)).status, 503);
  await settled(() => !fixture.doorway.status().active && fixture.connections.size === 0);
  assert.equal(fixture.doorway.status().terminal_failure, 'deadline'); assert.equal(fixture.seen.length, 1);
});
test('disconnect and shutdown abort the actual upstream and close waits for it', async t => {
  for (const disconnect of [true, false]) await t.test(String(disconnect), async sub => {
    const fixture = await setup(sub, () => {});
    const controller = new AbortController();
    const pending = fetch(fixture.api + API, { signal: controller.signal }).catch(() => null);
    await settled(() => fixture.seen.length === 1);
    if (disconnect) controller.abort(); else await fixture.doorway.close();
    await pending; await settled(() => !fixture.doorway.status().active && fixture.connections.size === 0);
    assert.equal(fixture.doorway.status().terminal_failure, disconnect ? 'client_aborted' : 'closing');
    assert.equal(fixture.doorway.status().completed.weather, 0);
  });
});

test('socket boundary rejects wrong modes, symlinks, files, missing and changed endpoints without connecting', async t => {
  const fixture = await setup(t, (_req, res) => json(res, pair().weather));
  const alias = join(fixture.root, 'alias.sock'); await symlink(fixture.socket, alias);
  await assert.rejects(socketBinding(alias));
  const file = join(fixture.root, 'regular'); await writeFile(file, 'private', { flag: 'wx', mode: 0o600 });
  await assert.rejects(socketBinding(file)); await assert.rejects(socketBinding(join(fixture.root, 'absent')));
  await chmod(fixture.socket, 0o660); await assert.rejects(socketBinding(fixture.socket));
  await chmod(fixture.socket, 0o600); await chmod(fixture.root, 0o750); await assert.rejects(socketBinding(fixture.socket));
  await chmod(fixture.root, 0o1700); await assert.rejects(socketBinding(fixture.socket));
  await chmod(fixture.root, 0o700);
  await rename(fixture.socket, join(fixture.root, 'original.sock'));
  const replacement = createServer((_req, res) => json(res, {}));
  await new Promise(done => replacement.listen(fixture.socket, done)); await chmod(fixture.socket, 0o600);
  t.after(async () => { replacement.closeAllConnections(); await new Promise(done => replacement.close(done)); });
  assert.equal((await fetch(fixture.api + API)).status, 503); assert.equal(fixture.seen.length, 0);
  assert.equal(fixture.doorway.status().terminal_failure, 'socket_boundary');
});

function liveStatus(products = pair(), count = 1) {
  return { schema: 3, profile: 'protected-core', calls: { weather: count, air_quality: count },
    completed: { weather: count, air_quality: count }, products,
    response_sha256: Object.fromEntries(Object.entries(products).map(([key, value]) => [key, hash(JSON.stringify(value))])),
    active: false, terminal_failure: null, synthetic_weather: false, synthetic_air_quality: false,
    core_executed: false, overlay_proven: false };
}
test('live control is strict and cannot reinterpret historical synthetic or unproven authority as live evidence', () => {
  validateLiveControl(liveStatus());
  for (const mutate of [value => { value.schema = 2; }, value => { value.calls.weather = 4; },
    value => { value.completed.weather = 2; }, value => { value.core_executed = true; },
    value => { value.overlay_proven = true; }, value => { value.extra = PRIVATE; },
    value => { value.products.weather.delivery.mode = 'synthetic'; },
    value => { value.products.weather.delivery.sha256 = PRIVATE; },
    value => { value.products.air_quality.forecast.samples.pop(); },
    value => { value.products.weather.forecast.samples[0].lead_hours = 1; },
    value => { value.terminal_failure = PRIVATE; }, value => { value.response_sha256.weather = null; }]) {
    const value = liveStatus(); mutate(value); assert.throws(() => validateLiveControl(value));
  }
});
test('explicit driver profile and GET-only control do not change the synthetic default or admit phase writes', async () => {
  const args = ['--adb', '/adb', '--serial', 'emulator-5554', '--output', '/output'];
  assert.equal(nativeDriverProfile(args), 'synthetic');
  assert.equal(nativeDriverProfile([...args, '--profile', 'protected-core']), 'protected-core');
  for (const suffix of [['--profile', 'unknown'], ['--profile', 'synthetic'], ['--profile']]) assert.throws(() => nativeDriverProfile([...args, ...suffix]));
  const diagnostic = new ObserverDiagnostic(); let calls = 0;
  const context = { profile: 'protected-core', diagnostic, remaining() {},
    async fetchControl(url, options) {
      calls++; assert.equal(url, 'http://127.0.0.1:43211/state'); assert.equal(options.method, 'GET');
      return new Response(JSON.stringify(liveStatus()), { status: 200 });
    } };
  await readFixtureControl(context);
  await assert.rejects(readFixtureControl(context, '/phase/initial')); assert.equal(calls, 1);
  await assert.rejects(readFixtureControl({ ...context, profile: 'synthetic' }));
});
test('live control decode/byte/status bounds and errors remain closed at the actual reader', async () => {
  for (const [response, subphase] of [[new Response(PRIVATE), 'control_decode'],
    [new Response('{}'.repeat(LIVE_CONTROL_LIMIT)), 'control_body'],
    [new Response('{}', { status: 503 }), 'control_status'],
    [new Response(JSON.stringify({ ...liveStatus(), extra: PRIVATE })), 'control_schema']]) {
    const diagnostic = new ObserverDiagnostic(); diagnostic.beginProducts(1);
    const report = { phase: 'initial-native-products', passed: false };
    await assert.rejects(readFixtureControl({ remaining() {}, diagnostic, profile: 'protected-core',
      fetchControl: async () => response }), error => {
      recordDriverFailure(report, diagnostic, error); return true;
    });
    assert.equal(report.passed, false); assert.equal(report.failure_diagnostic.schema, 5);
    assert.equal(report.failure_diagnostic.subphase, subphase);
    assert.ok(!JSON.stringify(report).includes(PRIVATE));
  }
});

function table(product, name) {
  const quality = name === 'air_quality';
  return { product: name, headers: HEADERS[name], rows: product.forecast.samples.map(sample => [sample.valid_at,
    ...(quality ? [sample.pm2_5, sample.pm10] : [sample.temperature_2m, sample.wind_10m.speed,
      sample.wind_10m.direction_from, sample.precipitation.amount]).map(value => value === null ? 'Not available' : String(value)),
    ...(!quality ? [sample.precipitation.start_at === null ? 'Not available'
      : `${sample.precipitation.start_at} → ${sample.precipitation.end_at}`] : [])]) };
}
function labels(product) {
  const source = product.forecast.source;
  return [`Model ${source.model}; run ${source.model_run_at}`, `Acquired ${source.acquired_at}`,
    `Expires ${product.freshness.expires_at}`, source.attribution, `${source.license}: ${source.license_url}`, source.changes];
}
function exercise(options = {}) {
  const products = pair(), diagnostic = new ObserverDiagnostic(), events = [];
  const report = { schema: 2, kind: 'overmorrow-installed-android-protected-core-trial', passed: false,
    profile: 'protected-core', joined_core_acceptance: false, checks: {}, observations: {},
    scope: { core_executed: false, overlay_proven: false, expiry_proven: false,
      mounted_widget_tables: false, real_adb_interaction: false } };
  let count = 1, background = false, resumed = false, now = Date.parse(NOW);
  const context = { report, diagnostic, clock: () => now,
    remaining() { options.remaining?.(report, diagnostic); },
    async control(path) {
      assert.equal(path, undefined); events.push(['control']);
      const value = liveStatus(structuredClone(products), count); options.control?.(value, report); return value;
    },
    async waitFor(check, milliseconds = 15000) {
      events.push(['wait', milliseconds]);
      for (let i = 0; i < (diagnostic.waitingFor === 'refresh_wait' ? 16 : 2); i++) {
        const value = await check(); if (value) return value;
      }
      throw new (adbFailure({}).constructor)('observation_deadline');
    },
    async snapshot() {
      const value = { schema: 3, kind: 'overmorrow-native-mounted-ui', package: PACKAGE, platform: 'android',
        profile: true, origin: 'http://127.0.0.1:43210',
        tables: Object.entries(products).map(([name, product]) => table(product, name)),
        labels: Object.values(products).flatMap(labels), current_lifecycle: background && !resumed ? 'paused' : 'resumed',
        lifecycle: resumed ? ['resumed', 'hidden', 'paused', 'resumed'] : ['resumed'],
        screen: { width: 1080, height: 1920, safe_area: { left: 0, top: 63, right: 1080, bottom: 1815 } },
        refresh: [{ enabled: true, visible: true, hit_testable: true, safe_target: true,
          x: 400, y: 800, scroll: { ancestors: 1, idle: true } }] };
      options.snapshot?.(value, report, diagnostic); return validateSnapshot(value);
    },
    async lifecycle() {
      const value = { schema: 1, kind: 'overmorrow-native-lifecycle',
        current_lifecycle: background && !resumed ? 'paused' : 'resumed',
        callback_state: background && !resumed ? 'paused' : 'resumed',
        callback_sequence: resumed ? 5 : background ? 4 : 1, guest_utc_ms: now };
      options.lifecycle?.(value, report, diagnostic); return value;
    },
    async adb(args) {
      events.push(['adb', ...args]); options.adb?.(args, report);
      if (args[2] === 'tap') count++;
      if (args[3] === 'KEYCODE_HOME') background = true;
      if (args[1] === 'am') { assert.deepEqual(args, ['shell', 'am', 'start', '-n', COMPONENT]); resumed = true; }
    },
    async sleep(ms) { events.push(['sleep', ms]); now += ms; options.sleep?.(ms, products); },
  };
  return { context, report, diagnostic, events, products, run: () => exerciseLiveNativeProducts(context) };
}

// Use the production observer loop with a virtual clock and serial, valid
// response snapshots. No Android, transport, provider or real elapsed wait.
function clockedLiveExercise(t, { responseMs = 10000, refreshPreparationMs = 0,
  lateControl = false, extraRequest = false } = {}) {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: Date.parse(NOW) });
  const deadline = Date.now() + 180000, starts = new Map(), states = [];
  const fixture = exercise({
    adb(args, report) {
      if (args[2] !== 'tap') return;
      if (report.phase === 'actual-refresh') t.mock.timers.tick(refreshPreparationMs);
      starts.set(report.phase, Date.now());
    },
    control(value, report) {
      const start = starts.get(report.phase);
      if (start === undefined || report.observations.before_background) return;
      const elapsed = Date.now() - start, count = value.calls.weather;
      // Weather completes before air quality is requested; both parsed JSON
      // products remain exactly the original response values and identities.
      value.calls.air_quality = elapsed < responseMs ? count - 1 : count;
      value.completed.weather = elapsed < responseMs ? count - 1 : count;
      value.completed.air_quality = elapsed < 2 * responseMs ? count - 1 : count;
      value.active = elapsed < 2 * responseMs;
      if (lateControl && report.phase === 'actual-refresh') {
        t.mock.timers.tick((lateControl === 'operation' ? start + 120000 : deadline) - Date.now());
        value.calls.air_quality = count;
        value.completed = { weather: count, air_quality: count };
        value.active = false;
      }
      if (extraRequest && report.phase === 'actual-refresh') value.calls.weather++;
      states.push({ phase: report.phase, elapsed, calls: { ...value.calls }, completed: { ...value.completed }, active: value.active });
    },
  });
  fixture.context.clock = Date.now;
  fixture.context.remaining = () => {
    if (Date.now() >= deadline) throw new (adbFailure({}).constructor)('trial_deadline');
  };
  const lifecycle = fixture.context.lifecycle, sleep = fixture.context.sleep;
  fixture.context.lifecycle = async () => ({ ...await lifecycle(), guest_utc_ms: Date.now() });
  fixture.context.sleep = async milliseconds => { await sleep(milliseconds); t.mock.timers.tick(milliseconds); };
  fixture.context.waitFor = (check, milliseconds = 15000) => {
    fixture.events.push(['wait', milliseconds]);
    return waitForObservation(check, deadline, fixture.context.remaining, milliseconds);
  };
  return { ...fixture, states, deadline, async settle() {
    let outcome;
    const pending = fixture.run().then(() => { outcome = { passed: true }; }, error => { outcome = { error }; });
    for (let i = 0; !outcome && i < 800; i++) {
      await new Promise(done => setImmediate(done));
      if (!outcome) t.mock.timers.tick(250);
    }
    assert.ok(outcome, 'the unchanged absolute driver deadline bounds the inert regression');
    await pending;
    return outcome;
  } };
}

test('live product rounds accept two serial valid responses after fifteen seconds within the original total deadline', async t => {
  const fixture = clockedLiveExercise(t), original = JSON.stringify(fixture.products);
  const result = await fixture.settle();
  assert.equal(result.error?.observerCode, undefined);
  assert.ifError(result.error);
  assert.equal(fixture.report.passed, true);
  assert.deepEqual(fixture.report.observations.requests, { weather: 3, air_quality: 3 });
  for (const phase of ['actual-refresh', 'background-resume-fresh']) {
    const states = fixture.states.filter(value => value.phase === phase);
    assert.ok(states.some(value => value.completed.weather > value.completed.air_quality && value.active));
    assert.ok(states.some(value => value.elapsed > 15000 && !value.active));
  }
  assert.ok(Date.now() < fixture.deadline);
  assert.equal(JSON.stringify(fixture.products), original);
  assert.equal(fixture.events.filter(event => event[0] === 'adb' && event[3] === 'tap').length, 2);
  assert.equal(fixture.report.joined_core_acceptance, false);
  assert.equal(fixture.report.scope.core_executed, false);
});

test('live operational observation retains absolute and per-round bounds and never accepts late or extra responses', async t => {
  for (const [name, options, code] of [
    ['preparation already consumed the total budget', { refreshPreparationMs: 165000 }, 'observation_deadline'],
    ['otherwise-valid control returns at the absolute deadline', { lateControl: 'global' }, 'trial_deadline'],
    ['otherwise-valid control returns at the operational deadline', { lateControl: 'operation' }, 'observation_deadline'],
    ['an extra GET is not completion evidence', { extraRequest: true }, 'validation_failed'],
  ]) await t.test(name, async sub => {
    const fixture = clockedLiveExercise(sub, options), result = await fixture.settle();
    assert.ok(result.error);
    recordDriverFailure(fixture.report, fixture.diagnostic, result.error);
    assert.equal(fixture.report.phase, 'actual-refresh');
    assert.equal(fixture.report.failure_diagnostic.code, code);
    assert.equal(fixture.report.passed, false);
    assert.equal(fixture.report.observations.refresh, undefined);
    assert.equal(fixture.report.checks.actual_tap_refresh, undefined);
    assert.equal(fixture.report.joined_core_acceptance, false);
    assert.equal(fixture.events.filter(event => event[0] === 'adb' && event[3] === 'tap').length, 1);
    if (options.refreshPreparationMs || options.lateControl === 'global') assert.equal(Date.now(), fixture.deadline);
    if (options.lateControl) {
      const late = fixture.states.at(-1);
      assert.deepEqual(late.completed, { weather: 2, air_quality: 2 });
      assert.equal(late.active, false); // A late positive snapshot still cannot pass.
    }
  });
});

test('live sequence retains 4/5 exact rows, two actual taps, same observer resume and original freshness without expiry/core claims', async () => {
  const fixture = exercise(), before = JSON.stringify(fixture.products); await fixture.run();
  assert.equal(fixture.report.passed, true); assert.equal(fixture.report.joined_core_acceptance, false);
  assert.equal(fixture.report.scope.core_executed, false); assert.equal(fixture.report.scope.overlay_proven, false);
  assert.equal(fixture.report.scope.expiry_proven, false);
  assert.deepEqual(fixture.report.observations.requests, { weather: 3, air_quality: 3 });
  for (const phase of ['initial', 'refresh', 'before_background', 'after_resume']) {
    assert.equal(fixture.report.observations[phase].weather.rows, 4); assert.equal(fixture.report.observations[phase].air_quality.rows, 5);
  }
  assert.equal(fixture.events.filter(event => event[0] === 'adb' && event[3] === 'tap').length, 2);
  assert.equal(fixture.events.filter(event => event[0] === 'adb' && event[2] === 'am').length, 1);
  assert.equal(fixture.events.filter(event => event[0] === 'sleep' && event[1] === 6000).length, 1);
  assert.equal(fixture.events.filter(event => event[0] === 'control').length, 4);
  const waits = fixture.events.filter(event => event[0] === 'wait');
  assert.equal(waits[0][1], 120000);
  assert.equal(waits.filter(event => event[1] === 120000).length, 3);
  assert.ok(waits.every(event => [15000, 120000].includes(event[1])));
  assert.equal(JSON.stringify(fixture.products), before);
  assert.ok(!JSON.stringify(fixture.report).includes('publisher_key'));
});
test('live refresh forbids re-acquisition, changed bytes/identity or expiry but permits unchanged real values', async () => {
  for (const change of [product => { product.forecast.source.acquired_at = '2026-10-12T02:00:01.000Z'; },
    product => { product.forecast.samples[0].temperature_2m = null; },
    product => { product.delivery.manifest_id = 'a'.repeat(64); },
    product => { product.delivery.revision++; },
    product => { product.delivery.publication_expires_at = '2026-10-12T02:02:01.000Z'; }]) {
    const fixture = exercise({ control(value, report) { if (report.phase === 'actual-refresh') change(value.products.weather); } });
    await assert.rejects(fixture.run()); assert.equal(fixture.report.passed, false);
  }
});
test('live products need completed responses, not request counts; no extra GET or non-null failure is accepted', async () => {
  for (const change of [value => { value.completed.air_quality = 0; value.products.air_quality = null; value.response_sha256.air_quality = null; },
    value => { value.active = true; }, value => { value.calls.weather = 4; },
    value => { value.terminal_failure = 'upstream_io'; }]) {
    const fixture = exercise({ control: change }); await assert.rejects(fixture.run()); assert.equal(fixture.report.passed, false);
  }
});
test('live background requires a new matching callback and still-valid host/guest after the original six seconds', async () => {
  for (const change of [value => { if (value.current_lifecycle === 'paused') value.callback_sequence = 1; },
    value => { if (value.current_lifecycle === 'paused') value.callback_state = 'resumed'; },
    value => { if (value.callback_sequence === 5) value.guest_utc_ms += 120000; }]) {
    const fixture = exercise({ lifecycle: change }); await assert.rejects(fixture.run()); assert.equal(fixture.report.passed, false);
  }
  const expired = exercise({ sleep(ms, products) {
    if (ms === 6000) for (const product of Object.values(products)) {
      product.freshness.expires_at = product.delivery.publication_expires_at = '2026-10-12T02:00:06.000Z';
    }
  } });
  await assert.rejects(expired.run()); assert.equal(expired.report.passed, false);
});
test('late HOME, post-resume response change and a new automatic fetch cannot become fresh-resume proof', async () => {
  const scenarios = [
    { lifecycle(value) { if (value.current_lifecycle === 'paused') value.guest_utc_ms += 120000; } },
    { control(value, report) { if (report.phase === 'background-resume-fresh' && report.observations.before_background) value.calls.air_quality = 4; } },
    { control(value, report) { if (report.phase === 'background-resume-fresh' && report.observations.before_background) value.response_sha256.weather = 'a'.repeat(64); } },
    { snapshot(value, _report, diagnostic) { if (diagnostic.subphase === 'resume_snapshot') value.tables[1].rows[0][1] = '999'; } },
  ];
  for (const scenario of scenarios) {
    const fixture = exercise(scenario); await assert.rejects(fixture.run()); assert.equal(fixture.report.passed, false);
  }
});
test('live mounted missing rows, stale labels and interruption remain failures with closed diagnostics', async () => {
  for (const options of [
    { snapshot(value) { value.tables[0].rows[0][1] = PRIVATE; } },
    { snapshot(value) { value.labels.push('Expired — refresh required; values are hidden'); } },
    { snapshot(value) { value.tables.pop(); } },
    { adb() { throw new (adbFailure({}).constructor)('interrupted'); } },
  ]) {
    const fixture = exercise(options);
    await assert.rejects(fixture.run(), error => {
      recordDriverFailure(fixture.report, fixture.diagnostic, error); return true;
    });
    assert.equal(fixture.report.passed, false); assert.equal(fixture.report.failure_diagnostic.schema, 5);
    assert.ok(!JSON.stringify(fixture.report).includes(PRIVATE));
  }
});
test('new fixture has no provider injection, phase setter, child spawn, clock writer or public raw-state export', async () => {
  const source = await readFile(new URL('./native-android-live-fixture.mjs', import.meta.url), 'utf8');
  for (const forbidden of ['fetchProvider:', 'fetchAirQualityProvider:', 'setPhase(', 'execFile(', 'spawn(', 'writeFile(']) assert.ok(!source.includes(forbidden));
  assert.match(source, /process\.argv\[2\], '--upstream-socket'/);
});
