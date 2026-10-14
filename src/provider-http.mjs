// SPDX-License-Identifier: GPL-3.0-only
// Development boundary: fixed public weather/AQ products, not a location catalogue.
import { createServer } from 'node:http';
import { constants } from 'node:fs';
import { lstat, readdir, realpath, open, mkdtemp, chmod, link, unlink, rmdir } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, resolve, extname } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { fetchCachedProvider, fetchCachedAirQualityProvider } from './provider-core.mjs';
import { providerVariables, toProviderForecast } from './provider.mjs';
import { toAirQualityProviderForecast } from './air-quality-provider.mjs';
import { airQualityFreshness, airQualityRequest } from './air-quality.mjs';
import { freshness, request, requireThat } from './forecast.mjs';

const API = '/api/volparossa/forecast';
const AQ_API = '/api/volparossa/air-quality';
const MAX_ASSET = 8 * 1024 * 1024, MAX_STATIC = 32 * 1024 * 1024;
const MAX_RESPONSE = 256 * 1024;
const UNIX_ORIGIN = 'http://127.0.0.1:43210';
const MAX_UNIX_PATH = 103;
const MIME = Object.freeze({ '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf' });
const HEADERS = Object.freeze({ 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer', 'Cross-Origin-Resource-Policy': 'same-origin',
  'Permissions-Policy': 'geolocation=(), camera=(), microphone=()', 'Connection': 'close',
  'Content-Security-Policy': "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" });
// Opt in only for an owner-selected Flutter CanvasKit deployment. This does not
// permit JavaScript eval, workers, remote engines/fonts or additional API origins.
const FLUTTER_HEADERS = Object.freeze({ ...HEADERS,
  'Content-Security-Policy': HEADERS['Content-Security-Policy']
    .replace("script-src 'self' 'unsafe-inline'", "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'")
    .replace("base-uri 'none'", "base-uri 'self'") });
const STATIC_PROFILES = Object.freeze({
  default: Object.freeze({ mime: MIME, headers: HEADERS, exactMime: Object.freeze({}) }),
  'flutter-canvaskit': Object.freeze({ mime: Object.freeze({ ...MIME,
    '.wasm': 'application/wasm', '.bin': 'application/octet-stream', '.otf': 'font/otf',
    '.frag': 'application/octet-stream' }), headers: FLUTTER_HEADERS,
  exactMime: Object.freeze({ '/assets/NOTICES': 'text/plain; charset=utf-8',
    '/LICENSE.txt': 'text/plain; charset=utf-8', '/LICENSE.VOLPAROSSA.txt': 'text/plain; charset=utf-8' }) }),
});

function exact(value, keys, code) {
  requireThat(value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('|') === [...keys].sort().join('|'), code);
}
function absolute(value) {
  requireThat(typeof value === 'string' && isAbsolute(value) && resolve(value) === value
    && !/[\x00-\x1f\x7f]/.test(value), 'BRIDGE_PATH_INVALID');
  return value;
}

function sameInode(left, right) {
  return left.dev === right.dev && left.ino === right.ino;
}

// Linux-only private API listener. The configured parent must already exist;
// neither cache directories nor the configured socket parent are created here.
async function listenUnix(server, socketPath) {
  absolute(socketPath);
  requireThat(process.platform === 'linux' && typeof process.getuid === 'function'
    && Buffer.byteLength(socketPath) <= MAX_UNIX_PATH, 'BRIDGE_SOCKET_INVALID');
  const parentPath = dirname(socketPath), uid = process.getuid();
  let parent, staging, parentInfo, stagingInfo, stagingPath, bindPath, socketInfo;
  let published = false, retired = false;
  function privateDirectory(info) {
    return info.isDirectory() && info.uid === uid && (info.mode & 0o7777) === 0o700;
  }
  async function parentUnchanged() {
    const current = await lstat(parentPath);
    return privateDirectory(current) && sameInode(parentInfo, current)
      && await realpath(parentPath) === parentPath;
  }
  function ownedSocket(info) {
    return socketInfo && info.isSocket() && info.uid === uid && sameInode(socketInfo, info);
  }
  // Unlink only a known inode through the pinned parent, never a replacement at
  // the caller's pathname. Missing/replaced entries are not adopted or repaired.
  async function removeSocket(path) {
    let info;
    try { info = await lstat(path); }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
    requireThat(ownedSocket(info), 'BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
    await unlink(path);
    return true;
  }
  async function retireBinding() {
    if (retired || !stagingPath) return;
    requireThat(stagingInfo, 'BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
    if (socketInfo) await removeSocket(bindPath);
    const current = await lstat(stagingPath);
    requireThat(current.isDirectory() && current.uid === uid && !(current.mode & 0o077)
      && sameInode(stagingInfo, current) && current.mode === stagingInfo.mode,
      'BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
    // rmdir never recursively removes entries. Keep the now-unlinked directory
    // descriptor open until libuv closes the listener. Its automatic unlink of
    // bindPath can then never address a replacement public socket or file.
    await rmdir(stagingPath);
    retired = true;
  }
  const publicPath = () => `/proc/self/fd/${parent.fd}/${basename(socketPath)}`;
  async function cleanup() {
    let failure;
    try {
      if (published) {
        const unchanged = await parentUnchanged().catch(() => false);
        const removed = await removeSocket(publicPath());
        requireThat(unchanged && removed, 'BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
      }
    } catch (error) { failure = error; }
    try { await staging?.close(); } catch (error) { failure ??= error; }
    try { await parent?.close(); } catch (error) { failure ??= error; }
    if (failure) throw new Error('BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
  }
  try {
    parent = await open(parentPath, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    parentInfo = await parent.stat();
    requireThat(privateDirectory(parentInfo) && await parentUnchanged(), 'BRIDGE_SOCKET_PARENT_INVALID');
    let exists = true;
    try { await lstat(publicPath()); }
    catch (error) { if (error.code !== 'ENOENT') throw error; exists = false; }
    requireThat(!exists, 'BRIDGE_SOCKET_EXISTS');
    stagingPath = await mkdtemp(`/proc/self/fd/${parent.fd}/.weather-socket-`);
    stagingInfo = await lstat(stagingPath);
    requireThat(stagingInfo.isDirectory() && stagingInfo.uid === uid && !(stagingInfo.mode & 0o077),
      'BRIDGE_SOCKET_PARENT_INVALID');
    staging = await open(stagingPath, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    const opened = await staging.stat();
    requireThat(privateDirectory(opened) && sameInode(stagingInfo, opened), 'BRIDGE_SOCKET_PARENT_INVALID');
    bindPath = `/proc/self/fd/${staging.fd}/api.sock`;
    requireThat(Buffer.byteLength(bindPath) <= MAX_UNIX_PATH, 'BRIDGE_SOCKET_INVALID');
    await new Promise((done, fail) => {
      server.once('error', fail);
      server.listen({ path: bindPath, exclusive: true }, () => {
        server.removeListener('error', fail); done();
      });
    });
    socketInfo = await lstat(bindPath);
    requireThat(socketInfo.isSocket() && socketInfo.uid === uid && socketInfo.nlink === 1,
      'BRIDGE_SOCKET_INVALID');
    await chmod(bindPath, 0o600);
    const privateSocket = await lstat(bindPath);
    requireThat(ownedSocket(privateSocket) && (privateSocket.mode & 0o7777) === 0o600
      && privateSocket.nlink === 1 && await parentUnchanged(), 'BRIDGE_SOCKET_INVALID');
    // Hard-link publication is atomic and fails if ANY destination entry exists.
    // It cannot overwrite even a concurrent socket, regular file or symlink.
    await link(bindPath, publicPath());
    published = true;
    await retireBinding();
    requireThat(await parentUnchanged(), 'BRIDGE_SOCKET_PARENT_CHANGED');
    const ready = await lstat(publicPath());
    requireThat(ownedSocket(ready) && (ready.mode & 0o7777) === 0o600 && ready.nlink === 1,
      'BRIDGE_SOCKET_INVALID');
    return cleanup;
  } catch (error) {
    let cleanupError;
    try { await retireBinding(); } catch (failure) { cleanupError = failure; }
    await new Promise(done => { server.close(done); server.closeAllConnections(); });
    try { await cleanup(); } catch (failure) { cleanupError ??= failure; }
    if (cleanupError) throw new Error('BRIDGE_SOCKET_CLEANUP_UNCONFIRMED');
    throw error;
  }
}

function coreConfiguration(value, airQuality = false) {
  const core = structuredClone(value);
  const automatic = core && Object.hasOwn(core, 'cacheMode');
  exact(core, ['mode', 'executable', 'controlSocket', 'cache', 'scratchParent', 'publisherKey',
    'name', 'minRevision', 'query', automatic ? 'cacheMode' : 'reuseCache'], 'BRIDGE_CONFIG_INVALID');
  requireThat(core.mode === 'core-cache' && (automatic ? core.cacheMode === 'create-or-open'
    : typeof core.reuseCache === 'boolean'), 'BRIDGE_CONFIG_INVALID');
  // Historical configurations remain open-only. The explicit new mode lets
  // the first actual GET ask core to create a cache; it does not create one
  // while starting the server, or make the HTTP process a cache validator.
  requireThat(automatic || core.reuseCache === true, 'BRIDGE_REUSABLE_CACHE_REQUIRED');
  for (const name of ['executable', 'controlSocket', 'cache', 'scratchParent']) absolute(core[name]);
  requireThat(typeof core.publisherKey === 'string' && /^[a-f0-9]{64}$/.test(core.publisherKey)
    && typeof core.name === 'string' && Buffer.byteLength(core.name) >= 1 && Buffer.byteLength(core.name) <= 128
    && !/[\x00-\x1f\x7f]/.test(core.name) && Number.isSafeInteger(core.minRevision)
    && core.minRevision >= 1, 'BRIDGE_CONFIG_INVALID');
  exact(core.query, ['latitude', 'longitude', 'run', 'model', 'steps', 'communityArea',
    ...(!airQuality ? ['includeWind',
      ...(core.query && Object.hasOwn(core.query, 'includePrecipitation') ? ['includePrecipitation'] : [])] : [])], 'BRIDGE_CONFIG_INVALID');
  core.query = airQuality ? airQualityRequest(core.query) : request(core.query);
  requireThat(core.query.communityArea, 'PUBLIC_COMMUNITY_AREA_REQUIRED');
  return Object.freeze(core);
}

async function requestCore(core, signal) {
  if (!Object.hasOwn(core, 'cacheMode')) return core;
  // Existence only selects one core operation. An unreadable parent is not an
  // absent cache. A canonical, non-group/world-writable parent must already
  // exist; neither parents nor cache files are made/adopted/repaired here.
  const parentPath = dirname(core.cache), parent = await lstat(parentPath);
  requireThat(parent.isDirectory() && !parent.isSymbolicLink() && !(parent.mode & 0o022)
    && await realpath(parentPath) === parentPath, 'BRIDGE_CACHE_PARENT_INVALID');
  let reuseCache;
  try {
    const info = await lstat(core.cache);
    requireThat(info.isDirectory() && !info.isSymbolicLink(), 'BRIDGE_CACHE_PATH_INVALID');
    reuseCache = true;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    reuseCache = false;
  }
  const after = await lstat(parentPath);
  requireThat(['dev', 'ino', 'uid', 'gid', 'mode'].every(key => parent[key] === after[key])
    && await realpath(parentPath) === parentPath, 'BRIDGE_CACHE_PARENT_CHANGED');
  requireThat(!signal.aborted, 'CANCELLED');
  const { cacheMode: _mode, ...options } = core;
  // Core checks ownership, directory identity, locks, index and chunks. A
  // create/EEXIST race or any failed open causes no retry or fallback here. After
  // joined cleanup, a later GET/restart makes a fresh choice for the same path,
  // including a complete cache left by an interrupted network operation.
  return { ...options, reuseCache };
}

export function providerHttpConfiguration(config) {
  exact(config, ['core', 'variables', ...(config && Object.hasOwn(config, 'airQuality') ? ['airQuality'] : [])], 'BRIDGE_CONFIG_INVALID');
  const core = coreConfiguration(config.core);
  let airQuality;
  if (Object.hasOwn(config, 'airQuality')) {
    exact(config.airQuality, ['core', 'variables'], 'BRIDGE_CONFIG_INVALID');
    const aqCore = coreConfiguration(config.airQuality.core, true);
    requireThat(aqCore.query.latitude === core.query.latitude && aqCore.query.longitude === core.query.longitude,
      'BRIDGE_AREA_MISMATCH');
    airQuality = Object.freeze({ core: aqCore,
      variables: providerVariables(config.airQuality.variables === undefined ? ['pm2_5', 'pm10'] : config.airQuality.variables) });
  }
  return Object.freeze({ core, variables: providerVariables(config.variables), ...(airQuality ? { airQuality } : {}) });
}

// Snapshot an explicit, owner-controlled dedicated build directory. Its eligible
// assets are public to this local UI: do not select a repository/config directory.
// No request-time filesystem paths, symlink traversal or directory listings.
async function staticAssets(directory, profile) {
  absolute(directory);
  requireThat(typeof process.getuid === 'function' && await realpath(directory) === directory, 'STATIC_ROOT_INVALID');
  const files = new Map(); let entries = 0, bytes = 0;
  async function visit(folder, prefix, depth) {
    const info = await lstat(folder);
    requireThat(depth <= 16 && info.isDirectory() && !info.isSymbolicLink()
      && info.uid === process.getuid() && !(info.mode & 0o022), 'STATIC_ROOT_INVALID');
    const children = await readdir(folder, { withFileTypes: true });
    requireThat((entries += children.length) <= 1024, 'STATIC_BUDGET_EXCEEDED');
    for (const entry of children) {
      const name = entry.name;
      requireThat(name.length <= 255 && !/[\x00-\x1f\x7f\\]/.test(name), 'STATIC_ROOT_INVALID');
      const path = join(folder, name), relative = `${prefix}/${name}`;
      if (entry.isDirectory()) { await visit(path, relative, depth + 1); continue; }
      requireThat(entry.isFile(), 'STATIC_ROOT_INVALID');
      // Directory entries only guide traversal. Authorize and size each asset
      // using the opened descriptor, never a pathname check made before open.
      const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try {
        const before = await file.stat();
        requireThat(before.isFile() && before.uid === process.getuid() && !(before.mode & 0o022)
          && before.nlink === 1, 'STATIC_ROOT_INVALID');
        const type = profile.exactMime[relative] ?? profile.mime[extname(name)];
        if (!type || name.startsWith('.')) continue;
        requireThat(before.size <= MAX_ASSET && (bytes += before.size) <= MAX_STATIC, 'STATIC_BUDGET_EXCEEDED');
        const data = Buffer.alloc(before.size + 1);
        let offset = 0;
        while (offset < data.length) {
          const { bytesRead } = await file.read(data, offset, data.length - offset, offset);
          if (!bytesRead) break;
          offset += bytesRead;
        }
        const after = await file.stat();
        requireThat(offset === before.size && after.size === before.size && after.mtimeMs === before.mtimeMs
          && after.ctimeMs === before.ctimeMs && after.uid === before.uid && after.mode === before.mode
          && after.nlink === 1, 'STATIC_ROOT_CHANGED');
        files.set(relative, { type, bytes: data.subarray(0, offset) });
      } finally { await file.close(); }
    }
  }
  await visit(directory, '', 0);
  requireThat(files.has('/index.html'), 'STATIC_INDEX_REQUIRED');
  return files;
}

function resultBytes(result, configuration, airQuality = false) {
  const { core, variables } = configuration;
  const delivery = result?.delivery;
  exact(delivery, ['mode', 'publisher_key', 'name', 'revision', 'manifest_id', 'sha256',
    'publication_expires_at', 'freshness', 'upstream_origin_attested', 'manifest_media_type_checked'], 'BRIDGE_RESULT_INVALID');
  requireThat(delivery.mode === 'core-cache' && delivery.publisher_key === core.publisherKey && delivery.name === core.name
    && Number.isSafeInteger(delivery.revision) && delivery.revision >= core.minRevision
    && typeof delivery.manifest_id === 'string' && /^[a-f0-9]{64}$/.test(delivery.manifest_id)
    && typeof delivery.sha256 === 'string' && /^[a-f0-9]{64}$/.test(delivery.sha256)
    && typeof delivery.publication_expires_at === 'string'
    && delivery.upstream_origin_attested === false && delivery.manifest_media_type_checked === false, 'BRIDGE_RESULT_INVALID');
  exact(delivery.freshness, ['stale', 'age_seconds', 'model_age_seconds', 'expires_at'], 'BRIDGE_RESULT_INVALID');
  requireThat(delivery.freshness.stale === false && Number.isSafeInteger(delivery.freshness.age_seconds)
    && delivery.freshness.age_seconds >= 0 && Number.isSafeInteger(delivery.freshness.model_age_seconds)
    && delivery.freshness.model_age_seconds >= 0, 'BRIDGE_RESULT_INVALID');
  const project = airQuality ? toAirQualityProviderForecast : toProviderForecast;
  const projection = project(result.forecast, { variables, now: result.freshness?.checked_at,
    publicationExpires: delivery.publication_expires_at });
  requireThat(isDeepStrictEqual(result, { ...projection, delivery }), 'BRIDGE_RESULT_INVALID');
  requireThat(delivery.freshness.expires_at === projection.freshness.expires_at, 'BRIDGE_RESULT_INVALID');
  const forecast = result.forecast, query = core.query;
  requireThat(forecast.area.sharing === 'public-community' && forecast.area.latitude === query.latitude
    && forecast.area.longitude === query.longitude && forecast.source.model === query.model
    && forecast.source.model_run_at === query.run
    && (airQuality || Object.hasOwn(forecast.units, 'wind_10m') === query.includeWind
      && Object.hasOwn(forecast.units, 'precipitation') === query.includePrecipitation)
    && isDeepStrictEqual(forecast.samples.map(sample => sample.lead_hours), [...query.steps]), 'FORECAST_QUERY_MISMATCH');
  requireThat(!(airQuality ? airQualityFreshness : freshness)(forecast,
    new Date().toISOString(), delivery.publication_expires_at).stale, 'STALE_FORECAST');
  const bytes = Buffer.from(JSON.stringify(result));
  requireThat(bytes.length <= MAX_RESPONSE, 'BRIDGE_RESULT_TOO_LARGE');
  return bytes;
}

export async function startProviderHttp({ config, staticRoot, staticProfile = 'default', port, socketPath, requestDeadlineMs = 180000 },
  { fetchProvider = fetchCachedProvider, fetchAirQualityProvider = fetchCachedAirQualityProvider } = {}) {
  const configuration = providerHttpConfiguration(config);
  const unix = socketPath !== undefined, tcpPort = port === undefined ? 0 : port;
  requireThat((unix ? port === undefined && staticRoot === undefined && staticProfile === 'default'
    : Number.isInteger(tcpPort) && tcpPort >= 0 && tcpPort <= 65535)
    && Number.isInteger(requestDeadlineMs) && requestDeadlineMs >= 1 && requestDeadlineMs <= 180000
    && typeof staticProfile === 'string' && Object.hasOwn(STATIC_PROFILES, staticProfile),
  'BRIDGE_CONFIG_INVALID');
  const profile = STATIC_PROFILES[staticProfile], assets = unix ? new Map() : await staticAssets(staticRoot, profile);
  let origin = unix ? UNIX_ORIGIN : undefined, active = null, closing = unix, cleanupUnconfirmed = false;
  const controllers = new Set();
  function send(response, status, body, type = 'application/json', extraHeaders = {}) {
    if (response.destroyed || response.writableEnded) return;
    response.writeHead(status, { ...profile.headers, ...extraHeaders, 'Content-Type': type, 'Content-Length': body.length });
    response.end(body);
  }
  // Retry pacing is not a reservation or a promise that cleanup has completed.
  const error = (response, status, code) => send(response, status, Buffer.from(JSON.stringify({ error: code })),
    'application/json', status === 429 && code === 'FORECAST_BUSY' ? { 'Retry-After': '1' } : {});
  const server = createServer({ maxHeaderSize: 8192, headersTimeout: 5000, requestTimeout: 5000,
    keepAliveTimeout: 1000, connectionsCheckingInterval: 1000 }, (incoming, response) => {
    const counts = {};
    for (let i = 0; i < incoming.rawHeaders.length; i += 2) {
      const key = incoming.rawHeaders[i].toLowerCase(); counts[key] = (counts[key] ?? 0) + 1;
    }
    if (closing) return error(response, 503, 'FORECAST_UNAVAILABLE');
    if (counts.host !== 1 || incoming.headers.host !== origin.slice('http://'.length)
      || (counts.origin ?? 0) > 1 || (incoming.headers.origin !== undefined && incoming.headers.origin !== origin)
      || (incoming.headers['sec-fetch-site'] !== undefined && !['same-origin', 'none'].includes(incoming.headers['sec-fetch-site']))) {
      return error(response, 403, 'ORIGIN_REJECTED');
    }
    if (incoming.method !== 'GET') return error(response, 405, 'METHOD_NOT_ALLOWED');
    if (incoming.headers['transfer-encoding'] !== undefined || (incoming.headers['content-length'] !== undefined
      && incoming.headers['content-length'] !== '0') || !incoming.url || incoming.url.length > 2048
      || !incoming.url.startsWith('/') || incoming.url.startsWith('//') || /[?#]/.test(incoming.url)) {
      return error(response, 400, 'REQUEST_INVALID');
    }
    let path;
    try { path = decodeURIComponent(incoming.url); } catch { return error(response, 400, 'REQUEST_INVALID'); }
    if (/[\x00-\x1f\x7f\\]/.test(path) || path.split('/').some(part => part === '.' || part === '..')) {
      return error(response, 400, 'REQUEST_INVALID');
    }
    const airQuality = path === AQ_API;
    if (path !== API && !airQuality) {
      if (path.startsWith('/api/')) return error(response, 404, 'NOT_FOUND');
      const asset = assets.get(path === '/' ? '/index.html' : path)
        ?? (!extname(path) ? assets.get('/index.html') : null);
      if (!asset) return error(response, 404, 'NOT_FOUND');
      return send(response, 200, asset.bytes, asset.type);
    }
    const selected = airQuality ? configuration.airQuality : configuration;
    const unavailable = airQuality ? 'AIR_QUALITY_UNAVAILABLE' : 'FORECAST_UNAVAILABLE';
    if (!selected || cleanupUnconfirmed) return error(response, 503, unavailable);
    if (active) return error(response, 429, 'FORECAST_BUSY');
    const controller = new AbortController(); controllers.add(controller);
    const abort = () => controller.abort();
    incoming.once('aborted', abort);
    const disconnected = () => { if (!response.writableEnded) abort(); };
    response.once('close', disconnected);
    // Abort owns the operation; await its cleanup before reporting completion.
    // Otherwise a sequential weather -> AQ client receives 503 while the shared
    // slot is still occupied and immediately loses its next request to 429.
    // The existing socket timeout still bounds a backend that ignores abort.
    const timer = setTimeout(abort, requestDeadlineMs);
    active = (async () => {
      try {
        const fetch = airQuality ? fetchAirQualityProvider : fetchProvider;
        const core = await requestCore(selected.core, controller.signal);
        const result = await Promise.resolve().then(() => fetch(core,
          { variables: selected.variables, signal: controller.signal }));
        if (controller.signal.aborted) throw new Error('CANCELLED');
        send(response, 200, resultBytes(result, selected, airQuality));
      } catch (failure) {
        // The subprocess adapter distinguishes an ordinary failure after joined
        // cleanup from an unconfirmed process group. Settling that promise alone
        // cannot authorize another operation or report a clean bridge shutdown.
        if (failure?.code === 'CORE_CLEANUP_UNCONFIRMED') cleanupUnconfirmed = true;
        error(response, 503, unavailable);
      }
      finally {
        clearTimeout(timer); incoming.removeListener('aborted', abort); response.removeListener('close', disconnected);
        controllers.delete(controller); active = null;
      }
    })();
  });
  server.maxConnections = 16; server.maxRequestsPerSocket = 16;
  server.setTimeout(requestDeadlineMs + 5000, socket => socket.destroy());
  server.on('clientError', (_error, socket) => { socket.destroy(); });
  let unixCleanup;
  if (unix) {
    unixCleanup = await listenUnix(server, socketPath);
    closing = false;
  } else {
    await new Promise((done, fail) => {
      server.once('error', fail);
      server.listen(tcpPort, '127.0.0.1', () => { server.removeListener('error', fail); done(); });
    });
    origin = `http://127.0.0.1:${server.address().port}`;
  }
  let closePromise;
  async function close() {
    closing = true;
    for (const controller of controllers) controller.abort();
    const stopped = new Promise(done => server.close(done));
    server.closeAllConnections();
    const running = active;
    let timer;
    try {
      await Promise.race([Promise.all([stopped, running]), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('BRIDGE_CLEANUP_UNCONFIRMED')), 5000);
      })]);
      if (cleanupUnconfirmed) throw new Error('BRIDGE_CLEANUP_UNCONFIRMED');
    } finally {
      clearTimeout(timer);
      if (unixCleanup) await unixCleanup();
    }
  }
  return Object.freeze({ origin, ...(unix ? { socketPath } : {}), close() {
    closePromise ??= close();
    return closePromise;
  } });
}
