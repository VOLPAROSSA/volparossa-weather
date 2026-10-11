// SPDX-License-Identifier: GPL-3.0-only
import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { mkdtemp, cp, copyFile, rm, mkdir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { forecast, windForecast, NOW, QUERY } from '../../tests/fixtures.mjs';
import { precipitationForecast } from '../../tests/precipitation-fixture.mjs';
import { toProviderForecast } from '../../src/provider.mjs';

const root = resolve(import.meta.dirname, '../..');
await mkdir(join(root, 'build'), { recursive: true });
const work = await mkdtemp(join(root, 'build/drizzli-client-test-'));
await cp(join(import.meta.dirname, 'overlay/src/lib/services/volparossa'), work, { recursive: true });
for (const file of ['provider.mjs', 'forecast.mjs']) await copyFile(join(root, 'src', file), join(work, file));
const { validateProvider, displayValue, displayAccumulationWindow, hasSupportedPrecipitation,
  fetchProvider, MAX_PROVIDER_BYTES } = await import(pathToFileURL(join(work, 'client.mjs')));
after(() => rm(work, { recursive: true }));

function response(source = windForecast(), now = NOW) {
  const expiry = new Date(Date.parse(now) + 600000).toISOString();
  return { ...toProviderForecast(source, { now, publicationExpires: expiry,
    variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m', 'precipitation', 'air_quality'] }),
  delivery: { mode: 'core-cache', publication_expires_at: expiry,
    upstream_origin_attested: false, manifest_media_type_checked: false } };
}

test('native points and units survive with no interpolation or current-weather claim', () => {
  const value = response(windForecast({ ...QUERY, steps: [3, 9, 24] }));
  const accepted = validateProvider(value, NOW);
  assert.deepEqual(accepted.timeline.valid_at, value.forecast.samples.map(s => s.valid_at));
  assert.equal(accepted.timeline.valid_at.length, 3);
  assert.equal(displayValue(accepted, 'temperature_2m', 0), '10.0');
  assert.equal(displayValue(accepted, 'wind_speed_10m', 0), '5.0');
  assert.equal(accepted.capabilities.current_observations, false);
});

test('unsupported precipitation and AQI do not become zero', () => {
  const value = validateProvider(response(forecast()), NOW);
  assert.equal(displayValue(value, 'wind_speed_10m', 0), 'Not available');
  assert.equal(displayValue(value, 'precipitation', 0), 'Not available');
  assert.equal(displayValue(value, 'air_quality', 0), 'Not available');
  assert.equal(hasSupportedPrecipitation(value), false);
  assert.equal(displayAccumulationWindow(value, 0), 'Not available');
});

test('precipitation keeps source accumulation windows, amounts, missing values and genuine zero', () => {
  const source = precipitationForecast({ ...QUERY, steps: [3, 9, 24], includeWind: true });
  source.samples[0].precipitation.amount = source.samples[0].precipitation.source_value = null;
  source.samples[1].precipitation.amount = source.samples[1].precipitation.source_value = 0;
  source.samples[2].precipitation.start_lead_hours = 6;
  source.samples[2].precipitation.start_at = '2026-09-30T18:00:00.000Z';
  source.samples[2].precipitation.source_value = 0.00001;
  source.samples[2].precipitation.amount = 0.01;
  const value = validateProvider(response(source), NOW);
  assert.equal(hasSupportedPrecipitation(value), true);
  assert.equal(displayValue(value, 'precipitation', 0), 'Not available');
  assert.equal(displayValue(value, 'precipitation', 1), '0');
  assert.equal(displayValue(value, 'precipitation', 2), '0.01');
  assert.equal(displayAccumulationWindow(value, 0), `${QUERY.run} → ${source.samples[0].valid_at}`);
  assert.equal(displayAccumulationWindow(value, 2), `2026-09-30T18:00:00.000Z → ${source.samples[2].valid_at}`);
  assert.equal(displayValue(value, 'air_quality', 0), 'Not available');
});

test('precipitation projection cannot replace native windows, units or totals with inferred rates', () => {
  const value = response(precipitationForecast({ ...QUERY, steps: [3, 9, 24] }));
  for (const mutate of [
    rain => { rain.accumulation_windows[1].start_at = value.timeline.valid_at[0]; },
    rain => { rain.accumulation_windows[1].end_at = value.timeline.valid_at[0]; },
    rain => { rain.accumulation_windows.pop(); },
    rain => { delete rain.accumulation_windows; },
    rain => { rain.values[1] /= 9; },
    rain => { rain.unit = 'mm/h'; },
    rain => { rain.statistic = 'rate'; },
  ]) {
    const changed = structuredClone(value);
    mutate(changed.series.find(item => item.variable === 'precipitation'));
    assert.throws(() => validateProvider(changed, NOW), /FORECAST_INVALID/);
  }
});

test('genuine zero differs from a missing value', () => {
  assert.equal(displayValue({ series: [{ variable: 'wind_speed_10m', values: [0, null] }] }, 'wind_speed_10m', 0), '0.0');
  assert.equal(displayValue({ series: [{ variable: 'wind_speed_10m', values: [0, null] }] }, 'wind_speed_10m', 1), 'Not available');
});

test('reject expired publication, tampered projection and private-area publication', () => {
  const value = response();
  assert.throws(() => validateProvider(value, value.delivery.publication_expires_at), /STALE_FORECAST/);
  for (const mutate of [
    body => { body.timeline.valid_at[0] = NOW; },
    body => { body.series[0].values[0] = 999; },
    body => { body.capabilities.current_observations = true; },
    body => { body.forecast.area.sharing = 'private'; },
    body => { body.delivery.upstream_origin_attested = true; },
    body => { body.freshness.expires_at = '2099-01-01T00:00:00.000Z'; },
  ]) {
    const changed = structuredClone(value); mutate(changed);
    assert.throws(() => validateProvider(changed, NOW));
  }
});

test('fetch is one fixed same-origin request, not location or publisher selection', async () => {
  const now = new Date().toISOString();
  const run = new Date(); run.setUTCHours(0, 0, 0, 0);
  const value = response(forecast({ ...QUERY, run: run.toISOString() }, now), now);
  let calls = 0;
  await fetchProvider(async (url, options) => {
    ++calls;
    assert.equal(url, '/api/volparossa/forecast');
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.body, undefined);
    return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
  }, new AbortController().signal);
  assert.equal(calls, 1);
});

test('HTTP errors, invalid UTF-8 and oversized bodies fail without fallback', async () => {
  for (const candidate of [new Response('bad', { status: 503 }),
    new Response(new Uint8Array([0xff]), { headers: { 'content-type': 'application/json' } }),
    new Response(' '.repeat(MAX_PROVIDER_BYTES + 1), { headers: { 'content-type': 'application/json' } })]) {
    let calls = 0;
    await assert.rejects(fetchProvider(async () => { ++calls; return candidate; }, new AbortController().signal));
    assert.equal(calls, 1);
  }
});

test('patch integrates actual week route and gates original outbound dependencies', async () => {
  const patch = await readFile(join(import.meta.dirname, 'upstream.patch'), 'utf8');
  assert.match(patch, /src\/routes\/weather\/week\/\+page.svelte/);
  assert.match(patch, /\+\s*<VolparossaWeek \/>/);
  assert.match(patch, /VOLPAROSSA_WEATHER\) redirect\(303, localizeHref\('\/weather\/week\/'\)\)/);
  assert.match(patch, /VOLPAROSSA_WEATHER\) return null/);
  assert.match(patch, /VOLPAROSSA_WEATHER\) throw new Error/);
  assert.match(patch, /\+\s*\{#if VOLPAROSSA_WEATHER && !routePath/);
  assert.match(patch, /Weather data: VOLPAROSSA provider from/);
  assert.match(patch, /Original Drizz\.li application by Open-Meteo/);
  assert.match(patch, /\+\s*\{#if !VOLPAROSSA_WEATHER\}/);
  const component = await readFile(join(import.meta.dirname, 'overlay/src/routes/weather/week/VolparossaForecast.svelte'), 'utf8');
  assert.match(component, /forecast\.forecast\.area\.latitude/);
  assert.match(component, /forecast\.timeline\.valid_at/);
  assert.match(component, /Missing does not mean dry, clear or clean air/);
  assert.doesNotMatch(component, /navigator\.geolocation|localStorage|fetchWeatherApi/);
});
