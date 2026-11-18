// SPDX-License-Identifier: GPL-3.0-only
// Offline comparison of two archived ECMWF 2t GRIB records at public stations.
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { ecmwfRequest, fieldUrl, MAX_FIELD_BYTES, MAX_INDEX_BYTES, ORIGIN, selectIndex, sha256 } from './ecmwf.mjs';
import { WeatherError, number, requireThat, utc } from './forecast.mjs';
import { observationIndex, compareTemperatureCases } from './forecast-verification.mjs';
import { readBytes } from './verification-input.mjs';

const ARCHIVE = 'https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com';
const MODELS = ['ifs', 'aifs-single'];
const HASH = /^[a-f0-9]{64}$/;

function gdal(program, args, bytes) {
  const result = spawnSync('/usr/bin/prlimit', ['--as=536870912', '--cpu=15', '--', '/usr/bin/' + program, ...args],
    { input: bytes, encoding: 'utf8',
    timeout: 15000, killSignal: 'SIGKILL', maxBuffer: 131072,
    env: { PATH: '/usr/bin:/bin', LANG: 'C', GDAL_DRIVER_PATH: 'disable', GDAL_PAM_ENABLED: 'NO',
      GDAL_CACHEMAX: '32', OPENBLAS_NUM_THREADS: '1',
      GDAL_DISABLE_READDIR_ON_OPEN: 'EMPTY_DIR', GRIB_NORMALIZE_UNITS: 'YES', GRIB_ADJUST_LONGITUDE_RANGE: 'YES' } });
  requireThat(result.error?.code !== 'ENOENT' && result.status !== 127, 'ARCHIVE_GDAL_REQUIRED');
  requireThat(!result.error && result.status === 0 && !result.signal, 'ARCHIVE_DECODER_FAILED');
  return result.stdout.trim();
}

export function archiveGrid(info, run, lead) {
  const band = info?.bands?.[0];
  const md = band?.metadata?.[''];
  requireThat(info?.driverShortName === 'GRIB' && Array.isArray(info.bands) && info.bands.length === 1 && band?.band === 1
    && JSON.stringify(info.size) === '[1440,721]' && JSON.stringify(info.geoTransform) === '[-180.125,0.25,0,90.125,0,-0.25]'
    && md?.GRIB_ELEMENT === 'TMP' && md.GRIB_SHORT_NAME === '2-HTGL' && md.GRIB_UNIT === '[C]'
    && md.GRIB_PDS_PDTN === '0' && /^CENTER=98\(ECMWF\)(?: |$)/.test(md.GRIB_IDS)
    && md.GRIB_REF_TIME === String(utc(run) / 1000) && md.GRIB_FORECAST_SECONDS === String(lead * 3600)
    && md.GRIB_VALID_TIME === String(utc(run) / 1000 + lead * 3600), 'ARCHIVE_GRIB_IDENTITY_MISMATCH');
  return band;
}

async function readField(directory, query, manifest, retrievedEnd) {
  const { model, run } = query;
  const pin = manifest.models?.[model];
  requireThat(typeof pin?.index_sha256 === 'string' && HASH.test(pin.index_sha256)
    && typeof pin.field_sha256 === 'string' && HASH.test(pin.field_sha256), 'ARCHIVE_PIN_INVALID');
  const lead = manifest.lead_hours;
  const modified = utc(pin.last_modified_at);
  requireThat(modified >= utc(run) && modified <= retrievedEnd, 'ARCHIVE_CHRONOLOGY_INVALID');
  const [index, bytes] = await Promise.all([readBytes(join(directory, model + '.index'), MAX_INDEX_BYTES),
    readBytes(join(directory, model + '.grib2'), MAX_FIELD_BYTES)]);
  requireThat(sha256(index) === pin.index_sha256 && sha256(bytes) === pin.field_sha256, 'ARCHIVE_HASH_MISMATCH');
  const { offset, length } = selectIndex(index, query, lead, '2t');
  requireThat(bytes.length === length && bytes.subarray(0,4).toString('ascii') === 'GRIB' && bytes[7] === 2
    && bytes.readBigUInt64BE(8) === BigInt(length) && bytes.subarray(-4).toString('ascii') === '7777',
    'ARCHIVE_FIELD_INVALID');
  const url = extension => fieldUrl(query, lead, extension).replace(ORIGIN, ARCHIVE);
  return { bytes, source: { model, last_modified_at: pin.last_modified_at,
    index_url: url('index'), index_sha256: pin.index_sha256, grib_url: url('grib2'), field_sha256: pin.field_sha256,
    range_start: offset, range_length: length } };
}

function sampleStation(field, station, run, lead) {
  // archiveGrid verified this cell-centred regular transform. Wrap the column
  // at the antimeridian, where +180 and -180 select the same cell.
  const column = Math.floor((station.longitude + 180.125) / 0.25) % 1440;
  const row = Math.floor((90.125 - station.latitude) / 0.25);
  const key = row * 1440 + column;
  if (field.cells.has(key)) return field.cells.get(key);
  const raw = gdal('gdallocationinfo', ['-valonly', '/vsistdin/', String(column), String(row)], field.bytes);
  requireThat(/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw), 'ARCHIVE_DECODER_FAILED');
  const value = Number(raw);
  const temperature = value === field.noData ? null : number(value, -273.15, Infinity, 'VALUE_INVALID');
  const sample = { valid_at: new Date(utc(run) + lead * 3600000).toISOString(), lead_hours: lead,
    grid: { latitude: 90 - row * 0.25, longitude: column * 0.25 - 180 }, temperature_2m: temperature };
  field.cells.set(key, sample);
  return sample;
}

export async function verifyArchivedTemperature(manifest, directory) {
  requireThat(manifest?.schema === 'volparossa.weather.ecmwf-archive-evaluation.v1'
    && Array.isArray(manifest.stations) && manifest.stations.length >= 1 && manifest.stations.length <= 8
    && /^\d{4}-\d{2}-\d{2}$/.test(manifest.retrieved_utc_date), 'ARCHIVE_MANIFEST_INVALID');
  const end = utc(manifest.retrieved_utc_date + 'T23:59:59.999Z');
  const stations = manifest.stations.map(({ observations, provenance }) => {
    const observed = observationIndex(observations, true);
    requireThat([...observed.keys()].every(time => utc(time) <= end), 'OBSERVATION_AFTER_RETRIEVAL');
    requireThat(typeof provenance?.url === 'string' && provenance.url.length <= 512 && URL.canParse(provenance.url)
      && /^https:\/\/[^\s?#@]+$/.test(provenance.url) && typeof provenance.sha256 === 'string' && HASH.test(provenance.sha256),
    'OBSERVATION_PROVENANCE_INVALID');
    return { observations, observed, url: provenance.url, sha256: provenance.sha256 };
  });
  requireThat(new Set(stations.map(s => s.observations.station.id)).size === stations.length
    && new Set(stations.map(s => [s.observations.station.latitude, s.observations.station.longitude].join(','))).size === stations.length,
  'DUPLICATE_STATION');
  const run = manifest.model_run_at, lead = manifest.lead_hours;
  // ECMWF indexes address global fields. Validate both model schedules and
  // both byte snapshots before either one reaches the native decoder.
  const queries = MODELS.map(model => ecmwfRequest({ model, latitude: 0, longitude: 0, run, steps: [lead] }));
  const inputs = await Promise.all(queries.map(query => readField(directory, query, manifest, end)));
  const decoder = gdal('gdalinfo', ['--version'], Buffer.alloc(0));
  requireThat(gdal('gdallocationinfo', ['--version'], Buffer.alloc(0)) === decoder, 'ARCHIVE_DECODER_MISMATCH');
  const fields = inputs.map(input => {
    const raw = gdal('gdalinfo', ['-if', 'GRIB', '-json', '/vsistdin/'], input.bytes);
    let info;
    try { info = JSON.parse(raw); } catch { throw new WeatherError('ARCHIVE_DECODER_FAILED'); }
    const band = archiveGrid(info, run, lead);
    return { ...input, noData: band.noDataValue, cells: new Map() };
  });
  const sources = fields.map(field => field.source);
  const reports = stations.map(({ observations, observed, url, sha256 }) => {
    const samples = fields.map(field => {
      const sample = sampleStation(field, observations.station, manifest.model_run_at, manifest.lead_hours);
      return new Map([[sample.valid_at, sample]]);
    });
    return { observation_file: { url, sha256 }, ...compareTemperatureCases(sources, samples, observations, observed, true) };
  });
  const total = key => reports.reduce((sum, report) => sum + report.coverage[key], 0);
  return { schema: 'volparossa.weather.archived-temperature-verification.v1',
    model_run_at: manifest.model_run_at, lead_hours: manifest.lead_hours, retrieved_utc_date: manifest.retrieved_utc_date,
    availability_basis: 'supplied-archive-last-modified', prospective_capture_proven: false, decoder,
    attribution: 'ECMWF Open Data, CC BY 4.0. Selected native grid cells and converted Kelvin to Celsius.',
    forecast_sources: sources, coverage: { stations: reports.length, grid_cells: fields[0].cells.size,
      candidate_station_times: total('candidate_times'),
      paired: total('paired'), excluded: total('excluded') }, stations: reports };
}
