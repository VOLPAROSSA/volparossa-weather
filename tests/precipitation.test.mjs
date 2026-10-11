// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseForecast, request, validateForecast } from '../src/forecast.mjs';
import { fetchField, fetchFields, forecastFromSamples, sampleWithPrecipitation, selectIndex } from '../src/ecmwf.mjs';
import { QUERY, NOW, forecast, windForecast } from './fixtures.mjs';
import { precipitationParts, precipitationForecast } from './precipitation-fixtures.mjs';

const query = { ...QUERY, includePrecipitation: true };
const code = expected => error => error.code === expected;
const encode = value => Buffer.from(JSON.stringify(value));
function sample(input = query, options) {
  const parts = precipitationParts(input, input.steps[0], options);
  return sampleWithPrecipitation(parts.decoded, input, input.steps[0], parts.evidence);
}

test('precipitation is explicit and independent of wind; legacy outputs keep their shape', () => {
  assert.equal(request(QUERY).includePrecipitation, false);
  assert.equal(request(query).includePrecipitation, true);
  for (const value of [1, null, 'true', [], {}]) {
    assert.throws(() => request({ ...query, includePrecipitation: value }), code('PRECIPITATION_REQUEST_INVALID'));
  }
  for (const original of [forecast(), windForecast()]) {
    assert.equal(Object.hasOwn(original.units, 'precipitation'), false);
    assert.equal(Object.hasOwn(original.samples[0], 'precipitation'), false);
    assert.deepEqual(parseForecast(encode(original)), original);
  }
  const parts = precipitationParts(query);
  assert.throws(() => sampleWithPrecipitation(parts.decoded, QUERY, 12, parts.evidence),
    code('PRECIPITATION_REQUEST_REQUIRED'));
  assert.equal(Object.hasOwn(precipitationForecast().samples[0], 'wind_10m'), false);
  assert.equal(precipitationForecast({ ...QUERY, includeWind: true }).samples[0].wind_10m.speed, 5);
});

test('IFS metres and AIFS kilograms per square metre give model-correct millimetres', () => {
  for (const [model, id, unit, sourceValue] of [['ifs', 228, 'm', 0.012], ['aifs-single', 228228, 'kg m**-2', 12]]) {
    const value = precipitationForecast({ ...query, model });
    const precipitation = value.samples[0].precipitation;
    assert.equal(value.units.precipitation, 'mm');
    assert.equal(precipitation.amount, 12);
    assert.equal(precipitation.source_value, sourceValue);
    assert.equal(precipitation.evidence.param_id, id);
    assert.equal(precipitation.evidence.unit, unit);
    assert.equal(precipitation.evidence.statistic, 'accum');
    assert.deepEqual(parseForecast(encode(value)), value);
    assert.match(value.source.changes, /native windows/);
    for (const includeWind of [false, true]) assert.ok(precipitationForecast({ ...query, model, includeWind }).source.changes.length <= 200);
  }
});

test('native accumulation start/end retained: no inferred hourly amount or differencing', () => {
  const value = precipitationForecast(query, NOW, { start: 6 });
  const precipitation = value.samples[0].precipitation;
  assert.equal(precipitation.start_lead_hours, 6);
  assert.equal(precipitation.end_lead_hours, 12);
  assert.equal(precipitation.start_at, '2026-09-30T18:00:00.000Z');
  assert.equal(precipitation.end_at, value.samples[0].valid_at);
  assert.equal(precipitation.amount, 12);
  // Packing can cause a slightly decreasing cumulative total. Do not invent
  // a monotonic adjustment, an hourly rate, or a negative interval forecast.
  const multi = { ...query, steps: [6, 12] };
  const samples = multi.steps.map((step, i) => {
    const parts = precipitationParts(multi, step, { value: i ? 0.012 : 0.0121 });
    return sampleWithPrecipitation(parts.decoded, multi, step, parts.evidence);
  });
  const result = forecastFromSamples(multi, samples, NOW);
  assert.deepEqual(result.samples.map(item => item.precipitation.start_lead_hours), [0, 0]);
  assert.deepEqual(result.samples.map(item => item.precipitation.amount), [12.1, 12]);
  assert.deepEqual(result.samples.map(item => item.lead_hours), [6, 12]);
});

test('null is missing, genuine zero remains zero, zero-length only at genuine model start', () => {
  for (const value of [0, null]) {
    const result = precipitationForecast(query, NOW, { value });
    assert.equal(result.samples[0].precipitation.amount, value);
    assert.equal(result.samples[0].precipitation.source_value, value);
    const initial = precipitationForecast({ ...query, steps: [0] }, NOW, { value });
    assert.equal(initial.samples[0].precipitation.start_at, query.run);
    assert.equal(initial.samples[0].precipitation.end_at, query.run);
  }
  assert.throws(() => sample({ ...query, steps: [0] }, { value: 1 }), code('DECODE_VALUE_INVALID'));
  for (const start of [-1, 12, 15, 0.5, NaN, null]) {
    assert.throws(() => sample(query, { start }), code('DECODE_ACCUMULATION_INVALID'));
  }
});

test('precipitation decoder rejects another model identity, unit, statistic, window and level', () => {
  const mutations = [
    keys => keys.paramId = 228228, keys => keys.shortName = 'cp', keys => keys.typeOfLevel = 'heightAboveGround',
    keys => keys.level = 2, keys => keys.stepType = 'instant', keys => keys.stepUnits = 0,
    keys => keys.endStep = 9, keys => keys.dataDate = 20260929, keys => keys.validityTime = 1200,
    keys => keys.typeOfStatisticalProcessing = 0, keys => keys.numberOfTimeRanges = 2,
    keys => delete keys.numberOfTimeRanges, keys => keys.class = 'ai',
  ];
  for (const mutate of mutations) {
    const parts = precipitationParts(query); mutate(parts.decoded.tp[0].keys);
    assert.throws(() => sampleWithPrecipitation(parts.decoded, query, 12, parts.evidence));
  }
  for (const value of [-1, Infinity, NaN, '0', undefined, Number.MAX_VALUE]) {
    const parts = precipitationParts(query); parts.decoded.tp[0].neighbours[0].value = value;
    assert.throws(() => sampleWithPrecipitation(parts.decoded, query, 12, parts.evidence));
  }
  const parts = precipitationParts(query); parts.decoded.tp[0].neighbours[0].unit = 'kg m**-2';
  assert.throws(() => sampleWithPrecipitation(parts.decoded, query, 12, parts.evidence), code('DECODE_UNITS_INVALID'));
});

test('temperature, wind and precipitation must be truly co-located on the same grid', () => {
  for (const includeWind of [false, true]) for (const mutate of [
    part => part.keys.iDirectionIncrementInDegrees = 0.5,
    part => part.keys.Nj = 360,
    part => part.neighbours[0].longitude += 0.25,
    part => part.neighbours[0].distance += 0.1,
  ]) {
    const input = { ...query, includeWind }, parts = precipitationParts(input);
    mutate(parts.decoded.tp[0]);
    assert.throws(() => sampleWithPrecipitation(parts.decoded, input, 12, parts.evidence));
  }
});

test('forecast validator binds conversion, evidence, exact windows and complete optional field sets', () => {
  const mutations = [
    result => result.samples[0].precipitation.amount = 11,
    result => result.samples[0].precipitation.source_value = null,
    result => result.samples[0].precipitation.amount = null,
    result => result.samples[0].precipitation.amount = Infinity,
    result => result.samples[0].precipitation.start_at = result.samples[0].valid_at,
    result => result.samples[0].precipitation.end_at = query.run,
    result => result.samples[0].precipitation.start_lead_hours = 12,
    result => result.samples[0].precipitation.end_lead_hours = 9,
    result => result.samples[0].precipitation.evidence.param_id = 228228,
    result => result.samples[0].precipitation.evidence.unit = 'kg m**-2',
    result => result.samples[0].precipitation.evidence.statistic = 'instant',
    result => result.samples[0].precipitation.evidence.decoder_sha256 = 'd'.repeat(64),
    result => result.samples[0].precipitation.evidence.index_sha256 = 'd'.repeat(64),
    result => result.samples[0].precipitation.evidence.range_start = result.samples[0].evidence.range_start,
    result => result.samples[0].precipitation.evidence.range_start = result.samples[0].wind_10m.evidence.eastward.range_start,
    result => result.source.model = 'aifs-single',
    result => result.source.model = 'constructor',
    result => result.units.precipitation = 'mm/h',
    result => delete result.units.precipitation,
    result => delete result.samples[0].precipitation,
    result => result.samples[0].precipitation.rate = 1,
    result => result.samples[0].evidence.param_id = 167,
  ];
  for (const mutate of mutations) {
    const value = precipitationForecast({ ...query, includeWind: true }); mutate(value);
    assert.throws(() => validateForecast(value));
  }
});

const grib = () => { const bytes = Buffer.alloc(64); bytes.write('GRIB'); bytes[7] = 2;
  bytes.writeBigUInt64BE(64n, 8); bytes.write('7777', 60); return bytes; };
const records = input => ['2t', '10u', '10v', 'tp'].map((param, i) => ({ date: '20260930', time: '1200', step: '12',
  param, levtype: 'sfc', class: input.model === 'ifs' ? 'od' : 'ai', stream: 'oper', type: 'fc', expver: '0001',
  _offset: i * 64, _length: 64 }));
function fetcher(input, calls, rows = records(input)) {
  return async (url, options) => {
    calls.push({ url, options });
    const index = url.endsWith('.index');
    const body = index ? rows.map(item => JSON.stringify(item)).join('\n') : grib();
    const headers = index ? {} : { 'content-range': options.headers.Range.replace('=', ' ') + '/256' };
    const response = new Response(body, { status: index ? 200 : 206, headers });
    Object.defineProperty(response, 'url', { value: url });
    return response;
  };
}

test('one shared bounded index and exactly one extra GRIB range, independent of wind', async () => {
  for (const model of ['ifs', 'aifs-single']) for (const includeWind of [false, true]) {
    const input = { ...query, model, includeWind }, calls = [];
    const result = await fetchFields(input, 12, { mode: 'origin', acceptDataLicense: true, fetcher: fetcher(input, calls) });
    assert.deepEqual(Object.keys(result), ['2t', ...(includeWind ? ['10u', '10v'] : []), 'tp']);
    assert.equal(calls.length, includeWind ? 5 : 3);
    assert.equal(calls.filter(call => call.url.endsWith('.index')).length, 1);
    assert.equal(calls.at(-1).options.headers.Range, 'bytes=192-255');
    assert.ok(calls.every(call => !call.url.includes(String(input.latitude)) && !call.url.includes(String(input.longitude))));
  }
  const calls = [];
  await fetchField({ ...query, includeWind: true }, 12,
    { mode: 'origin', acceptDataLicense: true, fetcher: fetcher(query, calls) });
  assert.equal(calls.length, 2, 'legacy single-field helper remains temperature-only');
});

test('requested missing/ambiguous precipitation fails before field downloads; index is not temporal authority', async () => {
  for (const rows of [records(query).slice(0, 3), [...records(query), records(query)[3]]]) {
    const calls = [];
    await assert.rejects(fetchFields(query, 12,
      { mode: 'origin', acceptDataLicense: true, fetcher: fetcher(query, calls, rows) }), code('FIELD_MISSING_OR_AMBIGUOUS'));
    assert.equal(calls.length, 1);
  }
  const index = records(query)[3];
  assert.deepEqual(selectIndex(encode(index), query, 12, 'tp'), { offset: 192, length: 64 });
  // MARS-style index step is the endpoint. Any alternate range encoding needs
  // explicit support/evidence, not silently parsing it as a duration.
  assert.throws(() => selectIndex(encode({ ...index, step: '0-12' }), query, 12, 'tp'));
  const calls = [];
  await assert.rejects(fetchFields(query, 12, { fetcher: fetcher(query, calls) }), code('ORIGIN_MODE_REQUIRED'));
  assert.equal(calls.length, 0);
});
