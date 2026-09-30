// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_BYTES, freshness, parseForecast, request, validateForecast } from '../src/forecast.mjs';
import { MAX_FIELD_BYTES, checkGrib, ecmwfRequest, fieldUrl, fetchField, forecastFromSamples,
  sampleFromDecoded, selectIndex } from '../src/ecmwf.mjs';
import { QUERY, NOW, EVIDENCE, decoded, forecast } from './fixtures.mjs';

const code = expected => error => error.code === expected;
const indexRecord = () => ({ date: '20260930', time: '1200', step: '12', param: '2t', levtype: 'sfc',
  class: 'od', stream: 'oper', type: 'fc', expver: '0001', _offset: 1234, _length: 64 });
const encode = value => Buffer.from(JSON.stringify(value));
const grib = () => { const bytes = Buffer.alloc(64); bytes.write('GRIB'); bytes[7] = 2;
  bytes.writeBigUInt64BE(64n, 8); bytes.write('7777', 60); return bytes; };

test('explicit run URLs reveal no location; IFS and AIFS cadence is not made hourly', () => {
  const url = fieldUrl(QUERY, 12, 'grib2');
  assert.equal(url, 'https://data.ecmwf.int/forecasts/20260930/12z/ifs/0p25/oper/20260930120000-12h-oper-fc.grib2');
  assert.equal(url.includes('52.52'), false);
  assert.match(fieldUrl({ ...QUERY, run: '2026-09-30T06:00:00.000Z' }, 12, 'index'), /06z\/ifs\/0p25\/oper/);
  assert.match(fieldUrl({ ...QUERY, model: 'aifs-single' }, 12, 'index'), /aifs-single/);
  assert.throws(() => ecmwfRequest({ ...QUERY, steps: [1] }), code('ECMWF_STEP_UNSUPPORTED'));
  assert.throws(() => ecmwfRequest({ ...QUERY, model: 'aifs-single', steps: [3] }), code('ECMWF_STEP_UNSUPPORTED'));
  assert.deepEqual(ecmwfRequest({ ...QUERY, steps: [144, 150, 360] }).steps, [144, 150, 360]);
  assert.deepEqual(ecmwfRequest({ ...QUERY, run: '2026-09-30T06:00:00.000Z', steps: [96, 144] }).steps, [96, 144]);
  assert.throws(() => ecmwfRequest({ ...QUERY, run: '2026-09-30T06:00:00.000Z', steps: [150] }));
  assert.throws(() => ecmwfRequest({ ...QUERY, steps: [147] }));
  assert.deepEqual(ecmwfRequest({ ...QUERY, model: 'aifs-single', steps: [0, 6, 360] }).steps, [0, 6, 360]);
  assert.throws(() => ecmwfRequest({ ...QUERY, run: '2026-05-12T12:00:00.000Z' }));
  assert.equal(ecmwfRequest({ ...QUERY, run: '2026-05-13T00:00:00.000Z' }).model, 'ifs');
  assert.throws(() => ecmwfRequest({ ...QUERY, run: '2026-01-01T00:00:00.000Z' }));
});

test('index selection requires exactly one exact run/parameter/step and bounded range', () => {
  assert.deepEqual(selectIndex(encode(indexRecord()), QUERY, 12), { offset: 1234, length: 64 });
  for (const changes of [{ date: '20260929' }, { time: '0000' }, { class: 'ai' }, { step: '15' },
    { type: 'pf' }, { stream: 'scda' }, { _length: MAX_FIELD_BYTES + 1 }, { _offset: -1 }, { _offset: '1234' }]) {
    assert.throws(() => selectIndex(encode({ ...indexRecord(), ...changes }), QUERY, 12));
  }
  assert.throws(() => selectIndex(Buffer.from(`${JSON.stringify(indexRecord())}\n${JSON.stringify(indexRecord())}`), QUERY, 12), code('FIELD_MISSING_OR_AMBIGUOUS'));
  assert.throws(() => selectIndex(encode({ ...indexRecord(), param: 'tp' }), QUERY, 12), code('FIELD_MISSING_OR_AMBIGUOUS'));
});

test('GRIB2 envelope must be exactly the indexed complete single message', () => {
  checkGrib(grib(), 64);
  for (const mutate of [b => b[7] = 1, b => b[63] = 0, b => b.writeBigUInt64BE(65n, 8)]) {
    const bytes = grib(); mutate(bytes); assert.throws(() => checkGrib(bytes, 64));
  }
});

test('actual decoder-shaped result yields Celsius with run, valid time and missingness preserved', () => {
  const result = forecast();
  assert.equal(result.samples[0].temperature_2m, 10);
  assert.equal(result.samples[0].valid_at, '2026-10-01T00:00:00.000Z');
  assert.equal(result.source.model_run_at, QUERY.run); assert.equal(result.source.issued_at, null);
  assert.equal(result.samples[0].lead_hours, 12);
  const missing = decoded(); missing[0].neighbours[0].value = null;
  assert.equal(sampleFromDecoded(missing, QUERY, 12, EVIDENCE).temperature_2m, null);
  assert.deepEqual(parseForecast(encode(result)), result);
});

test('mismatched native message or accumulated quantity cannot masquerade as 2m instantaneous temperature', () => {
  for (const changes of [{ shortName: 'tp' }, { paramId: 130 }, { level: 850 }, { dataDate: 20260929 },
    { validityTime: 1200 }, { stepType: 'accum' }, { endStep: 15 }, { class: 'ai' }, { stepUnits: 0 }]) {
    const bad = decoded(); Object.assign(bad[0].keys, changes);
    assert.throws(() => sampleFromDecoded(bad, QUERY, 12, EVIDENCE), code('DECODE_IDENTITY_MISMATCH'));
  }
  const bad = decoded(); bad[0].neighbours[0].unit = 'degC';
  assert.throws(() => sampleFromDecoded(bad, QUERY, 12, EVIDENCE), code('DECODE_UNITS_INVALID'));
  assert.throws(() => sampleFromDecoded([...decoded(), ...decoded()], QUERY, 12, EVIDENCE), code('DECODE_MESSAGE_COUNT'));
});

test('model age/acquisition age/publication expiry remain separate; cache does not rejuvenate', () => {
  const value = forecast();
  assert.equal(freshness(value, NOW).model_age_seconds, 9 * 3600);
  assert.equal(freshness(value, '2026-09-30T21:30:00.000Z').stale, true);
  assert.equal(freshness(value, '2026-09-30T21:10:00.000Z', '2026-09-30T21:05:00.000Z').stale, true);
  assert.throws(() => freshness(value, '2026-09-30T20:59:59.000Z'), code('CLOCK_BEFORE_ACQUISITION'));
  value.freshness.expires_at = '2026-09-30T22:00:00.000Z';
  assert.throws(() => validateForecast(value), code('EXPIRY_INVALID'));
  assert.throws(() => forecastFromSamples(QUERY, forecast().samples, '2026-10-04T00:00:00.000Z'), code('RUN_AGE_INVALID'));
});

test('inert contract rejects nonfinite values, unsupported units, invalid coordinates and body sizes', () => {
  for (const changes of [{ latitude: NaN }, { latitude: '52.52' }, { longitude: 181 }, { steps: [12, 12] }]) {
    assert.throws(() => request({ ...QUERY, ...changes }));
  }
  const value = forecast(); value.samples[0].temperature_2m = NaN;
  assert.throws(() => validateForecast(value));
  assert.throws(() => parseForecast(new Uint8Array(MAX_BYTES + 1)), code('BODY_TOO_LARGE'));
});

function response(url, body, status, headers = {}) {
  const result = new Response(body, { status, headers }); Object.defineProperty(result, 'url', { value: url }); return result;
}
test('one exact index + one field request; refuses full-file or mismatched Range fallback', async () => {
  let calls = 0;
  const fetcher = async (url, options) => {
    calls++; assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error');
    if (url.endsWith('.index')) return response(url, encode(indexRecord()), 200);
    assert.equal(options.headers.Range, 'bytes=1234-1297');
    return response(url, grib(), 206, { 'content-range': 'bytes 1234-1297/9999' });
  };
  const result = await fetchField(QUERY, 12, { mode: 'origin', acceptDataLicense: true, fetcher });
  assert.equal(calls, 2); assert.equal(result.field.length, 64);
  for (const bad of [{ status: 200 }, { status: 206, range: 'bytes 0-63/9999' }]) {
    await assert.rejects(fetchField(QUERY, 12, { mode: 'origin', acceptDataLicense: true,
      fetcher: async url => url.endsWith('.index') ? response(url, encode(indexRecord()), 200)
        : response(url, grib(), bad.status, { 'content-range': bad.range ?? '' }) }));
  }
});

test('no network before explicit origin/license consent; cancellation blocks request', async () => {
  let calls = 0; const fetcher = () => { calls++; throw new Error('must not execute'); };
  await assert.rejects(fetchField(QUERY, 12, { fetcher }), code('ORIGIN_MODE_REQUIRED'));
  await assert.rejects(fetchField(QUERY, 12, { mode: 'origin', fetcher }), code('DATA_LICENSE_REQUIRED'));
  const controller = new AbortController(); controller.abort();
  await assert.rejects(fetchField(QUERY, 12, { mode: 'origin', acceptDataLicense: true, signal: controller.signal, fetcher }), code('CANCELLED'));
  assert.equal(calls, 0);
});
