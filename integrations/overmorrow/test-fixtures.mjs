// SPDX-License-Identifier: GPL-3.0-only
// Synthetic contract samples only; never model-origin or distributed-delivery evidence.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { fixtureQuery, fixtureForecast, fixtureAirQualityQuery } from '../drizzli/browser-fixture.mjs';
import { toProviderForecast } from '../../src/provider.mjs';
import { freshness } from '../../src/forecast.mjs';
import { toAirQualityProviderForecast } from '../../src/air-quality-provider.mjs';
import { airQualityFreshness } from '../../src/air-quality.mjs';
import { aqForecast } from '../../tests/air-quality-fixtures.mjs';

export function syntheticProducts(now = '2026-10-11T01:00:00.000Z') {
  const run = new Date(now); run.setUTCHours(0, 0, 0, 0);
  const query = fixtureQuery(run.toISOString(), true);
  const weatherForecast = fixtureForecast(query, now);
  const qualityForecast = aqForecast(fixtureAirQualityQuery(query), now);
  const publicationExpires = new Date(Date.parse(now) + 120000).toISOString();
  function project(forecast, quality) {
    const name = quality ? 'synthetic-browser-air-quality' : 'synthetic-browser-forecast';
    const projection = (quality ? toAirQualityProviderForecast : toProviderForecast)(forecast, {
      variables: quality ? ['pm2_5', 'pm10'] : ['temperature_2m', 'wind_speed_10m',
        'wind_direction_10m', 'precipitation', 'air_quality'], now, publicationExpires });
    return { ...projection, delivery: { mode: 'core-cache', publisher_key: '1'.repeat(64), name,
      revision: 1, manifest_id: (quality ? '4' : '2').repeat(64), sha256: (quality ? '5' : '3').repeat(64),
      publication_expires_at: publicationExpires,
      freshness: (quality ? airQualityFreshness : freshness)(forecast, now, publicationExpires),
      upstream_origin_attested: false, manifest_media_type_checked: false } };
  }
  return { now, weather: project(weatherForecast, false), air_quality: project(qualityForecast, true) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  assert.equal(process.argv.length, 3, 'supply a new test fixture output path');
  await writeFile(process.argv[2], JSON.stringify(syntheticProducts(), null, 2) + '\n', { flag: 'wx', mode: 0o600 });
}
