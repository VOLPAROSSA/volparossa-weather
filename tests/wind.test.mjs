// SPDX-License-Identifier: GPL-3.0-only
// Synthetic wire/model contracts; only the recorded native smoke is live model evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseForecast, request, validateForecast, windVector } from '../src/forecast.mjs';
import { fetchFields, sampleWithWind } from '../src/ecmwf.mjs';
import { QUERY, forecast, windParts, windForecast } from './fixtures.mjs';

const query = { ...QUERY, includeWind: true };
const parameters = ['2t', '10u', '10v'];
const code = expected => error => error.code === expected;

test('opt-in leaves default temperature v1 shape untouched and wind roundtrips', () => {
  assert.equal(request(QUERY).includeWind, false);
  assert.throws(() => request({ ...QUERY, includeWind: 'yes' }), code('WIND_REQUEST_INVALID'));
  const temperature = forecast();
  assert.deepEqual(Object.keys(temperature.units), ['temperature_2m']);
  assert.equal(Object.hasOwn(temperature.samples[0], 'wind_10m'), false);
  const wind = windForecast();
  assert.equal(wind.schema, temperature.schema);
  assert.deepEqual(parseForecast(Buffer.from(JSON.stringify(wind))), wind);
  assert.equal(wind.samples[0].wind_10m.speed, 5);
  assert.equal(wind.samples[0].wind_10m.status, 'available');
});

test('meteorological direction is FROM true north, clockwise, not travel bearing', () => {
  for (const [u, v, expected] of [[0, -1, 0], [-1, 0, 90], [0, 1, 180], [1, 0, 270],
    [-1, -1, 45], [-1, 1, 135], [1, 1, 225], [1, -1, 315]]) {
    assert.equal(windVector(u, v).direction_from, expected);
  }
  assert.equal(windVector(3, 4).speed, 5);
  for (const value of [NaN, Infinity, '0', undefined]) assert.throws(() => windVector(value, 0));
});

test('missing component stays null; actual calm has zero speed and no invented north direction', () => {
  assert.deepEqual(windVector(null, 3), { eastward: null, northward: 3, speed: null, direction_from: null, status: 'missing' });
  assert.deepEqual(windVector(0, 0), { eastward: 0, northward: 0, speed: 0, direction_from: null, status: 'calm' });
  for (const [u, v] of [[null, 3], [null, null], [0, 0]]) {
    const { decoded, evidence } = windParts();
    decoded['10u'][0].neighbours[0].value = u; decoded['10v'][0].neighbours[0].value = v;
    assert.deepEqual(sampleWithWind(decoded, query, 12, evidence).wind_10m,
      { ...windVector(u, v), evidence: { eastward: evidence['10u'], northward: evidence['10v'] } });
  }
});

test('wind joins only matching run, lead, validity, parameter, height, earth-relative orientation and whole grid', () => {
  for (const change of [{ paramId: 165 }, { shortName: '10u' }, { level: 100 }, { validityDate: 20261002 },
    { endStep: 15 }, { dataTime: 0 }, { uvRelativeToGrid: 1 }, { Ni: 720 },
    { longitudeOfFirstGridPointInDegrees: 0 }, { jScansPositively: 1 }]) {
    const { decoded, evidence } = windParts(); Object.assign(decoded['10v'][0].keys, change);
    assert.throws(() => sampleWithWind(decoded, query, 12, evidence));
  }
  for (const change of [{ latitude: 52.75 }, { distance: 10 }, { unit: 'knots' }]) {
    const { decoded, evidence } = windParts(); Object.assign(decoded['10u'][0].neighbours[0], change);
    assert.throws(() => sampleWithWind(decoded, query, 12, evidence));
  }
});

test('signed cached wind still rejects invented speed/direction, missingness, mixed index or overlapping ranges', () => {
  for (const change of [value => value.samples[0].wind_10m.speed = 6,
    value => value.samples[0].wind_10m.direction_from += 180,
    value => value.samples[0].wind_10m.eastward = null,
    value => value.samples[0].wind_10m.evidence.eastward.index_sha256 = 'f'.repeat(64),
    value => value.samples[0].wind_10m.evidence.northward.range_start = 1234,
    value => delete value.samples[0].wind_10m,
    value => delete value.units.wind_direction_10m]) {
    const value = windForecast(); change(value); assert.throws(() => validateForecast(value));
  }
});

function records() {
  return parameters.map((param, i) => ({ date: '20260930', time: '1200', step: '12', param, levtype: 'sfc',
    class: 'od', stream: 'oper', type: 'fc', expver: '0001', _offset: 1234 + i * 64, _length: 64 }));
}
function index(items) { return items.map(item => JSON.stringify(item)).join('\n'); }
function response(url, bytes, status, headers = {}) {
  const value = new Response(bytes, { status, headers }); Object.defineProperty(value, 'url', { value: url }); return value;
}
function field() {
  const bytes = Buffer.alloc(64); bytes.write('GRIB'); bytes[7] = 2; bytes.writeBigUInt64BE(64n, 8); bytes.write('7777', 60);
  return bytes;
}
test('wind fetch shares one official index, then exactly three bounded HTTP 206 ranges', async () => {
  const calls = [];
  const result = await fetchFields(query, 12, { mode: 'origin', acceptDataLicense: true, fetcher: async (url, options) => {
    calls.push([url, options.headers.Range]);
    if (url.endsWith('.index')) return response(url, index(records()), 200);
    return response(url, field(), 206, { 'content-range': options.headers.Range.replace('=', ' ') + '/9999' });
  } });
  assert.equal(calls.length, 4);
  assert.deepEqual(calls.slice(1).map(item => item[1]), ['bytes=1234-1297', 'bytes=1298-1361', 'bytes=1362-1425']);
  assert.deepEqual(Object.keys(result), parameters);
  assert.equal(new Set(Object.values(result).map(item => item.indexSha256)).size, 1);
});

test('missing, duplicate, overlapping or mismatched wind fields fail before any payload download', async () => {
  for (const items of [records().slice(0, 2), [...records(), records()[1]],
    records().map((value, i) => i === 2 ? { ...value, _offset: 1234 } : value),
    records().map((value, i) => i === 1 ? { ...value, step: '15' } : value)]) {
    let calls = 0;
    await assert.rejects(fetchFields(query, 12, { mode: 'origin', acceptDataLicense: true, fetcher: async url => {
      calls++; assert.ok(url.endsWith('.index')); return response(url, index(items), 200);
    } }));
    assert.equal(calls, 1);
  }
});
