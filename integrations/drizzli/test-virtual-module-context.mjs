// SPDX-License-Identifier: GPL-3.0-only
// Pure fixtures for the exact context guard; runnable in controlled V8 or Node.
// No producer, native code, filesystem, network or host dependency is imported.

/** @param {boolean} ok @param {string} name */
function assert(ok, name) {
  if (!ok) throw new Error('P14_CONTEXT_TEST_FAILED:' + name);
}

/** @param {typeof import('./virtual-module-context.mjs').validateVirtualContext} validate
 * @param {typeof import('./virtual-module-context.mjs').preloadContextOptions} preloadOptions */
export function runVirtualContextTests(validate, preloadOptions) {
  let positive = 0;
  let negative = 0;
  const callback = function renderBuiltUrl() {};
  // Different function identity, deliberately identical source text.
  const replacement = function renderBuiltUrl() {};
  assert(callback !== replacement && callback.toString() === replacement.toString(), 'callback-fixture');

  /** Source-derived resolved field matrix: approved Vite 8.3.1 + Kit 2.70.1.
   * @param {boolean} ssr @returns {import('./virtual-module-context.mjs').ContextInput} */
  const fixture = (ssr) => ({ name: ssr ? 'ssr' : 'client', command: 'build', mode: 'production',
    isBundled: true, isWorker: false, lib: false, watch: null, write: true,
    consumer: ssr ? 'server' : 'client', ssr, base: ssr ? '/' : './',
    platform: ssr ? 'node' : 'browser', renderBuiltUrl: callback, devMode: undefined,
    moduleTypes: undefined, modulePreload: { polyfill: true } });

  /** @param {import('./virtual-module-context.mjs').ContextInput} input
   * @param {import('./virtual-module-context.mjs').ContextField} key
   * @param {unknown} [expected] */
  const refused = (input, key, expected = callback) => {
    let message = '';
    try { validate(input, expected); } catch (error) {
      if (error instanceof Error) message = error.message;
    }
    assert(message.startsWith('P14_VIRTUAL_CONTEXT:' + key + ':'), 'refuse-' + key);
    assert(message.length <= 80 && !message.includes('PRIVATE-SENTINEL'), 'bounded-private-' + key);
    negative++;
    return message;
  };

  for (const ssr of [true, false]) {
    const original = fixture(ssr);
    const context = validate(original, callback);
    assert(context.name === (ssr ? 'ssr' : 'client') && context.ssr === ssr
      && context.consumer === (ssr ? 'server' : 'client')
      && context.base === (ssr ? '/' : './') && context.platform === (ssr ? 'node' : 'browser'), 'full-context');
    assert(Object.keys(context).sort().join(',') === 'base,consumer,name,platform,ssr', 'unchanged-graph-schema');
    const flags = preloadOptions(context);
    assert(flags.renderBuiltUrl === true && flags.insertPreload === !ssr
      && flags.isRelativeBase === !ssr && flags.optimizeModulePreloadRelativePaths === false, 'native-preload-context');
    assert(original.renderBuiltUrl === callback, 'context-does-not-replace-callback');
    positive++;

    /** @type {[import('./virtual-module-context.mjs').ContextField,unknown][]} */
    const mutations = [
      ['name', 'PRIVATE-SENTINEL-environment'], ['command', 'serve'], ['mode', 'development'],
      ['isBundled', false], ['isWorker', true], ['lib', { entry: 'PRIVATE-SENTINEL-path' }],
      ['watch', { include: 'PRIVATE-SENTINEL-path' }], ['write', false],
      ['consumer', ssr ? 'client' : 'server'], ['ssr', !ssr], ['ssr', 'PRIVATE-SENTINEL-entry'],
      ['base', ssr ? './' : '/'], ['base', 'https://PRIVATE-SENTINEL/'],
      ['platform', ssr ? 'browser' : 'node'], ['renderBuiltUrl', undefined], ['renderBuiltUrl', null],
      ['renderBuiltUrl', true], ['renderBuiltUrl', 'PRIVATE-SENTINEL-code'],
      ['renderBuiltUrl', () => ({ runtime: 'PRIVATE-SENTINEL-code' })], ['renderBuiltUrl', replacement],
      ['devMode', true], ['moduleTypes', { '.js': 'copy' }], ['moduleTypes', { '.css': 'js' }],
      ['modulePreload', false], ['modulePreload', undefined], ['modulePreload', null],
      ['modulePreload', { polyfill: false }], ['modulePreload', {}], ['modulePreload', 'PRIVATE-SENTINEL'],
    ];
    for (const [key, value] of mutations) refused({ ...original, [key]: value }, key);
    refused(original, 'renderBuiltUrl', replacement);
    refused(original, 'renderBuiltUrl', true);
    // No expected callback may be inferred from an absent observed callback.
    refused({ ...original, renderBuiltUrl: null }, 'renderBuiltUrl', null);

    const multiple = { ...original, mode: 'PRIVATE-SENTINEL-mode', isBundled: false, renderBuiltUrl: replacement };
    assert(refused(multiple, 'mode') === 'P14_VIRTUAL_CONTEXT:mode:string', 'first-failure-order');
  }
  return { passed: true, positive_contexts: positive, negative_contexts: negative,
    ssr_and_client: true, callback_identity: true, native_preload_context: true,
    first_failure_diagnostic_bounded: true };
}
