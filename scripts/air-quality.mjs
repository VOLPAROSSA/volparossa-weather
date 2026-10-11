#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
import { parseArgs } from 'node:util';
import { airQualityRequest, AQ_SCHEMA } from '../src/air-quality.mjs';
import { requireThat } from '../src/forecast.mjs';

try {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    latitude: { type: 'string' }, longitude: { type: 'string' }, run: { type: 'string' },
    steps: { type: 'string', default: '3' }, 'community-area': { type: 'boolean', default: false },
    execute: { type: 'boolean', default: false }, 'accept-data-license': { type: 'boolean', default: false },
    decoder: { type: 'string' }, 'decoder-sha256': { type: 'string' }, 'scratch-parent': { type: 'string' },
    executable: { type: 'string' }, 'control-socket': { type: 'string' }, cache: { type: 'string' },
    'publisher-key': { type: 'string' }, name: { type: 'string' }, 'min-revision': { type: 'string' },
    'reuse-cache': { type: 'boolean', default: false },
  } });
  const mode = positionals[0];
  requireThat(positionals.length === 1 && ['origin', 'core-cache'].includes(mode), 'MODE_REQUIRED');
  requireThat(values.latitude !== undefined && values.longitude !== undefined
    && /^\d+(,\d+)*$/.test(values.steps), 'QUERY_REQUIRED');
  const query = airQualityRequest({ latitude: Number(values.latitude), longitude: Number(values.longitude),
    run: values.run, steps: values.steps.split(',').map(Number), communityArea: values['community-area'] });
  if (!values.execute) {
    console.log(JSON.stringify({ mode, executed: false, query, output_contract: AQ_SCHEMA, auto_fallback: false,
      notice: mode === 'origin'
        ? 'Explicit NOAA surface particulate model forecast. Fetch bounded fields; locate point locally. Source IP visible. Requires --execute and --accept-data-license. No AQI or current observation.'
        : 'Read exact public community product from explicit trusted publisher/name through core. No origin fallback or publication. No AQI or current observation.' }, null, 2));
  } else {
    const controller = new AbortController(); const abort = () => controller.abort();
    process.once('SIGINT', abort); process.once('SIGTERM', abort);
    try {
      const result = mode === 'origin'
        ? await (await import('../src/noaa-gefs.mjs')).fetchAirQualityForecast(query, {
          mode, acceptDataLicense: values['accept-data-license'], decoder: values.decoder,
          decoderSha256: values['decoder-sha256'], workDirectory: values['scratch-parent'], signal: controller.signal,
        })
        : await (await import('../src/air-quality-core.mjs')).fetchCachedAirQuality({
          mode, executable: values.executable, controlSocket: values['control-socket'], cache: values.cache,
          scratchParent: values['scratch-parent'], publisherKey: values['publisher-key'], name: values.name,
          minRevision: Number(values['min-revision']), query, reuseCache: values['reuse-cache'],
        }, { signal: controller.signal });
      console.log(JSON.stringify(result, null, 2));
    } finally { process.removeListener('SIGINT', abort); process.removeListener('SIGTERM', abort); }
  }
} catch (error) {
  console.error(JSON.stringify({ error: error.name === 'WeatherError' ? error.code : 'AIR_QUALITY_COMMAND_FAILED' }));
  process.exitCode = 1;
}
