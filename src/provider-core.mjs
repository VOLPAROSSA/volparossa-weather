// SPDX-License-Identifier: GPL-3.0-only
// Node/Linux boundary. Reuses the existing real core-cache adapter unchanged.
import { fetchCachedForecast } from './core-cache.mjs';
import { providerVariables, toProviderForecast } from './provider.mjs';
import { fetchCachedAirQuality } from './air-quality-core.mjs';
import { toAirQualityProviderForecast } from './air-quality-provider.mjs';

export async function fetchCachedProvider(options, { variables, signal, observeReceipt, receiptDeadline } = {}) {
  const requested = providerVariables(variables); // Refuse malformed requests before any work.
  const result = await fetchCachedForecast(options, { signal, observeReceipt, receiptDeadline });
  const projected = toProviderForecast(result.forecast, { variables: requested,
    publicationExpires: result.delivery.publication_expires_at });
  return { ...projected, delivery: result.delivery };
}

export async function fetchCachedAirQualityProvider(options, { variables = ['pm2_5', 'pm10'], signal, observeReceipt, receiptDeadline } = {}) {
  const requested = providerVariables(variables);
  const result = await fetchCachedAirQuality(options, { signal, observeReceipt, receiptDeadline });
  const projected = toAirQualityProviderForecast(result.forecast, { variables: requested,
    publicationExpires: result.delivery.publication_expires_at });
  return { ...projected, delivery: result.delivery };
}
