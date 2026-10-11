// SPDX-License-Identifier: GPL-3.0-only
import { toProviderForecast, PROVIDER_SCHEMA } from './provider.mjs';

export const ENDPOINT = '/api/volparossa/forecast';
export const MAX_PROVIDER_BYTES = 524288;
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

/** Validate the displayed projection against the original forecast, not just its label.
 * @param {any} value
 * @param {string} now
 */
export function validateProvider(value, now = new Date().toISOString()) {
  if (!value || value.schema !== PROVIDER_SCHEMA || value.kind !== 'forecast'
      || value.verification_scope !== 'forecast-schema-and-freshness-only'
      || !Array.isArray(value.series) || value.delivery?.mode !== 'core-cache'
      || value.delivery.upstream_origin_attested !== false
      || value.delivery.manifest_media_type_checked !== false
      || typeof value.delivery.publication_expires_at !== 'string'
      || value.freshness?.publication_expires_at !== value.delivery.publication_expires_at) {
    throw new Error('FORECAST_INVALID');
  }
  const projected = toProviderForecast(value.forecast, {
    variables: value.series.map((/** @type {any} */ item) => item?.variable), now,
    publicationExpires: value.delivery.publication_expires_at
  });
  if (value.forecast.area.sharing !== 'public-community'
      || !same(value.timeline, projected.timeline) || !same(value.series, projected.series)
      || !same(value.capabilities, projected.capabilities)
      || value.freshness.expires_at !== projected.freshness.expires_at) {
    throw new Error('FORECAST_INVALID');
  }
  return { ...projected, delivery: value.delivery };
}

/** @param {typeof fetch} fetcher @param {AbortSignal} signal */
export async function fetchProvider(fetcher, signal) {
  const response = await fetcher(ENDPOINT, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    headers: { Accept: 'application/json' }, signal
  });
  if (!response.ok || !response.headers.get('content-type')?.startsWith('application/json')
      || !response.body) throw new Error('FORECAST_UNAVAILABLE');
  const reader = response.body.getReader();
  const parts = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_PROVIDER_BYTES) throw new Error('FORECAST_TOO_LARGE');
      parts.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  return validateProvider(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
}

/** Internal display helpers preserve null and genuine zero separately.
 * @param {any} forecast @param {string} variable @param {number} index */
export function displayValue(forecast, variable, index) {
  const field = forecast.series.find((/** @type {any} */ item) => item.variable === variable);
  const value = field?.values?.[index];
  if (!Number.isFinite(value)) return 'Not available';
  // Preserve small nonzero accumulated amounts instead of rounding them dry.
  return variable === 'precipitation' ? String(value) : Number(value).toFixed(1);
}

/** @param {any} forecast */
export function hasSupportedPrecipitation(forecast) {
  const field = forecast.series.find((/** @type {any} */ item) => item.variable === 'precipitation');
  return field?.availability === 'supported' && field.unit === 'mm'
    && field.statistic === 'accumulation' && Array.isArray(field.accumulation_windows);
}

/** Use the supplied accumulation window, never infer it from adjacent points.
 * @param {any} forecast @param {number} index */
export function displayAccumulationWindow(forecast, index) {
  const field = forecast.series.find((/** @type {any} */ item) => item.variable === 'precipitation');
  const window = field?.accumulation_windows?.[index];
  return hasSupportedPrecipitation(forecast) && typeof window?.start_at === 'string'
    && typeof window?.end_at === 'string' ? `${window.start_at} → ${window.end_at}` : 'Not available';
}
