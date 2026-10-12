#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
// Bind two actual cold core receipts to Overmorrow's source-native tables.
// This prepares evidence only: it does not acquire, publish, or execute core.
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { requireThat } from '../../src/forecast.mjs';
import { canonical, prepareExpectedV2 } from '../drizzli/prepare-core-browser.mjs';

export { canonical };
const sha = value => createHash('sha256').update(value).digest('hex');

export function prepareExpected(bytes, receiptBytes, aqBytes, aqReceiptBytes, config, coreSha256) {
  // Reuse the existing cold-transfer and query checks, not Drizzli's formatter.
  const value = prepareExpectedV2(bytes, receiptBytes, aqBytes, aqReceiptBytes, config, coreSha256,
    (provider, variable, index) => {
      const field = provider.series.find(field => field.variable === variable);
      const number = field?.values?.[index];
      return number === null || number === undefined ? 'Not available' : String(number);
    }, (provider, index) => {
      const window = provider.series.find(field => field.variable === 'precipitation').accumulation_windows[index];
      return `${window.start_at} → ${window.end_at}`;
    });
  value.schema = 3;
  for (const product of Object.values(value.products)) {
    const { source, area } = product.forecast;
    Object.assign(product.display, {
      coordinates: `Public community area: ${area.latitude}, ${area.longitude}`,
      acquired_at: source.acquired_at,
      ...Object.fromEntries(['attribution', 'license', 'license_url', 'changes'].map(key => [key, source[key]])),
    });
    product.display_sha256 = sha(canonical(product.display));
  }
  value.display_sha256 = sha(canonical(Object.fromEntries(Object.entries(value.products)
    .map(([name, product]) => [name, product.display]))));
  return value;
}

export function prepareExpectedV5(...args) {
  // Identical source-native numbers, windows and cold-receipt checks. Only the
  // explicitly selected public-input profile/schema changes, never formatting.
  return { ...prepareExpected(...args), schema: 5 };
}

async function readPrivate(path, maximum) {
  requireThat(typeof path === 'string' && isAbsolute(path) && resolve(path) === path
    && await realpath(path) === path, 'CORE_BROWSER_PATH_INVALID');
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await handle.stat();
    requireThat(info.isFile() && info.nlink === 1 && [0, process.getuid()].includes(info.uid)
      && (info.mode & 0o777) === 0o600 && info.size > 0 && info.size <= maximum, 'CORE_BROWSER_FILE_INVALID');
    const bytes = Buffer.alloc(info.size + 1), { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
    const after = await handle.stat();
    requireThat(bytesRead === info.size && after.size === info.size && after.mtimeMs === info.mtimeMs
      && after.ctimeMs === info.ctimeMs, 'CORE_BROWSER_FILE_CHANGED');
    return bytes.subarray(0, bytesRead);
  } finally { await handle.close(); }
}

async function main() {
  const { values } = parseArgs({ options: Object.fromEntries(
    ['forecast', 'receipt', 'air-quality', 'air-quality-receipt', 'config', 'core-sha256', 'output', 'bundle-version']
      .map(name => [name, { type: 'string' }])) });
  const version = values['bundle-version'] ?? '3';
  requireThat(version === '3' || version === '5', 'CORE_BROWSER_BUNDLE_VERSION_INVALID');
  const decode = bytes => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  const weather = await readPrivate(values.forecast, 131072), receipt = await readPrivate(values.receipt, 16384);
  const aq = await readPrivate(values['air-quality'], 131072);
  const aqReceipt = await readPrivate(values['air-quality-receipt'], 16384);
  requireThat(decode(receipt).local_output === values.forecast
    && decode(aqReceipt).local_output === values['air-quality'], 'COLD_CORE_OUTPUT_MISMATCH');
  const config = decode(await readPrivate(values.config, 16384));
  const expected = (version === '5' ? prepareExpectedV5 : prepareExpected)(
    weather, receipt, aq, aqReceipt, config, values['core-sha256']);
  const raw = Buffer.from(JSON.stringify(expected, null, 2) + '\n');
  requireThat(raw.length <= 384 * 1024 && typeof values.output === 'string'
    && isAbsolute(values.output) && resolve(values.output) === values.output
    && await realpath(dirname(values.output)) === dirname(values.output), 'CORE_BROWSER_OUTPUT_INVALID');
  const output = await open(values.output, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o400);
  try { await output.writeFile(raw); await output.sync(); } finally { await output.close(); }
  process.stdout.write(JSON.stringify({ prepared: true, expected_sha256: sha(raw), display_sha256: expected.display_sha256 }) + '\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('{"error":"CORE_BROWSER_PREPARATION_FAILED"}\n'); process.exitCode = 1; });
}
