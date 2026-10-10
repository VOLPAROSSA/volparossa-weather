// SPDX-License-Identifier: GPL-3.0-only
// Framework-independent projection only. No fetch, publication or identity authority.
import { freshness, requireThat } from './forecast.mjs';

export const PROVIDER_SCHEMA = 'volparossa.weather.provider.v1';
const VARIABLES = Object.freeze({ temperature_2m: 'degC', wind_speed_10m: 'm/s', wind_direction_10m: 'degree' });

export function providerVariables(value = ['temperature_2m']) {
  requireThat(Array.isArray(value) && value.length >= 1 && value.length <= 16
    && [...value].every(name => typeof name === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(name))
    && new Set(value).size === value.length, 'PROVIDER_VARIABLES_INVALID');
  return Object.freeze([...value]);
}

export function toProviderForecast(forecast, { variables, now = new Date().toISOString(), publicationExpires = null } = {}) {
  const requested = providerVariables(variables);
  // This reuses all existing value/unit/run/evidence checks. Projection never
  // rejuvenates the original acquisition or the signed publication lifetime.
  const age = freshness(forecast, now, publicationExpires);
  requireThat(!age.stale, 'STALE_FORECAST');
  const original = structuredClone(forecast);
  const available = Object.keys(VARIABLES).filter(name => name === 'temperature_2m'
    || Object.hasOwn(original.units, 'wind_10m'));
  const series = requested.map(variable => {
    if (!available.includes(variable)) {
      return { variable, availability: 'unavailable',
        reason: Object.hasOwn(VARIABLES, variable) ? 'field_not_in_forecast' : 'unsupported_variable',
        unit: null, values: null, value_status: null };
    }
    const temperature = variable === 'temperature_2m';
    const values = original.samples.map(sample => temperature ? sample.temperature_2m
      : variable === 'wind_speed_10m' ? sample.wind_10m.speed : sample.wind_10m.direction_from);
    const valueStatus = original.samples.map((sample, index) => temperature
      ? values[index] === null ? 'missing' : 'available' : sample.wind_10m.status);
    return { variable, availability: 'supported', reason: null, unit: VARIABLES[variable],
      values, value_status: valueStatus };
  });
  return {
    schema: PROVIDER_SCHEMA, kind: 'forecast',
    capabilities: { implemented_variables: Object.keys(VARIABLES), available_variables: available,
      time_axis: 'native-model-valid-times', interpolation: false,
      current_observations: false, trained_corrections: false },
    timeline: { time_zone: 'UTC', valid_at: original.samples.map(sample => sample.valid_at),
      lead_hours: original.samples.map(sample => sample.lead_hours) },
    series,
    freshness: { ...age, checked_at: now, publication_expires_at: publicationExpires },
    // Preserve full source/run/license/grid and field evidence, not a second
    // guessed weather model. Schema checks alone do not authenticate its origin.
    forecast: original,
    verification_scope: 'forecast-schema-and-freshness-only',
    delivery: null,
  };
}
