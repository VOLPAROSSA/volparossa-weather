#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
// Explicit local development server. Never discovers or publishes a user's location.
import { parseArgs } from 'node:util';
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { isAbsolute, resolve } from 'node:path';
import { startProviderHttp } from '../src/provider-http.mjs';
import { requireThat } from '../src/forecast.mjs';

try {
  const { values } = parseArgs({ options: { config: { type: 'string' }, 'static-root': { type: 'string' },
    'static-profile': { type: 'string', default: 'default' },
    port: { type: 'string', default: '8788' } } });
  requireThat(typeof values.config === 'string' && isAbsolute(values.config) && resolve(values.config) === values.config
    && await realpath(values.config) === values.config && /^\d{1,5}$/.test(values.port), 'BRIDGE_CONFIG_INVALID');
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
  const server = await startProviderHttp({ config, staticRoot: values['static-root'],
    staticProfile: values['static-profile'], port: Number(values.port) });
  let stopping = false;
  const stop = async () => {
    if (stopping) return; stopping = true;
    try { await server.close(); }
    catch { process.stderr.write('{"error":"BRIDGE_CLEANUP_UNCONFIRMED"}\n'); process.exitCode = 1; }
  };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  process.stdout.write(JSON.stringify({ listening: server.origin, scope: 'fixed-public-community-forecast' }) + '\n');
} catch {
  process.stderr.write('{"error":"BRIDGE_START_FAILED"}\n'); process.exitCode = 1;
}
