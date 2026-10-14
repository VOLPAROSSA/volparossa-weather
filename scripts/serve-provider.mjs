#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
// Explicit local development server. Never discovers or publishes a user's location.
import { parseArgs } from 'node:util';
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, resolve } from 'node:path';
import { startProviderHttp } from '../src/provider-http.mjs';
import { requireThat } from '../src/forecast.mjs';

let proof;
try {
  const { values } = parseArgs({ options: { config: { type: 'string' }, 'static-root': { type: 'string' },
    'static-profile': { type: 'string', default: 'default' },
    port: { type: 'string' }, socket: { type: 'string' },
    'proof-profile': { type: 'string' }, 'private-receipt-directory': { type: 'string' } } });
  const unix = values.socket !== undefined, port = values.port ?? '8788';
  const observing = values['proof-profile'] !== undefined || values['private-receipt-directory'] !== undefined;
  requireThat(!observing || (unix && values['proof-profile'] === 'android-protected-core-v6'
    && typeof values['private-receipt-directory'] === 'string'
    && dirname(values.socket) !== values['private-receipt-directory']), 'BRIDGE_CONFIG_INVALID');
  requireThat(typeof values.config === 'string' && isAbsolute(values.config) && resolve(values.config) === values.config
    && await realpath(values.config) === values.config && (unix
      ? values.port === undefined && values['static-root'] === undefined && values['static-profile'] === 'default'
      : /^\d{1,5}$/.test(port)), 'BRIDGE_CONFIG_INVALID');
  const file = await open(values.config, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let config;
  try {
    const stat = await file.stat();
    requireThat(stat.isFile() && stat.nlink === 1 && stat.uid === process.getuid()
      && (stat.mode & 0o777) === 0o600 && stat.size > 0 && stat.size <= 16384, 'BRIDGE_CONFIG_INVALID');
    const bytes = Buffer.alloc(stat.size + 1), { bytesRead } = await file.read(bytes, 0, bytes.length, 0);
    requireThat(bytesRead === stat.size, 'BRIDGE_CONFIG_INVALID');
    config = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, bytesRead)));
  } finally { await file.close(); }
  if (observing) {
    // Fixed lazy dependency keeps historical, non-observing bundles unchanged.
    const { openAndroidProofReceipts } = await import('../src/android-proof-receipts.mjs');
    proof = await openAndroidProofReceipts(values['private-receipt-directory']);
  }
  const server = await startProviderHttp({ config, staticRoot: values['static-root'],
    staticProfile: values['static-profile'], ...(unix ? { socketPath: values.socket } : { port: Number(port) }) },
  proof ? { observeReceipt: proof.observeReceipt } : undefined);
  let stopping = false;
  const stop = async () => {
    if (stopping) return; stopping = true;
    try { try { await server.close(); } finally { await proof?.close(); } }
    catch { process.stderr.write('{"error":"BRIDGE_CLEANUP_UNCONFIRMED"}\n'); process.exitCode = 1; }
  };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  process.stdout.write(JSON.stringify({ listening: server.origin, ...(unix ? { transport: 'unix' } : {}),
    scope: 'fixed-public-community-forecast' }) + '\n');
} catch {
  await proof?.close().catch(() => {});
  process.stderr.write('{"error":"BRIDGE_START_FAILED"}\n'); process.exitCode = 1;
}
