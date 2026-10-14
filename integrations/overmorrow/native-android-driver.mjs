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
const LIFECYCLE_EXTENSION = 'ext.volparossa.native_lifecycle';
const ORIGIN = 'http://127.0.0.1:43210', CONTROL = 'http://127.0.0.1:43211';
export const HEADERS = Object.freeze({
  weather: ['Native valid time (UTC)', 'Temperature (°C)', 'Wind (m/s)', 'Wind from (°)',
    'Precipitation (mm)', 'Accumulation window (UTC)'],
  air_quality: ['Native valid time (UTC)', 'PM2.5 (µg/m³)', 'PM10 (µg/m³)'],
});
const pause = ms => new Promise(done => setTimeout(done, ms));
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const LIFECYCLE = Object.freeze(['resumed', 'inactive', 'hidden', 'paused', 'detached']);

export function validateLifecycle(value) {
  assert.ok(exactKeys(value, ['schema', 'kind', 'current_lifecycle', 'callback_state', 'callback_sequence', 'guest_utc_ms']));
  assert.equal(value.schema, 1); assert.equal(value.kind, 'overmorrow-native-lifecycle');
  assert.ok(value.current_lifecycle === null || LIFECYCLE.includes(value.current_lifecycle));
  assert.ok(value.callback_state === null || LIFECYCLE.includes(value.callback_state));
  assert.ok(Number.isInteger(value.callback_sequence) && value.callback_sequence >= 0 && value.callback_sequence <= 65535);
  assert.equal(value.callback_sequence === 0, value.callback_state === null);
  assert.ok(Number.isSafeInteger(value.guest_utc_ms) && value.guest_utc_ms >= 1000000000000 && value.guest_utc_ms <= 9999999999999);
  return value;
}

export async function readLifecycle(vm, isolate) {
  // Keep the exact VM/isolate selected by the full mounted-snapshot readiness
  // check. No retry of missing methods, app commands or new service attachment.
  return validateLifecycle(await vm.request(LIFECYCLE_EXTENSION, { isolateId: isolate }));
}

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
  assert.ok(value && value.schema === 3 && value.kind === 'overmorrow-native-mounted-ui');
  assert.equal(value.package, PACKAGE); assert.equal(value.platform, 'android');
  assert.equal(value.profile, true); assert.equal(value.origin, ORIGIN);
  assert.ok(Array.isArray(value.tables) && value.tables.length <= 4);
  assert.ok(Array.isArray(value.labels) && value.labels.length <= 2048
    && value.labels.every(text => typeof text === 'string' && text.length <= 1024));
  assert.ok(Array.isArray(value.lifecycle) && value.lifecycle.length <= 16
    && value.lifecycle.every(state => LIFECYCLE.includes(state)));
  assert.ok(value.current_lifecycle === null || LIFECYCLE.includes(value.current_lifecycle));
  assert.ok(exactKeys(value.screen, ['width', 'height', 'safe_area']) && ['width', 'height'].every(key => Number.isInteger(value.screen[key])
    && value.screen[key] >= 200 && value.screen[key] <= 4096));
  const safe = value.screen.safe_area;
  assert.ok(safe === null || (exactKeys(safe, ['left', 'top', 'right', 'bottom'])
    && Object.values(safe).every(Number.isFinite) && safe.left >= 0 && safe.top >= 0
    && safe.right <= value.screen.width && safe.bottom <= value.screen.height
    && safe.left < safe.right && safe.top < safe.bottom));
  assert.ok(Array.isArray(value.refresh) && value.refresh.length <= 1);
  for (const button of value.refresh) {
    assert.ok(exactKeys(button, ['enabled', 'visible', 'hit_testable', 'safe_target', 'x', 'y', 'scroll']));
    assert.ok(['enabled', 'visible', 'hit_testable', 'safe_target'].every(key => typeof button[key] === 'boolean'));
    assert.ok(exactKeys(button.scroll, ['ancestors', 'idle']));
    assert.ok(Number.isInteger(button.scroll.ancestors) && button.scroll.ancestors >= 0 && button.scroll.ancestors <= 16);
    assert.ok(button.scroll.ancestors === 0 ? button.scroll.idle === null : typeof button.scroll.idle === 'boolean');
    assert.ok(Number.isFinite(button.x) && Number.isFinite(button.y));
    if (button.visible) assert.ok(button.x > 0 && button.x < value.screen.width
      && button.y > 0 && button.y < value.screen.height);
    if (button.safe_target) assert.ok(button.visible && safe && Math.round(button.x) > safe.left
      && Math.round(button.x) < safe.right && Math.round(button.y) > safe.top && Math.round(button.y) < safe.bottom);
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
  'forward_port', 'websocket_create', 'websocket_connect', 'get_vm', 'isolate_identity', 'get_isolate', 'native_snapshot', 'isolate_wait',
  'package_check', 'force_stop', 'app_start', 'pidof', 'pid_validation',
  'control_request', 'control_status', 'control_body', 'control_decode', 'control_schema',
  'product_counts', 'product_count_wait', 'product_snapshot', 'product_metadata', 'product_tables',
  'products_unobserved', 'swipe', 'swipe_settle', 'refresh_snapshot', 'refresh_target', 'refresh_unobserved', 'refresh_wait', 'post_tap_snapshot',
  'tap', 'missing_values', 'expiry_snapshot', 'expiry_labels', 'expiry_wait', 'before_background',
  'background_home', 'background_snapshot', 'background_wait', 'background_pause', 'resume_start', 'resume_snapshot', 'resume_wait',
  'expired_labels', 'expired_tables', 'final_requests', 'clock_window', 'clock_guest_read',
  'clock_guest_decode', 'clock_validity', 'clock_wait', 'lifecycle_baseline', 'lifecycle_read', 'lifecycle_validate']);
const OBSERVER_CODES = new Set(['unknown', 'validation_failed', 'response_type_invalid', 'adb_exit',
  'adb_signal', 'adb_output_bound', 'adb_spawn_failed', 'adb_failed', 'websocket_deadline',
  'websocket_failed', 'vm_request_rejected', 'vm_request_deadline', 'vm_connection_closed',
  'vm_response_invalid', 'vm_response_type', 'vm_response_bound', 'vm_response_json',
  'observation_deadline', 'trial_deadline', 'interrupted', 'clock_expired', 'clock_host_before_acquisition']);

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
  beginProducts(expected) {
    this.subphase = 'unobserved'; this.waitingFor = null;
    this.appObservation = null;
    this.timing = {};
    this.progress = { expected_requests_per_product: expected, collection_attempts: 0, refresh_search_attempts: 0 };
  }
  note(values) {
    // Optional diagnostics cannot introduce a new failure or replace the real
    // operation's exception. No values are exported without the closed projection.
    try { Object.assign(this.progress, values()); } catch { /* retain unknown */ }
  }
  noteTiming(values) {
    try { Object.assign(this.timing, values()); } catch { /* retain unknown */ }
  }
  async timed(key, action) {
    let started;
    try { started = performance.now(); } catch { /* timing is optional */ }
    try { return await action(); }
    finally {
      try { this.noteTiming(() => ({ [key]: Math.floor(performance.now() - started) })); }
      catch { /* Optional timing cannot replace the operation's result/error. */ }
    }
  }
  observeProducts(snapshot) {
    this.appObservation = null;
    try {
      const value = snapshot?.diagnostic;
      if (!exactKeys(value, ['schema', 'provider', 'app']) || value.schema !== 1) return;
      const provider = exactKeys(value.provider, ['schema', 'weather', 'air_quality']) && value.provider.schema === 1
        ? { weather: projectProviderObservation(value.provider.weather), air_quality: projectProviderObservation(value.provider.air_quality) } : null;
      this.appObservation = {
        snapshot_subphase: OBSERVER_SUBPHASES.has(this.subphase) ? this.subphase : 'unobserved',
        current_lifecycle: LIFECYCLE.includes(snapshot.current_lifecycle) ? snapshot.current_lifecycle : null,
        provider, app: projectAppObservation(value.app),
      };
    } catch { /* Optional observation cannot change the real snapshot outcome. */ }
  }
  productFailure(error) {
    const value = this.progress ?? {};
    // Null means no valid bounded observation; zero is an observed zero.
    // Never coerce, round, clamp or echo an out-of-contract value.
    const count = (key, max) => Number.isInteger(value[key]) && value[key] >= 0 && value[key] <= max ? value[key] : null;
    const flag = key => typeof value[key] === 'boolean' ? value[key] : null;
    const last = this.appObservation;
    const lastSnapshot = exactKeys(last, ['snapshot_subphase', 'current_lifecycle', 'provider', 'app'])
      ? { snapshot_subphase: OBSERVER_SUBPHASES.has(last.snapshot_subphase) ? last.snapshot_subphase : 'unobserved',
        current_lifecycle: LIFECYCLE.includes(last.current_lifecycle) ? last.current_lifecycle : null,
        provider: exactKeys(last.provider, ['weather', 'air_quality'])
          ? { weather: projectProviderObservation(last.provider.weather), air_quality: projectProviderObservation(last.provider.air_quality) } : null,
        app: projectAppObservation(last.app) } : null;
    const timing = this.timing ?? {};
    const duration = key => Number.isInteger(timing[key]) && timing[key] >= 0 && timing[key] <= 180000 ? timing[key] : null;
    const bounded = (key, maximum) => Number.isInteger(timing[key]) && timing[key] >= 0 && timing[key] <= maximum ? timing[key] : null;
    return { ...this.failure(error), schema: 5, acceptance_evidence: false,
      progress: {
        expected_requests_per_product: count('expected_requests_per_product', 3),
        weather_requests_observed: count('weather_requests_observed', 3),
        air_quality_requests_observed: count('air_quality_requests_observed', 3),
        collection_attempts: count('collection_attempts', 16), refresh_search_attempts: count('refresh_search_attempts', 16),
        weather_table_seen: flag('weather_table_seen'), air_quality_table_seen: flag('air_quality_table_seen'),
        weather_table_matched: flag('weather_table_matched'), air_quality_table_matched: flag('air_quality_table_matched'),
        weather_metadata_matches: count('weather_metadata_matches', 6), air_quality_metadata_matches: count('air_quality_metadata_matches', 6),
        expiry_labels_matched: count('expiry_labels_matched', 2), expired_labels_observed: count('expired_labels_observed', 2),
        tables_remaining: count('tables_remaining', 4),
      }, last_snapshot: lastSnapshot,
      timing: {
        phase_prepare_ms: duration('phase_prepare_ms'), target_tap_ms: duration('target_tap_ms'),
        products_ready_ms: duration('products_ready_ms'),
        pre_home_ui_ms: duration('pre_home_ui_ms'), baseline_read_ms: duration('baseline_read_ms'),
        home_command_ms: duration('home_command_ms'), background_read_ms: duration('background_read_ms'),
        background_polls: bounded('background_polls', 64), callback_advance: bounded('callback_advance', 64),
        clock_failure_side: ['host_before', 'host_after', 'guest'].includes(timing.clock_failure_side) ? timing.clock_failure_side : null,
      } };
  }
}

function projectProviderObservation(value) {
  const enums = {
    stage: ['unobserved', 'request', 'headers', 'body', 'decode', 'validate', 'complete'],
    outcome: ['unobserved', 'pending', 'transport', 'httpStatus', 'contentType', 'contentLength',
      'bodyTooLarge', 'bodyStream', 'jsonEncoding', 'schema', 'futureAcquired', 'expired',
      'success', 'busy', 'busyLimit', 'deadline', 'areaMismatch'],
    http_class: ['unobserved', 'ok', 'busy', 'redirect', 'clientError', 'serverError', 'other'],
    clock_relation: ['unknown', 'beforeAcquired', 'atOrAfterExpiry', 'withinWindow'],
  };
  const flags = ['response_received', 'status_accepted', 'body_complete', 'json_decoded', 'product_validated'];
  if (!exactKeys(value, [...Object.keys(enums), 'attempts', ...flags])
      || Object.entries(enums).some(([key, allowed]) => !allowed.includes(value[key]))
      || !Number.isInteger(value.attempts) || value.attempts < 0 || value.attempts > 6
      || flags.some(key => typeof value[key] !== 'boolean')) return null;
  // Copy only fixed typed fields. This is the last attempt in the current load,
  // not a request history, timestamp, provider assertion or acceptance flag.
  return Object.fromEntries([...Object.keys(enums), 'attempts', ...flags].map(key => [key, value[key]]));
}

function projectAppObservation(value) {
  const state = ['loading', 'has_data', 'has_error', 'has_weather', 'has_air_quality'];
  const widgets = ['weather_view_mounted', 'air_quality_view_mounted', 'framework_error_mounted'];
  if (!exactKeys(value, ['home', ...state, ...widgets]) || !['absent', 'single', 'multiple'].includes(value.home)
      || state.some(key => value.home === 'single' ? typeof value[key] !== 'boolean' : value[key] !== null)
      || widgets.some(key => typeof value[key] !== 'boolean')) return null;
  return Object.fromEntries(['home', ...state, ...widgets].map(key => [key, value[key]]));
}

export function recordDriverFailure(report, diagnostic, error) {
  report.failure = 'NATIVE_TRIAL_PHASE_FAILED';
  try {
    if (['installed-app', 'read-only-observer'].includes(report.phase)) {
      report.failure_diagnostic = diagnostic.failure(error);
    } else if (['initial-native-products', 'actual-refresh', 'background-resume-expiry', 'background-resume-fresh'].includes(report.phase)) {
      report.failure_diagnostic = diagnostic.productFailure(error);
    }
  } catch { /* Diagnosis cannot mask the original failure or prevent cleanup. */ }
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

function exactKeys(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

function extensionNotReady(value, waiting) {
  // Flutter's pinned Dart a0daa5004ec02c0638ba6e50791ba9338a87374c:
  // runtime/vm/{service.cc,json_stream.cc,json_stream.h} serializes a missing
  // method with the exact echoed request; sdk/lib/developer/extension.dart
  // serializes our entrypoint's fixed error as Server error/data.details.
  // Neither arbitrary -32000 errors nor other RPCs become retry authority.
  if (waiting.method !== EXTENSION || !exactKeys(waiting.params, ['isolateId'])
      || !exactKeys(value, ['jsonrpc', 'id', 'error']) || value.jsonrpc !== '2.0'
      || !exactKeys(value.error, ['code', 'message', 'data'])) return false;
  const error = value.error;
  if (error.code === -32601 && error.message === 'Method not found'
      && exactKeys(error.data, ['request'])
      && exactKeys(error.data.request, ['method', 'params'])
      && error.data.request.method === EXTENSION
      && exactKeys(error.data.request.params, ['isolateId'])
      && error.data.request.params.isolateId === waiting.params.isolateId) return true;
  return error.code === -32000 && error.message === 'Server error'
    && exactKeys(error.data, ['details']) && error.data.details === 'Snapshot not ready';
}

class ReadOnlyVm {
  constructor(socket) {
    this.socket = socket; this.next = 0; this.pending = new Map();
    socket.addEventListener('message', event => {
      try {
        if (typeof event.data !== 'string') throw new ObserverFailure('vm_response_type');
        if (Buffer.byteLength(event.data) > 131072) throw new ObserverFailure('vm_response_bound');
        let value;
        try { value = JSON.parse(event.data); } catch { throw new ObserverFailure('vm_response_json'); }
        assert.ok(value !== null && typeof value === 'object' && !Array.isArray(value));
        const waiting = this.pending.get(value.id);
        if (!waiting) return;
        assert.equal(value.jsonrpc, '2.0');
        assert.notEqual(Object.hasOwn(value, 'error'), Object.hasOwn(value, 'result'));
        let failure;
        if (Object.hasOwn(value, 'error')) {
          failure = new ObserverFailure('vm_request_rejected');
          // In-memory predicate only: never retain error text or request data.
          failure.extensionPending = extensionNotReady(value, waiting);
        }
        this.pending.delete(value.id); clearTimeout(waiting.timer);
        if (failure) waiting.reject(failure); else waiting.resolve(value.result);
      } catch (error) {
        this.rejectPending(error instanceof ObserverFailure ? error.observerCode : 'vm_response_invalid');
        void this.close().catch(() => {});
      }
    });
    socket.addEventListener('close', () => this.rejectPending());
    socket.addEventListener('error', () => this.rejectPending());
  }
  rejectPending(code = 'vm_connection_closed') {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new ObserverFailure(code)); }
    this.pending.clear();
  }
  async request(method, params = {}) {
    assert.ok(['getVM', EXTENSION, LIFECYCLE_EXTENSION].includes(method));
    assert.ok(this.pending.size === 0 && this.socket.readyState === WebSocket.OPEN);
    const id = ++this.next;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new ObserverFailure('vm_request_deadline')); }, 3000);
      this.pending.set(id, { resolve, reject, timer, method, params });
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

export async function tapNativeRefresh({ diagnostic, waitFor, snapshot, swipe, adb, remaining }) {
  let previous = null, attempts = 0;
  diagnostic.waitingFor = 'refresh_wait';
  const target = await waitFor(async () => {
    attempts++;
    diagnostic.note(() => ({ refresh_search_attempts: attempts }));
    const value = await diagnostic.at('refresh_snapshot', snapshot), button = value.refresh[0];
    diagnostic.subphase = 'refresh_target';
    const ready = button?.enabled && button.visible && button.hit_testable && button.safe_target && button.scroll?.idle === true;
    const candidate = ready ? { x: button.x, y: button.y, width: value.screen.width, height: value.screen.height,
      ancestors: button.scroll.ancestors, ...value.screen.safe_area } : null;
    // isScrollingNotifier covers drag/ballistic activity; equal unrounded
    // physical coordinates across separate polls also reject moving layouts.
    // Neither observation invokes the callback or repairs the app's state.
    if (candidate && previous && Object.keys(candidate).every(key => candidate[key] === previous[key])) return candidate;
    previous = candidate;
    if (attempts >= 16) {
      diagnostic.subphase = 'refresh_unobserved';
      throw new Error('actual stationary refresh target not reachable');
    }
    if (!button || ((!button.visible || (!button.safe_target && value.screen.safe_area)) && button.scroll?.idle === true)) await swipe(value);
    return null;
  });
  diagnostic.waitingFor = null;
  remaining();
  await diagnostic.at('tap', () => adb(['shell', 'input', 'tap', String(Math.round(target.x)), String(Math.round(target.y))]));
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
      try {
        await diagnostic.at('native_snapshot', async () => {
          // A full getIsolate also serializes every library. Read only the
          // existing bounded extension instead; readiness is not UI acceptance.
          validateSnapshot(await vm.request(EXTENSION, { isolateId: candidate.id }));
        });
        return candidate.id;
      } catch (error) {
        if (!(error instanceof ObserverFailure && error.observerCode === 'vm_request_rejected'
            && error.extensionPending === true)) throw error;
      }
    }
    return null;
  });
  diagnostic.waitingFor = null;
  return isolate;
}

export async function readFixtureControl({ remaining, diagnostic, fetchControl = fetch, profile = 'synthetic' }, path = '/state') {
  const response = await diagnostic.at('control_request', () => {
    remaining(); assert.ok(['synthetic', 'protected-core'].includes(profile));
    assert.ok((profile === 'protected-core' ? ['/state'] : ['/state', '/phase/initial', '/phase/refresh', '/phase/short-lived']).includes(path));
    return fetchControl(`${CONTROL}${path}`, { method: path === '/state' ? 'GET' : 'POST',
      redirect: 'error', signal: AbortSignal.timeout(3000) });
  });
  await diagnostic.at('control_status', () => assert.equal(response.status, 200));
  const parts = []; let length = 0;
  await diagnostic.at('control_body', async () => {
    for await (const part of response.body) {
      length += part.length; assert.ok(length <= (profile === 'protected-core' ? 2 * 256 * 1024 + 4096 : 65536)); parts.push(part);
    }
  });
  const value = await diagnostic.at('control_decode', () => JSON.parse(Buffer.concat(parts).toString('utf8')));
  await diagnostic.at('control_schema', () => {
    if (profile === 'protected-core') return validateLiveControl(value);
    assert.equal(value.schema, 2); assert.equal(value.core_executed, false);
    assert.equal(value.overlay_proven, false); assert.equal(value.synthetic_weather, true);
    assert.equal(value.synthetic_air_quality, true);
  });
  return value;
}

export function validateLiveControl(value) {
  assert.ok(exactKeys(value, ['schema', 'profile', 'calls', 'completed', 'products', 'response_sha256', 'active',
    'terminal_failure', 'synthetic_weather', 'synthetic_air_quality', 'core_executed', 'overlay_proven']));
  assert.equal(value.schema, 3); assert.equal(value.profile, 'protected-core');
  for (const flag of ['synthetic_weather', 'synthetic_air_quality', 'core_executed', 'overlay_proven']) assert.equal(value[flag], false);
  assert.equal(value.terminal_failure, null); assert.equal(typeof value.active, 'boolean');
  for (const name of ['calls', 'completed', 'products', 'response_sha256']) assert.ok(exactKeys(value[name], ['weather', 'air_quality']));
  for (const name of ['weather', 'air_quality']) {
    assert.ok(Number.isInteger(value.calls[name]) && value.calls[name] >= 0 && value.calls[name] <= 3);
    assert.ok(Number.isInteger(value.completed[name]) && value.completed[name] >= 0 && value.completed[name] <= value.calls[name]);
    if (value.completed[name] === 0) {
      assert.equal(value.products[name], null); assert.equal(value.response_sha256[name], null);
    } else {
      assert.match(value.response_sha256[name], /^[a-f0-9]{64}$/);
      const product = value.products[name], delivery = product.delivery;
      assert.equal(product.kind, 'forecast'); assert.equal(delivery.mode, 'core-cache');
      assert.match(delivery.publisher_key, /^[a-f0-9]{64}$/); assert.match(delivery.manifest_id, /^[a-f0-9]{64}$/);
      assert.match(delivery.sha256, /^[a-f0-9]{64}$/);
      assert.ok(typeof delivery.name === 'string' && Buffer.byteLength(delivery.name) >= 1 && Buffer.byteLength(delivery.name) <= 128);
      assert.ok(Number.isSafeInteger(delivery.revision) && delivery.revision > 0);
      assert.equal(delivery.upstream_origin_attested, false); assert.equal(delivery.manifest_media_type_checked, false);
      assert.equal(product.forecast.schema, name === 'weather' ? 'volparossa.forecast.v1' : 'volparossa.air-quality.forecast.v1');
      assert.equal(product.forecast.samples.length, name === 'weather' ? 4 : 5);
      assert.deepEqual(product.forecast.samples.map(sample => sample.lead_hours), name === 'weather' ? [3, 9, 24, 48] : [3, 6, 12, 24, 48]);
    }
  }
  if (value.completed.weather > 0 && value.completed.air_quality > 0) productClockWindow(value.products);
  return value;
}

export function productClockWindow(products) {
  assert.ok(exactKeys(products, ['weather', 'air_quality']));
  const utc = value => {
    assert.ok(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value));
    const time = Date.parse(value);
    assert.ok(Number.isSafeInteger(time) && new Date(time).toISOString() === value);
    return time;
  };
  const windows = Object.values(products).map(product => {
    const acquired = utc(product.forecast.source.acquired_at);
    const expires = Math.min(utc(product.forecast.freshness.expires_at), utc(product.delivery.publication_expires_at));
    assert.ok(acquired < expires); assert.equal(utc(product.freshness.expires_at), expires);
    return { acquired, expires };
  });
  const window = { acquired: Math.max(...windows.map(value => value.acquired)),
    expires: Math.min(...windows.map(value => value.expires)) };
  assert.ok(window.acquired < window.expires);
  return window;
}

export async function phaseClockReady({ adb, diagnostic, remaining, clock = Date.now }, products) {
  const window = await diagnostic.at('clock_window', () => productClockWindow(products));
  function hostValid(side) {
    remaining(); const now = clock(); assert.ok(Number.isSafeInteger(now));
    if (now < window.acquired || now >= window.expires) diagnostic.noteTiming(() => ({ clock_failure_side: side }));
    if (now < window.acquired) throw new ObserverFailure('clock_host_before_acquisition');
    if (now >= window.expires) throw new ObserverFailure('clock_expired');
  }
  await diagnostic.at('clock_validity', () => hostValid('host_before'));
  // Android 16 toybox date.c reads CLOCK_REALTIME and implements %3N. This
  // fixed unprivileged read observes the real guest clock; it never sets it.
  // https://android.googlesource.com/platform/external/toybox/+/refs/tags/android-16.0.0_r1/toys/posix/date.c
  const raw = await diagnostic.at('clock_guest_read', () => adb(['shell', '/system/bin/date', '+%s%3N']));
  remaining();
  const guest = await diagnostic.at('clock_guest_decode', () => {
    assert.ok(typeof raw === 'string' && /^[1-9]\d{12}$/.test(raw));
    return Number(raw);
  });
  return diagnostic.at('clock_validity', () => {
    hostValid('host_after');
    if (guest >= window.expires) {
      diagnostic.noteTiming(() => ({ clock_failure_side: 'guest' }));
      throw new ObserverFailure('clock_expired');
    }
    return guest >= window.acquired;
  });
}

export async function lifecycleWithinWindow({ lifecycle, diagnostic, remaining, clock = Date.now }, products, baseline = false) {
  // A poll rejected before its first request must not inherit a previous
  // request duration. The poll counter separately includes this clock gate.
  diagnostic.noteTiming(() => ({ [baseline ? 'baseline_read_ms' : 'background_read_ms']: null, clock_failure_side: null }));
  const window = await diagnostic.at('clock_window', () => productClockWindow(products));
  function hostValid(side) {
    remaining(); const now = clock(); assert.ok(Number.isSafeInteger(now));
    if (now < window.acquired || now >= window.expires) diagnostic.noteTiming(() => ({ clock_failure_side: side }));
    if (now < window.acquired) throw new ObserverFailure('clock_host_before_acquisition');
    if (now >= window.expires) throw new ObserverFailure('clock_expired');
  }
  await diagnostic.at('clock_validity', () => hostValid('host_before'));
  const observed = await diagnostic.timed(baseline ? 'baseline_read_ms' : 'background_read_ms',
    () => diagnostic.at(baseline ? 'lifecycle_baseline' : 'lifecycle_read', lifecycle));
  remaining();
  const value = await diagnostic.at('lifecycle_validate', () => validateLifecycle(observed));
  await diagnostic.at('clock_validity', () => {
    hostValid('host_after');
    const guest = value.guest_utc_ms;
    if (guest < window.acquired || guest >= window.expires) diagnostic.noteTiming(() => ({ clock_failure_side: 'guest' }));
    if (guest >= window.expires) throw new ObserverFailure('clock_expired');
    assert.ok(guest >= window.acquired);
  });
  return value;
}

export async function prepareNativePhase(context, phase) {
  assert.ok(['initial', 'refresh', 'short-lived'].includes(phase));
  // POST exactly once, outside the existing bounded waiter. If waiting fails,
  // no replacement timestamps, renewed expiry or additional product GET exists.
  const prepared = await context.control(`/phase/${phase}`);
  assert.equal(prepared.phase, phase);
  const prior = ['initial', 'refresh', 'short-lived'].indexOf(phase);
  assert.deepEqual(prepared.calls, { weather: prior, air_quality: prior });
  context.diagnostic.waitingFor = 'clock_wait';
  await context.waitFor(() => phaseClockReady(context, prepared.products));
  context.diagnostic.waitingFor = null;
  return prepared;
}

// The production sequence is shared with inert contract tests. Injectable I/O
// is a test seam, never an alternate native acceptance path. Keep the original
// exact predicates, commands, attempt counts and wait budgets here.
export async function exerciseNativeProducts({ report, diagnostic, control, waitFor, snapshot: readSnapshot, lifecycle, adb, remaining,
  initialPrepared, clock = Date.now, sleep = pause }) {
  const phaseContext = { control, waitFor, adb, diagnostic, remaining, clock, lifecycle };
  async function snapshot() {
    // A failed or malformed new read must not inherit an earlier observation.
    diagnostic.observeProducts(null);
    const value = await readSnapshot();
    diagnostic.observeProducts(value);
    return value;
  }
  async function swipe(value) {
    const { width, height } = value.screen, x = Math.round(width * .5);
    await diagnostic.at('swipe', () => adb(['shell', 'input', 'swipe', String(x), String(Math.round(height * .78)),
      String(x), String(Math.round(height * .24)), '250']));
    await diagnostic.at('swipe_settle', () => sleep(200));
  }
  async function collect(expected) {
    const observed = {}, labels = new Set(), seen = new Set();
    for (let attempt = 0; attempt < 16; attempt++) {
      diagnostic.note(() => ({ collection_attempts: attempt + 1 }));
      const value = await diagnostic.at('product_snapshot', snapshot);
      diagnostic.subphase = 'product_metadata';
      for (const label of value.labels) { if (Object.values(expected.products).some(product => metadata(product).includes(label))) labels.add(label); }
      diagnostic.subphase = 'product_tables';
      for (const table of value.tables) {
        seen.add(table.product);
        try { observed[table.product] = verifyTable(table, expected.products[table.product]); }
        catch { /* An old mounted frame is not accepted as the new response. */ }
      }
      // These matches accumulate only within this collection, like acceptance.
      diagnostic.note(() => ({ weather_table_seen: seen.has('weather'), air_quality_table_seen: seen.has('air_quality'),
        weather_table_matched: Object.hasOwn(observed, 'weather'), air_quality_table_matched: Object.hasOwn(observed, 'air_quality'),
        weather_metadata_matches: metadata(expected.products.weather).filter(label => labels.has(label)).length,
        air_quality_metadata_matches: metadata(expected.products.air_quality).filter(label => labels.has(label)).length }));
      if (Object.keys(observed).length === 2 && Object.values(expected.products).every(product =>
        metadata(product).every(label => labels.has(label)))) return observed;
      await swipe(value);
    }
    diagnostic.subphase = 'products_unobserved';
    throw new Error('mounted native products not observed');
  }
  async function tapRefresh() {
    await tapNativeRefresh({ diagnostic, waitFor, snapshot, swipe, adb, remaining });
  }
  async function products(count, prepared) {
    diagnostic.waitingFor = 'product_count_wait';
    const result = await waitFor(async () => {
      const value = await control();
      diagnostic.note(() => ({ weather_requests_observed: value.calls.weather, air_quality_requests_observed: value.calls.air_quality }));
      diagnostic.subphase = 'product_counts';
      assert.ok(value.calls.weather <= count && value.calls.air_quality <= count);
      assert.equal(value.phase, prepared.phase);
      assert.deepEqual(value.products, prepared.products);
      if (value.calls.weather === count && value.calls.air_quality === count) return value;
      if (count > 1) {
        // Optional post-input state explains a pending count without replacing
        // the primary control/timeout failure, invoking app code or making GETs.
        try { await diagnostic.at('post_tap_snapshot', snapshot); }
        catch { /* Missing observation stays unknown; the real waiter remains. */ }
        finally { diagnostic.subphase = 'product_counts'; }
      }
      return null;
    });
    diagnostic.waitingFor = null;
    return result;
  }
  report.phase = 'initial-native-products'; diagnostic.beginProducts(1);
  const initial = await products(1, initialPrepared); report.observations.initial = await collect(initial);
  report.checks.initial_exact_native_rows = true;
  report.phase = 'actual-refresh'; diagnostic.beginProducts(2);
  const refreshPrepared = await prepareNativePhase(phaseContext, 'refresh'); await tapRefresh();
  const refreshed = await products(2, refreshPrepared); report.observations.refresh = await collect(refreshed);
  await diagnostic.at('missing_values', () => {
    assert.equal(refreshed.products.weather.forecast.samples[0].temperature_2m, null);
    assert.notEqual(initial.products.weather.forecast.samples[0].temperature_2m, null);
  });
  report.checks.actual_tap_refresh_and_missing_values = true;
  report.phase = 'background-resume-expiry'; diagnostic.beginProducts(3);
  const shortPrepared = await diagnostic.timed('phase_prepare_ms', () => prepareNativePhase(phaseContext, 'short-lived'));
  await diagnostic.timed('target_tap_ms', tapRefresh);
  const short = await diagnostic.timed('products_ready_ms', () => products(3, shortPrepared));
  // App is at the footer after a real tap; the same native product widgets
  // must consume the response before Android takes the app to background.
  // Use that one fresh snapshot for all pre-HOME UI predicates; a second VM
  // tree traversal adds no predicate and spends the immutable product TTL.
  diagnostic.waitingFor = 'expiry_wait';
  const before = await diagnostic.timed('pre_home_ui_ms', () => waitFor(async () => {
    const value = await diagnostic.at('expiry_snapshot', snapshot);
    diagnostic.subphase = 'expiry_labels';
    diagnostic.note(() => ({ expiry_labels_matched: Object.values(short.products)
      .filter(product => value.labels.includes(`Expires ${product.freshness.expires_at}`)).length }));
    return Object.values(short.products).every(product => value.labels.includes(`Expires ${product.freshness.expires_at}`)) ? value : null;
  }, 3000));
  diagnostic.waitingFor = null;
  await diagnostic.at('before_background', async () => {
    assert.equal(before.current_lifecycle, 'resumed');
    assert.ok(!before.labels.includes('Expired — refresh required; values are hidden'));
    for (const name of ['weather', 'air_quality']) {
      assert.ok(before.labels.includes(`Expires ${short.products[name].freshness.expires_at}`));
      verifyTable(before.tables.find(table => table.product === name), short.products[name]);
    }
  });
  const baseline = await lifecycleWithinWindow(phaseContext, short.products, true);
  await diagnostic.at('lifecycle_validate', () => {
    assert.equal(baseline.current_lifecycle, 'resumed');
    assert.ok(baseline.callback_state === null || baseline.callback_state === 'resumed');
  });
  await diagnostic.timed('home_command_ms', () => diagnostic.at('background_home',
    () => adb(['shell', 'input', 'keyevent', 'KEYCODE_HOME'])));
  diagnostic.waitingFor = 'background_wait';
  let backgroundPolls = 0;
  await waitFor(async () => {
    diagnostic.noteTiming(() => ({ background_polls: ++backgroundPolls, callback_advance: null }));
    // No full tree traversal or separate ADB clock query here. The current
    // clock must still be valid, not merely the time of an older callback.
    const background = await lifecycleWithinWindow(phaseContext, short.products);
    return diagnostic.at('lifecycle_validate', () => {
      assert.ok(background.callback_sequence >= baseline.callback_sequence);
      diagnostic.noteTiming(() => ({ callback_advance: background.callback_sequence - baseline.callback_sequence }));
      return background.callback_sequence > baseline.callback_sequence
        && ['paused', 'hidden'].includes(background.current_lifecycle)
        && background.callback_state === background.current_lifecycle ? background : null;
    });
  });
  diagnostic.waitingFor = null;
  await diagnostic.at('background_pause', async () => { await sleep(6000); remaining(); });
  diagnostic.waitingFor = 'resume_wait';
  const resumed = await resumeInstalledApp({
    adb: args => diagnostic.at('resume_start', () => adb(args)), waitFor,
    snapshot: () => diagnostic.at('resume_snapshot', snapshot),
  });
  diagnostic.waitingFor = null;
  diagnostic.note(() => ({ expired_labels_observed: resumed.labels
    .filter(label => label === 'Expired — refresh required; values are hidden').length,
    tables_remaining: resumed.tables.length }));
  await diagnostic.at('expired_labels', () => assert.ok(resumed.labels
    .filter(label => label === 'Expired — refresh required; values are hidden').length === 2));
  await diagnostic.at('expired_tables', () => assert.equal(resumed.tables.length, 0));
  const final = await control();
  diagnostic.note(() => ({ weather_requests_observed: final.calls.weather, air_quality_requests_observed: final.calls.air_quality }));
  await diagnostic.at('final_requests', () => assert.deepEqual(final.calls, { weather: 3, air_quality: 3 }));
  report.checks.real_android_background_resume = true;
  report.checks.expired_products_hidden_without_network_refresh = true;
  report.observations.requests = { weather: 3, air_quality: 3 };
  report.observations.lifecycle = resumed.lifecycle;
  report.scope.mounted_widget_tables = true; report.scope.real_adb_interaction = true;
  report.phase = 'complete'; report.passed = true;
}

// This profile observes real forwarded responses. It cannot independently
// establish cold retrieval, source acquisition or protected-route authority;
// those remain mandatory gates of the separate joined core proof.
export async function exerciseLiveNativeProducts({ report, diagnostic, control, waitFor, snapshot: readSnapshot,
  lifecycle, adb, remaining, clock = Date.now, sleep = pause }) {
  const context = { diagnostic, remaining, clock, lifecycle };
  async function snapshot() {
    diagnostic.observeProducts(null);
    const value = await readSnapshot(); diagnostic.observeProducts(value); return value;
  }
  async function swipe(value) {
    const { width, height } = value.screen, x = Math.round(width * .5);
    await diagnostic.at('swipe', () => adb(['shell', 'input', 'swipe', String(x), String(Math.round(height * .78)),
      String(x), String(Math.round(height * .24)), '250']));
    await diagnostic.at('swipe_settle', () => sleep(200));
  }
  async function products(count) {
    diagnostic.waitingFor = 'product_count_wait';
    const value = await waitFor(async () => {
      const current = await control();
      await diagnostic.at('control_schema', () => validateLiveControl(current));
      diagnostic.note(() => ({ weather_requests_observed: current.calls.weather,
        air_quality_requests_observed: current.calls.air_quality }));
      return diagnostic.at('product_counts', () => {
        for (const name of ['weather', 'air_quality']) assert.ok(current.calls[name] <= count);
        return !current.active && Object.values(current.calls).every(value => value === count)
          && Object.values(current.completed).every(value => value === count) ? current : null;
      });
    }, count === 1 ? 120000 : 15000);
    // Cold acquisition has more room than an observer poll, but still shares
    // the driver's original 180-second deadline with every remaining action.
    diagnostic.waitingFor = null;
    return value;
  }
  function immutable(product) {
    const delivery = product.delivery;
    return { forecast: product.forecast, delivery: Object.fromEntries(['mode', 'publisher_key', 'name', 'revision',
      'manifest_id', 'sha256', 'publication_expires_at', 'upstream_origin_attested', 'manifest_media_type_checked']
      .map(key => [key, delivery[key]])), expires_at: product.freshness.expires_at };
  }
  async function unchanged(current, initial) {
    await diagnostic.at('product_metadata', () => {
      for (const name of ['weather', 'air_quality']) assert.deepEqual(immutable(current.products[name]), immutable(initial.products[name]));
    });
  }
  function tables(value, expected) {
    assert.ok(!value.labels.includes('Expired — refresh required; values are hidden'));
    for (const name of ['weather', 'air_quality']) {
      verifyTable(value.tables.find(table => table.product === name), expected.products[name]);
      for (const label of metadata(expected.products[name])) assert.ok(value.labels.includes(label));
    }
  }
  async function collect(expected) {
    const observed = {}, labels = new Set();
    for (let attempt = 0; attempt < 16; attempt++) {
      diagnostic.note(() => ({ collection_attempts: attempt + 1 }));
      const value = await diagnostic.at('product_snapshot', snapshot);
      await diagnostic.at('product_metadata', () => assert.ok(!value.labels.includes('Expired — refresh required; values are hidden')));
      for (const label of value.labels) {
        if (Object.values(expected.products).some(product => metadata(product).includes(label))) labels.add(label);
      }
      for (const table of value.tables) {
        try { observed[table.product] = verifyTable(table, expected.products[table.product]); }
        catch { /* A previous frame is never evidence for the new response. */ }
      }
      diagnostic.note(() => ({ weather_table_matched: Object.hasOwn(observed, 'weather'),
        air_quality_table_matched: Object.hasOwn(observed, 'air_quality'),
        weather_metadata_matches: metadata(expected.products.weather).filter(label => labels.has(label)).length,
        air_quality_metadata_matches: metadata(expected.products.air_quality).filter(label => labels.has(label)).length }));
      if (Object.keys(observed).length === 2 && Object.values(expected.products).every(product =>
        metadata(product).every(label => labels.has(label)))) {
        await lifecycleWithinWindow(context, expected.products);
        return { ...observed, response_sha256: { ...expected.response_sha256 } };
      }
      await swipe(value);
    }
    diagnostic.subphase = 'products_unobserved'; throw new Error('mounted native products not observed');
  }
  const tap = () => tapNativeRefresh({ diagnostic, waitFor, snapshot, swipe, adb, remaining });
  report.phase = 'initial-native-products'; diagnostic.beginProducts(1);
  const initial = await products(1);
  report.observations.initial = await collect(initial);
  report.checks.initial_exact_native_rows = true;
  report.phase = 'actual-refresh'; diagnostic.beginProducts(2);
  await tap();
  const refreshed = await products(2); await unchanged(refreshed, initial);
  report.observations.refresh = await collect(refreshed);
  report.checks.actual_tap_refresh = true;
  report.phase = 'background-resume-fresh'; diagnostic.beginProducts(3);
  await tap();
  const third = await products(3); await unchanged(third, initial);
  report.observations.before_background = await collect(third);
  const before = await diagnostic.at('product_snapshot', snapshot);
  await diagnostic.at('before_background', () => {
    assert.equal(before.current_lifecycle, 'resumed'); tables(before, third);
  });
  const baseline = await lifecycleWithinWindow(context, third.products, true);
  await diagnostic.at('lifecycle_validate', () => {
    assert.equal(baseline.current_lifecycle, 'resumed');
    assert.ok(baseline.callback_state === null || baseline.callback_state === 'resumed');
  });
  await diagnostic.timed('home_command_ms', () => diagnostic.at('background_home',
    () => adb(['shell', 'input', 'keyevent', 'KEYCODE_HOME'])));
  diagnostic.waitingFor = 'background_wait';
  let polls = 0;
  await waitFor(async () => {
    diagnostic.noteTiming(() => ({ background_polls: ++polls, callback_advance: null }));
    const value = await lifecycleWithinWindow(context, third.products);
    return diagnostic.at('lifecycle_validate', () => {
      assert.ok(value.callback_sequence >= baseline.callback_sequence);
      diagnostic.noteTiming(() => ({ callback_advance: value.callback_sequence - baseline.callback_sequence }));
      return value.callback_sequence > baseline.callback_sequence && ['hidden', 'paused'].includes(value.current_lifecycle)
        && value.callback_state === value.current_lifecycle ? value : null;
    });
  });
  diagnostic.waitingFor = null;
  await diagnostic.at('background_pause', async () => { await sleep(6000); remaining(); });
  diagnostic.waitingFor = 'resume_wait';
  const resumed = await resumeInstalledApp({ adb: args => diagnostic.at('resume_start', () => adb(args)), waitFor,
    snapshot: () => diagnostic.at('resume_snapshot', snapshot) });
  diagnostic.waitingFor = null;
  await diagnostic.at('product_tables', () => tables(resumed, third));
  const current = await lifecycleWithinWindow(context, third.products);
  await diagnostic.at('lifecycle_validate', () => {
    assert.equal(current.current_lifecycle, 'resumed'); assert.equal(current.callback_state, 'resumed');
    assert.ok(current.callback_sequence > baseline.callback_sequence);
  });
  const final = await control();
  await diagnostic.at('final_requests', async () => {
    validateLiveControl(final); assert.equal(final.active, false);
    assert.deepEqual(final.calls, { weather: 3, air_quality: 3 });
    assert.deepEqual(final.completed, final.calls); assert.deepEqual(final.products, third.products);
    assert.deepEqual(final.response_sha256, third.response_sha256);
  });
  report.observations.after_resume = Object.fromEntries(['weather', 'air_quality'].map(name =>
    [name, verifyTable(resumed.tables.find(table => table.product === name), third.products[name])]));
  report.observations.bindings = Object.fromEntries(['weather', 'air_quality'].map(name =>
    [name, { forecast_sha256: initial.products[name].delivery.sha256,
      immutable_product_sha256: digest(immutable(initial.products[name])) }]));
  report.observations.requests = { weather: 3, air_quality: 3 };
  report.observations.lifecycle = resumed.lifecycle;
  Object.assign(report.checks, { third_refresh_exact_native_rows: true, real_android_background_resume: true,
    original_products_fresh_after_resume: true, no_extra_product_requests: true });
  report.scope.mounted_widget_tables = true; report.scope.real_adb_interaction = true;
  report.phase = 'complete'; report.passed = true;
}

export function nativeDriverProfile(args) {
  assert.ok(args.length === 6 || args.length === 8);
  assert.equal(args[0], '--adb'); assert.equal(args[2], '--serial'); assert.equal(args[4], '--output');
  if (args.length === 6) return 'synthetic';
  assert.equal(args[6], '--profile'); assert.equal(args[7], 'protected-core');
  return 'protected-core';
}

async function main() {
  const profile = nativeDriverProfile(process.argv.slice(2));
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
  if (profile === 'protected-core') {
    report.schema = 2; report.kind = 'overmorrow-installed-android-protected-core-trial';
    report.profile = profile; report.joined_core_acceptance = false;
    Object.assign(report.scope, { synthetic_weather: false, synthetic_air_quality: false, expiry_proven: false });
  }
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
  const control = path => readFixtureControl({ remaining, diagnostic, profile }, path);
  async function waitFor(check, milliseconds = 15000) {
    return waitForObservation(check, deadline, remaining, milliseconds);
  }
  let isolate;
  async function snapshot() { remaining(); return validateSnapshot(await vm.request(EXTENSION, { isolateId: isolate })); }
  async function lifecycle() { remaining(); return readLifecycle(vm, isolate); }
  try {
    const initialPrepared = profile === 'synthetic'
      ? await prepareNativePhase({ control, waitFor, adb, diagnostic, remaining }, 'initial') : null;
    if (profile === 'protected-core') {
      const initial = await control();
      assert.deepEqual(initial.calls, { weather: 0, air_quality: 0 }); assert.equal(initial.active, false);
    }
    const pid = await startInstalledApp({ adb, waitFor, diagnostic,
      installed() { report.scope.installed_android_app = true; }, ownApp() { appOwned = true; } });
    report.phase = 'read-only-observer';
    isolate = await observeVm({ adb, waitFor, pid, diagnostic,
      ownForward(value) { forward = value; report.cleanup.forward_removed = false; },
      ownVm(value) { vm = value; report.cleanup.vm_closed = false; } });
    const exercise = profile === 'synthetic' ? exerciseNativeProducts : exerciseLiveNativeProducts;
    await exercise({ report, diagnostic, control, waitFor, snapshot, lifecycle, adb, remaining, initialPrepared });
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
