// SPDX-License-Identifier: GPL-3.0-only
// Fixed HTTP doorway, not a provider implementation or overlay verifier.
// Only the APK API port is reversed; /state remains observer-only.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer, request as httpRequest } from 'node:http';
import { lstat, readFile, readlink, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const API_PORT = 43210, CONTROL_PORT = 43211;
export const LIVE_BODY_LIMIT = 256 * 1024, LIVE_CONTROL_LIMIT = 2 * LIVE_BODY_LIMIT + 4096;
const ORIGIN = `http://127.0.0.1:${API_PORT}`;
const PATHS = Object.freeze({ '/api/volparossa/forecast': 'weather', '/api/volparossa/air-quality': 'air_quality' });
const FIELDS = ['dev', 'ino', 'mode', 'uid', 'gid'];
const CODES = new Set(['socket_boundary', 'upstream_status', 'upstream_protocol', 'body_bound',
  'upstream_io', 'deadline', 'client_aborted', 'closing', 'request_limit', 'cleanup_unconfirmed']);
class DoorwayFailure extends Error {
  constructor(code) { super('live doorway failed'); this.code = CODES.has(code) ? code : 'upstream_io'; }
}

export async function socketBinding(path) {
  assert.ok(typeof path === 'string' && isAbsolute(path) && resolve(path) === path && Buffer.byteLength(path) <= 103);
  const parent = dirname(path), before = await lstat(parent), socket = await lstat(path);
  assert.ok(before.isDirectory() && before.uid === process.getuid() && (before.mode & 0o7777) === 0o700);
  assert.ok(socket.isSocket() && socket.uid === process.getuid() && (socket.mode & 0o7777) === 0o600 && socket.nlink === 1);
  assert.equal(await realpath(parent), parent); assert.equal(await realpath(path), path);
  const after = await lstat(parent), named = await lstat(path);
  assert.ok(FIELDS.every(key => before[key] === after[key] && socket[key] === named[key]));
  return { parent: Object.fromEntries(FIELDS.map(key => [key, after[key]])),
    socket: Object.fromEntries(FIELDS.map(key => [key, named[key]])) };
}

function incomingAllowed(incoming, port, control) {
  const counts = {};
  for (let i = 0; i < incoming.rawHeaders.length; i += 2) {
    const key = incoming.rawHeaders[i].toLowerCase(); counts[key] = (counts[key] ?? 0) + 1;
  }
  return incoming.socket.remoteAddress === '127.0.0.1' && counts.host === 1
    && incoming.headers.host === `127.0.0.1:${port}` && (counts.origin ?? 0) <= 1
    && (incoming.headers.origin === undefined || incoming.headers.origin === ORIGIN)
    && (incoming.headers['sec-fetch-site'] === undefined || ['same-origin', 'none'].includes(incoming.headers['sec-fetch-site']))
    && incoming.method === 'GET' && incoming.headers['transfer-encoding'] === undefined
    && (incoming.headers['content-length'] === undefined || incoming.headers['content-length'] === '0')
    && (control ? incoming.url === '/state' : Object.hasOwn(PATHS, incoming.url));
}

function send(response, status, body) {
  if (response.destroyed || response.writableEnded) return;
  response.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': body.length,
    'Cache-Control': 'no-store', Connection: 'close', 'X-Content-Type-Options': 'nosniff' });
  response.end(body);
}
const unavailable = Buffer.from('{"error":"FORECAST_UNAVAILABLE"}');

export async function startLiveFixture({ upstreamSocket, apiPort = API_PORT, controlPort = CONTROL_PORT,
  requestDeadlineMs = 185000 } = {}) {
  // Alternate ports/deadlines are bounded local test seams, never CLI inputs.
  assert.ok([apiPort, controlPort].every(port => Number.isInteger(port) && port >= 0 && port <= 65535));
  assert.ok(Number.isInteger(requestDeadlineMs) && requestDeadlineMs >= 1 && requestDeadlineMs <= 185000);
  const binding = await socketBinding(upstreamSocket);
  const calls = { weather: 0, air_quality: 0 }, completed = { weather: 0, air_quality: 0 };
  const products = { weather: null, air_quality: null }, hashes = { weather: null, air_quality: null };
  let active = null, abortActive, closing = false, stopping, failure = null;
  const status = () => structuredClone({ schema: 3, profile: 'protected-core', calls, completed, products,
    response_sha256: hashes, active: active !== null, terminal_failure: failure,
    synthetic_weather: false, synthetic_air_quality: false, core_executed: false, overlay_proven: false });
  const options = { maxHeaderSize: 8192, headersTimeout: 5000, requestTimeout: 5000,
    keepAliveTimeout: 1, connectionsCheckingInterval: 1000 };
  let boundApi, boundControl;
  const api = createServer(options, (incoming, response) => {
    if (!incomingAllowed(incoming, boundApi, false)) return send(response, 403, unavailable);
    if (closing || failure) return send(response, 503, unavailable);
    if (active) return send(response, 429, unavailable);
    const kind = PATHS[incoming.url];
    if (calls[kind] >= 3) { failure = 'request_limit'; return send(response, 503, unavailable); }
    calls[kind]++;
    const controller = new AbortController();
    abortActive = code => controller.abort(new DoorwayFailure(code));
    const disconnect = () => { if (!response.writableFinished) abortActive?.('client_aborted'); };
    response.once('close', disconnect);
    const timer = setTimeout(() => controller.abort(new DoorwayFailure('deadline')), requestDeadlineMs);
    active = (async () => {
      let request, socket, joined = Promise.resolve(), joinFailure = false;
      async function join() {
        request?.destroy(); socket?.destroy();
        let joinTimer;
        try {
          await Promise.race([joined, new Promise((_, reject) => {
            joinTimer = setTimeout(() => reject(new DoorwayFailure('cleanup_unconfirmed')), 2000);
          })]);
        } catch { joinFailure = true; throw new DoorwayFailure('cleanup_unconfirmed'); }
        finally { clearTimeout(joinTimer); }
      }
      try {
        try { assert.deepEqual(await socketBinding(upstreamSocket), binding); }
        catch { throw new DoorwayFailure('socket_boundary'); }
        controller.signal.throwIfAborted();
        const raw = await new Promise((done, reject) => {
          request = httpRequest({ socketPath: upstreamSocket, path: incoming.url, method: 'GET', agent: false,
            maxHeaderSize: 8192, signal: controller.signal,
            headers: { Host: ORIGIN.slice(7), Origin: ORIGIN, Accept: 'application/json', Connection: 'close' } }, reply => {
            const parts = []; let length = 0;
            const rejectReply = code => { reject(new DoorwayFailure(code)); reply.destroy(); };
            if (reply.statusCode !== 200) return rejectReply('upstream_status');
            if (!/^application\/json(?:;\s*charset=utf-8)?$/i.test(reply.headers['content-type'] ?? '')
                || reply.headers['content-encoding'] !== undefined) return rejectReply('upstream_protocol');
            if (reply.headers['content-length'] !== undefined && (!/^[0-9]+$/.test(reply.headers['content-length'])
                || Number(reply.headers['content-length']) > LIVE_BODY_LIMIT)) return rejectReply('body_bound');
            reply.on('data', part => {
              length += part.length;
              if (length > LIVE_BODY_LIMIT) return rejectReply('body_bound');
              parts.push(part);
            });
            reply.once('error', reject); reply.once('aborted', () => reject(new DoorwayFailure('upstream_io')));
            reply.once('end', () => reply.complete && length > 0 ? done(Buffer.concat(parts, length))
              : reject(new DoorwayFailure('upstream_protocol')));
          });
          request.once('socket', value => { socket = value; joined = new Promise(done => value.once('close', done)); });
          request.once('error', reject); request.end();
        });
        controller.signal.throwIfAborted();
        let product;
        try {
          product = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw));
          assert.ok(product && typeof product === 'object' && !Array.isArray(product));
        } catch { throw new DoorwayFailure('upstream_protocol'); }
        // The complete original response is kept only in this private process.
        // A parsed 200 is not core authority, app consumption or overlay proof.
        await join();
        controller.signal.throwIfAborted();
        products[kind] = product;
        hashes[kind] = createHash('sha256').update(raw).digest('hex'); completed[kind]++;
        send(response, 200, raw);
      } catch (error) {
        failure ??= controller.signal.aborted ? controller.signal.reason.code
          : error instanceof DoorwayFailure ? error.code : 'upstream_io';
        send(response, 503, unavailable);
      } finally {
        clearTimeout(timer); response.removeListener('close', disconnect);
        try { if (!joinFailure) await join(); }
        catch { /* The sticky cleanup result below forbids clean shutdown. */ }
        if (joinFailure) failure = 'cleanup_unconfirmed';
        abortActive = null; active = null;
      }
    })();
  });
  const control = createServer(options, (incoming, response) => {
    if (!incomingAllowed(incoming, boundControl, true)) return send(response, 403, unavailable);
    const body = Buffer.from(JSON.stringify(status()));
    if (body.length > LIVE_CONTROL_LIMIT) return send(response, 503, unavailable);
    send(response, 200, body);
  });
  for (const server of [api, control]) {
    server.maxConnections = 16; server.maxRequestsPerSocket = 1;
    server.on('clientError', (_error, socket) => socket.destroy());
  }
  const listen = (server, port) => new Promise((done, reject) => {
    server.once('error', reject); server.listen(port, '127.0.0.1', () => {
      server.removeListener('error', reject); done(server.address().port);
    });
  });
  async function close() {
    if (!stopping) stopping = (async () => {
      closing = true; abortActive?.('closing');
      const waits = [api, control].map(server => new Promise((done, reject) => {
        if (!server.listening) return done();
        server.close(error => error ? reject(error) : done()); server.closeAllConnections();
      }));
      await Promise.all([...waits, active]);
      if (failure === 'cleanup_unconfirmed') throw new DoorwayFailure(failure);
    })();
    return stopping;
  }
  try { boundApi = await listen(api, apiPort); boundControl = await listen(control, controlPort); }
  catch (error) { await close(); throw error; }
  return { apiPort: boundApi, controlPort: boundControl, status, close };
}

async function main() {
  assert.equal(process.argv.length, 4); assert.equal(process.argv[2], '--upstream-socket');
  assert.ok(process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.notEqual(await readlink('/proc/self/ns/net'), process.env.VOLPAROSSA_TEST_HOST_NETNS);
  assert.deepEqual((await readFile('/proc/net/dev', 'utf8')).split('\n').filter(line => line.includes(':'))
    .map(line => line.split(':')[0].trim()), ['lo']);
  const fixture = await startLiveFixture({ upstreamSocket: process.argv[3] });
  let stopping;
  const stop = () => {
    if (!stopping) stopping = fixture.close().catch(() => { process.exitCode = 1; });
    process.stdin.destroy(); return stopping;
  };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  process.stdin.once('data', () => { process.exitCode = 1; void stop(); });
  process.stdin.once('end', stop); process.stdin.resume();
  process.stdout.write(JSON.stringify({ ready: true, profile: 'protected-core', api_port: API_PORT,
    control_port: CONTROL_PORT, core_executed: false, overlay_proven: false }) + '\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write('native live doorway failed\n'); process.exitCode = 1; });
}
