// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchField } from '../src/ecmwf.mjs';
import { QUERY } from './fixtures.mjs';

const code = expected => error => error.code === expected;
const index = Buffer.from(JSON.stringify({ date: '20260930', time: '1200', step: '12', param: '2t',
  levtype: 'sfc', class: 'od', stream: 'oper', type: 'fc', expver: '0001', _offset: 1234, _length: 64 }));
const options = { mode: 'origin', acceptDataLicense: true };
const rangeHeaders = { 'content-range': 'bytes 1234-1297/9999' };

// Track the standard fetch/stream boundary without any origin request. A cancel
// promise may never settle: the fetch AbortSignal, not awaiting that promise,
// owns network teardown and bounds this method's error-path completion.
function trackedResponse(url, { status = 206, headers = rangeHeaders, chunks = [], cancel = () => Promise.resolve(),
  redirected = false, readerError = false } = {}) {
  const state = { readers: 0, reads: 0, readerCancels: 0, bodyCancels: 0 };
  let position = 0;
  const result = { url, status, redirected, headers: new Headers(headers), body: {
    getReader() {
      state.readers++;
      if (readerError) throw new Error('reader unavailable');
      return {
        async read() {
          state.reads++;
          return position < chunks.length ? { done: false, value: chunks[position++] } : { done: true };
        },
        cancel() { state.readerCancels++; return cancel(); },
      };
    },
    cancel() { state.bodyCancels++; return cancel(); },
  } };
  return { result, state };
}

async function rejectedResponse(change, expected, { indexFailure = false, bodyRead = false } = {}) {
  const observations = []; let rejected;
  await assert.rejects(fetchField(QUERY, 12, { ...options, fetcher: async (url, init) => {
    observations.push({ url, init });
    assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error');
    assert.equal(init.cache, 'no-store'); assert.equal(init.referrerPolicy, 'no-referrer');
    assert.equal(init.headers['Accept-Encoding'], 'identity');
    if (!indexFailure && url.endsWith('.index')) {
      const response = new Response(index); Object.defineProperty(response, 'url', { value: url }); return response;
    }
    if (!indexFailure) assert.equal(init.headers.Range, 'bytes=1234-1297');
    rejected = trackedResponse(change.url ?? url, change);
    return rejected.result;
  } }), code(expected));
  assert.equal(observations.length, indexFailure ? 1 : 2, 'no retry or source fallback');
  assert.ok(observations.every(({ init }) => init.signal.aborted), 'all finished fetches are explicitly aborted');
  assert.equal(rejected.state.readers, bodyRead ? 1 : 0);
  assert.equal(rejected.state.bodyCancels, bodyRead ? 0 : 1);
  assert.equal(rejected.state.readerCancels, bodyRead ? 1 : 0);
  if (!bodyRead) assert.equal(rejected.state.reads, 0, 'rejected headers never consume a field body');
}

test('rejected index and field statuses abort and cancel unread bodies without retry', async t => {
  for (const status of [429, 500, 206]) {
    await t.test(`index ${status}`, () => rejectedResponse({ status }, 'INDEX_HTTP_FAILED', { indexFailure: true }));
  }
  for (const status of [429, 500, 200]) {
    await t.test(`field ${status}`, () => rejectedResponse({ status }, 'EXACT_RANGE_REQUIRED'));
  }
});

test('invalid origin and field headers cancel before acquiring a body reader', async t => {
  for (const [name, change, expected] of [
    ['origin', { url: 'https://other.invalid/field' }, 'ORIGIN_CHANGED'],
    ['redirect', { redirected: true }, 'ORIGIN_CHANGED'],
    ['encoding', { headers: { ...rangeHeaders, 'content-encoding': 'gzip' } }, 'ENCODING_INVALID'],
    ['declared oversize', { headers: { ...rangeHeaders, 'content-length': '65' } }, 'BODY_TOO_LARGE'],
    ['invalid length', { headers: { ...rangeHeaders, 'content-length': '-1' } }, 'BODY_TOO_LARGE'],
    ['missing range', { headers: {} }, 'RANGE_RESPONSE_MISMATCH'],
    ['wrong range', { headers: { 'content-range': 'bytes 0-63/9999' } }, 'RANGE_RESPONSE_MISMATCH'],
  ]) await t.test(name, () => rejectedResponse(change, expected));
});

test('oversized and truncated exact-range bodies abort and cancel their acquired reader', async t => {
  await t.test('oversize', () => rejectedResponse({ chunks: [Buffer.alloc(65)] }, 'BODY_TOO_LARGE', { bodyRead: true }));
  await t.test('truncated', () => rejectedResponse({ chunks: [Buffer.alloc(63)] }, 'FIELD_TRUNCATED', { bodyRead: true }));
  await t.test('empty', () => rejectedResponse({ chunks: [] }, 'FIELD_TRUNCATED', { bodyRead: true }));
});

test('a failed getReader still cancels the unread body', async () => {
  let response, signal;
  await assert.rejects(fetchField(QUERY, 12, { ...options, fetcher: async (url, init) => {
    signal = init.signal; response = trackedResponse(url, { status: 200, readerError: true }); return response.result;
  } }), code('NETWORK_FAILED'));
  assert.equal(signal.aborted, true);
  assert.deepEqual(response.state, { readers: 1, reads: 0, readerCancels: 0, bodyCancels: 1 });
});

test('never-settling or rejected stream cancellation cannot extend or replace the original failure', { timeout: 1000 }, async t => {
  for (const [name, cancel] of [
    ['pending', () => new Promise(() => {})],
    ['rejected', () => Promise.reject(new Error('cancel failed'))],
  ]) {
    await t.test(`${name} unread body`, () => rejectedResponse({ status: 429, cancel }, 'EXACT_RANGE_REQUIRED'));
    await t.test(`${name} acquired reader`, () => rejectedResponse({ chunks: [Buffer.alloc(65)], cancel },
      'BODY_TOO_LARGE', { bodyRead: true }));
  }
});

test('caller cancellation before headers aborts the owned request without another request', async () => {
  const controller = new AbortController(); let calls = 0, ownedSignal;
  const operation = fetchField(QUERY, 12, { ...options, signal: controller.signal, fetcher: (url, init) => {
    calls++; ownedSignal = init.signal;
    return new Promise((resolve, reject) => init.signal.addEventListener('abort',
      () => reject(new DOMException('aborted', 'AbortError')), { once: true }));
  } });
  const rejection = assert.rejects(operation, code('CANCELLED'));
  controller.abort(); await rejection;
  assert.equal(calls, 1); assert.equal(ownedSignal.aborted, true);
});

test('the existing 30 second request timer aborts without a renewed deadline', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let calls = 0, aborts = 0, ownedSignal;
  const operation = fetchField(QUERY, 12, { ...options, fetcher: (url, init) => {
    calls++; ownedSignal = init.signal;
    return new Promise((resolve, reject) => init.signal.addEventListener('abort', () => {
      aborts++; reject(new DOMException('aborted', 'AbortError'));
    }, { once: true }));
  } });
  const rejection = assert.rejects(operation, code('TIMEOUT'));
  t.mock.timers.tick(29999); assert.equal(ownedSignal.aborted, false);
  t.mock.timers.tick(1); await rejection;
  t.mock.timers.tick(30000); assert.equal(calls, 1); assert.equal(aborts, 1);
});
