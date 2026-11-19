// SPDX-License-Identifier: GPL-3.0-only
// Observe the installed APK. Input comes from Android; snapshots are read-only.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { access, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { promisify } from 'node:util';
import { PACKAGE, HEADERS, ObserverDiagnostic, adbFailure, numberEqual, observeVm, readLifecycle,
  resumeInstalledApp, startInstalledApp, tapNativeRefresh, validateSnapshot, waitForObservation }
  from '../../integrations/overmorrow/native-android-driver.mjs';

const [adbPath, work] = process.argv.slice(2);
const run = promisify(execFile);
const diagnostic = new ObserverDiagnostic();
const deadline = Date.now() + 200000;
function remaining() { assert.ok(Date.now() < deadline, 'installed app observation deadline'); }
function waitFor(check, ms = 18000) { return waitForObservation(check, deadline, remaining, ms); }
async function adb(args) {
  try {
    return (await run(adbPath, ['-s', 'emulator-5554', ...args], { timeout: 8000, maxBuffer: 65536 })).stdout.trim();
  } catch (error) { throw adbFailure(error, { args, stdout: error.stdout, stderr: error.stderr }); }
}
async function file(name, timeout) {
  await waitFor(async () => {
    try { await access(join(work, name)); return true; }
    catch (error) { if (error.code !== 'ENOENT') throw error; return false; }
  }, timeout);
}
function productTable(view, kind, body) {
  const table = view.tables.find(row => row.product === kind);
  if (!table) return false;
  assert.deepEqual(table.headers, HEADERS[kind]);
  const [sample] = body.forecast.samples;
  const [row] = table.rows;
  if (table.rows.length !== 1 || row[0] !== sample.valid_at) return false;
  if (kind === 'air_quality') return Number.isFinite(sample.pm2_5) && Number.isFinite(sample.pm10)
    && numberEqual(row[1], sample.pm2_5) && numberEqual(row[2], sample.pm10);
  return numberEqual(row[1], sample.temperature_2m) && row.slice(2).every(cell => cell === 'Not available');
}

let vm, forward, started, isolate;
const observations = {};
async function snapshot() { return validateSnapshot(await vm.request('ext.volparossa.native_snapshot', { isolateId: isolate })); }
async function swipe(view) {
  const { width, height } = view.screen;
  await adb(['shell', 'input', 'swipe', String(Math.round(width / 2)), String(Math.round(height * .78)),
    String(Math.round(width / 2)), String(Math.round(height * .24)), '250']);
  await pause(200);
}
try {
  const pid = await startInstalledApp({ adb, waitFor, diagnostic, installed() {}, ownApp() { started = true; } });
  isolate = await observeVm({ adb, waitFor, pid, diagnostic, ownForward(value) { forward = value; }, ownVm(value) { vm = value; } });
  for (const phase of ['initial', 'refused', 'recovered']) {
    await file(phase + '.ready', 70000);
    if (phase === 'refused') {
      const resumed = await resumeInstalledApp({ adb, waitFor, snapshot });
      await waitFor(async () => {
        const view = await snapshot();
        return view.labels.includes('Expired — refresh required; values are hidden') && !view.tables.some(t => t.product === 'weather');
      });
      assert.equal(resumed.current_lifecycle, 'resumed');
    }
    if (phase !== 'initial') await tapNativeRefresh({ diagnostic, waitFor, snapshot, swipe, adb, remaining });
    await file(phase + '.json', 20000);
    const { weather, air } = JSON.parse(await readFile(join(work, phase + '.json')));
    assert.equal(weather[0], phase === 'refused' ? 503 : 200);
    assert.equal(air[0], 200);
    const view = await waitFor(async () => {
      const value = await snapshot();
      const weatherMatches = phase === 'refused'
        ? value.labels.includes('Weather unavailable or expired') && !value.tables.some(t => t.product === 'weather')
        : productTable(value, 'weather', weather[1]) && value.labels.includes('Expires ' + weather[1].freshness.expires_at);
      return weatherMatches && productTable(value, 'air_quality', air[1]) ? value : null;
    });
    const aq = air[1].delivery;
    observations[phase] = { weather_http: weather[0], air_quality_http: air[0], air_quality_manifest: aq.manifest_id,
      weather_manifest: weather[1].delivery?.manifest_id ?? null, weather_revision: weather[1].delivery?.revision ?? null,
      weather_table: view.tables.find(t => t.product === 'weather')?.rows ?? [], air_quality_table: view.tables.find(t => t.product === 'air_quality').rows };
    if (phase === 'initial') {
      await adb(['shell', 'input', 'keyevent', 'KEYCODE_HOME']);
      await waitFor(async () => ['hidden', 'paused'].includes((await readLifecycle(vm, isolate)).current_lifecycle));
    }
    await writeFile(join(work, phase + '.observed'), '', { flag: 'wx' });
  }
  assert.notEqual(observations.initial.weather_manifest, observations.recovered.weather_manifest);
  assert.deepEqual([observations.initial.weather_revision, observations.recovered.weather_revision], [1, 2]);
  assert.deepEqual(observations.initial.weather_table, observations.recovered.weather_table);
  for (const phase of ['refused', 'recovered']) {
    assert.equal(observations.initial.air_quality_manifest, observations[phase].air_quality_manifest);
    assert.deepEqual(observations.initial.air_quality_table, observations[phase].air_quality_table);
  }
} catch (error) {
  console.error('Android observation', diagnostic.subphase, diagnostic.waitingFor, error.name, error.code ?? '');
  throw error;
} finally {
  if (vm) await vm.close();
  if (forward) await adb(['forward', '--remove', forward]);
  if (started) await adb(['shell', 'am', 'force-stop', PACKAGE]);
}
await writeFile(join(work, 'installed.json'), JSON.stringify({ installed: true, real_refresh_taps: 2,
  background_expiry_hidden: true, observations }) + '\n', { flag: 'wx' });
