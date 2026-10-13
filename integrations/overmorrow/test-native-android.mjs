// SPDX-License-Identifier: GPL-3.0-only
// Inert observer/fixture contracts: no adb, emulator, server, SDK or app launch.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { HEADERS, PACKAGE, COMPONENT, numberEqual, validateSnapshot, verifyTable, vmAddress,
  adbFailure, ObserverDiagnostic, observeVm, waitForObservation, startInstalledApp, resumeInstalledApp,
  recordDriverFailure, readFixtureControl, exerciseNativeProducts } from './native-android-driver.mjs';
import { nativeFixtureState, API_PORT, CONTROL_PORT } from './native-android-fixture.mjs';

const NOW = '2026-10-12T02:00:00.000Z';
function fixture() {
  const state = nativeFixtureState(NOW);
  return { state, weather: state.product(false, NOW), air_quality: state.product(true, NOW) };
}
function table(product, quality = false) {
  return { product: quality ? 'air_quality' : 'weather', headers: HEADERS[quality ? 'air_quality' : 'weather'],
    rows: product.forecast.samples.map(sample => [sample.valid_at,
      ...(quality ? [sample.pm2_5, sample.pm10] : [sample.temperature_2m,
        sample.wind_10m.speed, sample.wind_10m.direction_from, sample.precipitation.amount])
        .map(value => value === null ? 'Not available' : String(value)),
      ...(!quality ? [sample.precipitation.start_at === null ? 'Not available'
        : `${sample.precipitation.start_at} → ${sample.precipitation.end_at}`] : [])]) };
}
function snapshot(tables = []) {
  return { schema: 1, kind: 'overmorrow-native-mounted-ui', package: PACKAGE, platform: 'android',
    profile: true, origin: 'http://127.0.0.1:43210', tables, labels: [], refresh: [],
    lifecycle: ['resumed'], current_lifecycle: 'resumed', screen: { width: 1080, height: 1920 } };
}

test('fixture separates loopback API/control and makes no core claim', () => {
  assert.equal(API_PORT, 43210); assert.equal(CONTROL_PORT, 43211);
  const { state } = fixture(), status = state.status();
  assert.equal(status.core_executed, false); assert.equal(status.overlay_proven, false);
  assert.equal(status.synthetic_weather, true); assert.equal(status.synthetic_air_quality, true);
  assert.deepEqual(status.calls, { weather: 1, air_quality: 1 });
});
test('fixture phases require real prior requests and preserve missing values', () => {
  const state = nativeFixtureState(NOW);
  assert.throws(() => state.setPhase('refresh'));
  state.product(false, NOW); state.product(true, NOW); state.setPhase('refresh');
  const weather = state.product(false, NOW); state.product(true, NOW);
  assert.equal(weather.forecast.samples[0].temperature_2m, null);
  state.setPhase('short-lived');
  const short = state.product(false, NOW); state.product(true, NOW);
  assert.equal(Date.parse(short.freshness.expires_at) - Date.parse(NOW), 4500);
  assert.throws(() => state.product(false, NOW)); assert.throws(() => state.setPhase('initial'));
});
test('exact ordered weather and independent AQ rows pass', () => {
  const values = fixture();
  assert.equal(verifyTable(table(values.weather), values.weather).rows, 4);
  assert.equal(verifyTable(table(values.air_quality, true), values.air_quality).rows, 5);
  validateSnapshot(snapshot([table(values.weather), table(values.air_quality, true)]));
});
test('numeric comparison permits redundant decimals but no missing-to-zero coercion or rounding', () => {
  assert.equal(numberEqual('2.0', 2), true); assert.equal(numberEqual('20e-1', 2), true);
  assert.equal(numberEqual('Not available', null), true); assert.equal(numberEqual('0', null), false);
  assert.equal(numberEqual('2.0000000000000000001', 2), false);
  assert.equal(numberEqual('NaN', NaN), false); assert.equal(numberEqual('', 0), false);
});
test('time, order, rows, exact precipitation windows and missing values cannot be substituted', () => {
  const { weather } = fixture();
  for (const mutate of [value => value.rows.reverse(), value => value.rows.pop(),
    value => { value.rows[0][0] = '2026-10-12T00:00:01.000Z'; },
    value => { value.rows[1][5] = 'Not available'; },
    value => { value.rows[0][1] = '0'; }, value => value.headers.reverse()]) {
    const value = structuredClone(table(weather)); mutate(value);
    assert.throws(() => verifyTable(value, weather));
  }
});
test('duplicated or unknown mounted table ownership rejected', () => {
  const { weather } = fixture(), value = table(weather);
  assert.throws(() => validateSnapshot(snapshot([value, value])));
  assert.throws(() => validateSnapshot(snapshot([{ ...value, product: 'other' }])));
});
test('wrong app/profile/origin and unbounded data rejected', () => {
  for (const change of [{ package: 'other' }, { profile: false }, { origin: 'https://example.com' },
    { labels: ['x'.repeat(1025)] }, { lifecycle: Array(17).fill('resumed') },
    { screen: { width: 99999, height: 10 } }]) {
    assert.throws(() => validateSnapshot({ ...snapshot(), ...change }));
  }
});
test('visible refresh is bounded and carries independent hit-test observation', () => {
  const value = snapshot(); value.refresh = [{ x: 500, y: 900, enabled: true, visible: true, hit_testable: true }];
  validateSnapshot(value);
  delete value.refresh[0].hit_testable; assert.throws(() => validateSnapshot(value));
  value.refresh[0].hit_testable = false; value.refresh[0].x = -2;
  assert.throws(() => validateSnapshot(value));
});
test('VM address is one loopback service from bounded log text, never arbitrary authority', () => {
  const line = 'I/flutter ( 1234): The Dart VM service is listening on http://127.0.0.1:34567/Ab_c-123=/';
  assert.deepEqual(vmAddress(line, '1234'), { port: 34567, token: 'Ab_c-123=' });
  for (const value of [line + '\n' + line, line.replace('127.0.0.1', 'example.com'),
    line.replace('34567', '65536'), 'x'.repeat(65537)]) assert.throws(() => vmAddress(value, '1234'));
});
test('driver owns exact Android component and uses only observation RPC methods', async () => {
  assert.equal(COMPONENT, 'org.volparossa.weather.trial/com.marotidev.overmorrow.MainActivity');
  const source = await readFile(new URL('./native-android-driver.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes("['getVM', EXTENSION].includes(method)"));
  assert.ok(!source.includes("vm.request('getIsolate'"));
  assert.ok(source.includes("['shell', 'input', 'tap'"));
  assert.ok(source.includes("['shell', 'input', 'keyevent', 'KEYCODE_HOME']"));
  assert.ok(source.includes('pixel_visibility_proven: false'));
  assert.ok(!source.includes("vm.request('evaluate'"));
  assert.ok(!source.includes('report.token') && !source.includes('report.logs'));
});

// These transports are inert EventTargets, not a VM/app success substitute.
const PRIVATE_TEXT = 'private-token http://127.0.0.1:43212/private/ /private/owner';
const VM_LINE = 'The Dart VM service is listening on http://127.0.0.1:34567/private-token/';
const EXTENSION = 'ext.volparossa.native_snapshot';
const flush = () => new Promise(done => setImmediate(done));
function observerFixture(options = {}) {
  const diagnostic = options.diagnostic ?? new ObserverDiagnostic(), calls = [], owned = [], requests = [];
  let vm;
  class Socket extends EventTarget {
    readyState = WebSocket.CONNECTING;
    constructor() {
      super();
      if (options.construct) throw options.construct;
      setImmediate(() => {
        if (options.connect === 'pending') return;
        this.readyState = options.connect === 'error' ? WebSocket.CLOSED : WebSocket.OPEN;
        this.dispatchEvent(new Event(options.connect === 'error' ? 'error' : 'open'));
      });
    }
    send(raw) {
      const request = JSON.parse(raw); calls.push(request.method); requests.push(request);
      setImmediate(() => {
        if (options.pending === request.method) return;
        if (options.close === request.method) { this.close(); return; }
        const result = request.method === 'getVM' ? (options.machine ?? { isolates: [{ id: 'isolates/12' }] })
          : (Object.hasOwn(options, 'snapshot') ? options.snapshot : snapshot());
        let data = options.malformed === request.method ? PRIVATE_TEXT
          : JSON.stringify({ jsonrpc: '2.0', id: request.id,
            ...(options.reject === request.method ? { error: { message: PRIVATE_TEXT } } : { result }) });
        if (options.message) data = options.message(request, data);
        this.dispatchEvent(new MessageEvent('message', { data }));
      });
    }
    close() { this.readyState = WebSocket.CLOSED; queueMicrotask(() => this.dispatchEvent(new Event('close'))); }
  }
  const context = { pid: options.pid ?? '1234', diagnostic, Socket,
    async adb(args) {
      calls.push(args[0]);
      if (options.adb === args[0] && calls.filter(value => value === args[0]).length >= (options.adbAfter ?? 1)) {
        throw adbFailure(options.error ?? { code: 1, stderr: PRIVATE_TEXT });
      }
      return args[0] === 'logcat' ? (options.log ?? VM_LINE) : (options.port ?? '45678');
    },
    waitFor: check => waitForObservation(check, Date.now() + 180000,
      options.remaining ?? (() => {}), options.wait ?? 15000),
    ownForward(value) { owned.push(value === null ? 'forward-unconfirmed' : 'forward-owned'); },
    ownVm(value) { vm = value; owned.push('vm-owned'); },
  };
  return { diagnostic, calls, owned, requests, run: () => observeVm(context),
    get vm() { return vm; },
    async close() { if (vm) await vm.close(); } };
}
async function rejectedObserver(fixture) {
  let error;
  try { await fixture.run(); } catch (value) { error = value; }
  assert.ok(error, 'inert transport must fail');
  const receipt = fixture.diagnostic.failure(error);
  assert.deepEqual(Object.keys(receipt).sort(), ['schema', 'subphase', 'code', 'adb_exit_status',
    'adb_signal', 'cause_established', 'raw_output_retained'].sort());
  assert.equal(receipt.cause_established, false); assert.equal(receipt.raw_output_retained, false);
  assert.ok(Buffer.byteLength(JSON.stringify(receipt)) <= 512);
  for (const secret of ['private-token', 'http://', '/private/', '43212']) {
    assert.ok(!JSON.stringify(receipt).includes(secret));
  }
  await fixture.close();
  return receipt;
}

test('observer production sequence uses only read-only RPCs and transfers cleanup ownership before connection', async () => {
  const fixture = observerFixture();
  assert.equal(await fixture.run(), 'isolates/12');
  assert.deepEqual(fixture.calls, ['logcat', 'forward', 'getVM', EXTENSION]);
  assert.deepEqual(fixture.owned, ['forward-unconfirmed', 'forward-owned', 'vm-owned']);
  assert.equal(fixture.diagnostic.waitingFor, null);
  await fixture.close();
});

// Exact pinned Dart serializers, not arbitrary JSON-RPC error-code retries.
function missingExtension(request) {
  return { code: -32601, message: 'Method not found',
    data: { request: { method: request.method, params: request.params } } };
}
function snapshotPending() {
  return { code: -32000, message: 'Server error', data: { details: 'Snapshot not ready' } };
}
function errorMessage(request, error) {
  return JSON.stringify({ jsonrpc: '2.0', id: request.id, error });
}
test('readiness retries only the exact absent extension and own pending snapshot until validated', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  let attempts = 0, settled = false;
  const fixture = observerFixture({ message(request, normal) {
    if (request.method !== EXTENSION || ++attempts > 2) return normal;
    return errorMessage(request, attempts === 1 ? missingExtension(request) : snapshotPending());
  } });
  const result = fixture.run().then(value => { settled = true; return value; });
  for (let i = 0; i < 8; i++) await flush();
  assert.equal(attempts, 1); assert.equal(settled, false);
  t.mock.timers.tick(250);
  for (let i = 0; i < 8; i++) await flush();
  assert.equal(attempts, 2); assert.equal(settled, false);
  t.mock.timers.tick(250);
  assert.equal(await result, 'isolates/12');
  assert.equal(attempts, 3);
  assert.deepEqual(fixture.calls, ['logcat', 'forward', ...Array(3).fill(['getVM', EXTENSION]).flat()]);
  assert.ok(fixture.requests.filter(row => row.method === EXTENSION)
    .every(row => JSON.stringify(row.params) === '{"isolateId":"isolates/12"}'));
  await fixture.close();
});
test('near-match errors, wrong RPC context and unexpected envelope data remain fatal and redacted', async () => {
  const variants = [
    request => ({ ...missingExtension(request), code: -32602 }),
    request => ({ ...missingExtension(request), message: PRIVATE_TEXT }),
    request => ({ ...missingExtension(request), data: null }),
    request => ({ ...missingExtension(request), data: { request: { method: 'getVM', params: request.params } } }),
    request => ({ ...missingExtension(request), data: { request: { method: EXTENSION, params: { isolateId: 'isolates/99' } } } }),
    request => ({ ...missingExtension(request), data: { request: { method: EXTENSION, params: { ...request.params, extra: PRIVATE_TEXT } } } }),
    request => ({ ...missingExtension(request), data: { ...missingExtension(request).data, details: PRIVATE_TEXT } }),
    () => ({ ...snapshotPending(), code: -32001 }),
    () => ({ ...snapshotPending(), message: 'Extension error' }),
    () => ({ ...snapshotPending(), data: { details: PRIVATE_TEXT } }),
    () => ({ ...snapshotPending(), data: { details: 'Snapshot not ready', extra: PRIVATE_TEXT } }),
    () => ({ ...snapshotPending(), extra: PRIVATE_TEXT }),
    () => null, () => [], () => false,
  ];
  for (const variant of variants) {
    const fixture = observerFixture({ message: (request, normal) => request.method === EXTENSION
      ? errorMessage(request, variant(request)) : normal });
    const receipt = await rejectedObserver(fixture);
    assert.equal(receipt.subphase, 'native_snapshot'); assert.equal(receipt.code, 'vm_request_rejected');
    assert.equal(fixture.requests.length, 2);
  }
  for (const error of [missingExtension, snapshotPending]) {
    const fixture = observerFixture({ message: request => errorMessage(request, error(request)) });
    const receipt = await rejectedObserver(fixture);
    assert.equal(receipt.subphase, 'get_vm'); assert.equal(receipt.code, 'vm_request_rejected');
    assert.equal(fixture.requests.length, 1);
  }
  for (const change of [{ extra: PRIVATE_TEXT }, { result: snapshot() }, { jsonrpc: '1.0' }]) {
    const fixture = observerFixture({ message: (request, normal) => request.method === EXTENSION
      ? JSON.stringify({ jsonrpc: '2.0', id: request.id, error: snapshotPending(), ...change }) : normal });
    const receipt = await rejectedObserver(fixture);
    assert.equal(receipt.subphase, 'native_snapshot');
    assert.equal(receipt.code, Object.hasOwn(change, 'extra') ? 'vm_request_rejected' : 'vm_response_invalid');
  }
});
test('extension readiness validates the same snapshot identity, bounds and shape without claiming final tables', async () => {
  for (const value of [null, [], {}, { ...snapshot(), package: 'other' }, { ...snapshot(), profile: false },
    { ...snapshot(), origin: PRIVATE_TEXT }, { ...snapshot(), tables: Array(5).fill({}) },
    { ...snapshot(), labels: [PRIVATE_TEXT.repeat(100)] }]) {
    const receipt = await rejectedObserver(observerFixture({ snapshot: value }));
    assert.equal(receipt.subphase, 'native_snapshot'); assert.equal(receipt.code, 'validation_failed');
  }
  // Empty tables are valid only as readiness, not a replacement for collect/verifyTable.
  const fixture = observerFixture({ snapshot: snapshot() });
  assert.equal(await fixture.run(), 'isolates/12');
  const source = await readFile(new URL('./native-android-driver.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes('verifyTable(table, expected.products[table.product])'));
  await fixture.close();
});
test('VM type, byte bound, JSON and envelope errors have distinct closed codes at the actual request', async () => {
  for (const [data, code] of [[new Uint8Array([1]), 'vm_response_type'],
    [new Blob([PRIVATE_TEXT]), 'vm_response_type'], ['x'.repeat(131073), 'vm_response_bound'],
    ['é'.repeat(65537), 'vm_response_bound'], [PRIVATE_TEXT, 'vm_response_json'],
    ['null', 'vm_response_invalid'], ['[]', 'vm_response_invalid']]) {
    const fixture = observerFixture({ message: (request, normal) => request.method === EXTENSION ? data : normal });
    const receipt = await rejectedObserver(fixture);
    assert.equal(receipt.code, code); assert.equal(receipt.subphase, 'native_snapshot');
    assert.equal(fixture.vm.socket.readyState, WebSocket.CLOSED);
  }
  for (const extra of [0, 1]) {
    const fixture = observerFixture({ message(request, normal) {
      return request.method === EXTENSION ? normal + ' '.repeat(131072 - Buffer.byteLength(normal) + extra) : normal;
    } });
    if (extra) assert.equal((await rejectedObserver(fixture)).code, 'vm_response_bound');
    else { assert.equal(await fixture.run(), 'isolates/12'); await fixture.close(); }
  }
});
test('readiness remains within 15s even for exact pending errors or a late valid snapshot', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  for (const error of [missingExtension, snapshotPending]) {
    const fixture = observerFixture({ message: (request, normal) => request.method === EXTENSION
      ? errorMessage(request, error(request)) : normal });
    const result = rejectedObserver(fixture);
    for (let i = 0; i < 8; i++) await flush();
    t.mock.timers.tick(15000);
    const receipt = await result;
    assert.equal(receipt.code, 'observation_deadline'); assert.equal(receipt.subphase, 'isolate_wait');
    assert.equal(fixture.requests.length, 2);
  }
  const fixture = observerFixture({ message(request, normal) {
    if (request.method === EXTENSION) t.mock.timers.setTime(Date.now() + 15000);
    return normal;
  } });
  const receipt = await rejectedObserver(fixture);
  assert.equal(receipt.code, 'observation_deadline'); assert.equal(receipt.subphase, 'isolate_wait');
});
test('selected snapshot isolate and VM stay identical for subsequent lifecycle observations', async () => {
  const fixture = observerFixture({ machine: { isolates: [{ id: 'isolates/11' }, { id: 'isolates/12' }] },
    message: (request, normal) => request.params.isolateId === 'isolates/11'
      ? errorMessage(request, missingExtension(request)) : normal });
  const isolate = await fixture.run(); assert.equal(isolate, 'isolates/12');
  assert.equal(fixture.owned.filter(value => value === 'vm-owned').length, 1);
  const vm = fixture.vm;
  await resumeInstalledApp({ async adb(args) { assert.deepEqual(args, ['shell', 'am', 'start', '-n', COMPONENT]); },
    async waitFor(check) { assert.equal(await check(), null); },
    async snapshot() { return validateSnapshot(await vm.request(EXTENSION, { isolateId: isolate })); } });
  assert.equal(fixture.vm, vm);
  assert.deepEqual(fixture.requests.at(-1).params, { isolateId: 'isolates/12' });
  await fixture.close();
});
test('pending extension errors outside readiness remain rejected and never become lifecycle observations', async () => {
  let ready = false;
  const fixture = observerFixture({ message: (request, normal) => ready && request.method === EXTENSION
    ? errorMessage(request, snapshotPending()) : normal });
  const isolate = await fixture.run(); ready = true;
  await assert.rejects(fixture.vm.request(EXTENSION, { isolateId: isolate }), error => {
    assert.equal(error.observerCode, 'vm_request_rejected');
    assert.equal(error.extensionPending, true);
    assert.ok(!JSON.stringify(fixture.diagnostic.failure(error)).includes('Snapshot not ready'));
    return true;
  });
  await fixture.close();
});
test('interruption during a successful snapshot response remains fatal before readiness returns', async () => {
  let interrupted = false;
  const Failure = adbFailure({}).constructor;
  const fixture = observerFixture({ remaining() { if (interrupted) throw new Failure('interrupted'); },
    message(request, normal) { if (request.method === EXTENSION) interrupted = true; return normal; } });
  const receipt = await rejectedObserver(fixture);
  assert.equal(receipt.code, 'interrupted'); assert.equal(receipt.subphase, 'native_snapshot');
  assert.equal(fixture.requests.length, 2);
  assert.deepEqual(fixture.owned, ['forward-unconfirmed', 'forward-owned', 'vm-owned']);
});
test('ADB metadata is a closed bounded classification and never carries raw callback text', () => {
  const diagnostic = new ObserverDiagnostic();
  for (const [error, code, exit, signal] of [
    [{ code: 1 }, 'adb_exit', 1, null], [{ code: 999999 }, 'adb_exit', null, null],
    [{ signal: 'SIGKILL', killed: true }, 'adb_signal', null, 'SIGKILL'],
    [{ signal: 'SIGTERM' }, 'adb_signal', null, 'SIGTERM'],
    [{ code: 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' }, 'adb_output_bound', null, null],
    [{ code: 'ENOENT' }, 'adb_spawn_failed', null, null], [{ code: 'EACCES' }, 'adb_spawn_failed', null, null],
    [{ code: PRIVATE_TEXT, signal: PRIVATE_TEXT }, 'adb_failed', null, null],
  ]) {
    const receipt = diagnostic.failure(adbFailure({ ...error, message: PRIVATE_TEXT, stdout: PRIVATE_TEXT, stderr: PRIVATE_TEXT }));
    assert.equal(receipt.code, code); assert.equal(receipt.adb_exit_status, exit); assert.equal(receipt.adb_signal, signal);
    assert.ok(!JSON.stringify(receipt).includes('private'));
  }
  assert.equal(diagnostic.failure(new Error(PRIVATE_TEXT)).code, 'unknown');
  const tampered = adbFailure({ code: 1 });
  tampered.observerCode = tampered.exitStatus = tampered.signal = diagnostic.subphase = PRIVATE_TEXT;
  assert.deepEqual(diagnostic.failure(tampered), { schema: 1, subphase: 'unobserved', code: 'unknown',
    adb_exit_status: null, adb_signal: null, cause_established: false, raw_output_retained: false });
});
test('each existing observer boundary reports its own failing subphase without secret values', async () => {
  for (const [options, subphase, code] of [
    [{ adb: 'logcat' }, 'logcat_read', 'adb_exit'],
    [{ adb: 'forward' }, 'forward_create', 'adb_exit'],
    [{ port: PRIVATE_TEXT }, 'forward_port', 'validation_failed'],
    [{ construct: new Error(PRIVATE_TEXT) }, 'websocket_create', 'unknown'],
    [{ connect: 'error' }, 'websocket_connect', 'websocket_failed'],
    [{ reject: 'getVM' }, 'get_vm', 'vm_request_rejected'],
    [{ reject: EXTENSION }, 'native_snapshot', 'vm_request_rejected'],
    [{ machine: { isolates: Array(9).fill({ id: 'isolates/12' }) } }, 'get_vm', 'validation_failed'],
    [{ machine: { isolates: null } }, 'get_vm', 'response_type_invalid'],
    [{ machine: { isolates: [{ id: PRIVATE_TEXT }] } }, 'isolate_identity', 'validation_failed'],
    [{ malformed: 'getVM' }, 'get_vm', 'vm_response_json'],
    [{ close: EXTENSION }, 'native_snapshot', 'vm_connection_closed'],
  ]) {
    const receipt = await rejectedObserver(observerFixture(options));
    assert.equal(receipt.subphase, subphase); assert.equal(receipt.code, code);
  }
});
test('a later address poll failure belongs to that ADB read rather than the earlier parser attempt', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const fixture = observerFixture({ log: PRIVATE_TEXT, adb: 'logcat', adbAfter: 2 });
  const result = rejectedObserver(fixture);
  await flush(); assert.equal(fixture.diagnostic.subphase, 'vm_address');
  t.mock.timers.tick(250);
  const receipt = await result;
  assert.equal(receipt.subphase, 'logcat_read'); assert.equal(receipt.code, 'adb_exit');
  assert.equal(fixture.calls.length, 2); assert.deepEqual(fixture.owned, []);
});
test('original WebSocket 5s and VM request 3s deadlines remain bounded and distinguishable', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  for (const [options, milliseconds, subphase, code] of [
    [{ connect: 'pending' }, 5000, 'websocket_connect', 'websocket_deadline'],
    [{ pending: 'getVM' }, 3000, 'get_vm', 'vm_request_deadline'],
    [{ pending: EXTENSION }, 3000, 'native_snapshot', 'vm_request_deadline'],
  ]) {
    const fixture = observerFixture(options), result = rejectedObserver(fixture);
    for (let i = 0; i < 5; i++) await flush();
    t.mock.timers.tick(milliseconds - 1); await flush();
    assert.equal(fixture.diagnostic.subphase, subphase);
    t.mock.timers.tick(1);
    const receipt = await result; assert.equal(receipt.subphase, subphase); assert.equal(receipt.code, code);
  }
});
test('address/isolate observation expiry identifies the wait, not stale prior RPC or sensitive log text', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  for (const [options, stage] of [[{ log: PRIVATE_TEXT }, 'vm_address'], [{ machine: { isolates: [] } }, 'isolate_wait']]) {
    const fixture = observerFixture(options), result = rejectedObserver(fixture);
    for (let i = 0; i < 5; i++) await flush();
    t.mock.timers.tick(15000);
    const receipt = await result;
    assert.equal(receipt.subphase, stage); assert.equal(receipt.code, 'observation_deadline');
  }
});
test('diagnostic snapshot is frozen before cleanup and cannot be relabeled by later operations', async () => {
  const fixture = observerFixture({ adb: 'forward' });
  const receipt = await rejectedObserver(fixture), before = JSON.stringify(receipt);
  await fixture.diagnostic.at('logcat_read', () => {});
  fixture.diagnostic.failure(adbFailure({ signal: 'SIGKILL' }));
  assert.equal(JSON.stringify(receipt), before);
  const source = await readFile(new URL('./native-android-driver.mjs', import.meta.url), 'utf8');
  assert.ok(source.indexOf('recordDriverFailure(report, diagnostic, error);') < source.indexOf('if (vm) try'));
  assert.ok(source.includes("['installed-app', 'read-only-observer'].includes(report.phase)"));
  assert.ok(source.includes('timeout: 8000, killSignal: \'SIGKILL\', maxBuffer: 65536'));
  assert.ok(source.includes('deadline = started + 180000'));
});

function installedFixture(options = {}) {
  const diagnostic = new ObserverDiagnostic(), calls = [];
  const report = { passed: false, phase: 'installed-app', scope: { installed_android_app: false } };
  let appOwned = false;
  return { diagnostic, report, calls, owned: () => appOwned,
    async run() {
      try {
        return await startInstalledApp({ diagnostic,
          waitFor: check => waitForObservation(check, options.deadline ?? Date.now() + 180000,
            options.remaining ?? (() => {})),
          async adb(args) {
            const operation = args[1] === 'pm' ? 'package_check' : args[1] === 'pidof' ? 'pidof'
              : args[2] === 'force-stop' ? 'force_stop' : 'app_start';
            calls.push({ operation, args, appOwned });
            if (options.fail === operation) throw adbFailure(options.error ?? { code: 1, stdout: PRIVATE_TEXT, stderr: PRIVATE_TEXT },
              { args, stdout: options.stdout, stderr: options.stderr });
            if (operation === 'package_check') return options.package ?? 'package:/data/app/private/base.apk';
            if (operation === 'pidof' && options.readPid) return options.readPid(args);
            return operation === 'pidof' ? (options.pid ?? '1234') : '';
          },
          installed() { report.scope.installed_android_app = true; }, ownApp() { appOwned = true; },
        });
      } catch (error) { recordDriverFailure(report, diagnostic, error); throw error; }
    },
  };
}
test('installed-app helper preserves exact command sequence, validation and cleanup ownership', async () => {
  const fixture = installedFixture();
  assert.equal(await fixture.run(), '1234');
  assert.deepEqual(fixture.calls.map(row => row.args), [
    ['shell', 'pm', 'path', PACKAGE], ['shell', 'am', 'force-stop', PACKAGE],
    ['shell', 'am', 'start', '-n', COMPONENT], ['shell', 'pidof', PACKAGE],
  ]);
  assert.deepEqual(fixture.calls.map(row => row.appOwned), [false, false, true, true]);
  assert.equal(fixture.report.scope.installed_android_app, true);
  assert.equal(fixture.report.passed, false); // This helper alone is not app acceptance.
  assert.ok(!Object.hasOwn(fixture.report, 'failure_diagnostic'));
});
test('every installed-app command failure reports only its own closed boundary and preserves ownership', async () => {
  for (const [phase, installed, owned, commands] of [
    ['package_check', false, false, 1], ['force_stop', true, false, 2],
    ['app_start', true, true, 3], ['pidof', true, true, 4],
  ]) {
    const fixture = installedFixture({ fail: phase });
    await assert.rejects(fixture.run());
    assert.equal(fixture.calls.length, commands);
    assert.equal(fixture.report.scope.installed_android_app, installed); assert.equal(fixture.owned(), owned);
    assert.equal(fixture.report.failure, 'NATIVE_TRIAL_PHASE_FAILED');
    assert.equal(fixture.report.failure_diagnostic.subphase, phase);
    assert.equal(fixture.report.failure_diagnostic.code, 'adb_exit');
    assert.equal(fixture.report.failure_diagnostic.adb_exit_status, 1);
    assert.ok(Buffer.byteLength(JSON.stringify(fixture.report.failure_diagnostic)) <= 512);
    assert.ok(!JSON.stringify(fixture.report).includes('private'));
    assert.equal(fixture.report.passed, false);
  }
});
test('package and PID outputs retain their original strict rejection without exporting the value', async () => {
  for (const [options, subphase, installed, owned] of [
    [{ package: PRIVATE_TEXT }, 'package_check', false, false],
    [{ pid: PRIVATE_TEXT }, 'pid_validation', true, true],
    [{ pid: '1234\n1235' }, 'pid_validation', true, true],
    [{ pid: '1234 1234' }, 'pid_validation', true, true],
    [{ pid: '0' }, 'pid_validation', true, true],
    [{ pid: '123456789' }, 'pid_validation', true, true],
    [{ pid: '' }, 'pid_validation', true, true],
  ]) {
    const fixture = installedFixture(options); await assert.rejects(fixture.run());
    assert.equal(fixture.report.scope.installed_android_app, installed); assert.equal(fixture.owned(), owned);
    assert.equal(fixture.report.failure_diagnostic.subphase, subphase);
    assert.equal(fixture.report.failure_diagnostic.code, 'validation_failed');
    for (const value of ['private', '1234', '1235', 'http://']) assert.ok(!JSON.stringify(fixture.report).includes(value));
  }
});
test('failure publisher keeps historical startup schema and resets product-phase observations', async () => {
  const diagnostic = new ObserverDiagnostic();
  await diagnostic.at('get_isolate', () => {});
  for (const phase of ['installed-app', 'read-only-observer']) {
    const report = { phase, passed: false };
    recordDriverFailure(report, diagnostic, adbFailure({ signal: 'SIGKILL' }));
    assert.equal(report.failure_diagnostic.schema, 1);
    assert.equal(report.failure_diagnostic.code, 'adb_signal'); assert.equal(report.failure_diagnostic.adb_signal, 'SIGKILL');
  }
  for (const phase of ['initial-native-products', 'actual-refresh', 'background-resume-expiry']) {
    const report = { phase, passed: false };
    diagnostic.beginProducts(1);
    recordDriverFailure(report, diagnostic, new TypeError(PRIVATE_TEXT));
    assert.equal(report.failure, 'NATIVE_TRIAL_PHASE_FAILED');
    assert.equal(report.failure_diagnostic.schema, 3);
    assert.equal(report.failure_diagnostic.subphase, 'unobserved');
    assert.equal(report.failure_diagnostic.progress.weather_requests_observed, null);
  }
});
test('interruption before the first observer query cannot inherit installed PID validation', async () => {
  const fixture = installedFixture();
  const pid = await fixture.run();
  assert.equal(fixture.diagnostic.subphase, 'pid_validation');
  fixture.report.phase = 'read-only-observer';
  // Use the existing closed error type without exposing a new production API.
  const Failure = adbFailure({}).constructor, interrupted = new Failure('interrupted');
  let checks = 0;
  try {
    await observeVm({ pid, diagnostic: fixture.diagnostic,
      async waitFor() { throw interrupted; },
      async adb() { checks++; }, ownForward() { checks++; }, ownVm() { checks++; },
    });
    assert.fail('the pre-query interruption must propagate');
  } catch (error) {
    assert.equal(error, interrupted);
    recordDriverFailure(fixture.report, fixture.diagnostic, error);
  }
  assert.equal(checks, 0); assert.equal(fixture.owned(), true);
  assert.equal(fixture.report.scope.installed_android_app, true);
  assert.equal(fixture.report.failure_diagnostic.subphase, 'unobserved');
  assert.equal(fixture.report.failure_diagnostic.code, 'interrupted');
  assert.equal(fixture.report.passed, false);
});

function absentPid(args = ['shell', 'pidof', PACKAGE]) {
  return adbFailure({ code: 1, signal: null, killed: false }, { args, stdout: '', stderr: '' });
}
test('only exact pidof exit 1 with complete empty streams and no kill is an in-memory absence', () => {
  const diagnostic = new ObserverDiagnostic(), args = ['shell', 'pidof', PACKAGE];
  const absence = absentPid(); assert.equal(absence.pidAbsent, true);
  const receipt = diagnostic.failure(absence);
  assert.equal(receipt.code, 'adb_exit'); assert.equal(receipt.adb_exit_status, 1);
  assert.ok(!Object.hasOwn(receipt, 'pidAbsent'));
  for (const [error, context] of [
    [{ code: 1 }, { args, stdout: '', stderr: '' }],
    [{ code: 1, signal: null }, { args, stdout: '', stderr: '' }],
    [{ code: 1, signal: null, killed: true }, { args, stdout: '', stderr: '' }],
    [{ code: 1, signal: 'SIGKILL', killed: false }, { args, stdout: '', stderr: '' }],
    [{ code: 2, signal: null, killed: false }, { args, stdout: '', stderr: '' }],
    [{ code: 1, signal: null, killed: false }, { args, stdout: '', stderr: PRIVATE_TEXT }],
    [{ code: 1, signal: null, killed: false }, { args, stdout: '1234', stderr: '' }],
    [{ code: 1, signal: null, killed: false }, { args, stdout: '', stderr: '\n' }],
    [{ code: 1, signal: null, killed: false }, { args, stdout: '' }],
    [{ code: 1, signal: null, killed: false }, { args: ['shell', 'pidof', 'other'], stdout: '', stderr: '' }],
    [{ code: 1, signal: null, killed: false }, { args: [...args, '-s'], stdout: '', stderr: '' }],
    [{ code: 1, signal: null, killed: false }, { args: ['shell', 'am', 'start'], stdout: '', stderr: '' }],
  ]) {
    const failure = adbFailure(error, context); assert.equal(failure.pidAbsent, false);
    assert.ok(!JSON.stringify(diagnostic.failure(failure)).includes('private'));
  }
});
test('one actual helper launch polls absent PID then continues into the unchanged read-only observer', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  let reads = 0;
  const fixture = installedFixture({ readPid(args) { if (++reads < 3) throw absentPid(args); return '1234'; } });
  const result = fixture.run();
  await flush(); assert.equal(reads, 1); assert.equal(fixture.owned(), true);
  t.mock.timers.tick(250); await flush(); assert.equal(reads, 2);
  t.mock.timers.tick(250); const pid = await result;
  assert.equal(pid, '1234'); assert.equal(fixture.diagnostic.waitingFor, null);
  assert.equal(fixture.calls.filter(row => row.operation === 'app_start').length, 1);
  assert.equal(fixture.calls.filter(row => row.operation === 'force_stop').length, 1);
  assert.ok(fixture.calls.filter(row => row.operation === 'pidof').every(row => row.appOwned));
  const observer = observerFixture({ pid, diagnostic: fixture.diagnostic });
  assert.equal(await observer.run(), 'isolates/12');
  assert.deepEqual(observer.calls, ['logcat', 'forward', 'getVM', EXTENSION]);
  await observer.close(); assert.equal(fixture.report.passed, false);
});
test('PID polling does not hide transport errors, missing metadata, killed commands or forged absence', async () => {
  const args = ['shell', 'pidof', PACKAGE];
  const failures = [
    adbFailure({ code: 1, signal: null, killed: false }, { args, stdout: '', stderr: PRIVATE_TEXT }),
    adbFailure({ code: 1, signal: null, killed: false }, { args, stdout: '1234', stderr: '' }),
    adbFailure({ code: 1 }), adbFailure({ code: 1, signal: null, killed: true }, { args, stdout: '', stderr: '' }),
    adbFailure({ code: 2 }), adbFailure({ signal: 'SIGKILL' }),
    adbFailure({ code: 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' }),
    { observerCode: 'adb_exit', exitStatus: 1, signal: null, pidAbsent: true },
  ];
  for (const failure of failures) {
    const fixture = installedFixture({ readPid() { throw failure; } });
    await assert.rejects(fixture.run(), error => error === failure);
    assert.equal(fixture.calls.length, 4); assert.equal(fixture.owned(), true);
    assert.equal(fixture.report.failure_diagnostic.subphase, 'pidof');
    assert.equal(fixture.report.passed, false);
  }
});
test('absent PID expires in the original 15s observation window without relaunch', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const fixture = installedFixture({ readPid(args) { throw absentPid(args); } });
  const result = assert.rejects(fixture.run(), error => error.observerCode === 'observation_deadline');
  await flush(); t.mock.timers.tick(15000); await result;
  assert.equal(fixture.calls.length, 4); assert.equal(fixture.owned(), true);
  assert.equal(fixture.report.failure_diagnostic.subphase, 'pidof');
  assert.equal(fixture.report.failure_diagnostic.code, 'observation_deadline');
});
test('PID returned at or after observation/global deadline is rejected with ownership retained', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const Failure = adbFailure({}).constructor;
  for (const [elapsed, global, code] of [[15000, 180000, 'observation_deadline'],
    [15001, 180000, 'observation_deadline'], [1000, 1000, 'trial_deadline']]) {
    let resolvePid;
    const deadline = Date.now() + global;
    const fixture = installedFixture({ deadline,
      remaining() { if (Date.now() >= deadline) throw new Failure('trial_deadline'); },
      readPid() { return new Promise(resolve => { resolvePid = resolve; }); } });
    const result = assert.rejects(fixture.run(), error => error.observerCode === code);
    await flush(); assert.equal(typeof resolvePid, 'function');
    t.mock.timers.tick(elapsed); resolvePid('1234'); await result;
    assert.equal(fixture.calls.length, 4); assert.equal(fixture.owned(), true);
    assert.equal(fixture.report.passed, false);
  }
});
test('interruptions before or during a PID query cannot become successful startup', async () => {
  const Failure = adbFailure({}).constructor;
  for (const before of [true, false]) {
    let interrupted = before, resolvePid;
    const error = new Failure('interrupted');
    const fixture = installedFixture({ remaining() { if (interrupted) throw error; },
      readPid() { return new Promise(resolve => { resolvePid = resolve; }); } });
    const result = assert.rejects(fixture.run(), failure => failure === error);
    await flush();
    if (!before) { interrupted = true; resolvePid('1234'); }
    await result;
    assert.equal(fixture.calls.length, before ? 3 : 4); assert.equal(fixture.owned(), true);
    assert.equal(fixture.report.failure_diagnostic.code, 'interrupted');
    assert.equal(fixture.report.passed, false);
  }
});
test('resume dispatch uses the original snapshot closure and requires actual paused then resumed state', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const calls = [], values = [snapshot(), { ...snapshot(), lifecycle: ['resumed', 'paused'], current_lifecycle: 'paused' },
    { ...snapshot(), lifecycle: ['resumed', 'paused', 'resumed'] }];
  let reads = 0;
  const result = resumeInstalledApp({ async adb(args) { calls.push(args); },
    waitFor: check => waitForObservation(check, Date.now() + 180000, () => {}),
    async snapshot() { return values[reads++]; } });
  await flush(); assert.equal(reads, 1);
  t.mock.timers.tick(250); await flush(); assert.equal(reads, 2);
  t.mock.timers.tick(250); assert.equal(await result, values[2]);
  assert.deepEqual(calls, [['shell', 'am', 'start', '-n', COMPONENT]]);
  const source = await readFile(new URL('./native-android-driver.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes('resumeInstalledApp({ adb, waitFor, snapshot })'));
  assert.ok(source.includes('await vm.request(EXTENSION, { isolateId: isolate })'));
  assert.ok(source.includes('assert.equal(resumed.tables.length, 0)'));
  assert.ok(source.includes('assert.deepEqual(final.calls, { weather: 3, air_quality: 3 })'));
  assert.ok(!source.includes("'start', '-W'"));
});
test('resume launch errors and missing or late lifecycle observations never become readiness', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const failure = adbFailure({ signal: 'SIGKILL' }); let reads = 0;
  await assert.rejects(resumeInstalledApp({ async adb() { throw failure; },
    async waitFor() { reads++; }, async snapshot() { reads++; } }), error => error === failure);
  assert.equal(reads, 0);
  for (const late of [false, true]) {
    let calls = 0, resolveSnapshot;
    const result = assert.rejects(resumeInstalledApp({ async adb() { calls++; },
      waitFor: check => waitForObservation(check, Date.now() + 180000, () => {}),
      async snapshot() { return late ? new Promise(resolve => { resolveSnapshot = resolve; }) : snapshot(); },
    }), error => error.observerCode === 'observation_deadline');
    await flush(); t.mock.timers.tick(15000);
    if (late) resolveSnapshot({ ...snapshot(), lifecycle: ['paused', 'resumed'] });
    await result; assert.equal(calls, 1);
  }
});

function controlResponse(value, status = 200) {
  const bytes = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
  return { status, body: (async function* () { yield bytes; })() };
}
async function rejectedProducts(fixture) {
  let failure;
  try { await fixture.run(); } catch (error) { failure = error; }
  assert.ok(failure, 'synthetic product operation must fail');
  recordDriverFailure(fixture.report, fixture.diagnostic, failure);
  assert.equal(fixture.report.passed, false);
  const receipt = fixture.report.failure_diagnostic;
  assert.equal(receipt.schema, 3); assert.equal(receipt.acceptance_evidence, false);
  assert.equal(receipt.cause_established, false); assert.equal(receipt.raw_output_retained, false);
  assert.ok(Buffer.byteLength(JSON.stringify(receipt)) <= 2048);
  for (const raw of ['private-token', 'http://', '/private/', 'Expires ', 'Temperature']) {
    assert.ok(!JSON.stringify(receipt).includes(raw));
  }
  return { failure, receipt };
}
function productMetadata(product) {
  const source = product.forecast.source;
  return [`Model ${source.model}; run ${source.model_run_at}`, `Acquired ${source.acquired_at}`,
    `Expires ${product.freshness.expires_at}`, source.attribution, `${source.license}: ${source.license_url}`, source.changes];
}
// No server, app or native process. Run the actual driver sequence against the
// synthetic fixture's products to test its predicates, not to claim UI proof.
function productExerciseFixture(options = {}) {
  const { state } = fixture(), diagnostic = new ObserverDiagnostic(), events = [];
  const report = { phase: 'read-only-observer', passed: false, checks: {}, observations: {},
    scope: { mounted_widget_tables: false, real_adb_interaction: false } };
  let resumed = false;
  const context = { report, diagnostic, remaining() { options.remaining?.(report, diagnostic); },
    async control(path) {
      return readFixtureControl({ remaining: context.remaining, diagnostic, async fetchControl(url, init) {
        const path = new URL(url).pathname;
        events.push(['control', path, init.method]);
        assert.equal(new URL(url).origin, 'http://127.0.0.1:43211');
        assert.equal(init.redirect, 'error'); assert.ok(init.signal instanceof AbortSignal);
        if (path !== '/state') state.setPhase(path.slice('/phase/'.length));
        const value = state.status();
        options.control?.(value, path, report, diagnostic);
        return controlResponse(value);
      } }, path);
    },
    async waitFor(check, milliseconds = 15000) {
      events.push(['wait', milliseconds]);
      options.beforeWait?.(report, diagnostic);
      const result = await check();
      if (!result) throw new (adbFailure({}).constructor)('observation_deadline');
      return result;
    },
    async snapshot() {
      events.push(['snapshot', report.phase, diagnostic.subphase]);
      const products = state.status().products;
      const value = snapshot(resumed ? [] : [table(products.weather), table(products.air_quality, true)]);
      value.labels = resumed ? Array(2).fill('Expired — refresh required; values are hidden')
        : Object.values(products).flatMap(productMetadata);
      value.refresh = [{ x: 540, y: 1800, enabled: true, visible: true, hit_testable: true }];
      if (resumed) value.lifecycle = ['resumed', 'inactive', 'hidden', 'paused', 'resumed'];
      options.snapshot?.(value, report, diagnostic);
      return validateSnapshot(value);
    },
    async adb(args) {
      events.push(['adb', ...args]); options.adb?.(args, report, diagnostic);
      if (args[2] === 'tap') { state.product(false, NOW); state.product(true, NOW); }
      if (args[1] === 'am') { assert.deepEqual(args, ['shell', 'am', 'start', '-n', COMPONENT]); resumed = true; }
    },
    async sleep(ms) { events.push(['sleep', ms]); options.sleep?.(ms, report, diagnostic); },
  };
  return { report, diagnostic, events, context, state, run: () => exerciseNativeProducts(context) };
}

test('actual product sequence retains exact initial/refresh/expiry gates, commands and wait budgets', async () => {
  const fixture = productExerciseFixture(); await fixture.run();
  assert.equal(fixture.report.passed, true); assert.equal(fixture.report.phase, 'complete');
  assert.deepEqual(fixture.report.checks, { initial_exact_native_rows: true,
    actual_tap_refresh_and_missing_values: true, real_android_background_resume: true,
    expired_products_hidden_without_network_refresh: true });
  assert.deepEqual(fixture.report.observations.requests, { weather: 3, air_quality: 3 });
  assert.equal(fixture.report.observations.initial.weather.rows, 4);
  assert.equal(fixture.report.observations.refresh.air_quality.rows, 5);
  assert.deepEqual(fixture.events.filter(row => row[0] === 'wait').map(row => row[1]), [15000, 15000, 15000, 3000, 15000]);
  assert.deepEqual(fixture.events.filter(row => row[0] === 'control').map(row => row.slice(1)),
    [['/state', 'GET'], ['/phase/refresh', 'POST'], ['/state', 'GET'], ['/phase/short-lived', 'POST'], ['/state', 'GET'], ['/state', 'GET']]);
  assert.deepEqual(fixture.events.filter(row => row[0] === 'adb').map(row => row.slice(1)), [
    ['shell', 'input', 'tap', '540', '1800'], ['shell', 'input', 'tap', '540', '1800'],
    ['shell', 'input', 'keyevent', 'KEYCODE_HOME'], ['shell', 'am', 'start', '-n', COMPONENT]]);
  assert.deepEqual(fixture.events.filter(row => row[0] === 'sleep'), [['sleep', 6000]]);
});
test('control request/status/body/decode/schema failures preserve the primary exception and redact output', async () => {
  const primary = new Error(PRIVATE_TEXT), value = fixture().state.status();
  for (const [stage, fetchControl] of [
    ['control_request', async () => { throw primary; }],
    ['control_status', async () => controlResponse(PRIVATE_TEXT, 400)],
    ['control_body', async () => ({ status: 200, body: (async function* () { throw primary; })() })],
    ['control_body', async () => controlResponse('x'.repeat(65537))],
    ['control_decode', async () => controlResponse(PRIVATE_TEXT)],
    ['control_schema', async () => controlResponse({ ...value, core_executed: true })],
  ]) {
    const diagnostic = new ObserverDiagnostic(); diagnostic.beginProducts(1);
    let failure;
    try { await readFixtureControl({ diagnostic, remaining() {}, fetchControl }); } catch (error) { failure = error; }
    assert.ok(failure);
    if (stage === 'control_request' || stage === 'control_body' && fetchControl.toString().includes('throw primary')) assert.equal(failure, primary);
    const report = { phase: 'initial-native-products', passed: false };
    recordDriverFailure(report, diagnostic, failure);
    assert.equal(report.failure_diagnostic.subphase, stage);
    assert.ok(!JSON.stringify(report).includes(PRIVATE_TEXT));
  }
  const diagnostic = new ObserverDiagnostic(), json = JSON.stringify(value);
  assert.deepEqual(await readFixtureControl({ diagnostic, remaining() {},
    fetchControl: async () => controlResponse(json + ' '.repeat(65536 - Buffer.byteLength(json))) }), value);
  let fetches = 0;
  await assert.rejects(readFixtureControl({ diagnostic, remaining() {}, fetchControl() { fetches++; } }, PRIVATE_TEXT));
  assert.equal(fetches, 0);
});
test('request diagnostics distinguish zero observed from unknown and expected count, without relaxing counts', async () => {
  const absent = productExerciseFixture({ beforeWait() { throw new Error(PRIVATE_TEXT); } });
  const unseen = (await rejectedProducts(absent)).receipt.progress;
  assert.equal(unseen.expected_requests_per_product, 1); assert.equal(unseen.weather_requests_observed, null);
  const waiting = productExerciseFixture({ control(value) { value.calls = { weather: 0, air_quality: 1 }; } });
  const result = await rejectedProducts(waiting);
  assert.equal(result.receipt.subphase, 'product_count_wait');
  assert.equal(result.receipt.progress.weather_requests_observed, 0);
  assert.equal(result.receipt.progress.air_quality_requests_observed, 1);
  const excessive = productExerciseFixture({ control(value) { value.calls.weather = 2; } });
  const rejected = await rejectedProducts(excessive);
  assert.equal(rejected.receipt.subphase, 'product_counts'); assert.equal(rejected.receipt.code, 'validation_failed');
  assert.equal(rejected.receipt.progress.weather_requests_observed, 2);
  assert.deepEqual(excessive.report.checks, {});
});
test('real product waiter keeps its 15s bound and interruption remains primary after an awaited control read', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100 });
  const pending = productExerciseFixture({ control(value) { value.calls = { weather: 0, air_quality: 0 }; } });
  pending.context.waitFor = check => waitForObservation(check, Date.now() + 180000, () => {});
  const result = rejectedProducts(pending);
  await flush(); t.mock.timers.tick(15000);
  const { receipt } = await result;
  assert.equal(receipt.code, 'observation_deadline'); assert.equal(receipt.subphase, 'product_count_wait');
  assert.equal(receipt.progress.expected_requests_per_product, 1);
  assert.equal(receipt.progress.weather_requests_observed, 0);
  assert.equal(receipt.progress.air_quality_requests_observed, 0);
  const primary = new (adbFailure({}).constructor)('interrupted');
  let interrupted = false;
  const fixture = productExerciseFixture({ control() { interrupted = true; } });
  fixture.context.waitFor = check => waitForObservation(check, Date.now() + 180000, () => { if (interrupted) throw primary; });
  const failure = await rejectedProducts(fixture);
  assert.equal(failure.failure, primary); assert.equal(failure.receipt.code, 'interrupted');
  assert.deepEqual(fixture.report.checks, {});
  assert.ok(!fixture.events.some(row => row[0] === 'snapshot' || row[0] === 'adb'));
});
test('16 mounted collection attempts retain exact tables and all six metadata fields per product', async () => {
  for (const mode of ['table', 'metadata', 'empty']) {
    const fixture = productExerciseFixture({ snapshot(value) {
      if (mode === 'table') value.tables[0].rows[0][1] = '1234567';
      if (mode === 'metadata') value.labels = value.labels.filter(text => !text.startsWith('Model '));
      if (mode === 'empty') { value.tables = []; value.labels = []; }
    } });
    const { receipt } = await rejectedProducts(fixture);
    assert.equal(receipt.subphase, 'products_unobserved'); assert.equal(receipt.progress.collection_attempts, 16);
    assert.equal(receipt.progress.weather_table_seen, mode !== 'empty');
    assert.equal(receipt.progress.weather_table_matched, mode === 'metadata');
    assert.equal(receipt.progress.weather_metadata_matches, mode === 'empty' ? 0 : mode === 'metadata' ? 5 : 6);
    assert.equal(fixture.events.filter(row => row[0] === 'adb' && row[3] === 'swipe').length, 16);
    assert.ok(fixture.events.filter(row => row[0] === 'sleep').every(row => row[1] === 200));
  }
});
test('snapshot/swipe/tap/background/resume failures bind actual awaited operation and preserve identity', async () => {
  const primary = adbFailure({ signal: 'SIGKILL' });
  for (const stage of ['product_snapshot', 'swipe', 'refresh_snapshot', 'tap', 'expiry_snapshot',
    'before_background', 'background_home', 'background_pause', 'resume_start', 'resume_snapshot']) {
    const fail = diagnostic => { if (diagnostic.subphase === stage) throw primary; };
    const fixture = productExerciseFixture({ snapshot(value, report, diagnostic) {
      fail(diagnostic); if (stage === 'swipe') value.labels = [];
    }, adb(args, report, diagnostic) { fail(diagnostic); }, sleep(ms, report, diagnostic) { fail(diagnostic); } });
    const { receipt, failure } = await rejectedProducts(fixture);
    assert.equal(failure, primary); assert.equal(receipt.subphase, stage); assert.equal(receipt.code, 'adb_signal');
  }
});
test('refresh target cannot be inferred, and phase reset prevents stale initial success counters', async () => {
  const fixture = productExerciseFixture({ snapshot(value, report) { if (report.phase === 'actual-refresh') value.refresh = []; } });
  const { receipt } = await rejectedProducts(fixture);
  assert.equal(receipt.subphase, 'refresh_unobserved'); assert.equal(receipt.progress.refresh_search_attempts, 16);
  assert.equal(receipt.progress.expected_requests_per_product, 2); assert.equal(receipt.progress.collection_attempts, 0);
  assert.equal(receipt.progress.weather_requests_observed, null); assert.equal(receipt.progress.weather_table_matched, null);
  assert.equal(fixture.report.checks.initial_exact_native_rows, true);
  assert.equal(fixture.report.checks.actual_tap_refresh_and_missing_values, undefined);
});
test('missing value, expiry consumption, real lifecycle, hidden tables and no-extra-fetch remain required', async () => {
  for (const stage of ['missing_values', 'expiry_wait', 'before_background', 'resume_wait', 'expired_labels', 'expired_tables', 'final_requests']) {
    const fixture = productExerciseFixture({ control(value, path, report) {
      if (stage === 'missing_values' && report.phase === 'actual-refresh' && path === '/state') {
        value.products.weather.forecast.samples[0].temperature_2m = 12;
      }
      if (stage === 'final_requests' && report.phase === 'background-resume-expiry' && value.calls.weather === 3
          && fixture.events.some(row => row[0] === 'adb' && row[2] === 'am')) value.calls.air_quality = 2;
    }, snapshot(value, report, diagnostic) {
      if (stage === 'missing_values' && diagnostic.subphase === 'product_snapshot' && report.phase === 'actual-refresh') value.tables[0].rows[0][1] = '12';
      if (stage === 'expiry_wait' && diagnostic.subphase === 'expiry_snapshot') value.labels = [];
      if (stage === 'before_background' && diagnostic.subphase === stage) value.current_lifecycle = 'paused';
      if (diagnostic.subphase === 'resume_snapshot') {
        if (stage === 'resume_wait') value.lifecycle = ['resumed'];
        if (stage === 'expired_labels') value.labels.pop();
        if (stage === 'expired_tables') value.tables = [table(fixture.state.status().products.weather)];
      }
    } });
    const { receipt } = await rejectedProducts(fixture);
    assert.equal(receipt.subphase, stage);
    assert.equal(fixture.report.scope.mounted_widget_tables, false);
    assert.equal(fixture.report.scope.real_adb_interaction, false);
    if (stage === 'expiry_wait') assert.equal(receipt.progress.expiry_labels_matched, 0);
    if (stage === 'expired_labels') assert.equal(receipt.progress.expired_labels_observed, 1);
    if (stage === 'expired_tables') assert.equal(receipt.progress.tables_remaining, 1);
  }
});
test('schema3 retains bounded progress, cannot echo arbitrary data, and optional diagnosis cannot mask failure', () => {
  const diagnostic = new ObserverDiagnostic(); diagnostic.beginProducts(1);
  const keys = Object.keys(diagnostic.productFailure(new Error()).progress);
  for (const invalid of [PRIVATE_TEXT, {}, [], NaN, Infinity, -1, 999999, 1.5]) {
    diagnostic.progress = Object.fromEntries(keys.map(key => [key, invalid]));
    diagnostic.progress[PRIVATE_TEXT] = PRIVATE_TEXT; diagnostic.subphase = PRIVATE_TEXT;
    const receipt = diagnostic.productFailure(new Error(PRIVATE_TEXT));
    assert.deepEqual(Object.keys(receipt.progress), keys); assert.ok(Object.values(receipt.progress).every(value => value === null));
    assert.equal(receipt.subphase, 'unobserved'); assert.ok(!JSON.stringify(receipt).includes(PRIVATE_TEXT));
  }
  diagnostic.beginProducts(3);
  diagnostic.note(() => { throw new Error(PRIVATE_TEXT); });
  assert.equal(diagnostic.productFailure(new Error()).progress.weather_requests_observed, null);
  const report = { phase: 'actual-refresh', passed: false };
  diagnostic.productFailure = () => { throw new Error(PRIVATE_TEXT); };
  recordDriverFailure(report, diagnostic, new Error(PRIVATE_TEXT));
  assert.deepEqual(report, { phase: 'actual-refresh', passed: false, failure: 'NATIVE_TRIAL_PHASE_FAILED' });
});

function appDiagnostic() {
  const product = () => ({ stage: 'complete', outcome: 'success', http_class: 'ok',
    clock_relation: 'withinWindow', attempts: 1, response_received: true,
    status_accepted: true, body_complete: true, json_decoded: true, product_validated: true });
  return { schema: 1, provider: { schema: 1, weather: product(), air_quality: product() },
    app: { home: 'single', loading: false, has_data: true, has_error: false,
      has_weather: true, has_air_quality: true, weather_view_mounted: true,
      air_quality_view_mounted: true, framework_error_mounted: false } };
}

test('actual snapshot-to-failure path separates request, response, parsing, clocks and mounted app state', async () => {
  for (const [outcome, clock, stage, received, decoded] of [
    ['transport', 'unknown', 'request', false, false],
    ['httpStatus', 'unknown', 'headers', true, false],
    ['jsonEncoding', 'unknown', 'decode', true, false],
    ['schema', 'unknown', 'validate', true, true],
    ['futureAcquired', 'beforeAcquired', 'validate', true, true],
    ['expired', 'atOrAfterExpiry', 'validate', true, true],
    ['success', 'withinWindow', 'complete', true, true],
  ]) {
    const observed = appDiagnostic();
    for (const key of ['weather', 'air_quality']) Object.assign(observed.provider[key], {
      outcome, clock_relation: clock, stage, response_received: received,
      http_class: !received ? 'unobserved' : outcome === 'httpStatus' ? 'serverError' : 'ok',
      status_accepted: received && outcome !== 'httpStatus', body_complete: stage !== 'headers' && received,
      json_decoded: decoded, product_validated: outcome === 'success',
    });
    Object.assign(observed.app, { has_data: outcome === 'success', has_error: outcome !== 'success',
      has_weather: outcome === 'success', has_air_quality: outcome === 'success',
      weather_view_mounted: false, air_quality_view_mounted: false });
    const fixture = productExerciseFixture({ snapshot(value) { value.tables = []; value.labels = []; value.diagnostic = observed; } });
    const { receipt } = await rejectedProducts(fixture);
    assert.equal(receipt.subphase, 'products_unobserved');
    assert.equal(receipt.progress.weather_requests_observed, 1);
    assert.equal(receipt.last_snapshot.snapshot_subphase, 'product_snapshot');
    assert.deepEqual(receipt.last_snapshot.provider.weather, observed.provider.weather);
    assert.deepEqual(receipt.last_snapshot.app, observed.app);
    assert.deepEqual(fixture.report.checks, {}); // Even parser success cannot supply absent native UI.
  }
});

test('diagnostic projection requires exact closed shapes and bounds; never exports raw values', () => {
  const diagnostic = new ObserverDiagnostic(); diagnostic.beginProducts(1);
  const render = value => { diagnostic.observeProducts({ diagnostic: value }); return diagnostic.productFailure(new Error(PRIVATE_TEXT)); };
  const nulls = [null, [], {}, PRIVATE_TEXT, true, 123];
  for (const value of [...nulls, { ...appDiagnostic(), extra: PRIVATE_TEXT }, { ...appDiagnostic(), schema: 2 }]) {
    assert.equal(render(value).last_snapshot, null);
  }
  for (const key of Object.keys(appDiagnostic().provider.weather)) {
    for (const invalid of [...nulls, -1, 7, 1.5, NaN, Infinity]) {
      if (typeof invalid === 'boolean' && ['response_received', 'status_accepted', 'body_complete', 'json_decoded', 'product_validated'].includes(key)) continue;
      const value = appDiagnostic(); value.provider.weather[key] = invalid;
      const receipt = render(value);
      assert.equal(receipt.last_snapshot.provider.weather, null);
      assert.deepEqual(receipt.last_snapshot.provider.air_quality, value.provider.air_quality);
      assert.ok(!JSON.stringify(receipt).includes(PRIVATE_TEXT));
    }
    const value = appDiagnostic(); delete value.provider.weather[key];
    assert.equal(render(value).last_snapshot.provider.weather, null);
  }
  for (const [target, field] of [['provider', 'provider'], ['app', 'app']]) {
    const value = appDiagnostic(); value[target][PRIVATE_TEXT] = PRIVATE_TEXT;
    assert.equal(render(value).last_snapshot[field], null);
  }
  const value = appDiagnostic(); value.provider.weather[PRIVATE_TEXT] = PRIVATE_TEXT;
  assert.equal(render(value).last_snapshot.provider.weather, null);
  for (const home of ['absent', 'multiple']) {
    const value = appDiagnostic(); value.app.home = home;
    for (const key of ['loading', 'has_data', 'has_error', 'has_weather', 'has_air_quality']) value.app[key] = null;
    assert.deepEqual(render(value).last_snapshot.app, value.app);
    value.app.has_error = false; assert.equal(render(value).last_snapshot.app, null);
  }
  for (const key of Object.keys(appDiagnostic().app)) {
    const value = appDiagnostic(); value.app[key] = PRIVATE_TEXT;
    assert.equal(render(value).last_snapshot.app, null);
  }
  const minimal = appDiagnostic(); minimal.provider.weather.attempts = 0;
  assert.equal(render(minimal).last_snapshot.provider.weather.attempts, 0);
  minimal.provider.weather.attempts = 6;
  assert.equal(render(minimal).last_snapshot.provider.weather.attempts, 6);
  diagnostic.appObservation = { snapshot_subphase: PRIVATE_TEXT, provider: { weather: PRIVATE_TEXT, air_quality: {} }, app: PRIVATE_TEXT };
  assert.ok(!JSON.stringify(diagnostic.productFailure(new Error())).includes(PRIVATE_TEXT));
});

test('new snapshot failures, invalid optional data and phase transitions cannot retain stale app observations', async () => {
  const primary = new Error(PRIVATE_TEXT);
  const fixture = productExerciseFixture({ snapshot(value, report, diagnostic) {
    value.tables = []; value.labels = [];
    if (diagnostic.progress.collection_attempts === 1) value.diagnostic = appDiagnostic();
    else throw primary;
  } });
  const failure = await rejectedProducts(fixture);
  assert.equal(failure.failure, primary); assert.equal(failure.receipt.last_snapshot, null);
  const diagnostic = new ObserverDiagnostic(); diagnostic.beginProducts(1);
  diagnostic.observeProducts({ diagnostic: appDiagnostic() });
  assert.ok(diagnostic.productFailure(primary).last_snapshot);
  diagnostic.beginProducts(2); assert.equal(diagnostic.productFailure(primary).last_snapshot, null);
  diagnostic.observeProducts({ diagnostic: appDiagnostic() });
  diagnostic.observeProducts({ get diagnostic() { throw primary; } });
  assert.equal(diagnostic.productFailure(primary).last_snapshot, null);
  const succeeds = productExerciseFixture({ snapshot(value) { value.diagnostic = { secret: PRIVATE_TEXT }; } });
  await succeeds.run(); assert.equal(succeeds.report.passed, true);
  assert.ok(!JSON.stringify(succeeds.report).includes(PRIVATE_TEXT));
});

test('read-only outcomes are not final UI acceptance, and worst-case closed receipt remains bounded', async () => {
  const observed = appDiagnostic();
  Object.assign(observed.app, { loading: true, has_error: true, framework_error_mounted: true });
  for (const item of Object.values(observed.provider).filter(value => typeof value === 'object')) {
    Object.assign(item, { stage: 'unobserved', outcome: 'futureAcquired', http_class: 'serverError',
      clock_relation: 'atOrAfterExpiry', attempts: 6 });
  }
  const fixture = productExerciseFixture({ snapshot(value) { value.diagnostic = observed; } });
  await fixture.run(); assert.equal(fixture.report.passed, true);
  assert.equal(fixture.report.scope.mounted_widget_tables, true);
  // The contradictory synthetic diagnostic cannot override actual assertion results.
  fixture.diagnostic.subphase = 'background_pause';
  assert.ok(Buffer.byteLength(JSON.stringify(fixture.diagnostic.productFailure(adbFailure({ signal: 'SIGKILL' })))) <= 2048);
});
