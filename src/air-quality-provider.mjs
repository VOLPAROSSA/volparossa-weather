// SPDX-License-Identifier: GPL-3.0-only
// Pure browser-compatible projection. No acquisition, publication or authority.
import { airQualityFreshness, AQ_UNITS } from './air-quality.mjs';
import { requireThat } from './forecast.mjs';
import { providerVariables } from './provider.mjs';

export const AIR_QUALITY_PROVIDER_SCHEMA = 'volparossa.air-quality.provider.v1';

export function toAirQualityProviderForecast(forecast, { variables = ['pm2_5', 'pm10'],
  now = new Date().toISOString(), publicationExpires = null } = {}) {
  const requested = providerVariables(variables);
  const age = airQualityFreshness(forecast, now, publicationExpires);
  requireThat(!age.stale, 'STALE_FORECAST');
  const original = structuredClone(forecast), available = Object.keys(AQ_UNITS);
  const series = requested.map(variable => {
    if (!Object.hasOwn(AQ_UNITS, variable)) return { variable, availability: 'unavailable',
      reason: 'unsupported_variable', unit: null, values: null, value_status: null };
    const values = original.samples.map(sample => sample[variable]);
    return { variable, availability: 'supported', reason: null, unit: AQ_UNITS[variable],
      statistic: 'instant', values, value_status: values.map(value => value === null ? 'missing' : 'available') };
  });
  return {
    schema: AIR_QUALITY_PROVIDER_SCHEMA, kind: 'forecast',
    capabilities: { implemented_variables: [...available], available_variables: [...available],
      time_axis: 'native-model-valid-times', interpolation: false,
      current_observations: false, trained_corrections: false },
    timeline: { time_zone: 'UTC', valid_at: original.samples.map(sample => sample.valid_at),
      lead_hours: original.samples.map(sample => sample.lead_hours) },
    series, freshness: { ...age, checked_at: now, publication_expires_at: publicationExpires },
    forecast: original, verification_scope: 'forecast-schema-and-freshness-only', delivery: null,
  };
}
