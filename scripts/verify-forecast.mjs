#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { MAX_BYTES, WeatherError, requireThat } from '../src/forecast.mjs';
import { verifyTemperature } from '../src/forecast-verification.mjs';

async function readInput(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = await file.stat();
    requireThat(stat.isFile() && stat.size > 0 && stat.size <= MAX_BYTES, 'VERIFICATION_FILE_INVALID');
    const bytes = Buffer.alloc(stat.size + 1);
    let offset = 0;
    while (offset < bytes.length) {
      const { bytesRead } = await file.read(bytes, offset, bytes.length - offset, offset);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    requireThat(offset === stat.size, 'VERIFICATION_FILE_INVALID');
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, offset))); }
    catch { throw new WeatherError('JSON_INVALID'); }
  } finally { await file.close(); }
}

try {
  const files = process.argv.slice(2);
  requireThat(files.length === 3, 'EXPECTED_IFS_AIFS_OBSERVATIONS_FILES');
  console.log(JSON.stringify(verifyTemperature(...await Promise.all(files.map(readInput))), null, 2));
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof WeatherError ? error.code : 'VERIFICATION_INPUT_FAILED' }));
  process.exitCode = 1;
}
