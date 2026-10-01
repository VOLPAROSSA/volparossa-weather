// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic structures, never saved as upstream model evidence.
import { forecastFromSamples, sampleFromDecoded, sampleWithWind } from '../src/ecmwf.mjs';
export const NOW = '2026-09-30T21:00:00.000Z';
export const QUERY = { latitude: 52.52, longitude: 13.41, model: 'ifs',
  run: '2026-09-30T12:00:00.000Z', steps: [12], communityArea: true };
export const EVIDENCE = { index_sha256: 'a'.repeat(64), field_sha256: 'b'.repeat(64), decoder_sha256: 'c'.repeat(64),
  parameter: '2t', unit: 'K', statistic: 'instant', resolution: '0p25', range_start: 1234, range_length: 64 };
export function decoded(query = QUERY, step = query.steps[0], parameter = '2t') {
  const valid = new Date(Date.parse(query.run) + step * 3600000).toISOString();
  return [{ keys: { edition: 2, centre: 'ecmf', shortName: parameter, paramId: { '2t': 167, '10u': 165, '10v': 166 }[parameter],
    dataDate: Number(query.run.slice(0, 10).replaceAll('-', '')), dataTime: Number(query.run.slice(11, 13)) * 100,
    validityDate: Number(valid.slice(0, 10).replaceAll('-', '')), validityTime: Number(valid.slice(11, 13)) * 100,
    stepType: 'instant', startStep: step, endStep: step, stepUnits: 1,
    typeOfLevel: 'heightAboveGround', level: parameter === '2t' ? 2 : 10, gridType: 'regular_ll',
    Ni: 1440, Nj: 721, latitudeOfFirstGridPointInDegrees: 90, longitudeOfFirstGridPointInDegrees: 180,
    latitudeOfLastGridPointInDegrees: -90, longitudeOfLastGridPointInDegrees: 179.75,
    iDirectionIncrementInDegrees: 0.25, jDirectionIncrementInDegrees: 0.25,
    iScansNegatively: 0, jScansPositively: 0, jPointsAreConsecutive: 0, uvRelativeToGrid: 0,
    class: query.model === 'ifs' ? 'od' : 'ai', stream: 'oper', type: 'fc' },
  method: 'nearest', neighbours: [{ latitude: 52.5, longitude: 13.5, distance: 6.5, distance_unit: 'km',
    unit: parameter === '2t' ? 'K' : 'm s**-1', value: { '2t': 283.15, '10u': 3, '10v': 4 }[parameter] }] }];
}
export function windParts(query = { ...QUERY, includeWind: true }, step = query.steps[0]) {
  const parameters = ['2t', '10u', '10v'];
  return { decoded: Object.fromEntries(parameters.map(parameter => [parameter, decoded(query, step, parameter)])),
    evidence: Object.fromEntries(parameters.map((parameter, i) => [parameter, { ...EVIDENCE, parameter,
      unit: parameter === '2t' ? 'K' : 'm s**-1', range_start: 1234 + i * 64 }])) };
}
export function windForecast(query = { ...QUERY, includeWind: true }, now = NOW) {
  const request = { ...query, includeWind: true };
  return forecastFromSamples(request, request.steps.map(step => {
    const { decoded, evidence } = windParts(request, step);
    return sampleWithWind(decoded, request, step, evidence);
  }), now);
}
export function forecast(query = QUERY, now = NOW) {
  return forecastFromSamples(query, query.steps.map(step => sampleFromDecoded(decoded(query, step), query, step, { ...EVIDENCE })), now);
}
