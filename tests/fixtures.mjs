// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic structures, never saved as upstream model evidence.
import { forecastFromSamples, sampleFromDecoded } from '../src/ecmwf.mjs';
export const NOW = '2026-09-30T21:00:00.000Z';
export const QUERY = { latitude: 52.52, longitude: 13.41, model: 'ifs',
  run: '2026-09-30T12:00:00.000Z', steps: [12], communityArea: true };
export const EVIDENCE = { index_sha256: 'a'.repeat(64), field_sha256: 'b'.repeat(64), decoder_sha256: 'c'.repeat(64),
  parameter: '2t', unit: 'K', statistic: 'instant', resolution: '0p25', range_start: 1234, range_length: 64 };
export function decoded(query = QUERY, step = query.steps[0]) {
  const valid = new Date(Date.parse(query.run) + step * 3600000).toISOString();
  return [{ keys: { edition: 2, centre: 'ecmf', shortName: '2t', paramId: 167,
    dataDate: Number(query.run.slice(0, 10).replaceAll('-', '')), dataTime: Number(query.run.slice(11, 13)) * 100,
    validityDate: Number(valid.slice(0, 10).replaceAll('-', '')), validityTime: Number(valid.slice(11, 13)) * 100,
    stepType: 'instant', startStep: step, endStep: step, stepUnits: 1,
    typeOfLevel: 'heightAboveGround', level: 2, gridType: 'regular_ll',
    class: query.model === 'ifs' ? 'od' : 'ai', stream: 'oper', type: 'fc' },
  method: 'nearest', neighbours: [{ latitude: 52.5, longitude: 13.5, distance: 6.5, distance_unit: 'km', unit: 'K', value: 283.15 }] }];
}
export function forecast(query = QUERY, now = NOW) {
  return forecastFromSamples(query, query.steps.map(step => sampleFromDecoded(decoded(query, step), query, step, { ...EVIDENCE })), now);
}
