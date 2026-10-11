#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
// Disposable joined-proof preparation, not a publisher or a source of weather data.
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { parseForecast, requireThat } from '../../src/forecast.mjs';
import { toProviderForecast } from '../../src/provider.mjs';
import { parseAirQualityForecast } from '../../src/air-quality.mjs';
import { toAirQualityProviderForecast } from '../../src/air-quality-provider.mjs';
import { providerHttpConfiguration } from '../../src/provider-http.mjs';

const hex = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const sha = value => createHash('sha256').update(value).digest('hex');
export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

export function prepareExpected(bytes, receiptBytes, config, coreSha256, displayValue) {
  requireThat(hex(coreSha256) && typeof displayValue === 'function', 'CORE_BROWSER_INPUT_INVALID');
  const configuration = providerHttpConfiguration(config);
  requireThat(!configuration.airQuality && !configuration.core.query.includePrecipitation, 'CORE_BROWSER_INPUT_INVALID');
  return { schema: 1, core_sha256: coreSha256,
    ...prepareProduct(bytes, receiptBytes, configuration, displayValue) };
}

function prepareProduct(bytes, receiptBytes, configuration, displayValue, accumulationWindow = null, airQuality = false) {
  const core = configuration.core;
  const forecast = airQuality ? parseAirQualityForecast(bytes) : parseForecast(bytes);
  const receipt = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(receiptBytes));
  requireThat(receipt?.operation === 'named_content_download' && receipt.publisher_key === core.publisherKey
    && receipt.name === core.name && Number.isSafeInteger(receipt.revision) && receipt.revision >= core.minRevision
    && hex(receipt.manifest_id) && receipt.sha256 === sha(bytes) && receipt.bytes === bytes.length
    && receipt.cache === core.cache && receipt.local_delivery === true && receipt.output_mode === '0600'
    && receipt.ownership_changed === false && receipt.origin_authenticated === false
    && receipt.globally_latest === false && receipt.cache_only === false
    && receipt.peer_bytes === bytes.length && Number.isSafeInteger(receipt.providers_used)
    && receipt.providers_used >= 1 && receipt.origin_body_bytes === 0 && receipt.origin_range_requests === 0
    && Number.isSafeInteger(receipt.publication_expires_unix_seconds)
    && receipt.publication_expires_unix_seconds > 0, 'COLD_CORE_RECEIPT_INVALID');
  const publicationExpires = new Date(receipt.publication_expires_unix_seconds * 1000).toISOString();
  const provider = (airQuality ? toAirQualityProviderForecast : toProviderForecast)(forecast,
    { variables: configuration.variables, publicationExpires });
  requireThat(forecast.area.sharing === 'public-community' && forecast.area.latitude === core.query.latitude
    && forecast.area.longitude === core.query.longitude && forecast.source.model === core.query.model
    && forecast.source.model_run_at === core.query.run
    && (airQuality || Object.hasOwn(forecast.units, 'wind_10m') === core.query.includeWind
      && Object.hasOwn(forecast.units, 'precipitation') === core.query.includePrecipitation)
    && canonical(forecast.samples.map(sample => sample.lead_hours)) === canonical(core.query.steps),
  'CORE_BROWSER_QUERY_MISMATCH');
  const display = {
    coordinates: `${forecast.area.latitude}° latitude, ${forecast.area.longitude}° longitude`,
    native: provider.timeline.valid_at,
    values: provider.timeline.valid_at.map((_, index) => (airQuality ? ['pm2_5', 'pm10']
      : ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', ...(accumulationWindow ? ['precipitation'] : [])])
      .map(variable => displayValue(provider, variable, index))
      .concat(accumulationWindow ? [accumulationWindow(provider, index)] : [])),
    model_run: `${forecast.source.model} · ${forecast.source.model_run_at}`,
    expires_at: provider.freshness.expires_at,
    ...(airQuality ? Object.fromEntries(['attribution', 'license', 'license_url', 'changes']
      .map(key => [key, forecast.source[key]])) : {}),
  };
  return { cold_receipt_sha256: sha(receiptBytes),
    publication: { publisher_key: receipt.publisher_key, name: receipt.name, revision: receipt.revision,
      manifest_id: receipt.manifest_id, sha256: receipt.sha256, bytes: receipt.bytes,
      expires_unix_seconds: receipt.publication_expires_unix_seconds },
    forecast, display, display_sha256: sha(canonical(display)) };
}

export function prepareExpectedV2(bytes, receiptBytes, airQualityBytes, airQualityReceiptBytes,
  config, coreSha256, displayValue, displayAccumulationWindow) {
  requireThat(hex(coreSha256) && typeof displayValue === 'function'
    && typeof displayAccumulationWindow === 'function', 'CORE_BROWSER_INPUT_INVALID');
  const configuration = providerHttpConfiguration(config), aq = configuration.airQuality;
  requireThat(aq && configuration.core.query.includeWind && configuration.core.query.includePrecipitation
    && ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation']
      .every(value => configuration.variables.includes(value))
    && canonical(aq.variables) === canonical(['pm2_5', 'pm10'])
    && configuration.core.name !== aq.core.name && configuration.core.cache !== aq.core.cache
    && ['executable', 'controlSocket', 'scratchParent'].every(key => configuration.core[key] === aq.core[key]),
  'CORE_BROWSER_PRODUCTS_INVALID');
  const products = {
    weather: prepareProduct(bytes, receiptBytes, configuration, displayValue, displayAccumulationWindow),
    air_quality: prepareProduct(airQualityBytes, airQualityReceiptBytes, aq, displayValue, null, true),
  };
  return { schema: 2, core_sha256: coreSha256, products,
    display_sha256: sha(canonical(Object.fromEntries(Object.entries(products).map(([key, product]) => [key, product.display])))) };
}

async function readPrivate(path, maximum, mode) {
  requireThat(typeof path === 'string' && isAbsolute(path) && resolve(path) === path
    && await realpath(path) === path, 'CORE_BROWSER_PATH_INVALID');
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await handle.stat();
    requireThat(info.isFile() && info.nlink === 1 && [0, process.getuid()].includes(info.uid)
      && (info.mode & 0o777) === mode && info.size > 0 && info.size <= maximum, 'CORE_BROWSER_FILE_INVALID');
    const bytes = Buffer.alloc(info.size + 1), { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
    const after = await handle.stat();
    requireThat(bytesRead === info.size && after.size === info.size && after.mtimeMs === info.mtimeMs
      && after.ctimeMs === info.ctimeMs, 'CORE_BROWSER_FILE_CHANGED');
    return bytes.subarray(0, bytesRead);
  } finally { await handle.close(); }
}

async function main() {
  const { values } = parseArgs({ options: Object.fromEntries(
    ['forecast', 'receipt', 'air-quality', 'air-quality-receipt', 'config', 'core-sha256', 'output']
      .map(name => [name, { type: 'string' }])) });
  const v2 = values['air-quality'] !== undefined;
  requireThat(v2 === (values['air-quality-receipt'] !== undefined), 'CORE_BROWSER_INPUT_INVALID');
  const bytes = await readPrivate(values.forecast, 131072, 0o600);
  const receiptBytes = await readPrivate(values.receipt, 16384, 0o600);
  const receipt = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(receiptBytes));
  requireThat(receipt.local_output === values.forecast, 'COLD_CORE_OUTPUT_MISMATCH');
  const config = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await readPrivate(values.config, 16384, 0o600)));
  // This exact transferred module and both its imports are bound by the core bundle.
  const { displayValue, displayAccumulationWindow } = await import('../../build/drizzli-volparossa/src/lib/services/volparossa/client.mjs');
  let expected;
  if (v2) {
    const aqBytes = await readPrivate(values['air-quality'], 131072, 0o600);
    const aqReceiptBytes = await readPrivate(values['air-quality-receipt'], 16384, 0o600);
    requireThat(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(aqReceiptBytes)).local_output
      === values['air-quality'], 'COLD_CORE_OUTPUT_MISMATCH');
    expected = prepareExpectedV2(bytes, receiptBytes, aqBytes, aqReceiptBytes, config,
      values['core-sha256'], displayValue, displayAccumulationWindow);
  } else expected = prepareExpected(bytes, receiptBytes, config, values['core-sha256'], displayValue);
  const raw = Buffer.from(JSON.stringify(expected, null, 2) + '\n');
  requireThat(raw.length <= (v2 ? 384 : 192) * 1024 && typeof values.output === 'string'
    && isAbsolute(values.output) && resolve(values.output) === values.output
    && await realpath(dirname(values.output)) === dirname(values.output), 'CORE_BROWSER_OUTPUT_INVALID');
  const output = await open(values.output, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o400);
  try { await output.writeFile(raw); await output.sync(); } finally { await output.close(); }
  process.stdout.write(JSON.stringify({ prepared: true, expected_sha256: sha(raw), display_sha256: expected.display_sha256 }) + '\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('{"error":"CORE_BROWSER_PREPARATION_FAILED"}\n'); process.exitCode = 1; });
}
