// SPDX-License-Identifier: GPL-3.0-only
// Source-native particulate forecasts, not observations, an AQI or health advice.
import { WeatherError, number, requireThat, utc } from './forecast.mjs';

export const AQ_SCHEMA = 'volparossa.air-quality.forecast.v1';
export const AQ_MAX_BYTES = 131072;
export const AQ_MAX_SAMPLES = 16;
export const AQ_MAX_AGE_SECONDS = 1800;
export const AQ_MAX_RUN_AGE_SECONDS = 72 * 3600;
export const AQ_UNITS = Object.freeze({ pm2_5: 'ug/m3', pm10: 'ug/m3' });
export const AQ_SOURCE = Object.freeze({
  provider: 'noaa', product: 'gefs-aerosols-surface-total-pm', model: 'gefs-aerosols',
  acquisition: 'origin-https', attribution: 'NOAA/NWS GEFS-Aerosols',
  license: 'LicenseRef-NOAA-NODD', license_url: 'https://registry.opendata.aws/noaa-gefs/',
  changes: 'Nearest grid point; native instantaneous particulate forecasts, not observations or AQI. Modified presentation, not an official NOAA product.',
});
export const AQ_FIELDS = Object.freeze({
  pm2_5: Object.freeze({ parameter: 'PMTF', param_id: 260375, particle_size_upper_m: 2.5e-6 }),
  pm10: Object.freeze({ parameter: 'PMTC', param_id: 260374, particle_size_upper_m: 1e-5 }),
});
const PROVENANCE = ['index_sha256', 'field_sha256', 'range_start', 'range_length', 'decoder_sha256'];
const MEASURE = Object.freeze({ unit: '(10**-6 g) m**-3', statistic: 'instant',
  resolution: '0p25', aerosol_type: 62000 });
function object(value, keys, code) {
  requireThat(value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('|') === [...keys].sort().join('|'), code);
}
function runTime(value) {
  const time = utc(value);
  requireThat(time % (6 * 3600000) === 0, 'AQ_RUN_INVALID');
  return time;
}
function lead(value) {
  requireThat(Number.isInteger(value) && value >= 0 && value <= 120 && value % 3 === 0, 'AQ_STEPS_INVALID');
}
export function airQualityRequest({ latitude, longitude, run, steps = [3], communityArea = false,
  model = 'gefs-aerosols' } = {}) {
  number(latitude, -90, 90, 'LATITUDE_INVALID'); number(longitude, -180, 180, 'LONGITUDE_INVALID');
  runTime(run);
  requireThat(model === AQ_SOURCE.model, 'AQ_MODEL_UNSUPPORTED');
  requireThat(typeof communityArea === 'boolean', 'SHARING_INVALID');
  requireThat(Array.isArray(steps) && steps.length > 0 && steps.length <= AQ_MAX_SAMPLES, 'AQ_STEPS_INVALID');
  let previous = -1;
  for (const step of steps) { lead(step); requireThat(step > previous, 'AQ_STEPS_INVALID'); previous = step; }
  return Object.freeze({ latitude, longitude, run, model, steps: Object.freeze([...steps]), communityArea });
}
function evidence(value, field) {
  const fixed = { ...AQ_FIELDS[field], ...MEASURE };
  object(value, [...PROVENANCE, ...Object.keys(fixed)], 'AQ_EVIDENCE_INVALID');
  for (const key of ['index_sha256', 'field_sha256', 'decoder_sha256']) {
    requireThat(typeof value[key] === 'string' && /^[a-f0-9]{64}$/.test(value[key]), 'HASH_INVALID');
  }
  for (const [key, expected] of Object.entries(fixed)) requireThat(value[key] === expected, 'AQ_EVIDENCE_INVALID');
  requireThat(Number.isSafeInteger(value.range_start) && value.range_start >= 0
    && Number.isSafeInteger(value.range_length) && value.range_length >= 20 && value.range_length <= 2 * 1024 * 1024
    && Number.isSafeInteger(value.range_start + value.range_length), 'RANGE_INVALID');
}
export function validateAirQualityForecast(value) {
  object(value, ['schema', 'kind', 'area', 'source', 'units', 'samples', 'freshness'], 'AQ_FORECAST_INVALID');
  requireThat(value.schema === AQ_SCHEMA && value.kind === 'forecast', 'SCHEMA_INVALID');
  object(value.area, ['latitude', 'longitude', 'sharing'], 'AREA_INVALID');
  number(value.area.latitude, -90, 90, 'LATITUDE_INVALID'); number(value.area.longitude, -180, 180, 'LONGITUDE_INVALID');
  requireThat(['private', 'public-community'].includes(value.area.sharing), 'SHARING_INVALID');
  object(value.source, [...Object.keys(AQ_SOURCE), 'model_run_at', 'issued_at', 'acquired_at'], 'SOURCE_INVALID');
  for (const [key, expected] of Object.entries(AQ_SOURCE)) requireThat(value.source[key] === expected, 'AQ_SOURCE_INVALID');
  // Acquisition time is not a claimed issue time, nor a current observation.
  requireThat(value.source.issued_at === null, 'ISSUE_TIME_INVALID');
  const run = runTime(value.source.model_run_at), acquired = utc(value.source.acquired_at);
  requireThat(run <= acquired && acquired - run < AQ_MAX_RUN_AGE_SECONDS * 1000, 'RUN_AGE_INVALID');
  object(value.units, Object.keys(AQ_UNITS), 'UNITS_INVALID');
  for (const [key, unit] of Object.entries(AQ_UNITS)) requireThat(value.units[key] === unit, 'UNITS_INVALID');
  object(value.freshness, ['basis', 'expires_at'], 'FRESHNESS_INVALID');
  requireThat(value.freshness.basis === 'acquisition-and-model-run-age', 'FRESHNESS_INVALID');
  const expires = utc(value.freshness.expires_at);
  requireThat(expires > acquired && expires - acquired <= AQ_MAX_AGE_SECONDS * 1000
    && expires <= run + AQ_MAX_RUN_AGE_SECONDS * 1000, 'EXPIRY_INVALID');
  requireThat(Array.isArray(value.samples) && value.samples.length > 0 && value.samples.length <= AQ_MAX_SAMPLES, 'SAMPLES_INVALID');
  let previous = -1;
  for (const sample of value.samples) {
    object(sample, ['valid_at', 'lead_hours', 'pm2_5', 'pm10', 'grid', 'evidence'], 'SAMPLE_INVALID');
    lead(sample.lead_hours);
    requireThat(sample.lead_hours > previous, 'AQ_STEPS_INVALID'); previous = sample.lead_hours;
    requireThat(utc(sample.valid_at) === run + sample.lead_hours * 3600000, 'VALID_TIME_INVALID');
    object(sample.grid, ['latitude', 'longitude', 'distance_km', 'method'], 'GRID_INVALID');
    number(sample.grid.latitude, -90, 90, 'GRID_INVALID'); number(sample.grid.longitude, -180, 180, 'GRID_INVALID');
    number(sample.grid.distance_km, 0, 50, 'GRID_INVALID');
    requireThat(sample.grid.method === 'nearest-grid-no-interpolation', 'GRID_INVALID');
    object(sample.evidence, Object.keys(AQ_FIELDS), 'AQ_EVIDENCE_INVALID');
    for (const field of Object.keys(AQ_FIELDS)) {
      if (sample[field] !== null) number(sample[field], 0, Infinity, 'AQ_VALUE_INVALID');
      evidence(sample.evidence[field], field);
    }
    const ranges = Object.values(sample.evidence).sort((a, b) => a.range_start - b.range_start);
    requireThat(ranges[0].index_sha256 === ranges[1].index_sha256
      && ranges[0].decoder_sha256 === ranges[1].decoder_sha256
      && ranges[1].range_start >= ranges[0].range_start + ranges[0].range_length, 'AQ_PROVENANCE_MISMATCH');
  }
  return value;
}
export function airQualityForecastFromSamples({ query, samples, acquiredAt, maxAgeSeconds = AQ_MAX_AGE_SECONDS }) {
  const expected = airQualityRequest(query);
  number(maxAgeSeconds, 1, AQ_MAX_AGE_SECONDS, 'EXPIRY_INVALID');
  const acquired = utc(acquiredAt), run = runTime(expected.run);
  requireThat(Array.isArray(samples) && JSON.stringify(samples.map(sample => sample?.lead_hours)) === JSON.stringify(expected.steps),
    'AQ_QUERY_MISMATCH');
  const value = {
    schema: AQ_SCHEMA, kind: 'forecast',
    area: { latitude: expected.latitude, longitude: expected.longitude, sharing: expected.communityArea ? 'public-community' : 'private' },
    source: { ...AQ_SOURCE, model_run_at: expected.run, issued_at: null, acquired_at: acquiredAt },
    units: { ...AQ_UNITS },
    samples: samples.map(sample => ({ ...structuredClone(sample), evidence: Object.fromEntries(Object.keys(AQ_FIELDS).map(field => {
      // Only the decoder adapter may supply these hashes/ranges. Construction
      // labels the supported product; hashes do not authenticate NOAA by themselves.
      const original = sample.evidence?.[field]; object(original, PROVENANCE, 'AQ_EVIDENCE_INVALID');
      return [field, { ...original, ...AQ_FIELDS[field], ...MEASURE }];
    })) })),
    freshness: { basis: 'acquisition-and-model-run-age',
      expires_at: new Date(Math.min(acquired + maxAgeSeconds * 1000, run + AQ_MAX_RUN_AGE_SECONDS * 1000)).toISOString() },
  };
  return validateAirQualityForecast(value);
}
export function parseAirQualityForecast(bytes) {
  requireThat(bytes instanceof Uint8Array && bytes.byteLength <= AQ_MAX_BYTES, 'BODY_TOO_LARGE');
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new WeatherError('JSON_INVALID'); }
  return validateAirQualityForecast(value);
}
export function airQualityFreshness(value, now = new Date().toISOString(), publicationExpires = null) {
  validateAirQualityForecast(value);
  const current = utc(now), acquired = utc(value.source.acquired_at);
  requireThat(current >= acquired, 'CLOCK_BEFORE_ACQUISITION');
  const expires = Math.min(utc(value.freshness.expires_at), publicationExpires === null ? Infinity : utc(publicationExpires));
  return { stale: current >= expires, age_seconds: Math.floor((current - acquired) / 1000),
    model_age_seconds: Math.floor((current - utc(value.source.model_run_at)) / 1000), expires_at: new Date(expires).toISOString() };
}
