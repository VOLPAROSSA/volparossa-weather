// SPDX-License-Identifier: GPL-3.0-only
// Inert observer/fixture contracts: no adb, emulator, server, SDK or app launch.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { HEADERS, PACKAGE, COMPONENT, numberEqual, validateSnapshot, verifyTable, vmAddress,
  adbFailure, ObserverDiagnostic, observeVm, waitForObservation } from './native-android-driver.mjs';
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
  assert.ok(source.includes("['getVM', 'getIsolate', EXTENSION].includes(method)"));
  assert.ok(source.includes("['shell', 'input', 'tap'"));
  assert.ok(source.includes("['shell', 'input', 'keyevent', 'KEYCODE_HOME']"));
  assert.ok(source.includes('pixel_visibility_proven: false'));
  assert.ok(!source.includes("vm.request('evaluate'"));
  assert.ok(!source.includes('report.token') && !source.includes('report.logs'));
});

// These transports are inert EventTargets, not a VM/app success substitute.
const PRIVATE_TEXT = 'private-token http://127.0.0.1:43212/private/ /private/owner';
const VM_LINE = 'The Dart VM service is listening on http://127.0.0.1:34567/private-token/';
const flush = () => new Promise(done => setImmediate(done));
function observerFixture(options = {}) {
  const diagnostic = new ObserverDiagnostic(), calls = [], owned = [];
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
      const request = JSON.parse(raw); calls.push(request.method);
      setImmediate(() => {
        if (options.pending === request.method) return;
        if (options.close === request.method) { this.close(); return; }
        const result = request.method === 'getVM' ? (options.machine ?? { isolates: [{ id: 'isolates/12' }] })
          : { extensionRPCs: ['ext.volparossa.native_snapshot'] };
        const data = options.malformed === request.method ? PRIVATE_TEXT
          : JSON.stringify({ jsonrpc: '2.0', id: request.id,
            ...(options.reject === request.method ? { error: { message: PRIVATE_TEXT } } : { result }) });
        this.dispatchEvent(new MessageEvent('message', { data }));
      });
    }
    close() { this.readyState = WebSocket.CLOSED; queueMicrotask(() => this.dispatchEvent(new Event('close'))); }
  }
  const context = { pid: '1234', diagnostic, Socket,
    async adb(args) {
      calls.push(args[0]);
      if (options.adb === args[0] && calls.filter(value => value === args[0]).length >= (options.adbAfter ?? 1)) {
        throw adbFailure(options.error ?? { code: 1, stderr: PRIVATE_TEXT });
      }
      return args[0] === 'logcat' ? (options.log ?? VM_LINE) : (options.port ?? '45678');
    },
    waitFor: check => waitForObservation(check, Date.now() + 180000, () => {}, options.wait ?? 15000),
    ownForward(value) { owned.push(value === null ? 'forward-unconfirmed' : 'forward-owned'); },
    ownVm(value) { vm = value; owned.push('vm-owned'); },
  };
  return { diagnostic, calls, owned, run: () => observeVm(context),
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
  assert.deepEqual(fixture.calls, ['logcat', 'forward', 'getVM', 'getIsolate']);
  assert.deepEqual(fixture.owned, ['forward-unconfirmed', 'forward-owned', 'vm-owned']);
  assert.equal(fixture.diagnostic.waitingFor, null);
  await fixture.close();
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
    [{ machine: null, reject: 'getIsolate' }, 'get_isolate', 'vm_request_rejected'],
    [{ machine: { isolates: Array(9).fill({ id: 'isolates/12' }) } }, 'get_vm', 'validation_failed'],
    [{ machine: { isolates: null } }, 'get_vm', 'response_type_invalid'],
    [{ machine: { isolates: [{ id: PRIVATE_TEXT }] } }, 'isolate_identity', 'validation_failed'],
    [{ malformed: 'getVM' }, 'get_vm', 'vm_response_invalid'],
    [{ close: 'getIsolate' }, 'get_isolate', 'vm_connection_closed'],
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
    [{ pending: 'getIsolate' }, 3000, 'get_isolate', 'vm_request_deadline'],
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
  assert.ok(source.indexOf('report.failure_diagnostic = diagnostic.failure(error)') < source.indexOf('if (vm) try'));
  assert.ok(source.includes("if (report.phase === 'read-only-observer')"));
  assert.ok(source.includes('timeout: 8000, killSignal: \'SIGKILL\', maxBuffer: 65536'));
  assert.ok(source.includes('deadline = started + 180000'));
});
