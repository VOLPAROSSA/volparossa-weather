// SPDX-License-Identifier: GPL-3.0-only
// Deliberately synthetic decoder structures, not upstream acquisition evidence.
import { PRECIPITATION_SOURCES } from '../src/forecast.mjs';
import { forecastFromSamples, sampleWithPrecipitation } from '../src/ecmwf.mjs';
import { QUERY, NOW, EVIDENCE, decoded, windParts } from './fixtures.mjs';

export function precipitationParts(query = { ...QUERY, includePrecipitation: true }, step = query.steps[0],
  { start = 0, value = query.model === 'ifs' ? 0.012 : 12 } = {}) {
  const parts = query.includeWind ? windParts(query, step)
    : { decoded: { '2t': decoded(query, step) }, evidence: { '2t': { ...EVIDENCE } } };
  const source = PRECIPITATION_SOURCES[query.model];
  const tp = decoded(query, step);
  Object.assign(tp[0].keys, { shortName: 'tp', paramId: source.id, typeOfLevel: 'surface', level: 0,
    stepType: 'accum', startStep: start, endStep: step, numberOfTimeRanges: 1, typeOfStatisticalProcessing: 1 });
  delete tp[0].keys.uvRelativeToGrid;
  Object.assign(tp[0].neighbours[0], { unit: source.unit, value });
  parts.decoded.tp = tp;
  parts.evidence.tp = { ...EVIDENCE, parameter: 'tp', unit: source.unit, param_id: source.id,
    statistic: 'accum', range_start: EVIDENCE.range_start + 3 * EVIDENCE.range_length };
  return parts;
}

export function precipitationForecast(input = QUERY, now = NOW, options = {}) {
  const query = { ...input, includePrecipitation: true };
  return forecastFromSamples(query, query.steps.map(step => {
    const parts = precipitationParts(query, step, options);
    return sampleWithPrecipitation(parts.decoded, query, step, parts.evidence);
  }), now);
}
