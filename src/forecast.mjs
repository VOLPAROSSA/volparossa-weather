// SPDX-License-Identifier: GPL-3.0-only
// Inert forecast JSON. No network, location discovery or persistence.
export const SCHEMA = 'volparossa.forecast.v1';
export const MAX_SAMPLES = 16;
export const MAX_BYTES = 131072;
export const MAX_AGE_SECONDS = 1800;
export const MAX_RUN_AGE_SECONDS = 72 * 3600;
export const UNITS = Object.freeze({ temperature_2m: 'degC' });
export const WIND_UNITS = Object.freeze({ wind_10m: 'm/s', wind_direction_10m: 'degree' });
export class WeatherError extends Error {
  constructor(code) { super(code); this.name = 'WeatherError'; this.code = code; }
}
export function requireThat(condition, code) { if (!condition) throw new WeatherError(code); }
export function number(value, min, max, code) {
  requireThat(typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max, code);
  return value;
}
function object(value, keys, code) {
  requireThat(value !== null && typeof value === 'object' && !Array.isArray(value), code);
  requireThat(Object.keys(value).sort().join('|') === [...keys].sort().join('|'), code);
}
export function utc(value) {
  requireThat(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value), 'TIME_INVALID');
  const ms = Date.parse(value);
  requireThat(Number.isFinite(ms) && new Date(ms).toISOString() === value, 'TIME_INVALID');
  return ms;
}
function hash(value) { requireThat(typeof value === 'string' && /^[a-f0-9]{64}$/.test(value), 'HASH_INVALID'); }
export function request({ latitude, longitude, run, model = 'ifs', steps = [24], communityArea = false, includeWind = false } = {}) {
  number(latitude, -90, 90, 'LATITUDE_INVALID'); number(longitude, -180, 180, 'LONGITUDE_INVALID');
  requireThat(utc(run) % 3600000 === 0, 'RUN_INVALID');
  requireThat(typeof model === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(model), 'MODEL_INVALID');
  requireThat(Array.isArray(steps) && steps.length >= 1 && steps.length <= MAX_SAMPLES, 'STEPS_INVALID');
  let previous = -1;
  for (const step of steps) {
    requireThat(Number.isInteger(step) && step >= 0 && step <= 360 && step > previous, 'STEPS_INVALID');
    previous = step;
  }
  requireThat(typeof communityArea === 'boolean', 'SHARING_INVALID');
  requireThat(typeof includeWind === 'boolean', 'WIND_REQUEST_INVALID');
  return Object.freeze({ latitude, longitude, run, model, steps: Object.freeze([...steps]), communityArea, includeWind });
}

export function windVector(eastward, northward) {
  for (const component of [eastward, northward]) if (component !== null) number(component, -Infinity, Infinity, 'WIND_VALUE_INVALID');
  if (eastward === null || northward === null) return { eastward, northward, speed: null, direction_from: null, status: 'missing' };
  const speed = Math.hypot(eastward, northward);
  number(speed, 0, Infinity, 'WIND_VALUE_INVALID');
  if (speed === 0) return { eastward, northward, speed: 0, direction_from: null, status: 'calm' };
  // ECMWF meteorological convention: clockwise FROM true north. JS atan2(y,x).
  const direction = ((180 + Math.atan2(eastward, northward) * 180 / Math.PI) % 360 + 360) % 360;
  return { eastward, northward, speed, direction_from: direction, status: 'available' };
}

function validateEvidence(evidence, parameter, unit) {
  object(evidence, ['index_sha256', 'field_sha256', 'parameter', 'unit', 'statistic',
    'resolution', 'range_start', 'range_length', 'decoder_sha256'], 'EVIDENCE_INVALID');
  for (const key of ['index_sha256', 'field_sha256', 'decoder_sha256']) hash(evidence[key]);
  requireThat(evidence.parameter === parameter && evidence.unit === unit
    && evidence.statistic === 'instant' && evidence.resolution === '0p25', 'EVIDENCE_INVALID');
  requireThat(Number.isSafeInteger(evidence.range_start) && evidence.range_start >= 0
    && Number.isSafeInteger(evidence.range_length) && evidence.range_length >= 20
    && evidence.range_length <= 8 * 1024 * 1024, 'RANGE_INVALID');
}
export function validateForecast(value) {
  object(value, ['schema', 'kind', 'area', 'source', 'units', 'samples', 'freshness'], 'FORECAST_INVALID');
  requireThat(value.schema === SCHEMA && value.kind === 'forecast', 'SCHEMA_INVALID');
  object(value.area, ['latitude', 'longitude', 'sharing'], 'AREA_INVALID');
  number(value.area.latitude, -90, 90, 'LATITUDE_INVALID'); number(value.area.longitude, -180, 180, 'LONGITUDE_INVALID');
  requireThat(['private', 'public-community'].includes(value.area.sharing), 'SHARING_INVALID');
  object(value.source, ['provider', 'product', 'model', 'model_run_at', 'issued_at', 'acquired_at',
    'acquisition', 'attribution', 'license', 'license_url', 'changes'], 'SOURCE_INVALID');
  for (const key of ['provider', 'product', 'model', 'attribution', 'changes']) {
    requireThat(typeof value.source[key] === 'string' && value.source[key].length > 0
      && value.source[key].length <= 200 && !/[\x00-\x1f\x7f]/.test(value.source[key]), 'SOURCE_INVALID');
  }
  requireThat(value.source.acquisition === 'origin-https', 'ACQUISITION_INVALID');
  requireThat(value.source.license === 'CC-BY-4.0'
    && value.source.license_url === 'https://creativecommons.org/licenses/by/4.0/', 'LICENSE_INVALID');
  const acquired = utc(value.source.acquired_at), run = utc(value.source.model_run_at);
  requireThat(run <= acquired && acquired - run < MAX_RUN_AGE_SECONDS * 1000, 'RUN_AGE_INVALID');
  if (value.source.issued_at !== null) requireThat(utc(value.source.issued_at) <= acquired, 'ISSUE_TIME_INVALID');
  requireThat(value.units !== null && typeof value.units === 'object' && !Array.isArray(value.units), 'UNITS_INVALID');
  const includesWind = Object.hasOwn(value.units, 'wind_10m');
  const units = includesWind ? { ...UNITS, ...WIND_UNITS } : UNITS;
  object(value.units, Object.keys(units), 'UNITS_INVALID');
  for (const [key, unit] of Object.entries(units)) requireThat(value.units[key] === unit, 'UNITS_INVALID');
  object(value.freshness, ['basis', 'expires_at'], 'FRESHNESS_INVALID');
  requireThat(value.freshness.basis === 'acquisition-and-model-run-age', 'FRESHNESS_INVALID');
  const expires = utc(value.freshness.expires_at);
  requireThat(expires > acquired && expires - acquired <= MAX_AGE_SECONDS * 1000
    && expires <= run + MAX_RUN_AGE_SECONDS * 1000, 'EXPIRY_INVALID');
  requireThat(Array.isArray(value.samples) && value.samples.length >= 1 && value.samples.length <= MAX_SAMPLES, 'SAMPLES_INVALID');
  let previous = -1;
  for (const sample of value.samples) {
    object(sample, ['valid_at', 'lead_hours', 'temperature_2m', 'grid', 'evidence',
      ...(includesWind ? ['wind_10m'] : [])], 'SAMPLE_INVALID');
    requireThat(Number.isInteger(sample.lead_hours) && sample.lead_hours >= 0
      && sample.lead_hours <= 360 && sample.lead_hours > previous, 'STEPS_INVALID');
    requireThat(utc(sample.valid_at) === run + sample.lead_hours * 3600000, 'VALID_TIME_INVALID'); previous = sample.lead_hours;
    if (sample.temperature_2m !== null) number(sample.temperature_2m, -273.15, Infinity, 'VALUE_INVALID');
    object(sample.grid, ['latitude', 'longitude', 'distance_km', 'method'], 'GRID_INVALID');
    number(sample.grid.latitude, -90, 90, 'GRID_INVALID'); number(sample.grid.longitude, -180, 180, 'GRID_INVALID');
    number(sample.grid.distance_km, 0, 50, 'GRID_INVALID');
    requireThat(sample.grid.method === 'nearest-grid-no-interpolation', 'GRID_INVALID');
    validateEvidence(sample.evidence, '2t', 'K');
    if (includesWind) {
      const wind = sample.wind_10m;
      object(wind, ['eastward', 'northward', 'speed', 'direction_from', 'status', 'evidence'], 'WIND_INVALID');
      const derived = windVector(wind.eastward, wind.northward);
      requireThat(wind.status === derived.status, 'WIND_DERIVATION_MISMATCH');
      for (const key of ['speed', 'direction_from']) {
        if (derived[key] === null) requireThat(wind[key] === null, 'WIND_DERIVATION_MISMATCH');
        else {
          number(wind[key], 0, key === 'speed' ? Infinity : 360, 'WIND_VALUE_INVALID');
          requireThat((key !== 'direction_from' || wind[key] < 360)
            && Math.abs(wind[key] - derived[key]) <= 1e-12 * Math.max(1, Math.abs(derived[key])), 'WIND_DERIVATION_MISMATCH');
        }
      }
      object(wind.evidence, ['eastward', 'northward'], 'WIND_EVIDENCE_INVALID');
      const allEvidence = [sample.evidence, wind.evidence.eastward, wind.evidence.northward];
      validateEvidence(wind.evidence.eastward, '10u', 'm s**-1');
      validateEvidence(wind.evidence.northward, '10v', 'm s**-1');
      requireThat(allEvidence.every(item => item.index_sha256 === sample.evidence.index_sha256
        && item.decoder_sha256 === sample.evidence.decoder_sha256), 'WIND_PROVENANCE_MISMATCH');
      const ranges = [...allEvidence].sort((a, b) => a.range_start - b.range_start);
      requireThat(ranges.slice(1).every((item, index) =>
        item.range_start >= ranges[index].range_start + ranges[index].range_length), 'WIND_PROVENANCE_MISMATCH');
    }
  }
  return value;
}
export function freshness(value, now = new Date().toISOString(), publicationExpires = null) {
  validateForecast(value);
  const current = utc(now), acquired = utc(value.source.acquired_at);
  requireThat(current >= acquired, 'CLOCK_BEFORE_ACQUISITION');
  const expires = Math.min(utc(value.freshness.expires_at), publicationExpires === null ? Infinity : utc(publicationExpires));
  return { stale: current >= expires, age_seconds: Math.floor((current - acquired) / 1000),
    model_age_seconds: Math.floor((current - utc(value.source.model_run_at)) / 1000), expires_at: new Date(expires).toISOString() };
}
export function parseForecast(bytes) {
  requireThat(bytes instanceof Uint8Array && bytes.byteLength <= MAX_BYTES, 'BODY_TOO_LARGE');
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new WeatherError('JSON_INVALID'); }
  return validateForecast(value);
}
