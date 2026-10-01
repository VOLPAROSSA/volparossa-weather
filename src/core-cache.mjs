// SPDX-License-Identifier: GPL-3.0-only
// Node/Linux adapter to the existing trusted core CLI; never an origin fallback.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, realpath, mkdtemp, open, rm } from 'node:fs/promises';
import { isAbsolute, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { MAX_BYTES, WeatherError, freshness, parseForecast, request, requireThat } from './forecast.mjs';

const HEX = /^[a-f0-9]{64}$/;
const MAX_REPORT_BYTES = 16384;

function absolute(value) {
  requireThat(typeof value === 'string' && isAbsolute(value) && resolve(value) === value
    && !/[\x00-\x1f\x7f]/.test(value), 'PATH_INVALID');
  return value;
}

function groupExists(pid) {
  try { process.kill(-pid, 0); return true; }
  catch (error) { if (error.code === 'ESRCH') return false; throw error; }
}

export async function runOwnedJsonProcess(executable, args, cwd, signal, timeoutMs = 180000) {
  requireThat(!signal?.aborted, 'CANCELLED');
  const child = spawn(executable, args, { cwd, detached: true, shell: false,
    env: { LANG: 'C.UTF-8', RUST_LOG: 'off' }, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', outputBytes = 0, failure = null;
  let timer, killTimer;
  const stop = code => {
    failure ??= code;
    if (!child.pid) return;
    try { process.kill(-child.pid, 'SIGTERM'); } catch {}
    killTimer ??= setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }, 2000);
  };
  const abort = () => stop('CANCELLED');
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) abort();
  timer = setTimeout(() => stop('CORE_TIMEOUT'), timeoutMs);
  child.stdout.on('data', data => {
    outputBytes += data.length;
    if (outputBytes > MAX_REPORT_BYTES) stop('CORE_REPORT_TOO_LARGE');
    else stdout += data.toString('utf8');
  });
  // Discard diagnostics (which could contain file paths/private configuration).
  child.stderr.on('data', data => {
    outputBytes += data.length;
    if (outputBytes > MAX_REPORT_BYTES) stop('CORE_REPORT_TOO_LARGE');
  });
  const result = await new Promise(done => {
    child.once('error', () => { failure ??= 'CORE_START_FAILED'; });
    child.once('close', (code, exitSignal) => done({ code, exitSignal }));
  });
  clearTimeout(timer); clearTimeout(killTimer);
  signal?.removeEventListener('abort', abort);
  if (child.pid && groupExists(child.pid)) {
    // Never leave CLI descendants behind when its leader exits first.
    stop('CORE_DESCENDANT_REMAINS');
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
    for (let attempt = 0; attempt < 40 && groupExists(child.pid); attempt++) await delay(50);
    clearTimeout(killTimer);
    requireThat(!groupExists(child.pid), 'CORE_CLEANUP_UNCONFIRMED');
  }
  requireThat(failure === null, failure);
  requireThat(result.code === 0 && result.exitSignal === null, 'CORE_FAILED');
  try { return JSON.parse(stdout); } catch { throw new WeatherError('CORE_REPORT_INVALID'); }
}

export async function fetchCachedForecast({ mode, executable, controlSocket, cache, scratchParent,
  publisherKey, name, minRevision, query, reuseCache = false }, { signal } = {}) {
  requireThat(mode === 'core-cache', 'CORE_MODE_REQUIRED');
  requireThat(process.platform === 'linux' && typeof process.getuid === 'function', 'CORE_PLATFORM_UNAVAILABLE');
  const expected = request(query);
  requireThat(expected.communityArea, 'PUBLIC_COMMUNITY_AREA_REQUIRED');
  requireThat(typeof publisherKey === 'string' && HEX.test(publisherKey), 'PUBLISHER_INVALID');
  requireThat(typeof name === 'string' && Buffer.byteLength(name) > 0 && Buffer.byteLength(name) <= 128
    && !/[\x00-\x1f\x7f]/.test(name), 'NAME_INVALID');
  requireThat(Number.isSafeInteger(minRevision) && minRevision >= 1, 'REVISION_INVALID');
  requireThat(typeof reuseCache === 'boolean', 'REUSE_INVALID');
  for (const path of [executable, controlSocket, cache, scratchParent]) absolute(path);
  const parent = await lstat(scratchParent);
  requireThat(parent.isDirectory() && !parent.isSymbolicLink() && parent.uid === process.getuid()
    && (parent.mode & 0o777) === 0o700 && await realpath(scratchParent) === scratchParent, 'PRIVATE_PARENT_REQUIRED');
  const program = await lstat(executable);
  requireThat(program.isFile() && !program.isSymbolicLink() && await realpath(executable) === executable,
    'CORE_EXECUTABLE_INVALID');
  const socket = await lstat(controlSocket);
  requireThat(socket.isSocket() && !socket.isSymbolicLink(), 'CONTROL_SOCKET_INVALID');
  const work = await mkdtemp(join(scratchParent, 'forecast-'));
  const output = join(work, 'forecast.json');
  try {
    const args = ['--control-socket', controlSocket, 'content', 'fetch-name',
      '--publisher-key', publisherKey, '--name', name, '--min-revision', String(minRevision),
      '--cache', cache, '--local-output', output, '--quota-bytes', String(MAX_BYTES),
      '--max-entries', '16', '--min-free-bytes', '67108864'];
    if (reuseCache) args.push('--reuse-cache');
    const receipt = await runOwnedJsonProcess(executable, args, work, signal);
    requireThat(receipt && receipt.operation === 'named_content_download' && receipt.publisher_key === publisherKey
      && receipt.name === name && Number.isSafeInteger(receipt.revision) && receipt.revision >= minRevision
      && receipt.local_delivery === true && receipt.output_mode === '0600' && receipt.ownership_changed === false
      && receipt.origin_authenticated === false && receipt.globally_latest === false && receipt.cache_only === false
      && receipt.local_output === output && receipt.cache === cache && HEX.test(receipt.manifest_id)
      && HEX.test(receipt.sha256) && Number.isSafeInteger(receipt.bytes) && receipt.bytes > 0
      && receipt.bytes <= MAX_BYTES && Number.isSafeInteger(receipt.publication_expires_unix_seconds)
      && receipt.publication_expires_unix_seconds > 0, 'CORE_RECEIPT_INVALID');
    const file = await open(output, constants.O_RDONLY | constants.O_NOFOLLOW);
    let bytes;
    try {
      const stat = await file.stat();
      requireThat(stat.isFile() && stat.uid === process.getuid() && stat.nlink === 1
        && (stat.mode & 0o777) === 0o600 && stat.size === receipt.bytes, 'OUTPUT_INVALID');
      bytes = Buffer.alloc(receipt.bytes + 1);
      const { bytesRead } = await file.read(bytes, 0, bytes.length, 0);
      requireThat(bytesRead === receipt.bytes, 'OUTPUT_INVALID');
      bytes = bytes.subarray(0, bytesRead);
    } finally { await file.close(); }
    requireThat(createHash('sha256').update(bytes).digest('hex') === receipt.sha256, 'CORE_HASH_MISMATCH');
    const forecast = parseForecast(bytes);
    requireThat(forecast.area.sharing === 'public-community' && forecast.area.latitude === expected.latitude
      && forecast.area.longitude === expected.longitude && forecast.source.model === expected.model
      && forecast.source.model_run_at === expected.run
      && JSON.stringify(forecast.samples.map(sample => sample.lead_hours)) === JSON.stringify(expected.steps), 'FORECAST_QUERY_MISMATCH');
    const expiry = new Date(receipt.publication_expires_unix_seconds * 1000);
    requireThat(Number.isFinite(expiry.getTime()), 'CORE_RECEIPT_INVALID');
    const age = freshness(forecast, new Date().toISOString(), expiry.toISOString());
    requireThat(!age.stale, 'STALE_FORECAST');
    requireThat(!signal?.aborted, 'CANCELLED');
    return { forecast, delivery: { mode: 'core-cache', publisher_key: publisherKey, name,
      revision: receipt.revision, manifest_id: receipt.manifest_id, sha256: receipt.sha256,
      publication_expires_at: expiry.toISOString(), freshness: age,
      upstream_origin_attested: false, manifest_media_type_checked: false } };
  } finally {
    // Only our new, exact temporary output directory. The agent's verified cache remains.
    await rm(work, { recursive: true, force: false });
  }
}
