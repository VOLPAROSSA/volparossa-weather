// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const command = fileURLToPath(new URL('../scripts/air-quality.mjs', import.meta.url));
const query = ['--latitude', '52.52', '--longitude', '13.41', '--run', '2026-10-10T00:00:00.000Z', '--steps', '3,6'];
function run(args) {
  const output = spawnSync(process.execPath, [command, ...args], { encoding: 'utf8', timeout: 5000, maxBuffer: 16384,
    env: { LANG: 'C.UTF-8' } });
  assert.equal(output.error, undefined);
  return output;
}
test('both preview modes are inert and keep private locations private by default', () => {
  for (const mode of ['origin', 'core-cache']) {
    const output = run([mode, ...query]);
    assert.equal(output.status, 0, output.stderr);
    const plan = JSON.parse(output.stdout);
    assert.equal(plan.executed, false); assert.equal(plan.auto_fallback, false);
    assert.equal(plan.query.communityArea, false);
    assert.equal(plan.query.model, 'gefs-aerosols');
    assert.equal(plan.output_contract, 'volparossa.air-quality.forecast.v1');
  }
});
test('CLI rejects absent, malformed, wrong-cycle and oversized requests before execution', () => {
  for (const args of [[], ['origin'], ['wrong', ...query], ['origin', ...query, 'extra'],
    ['origin', ...query, '--steps', '3,'], ['origin', ...query, '--steps', '1'],
    ['origin', ...query, '--run', '2026-10-10T01:00:00.000Z'], ['origin', ...query, '--unknown-secret', '/private/path']]) {
    const output = run(args); assert.equal(output.status, 1); assert.equal(output.stdout, '');
    const error = JSON.parse(output.stderr); assert.match(error.error, /^[A-Z_]+$/);
    assert(!output.stderr.includes('/private/path'));
  }
});
