// SPDX-License-Identifier: GPL-3.0-only
// Explicit disposable profile-6 evidence, never default product logging.
// Original CLI stdout remains private; this observation is not overlay proof.
import { constants } from 'node:fs';
import { lstat, open, readdir, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { isAbsolute, resolve } from 'node:path';
import { requireThat } from './forecast.mjs';

export const ANDROID_PROOF_PROFILE = 'android-protected-core-v6';
const MAX_RECEIPT = 16384;
const CLOSE_TIMEOUT_MS = 5000;
const KEYS = ['operation', 'bytes', 'chunks', 'publisher_key', 'name', 'revision', 'manifest_id',
  'publication_expires_unix_seconds', 'sha256', 'local_delivery', 'output_mode', 'ownership_changed',
  'origin_authenticated', 'globally_latest', 'peer_bytes', 'providers_used', 'origin_body_bytes',
  'origin_range_requests', 'provider_peer_ids', 'control_relay_peer_id', 'cache_only', 'cache', 'local_output'].sort();
const HEX = /^[a-f0-9]{64}$/, PEER = /^[1-9A-HJ-NP-Za-km-z]{1,128}$/;
const same = (a, b) => a.dev === b.dev && a.ino === b.ino;
const privateDirectory = info => info.isDirectory() && info.uid === process.getuid() && (info.mode & 0o777) === 0o700;

function validatedReceipt(stdout) {
  requireThat(Buffer.isBuffer(stdout) && stdout.length > 0 && stdout.length <= MAX_RECEIPT, 'PROOF_RECEIPT_INVALID');
  const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(stdout));
  requireThat(value && typeof value === 'object' && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify(KEYS), 'PROOF_RECEIPT_INVALID');
  requireThat(value.operation === 'named_content_download' && value.local_delivery === true && value.output_mode === '0600'
    && ['ownership_changed', 'origin_authenticated', 'globally_latest', 'cache_only'].every(key => value[key] === false)
    && ['publisher_key', 'manifest_id', 'sha256'].every(key => typeof value[key] === 'string' && HEX.test(value[key]))
    && typeof value.name === 'string' && value.name.length > 0 && Buffer.byteLength(value.name) <= 128
    && !/[\x00-\x1f\x7f]/.test(value.name)
    && ['cache', 'local_output'].every(key => typeof value[key] === 'string' && isAbsolute(value[key])
      && resolve(value[key]) === value[key] && !/[\x00-\x1f\x7f]/.test(value[key])), 'PROOF_RECEIPT_INVALID');
  requireThat(['bytes', 'chunks', 'revision', 'publication_expires_unix_seconds'].every(key => Number.isSafeInteger(value[key]) && value[key] > 0)
    && value.bytes <= 256 * 1024 * 1024 && value.chunks <= 1024
    && Number.isSafeInteger(value.peer_bytes) && value.peer_bytes >= 0 && value.peer_bytes <= value.bytes
    && Number.isSafeInteger(value.providers_used) && value.providers_used >= 0 && value.providers_used <= 16
    && value.origin_body_bytes === 0 && value.origin_range_requests === 0
    && Array.isArray(value.provider_peer_ids) && value.provider_peer_ids.length === value.providers_used
    && new Set(value.provider_peer_ids).size === value.providers_used
    && value.provider_peer_ids.every(peer => typeof peer === 'string' && PEER.test(peer) && peer !== value.control_relay_peer_id)
    && typeof value.control_relay_peer_id === 'string' && (value.control_relay_peer_id === '' || PEER.test(value.control_relay_peer_id)),
  'PROOF_RECEIPT_INVALID');
}

export async function openAndroidProofReceipts(directory) {
  requireThat(process.platform === 'linux' && typeof process.getuid === 'function'
    && typeof directory === 'string' && isAbsolute(directory) && resolve(directory) === directory
    && !/[\x00-\x1f\x7f]/.test(directory) && await realpath(directory) === directory, 'PROOF_DIRECTORY_INVALID');
  const parent = await open(directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  const expected = new Map(), counts = { weather: 0, air_quality: 0 };
  let closed = false, closing = false, failed = false;
  let active = null, retirement, closePromise;
  let before;
  async function identity() {
    requireThat(!closed && privateDirectory(before) && privateDirectory(await parent.stat())
      && same(before, await lstat(directory)) && await realpath(directory) === directory, 'PROOF_DIRECTORY_CHANGED');
    const names = await readdir(`/proc/self/fd/${parent.fd}`);
    requireThat(names.length === expected.size && names.every(name => expected.has(name)), 'PROOF_DIRECTORY_CHANGED');
    for (const [name, saved] of expected) {
      const current = await lstat(`/proc/self/fd/${parent.fd}/${name}`);
      requireThat(saved && current.isFile() && same(saved, current) && current.nlink === 1
        && current.uid === saved.uid && current.mode === saved.mode && current.size === saved.size
        && current.mtimeMs === saved.mtimeMs && current.ctimeMs === saved.ctimeMs, 'PROOF_FILE_CHANGED');
    }
  }
  try { before = await parent.stat(); await identity(); } catch (error) { await parent.close(); throw error; }

  async function observeReceipt(event, { signal, deadline } = {}) {
    requireThat(!failed && !closed && !closing && active === null, 'PROOF_SINK_UNAVAILABLE');
    const operation = writeObservation(event, signal, deadline);
    active = operation;
    try { await operation; }
    finally { active = null; }
  }

  async function writeObservation(event, signal, deadline) {
    const check = () => requireThat(!closing && !signal?.aborted
      && Number.isFinite(deadline) && performance.now() < deadline, 'CANCELLED');
    try {
      check();
      requireThat(event && Object.hasOwn(counts, event.product) && counts[event.product] < 3
        && Number.isSafeInteger(event.startedAt) && event.startedAt > 0
        && Number.isSafeInteger(event.completedAt) && event.completedAt >= event.startedAt
        && event.completedAt - event.startedAt <= 185000 && typeof event.reuseCache === 'boolean', 'PROOF_OBSERVATION_INVALID');
      validatedReceipt(event.stdout);
      await identity(); check();
      const ordinal = ++counts[event.product];
      const metadata = Buffer.from(JSON.stringify({ schema: 1, kind: 'weather-android-core-receipt-observation',
        profile: ANDROID_PROOF_PROFILE, product: event.product, ordinal, started_at_ms: event.startedAt,
        completed_at_ms: event.completedAt, reuse_cache: event.reuseCache, stdout_bytes: event.stdout.length,
        stdout_sha256: createHash('sha256').update(event.stdout).digest('hex') }) + '\n');
      // At most two small, exclusive regular-file writes per successful call.
      // No detached writer/race, renewal, retry or HTTP-served evidence directory.
      for (const [suffix, bytes] of [['receipt.json', event.stdout], ['observation.json', metadata]]) {
        check();
        const name = `${event.product}-${ordinal}.${suffix}`;
        const file = await open(`/proc/self/fd/${parent.fd}/${name}`,
          constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0o600);
        expected.set(name, null);
        try {
          const info = await file.stat();
          requireThat(info.isFile() && info.uid === process.getuid() && info.nlink === 1
            && (info.mode & 0o777) === 0o600 && info.size === 0, 'PROOF_FILE_INVALID');
          check(); await file.writeFile(bytes, { signal }); check();
          const after = await file.stat();
          requireThat(same(info, after) && after.size === bytes.length && after.nlink === 1
            && after.uid === info.uid && after.mode === info.mode, 'PROOF_FILE_CHANGED');
          expected.set(name, after);
        } finally { await file.close(); }
        check();
      }
      await identity(); check();
    } catch (error) { failed = true; throw error; }
  }

  return Object.freeze({ observeReceipt, close() {
    if (closePromise) return closePromise;
    // Stop admission synchronously, including while an existing filesystem open
    // is pending. Its /proc/self/fd path must retain the same pinned directory.
    closing = true;
    const running = active;
    retirement = (async () => {
      if (running) await running.catch(() => {});
      try { await identity(); }
      finally { closed = true; await parent.close(); }
    })();
    closePromise = (async () => {
      let timer;
      try {
        await Promise.race([retirement, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('PROOF_CLEANUP_UNCONFIRMED')), CLOSE_TIMEOUT_MS);
        })]);
      } finally { clearTimeout(timer); }
    })();
    // On an incomplete join the sink still owns both promises and the handle.
    // Only real observer settlement retires it; timeout is never cleanup proof.
    return closePromise;
  } });
}
