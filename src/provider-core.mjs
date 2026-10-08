// SPDX-License-Identifier: GPL-3.0-only
// Node/Linux boundary. Reuses the existing real core-cache adapter unchanged.
import { fetchCachedForecast } from './core-cache.mjs';
import { providerVariables, toProviderForecast } from './provider.mjs';

export async function fetchCachedProvider(options, { variables, signal } = {}) {
  const requested = providerVariables(variables); // Refuse malformed requests before any work.
  const result = await fetchCachedForecast(options, { signal });
  const projected = toProviderForecast(result.forecast, { variables: requested,
    publicationExpires: result.delivery.publication_expires_at });
  return { ...projected, delivery: result.delivery };
}
