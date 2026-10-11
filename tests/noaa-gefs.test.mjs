// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { mkdtemp, chmod, mkdir, open, writeFile, readdir, rename, rm, stat, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { airQualityRequest } from '../src/air-quality.mjs';
import { fetchAirQualityForecast, gefsFieldUrl, selectGefsIndex, sampleFromGefsDecoded,
  GEFS_MAX_INDEX_BYTES, GEFS_MAX_FIELD_BYTES } from '../src/noaa-gefs.mjs';

const QUERY = airQualityRequest({ latitude: 52.52, longitude: 13.41, run: '2026-10-10T00:00:00.000Z', steps: [3] });
const NOW = '2026-10-10T04:00:00.000Z';
const code = expected => error => error.code === expected;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
// Literal metadata from the real NOAA 20261010/00 f003 public-mirror probe,
// not a claim that these deliberately tiny test bytes are meteorological GRIB.
function decoded(field = 'pm2_5') {
  return [{ keys: {
    edition: 2, centre: 'kwbc', subCentre: 0, tablesVersion: 2, localTablesVersion: 1,
    discipline: 0, parameterCategory: 13, parameterNumber: field === 'pm2_5' ? 193 : 192,
    productDefinitionTemplateNumber: 48, aerosolType: 62000, constituentType: 62000,
    typeOfSizeInterval: 0, scaleFactorOfFirstSize: field === 'pm2_5' ? 7 : 6,
    scaledValueOfFirstSize: field === 'pm2_5' ? 25 : 10, scaleFactorOfSecondSize: 0, scaledValueOfSecondSize: 0,
    paramId: field === 'pm2_5' ? 260375 : 260374, shortName: field === 'pm2_5' ? 'pmtf' : 'pmtc',
    name: field === 'pm2_5' ? 'Particulate matter (fine)' : 'Particulate matter (coarse)',
    units: '(10**-6 g) m**-3', stepType: 'instant', stepUnits: 1, startStep: 3, endStep: 3,
    dataDate: 20261010, dataTime: 0, validityDate: 20261010, validityTime: 300,
    significanceOfReferenceTime: 1, typeOfProcessedData: 'fc', typeOfGeneratingProcess: 2,
    generatingProcessIdentifier: 96, typeOfLevel: 'surface', level: 0, topLevel: 0, bottomLevel: 0,
    typeOfFirstFixedSurface: 'sfc', scaleFactorOfFirstFixedSurface: 0, scaledValueOfFirstFixedSurface: 0,
    typeOfSecondFixedSurface: 255, scaleFactorOfSecondFixedSurface: 0, scaledValueOfSecondFixedSurface: 0,
    gridType: 'regular_ll', gridDefinitionTemplateNumber: 0, Ni: 1440, Nj: 721, numberOfDataPoints: 1038240,
    latitudeOfFirstGridPointInDegrees: 90, longitudeOfFirstGridPointInDegrees: 0,
    latitudeOfLastGridPointInDegrees: -90, longitudeOfLastGridPointInDegrees: 359.75,
    iDirectionIncrementInDegrees: 0.25, jDirectionIncrementInDegrees: 0.25,
    iScansNegatively: 0, jScansPositively: 0, jPointsAreConsecutive: 0, alternativeRowScanning: 0,
    bitmapPresent: 0, numberOfMissing: 0, packingType: 'grid_complex_spatial_differencing',
  }, method: 'nearest', neighbours: [{ index: 216054, latitude: 52.5, longitude: 13.5,
    distance: 6.48435, distance_unit: 'km', value: field === 'pm2_5' ? 5.53071 : 11.5959,
    unit: '(10**-6 g) m**-3' }] }];
}
const pair = () => ({ pm2_5: decoded(), pm10: decoded('pm10') });
const index = () => [
  '1:0:d=2026101000:PMTC:surface:3 hour fcst:aerosol=Total aerosol:aerosol_size <1e-05:',
  '2:64:d=2026101000:PMTF:surface:3 hour fcst:aerosol=Total aerosol:aerosol_size <2.5e-06:',
  '3:128:d=2026101000:COLMD:entire atmosphere:3 hour fcst:aerosol=Total aerosol:aerosol_size <1e-05:',
].join('\n') + '\n';
function grib() { const bytes = Buffer.alloc(64); bytes.write('GRIB'); bytes[7] = 2;
  bytes.writeBigUInt64BE(64n, 8); bytes.write('7777', 60); return bytes; }
function response(url, body, status = 200, headers = {}) {
  const value = new Response(body, { status, headers }); Object.defineProperty(value, 'url', { value: url }); return value;
}
function transport(override = null) {
  return async (url, options) => {
    assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error');
    assert.equal(options.referrerPolicy, 'no-referrer'); assert.equal(options.cache, 'no-store');
    assert.equal(options.method, 'GET');
    assert.equal(url, gefsFieldUrl(QUERY, 3) + (url.endsWith('.idx') ? '.idx' : ''));
    if (override) { const changed = override(url, options); if (changed) return changed; }
    if (url.endsWith('.idx')) { assert.deepEqual(options.headers, { 'Accept-Encoding': 'identity' });
      return response(url, index()); }
    const range = options.headers.Range === 'bytes=64-127' ? 'bytes 64-127/192' : 'bytes 0-63/192';
    assert.ok(['bytes=0-63', 'bytes=64-127'].includes(options.headers.Range));
    return response(url, grib(), 206, { 'Content-Range': range });
  };
}
async function fixture(action, script = null) {
  const parent = await mkdtemp(join(tmpdir(), 'volparossa-noaa-test-')); await chmod(parent, 0o700);
  try {
    const decoder = join(parent, 'decoder');
    const source = script ?? `#!/bin/sh\ncase "$6" in\n*/pm2_5.grib2) printf '%s' '${JSON.stringify(decoded())}' ;;\n*/pm10.grib2) printf '%s' '${JSON.stringify(decoded('pm10'))}' ;;\n*) exit 3 ;;\nesac\n`;
    await writeFile(decoder, source, { mode: 0o700, flag: 'wx' });
    const options = { mode: 'origin', acceptDataLicense: true, decoder, decoderSha256: hash(source),
      workDirectory: parent, fetchImpl: transport(), now: NOW };
    await action(options, parent);
    assert.deepEqual((await readdir(parent)).sort(), ['decoder']);
  } finally { await rm(parent, { recursive: true, force: false }); }
}

test('fixed anonymous mirror paths contain run/lead, never private coordinates or an alternate origin', () => {
  assert.equal(gefsFieldUrl(QUERY, 3),
    'https://noaa-gefs-pds.s3.amazonaws.com/gefs.20261010/00/chem/pgrb2ap25/gefs.chem.t00z.a2d_0p25.f003.grib2');
  assert.equal(gefsFieldUrl({ ...QUERY, latitude: -43, longitude: -175 }, 3), gefsFieldUrl(QUERY, 3));
  assert.match(gefsFieldUrl({ ...QUERY, run: '2026-10-10T18:00:00.000Z', steps: [120] }, 120), /t18z.*f120/);
  assert.throws(() => gefsFieldUrl(QUERY, 6), code('AQ_STEP_NOT_REQUESTED'));
  for (const changes of [{ steps: [1] }, { steps: [123] }, { steps: [3, 3] }, { model: 'gfs' },
    { run: '2026-10-10T03:00:00.000Z' }, { latitude: NaN }]) assert.throws(() => gefsFieldUrl({ ...QUERY, ...changes }, 3));
});

test('inventory selects total surface PM2.5/PM10, not dust, salt, or column mass', () => {
  assert.deepEqual(selectGefsIndex(Buffer.from(index()), QUERY, 3), {
    pm2_5: { offset: 64, length: 64 }, pm10: { offset: 0, length: 64 },
  });
  const actual = [
    '1:0:d=2026101000:PMTF:surface:3 hour fcst:aerosol=Dust dry:aerosol_size <2.5e-06:',
    '2:20296273:d=2026101000:PMTC:surface:3 hour fcst:aerosol=Total aerosol:aerosol_size <1e-05:',
    '3:21103457:d=2026101000:PMTF:surface:3 hour fcst:aerosol=Total aerosol:aerosol_size <2.5e-06:',
    '4:21719384:d=2026101000:COLMD:entire atmosphere:3 hour fcst:aerosol=Total aerosol:aerosol_size <1e-05:',
  ].join('\n');
  assert.deepEqual(selectGefsIndex(actual, QUERY, 3), {
    pm2_5: { offset: 21103457, length: 615927 }, pm10: { offset: 20296273, length: 807184 },
  });
});

test('malformed, missing, duplicate, foreign run/step, oversized and unbounded inventories fail closed', () => {
  for (const bad of [index().replaceAll('2026101000', '2026100918'), index().replaceAll('3 hour fcst', '6 hour fcst'),
    index().replace('PMTF:surface', 'PMTF:entire atmosphere'), index().replace(' <2.5e-06:', ' <1e-05:'),
    index().replace('2:64:', '2:0:'), index().replace('2:64:', '2:19:'), index().replace('2:64:', '2:-1:'),
    index().replace('2:64:', '8:64:'), index().replace('3:128:', `3:${GEFS_MAX_FIELD_BYTES + 65}:`),
    index().replace(':PMTF:', ':PMTX:'), index().replaceAll('aerosol=Total aerosol:', 'aerosol=Dust dry:'),
    index().split('\n').slice(0, 2).join('\n'), index() + '\n', '\u0000' + index(),
    index() + '4:192:d=2026101000:PMTF:surface:3 hour fcst:aerosol=Total aerosol:aerosol_size <2.5e-06:\n'
      + '5:256:d=2026101000:COLMD:entire atmosphere:3 hour fcst:aerosol=Total aerosol:aerosol_size <1e-05:\n']) {
    assert.throws(() => selectGefsIndex(bad, QUERY, 3));
  }
  assert.throws(() => selectGefsIndex(Buffer.alloc(GEFS_MAX_INDEX_BYTES + 1), QUERY, 3), code('INDEX_TOO_LARGE'));
  assert.throws(() => selectGefsIndex(new Uint8Array([255]), QUERY, 3), code('INDEX_INVALID'));
});

test('native instantaneous concentrations retain values, null, true zero and colocated point without AQI', () => {
  const evidence = { pm2_5: {}, pm10: {} }, sample = sampleFromGefsDecoded(pair(), QUERY, 3, evidence);
  assert.equal(sample.pm2_5, 5.53071); assert.equal(sample.pm10, 11.5959);
  assert.equal(sample.valid_at, '2026-10-10T03:00:00.000Z'); assert.equal(sample.lead_hours, 3);
  assert.deepEqual(sample.grid, { latitude: 52.5, longitude: 13.5, distance_km: 6.48435, method: 'nearest-grid-no-interpolation' });
  const missing = pair(); missing.pm2_5[0].neighbours[0].value = null; missing.pm10[0].neighbours[0].value = 0;
  const result = sampleFromGefsDecoded(missing, QUERY, 3, evidence);
  assert.equal(result.pm2_5, null); assert.equal(result.pm10, 0); assert.equal(Object.hasOwn(result, 'aqi'), false);
});

test('every quantity/run/statistic/aerosol/layer/grid identity is required independently of field labels', () => {
  for (const [key, value] of Object.entries(decoded()[0].keys)) {
    const bad = pair(); bad.pm2_5[0].keys[key] = typeof value === 'string' ? `${value}-wrong` : value + 1;
    // bitmap=1, missing=0 is a legitimate all-present bitmap.
    if (key === 'bitmapPresent') bad.pm2_5[0].keys[key] = 2;
    assert.throws(() => sampleFromGefsDecoded(bad, QUERY, 3, {}), undefined, key);
    const absent = pair(); delete absent.pm2_5[0].keys[key];
    assert.throws(() => sampleFromGefsDecoded(absent, QUERY, 3, {}), undefined, `missing ${key}`);
  }
  const swapped = { pm2_5: decoded('pm10'), pm10: decoded() };
  assert.throws(() => sampleFromGefsDecoded(swapped, QUERY, 3, {}));
  assert.throws(() => sampleFromGefsDecoded({ pm2_5: [], pm10: decoded('pm10') }, QUERY, 3, {}), code('DECODE_MESSAGE_COUNT'));
});

test('bad values, units, nearest point/index, query mismatch and non-colocated fields are rejected', () => {
  for (const change of [{ value: -1 }, { value: NaN }, { value: Infinity }, { value: '0' }, { value: undefined },
    { unit: 'kg m**-3' }, { distance_unit: 'm' }, { distance: 51 }, { distance: -1 }, { index: 216055 },
    { longitude: 13.6 }, { latitude: 52.6 }]) {
    const bad = pair(); Object.assign(bad.pm2_5[0].neighbours[0], change);
    assert.throws(() => sampleFromGefsDecoded(bad, QUERY, 3, {}));
  }
  assert.throws(() => sampleFromGefsDecoded(pair(), { ...QUERY, latitude: 10 }, 3, {}), code('DECODE_QUERY_MISMATCH'));
  const drift = pair(); drift.pm10[0].neighbours[0].distance += 0.01;
  assert.throws(() => sampleFromGefsDecoded(drift, QUERY, 3, {}), code('DECODE_GRID_MISMATCH'));
  const west = pair();
  for (const field of Object.keys(west)) Object.assign(west[field][0].neighbours[0], { longitude: 359.75, index: 217439 });
  assert.equal(sampleFromGefsDecoded(west, { ...QUERY, longitude: -0.24 }, 3, {}).grid.longitude, -0.25);
  const spherical = pair();
  for (const field of Object.keys(spherical)) Object.assign(spherical[field][0].neighbours[0], {
    latitude: 52.75, longitude: 13.25, index: 214613, distance: 16.254 });
  assert.equal(sampleFromGefsDecoded(spherical, { ...QUERY, latitude: 52.62499, longitude: 13.375 }, 3, {}).grid.latitude, 52.75);
});

test('inert end-to-end adapter uses one small index, two exact ranges, pinned bounded child and cleans scratch', async () => {
  await fixture(async (options, parent) => {
    const calls = []; const fetcher = transport();
    options.fetchImpl = (url, config) => { calls.push([url, config.headers.Range]); return fetcher(url, config); };
    const result = await fetchAirQualityForecast(QUERY, options);
    assert.equal(result.schema, 'volparossa.air-quality.forecast.v1');
    assert.deepEqual(result.units, { pm2_5: 'ug/m3', pm10: 'ug/m3' });
    assert.equal(result.samples[0].pm10, 11.5959); assert.equal(result.samples[0].pm2_5, 5.53071);
    assert.equal(result.samples[0].evidence.pm2_5.index_sha256, hash(index()));
    assert.equal(result.samples[0].evidence.pm2_5.field_sha256, hash(grib()));
    assert.equal(result.samples[0].evidence.pm2_5.statistic, 'instant');
    assert.equal(result.samples[0].evidence.pm10.range_start, 0);
    assert.equal(result.source.acquired_at, NOW); assert.equal(result.source.issued_at, null);
    assert.equal(result.freshness.expires_at, '2026-10-10T04:30:00.000Z');
    assert.deepEqual(calls.map(call => call[1]), [undefined, 'bytes=64-127', 'bytes=0-63']);
    assert.deepEqual(await readdir(parent), ['decoder']);
  });
});

test('origin/license, stale/future run, pin, private scratch and pre-abort gates run before HTTP', async () => {
  await fixture(async options => {
    let calls = 0; const fetchImpl = () => { calls++; throw new Error('must not execute'); };
    const controller = new AbortController(); controller.abort();
    for (const changes of [{ mode: undefined }, { acceptDataLicense: false }, { decoderSha256: '0'.repeat(64) },
      { now: '2026-10-13T00:00:00.000Z' }, { now: '2026-10-09T23:59:00.000Z' },
      { signal: controller.signal }, { maxAgeSeconds: 1801 }]) {
      await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, ...changes, fetchImpl }));
    }
    await chmod(options.workDirectory, 0o755);
    await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, fetchImpl }), code('PRIVATE_PARENT_REQUIRED'));
    await chmod(options.workDirectory, 0o700);
    const alias = join(options.workDirectory, 'alias'); await symlink(options.decoder, alias);
    try { await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, decoder: alias, fetchImpl }), code('DECODER_PATH_INVALID')); }
    finally { await rm(alias); }
    assert.equal(calls, 0);
  });
});

test('only the private pinned snapshot executes after source replacement or in-place changes', async () => {
  for (const replace of [false, true]) await fixture(async (options, parent) => {
    const fetcher = transport(), backup = join(parent, 'original-decoder'); let calls = 0;
    options.fetchImpl = async (url, config) => {
      if (calls++ === 0) {
        const names = (await readdir(parent)).filter(name => name.startsWith('noaa-gefs-'));
        assert.equal(names.length, 1);
        const work = join(parent, names[0]), snapshot = join(work, 'decoder', 'grib_ls');
        for (const directory of [work, join(work, 'decoder')]) {
          const info = await stat(directory);
          assert.equal(info.uid, process.getuid()); assert.equal(info.mode & 0o777, 0o700);
        }
        const snapshotFile = await open(snapshot, constants.O_RDONLY | constants.O_NOFOLLOW);
        try {
          assert.equal((await snapshotFile.stat()).mode & 0o777, 0o500);
          assert.equal(hash(await snapshotFile.readFile()), options.decoderSha256);
        } finally { await snapshotFile.close(); }
        await assert.rejects(stat(join(work, 'lib')), { code: 'ENOENT' });
        if (replace) await rename(options.decoder, backup);
        await writeFile(options.decoder,
          `#!/bin/sh\nprintf compromised > '${join(parent, 'executed-unpinned')}'\nexit 7\n`, { mode: 0o700 });
      }
      return fetcher(url, config);
    };
    try {
      const result = await fetchAirQualityForecast(QUERY, options);
      assert.equal(calls, 3); assert.equal(result.samples[0].pm2_5, 5.53071);
      assert.equal(result.samples[0].pm10, 11.5959);
      assert.equal(result.samples[0].evidence.pm2_5.decoder_sha256, options.decoderSha256);
      await assert.rejects(stat(join(parent, 'executed-unpinned')), { code: 'ENOENT' });
    } finally { if (replace) await rename(backup, options.decoder); }
  });
});

test('nonregular, empty, nonexecutable and oversized decoder descriptors fail before HTTP', async () => {
  for (const kind of ['directory', 'empty', 'nonexecutable', 'oversized']) await fixture(async options => {
    if (kind === 'directory') { await rm(options.decoder); await mkdir(options.decoder, { mode: 0o700 }); }
    else if (kind === 'nonexecutable') await chmod(options.decoder, 0o600);
    else {
      const file = await open(options.decoder, 'w');
      try { await file.truncate(kind === 'empty' ? 0 : 64 * 1024 * 1024 + 1); }
      finally { await file.close(); }
    }
    let calls = 0;
    await assert.rejects(fetchAirQualityForecast(QUERY, { ...options,
      fetchImpl: () => { calls++; throw new Error('must not execute'); } }), code('DECODER_PIN_MISMATCH'));
    assert.equal(calls, 0);
  });
});

test('mutation during the bounded descriptor read rejects the pin and closes the opened decoder', async t => {
  await fixture(async options => {
    const probe = await open(options.decoder, 'r'), prototype = Object.getPrototypeOf(probe);
    await probe.close();
    const read = prototype.read; let handle, readCapacity, calls = 0;
    const originalSize = (await stat(options.decoder)).size;
    t.mock.method(prototype, 'read', async function (...args) {
      handle = this; readCapacity = args[0].length;
      await writeFile(options.decoder, '#!/bin/sh\nexit 9\n');
      return Reflect.apply(read, this, args);
    });
    try {
      await assert.rejects(fetchAirQualityForecast(QUERY, { ...options,
        fetchImpl: () => { calls++; throw new Error('must not execute'); } }), code('DECODER_PIN_MISMATCH'));
      assert.equal(calls, 0); assert.equal(readCapacity, originalSize + 1);
      assert.ok(handle); assert.equal(handle.fd, -1);
    } finally { t.mock.restoreAll(); }
  });
});

test('HTTP refuses redirects, full files, wrong ranges, compressed/truncated/oversized bodies and malformed GRIB', async () => {
  await fixture(async options => {
    for (const altered of [
      (url) => response(url.replace('noaa-gefs-pds', 'elsewhere'), '', 200),
      (url) => response(url, '', 403),
      (url) => response(url, index(), 200, { 'Content-Encoding': 'gzip' }),
      (url) => response(url, index(), 200, { 'Content-Length': GEFS_MAX_INDEX_BYTES + 1 }),
      (url) => response(url, Buffer.alloc(GEFS_MAX_INDEX_BYTES + 1)),
      (url) => response(url, index(), 200, { 'Content-Length': 1 }),
    ]) await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, fetchImpl: transport(altered) }));
    for (const altered of [
      url => response(url, grib(), 200),
      url => response(url, grib(), 206, { 'Content-Range': 'bytes 0-63/192' }),
      url => response(url, grib(), 206, { 'Content-Range': 'bytes 64-127/*' }),
      url => response(url, grib(), 206, { 'Content-Range': 'bytes 64-127/127' }),
      url => response(url, grib().subarray(0, 63), 206, { 'Content-Range': 'bytes 64-127/192' }),
      url => response(url, Buffer.alloc(65), 206, { 'Content-Range': 'bytes 64-127/192' }),
      url => response(url, Buffer.alloc(64), 206, { 'Content-Range': 'bytes 64-127/192' }),
    ]) await assert.rejects(fetchAirQualityForecast(QUERY, { ...options,
      fetchImpl: transport(url => url.endsWith('.idx') ? null : altered(url)) }));
  });
});

test('caller abort releases an unfinished HTTP response and removes only owned scratch', async () => {
  await fixture(async (options, parent) => {
    const controller = new AbortController(); let cancel = false;
    options.fetchImpl = async url => {
      setTimeout(() => controller.abort(), 20);
      return response(url, new ReadableStream({ cancel() { cancel = true; } }));
    };
    await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, signal: controller.signal }), code('CANCELLED'));
    assert.equal(cancel, true); assert.deepEqual(await readdir(parent), ['decoder']);
  });
});

test('nonresponsive injected transport cannot defeat cancellation; private errors are not exposed', async () => {
  await fixture(async options => {
    const controller = new AbortController();
    const fetchImpl = () => { setTimeout(() => controller.abort(), 20); return new Promise(() => {}); };
    await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, fetchImpl, signal: controller.signal }), code('CANCELLED'));
    await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, fetchImpl: () => { throw new Error('private URL/token'); } }),
      error => error.code === 'NETWORK_FAILED' && !error.message.includes('private'));
  });
});

test('decoder failure and child cancellation clean fields and process group without raw stderr leakage', async () => {
  await fixture(async options => {
    await assert.rejects(fetchAirQualityForecast(QUERY, options),
      error => error.code === 'CORE_FAILED' && !error.message.includes('private'));
  }, '#!/bin/sh\nprintf private-error >&2\nexit 7\n');
  await fixture(async options => {
    const controller = new AbortController(), started = Date.now();
    const timer = setTimeout(() => controller.abort(), 100);
    try { await assert.rejects(fetchAirQualityForecast(QUERY, { ...options, signal: controller.signal }), code('CANCELLED')); }
    finally { clearTimeout(timer); }
    assert.ok(Date.now() - started < 5000);
  }, '#!/bin/sh\nsleep 30\n');
});
