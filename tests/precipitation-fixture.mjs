// SPDX-License-Identifier: GPL-3.0-only
// Synthetic accumulated amounts for adapter/UI tests, not upstream evidence.
import { forecast, windForecast, QUERY, NOW } from './fixtures.mjs';

export function precipitationForecast(query = QUERY, now = NOW) {
  const base = { ...query, includePrecipitation: false };
  const value = query.includeWind ? windForecast(base, now) : forecast(base, now);
  const ifs = query.model === 'ifs';
  value.units.precipitation = 'mm';
  for (const [i, sample] of value.samples.entries()) {
    const sourceValue = sample.lead_hours === 0 ? 0 : ifs ? (i + 1) / 1000 : i + 1;
    sample.precipitation = {
      amount: sourceValue * (ifs ? 1000 : 1), source_value: sourceValue,
      start_lead_hours: 0, end_lead_hours: sample.lead_hours,
      start_at: query.run, end_at: sample.valid_at,
      evidence: { ...sample.evidence, parameter: 'tp', param_id: ifs ? 228 : 228228,
        unit: ifs ? 'm' : 'kg m**-2', statistic: 'accum',
        range_start: sample.evidence.range_start + (query.includeWind ? 3 : 1) * 64 },
    };
  }
  return value;
}
