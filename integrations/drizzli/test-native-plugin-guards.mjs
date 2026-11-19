// SPDX-License-Identifier: GPL-3.0-only
// Pure first-party replays of the pinned constructor/provenance facts. Hash,
// callback and native-constructor seams are explicit simulations, not execution
// of Vite, Rolldown or a native component and not actual compiler proof.

/** @typedef {import('./native-plugin-guards.mjs').Plugin} Plugin */
/** @typedef {import('./native-plugin-guards.mjs').Digest} Digest */

/** @param {boolean} ok @param {string} name */
function assertNativeTest(ok, name) {
  if (!ok) throw new Error('P14_NATIVE_TEST_FAILED:' + name);
}

/** Shared fixture for the guard and actual first-party observer lifecycle tests.
 * Original constructor facts: own name/_options/enforce fields, shared class
 * prototype, eager callable bridges and Vite's resolver watch marker. Source
 * callbacks are represented by different first-party functions with explicitly
 * mocked original fingerprints. No original dependency code is evaluated. */
export function createNativePluginFixture() {
  // Only the fixture's explicit Proxy constructor is tracked here. Production
  // passes the pinned Node builtin util.types.isProxy; this is its inert seam.
  const proxies = new WeakSet();
  /** @param {unknown} value */
  const isProxy = (value) => value !== null && (typeof value === 'object' || typeof value === 'function') && proxies.has(value);
  /** @template {object} T @param {T} target @param {ProxyHandler<T>} handler @returns {T} */
  const proxy = (target, handler) => { const value = new Proxy(target, handler); proxies.add(value); return value; };
  /** @type {Map<string,Digest>} */
  const fingerprints = new Map();
  /** @param {string} value @param {Digest} expected */
  const stampText = (value, expected) => { fingerprints.set(value, expected); };
  /** @param {string} value @returns {Digest} */
  const digest = (value) => fingerprints.get(value) ?? { bytes: value.length, sha256: '0'.repeat(64) };
  /** @param {unknown} value @param {number} [depth] @returns {unknown} */
  const snapshot = (value, depth = 0) => {
    assertNativeTest(depth <= 12, 'snapshot-bound');
    if (typeof value === 'function') return { function_sha256: digest(Function.prototype.toString.call(value)).sha256 };
    if (value instanceof RegExp) return { source: value.source, flags: value.flags };
    if (value === undefined) return { undefined: true };
    if (value === null || typeof value !== 'object') return value;
    if (Array.isArray(value)) return value.map((entry) => snapshot(entry, depth + 1));
    return Object.fromEntries(Object.getOwnPropertyNames(value).sort().map((key) => [key, snapshot(Reflect.get(value, key), depth + 1)]));
  };

  class FixtureBuiltin {
    /** @type {string} */ name;
    /** @type {unknown} */ _options;
    /** @type {undefined} */ enforce;
    /** @param {string} name @param {unknown} [options] */
    constructor(name, options) { this.name = name; this._options = options; }
  }
  Object.defineProperty(FixtureBuiltin, 'name', { value: 'BuiltinPlugin' });
  stampText(Function.prototype.toString.call(FixtureBuiltin), { bytes: 175, sha256: 'c21074a9c48e2cd73b7dd8bb41390b3c69afa89af987a05d4cb8cd97aed169fd' });
  /** @param {unknown[]} args */
  async function callableBridgeFixture(...args) { void args; return null; }
  stampText(Function.prototype.toString.call(callableBridgeFixture), { bytes: 335, sha256: 'c840a97efc426bf192c8c1325ed61d87df768202d5de65ab43287889b69da46b' });
  /** @param {string} id @param {unknown} [options] @returns {Plugin} */
  const native = (id, options) => {
    const plugin = /** @type {Plugin} */ (new FixtureBuiltin(id, options));
    if (id === 'builtin:vite-json' || id === 'builtin:vite-resolve' || id === 'builtin:oxc-runtime') {
      // The source bridge may see four hooks and its exported getOrder method.
      // The registry captures the original constructed interface, rather than
      // learning arbitrary new hook keys from a build observation.
      for (const key of ['getOrder', 'resolveId', 'load', 'transform', 'watchChange']) Reflect.set(plugin, key, callableBridgeFixture);
    }
    if (id === 'builtin:vite-resolve') Reflect.set(plugin, 'perEnvironmentWatchChangeDuringDev', true);
    return plugin;
  };
  /** @param {string} id @param {unknown} environment @returns {Plugin|Plugin[]} */
  const produce = (id, environment) => {
    assertNativeTest(environment !== null && typeof environment === 'object' && 'name' in environment
      && (environment.name === 'ssr' || environment.name === 'client'), 'fixture-environment');
    const ssr = environment !== null && typeof environment === 'object' && 'name' in environment && environment.name === 'ssr';
    const options = id === 'builtin:vite-build-import-analysis'
      ? { preloadCode: 'fixture-preload', insertPreload: !ssr, optimizeModulePreloadRelativePaths: false,
        renderBuiltUrl: true, isRelativeBase: !ssr }
      : id === 'builtin:vite-alias' ? { entries: [{ find: '$lib', replacement: '/fixture/src/lib' }] }
      : { fixture: id, context: ssr ? 'ssr' : 'client' };
    const plugin = native(id, options);
    return id === 'builtin:vite-manifest'
      ? [{ name: 'native:manifest-envs' }, plugin, { name: 'native:manifest-compatible' }] : plugin;
  };
  /** @type {[string,string,number,string,(environment:unknown)=>Plugin|Plugin[]][]} */
  const rows = [
    ['alias', 'builtin:vite-alias', 323, '9be2df664e95147e3884648a1f3e152f01c46a8d82fadb0327aacca2071e85e2',
      /** @param {unknown} environment */ function aliasFixture(environment) { return produce('builtin:vite-alias', environment); }],
    ['vite:modulepreload-polyfill', 'builtin:vite-module-preload-polyfill', 186, 'acb56766656716383a2b54e02146b82be6ef68659942ea0dd14dd518628e4875',
      /** @param {unknown} environment */ function polyfillFixture(environment) { return produce('builtin:vite-module-preload-polyfill', environment); }],
    ['vite:resolve-builtin', 'builtin:vite-resolve', 103, '8028fce923826504508c554b7219a3174b7c6a543d4fb892839bd709bfda7892',
      /** @param {unknown} environment */ function resolveFixture(environment) { return produce('builtin:vite-resolve', environment); }],
    ['vite:oxc', 'builtin:vite-transform', 714, '9f3b0a4838e11c38bd2cc8e181536a414f985997b8e6fcd17b2c8cfb543c2386',
      /** @param {unknown} environment */ function transformFixture(environment) { return produce('builtin:vite-transform', environment); }],
    ['vite:dynamic-import-vars', 'builtin:vite-dynamic-import-vars', 411, '227c58ea194a082b3f03314b39b2b6c218a80c534ee855510adbb85bfbb3f521',
      /** @param {unknown} environment */ function dynamicFixture(environment) { return produce('builtin:vite-dynamic-import-vars', environment); }],
    ['vite:import-glob', 'builtin:vite-import-glob', 301, '9569c98bbf185719188aacc8282cfead29981e4081100ad7b26d4a0ae545aa4a',
      /** @param {unknown} environment */ function globFixture(environment) { return produce('builtin:vite-import-glob', environment); }],
    ['native:import-analysis-build', 'builtin:vite-build-import-analysis', 319, 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376',
      /** @param {unknown} environment */ function preloadFixture(environment) { return produce('builtin:vite-build-import-analysis', environment); }],
    ['native:manifest', 'builtin:vite-manifest', 2731, '033d2c83675b1300ccbc918ca07ae6a97db60d1f460a9aedabaa9c892414ed10',
      /** @param {unknown} environment */ function manifestFixture(environment) { return produce('builtin:vite-manifest', environment); }],
    ['native:reporter', 'builtin:vite-reporter', 631, '36746a61881d5251859d2c592146459c43f93138708262a888e7254fbad2bfc4',
      /** @param {unknown} environment */ function reporterFixture(environment) { return produce('builtin:vite-reporter', environment); }],
  ];
  /** @type {Map<string,Plugin>} */
  const factories = new Map();
  for (const [name, , bytes, sha256, handler] of rows) {
    stampText(Function.prototype.toString.call(handler), { bytes, sha256 });
    const plugin = { name };
    Reflect.set(plugin, 'applyToEnvironment', handler);
    factories.set(name, plugin);
  }
  function disabledRuntimeFixture() { return false; }
  stampText(Function.prototype.toString.call(disabledRuntimeFixture), { bytes: 80, sha256: 'ae702863cd45e942b89b489bd64bd78085dc89d89e4e5524d9eb73f35280ab45' });
  const disabled = { ...native('builtin:oxc-runtime'), applyToEnvironment: disabledRuntimeFixture };
  const json = native('builtin:vite-json', { namedExports: true, stringify: 'auto', minify: true });
  const fallback = native('builtin:vite-load-fallback');
  const user = { name: 'fixture-user' };
  /** @param {string} name @returns {Plugin} */
  const factory = (name) => { const value = factories.get(name); assertNativeTest(value !== undefined, 'factory-name'); if (!value) throw new Error('fixture'); return value; };
  const core = [factory('alias'), factory('vite:modulepreload-polyfill'), factory('vite:resolve-builtin'), disabled,
    factory('vite:oxc'), json, factory('vite:dynamic-import-vars'), factory('vite:import-glob'),
    factory('native:import-analysis-build'), factory('native:manifest'), factory('native:reporter'), fallback];
  /** A second Vite configuration constructs fresh plugins while the imported
   * Rolldown class/prototype remains the SAME cached dependency object.
   * @returns {Plugin[]} */
  const freshCore = () => {
    /** @type {Map<string,Plugin>} */
    const fresh = new Map();
    for (const [name, , , , handler] of rows) {
      const plugin = { name };
      Reflect.set(plugin, 'applyToEnvironment', handler);
      fresh.set(name, plugin);
    }
    /** @param {string} name @returns {Plugin} */
    const get = (name) => { const value = fresh.get(name); if (!value) throw new Error('fixture'); return value; };
    const runtime = { ...native('builtin:oxc-runtime'), applyToEnvironment: disabledRuntimeFixture };
    return [get('alias'), get('vite:modulepreload-polyfill'), get('vite:resolve-builtin'), runtime,
      get('vite:oxc'), native('builtin:vite-json', { namedExports: true, stringify: 'auto', minify: true }),
      get('vite:dynamic-import-vars'), get('vite:import-glob'), get('native:import-analysis-build'),
      get('native:manifest'), get('native:reporter'), native('builtin:vite-load-fallback')];
  };
  /** @param {Plugin} producer @param {string} environment @returns {unknown} */
  const resultFor = (producer, environment) => {
    const handler = producer.applyToEnvironment;
    assertNativeTest(typeof handler === 'function', 'apply-function');
    return handler ? Reflect.apply(handler, undefined, [{ name: environment }]) : undefined;
  };

  /** Vite clone bridge source is mocked, while invocation preserves the actual
   * first-party hook handler, receiver, arguments and return value.
   * @param {unknown} original @param {string} key @returns {unknown} */
  const cloneHook = (original, key) => {
    const handler = typeof original === 'function' ? original
      : original !== null && typeof original === 'object' && 'handler' in original ? original.handler : undefined;
    if (typeof handler !== 'function') return original;
    /** @this {unknown} @param {unknown[]} args */
    function resolveBridgeFixture(...args) { return Reflect.apply(handler, this, args); }
    /** @this {unknown} @param {unknown[]} args */
    function loadBridgeFixture(...args) { return Reflect.apply(handler, this, args); }
    /** @this {unknown} @param {unknown[]} args */
    function transformBridgeFixture(...args) { return Reflect.apply(handler, this, args); }
    /** @this {unknown} @param {unknown[]} args */
    function otherBridgeFixture(...args) { return Reflect.apply(handler, this, args); }
    const bridge = key === 'resolveId' ? resolveBridgeFixture : key === 'load' ? loadBridgeFixture
      : key === 'transform' ? transformBridgeFixture : otherBridgeFixture;
    const expected = key === 'resolveId' ? { bytes: 164, sha256: 'ff289755ce31f36756e2b0b19286339848677398c9f2a3a868b24601735635cc' }
      : key === 'load' ? { bytes: 144, sha256: '7c54a44a40b1b02d9fdd0c3768169e41bb28d8255bb4e7ce3887f4085255435c' }
      : key === 'transform' ? { bytes: 168, sha256: '0c1d95bac0242e4203fd14d8f09a54de3e2ce053374a33a2dfbf42a87ee43d61' }
      : { bytes: 463, sha256: '856f666b8279dfb5b55b58b8fca41cad3220e34f015346304edbc227d5d39f55' };
    stampText(Function.prototype.toString.call(bridge), expected);
    if (typeof original === 'function') return bridge;
    if (original !== null && typeof original === 'object') return { ...original, handler: bridge };
    return original;
  };
  const cloneHooks = new Set(['options', 'buildStart', 'buildEnd', 'renderStart', 'renderError', 'renderChunk',
    'writeBundle', 'generateBundle', 'banner', 'footer', 'augmentChunkHash', 'outputOptions', 'resolveFileUrl',
    'intro', 'outro', 'closeBundle', 'closeWatcher', 'load', 'moduleParsed', 'watchChange', 'resolveDynamicImport',
    'resolveId', 'transform', 'onLog']);
  /** @param {Plugin[]} plugins @returns {Plugin[]} */
  const clones = (plugins) => plugins.map((plugin) => {
    const clone = /** @type {Plugin} */ (Object.assign(Object.create(Object.getPrototypeOf(plugin)), plugin));
    for (const key of Object.keys(clone)) if (cloneHooks.has(key)) Reflect.set(clone, key, cloneHook(Reflect.get(plugin, key), key));
    return clone;
  });
  return { prototype: FixtureBuiltin.prototype, digest, snapshot, stampText, isProxy, proxy, native, core, users: [user],
    user, factories, factory, disabled, json, fallback, freshCore, resultFor, clones };
}

/** @param {typeof import('./native-plugin-guards.mjs').createNativePluginGuard} create */
export function runNativePluginGuardTests(create) {
  let positive = 0;
  let negative = 0;
  /** @param {()=>unknown} operation @param {string} [expected] */
  const denied = (operation, expected) => {
    let message = '';
    try { operation(); } catch (error) { if (error instanceof Error) message = error.message; }
    assertNativeTest(message.startsWith('P14_NATIVE:') && (!expected || message === 'P14_NATIVE:' + expected)
      && !message.includes('PRIVATE-SENTINEL'), 'denial:' + (expected ?? 'native'));
    negative++;
  };
  /** @param {()=>unknown} operation @param {string} name */
  const readOnly = (operation, name) => {
    let blocked = false;
    try { blocked = operation() === false; } catch (error) { blocked = error instanceof TypeError; }
    assertNativeTest(blocked, 'readonly:' + name);
    negative++;
  };
  const setup = () => {
    const fixture = createNativePluginFixture();
    const guard = create(fixture.prototype, fixture.digest, fixture.snapshot, fixture.isProxy);
    guard.setUsers(fixture.users);
    const configuration = [...fixture.core, ...fixture.users];
    guard.configuration(configuration);
    /** @param {string} name @returns {Plugin[]} */
    const environment = (name) => {
      /** @type {Plugin[]} */
      const plugins = [];
      for (const producer of configuration) {
        if (!producer.applyToEnvironment) { plugins.push(producer); continue; }
        const result = fixture.resultFor(producer, name);
        guard.captureApply(producer, name, result);
        if (Array.isArray(result)) plugins.push(...result);
        else if (result !== null && typeof result === 'object' && 'name' in result) plugins.push(/** @type {Plugin} */ (result));
      }
      guard.environment(name, plugins);
      return plugins;
    };
    return { ...fixture, guard, configuration, environment };
  };

  for (const name of ['ssr', 'client']) {
    const f = setup();
    const plugins = f.environment(name);
    const clones = f.clones(plugins);
    f.guard.inputs(name, plugins, clones);
    f.guard.output({ format: 'es' }); // outputOptions occurs before buildStart.
    f.guard.environment(name, plugins);
    f.guard.inputs(name, plugins, clones);
    positive++;
    for (const mutation of ['extra', 'missing', 'duplicate', 'order', 'prototype', 'foreign', 'disabled']) {
      const c = setup();
      const selected = c.environment(name);
      const alias = selected[0];
      if (mutation === 'extra') selected.push(c.native('builtin:PRIVATE-SENTINEL'));
      if (mutation === 'missing') selected.splice(0, 1);
      if (mutation === 'duplicate') selected.push(alias);
      if (mutation === 'order') [selected[0], selected[1]] = [selected[1], selected[0]];
      if (mutation === 'prototype') Object.setPrototypeOf(alias, {});
      if (mutation === 'foreign') selected[0] = c.native('builtin:vite-alias', alias._options);
      if (mutation === 'disabled') selected.push(c.disabled);
      denied(() => c.guard.environment(name, selected));
    }
    for (const mutation of ['append', 'replace', 'prototype', 'options', 'hook']) {
      const c = setup();
      const selected = c.environment(name);
      const input = c.clones(selected);
      c.guard.inputs(name, selected, input);
      if (mutation === 'append') input.push(c.native('builtin:vite-alias', {}));
      if (mutation === 'replace') input[0] = c.native('builtin:vite-alias', input[0]._options);
      if (mutation === 'prototype') Object.setPrototypeOf(input[0], {});
      if (mutation === 'options') input[0]._options = { same: 'PRIVATE-SENTINEL' };
      if (mutation === 'hook') Reflect.set(input[0], 'transform', () => null);
      denied(() => c.guard.environment(name, selected));
    }
    const inputForeign = setup();
    const envForeign = inputForeign.environment(name);
    const foreign = inputForeign.clones(envForeign);
    foreign[0]._options = { entries: [] };
    denied(() => inputForeign.guard.inputs(name, envForeign, foreign), 'input-options-reference');
    const bridge = setup();
    const envBridge = bridge.environment(name);
    const inputBridge = bridge.clones(envBridge);
    const jsonClone = inputBridge.find((plugin) => plugin.name === 'builtin:vite-json');
    assertNativeTest(jsonClone !== undefined, 'json-clone');
    if (jsonClone) Reflect.set(jsonClone, 'transform', () => null);
    denied(() => bridge.guard.inputs(name, envBridge, inputBridge), 'input-bridge-source');
  }
  {
    const f = setup();
    const ssr = f.environment('ssr');
    const client = f.environment('client');
    client[0] = ssr[0];
    denied(() => f.guard.environment('client', client), 'environment-producer');
    denied(() => f.guard.environment('worker', ssr), 'environment');
  }
  for (const kind of ['user', 'factory', 'source', 'duplicate', 'direct', 'config-append', 'config-replace', 'disabled']) {
    const f = createNativePluginFixture();
    const guard = create(f.prototype, f.digest, f.snapshot, f.isProxy);
    if (kind === 'user') { denied(() => guard.setUsers([f.native('builtin:vite-alias', {})]), 'user-native'); continue; }
    guard.setUsers(kind === 'factory' ? [f.factory('alias')] : f.users);
    const config = [...f.core, ...f.users];
    if (kind === 'source') Reflect.set(f.factory('alias'), 'applyToEnvironment', () => true);
    if (kind === 'duplicate') config.push(f.factory('alias'));
    if (kind === 'direct') config.unshift(f.native('builtin:vite-alias', {}));
    if (kind === 'disabled') Reflect.set(f.disabled, 'applyToEnvironment', () => true);
    if (kind === 'config-append' || kind === 'config-replace') {
      guard.configuration(config);
      if (kind === 'config-append') config.push({ name: 'PRIVATE-SENTINEL' });
      else config[0] = { ...config[0] };
      denied(() => guard.configuration(config));
    } else denied(() => guard.configuration(config));
  }
  {
    const f = setup();
    const foreign = { ...f.factory('alias') };
    denied(() => f.guard.captureApply(foreign, 'ssr', f.native('builtin:vite-alias', {})), 'foreign-producer');
    denied(() => f.guard.captureApply(f.disabled, 'ssr', true), 'disabled-selected');
    denied(() => f.guard.captureApply(f.factory('alias'), 'ssr', false), 'apply-result');
    const result = f.resultFor(f.factory('alias'), 'ssr');
    f.guard.captureApply(f.factory('alias'), 'ssr', result);
    denied(() => f.guard.captureApply(f.factory('alias'), 'ssr', f.resultFor(f.factory('alias'), 'ssr')), 'apply-duplicate');
  }
  {
    const f = setup();
    const original = f.json.transform;
    assertNativeTest(typeof original === 'function', 'controlled-original');
    const observed = () => null;
    Reflect.set(f.json, 'transform', observed);
    f.guard.controlledHook(f.json, 'transform', original, observed);
    f.guard.configuration(f.configuration);
    positive++;
    Reflect.set(f.json, 'transform', () => null);
    denied(() => f.guard.configuration(f.configuration));
  }
  {
    const f = setup();
    const before = Object.getOwnPropertyDescriptor(f.prototype, 'constructor');
    Object.defineProperty(f.prototype, 'constructor', { ...before, value: function changedConstructor() {} });
    denied(() => f.guard.configuration(f.configuration));
    if (before) Object.defineProperty(f.prototype, 'constructor', before);
  }
  {
    const f = setup();
    const callback = function sameBytes() {};
    const replacement = function sameBytes() {};
    assertNativeTest(callback !== replacement && callback.toString() === replacement.toString(), 'deep-callback-fixture');
    // A selected factory constructs its own options before handing the object
    // to the registry. Afterwards even identical-source callback replacement
    // is rejected, rather than accepted from a matching string fingerprint.
    const alias = f.native('builtin:vite-alias', { nested: { callback } });
    f.guard.captureApply(f.factory('alias'), 'ssr', alias);
    const options = alias._options;
    assertNativeTest(options !== null && typeof options === 'object' && 'nested' in options, 'deep-options');
    if (options !== null && typeof options === 'object' && 'nested' in options
        && options.nested !== null && typeof options.nested === 'object') Reflect.set(options.nested, 'callback', replacement);
    denied(() => f.guard.configuration(f.configuration), 'identity-value');
  }
  for (const output of [{ plugins: [{ name: 'foreign-output' }] }, [{ format: 'es', plugins: [{}] }], null]) {
    const f = setup();
    denied(() => f.guard.output(output));
  }
  {
    const f = createNativePluginFixture();
    const foreignPrototype = Object.create(Object.prototype);
    Object.defineProperty(foreignPrototype, 'constructor', Object.getOwnPropertyDescriptor(f.prototype, 'constructor') ?? {});
    denied(() => create(foreignPrototype, f.digest, f.snapshot, f.isProxy), 'constructor-shape');
    let calls = 0;
    const proxyPrototype = f.proxy(f.prototype, { ownKeys() { calls++; return []; } });
    denied(() => create(proxyPrototype, f.digest, f.snapshot, f.isProxy), 'proxy');
    assertNativeTest(calls === 0, 'prototype-proxy-not-inspected');
    Object.defineProperty(f.prototype.constructor, Symbol.hasInstance, { value: () => true });
    denied(() => create(f.prototype, f.digest, f.snapshot, f.isProxy), 'constructor-shape');
  }
  for (const kind of ['callback', 'getter', 'proxy']) {
    const f = createNativePluginFixture();
    const guard = create(f.prototype, f.digest, f.snapshot, f.isProxy);
    guard.setUsers(f.users);
    let calls = 0;
    if (kind === 'callback') Reflect.set(f.json, 'transform', () => null);
    if (kind === 'getter') f.json._options = { get namedExports() { calls++; return true; }, stringify: 'auto', minify: true };
    if (kind === 'proxy') f.json._options = f.proxy({}, { ownKeys() { calls++; return []; } });
    denied(() => guard.configuration([...f.core, ...f.users]));
    assertNativeTest(calls === 0, 'native-options-unsafe-interface-not-invoked');
  }
  {
    const f = setup();
    const env = f.environment('ssr');
    const clones = f.clones(env);
    const userClone = clones.find((plugin) => plugin.name === f.user.name);
    assertNativeTest(userClone !== undefined, 'nonnative-clone');
    if (userClone) Reflect.set(userClone, 'options', () => ({}));
    denied(() => f.guard.inputs('ssr', env, clones), 'input-hook-source-key');
  }
  {
    const f = setup();
    const env = f.environment('ssr');
    const clones = f.clones(env);
    f.guard.inputs('ssr', env, clones);
    const userClone = clones.find((plugin) => plugin.name === f.user.name);
    let calls = 0;
    if (userClone) Object.defineProperty(userClone, 'options', { get() { calls++; return () => ({}); }, configurable: true });
    denied(() => f.guard.environment('ssr', env), 'input-hook-key');
    assertNativeTest(calls === 0, 'late-clone-getter-not-invoked');
  }
  {
    const f = createNativePluginFixture();
    // Four ordinary callable hooks without enumerable getOrder is supported
    // too: no unproven NAPI enumeration detail is promoted into authority.
    Reflect.deleteProperty(f.json, 'getOrder');
    const guard = create(f.prototype, f.digest, f.snapshot, f.isProxy);
    guard.setUsers(f.users);
    guard.configuration([...f.core, ...f.users]);
    positive++;
  }
  {
    const f = setup();
    const env = f.environment('ssr');
    const input = f.clones(env);
    f.guard.inputs('ssr', env, input);
    f.guard.finalizeInputs('ssr', env, input);
    f.guard.environment('ssr', env);
    assertNativeTest(Object.isFrozen(input) && Object.isFrozen(f.prototype)
      && Object.isFrozen(f.prototype.constructor), 'finalized-array-and-class');
    assertNativeTest(typeof f.json.transform === 'function' && !Object.isFrozen(f.json.transform)
      && Reflect.set(f.user, 'apiState', true), 'callbacks-and-original-user-api-not-frozen');
    const alias = input[0];
    readOnly(() => Reflect.set(input, '0', input[1]), 'input-entry');
    readOnly(() => input.push(alias), 'input-append');
    readOnly(() => Reflect.set(alias, 'name', 'builtin:vite-load-fallback'), 'native-name');
    readOnly(() => Reflect.setPrototypeOf(alias, {}), 'native-prototype');
    const user = input.find((plugin) => plugin.name === f.user.name);
    assertNativeTest(user !== undefined, 'final-user-clone');
    if (user) {
      readOnly(() => Reflect.set(user, 'options', () => ({})), 'observer-hook');
      readOnly(() => Reflect.defineProperty(user, 'transform', { value: () => null }), 'late-hook');
      readOnly(() => Reflect.set(user, '_parallel', { fileUrl: 'PRIVATE-SENTINEL' }), 'parallel-marker');
      readOnly(() => Reflect.set(user, 'name', 'builtin:vite-alias'), 'clone-name');
      assertNativeTest(Reflect.set(user, 'apiCache', { mutable: true }), 'js-api-cache-remains-mutable');
    }
    readOnly(() => Reflect.defineProperty(f.prototype.constructor, Symbol.hasInstance, { value: () => true }), 'native-has-instance');
    // Original normalizers use fresh arrays and preserve plugin references.
    const normalized = input.flat().filter(Boolean);
    assertNativeTest(normalized !== input && normalized.length === input.length
      && normalized.every((plugin, index) => plugin === input[index]), 'source-normalization-after-freeze');
    f.guard.environment('ssr', env);
    positive++;

    // Exact same frozen imported class/prototype, fresh nested client config.
    const nested = create(f.prototype, f.digest, f.snapshot, f.isProxy);
    nested.setUsers(f.users);
    const nestedConfig = [...f.freshCore(), ...f.users];
    nested.configuration(nestedConfig);
    /** @type {Plugin[]} */
    const nestedEnv = [];
    for (const producer of nestedConfig) {
      if (!producer.applyToEnvironment) { nestedEnv.push(producer); continue; }
      const result = f.resultFor(producer, 'client');
      nested.captureApply(producer, 'client', result);
      if (Array.isArray(result)) nestedEnv.push(...result);
      else if (result !== null && typeof result === 'object' && 'name' in result) nestedEnv.push(/** @type {Plugin} */ (result));
    }
    nested.environment('client', nestedEnv);
    const nestedInput = f.clones(nestedEnv);
    nested.inputs('client', nestedEnv, nestedInput);
    nested.finalizeInputs('client', nestedEnv, nestedInput);
    nested.environment('client', nestedEnv);
    positive++;
  }
  {
    const f = setup();
    /** @type {{format:string,plugins:unknown[]}} */
    const output = { format: 'es', plugins: [] };
    f.guard.output(output);
    f.guard.finalizeOutput(output);
    readOnly(() => output.plugins.push({}), 'output-array');
    readOnly(() => Reflect.set(output, 'plugins', [{ name: 'foreign' }]), 'output-owner-field');
    const absent = { format: 'es' };
    f.guard.finalizeOutput(absent);
    readOnly(() => Reflect.set(absent, 'plugins', [{ name: 'foreign' }]), 'absent-output-plugin-field');
    assertNativeTest(Reflect.set(absent, 'fileName', 'still-mutable.js'), 'output-other-fields-mutable');
    positive++;
  }
  {
    const f = setup();
    let calls = 0;
    const toggling = { get plugins() { calls++; return calls === 1 ? [] : [{ name: 'foreign-output' }]; } };
    denied(() => f.guard.output(toggling), 'output-plugin-accessor');
    assertNativeTest(calls === 0, 'output-getter-never-invoked');
    const inherited = Object.create({ plugins: [] });
    denied(() => f.guard.output(inherited), 'output-inherited-plugins');
    const proxy = f.proxy({ plugins: [] }, { get() { calls++; return []; } });
    denied(() => f.guard.output(proxy), 'proxy');
    assertNativeTest(calls === 0, 'output-proxy-trap-never-invoked');
    const nested = f.proxy([], { get() { calls++; return []; } });
    denied(() => f.guard.output({ plugins: nested }));
    assertNativeTest(calls === 0, 'plugins-proxy-trap-never-invoked');
  }
  {
    const f = setup();
    f.guard.output(undefined);
    f.guard.output([{ format: 'es' }, { plugins: [] }]);
    positive++;
  }
  return { passed: true, positive_cases: positive, negative_cases: negative,
    complete_ssr_client_native_sequences: true, source_bound_constructor_and_factory_replay: true,
    producer_identity_prototype_hooks_and_nested_callback_identity: true,
    input_clone_and_output_plugin_boundaries: true, readonly_dispatch_and_hook_authority_boundaries: true,
    same_cached_frozen_class_nested_client: true, getter_and_proxy_interfaces_never_invoked: true,
    explicit_mock_hash_and_native_interfaces: true,
    dependency_or_native_execution: false };
}
