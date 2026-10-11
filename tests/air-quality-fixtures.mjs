// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic concentrations and hashes, not NOAA observations/evidence.
import { airQualityForecastFromSamples, airQualityRequest } from '../src/air-quality.mjs';
export const AQ_NOW = '2026-10-11T01:00:00.000Z';
export const AQ_QUERY = Object.freeze({ latitude: 52.52, longitude: 13.41,
  run: '2026-10-10T00:00:00.000Z', steps: [3, 6, 12], communityArea: true });
export function aqSamples(query = AQ_QUERY) {
  return query.steps.map((step, i) => ({
    valid_at: new Date(Date.parse(query.run) + step * 3600000).toISOString(), lead_hours: step,
    pm2_5: [null, 0, 5.53071][i % 3], pm10: [11.5959, null, 0][i % 3],
    grid: { latitude: 52.5, longitude: 13.5, distance_km: 6.48435, method: 'nearest-grid-no-interpolation' },
    evidence: Object.fromEntries(['pm2_5', 'pm10'].map((field, index) => [field, {
      index_sha256: 'a'.repeat(64), field_sha256: (index ? 'b' : 'c').repeat(64),
      decoder_sha256: 'd'.repeat(64), range_start: 100 + index * 100, range_length: 64,
    }])),
  }));
}
export function aqForecast(query = AQ_QUERY, now = AQ_NOW) {
  return airQualityForecastFromSamples({ query: airQualityRequest(query), samples: aqSamples(query), acquiredAt: now });
}
