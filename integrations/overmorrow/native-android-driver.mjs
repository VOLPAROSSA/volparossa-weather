// SPDX-License-Identifier: GPL-3.0-only
// Observe the installed real Android app through a READ-ONLY debug extension.
// All interaction is actual adb input/activity lifecycle, never Dart evaluation.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstat, mkdir, readFile, readlink, realpath, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const PACKAGE = 'org.volparossa.weather.trial';
export const COMPONENT = `${PACKAGE}/com.marotidev.overmorrow.MainActivity`;
const EXTENSION = 'ext.volparossa.native_snapshot';
const ORIGIN = 'http://127.0.0.1:43210', CONTROL = 'http://127.0.0.1:43211';
export const HEADERS = Object.freeze({
  weather: ['Native valid time (UTC)', 'Temperature (°C)', 'Wind (m/s)', 'Wind from (°)',
    'Precipitation (mm)', 'Accumulation window (UTC)'],
  air_quality: ['Native valid time (UTC)', 'PM2.5 (µg/m³)', 'PM10 (µg/m³)'],
});
const pause = ms => new Promise(done => setTimeout(done, ms));
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

function decimal(value) {
  assert.ok(typeof value === 'string' && value.length <= 40);
  const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(value);
  assert.ok(match);
  let coefficient = BigInt(`${match[1]}${match[2]}${match[3] ?? ''}`);
  let exponent = Number(match[4] ?? 0) - (match[3]?.length ?? 0);
  if (coefficient === 0n) return '0';
  while (coefficient % 10n === 0n) { coefficient /= 10n; exponent++; }
  return `${coefficient}:${exponent}`;
}

export function numberEqual(actual, expected) {
  if (expected === null) return actual === 'Not available';
  try { return Number.isFinite(expected) && decimal(actual) === decimal(String(expected)); }
  catch { return false; }
}

export function validateSnapshot(value) {
  assert.ok(value && value.schema === 1 && value.kind === 'overmorrow-native-mounted-ui');
  assert.equal(value.package, PACKAGE); assert.equal(value.platform, 'android');
  assert.equal(value.profile, true); assert.equal(value.origin, ORIGIN);
  assert.ok(Array.isArray(value.tables) && value.tables.length <= 4);
  assert.ok(Array.isArray(value.labels) && value.labels.length <= 2048
    && value.labels.every(text => typeof text === 'string' && text.length <= 1024));
  assert.ok(Array.isArray(value.lifecycle) && value.lifecycle.length <= 16
    && value.lifecycle.every(state => ['resumed', 'inactive', 'hidden', 'paused', 'detached'].includes(state)));
  assert.ok(['resumed', 'inactive', 'hidden', 'paused', 'detached', null].includes(value.current_lifecycle));
  assert.ok(value.screen && ['width', 'height'].every(key => Number.isInteger(value.screen[key])
    && value.screen[key] >= 200 && value.screen[key] <= 4096));
  assert.ok(Array.isArray(value.refresh) && value.refresh.length <= 1);
  for (const button of value.refresh) {
    assert.ok(['enabled', 'visible', 'hit_testable'].every(key => typeof button[key] === 'boolean'));
    assert.ok(Number.isFinite(button.x) && Number.isFinite(button.y));
    if (button.visible) assert.ok(button.x > 0 && button.x < value.screen.width
      && button.y > 0 && button.y < value.screen.height);
  }
  for (const table of value.tables) {
    assert.ok(Object.hasOwn(HEADERS, table.product));
    assert.deepEqual(table.headers, HEADERS[table.product]);
    assert.ok(Array.isArray(table.rows) && table.rows.length <= 16 && table.rows.every(row =>
      Array.isArray(row) && row.length === table.headers.length && row.every(cell =>
        typeof cell === 'string' && cell.length <= 256)));
  }
  assert.equal(new Set(value.tables.map(table => table.product)).size, value.tables.length);
  return value;
}

export function verifyTable(table, product) {
  const quality = table.product === 'air_quality', forecast = product.forecast;
  assert.deepEqual(table.headers, HEADERS[table.product]);
  assert.equal(table.rows.length, quality ? 5 : 4);
  assert.equal(table.rows.length, forecast.samples.length);
  for (let index = 0; index < table.rows.length; index++) {
    const row = table.rows[index], sample = forecast.samples[index];
    assert.equal(row.length, quality ? 3 : 6); assert.equal(row[0], sample.valid_at);
    const numbers = quality ? [sample.pm2_5, sample.pm10] : [sample.temperature_2m,
      sample.wind_10m.speed, sample.wind_10m.direction_from, sample.precipitation.amount];
    assert.ok(numbers.every((number, column) => numberEqual(row[column + 1], number)));
    if (!quality) assert.equal(row[5], sample.precipitation.start_at === null ? 'Not available'
      : `${sample.precipitation.start_at} → ${sample.precipitation.end_at}`);
  }
  return { rows: table.rows.length, table_sha256: digest(table), product_sha256: digest(product) };
}

function metadata(product) {
  const source = product.forecast.source;
  return [`Model ${source.model}; run ${source.model_run_at}`, `Acquired ${source.acquired_at}`,
    `Expires ${product.freshness.expires_at}`, source.attribution, `${source.license}: ${source.license_url}`,
    source.changes];
}

export function vmAddress(log, pid) {
  assert.ok(typeof log === 'string' && Buffer.byteLength(log) <= 65536 && /^[1-9]\d{0,7}$/.test(pid));
  const matches = [...log.matchAll(/The Dart VM service is listening on (http:\/\/127\.0\.0\.1:(\d{1,5})\/([A-Za-z0-9_=-]{1,128})\/)/g)];
  assert.equal(matches.length, 1, 'one fresh app VM service required');
  const port = Number(matches[0][2]); assert.ok(port >= 1024 && port <= 65535);
  // Keep the token in memory only. Neither this object nor raw logcat is saved.
  return { port, token: matches[0][3] };
}

const OBSERVER_SUBPHASES = new Set(['unobserved', 'logcat_read', 'vm_address', 'forward_create',
  'forward_port', 'websocket_create', 'websocket_connect', 'get_vm', 'isolate_identity', 'get_isolate', 'isolate_wait',
  'package_check', 'force_stop', 'app_start', 'pidof', 'pid_validation']);
const OBSERVER_CODES = new Set(['unknown', 'validation_failed', 'response_type_invalid', 'adb_exit',
  'adb_signal', 'adb_output_bound', 'adb_spawn_failed', 'adb_failed', 'websocket_deadline',
  'websocket_failed', 'vm_request_rejected', 'vm_request_deadline', 'vm_connection_closed',
  'vm_response_invalid', 'observation_deadline', 'trial_deadline', 'interrupted']);

class ObserverFailure extends Error {
  constructor(code, exitStatus = null, signal = null) {
    super('closed native observer failure');
    this.observerCode = OBSERVER_CODES.has(code) ? code : 'unknown';
    this.exitStatus = Number.isInteger(exitStatus) && exitStatus >= 0 && exitStatus <= 255 ? exitStatus : null;
    this.signal = ['SIGKILL', 'SIGTERM'].includes(signal) ? signal : null;
  }
}

export function adbFailure(error, { args, stdout, stderr } = {}) {
  // Classify Node's callback metadata; never export its command, message,
  // stdout, stderr, path or the VM service authentication URI.
  const code = error?.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' ? 'adb_output_bound'
    : Number.isInteger(error?.code) ? 'adb_exit'
    : ['SIGKILL', 'SIGTERM'].includes(error?.signal) ? 'adb_signal'
    : ['ENOENT', 'EACCES', 'EMFILE', 'ENFILE'].includes(error?.code) ? 'adb_spawn_failed' : 'adb_failed';
  const failure = new ObserverFailure(code, error?.code, error?.signal);
  // Android 16 toybox pidof returns 1 with no output when no process matches.
  // ADB transport errors can also return 1: only this exact command and empty
  // complete streams qualify. Keep the discriminator in memory, never output.
  failure.pidAbsent = Array.isArray(args) && args.length === 3
    && args[0] === 'shell' && args[1] === 'pidof' && args[2] === PACKAGE
    && error?.code === 1 && error.signal === null && error.killed === false
    && stdout === '' && stderr === '';
  return failure;
}

export class ObserverDiagnostic {
  subphase = 'unobserved';
  waitingFor = null;
  async at(subphase, action) {
    assert.ok(OBSERVER_SUBPHASES.has(subphase));
    this.subphase = subphase;
    return action();
  }
  failure(error) {
    const known = error instanceof ObserverFailure;
    const code = known ? (OBSERVER_CODES.has(error.observerCode) ? error.observerCode : 'unknown')
      : error?.code === 'ERR_ASSERTION' ? 'validation_failed'
      : error instanceof TypeError ? 'response_type_invalid' : 'unknown';
    const subphase = code === 'observation_deadline' ? this.waitingFor : this.subphase;
    return { schema: 1, subphase: OBSERVER_SUBPHASES.has(subphase) ? subphase : 'unobserved',
      code, adb_exit_status: known && Number.isInteger(error.exitStatus)
        && error.exitStatus >= 0 && error.exitStatus <= 255 ? error.exitStatus : null,
      adb_signal: known && ['SIGKILL', 'SIGTERM'].includes(error.signal) ? error.signal : null,
      cause_established: false, raw_output_retained: false };
  }
}

export function recordDriverFailure(report, diagnostic, error) {
  report.failure = 'NATIVE_TRIAL_PHASE_FAILED';
  if (['installed-app', 'read-only-observer'].includes(report.phase)) {
    report.failure_diagnostic = diagnostic.failure(error);
  }
}

export async function startInstalledApp({ adb, waitFor, diagnostic, installed, ownApp }) {
  await diagnostic.at('package_check', async () => {
    assert.match(await adb(['shell', 'pm', 'path', PACKAGE]), /^package:\/data\/app\/[^\r\n]+\/base\.apk$/);
  });
  installed();
  await diagnostic.at('force_stop', () => adb(['shell', 'am', 'force-stop', PACKAGE]));
  // Retain ownership before the existing launch command, including failure.
  ownApp();
  // AOSP android-16.0.0_r1 ActivityManagerShellCommand.runStartActivity uses
  // startActivityAndWait only for -W. Dispatch the same activity; actual PID,
  // read-only VM and mounted UI observations below establish readiness.
  await diagnostic.at('app_start', () => adb(['shell', 'am', 'start', '-n', COMPONENT]));
  diagnostic.subphase = diagnostic.waitingFor = 'pidof';
  const pid = await waitFor(async () => {
    let value;
    try { value = await diagnostic.at('pidof', () => adb(['shell', 'pidof', PACKAGE])); }
    catch (error) {
      if (error instanceof ObserverFailure && error.pidAbsent === true
          && error.observerCode === 'adb_exit' && error.exitStatus === 1 && error.signal === null) return null;
      throw error;
    }
    await diagnostic.at('pid_validation', () => assert.match(value, /^[1-9]\d{0,7}$/));
    return value;
  });
  diagnostic.waitingFor = null;
  return pid;
}

export async function resumeInstalledApp({ adb, waitFor, snapshot }) {
  await adb(['shell', 'am', 'start', '-n', COMPONENT]);
  // The caller retains the original VM and isolate; no new attach or process
  // launch is substituted for the observed paused-to-resumed lifecycle.
  return waitFor(async () => {
    const value = await snapshot();
    return value.current_lifecycle === 'resumed' && value.lifecycle.includes('paused')
      && value.lifecycle.lastIndexOf('resumed') > value.lifecycle.lastIndexOf('paused') ? value : null;
  });
}

class ReadOnlyVm {
  constructor(socket) {
    this.socket = socket; this.next = 0; this.pending = new Map();
    socket.addEventListener('message', event => {
      try {
        assert.equal(typeof event.data, 'string'); assert.ok(Buffer.byteLength(event.data) <= 131072);
        const value = JSON.parse(event.data), waiting = this.pending.get(value.id);
        if (!waiting) return; this.pending.delete(value.id); clearTimeout(waiting.timer);
        if (value.error) waiting.reject(new ObserverFailure('vm_request_rejected')); else waiting.resolve(value.result);
      } catch { this.rejectPending('vm_response_invalid'); void this.close().catch(() => {}); }
    });
    socket.addEventListener('close', () => this.rejectPending());
    socket.addEventListener('error', () => this.rejectPending());
  }
  rejectPending(code = 'vm_connection_closed') {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new ObserverFailure(code)); }
    this.pending.clear();
  }
  async request(method, params = {}) {
    assert.ok(['getVM', 'getIsolate', EXTENSION].includes(method));
    assert.ok(this.pending.size === 0 && this.socket.readyState === WebSocket.OPEN);
    const id = ++this.next;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new ObserverFailure('vm_request_deadline')); }, 3000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
    });
  }
  async close() {
    this.rejectPending();
    if (this.socket.readyState === WebSocket.CLOSED) return;
    await new Promise((done, reject) => {
      const timer = setTimeout(() => reject(new Error('VM close deadline')), 2000);
      this.socket.addEventListener('close', () => { clearTimeout(timer); done(); }, { once: true });
      this.socket.close();
    });
  }
}

export async function waitForObservation(check, deadline, remaining, milliseconds = 15000) {
  const end = Math.min(deadline, Date.now() + milliseconds);
  while (Date.now() < end) {
    remaining();
    const value = await check();
    remaining();
    if (Date.now() >= end) break; // An awaited result cannot extend its window.
    if (value) return value;
    await pause(250);
  }
  throw new ObserverFailure('observation_deadline');
}

export async function observeVm({ adb, waitFor, pid, diagnostic, ownForward, ownVm, Socket = WebSocket }) {
  diagnostic.subphase = 'unobserved';
  diagnostic.waitingFor = 'vm_address';
  const address = await waitFor(async () => {
    const logs = await diagnostic.at('logcat_read', () => adb(['logcat', '-d', '--pid', pid, '-s', 'flutter:I', '-t', '200']));
    return diagnostic.at('vm_address', () => {
      try { return vmAddress(logs, pid); } catch { return null; }
    });
  });
  diagnostic.waitingFor = null;
  ownForward(null); // A failed forward command is not confirmed cleaned up.
  const port = await diagnostic.at('forward_create', () => adb(['forward', 'tcp:0', `tcp:${address.port}`]));
  await diagnostic.at('forward_port', () => {
    assert.match(port, /^[1-9]\d{3,4}$/); assert.ok(Number(port) <= 65535);
  });
  ownForward(`tcp:${port}`);
  const vm = await diagnostic.at('websocket_create', () => {
    const socket = new Socket(`ws://127.0.0.1:${port}/${address.token}/ws`);
    const value = new ReadOnlyVm(socket); ownVm(value); return value;
  });
  await diagnostic.at('websocket_connect', () => new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new ObserverFailure('websocket_deadline')), 5000);
    vm.socket.addEventListener('open', () => { clearTimeout(timer); done(); }, { once: true });
    vm.socket.addEventListener('error', () => { clearTimeout(timer); reject(new ObserverFailure('websocket_failed')); }, { once: true });
  }));
  diagnostic.waitingFor = 'isolate_wait';
  const isolate = await waitFor(async () => {
    const machine = await diagnostic.at('get_vm', async () => {
      const value = await vm.request('getVM'); assert.ok(value.isolates.length <= 8); return value;
    });
    for (const candidate of machine.isolates) {
      await diagnostic.at('isolate_identity', () => assert.match(candidate.id, /^isolates\/[0-9]+$/));
      const value = await diagnostic.at('get_isolate', () => vm.request('getIsolate', { isolateId: candidate.id }));
      if (value.extensionRPCs?.includes(EXTENSION)) return candidate.id;
    }
    return null;
  });
  diagnostic.waitingFor = null;
  return isolate;
}

async function main() {
  assert.equal(process.argv.length, 8);
  assert.equal(process.argv[2], '--adb'); assert.equal(process.argv[4], '--serial');
  assert.equal(process.argv[6], '--output');
  const adbPath = process.argv[3], serial = process.argv[5], output = resolve(process.argv[7]);
  assert.ok(isAbsolute(adbPath) && await realpath(adbPath) === adbPath);
  assert.equal(serial, 'emulator-5554'); assert.equal(await realpath(dirname(output)), dirname(output));
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  await mkdir(output, { mode: 0o700 });
  const info = await lstat(output); assert.equal(info.uid, process.getuid()); assert.equal(info.mode & 0o777, 0o700);
  const report = { schema: 1, kind: 'overmorrow-installed-android-synthetic-trial', passed: false,
    phase: 'installed-app', package: PACKAGE, checks: {}, observations: {},
    scope: { installed_android_app: false, mounted_widget_tables: false, pixel_visibility_proven: false,
      real_adb_interaction: false, synthetic_weather: true, synthetic_air_quality: true,
      core_executed: false, overlay_proven: false, physical_device: false, production_authority: false },
    cleanup: { app_stopped: false, forward_removed: true, vm_closed: true } };
  let vm, forward, appOwned = false, interrupted = false;
  const diagnostic = new ObserverDiagnostic();
  const started = Date.now(), deadline = started + 180000;
  const onSignal = () => { interrupted = true; };
  process.on('SIGTERM', onSignal); process.on('SIGINT', onSignal);
  function remaining() {
    if (interrupted) throw new ObserverFailure('interrupted');
    if (!(Date.now() < deadline)) throw new ObserverFailure('trial_deadline');
  }
  async function adb(args, cleanup = false) {
    if (!cleanup) remaining();
    return new Promise((done, reject) => execFile(adbPath, ['-s', serial, ...args], {
      timeout: 8000, killSignal: 'SIGKILL', maxBuffer: 65536, encoding: 'utf8',
    }, (error, stdout, stderr) => error ? reject(adbFailure(error, { args, stdout, stderr })) : done(stdout.trim())));
  }
  async function control(path = '/state') {
    remaining(); assert.ok(['/state', '/phase/refresh', '/phase/short-lived'].includes(path));
    const response = await fetch(`${CONTROL}${path}`, { method: path === '/state' ? 'GET' : 'POST',
      redirect: 'error', signal: AbortSignal.timeout(3000) });
    assert.equal(response.status, 200);
    const parts = []; let length = 0;
    for await (const part of response.body) { length += part.length; assert.ok(length <= 65536); parts.push(part); }
    const value = JSON.parse(Buffer.concat(parts).toString('utf8'));
    assert.equal(value.schema, 1); assert.equal(value.core_executed, false);
    assert.equal(value.overlay_proven, false); assert.equal(value.synthetic_weather, true);
    assert.equal(value.synthetic_air_quality, true);
    return value;
  }
  async function waitFor(check, milliseconds = 15000) {
    return waitForObservation(check, deadline, remaining, milliseconds);
  }
  let isolate;
  async function snapshot() { remaining(); return validateSnapshot(await vm.request(EXTENSION, { isolateId: isolate })); }
  async function swipe(value) {
    const { width, height } = value.screen, x = Math.round(width * .5);
    await adb(['shell', 'input', 'swipe', String(x), String(Math.round(height * .78)),
      String(x), String(Math.round(height * .24)), '250']); await pause(200);
  }
  async function collect(expected) {
    const observed = {}, labels = new Set();
    for (let attempt = 0; attempt < 16; attempt++) {
      const value = await snapshot();
      for (const label of value.labels) { if (Object.values(expected.products).some(product => metadata(product).includes(label))) labels.add(label); }
      for (const table of value.tables) {
        try { observed[table.product] = verifyTable(table, expected.products[table.product]); }
        catch { /* An old mounted frame is not accepted as the new response. */ }
      }
      if (Object.keys(observed).length === 2 && Object.values(expected.products).every(product =>
        metadata(product).every(label => labels.has(label)))) return observed;
      await swipe(value);
    }
    throw new Error('mounted native products not observed');
  }
  async function tapRefresh() {
    for (let attempt = 0; attempt < 16; attempt++) {
      const value = await snapshot(), button = value.refresh[0];
      if (button?.enabled && button.visible && button.hit_testable) {
        await adb(['shell', 'input', 'tap', String(Math.round(button.x)), String(Math.round(button.y))]);
        return;
      }
      await swipe(value);
    }
    throw new Error('actual refresh target not reachable');
  }
  async function products(count) {
    return waitFor(async () => {
      const value = await control();
      assert.ok(value.calls.weather <= count && value.calls.air_quality <= count);
      return value.calls.weather === count && value.calls.air_quality === count ? value : null;
    });
  }
  try {
    const pid = await startInstalledApp({ adb, waitFor, diagnostic,
      installed() { report.scope.installed_android_app = true; }, ownApp() { appOwned = true; } });
    report.phase = 'read-only-observer';
    isolate = await observeVm({ adb, waitFor, pid, diagnostic,
      ownForward(value) { forward = value; report.cleanup.forward_removed = false; },
      ownVm(value) { vm = value; report.cleanup.vm_closed = false; } });
    report.phase = 'initial-native-products';
    const initial = await products(1); report.observations.initial = await collect(initial);
    report.checks.initial_exact_native_rows = true;
    report.phase = 'actual-refresh';
    await control('/phase/refresh'); await tapRefresh();
    const refreshed = await products(2); report.observations.refresh = await collect(refreshed);
    assert.equal(refreshed.products.weather.forecast.samples[0].temperature_2m, null);
    assert.notEqual(initial.products.weather.forecast.samples[0].temperature_2m, null);
    report.checks.actual_tap_refresh_and_missing_values = true;
    report.phase = 'background-resume-expiry';
    await control('/phase/short-lived'); await tapRefresh();
    const short = await products(3);
    // App is at the footer after a real tap; the same native product widgets
    // must consume the response before Android takes the app to background.
    await waitFor(async () => {
      const value = await snapshot();
      return Object.values(short.products).every(product => value.labels.includes(`Expires ${product.freshness.expires_at}`)) ? value : null;
    }, 3000);
    const before = await snapshot(); assert.equal(before.current_lifecycle, 'resumed');
    await adb(['shell', 'input', 'keyevent', 'KEYCODE_HOME']);
    await pause(6000); remaining();
    const resumed = await resumeInstalledApp({ adb, waitFor, snapshot });
    assert.ok(resumed.labels.filter(label => label === 'Expired — refresh required; values are hidden').length === 2);
    assert.equal(resumed.tables.length, 0); assert.deepEqual((await control()).calls, { weather: 3, air_quality: 3 });
    report.checks.real_android_background_resume = true;
    report.checks.expired_products_hidden_without_network_refresh = true;
    report.observations.requests = { weather: 3, air_quality: 3 };
    report.observations.lifecycle = resumed.lifecycle;
    report.scope.mounted_widget_tables = true; report.scope.real_adb_interaction = true;
    report.phase = 'complete'; report.passed = true;
  } catch (error) {
    recordDriverFailure(report, diagnostic, error);
  } finally {
    if (vm) try { await vm.close(); report.cleanup.vm_closed = true; } catch { /* retain uncertainty */ }
    if (forward) try { await adb(['forward', '--remove', forward], true); report.cleanup.forward_removed = true; } catch { /* retain uncertainty */ }
    if (appOwned) try {
      await adb(['shell', 'am', 'force-stop', PACKAGE], true);
      // pidof returns exit 1 for absence; check the exact process table instead.
      const processes = await adb(['shell', 'ps', '-A', '-o', 'NAME'], true);
      assert.ok(!processes.split(/\r?\n/).some(name => name.trim() === PACKAGE)); report.cleanup.app_stopped = true;
    } catch { /* retain uncertainty */ }
    report.passed &&= Object.values(report.cleanup).every(Boolean);
    report.elapsed_ms = Date.now() - started;
    await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    process.removeListener('SIGTERM', onSignal); process.removeListener('SIGINT', onSignal);
  }
  if (!report.passed) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('native Android trial setup failed\n'); process.exitCode = 1; });
}
