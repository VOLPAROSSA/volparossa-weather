// SPDX-License-Identifier: GPL-3.0-only
// Pure first-party validation. Expected values derive from the pinned Kit/Vite
// sources; an observed configuration never authorizes a callback or code hash.

/** @typedef {'name'|'command'|'mode'|'isBundled'|'isWorker'|'lib'|'watch'|'write'|'consumer'|'ssr'|'base'|'platform'|'renderBuiltUrl'|'devMode'|'moduleTypes'|'modulePreload'} ContextField */
/** @typedef {Record<ContextField,unknown>} ContextInput */
/** @typedef {{name:'ssr'|'client',consumer:'server'|'client',ssr:boolean,base:'/'|'./',platform:'node'|'browser'}} GraphEnvironment */

/** Only finite classifications enter diagnostics; no paths, source, environment
 * values, callback names or arbitrary strings/objects are serialized.
 * @param {unknown} value @returns {string} */
function classification(value) {
  if (value === undefined) return 'undefined';
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  return typeof value;
}

/** The caller authenticates expectedRenderBuiltUrl against the exact original
 * Kit method fingerprint and sealed source/configuration before passing it.
 * Identity then prevents replacement, even by a function with identical source.
 * All other predicates preserve the existing equality/truthiness controls.
 * @param {ContextInput} input @param {unknown} expectedRenderBuiltUrl
 * @returns {GraphEnvironment} */
export function validateVirtualContext(input, expectedRenderBuiltUrl) {
  const ssr = input.name === 'ssr';
  const preload = input.modulePreload;
  /** @type {[ContextField,boolean][]} */
  const checks = [
    ['name', input.name === 'ssr' || input.name === 'client'],
    ['command', input.command === 'build'],
    ['mode', input.mode === 'production'],
    ['isBundled', input.isBundled === true],
    ['isWorker', !input.isWorker],
    ['lib', !input.lib],
    ['watch', !input.watch],
    ['write', input.write === true],
    ['consumer', input.consumer === (ssr ? 'server' : 'client')],
    ['ssr', input.ssr === ssr],
    ['base', input.base === (ssr ? '/' : './')],
    ['platform', input.platform === (ssr ? 'node' : 'browser')],
    ['renderBuiltUrl', typeof expectedRenderBuiltUrl === 'function'
      && input.renderBuiltUrl === expectedRenderBuiltUrl],
    ['devMode', !input.devMode],
    ['moduleTypes', input.moduleTypes === undefined],
    ['modulePreload', preload !== null && typeof preload === 'object'
      && 'polyfill' in preload && preload.polyfill === true],
  ];
  for (const [key, valid] of checks) {
    if (!valid) throw new Error('P14_VIRTUAL_CONTEXT:' + key + ':' + classification(input[key]));
  }
  return { name: ssr ? 'ssr' : 'client', consumer: ssr ? 'server' : 'client', ssr,
    base: ssr ? '/' : './', platform: ssr ? 'node' : 'browser' };
}

/** Kit installs renderBuiltUrl for both builds. Pinned Vite therefore selects
 * the already approved relative preload source even for SSR with base '/'.
 * @param {GraphEnvironment} context
 * @returns {{insertPreload:boolean,isRelativeBase:boolean,renderBuiltUrl:true,optimizeModulePreloadRelativePaths:false}} */
export function preloadContextOptions(context) {
  return { insertPreload: !context.ssr, isRelativeBase: !context.ssr,
    renderBuiltUrl: true, optimizeModulePreloadRelativePaths: false };
}
