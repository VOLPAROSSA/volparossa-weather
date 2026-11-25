#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
import { stat } from 'node:fs/promises';
import { readBytes } from '../src/verification-input.mjs';
import { MAX_BYTES, WeatherError, requireThat } from '../src/forecast.mjs';
import { compareEqualWeightTemperature, verifyTemperature } from '../src/forecast-verification.mjs';

async function readInput(path) {
  const bytes = await readBytes(path, MAX_BYTES);
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new WeatherError('JSON_INVALID'); }
}

try {
  const files = process.argv.slice(2);
  const compareBlend = files.length === 4 && files[0] === '--compare-blend';
  if (compareBlend) files.shift();
  requireThat(files.length === 3, 'EXPECTED_IFS_AIFS_OBSERVATIONS_FILES');
  let result;
  // A regular third file is the original three-file command, even when its
  // first forecast happens to have the literal filename "archive".
  if (files[0] === 'archive' && (await stat(files[2])).isDirectory()) {
    const { verifyArchivedTemperature } = await import('../src/archived-temperature.mjs');
    result = await verifyArchivedTemperature(await readInput(files[1]), files[2]);
  } else result = verifyTemperature(...await Promise.all(files.map(readInput)));
  const output = compareBlend
    ? { verification: result, comparison: compareEqualWeightTemperature(result.stations ?? [result]) }
    : result;
  console.log(JSON.stringify(output, null, 2));
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof WeatherError ? error.code : 'VERIFICATION_INPUT_FAILED' }));
  process.exitCode = 1;
}
