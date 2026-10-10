// SPDX-License-Identifier: GPL-3.0-only
// Uses the actual pinned Svelte compiler and actual component in the staged app.
// This is server-render evidence, not browser hydration or overlay evidence.
import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile, writeFile, unlink, realpath } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { resolve, join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { windForecast, forecast, QUERY, NOW } from '../../tests/fixtures.mjs';
import { toProviderForecast } from '../../src/provider.mjs';

const root = resolve(import.meta.dirname, '../..');
assert.ok(process.env.DRIZZLI_STAGE, 'Set DRIZZLI_STAGE to the exact staged upstream checkout');
const stage = await realpath(process.env.DRIZZLI_STAGE);
assert.equal(dirname(stage), await realpath(join(root, 'build')));
const require = createRequire(join(stage, 'package.json'));
const { compile } = require('svelte/compiler');
const { render } = await import(pathToFileURL(require.resolve('svelte/server')));
const components = join(stage, 'src/routes/weather/week');
const sourcePath = join(components, 'VolparossaForecast.svelte');
assert.equal(await readFile(sourcePath, 'utf8'), await readFile(join(import.meta.dirname,
  'overlay/src/routes/weather/week/VolparossaForecast.svelte'), 'utf8'));
const output = join(components, `.volparossa-render-${randomUUID()}.mjs`);
const compiled = compile(await readFile(sourcePath, 'utf8'), { filename: sourcePath, generate: 'server' });
await writeFile(output, compiled.js.code, { flag: 'wx', mode: 0o600 });
after(() => unlink(output));
const Component = (await import(pathToFileURL(output))).default;
const { validateProvider } = await import(pathToFileURL(join(stage, 'src/lib/services/volparossa/client.mjs')));

function provider(original) {
  const expiry = '2026-09-30T21:10:00.000Z';
  const value = { ...toProviderForecast(original, { now: NOW, publicationExpires: expiry,
    variables: ['temperature_2m', 'wind_speed_10m', 'wind_direction_10m'] }),
  delivery: { mode: 'core-cache', upstream_origin_attested: false,
    manifest_media_type_checked: false, publication_expires_at: expiry } };
  return validateProvider(value, NOW);
}

test('actual Svelte child renders supplied coordinates, native times and temperature/wind', async () => {
  const value = provider(windForecast({ ...QUERY, steps: [3, 9, 24] }));
  const html = (await render(Component, { props: { forecast: value } })).body;
  assert.match(html, /52\.52° latitude, 13\.41° longitude/);
  for (const time of value.timeline.valid_at) assert.ok(html.includes(time));
  assert.match(html, /10\.0<\/td>/);
  assert.match(html, /5\.0<\/td>/);
  assert.match(html, /not current observations/);
  assert.match(html, /Missing does not mean dry, clear or clean air/);
  assert.equal((html.match(/<tr /g) || []).length, 3);
  assert.doesNotMatch(html, /<iframe|<script|<img/);
  assert.match(html, /href="https:\/\/www.ecmwf.int\/en\/forecasts\/datasets\/open-data"/);
  assert.match(html, /href="https:\/\/creativecommons.org\/licenses\/by\/4.0\/"/);
  assert.match(html, /Processing:/);
});

test('source descriptions are escaped by the actual Svelte component', async () => {
  const original = forecast();
  original.source.changes = '<script>not executable</script>';
  const html = (await render(Component, { props: { forecast: provider(original) } })).body;
  assert.ok(html.includes('&lt;script>not executable&lt;/script>'));
  assert.doesNotMatch(html, /<script>/);
});

test('actual Svelte child renders missing wind rather than invented zero', async () => {
  const html = (await render(Component, { props: { forecast: provider(forecast()) } })).body;
  assert.equal((html.match(/Not available<\/td>/g) || []).length, 2);
  assert.match(html, /Precipitation, air quality/);
});

test('actual week integration component compiles for client and server', async () => {
  for (const file of ['VolparossaWeek.svelte', '+page.svelte']) {
    const filename = join(components, file);
    const source = await readFile(filename, 'utf8');
    assert.ok(compile(source, { filename, generate: 'client' }).js.code.length > 0);
    assert.ok(compile(source, { filename, generate: 'server' }).js.code.length > 0);
  }
});
