// SPDX-License-Identifier: GPL-3.0-only
import { MAX_SAMPLES, UNITS, number, requireThat, utc, validateForecast } from './forecast.mjs';
import { ecmwfRequest } from './ecmwf.mjs';

function fields(value, names) {
  requireThat(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === names.length && names.every(key => Object.hasOwn(value, key)),
  'OBSERVATION_FORMAT_INVALID');
}

export function observationIndex(data, archive = false) {
  fields(data, ['schema', 'source', 'license', 'station', 'sharing', 'purpose', 'variable', 'unit', 'statistic', 'samples']);
  requireThat(data.schema === 'volparossa.weather.observations.v1' && data.sharing === 'public'
    && data.purpose === (archive ? 'retrospective-evaluation' : 'held-out-evaluation') && data.variable === 'temperature_2m'
    && data.unit === UNITS.temperature_2m && (data.statistic === 'instant' || archive && data.statistic === 'nominal-synoptic-hour'), 'OBSERVATION_CONTRACT_INVALID');
  fields(data.station, ['id', 'latitude', 'longitude']);
  for (const label of [data.source, data.license, data.station.id]) {
    requireThat(typeof label === 'string' && label.trim().length > 0 && label.length <= 200
      && !/[\x00-\x1f\x7f]/.test(label), 'OBSERVATION_PROVENANCE_INVALID');
  }
  number(data.station.latitude, -90, 90, 'LATITUDE_INVALID');
  number(data.station.longitude, -180, 180, 'LONGITUDE_INVALID');
  requireThat(Array.isArray(data.samples) && data.samples.length <= 2 * MAX_SAMPLES, 'OBSERVATION_COUNT_INVALID');

  const byTime = new Map();
  for (const sample of data.samples) {
    fields(sample, ['observed_at', 'temperature_2m', 'quality']);
    utc(sample.observed_at);
    requireThat(!byTime.has(sample.observed_at), 'DUPLICATE_OBSERVATION');
    requireThat((['accepted', 'rejected'].includes(sample.quality) || archive && sample.quality === 'provisional'), 'OBSERVATION_QUALITY_INVALID');
    if (sample.temperature_2m !== null) number(sample.temperature_2m, -273.15, Infinity, 'VALUE_INVALID');
    byTime.set(sample.observed_at, sample);
  }
  return byTime;
}

function indexForecast(forecast, model, station) {
  validateForecast(forecast);
  const { source, area, samples } = forecast;
  requireThat(source.model === model && source.provider === 'ecmwf'
    && source.product === 'open-data-single-level-forecast', 'VERIFICATION_MODEL_INVALID');
  requireThat(area.sharing === 'public-community' && area.latitude === station.latitude
    && area.longitude === station.longitude, 'VERIFICATION_STATION_MISMATCH');
  ecmwfRequest({ latitude: area.latitude, longitude: area.longitude, model,
    run: source.model_run_at, steps: samples.map(sample => sample.lead_hours) });
  return new Map(samples.map(sample => [sample.valid_at, sample]));
}

function score(errors) {
  if (!errors.length) return { mean_error_degC: null, mean_absolute_error_degC: null };
  const mean = values => number(values.reduce((total, value) => total + value, 0) / values.length,
    -Infinity, Infinity, 'VERIFICATION_ERROR_OUT_OF_RANGE');
  return { mean_error_degC: mean(errors), mean_absolute_error_degC: mean(errors.map(Math.abs)) };
}

// Compare the fixed 50:50 estimate on precisely the pairs admitted by the verifier.
// Each station/time counts once, even when several stations share one forecast cell.
export function compareEqualWeightTemperature(reports) {
  const ifs = [], aifs = [], blend = [];
  let excluded = 0;
  for (const report of reports) {
    for (const sample of report.cases) {
      if (sample.excluded) {
        excluded++;
        continue;
      }
      const left = sample.ifs_error_degC, right = sample.aifs_single_error_degC;
      ifs.push(left);
      aifs.push(right);
      // The average signed error equals the average forecast minus the observation.
      blend.push(left / 2 + right / 2);
    }
  }
  return { method: 'equal-weight-ifs-aifs-single', unit: 'degC', stations: reports.length,
    paired_station_times: blend.length, excluded_station_times: excluded,
    ifs: score(ifs), 'aifs-single': score(aifs), blend: score(blend) };
}

function stationDistanceKm(station, grid) {
  const radians = Math.PI / 180;
  const halfLatitude = (grid.latitude - station.latitude) * radians / 2;
  const halfLongitude = (grid.longitude - station.longitude) * radians / 2;
  const haversine = Math.sin(halfLatitude) ** 2 + Math.cos(station.latitude * radians)
    * Math.cos(grid.latitude * radians) * Math.sin(halfLongitude) ** 2;
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(haversine)));
}

export function verifyTemperature(ifs, aifs, observations) {
  const observed = observationIndex(observations);
  const forecasts = [ifs, aifs];
  const samples = [indexForecast(ifs, 'ifs', observations.station), indexForecast(aifs, 'aifs-single', observations.station)];
  requireThat(ifs.source.model_run_at === aifs.source.model_run_at, 'VERIFICATION_RUN_MISMATCH');
  return { schema: 'volparossa.weather.temperature-verification.v1', model_run_at: ifs.source.model_run_at,
    forecast_sources: forecasts.map(({ source }) => ({ model: source.model, acquired_at: source.acquired_at,
      attribution: source.attribution, license: source.license, license_url: source.license_url })),
    ...compareTemperatureCases(forecasts.map(f => f.source), samples, observations, observed, false) };
}

export function compareTemperatureCases(sources, samples, observations, observed, archive) {
  const times = new Set([...observed.keys(), ...samples[0].keys(), ...samples[1].keys()]);
  const errors = [[], []];
  const cases = [];
  for (const valid_at of [...times].sort()) {
    const observation = observed.get(valid_at);
    const pair = samples.map(byTime => byTime.get(valid_at));
    const reasons = [];
    if (!observation || observation.temperature_2m === null) reasons.push('missing_observation');
    if (observation?.quality === 'rejected') reasons.push('rejected_observation');
    for (const [i, sample] of pair.entries()) {
      const { model, acquired_at, last_modified_at } = sources[i];
      if (!sample || sample.temperature_2m === null) reasons.push(model + '_missing_forecast');
      if (sample && archive && last_modified_at >= valid_at) reasons.push(model + '_archive_not_available_in_advance');
      if (sample && !archive && acquired_at >= valid_at) reasons.push(model + '_not_acquired_in_advance');
    }
    let stationDistance;
    if (pair.every(Boolean)) {
      const [first, second] = pair.map(sample => sample.grid);
      if (first.latitude !== second.latitude || first.longitude !== second.longitude) reasons.push('grid_mismatch');
      else {
        stationDistance = stationDistanceKm(observations.station, first);
        if (stationDistance > 50) reasons.push('grid_outside_station_area');
      }
    }
    if (reasons.length) {
      cases.push({ valid_at, excluded: reasons });
      continue;
    }
    const differences = pair.map((sample, i) => {
      const difference = number(sample.temperature_2m - observation.temperature_2m,
        -Infinity, Infinity, 'VERIFICATION_ERROR_OUT_OF_RANGE');
      errors[i].push(difference);
      return difference;
    });
    const { latitude, longitude } = pair[0].grid;
    cases.push({ valid_at, lead_hours: pair[0].lead_hours, grid: { latitude, longitude, distance_km: stationDistance },
      ...(archive ? { observation_quality: observation.quality, observation_statistic: observations.statistic,
        ifs_degC: pair[0].temperature_2m, aifs_single_degC: pair[1].temperature_2m } : {}),
      observed_degC: observation.temperature_2m, ifs_error_degC: differences[0], aifs_single_error_degC: differences[1] });
  }
  return { observations: { source: observations.source, license: observations.license, station: { ...observations.station },
      declared_sharing: observations.sharing, declared_purpose: observations.purpose, source_authenticated: false },
    coverage: { candidate_times: times.size, paired: errors[0].length, excluded: times.size - errors[0].length },
    models: { ifs: score(errors[0]), 'aifs-single': score(errors[1]) }, cases };
}
