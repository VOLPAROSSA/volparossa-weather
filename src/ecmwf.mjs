// SPDX-License-Identifier: GPL-3.0-only
import { createHash } from 'node:crypto';
import { lstat, realpath, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { MAX_AGE_SECONDS, MAX_RUN_AGE_SECONDS, SCHEMA, UNITS, WIND_UNITS, WeatherError,
  number, request, requireThat, utc, validateForecast, windVector } from './forecast.mjs';
import { runOwnedJsonProcess } from './core-cache.mjs';

export const ORIGIN = 'https://data.ecmwf.int/forecasts';
export const MAX_INDEX_BYTES = 524288;
export const MAX_FIELD_BYTES = 8 * 1024 * 1024;
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const PARAMETERS = Object.freeze({ '2t': { id: 167, level: 2, unit: 'K' },
  '10u': { id: 165, level: 10, unit: 'm s**-1' }, '10v': { id: 166, level: 10, unit: 'm s**-1' } });
const GRID_KEYS = ['Ni', 'Nj', 'latitudeOfFirstGridPointInDegrees', 'longitudeOfFirstGridPointInDegrees',
  'latitudeOfLastGridPointInDegrees', 'longitudeOfLastGridPointInDegrees', 'iDirectionIncrementInDegrees',
  'jDirectionIncrementInDegrees', 'iScansNegatively', 'jScansPositively', 'jPointsAreConsecutive'];

export function ecmwfRequest(input) {
  const query = request(input);
  const run = new Date(utc(query.run));
  requireThat(['ifs', 'aifs-single'].includes(query.model), 'ECMWF_MODEL_UNSUPPORTED');
  requireThat(run.getUTCMinutes() === 0 && run.getUTCHours() % 6 === 0
    && query.run >= '2026-05-13T00:00:00.000Z', 'ECMWF_RUN_UNSUPPORTED');
  // Current dataset catalogue supersedes shorter horizons in older access examples.
  const maximum = query.model === 'ifs' ? (run.getUTCHours() % 12 === 0 ? 360 : 144) : 360;
  for (const step of query.steps) requireThat(step <= maximum
    && step % (query.model === 'aifs-single' || step > 144 ? 6 : 3) === 0, 'ECMWF_STEP_UNSUPPORTED');
  return query;
}

export function fieldUrl(input, step, extension) {
  const query = ecmwfRequest(input);
  requireThat(query.steps.includes(step) && ['index', 'grib2'].includes(extension), 'REQUEST_INVALID');
  const date = query.run.slice(0, 10).replaceAll('-', ''), hour = query.run.slice(11, 13);
  return `${ORIGIN}/${date}/${hour}z/${query.model}/0p25/oper/${date}${hour}0000-${step}h-oper-fc.${extension}`;
}

export function selectIndex(bytes, input, step, parameter = '2t') {
  const query = ecmwfRequest(input);
  requireThat(Object.hasOwn(PARAMETERS, parameter), 'PARAMETER_UNSUPPORTED');
  requireThat(bytes instanceof Uint8Array && bytes.length <= MAX_INDEX_BYTES, 'INDEX_TOO_LARGE');
  let lines;
  try { lines = new TextDecoder('utf-8', { fatal: true }).decode(bytes).trim().split('\n'); }
  catch { throw new WeatherError('INDEX_INVALID'); }
  requireThat(lines.length <= 4096, 'INDEX_TOO_LARGE');
  const selected = [];
  for (const line of lines) {
    requireThat(line.length <= 4096, 'INDEX_INVALID');
    let item;
    try { item = JSON.parse(line); } catch { throw new WeatherError('INDEX_INVALID'); }
    requireThat(item && !Array.isArray(item) && typeof item === 'object', 'INDEX_INVALID');
    if (item.param !== parameter || item.levtype !== 'sfc') continue;
    requireThat(item.date === query.run.slice(0, 10).replaceAll('-', '') && item.time === query.run.slice(11, 13) + '00'
      && item.step === String(step) && item.class === (query.model === 'ifs' ? 'od' : 'ai')
      && item.type === 'fc' && item.stream === 'oper' && item.expver === '0001', 'INDEX_IDENTITY_MISMATCH');
    requireThat(Number.isSafeInteger(item._offset) && item._offset >= 0 && item._offset < 2 ** 40
      && Number.isSafeInteger(item._length) && item._length >= 20 && item._length <= MAX_FIELD_BYTES, 'INDEX_RANGE_INVALID');
    selected.push({ offset: item._offset, length: item._length });
  }
  requireThat(selected.length === 1, 'FIELD_MISSING_OR_AMBIGUOUS');
  return selected[0];
}

async function getBytes(url, { range = null, signal, fetcher = globalThis.fetch } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw new WeatherError('CANCELLED');
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 30000);
  let reader;
  try {
    const headers = { 'Accept-Encoding': 'identity' };
    if (range) headers.Range = `bytes=${range.offset}-${range.offset + range.length - 1}`;
    const response = await fetcher(url, { method: 'GET', headers, signal: controller.signal,
      redirect: 'error', credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-store' });
    requireThat(response.url === url && !response.redirected, 'ORIGIN_CHANGED');
    requireThat(response.status === (range ? 206 : 200), range ? 'EXACT_RANGE_REQUIRED' : 'INDEX_HTTP_FAILED');
    requireThat(!response.headers.get('content-encoding') || response.headers.get('content-encoding') === 'identity', 'ENCODING_INVALID');
    const limit = range ? range.length : MAX_INDEX_BYTES;
    const declared = response.headers.get('content-length');
    requireThat(declared === null || (/^\d+$/.test(declared) && Number(declared) <= limit), 'BODY_TOO_LARGE');
    if (range) {
      const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('content-range') ?? '');
      requireThat(match && Number(match[1]) === range.offset && Number(match[2]) === range.offset + range.length - 1
        && Number.isSafeInteger(Number(match[3])) && Number(match[3]) > Number(match[2]), 'RANGE_RESPONSE_MISMATCH');
    }
    requireThat(response.body?.getReader, 'BODY_UNAVAILABLE'); reader = response.body.getReader();
    let size = 0; const chunks = [];
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; requireThat(size <= limit, 'BODY_TOO_LARGE'); chunks.push(value);
    }
    if (range) requireThat(size === range.length, 'FIELD_TRUNCATED');
    return Buffer.concat(chunks, size);
  } catch (error) {
    if (error instanceof WeatherError) throw error;
    throw new WeatherError(controller.signal.aborted ? (signal?.aborted ? 'CANCELLED' : 'TIMEOUT') : 'NETWORK_FAILED');
  } finally { await reader?.cancel().catch(() => {}); clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

export function checkGrib(bytes, length) {
  requireThat(bytes.length === length && bytes.length >= 20 && bytes.subarray(0, 4).toString() === 'GRIB'
    && bytes[7] === 2 && bytes.readBigUInt64BE(8) === BigInt(length)
    && bytes.subarray(-4).toString() === '7777', 'GRIB_ENVELOPE_INVALID');
}

export async function fetchField(input, step, { mode, acceptDataLicense = false, signal, fetcher } = {}) {
  return (await fetchFields({ ...input, includeWind: false }, step, { mode, acceptDataLicense, signal, fetcher }))['2t'];
}

export async function fetchFields(input, step, { mode, acceptDataLicense = false, signal, fetcher } = {}) {
  requireThat(mode === 'origin', 'ORIGIN_MODE_REQUIRED');
  requireThat(acceptDataLicense === true, 'DATA_LICENSE_REQUIRED');
  const query = ecmwfRequest(input);
  const index = await getBytes(fieldUrl(query, step, 'index'), { signal, fetcher });
  const parameters = query.includeWind ? ['2t', '10u', '10v'] : ['2t'];
  const ranges = parameters.map(parameter => ({ parameter, ...selectIndex(index, query, step, parameter) }));
  const ordered = [...ranges].sort((a, b) => a.offset - b.offset);
  requireThat(ordered.slice(1).every((item, i) => item.offset >= ordered[i].offset + ordered[i].length), 'INDEX_RANGES_OVERLAP');
  const result = {};
  for (const { parameter, offset, length } of ranges) {
    const range = { offset, length };
    const field = await getBytes(fieldUrl(query, step, 'grib2'), { range, signal, fetcher });
    checkGrib(field, range.length);
    result[parameter] = { field, indexSha256: sha256(index), fieldSha256: sha256(field), range };
  }
  return result;
}

function decodedPoint(decoded, input, step, parameter) {
  const query = ecmwfRequest(input);
  const expected = PARAMETERS[parameter];
  requireThat(expected !== undefined, 'PARAMETER_UNSUPPORTED');
  requireThat(Array.isArray(decoded) && decoded.length === 1, 'DECODE_MESSAGE_COUNT');
  const { keys, method, neighbours } = decoded[0];
  const validAt = new Date(utc(query.run) + step * 3600000).toISOString();
  requireThat(keys && keys.edition === 2 && keys.centre === 'ecmf' && keys.shortName === parameter && keys.paramId === expected.id
    && keys.dataDate === Number(query.run.slice(0, 10).replaceAll('-', '')) && keys.dataTime === Number(query.run.slice(11, 13)) * 100
    && keys.validityDate === Number(validAt.slice(0, 10).replaceAll('-', '')) && keys.validityTime === Number(validAt.slice(11, 13)) * 100
    && keys.stepType === 'instant' && keys.startStep === step && keys.endStep === step && keys.stepUnits === 1
    && keys.typeOfLevel === 'heightAboveGround' && keys.level === expected.level && keys.gridType === 'regular_ll'
    && keys.class === (query.model === 'ifs' ? 'od' : 'ai') && keys.stream === 'oper' && keys.type === 'fc', 'DECODE_IDENTITY_MISMATCH');
  requireThat(method === 'nearest' && Array.isArray(neighbours) && neighbours.length === 1, 'DECODE_GRID_INVALID');
  const point = neighbours[0];
  requireThat(point.unit === expected.unit && point.distance_unit === 'km', 'DECODE_UNITS_INVALID');
  if (point.value !== null) number(point.value, parameter === '2t' ? 0 : -Infinity, Infinity, 'DECODE_VALUE_INVALID');
  number(point.latitude, -90, 90, 'DECODE_GRID_INVALID'); number(point.longitude, 0, 360, 'DECODE_GRID_INVALID');
  number(point.distance, 0, 50, 'DECODE_GRID_INVALID');
  return { keys, point, validAt };
}

export function sampleFromDecoded(decoded, input, step, evidence) {
  const { point, validAt } = decodedPoint(decoded, input, step, '2t');
  return { valid_at: validAt, lead_hours: step, temperature_2m: point.value === null ? null : point.value - 273.15,
    grid: { latitude: point.latitude, longitude: point.longitude > 180 ? point.longitude - 360 : point.longitude,
      distance_km: point.distance, method: 'nearest-grid-no-interpolation' }, evidence };
}

export function sampleWithWind(decoded, input, step, evidence) {
  requireThat(ecmwfRequest(input).includeWind, 'WIND_REQUEST_REQUIRED');
  const sample = sampleFromDecoded(decoded['2t'], input, step, evidence['2t']);
  const parts = Object.fromEntries(['2t', '10u', '10v'].map(parameter =>
    [parameter, decodedPoint(decoded[parameter], input, step, parameter)]));
  const temperature = parts['2t'];
  for (const { keys, point } of Object.values(parts)) {
    for (const key of GRID_KEYS) {
      number(keys[key], -Infinity, Infinity, 'DECODE_GRID_INVALID');
      requireThat(keys[key] === temperature.keys[key], 'DECODE_GRID_MISMATCH');
    }
    requireThat(keys.Ni === 1440 && keys.Nj === 721
      && keys.iDirectionIncrementInDegrees === 0.25 && keys.jDirectionIncrementInDegrees === 0.25
      && [keys.iScansNegatively, keys.jScansPositively, keys.jPointsAreConsecutive].every(flag => flag === 0 || flag === 1),
    'DECODE_GRID_INVALID');
    requireThat(['latitude', 'longitude', 'distance'].every(key => point[key] === temperature.point[key]), 'DECODE_GRID_MISMATCH');
  }
  requireThat(parts['10u'].keys.uvRelativeToGrid === 0 && parts['10v'].keys.uvRelativeToGrid === 0,
    'WIND_ORIENTATION_UNSUPPORTED');
  return { ...sample, wind_10m: { ...windVector(parts['10u'].point.value, parts['10v'].point.value),
    evidence: { eastward: evidence['10u'], northward: evidence['10v'] } } };
}

export function forecastFromSamples(input, samples, acquiredAt) {
  const query = request(input), acquired = utc(acquiredAt), run = utc(query.run);
  requireThat(JSON.stringify(samples.map(sample => sample.lead_hours)) === JSON.stringify(query.steps), 'FORECAST_STEPS_MISMATCH');
  return validateForecast({ schema: SCHEMA, kind: 'forecast',
    area: { latitude: query.latitude, longitude: query.longitude, sharing: query.communityArea ? 'public-community' : 'private' },
    source: { provider: 'ecmwf', product: 'open-data-single-level-forecast', model: query.model,
      model_run_at: query.run, issued_at: null, acquired_at: acquiredAt, acquisition: 'origin-https',
      attribution: 'ECMWF open data', license: 'CC-BY-4.0', license_url: 'https://creativecommons.org/licenses/by/4.0/',
      changes: query.includeWind
        ? 'Nearest co-located grid via ecCodes; Kelvin to Celsius; 10 m east/north components to speed and meteorological direction-from; no interpolation.'
        : 'Nearest grid point via ecCodes; 2 m temperature converted from Kelvin to Celsius; no interpolation.' },
    units: { ...UNITS, ...(query.includeWind ? WIND_UNITS : {}) }, samples,
    freshness: { basis: 'acquisition-and-model-run-age',
      expires_at: new Date(Math.min(acquired + MAX_AGE_SECONDS * 1000, run + MAX_RUN_AGE_SECONDS * 1000)).toISOString() } });
}

export async function fetchForecast(input, { mode, acceptDataLicense, decoder, decoderSha256, scratchParent, signal } = {}) {
  const query = ecmwfRequest(input);
  requireThat(mode === 'origin' && acceptDataLicense === true, 'EXPLICIT_ORIGIN_LICENSE_REQUIRED');
  requireThat(process.platform === 'linux', 'DECODER_PLATFORM_UNAVAILABLE');
  requireThat(typeof decoderSha256 === 'string' && /^[a-f0-9]{64}$/.test(decoderSha256), 'DECODER_PIN_REQUIRED');
  requireThat(isAbsolute(decoder) && await realpath(decoder) === decoder, 'DECODER_PATH_INVALID');
  const program = await lstat(decoder);
  requireThat(program.isFile() && program.size <= 64 * 1024 * 1024
    && sha256(await readFile(decoder)) === decoderSha256, 'DECODER_PIN_MISMATCH');
  const parent = await lstat(scratchParent);
  requireThat(parent.isDirectory() && parent.uid === process.getuid() && (parent.mode & 0o777) === 0o700
    && await realpath(scratchParent) === scratchParent, 'PRIVATE_PARENT_REQUIRED');
  const runAge = Date.now() - utc(query.run);
  requireThat(runAge >= 0 && runAge < MAX_RUN_AGE_SECONDS * 1000, 'RUN_AGE_INVALID');
  const work = await mkdtemp(join(scratchParent, 'ecmwf-'));
  const samples = [];
  try {
    for (const step of query.steps) {
      const fields = await fetchFields(query, step, { mode, acceptDataLicense, signal });
      const decoded = {}, evidence = {};
      for (const [parameter, downloaded] of Object.entries(fields)) {
        const path = join(work, `field-${step}-${parameter}.grib2`);
        await writeFile(path, downloaded.field, { mode: 0o600, flag: 'wx' });
        const keys = 'edition:i,centre:s,dataDate:i,dataTime:i,validityDate:i,validityTime:i,shortName:s,paramId:i,typeOfLevel:s,level:i,stepType:s,startStep:i,endStep:i,stepUnits:i,class:s,stream:s,type:s,gridType:s'
          + (query.includeWind ? ',' + GRID_KEYS.map(key => key + ':d').join(',') : '')
          + (parameter !== '2t' ? ',uvRelativeToGrid:i' : '');
        decoded[parameter] = await runOwnedJsonProcess('/usr/bin/prlimit', ['--as=536870912', '--cpu=20', '--', decoder,
          '-j', '-l', `${query.latitude},${query.longitude},1`, '-p', keys, path], work, signal, 30000);
        await rm(path); // Keep scratch disk bounded to one decoded field, not every requested lead.
        evidence[parameter] = { index_sha256: downloaded.indexSha256, field_sha256: downloaded.fieldSha256,
          parameter, unit: PARAMETERS[parameter].unit, statistic: 'instant', resolution: '0p25',
          range_start: downloaded.range.offset, range_length: downloaded.range.length, decoder_sha256: decoderSha256 };
      }
      samples.push(query.includeWind ? sampleWithWind(decoded, query, step, evidence)
        : sampleFromDecoded(decoded['2t'], query, step, evidence['2t']));
    }
    return forecastFromSamples(query, samples, new Date().toISOString());
  } finally { await rm(work, { recursive: true, force: false }); }
}
