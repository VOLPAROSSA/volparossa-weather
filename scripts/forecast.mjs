#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
import { parseArgs } from 'node:util';
import { request } from '../src/forecast.mjs';
import { fetchForecast, ecmwfRequest, fieldUrl } from '../src/ecmwf.mjs';
import { fetchCachedForecast } from '../src/core-cache.mjs';

try {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    latitude: { type: 'string' }, longitude: { type: 'string' }, run: { type: 'string' },
    model: { type: 'string', default: 'ifs' }, steps: { type: 'string', default: '24' },
    'community-area': { type: 'boolean', default: false }, execute: { type: 'boolean', default: false },
    'accept-data-license': { type: 'boolean', default: false }, decoder: { type: 'string' },
    'decoder-sha256': { type: 'string' }, 'scratch-parent': { type: 'string' },
    executable: { type: 'string' }, 'control-socket': { type: 'string' }, cache: { type: 'string' },
    'publisher-key': { type: 'string' }, name: { type: 'string' }, 'min-revision': { type: 'string' },
    'reuse-cache': { type: 'boolean', default: false },
  } });
  const mode = positionals[0];
  if (positionals.length !== 1 || !['origin', 'core-cache'].includes(mode)) throw new Error('MODE_REQUIRED');
  const query = request({ latitude: Number(values.latitude), longitude: Number(values.longitude), run: values.run,
    model: values.model, steps: values.steps.split(',').map(Number), communityArea: values['community-area'] });
  if (!values.execute) {
    if (mode === 'origin') ecmwfRequest(query);
    console.log(JSON.stringify({ mode, executed: false, query, auto_fallback: false,
      index_urls: mode === 'origin' ? query.steps.map(step => fieldUrl(query, step, 'index')) : [],
      notice: mode === 'origin'
        ? 'Fetch exact model-field byte ranges; derive point locally with a pinned decoder. No location sent upstream; source IP is visible. Requires --execute and --accept-data-license.'
        : 'Read only the explicit trusted publisher/name and exact model run/steps. No publication, origin fallback or training.' }, null, 2));
  } else {
    const controller = new AbortController(); const abort = () => controller.abort();
    process.once('SIGINT', abort); process.once('SIGTERM', abort);
    try {
      const result = mode === 'origin'
        ? await fetchForecast(query, { mode, acceptDataLicense: values['accept-data-license'],
          decoder: values.decoder, decoderSha256: values['decoder-sha256'], scratchParent: values['scratch-parent'], signal: controller.signal })
        : await fetchCachedForecast({ mode, executable: values.executable, controlSocket: values['control-socket'],
          cache: values.cache, scratchParent: values['scratch-parent'], publisherKey: values['publisher-key'],
          name: values.name, minRevision: Number(values['min-revision']), query, reuseCache: values['reuse-cache'] }, { signal: controller.signal });
      console.log(JSON.stringify(result, null, 2));
    } finally { process.removeListener('SIGINT', abort); process.removeListener('SIGTERM', abort); }
  }
} catch (error) {
  // Closed errors only: no upstream bodies, stderr, arbitrary paths or private locations.
  console.error(JSON.stringify({ error: error.name === 'WeatherError' ? error.code : 'WEATHER_COMMAND_FAILED' }));
  process.exitCode = 1;
}
