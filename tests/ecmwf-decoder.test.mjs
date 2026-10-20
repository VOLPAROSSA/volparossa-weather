// SPDX-License-Identifier: GPL-3.0-only
// Synthetic GRIB/decoder fixtures with real subprocess joining; no live model data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {mkdtemp, chmod, mkdir, open, writeFile, readdir, rename, rm, stat, symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fetchForecast} from '../src/ecmwf.mjs';
import {QUERY, decoded} from './fixtures.mjs';
const hash = value => createHash('sha256').update(value).digest('hex');
const code = expected => error => error.code === expected;
function response(url, body, status = 200, headers = {}) {
  const value = new Response(body, {status, headers}); Object.defineProperty(value, 'url', {value: url}); return value;
}
async function fixture(t, action, script = null) {
  const parent = await mkdtemp(join(tmpdir(), 'volparossa-ecmwf-decoder-')); await chmod(parent, 0o700);
  const run = new Date(); run.setUTCHours(0, 0, 0, 0);
  const query = {...QUERY, run: run.toISOString()};
  const decoder = join(parent, 'source-decoder');
  const source = script ?? `#!/bin/sh\nprintf '%s' '${JSON.stringify(decoded(query))}'\n`;
  await writeFile(decoder, source, {mode: 0o700, flag: 'wx'});
  const options = {mode: 'origin', acceptDataLicense: true, decoder, decoderSha256: hash(source), scratchParent: parent};
  const calls = [];
  const transport = async (url, config) => {
    calls.push(url); assert.equal(config.credentials, 'omit'); assert.equal(config.redirect, 'error');
    if (url.endsWith('.index')) return response(url, JSON.stringify({date: query.run.slice(0, 10).replaceAll('-', ''),
      time: '0000', step: '12', param: '2t', levtype: 'sfc', class: 'od', stream: 'oper', type: 'fc',
      expver: '0001', _offset: 1234, _length: 64}) + '\n');
    assert.equal(config.headers.Range, 'bytes=1234-1297');
    const bytes = Buffer.alloc(64); bytes.write('GRIB'); bytes[7] = 2;
    bytes.writeBigUInt64BE(64n, 8); bytes.write('7777', 60);
    return response(url, bytes, 206, {'Content-Range': 'bytes 1234-1297/2000'});
  };
  t.mock.method(globalThis, 'fetch', transport);
  try { await action({parent, options, query, transport, calls}); }
  finally { t.mock.restoreAll(); await rm(parent, {recursive: true, force: false}); }
}
test('ECMWF executes only the private pinned decoder snapshot after source replacement or mutation', async t => {
  for (const replace of [true, false]) await t.test(replace ? 'replacement' : 'in-place mutation', async t => {
    await fixture(t, async ({parent, options, query, transport, calls}) => {
      let changed = false;
      t.mock.method(globalThis, 'fetch', async (...args) => {
        if (!changed) {
          changed = true;
          const workName = (await readdir(parent)).find(name => name.startsWith('ecmwf-'));
          const work = join(parent, workName), directory = join(work, 'decoder'), executable = join(directory, 'grib_ls');
          assert.equal((await stat(work)).mode & 0o777, 0o700);
          assert.equal((await stat(directory)).mode & 0o777, 0o700);
          const handle = await open(executable, constants.O_RDONLY | constants.O_NOFOLLOW);
          try { assert.equal((await handle.stat()).mode & 0o777, 0o500);
            assert.equal(hash(await handle.readFile()), options.decoderSha256); }
          finally { await handle.close(); }
          await assert.rejects(stat(join(work, 'lib')), {code: 'ENOENT'});
          if (replace) await rename(options.decoder, join(parent, 'original-decoder'));
          await writeFile(options.decoder, `#!/bin/sh\nprintf compromised > '${join(parent, 'executed-unpinned')}'\nexit 7\n`, {mode: 0o700});
        }
        return transport(...args);
      });
      const result = await fetchForecast(query, options);
      assert.equal(result.samples[0].temperature_2m, 10); assert.equal(calls.length, 2);
      assert.equal(result.samples[0].evidence.decoder_sha256, options.decoderSha256);
      await assert.rejects(stat(join(parent, 'executed-unpinned')), {code: 'ENOENT'});
      assert.equal((await readdir(parent)).some(name => name.startsWith('ecmwf-')), false);
    });
  });
});
test('symlink, nonregular, empty, nonexecutable and oversized decoders fail before HTTP', async t => {
  for (const kind of ['symlink', 'directory', 'empty', 'nonexecutable', 'oversized']) await t.test(kind, async t => {
    await fixture(t, async ({parent, options, query, calls}) => {
      if (kind === 'symlink') {
        await rename(options.decoder, join(parent, 'target')); await symlink(join(parent, 'target'), options.decoder);
      } else if (kind === 'directory') { await rm(options.decoder); await mkdir(options.decoder, {mode: 0o700}); }
      else if (kind === 'nonexecutable') await chmod(options.decoder, 0o600);
      else { const file = await open(options.decoder, 'w');
        try { await file.truncate(kind === 'empty' ? 0 : 64 * 1024 * 1024 + 1); } finally { await file.close(); } }
      await assert.rejects(fetchForecast(query, options), code(kind === 'symlink' ? 'DECODER_PATH_INVALID' : 'DECODER_PIN_MISMATCH'));
      assert.equal(calls.length, 0); assert.equal((await readdir(parent)).some(name => name.startsWith('ecmwf-')), false);
    });
  });
});
test('mutation while reading the decoder is bounded, rejects the pin and closes the descriptor', async t => {
  await fixture(t, async ({options, query, calls}) => {
    const probe = await open(options.decoder, 'r'), prototype = Object.getPrototypeOf(probe); await probe.close();
    const read = prototype.read; let handle, capacity;
    const originalSize = (await stat(options.decoder)).size;
    t.mock.method(prototype, 'read', async function (...args) {
      handle = this; capacity = args[0].length; await writeFile(options.decoder, '#!/bin/sh\nexit 9\n');
      return Reflect.apply(read, this, args);
    });
    await assert.rejects(fetchForecast(query, options), code('DECODER_PIN_MISMATCH'));
    assert.equal(capacity, originalSize + 1); assert.equal(calls.length, 0); assert.equal(handle.fd, -1);
  });
});
test('HTTP rejection removes the private executable and scratch tree', async t => {
  await fixture(t, async ({parent, options, query}) => {
    t.mock.method(globalThis, 'fetch', async url => response(url, '', 403));
    await assert.rejects(fetchForecast(query, options), code('INDEX_HTTP_FAILED'));
    assert.deepEqual(await readdir(parent), ['source-decoder']);
  });
});
test('cancellation joins a real synthetic decoder subprocess before removing its snapshot', async t => {
  await fixture(t, async ({parent, options, query}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 100);
    try { await assert.rejects(fetchForecast(query, {...options, signal: controller.signal}), code('CANCELLED')); }
    finally { clearTimeout(timer); }
    assert.deepEqual(await readdir(parent), ['source-decoder']);
  }, '#!/bin/sh\nexec /usr/bin/sleep 30\n');
});
