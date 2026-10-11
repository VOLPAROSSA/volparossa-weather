// SPDX-License-Identifier: GPL-3.0-only
// NOAA's public NODD GEFS mirror: whole-grid fields, with location lookup local.
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, realpath, mkdtemp, mkdir, open, writeFile, rm } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { WeatherError, number, requireThat, utc } from './forecast.mjs';
import { airQualityRequest, airQualityForecastFromSamples, AQ_MAX_AGE_SECONDS,
  AQ_MAX_RUN_AGE_SECONDS } from './air-quality.mjs';
import { runOwnedJsonProcess } from './core-cache.mjs';

export const GEFS_ORIGIN = 'https://noaa-gefs-pds.s3.amazonaws.com';
export const GEFS_MAX_INDEX_BYTES = 65536;
export const GEFS_MAX_FIELD_BYTES = 2 * 1024 * 1024;
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const FIELDS = Object.freeze({
  pm2_5: { parameter: 'PMTF', size: '2.5e-06', parameterNumber: 193,
    scaleFactorOfFirstSize: 7, scaledValueOfFirstSize: 25, paramId: 260375,
    shortName: 'pmtf', name: 'Particulate matter (fine)' },
  pm10: { parameter: 'PMTC', size: '1e-05', parameterNumber: 192,
    scaleFactorOfFirstSize: 6, scaledValueOfFirstSize: 10, paramId: 260374,
    shortName: 'pmtc', name: 'Particulate matter (coarse)' },
});
// Identity captured from the real 20261010/00 f003 public GRIB2 messages.
// PMTC's total aerosol <10um is PM10, not PM10 minus PM2.5.
const COMMON = Object.freeze({
  edition: 2, centre: 'kwbc', subCentre: 0, tablesVersion: 2, localTablesVersion: 1,
  discipline: 0, parameterCategory: 13, productDefinitionTemplateNumber: 48,
  aerosolType: 62000, constituentType: 62000, typeOfSizeInterval: 0,
  scaleFactorOfSecondSize: 0, scaledValueOfSecondSize: 0,
  units: '(10**-6 g) m**-3', stepType: 'instant', stepUnits: 1,
  significanceOfReferenceTime: 1, typeOfProcessedData: 'fc', typeOfGeneratingProcess: 2,
  generatingProcessIdentifier: 96, typeOfLevel: 'surface', level: 0, topLevel: 0, bottomLevel: 0,
  typeOfFirstFixedSurface: 'sfc', scaleFactorOfFirstFixedSurface: 0, scaledValueOfFirstFixedSurface: 0,
  typeOfSecondFixedSurface: 255, scaleFactorOfSecondFixedSurface: 0, scaledValueOfSecondFixedSurface: 0,
  gridType: 'regular_ll', gridDefinitionTemplateNumber: 0, Ni: 1440, Nj: 721,
  numberOfDataPoints: 1038240, latitudeOfFirstGridPointInDegrees: 90,
  longitudeOfFirstGridPointInDegrees: 0, latitudeOfLastGridPointInDegrees: -90,
  longitudeOfLastGridPointInDegrees: 359.75, iDirectionIncrementInDegrees: 0.25,
  jDirectionIncrementInDegrees: 0.25, iScansNegatively: 0, jScansPositively: 0,
  jPointsAreConsecutive: 0, alternativeRowScanning: 0,
  packingType: 'grid_complex_spatial_differencing',
});
const VARIABLE_KEYS = { parameterNumber: 0, scaleFactorOfFirstSize: 0, scaledValueOfFirstSize: 0,
  paramId: 0, shortName: '', name: '', dataDate: 0, dataTime: 0, validityDate: 0, validityTime: 0,
  startStep: 0, endStep: 0, bitmapPresent: 0, numberOfMissing: 0 };
const DECODE_KEYS = Object.entries({ ...COMMON, ...VARIABLE_KEYS })
  .map(([key, value]) => `${key}:${typeof value === 'string' ? 's' : Number.isInteger(value) ? 'i' : 'd'}`).join(',');

async function pinnedDecoderBytes(path, digest) {
  // Inspect and read the same opened object. O_NONBLOCK also prevents a replaced
  // FIFO from blocking before fstat can reject it; never follow a leaf symlink.
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await handle.stat();
    requireThat(before.isFile() && before.size > 0 && before.size <= 64 * 1024 * 1024
      && (before.mode & 0o111) !== 0, 'DECODER_PIN_MISMATCH');
    // One extra byte detects growth without an unbounded readFile allocation.
    const bytes = Buffer.alloc(before.size + 1); let size = 0;
    while (size < bytes.length) {
      const { bytesRead } = await handle.read(bytes, size, bytes.length - size, size);
      if (bytesRead === 0) break;
      size += bytesRead;
    }
    const after = await handle.stat(), captured = bytes.subarray(0, size);
    requireThat(size === before.size && ['size', 'mtimeMs', 'ctimeMs', 'mode', 'uid', 'gid', 'nlink']
      .every(key => before[key] === after[key]) && sha256(captured) === digest, 'DECODER_PIN_MISMATCH');
    return captured;
  } finally { await handle.close(); }
}

function stepQuery(input, step) {
  const query = airQualityRequest(input);
  requireThat(query.steps.includes(step), 'AQ_STEP_NOT_REQUESTED');
  return query;
}
export function gefsFieldUrl(input, step) {
  const query = stepQuery(input, step);
  const date = query.run.slice(0, 10).replaceAll('-', ''), hour = query.run.slice(11, 13);
  return `${GEFS_ORIGIN}/gefs.${date}/${hour}/chem/pgrb2ap25/gefs.chem.t${hour}z.a2d_0p25.f${String(step).padStart(3, '0')}.grib2`;
}

export function selectGefsIndex(input, queryInput, step) {
  const query = stepQuery(queryInput, step);
  requireThat(typeof input === 'string' || input instanceof Uint8Array, 'INDEX_INVALID');
  requireThat((typeof input === 'string' ? Buffer.byteLength(input) : input.byteLength) <= GEFS_MAX_INDEX_BYTES,
    'INDEX_TOO_LARGE');
  let text;
  try { text = typeof input === 'string' ? input : new TextDecoder('utf-8', { fatal: true }).decode(input); }
  catch { throw new WeatherError('INDEX_INVALID'); }
  const lines = text.replace(/\n$/, '').split('\n');
  requireThat(lines.length > 1 && lines.length <= 512, 'INDEX_INVALID');
  const date = query.run.slice(0, 10).replaceAll('-', '') + query.run.slice(11, 13);
  const forecast = step === 0 ? 'anl' : `${step} hour fcst`;
  const records = lines.map((line, index) => {
    requireThat(line.length <= 2048 && !/[\x00-\x1f\x7f]/.test(line), 'INDEX_INVALID');
    const match = /^([1-9][0-9]*):(0|[1-9][0-9]*):d=([0-9]{10}):([^:]+):([^:]+):([^:]+):(.*)$/.exec(line);
    requireThat(match && Number(match[1]) === index + 1, 'INDEX_INVALID');
    const offset = Number(match[2]);
    requireThat(Number.isSafeInteger(offset) && offset < 2 ** 40, 'INDEX_RANGE_INVALID');
    requireThat(match[3] === date && match[6] === forecast, 'INDEX_IDENTITY_MISMATCH');
    return { offset, parameter: match[4], level: match[5], qualifiers: match[7] };
  });
  requireThat(records[0].offset === 0 && records.slice(1).every((record, i) => record.offset > records[i].offset),
    'INDEX_RANGE_INVALID');
  return Object.fromEntries(Object.entries(FIELDS).map(([field, expected]) => {
    const selected = records.flatMap((record, index) => {
      if (record.parameter !== expected.parameter || !record.qualifiers.startsWith('aerosol=Total aerosol:')) return [];
      requireThat(record.level === 'surface'
        && record.qualifiers === `aerosol=Total aerosol:aerosol_size <${expected.size}:`, 'INDEX_IDENTITY_MISMATCH');
      requireThat(index + 1 < records.length, 'INDEX_RANGE_INVALID');
      const length = records[index + 1].offset - record.offset;
      requireThat(length >= 20 && length <= GEFS_MAX_FIELD_BYTES, 'INDEX_RANGE_INVALID');
      return [{ offset: record.offset, length }];
    });
    requireThat(selected.length === 1, 'FIELD_MISSING_OR_AMBIGUOUS');
    return [field, selected[0]];
  }));
}

function aborted(signal) { if (signal?.aborted) throw new WeatherError('CANCELLED'); }
function untilAbort(promise, signal) {
  if (signal.aborted) return Promise.reject(new WeatherError('CANCELLED'));
  let listener;
  const abort = new Promise((resolve, reject) => {
    listener = () => reject(new WeatherError('CANCELLED'));
    signal.addEventListener('abort', listener, { once: true });
  });
  return Promise.race([promise, abort]).finally(() => signal.removeEventListener('abort', listener));
}
async function getBytes(url, { range, signal, fetchImpl }) {
  aborted(signal);
  const controller = new AbortController(), abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 30000);
  let reader, response;
  try {
    const headers = { 'Accept-Encoding': 'identity' };
    if (range) headers.Range = `bytes=${range.offset}-${range.offset + range.length - 1}`;
    response = await untilAbort(Promise.resolve().then(() => fetchImpl(url, { method: 'GET', headers,
      signal: controller.signal, redirect: 'error', credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-store' })), controller.signal);
    requireThat(response.url === url && !response.redirected, 'ORIGIN_CHANGED');
    requireThat(response.status === (range ? 206 : 200), range ? 'EXACT_RANGE_REQUIRED' : 'INDEX_HTTP_FAILED');
    requireThat(!response.headers.get('content-encoding') || response.headers.get('content-encoding') === 'identity', 'ENCODING_INVALID');
    const limit = range?.length ?? GEFS_MAX_INDEX_BYTES, declared = response.headers.get('content-length');
    requireThat(declared === null || (/^[0-9]+$/.test(declared) && Number(declared) <= limit), 'BODY_TOO_LARGE');
    if (range) {
      const match = /^bytes ([0-9]+)-([0-9]+)\/([0-9]+)$/.exec(response.headers.get('content-range') ?? '');
      requireThat(match && Number(match[1]) === range.offset && Number(match[2]) === range.offset + range.length - 1
        && Number.isSafeInteger(Number(match[3])) && Number(match[3]) > Number(match[2]), 'RANGE_RESPONSE_MISMATCH');
    }
    requireThat(response.body?.getReader, 'BODY_UNAVAILABLE'); reader = response.body.getReader();
    let size = 0; const chunks = [];
    while (true) {
      const { done, value } = await untilAbort(reader.read(), controller.signal); if (done) break;
      requireThat(value instanceof Uint8Array, 'BODY_INVALID');
      size += value.byteLength; requireThat(size <= limit, 'BODY_TOO_LARGE'); chunks.push(value);
    }
    requireThat(declared === null || size === Number(declared), 'BODY_TRUNCATED');
    if (range) requireThat(size === range.length, 'FIELD_TRUNCATED');
    return Buffer.concat(chunks, size);
  } catch (error) {
    if (controller.signal.aborted) throw new WeatherError(signal?.aborted ? 'CANCELLED' : 'TIMEOUT');
    if (error instanceof WeatherError) throw error;
    throw new WeatherError('NETWORK_FAILED');
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort); controller.abort();
    // Abort owns the real fetch. A hostile test transport must not stall cleanup.
    if (reader) void reader.cancel().catch(() => {});
    else if (response?.body) void response.body.cancel().catch(() => {});
  }
}

function decodePoint(decoded, query, step, field) {
  requireThat(Array.isArray(decoded) && decoded.length === 1, 'DECODE_MESSAGE_COUNT');
  const { keys, method, neighbours } = decoded[0] ?? {};
  requireThat(keys && typeof keys === 'object' && !Array.isArray(keys), 'DECODE_IDENTITY_MISMATCH');
  const { parameter, size, ...identity } = FIELDS[field];
  const validAt = new Date(utc(query.run) + step * 3600000).toISOString();
  const expected = { ...COMMON, ...identity, startStep: step, endStep: step,
    dataDate: Number(query.run.slice(0, 10).replaceAll('-', '')), dataTime: Number(query.run.slice(11, 13)) * 100,
    validityDate: Number(validAt.slice(0, 10).replaceAll('-', '')), validityTime: Number(validAt.slice(11, 13)) * 100 };
  requireThat(Object.entries(expected).every(([key, value]) => keys[key] === value), 'DECODE_IDENTITY_MISMATCH');
  requireThat([0, 1].includes(keys.bitmapPresent) && Number.isInteger(keys.numberOfMissing)
    && keys.numberOfMissing >= 0 && keys.numberOfMissing <= COMMON.numberOfDataPoints
    && (keys.bitmapPresent === 1 || keys.numberOfMissing === 0), 'DECODE_MISSINGNESS_INVALID');
  requireThat(method === 'nearest' && Array.isArray(neighbours) && neighbours.length === 1, 'DECODE_GRID_INVALID');
  const point = neighbours[0];
  requireThat(point && point.unit === COMMON.units && point.distance_unit === 'km', 'DECODE_UNITS_INVALID');
  // grib_ls emits null for missing (including its 9999 sentinel); never turn that
  // absence into clean air. Its nearest JSON values have six significant digits.
  if (point.value !== null) number(point.value, 0, Infinity, 'DECODE_VALUE_INVALID');
  number(point.latitude, -90, 90, 'DECODE_GRID_INVALID'); number(point.longitude, 0, 359.75, 'DECODE_GRID_INVALID');
  number(point.distance, 0, 50, 'DECODE_GRID_INVALID');
  const column = point.longitude * 4, row = (90 - point.latitude) * 4;
  requireThat(Number.isInteger(row) && Number.isInteger(column) && point.index === row * 1440 + column,
    'DECODE_GRID_INVALID');
  const lon = (query.longitude + 360) % 360, radians = Math.PI / 180;
  // ecCodes chooses the geographically nearest of the surrounding four points,
  // not independently rounded latitude/longitude (important near high latitudes).
  const separation = (latitude, longitude) => Math.sin((latitude - query.latitude) * radians / 2) ** 2
    + Math.cos(query.latitude * radians) * Math.cos(latitude * radians)
      * Math.sin((longitude - lon) * radians / 2) ** 2;
  const rows = [Math.floor((90 - query.latitude) * 4), Math.ceil((90 - query.latitude) * 4)];
  const columns = [Math.floor(lon * 4) % 1440, Math.ceil(lon * 4) % 1440];
  const closest = Math.min(...rows.flatMap(r => columns.map(c => separation(90 - r / 4, c / 4))));
  const selected = separation(point.latitude, point.longitude);
  requireThat(Math.abs(selected - closest) <= 1e-15, 'DECODE_QUERY_MISMATCH');
  return { point, validAt };
}
export function sampleFromGefsDecoded(decoded, input, step, evidence) {
  const query = stepQuery(input, step);
  const parts = Object.fromEntries(Object.keys(FIELDS).map(field => [field, decodePoint(decoded?.[field], query, step, field)]));
  const point = parts.pm2_5.point;
  requireThat(['latitude', 'longitude', 'distance', 'index'].every(key => point[key] === parts.pm10.point[key]), 'DECODE_GRID_MISMATCH');
  return { valid_at: parts.pm2_5.validAt, lead_hours: step, pm2_5: point.value, pm10: parts.pm10.point.value,
    grid: { latitude: point.latitude, longitude: point.longitude > 180 ? point.longitude - 360 : point.longitude,
      distance_km: point.distance, method: 'nearest-grid-no-interpolation' }, evidence };
}

export async function fetchAirQualityForecast(input, { mode, acceptDataLicense = false,
  fetchImpl = globalThis.fetch, decoder, decoderSha256, workDirectory, signal,
  now = () => new Date().toISOString(), maxAgeSeconds = AQ_MAX_AGE_SECONDS } = {}) {
  const query = airQualityRequest(input);
  requireThat(mode === 'origin' && acceptDataLicense === true, 'EXPLICIT_ORIGIN_LICENSE_REQUIRED');
  number(maxAgeSeconds, 1, AQ_MAX_AGE_SECONDS, 'EXPIRY_INVALID');
  const clock = () => typeof now === 'function' ? now() : now;
  const checkAge = () => { const value = clock(), age = utc(value) - utc(query.run);
    requireThat(age >= 0 && age < AQ_MAX_RUN_AGE_SECONDS * 1000, 'RUN_AGE_INVALID'); return value; };
  checkAge(); aborted(signal);
  requireThat(process.platform === 'linux', 'DECODER_PLATFORM_UNAVAILABLE');
  requireThat(typeof fetchImpl === 'function', 'FETCH_INVALID');
  requireThat(typeof decoderSha256 === 'string' && /^[a-f0-9]{64}$/.test(decoderSha256), 'DECODER_PIN_REQUIRED');
  requireThat(typeof decoder === 'string' && isAbsolute(decoder) && await realpath(decoder) === decoder, 'DECODER_PATH_INVALID');
  const program = await pinnedDecoderBytes(decoder, decoderSha256);
  requireThat(typeof workDirectory === 'string' && isAbsolute(workDirectory), 'PRIVATE_PARENT_REQUIRED');
  const parent = await lstat(workDirectory);
  requireThat(parent.isDirectory() && parent.uid === process.getuid() && (parent.mode & 0o777) === 0o700
    && await realpath(workDirectory) === workDirectory, 'PRIVATE_PARENT_REQUIRED');
  aborted(signal);
  const work = await mkdtemp(join(workDirectory, 'noaa-gefs-'));
  const samples = [];
  try {
    // Execute the captured, pinned bytes, not the replaceable source pathname.
    // The supported ecCodes build embeds definitions/static ecCodes+libaec; its
    // $ORIGIN/../lib lookup remains inside this new private tree (no lib there),
    // with only the documented system runtime libraries resolved externally.
    // Arbitrary decoders needing adjacent files are not relocation-compatible.
    // This is not isolation from root/same-UID tampering or system-library trust.
    const executableDirectory = join(work, 'decoder'), executable = join(executableDirectory, 'grib_ls');
    await mkdir(executableDirectory, { mode: 0o700 });
    await writeFile(executable, program, { mode: 0o500, flag: 'wx' });
    for (const step of query.steps) {
      checkAge(); aborted(signal);
      const url = gefsFieldUrl(query, step);
      const index = await getBytes(`${url}.idx`, { fetchImpl, signal });
      const ranges = selectGefsIndex(index, query, step), decoded = {}, evidence = {};
      for (const field of Object.keys(FIELDS)) {
        const range = ranges[field], bytes = await getBytes(url, { fetchImpl, signal, range });
        requireThat(bytes.length === range.length && bytes.length >= 20 && bytes.subarray(0, 4).toString() === 'GRIB'
          && bytes[7] === 2 && bytes.readBigUInt64BE(8) === BigInt(bytes.length)
          && bytes.subarray(-4).toString() === '7777', 'GRIB_ENVELOPE_INVALID');
        const path = join(work, `${field}.grib2`);
        await writeFile(path, bytes, { mode: 0o600, flag: 'wx' });
        aborted(signal);
        decoded[field] = await runOwnedJsonProcess('/usr/bin/prlimit', ['--as=536870912', '--cpu=20', '--',
          executable, '-j', '-l', `${query.latitude},${query.longitude},1`, '-p', DECODE_KEYS, path], work, signal, 30000);
        evidence[field] = { index_sha256: sha256(index), field_sha256: sha256(bytes), range_start: range.offset,
          range_length: range.length, decoder_sha256: decoderSha256 };
        await rm(path);
      }
      samples.push(sampleFromGefsDecoded(decoded, query, step, evidence));
    }
    aborted(signal);
    return airQualityForecastFromSamples({ query, samples, acquiredAt: checkAge(), maxAgeSeconds });
  } finally { await rm(work, { recursive: true, force: false }); }
}
