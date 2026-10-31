// SPDX-License-Identifier: GPL-3.0-only
// Actual first-party observer integration, with explicit external IO/hash/native
// seams. Constructor/configuration replay derives from pinned original sources;
// no Vite, Rolldown, native component, CSS compiler or host facility is executed.

/** @typedef {{name:string,enforce?:'pre'|'post',_options?:unknown}} FixturePlugin */
/** @typedef {{root:string,inlineConfig:object,command:string,mode:string,isWorker:boolean,isBundled:boolean,base:string,consumer:string,experimental:{renderBuiltUrl:unknown},build:{ssr:boolean,lib:boolean,watch:null,write:boolean,modulePreload:{polyfill:boolean},rolldownOptions:{platform:string}},plugins:FixturePlugin[]}} FixtureConfig */
/** @typedef {{name:string,config:FixtureConfig,plugins:FixturePlugin[]}} FixtureEnvironment */
/** @typedef {{environment:FixtureEnvironment}} FixtureReceiver */
/** @typedef {{plugins:FixturePlugin[],moduleTypes:{'.css':string},output?:unknown}} FixtureInput */
/** @typedef {FixturePlugin & {config:{handler:(config:{plugins:FixturePlugin[]},environment:{command:string,mode:string})=>Promise<void>},configResolved:(config:FixtureConfig)=>void,options:{handler:(this:FixtureReceiver,options:FixtureInput)=>unknown},outputOptions:{handler:(this:FixtureReceiver,options:object)=>unknown},buildStart:{handler:(this:FixtureReceiver,options:object)=>unknown},transform:{handler:(this:FixtureReceiver,code:string,id:string)=>unknown},generateBundle:{handler:(this:FixtureReceiver,options:object,bundle:object)=>unknown}} FixtureObserver */
/** @typedef {{captureLoad:typeof import('./virtual-module-guards.mjs').captureLoad,observeHook:typeof import('./virtual-module-guards.mjs').observeHook,observeResult:typeof import('./virtual-module-guards.mjs').observeResult,rejectLateTransform:typeof import('./virtual-module-guards.mjs').rejectLateTransform,replaceHandler:typeof import('./virtual-module-guards.mjs').replaceHandler,validateVirtualContext:typeof import('./virtual-module-context.mjs').validateVirtualContext,preloadContextOptions:typeof import('./virtual-module-context.mjs').preloadContextOptions,createNativePluginGuard:typeof import('./native-plugin-guards.mjs').createNativePluginGuard,createNativePluginFixture:typeof import('./test-native-plugin-guards.mjs').createNativePluginFixture}} GuardDependencies */

/** @param {boolean} ok @param {string} name */
function assertLifecycle(ok, name) {
  if (!ok) throw new Error('P14_LIFECYCLE_TEST_FAILED:' + name);
}

/** @param {FixturePlugin} plugin @param {string} key
 * @returns {(this:FixtureReceiver,...args:unknown[])=>unknown} */
function fixtureHook(plugin, key) {
  const value = Reflect.get(plugin, key);
  const handler = typeof value === 'function' ? value
    : value !== null && typeof value === 'object' && 'handler' in value ? value.handler : undefined;
  assertLifecycle(typeof handler === 'function', 'hook-' + key);
  return /** @type {(this:FixtureReceiver,...args:unknown[])=>unknown} */ (handler);
}

/** @param {string} source @param {GuardDependencies} guards */
export async function runObserverLifecycleTests(source, guards) {
  const imports = [
    "import { createHash } from 'node:crypto';",
    "import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';",
    "import { relative, resolve } from 'node:path';",
    "import { types as nodeTypes } from 'node:util';",
    "import { viteBuildImportAnalysisPlugin } from 'rolldown/experimental';",
    "import { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler } from './virtual-module-guards.mjs';",
    "import { validateVirtualContext, preloadContextOptions } from './virtual-module-context.mjs';",
    "import { createNativePluginGuard } from './native-plugin-guards.mjs';",
  ];
  for (const line of imports) {
    assertLifecycle(source.split(line + '\n').length === 2, 'exact-import-seam');
    source = source.replace(line + '\n', '');
  }
  const declaration = 'export default function sourceModuleGraph(userOptions)';
  const captureDeclaration = 'export async function captureUserPlugins(options)';
  assertLifecycle(source.split(captureDeclaration).length === 2, 'exact-user-capture-seam');
  source = source.replace(captureDeclaration, 'async function captureUserPlugins(options)');
  assertLifecycle(source.split(declaration).length === 2, 'exact-factory-seam');
  source = source.replace(declaration, 'function sourceModuleGraph(userOptions)');
  assertLifecycle(!/^import /m.test(source) && !/^export /m.test(source), 'no-other-module-seams');
  const callback = function approvedCallback() {};
  const identicalCallback = function approvedCallback() {};
  const shortCallback = function shortCallback() {};
  const changedCallback = function changedCallback() {};
  /** @type {Record<string,string>} */
  const kitCode = { '\0virtual:__sveltekit/env': 'fixture-kit-env', '\0virtual:__sveltekit/server': 'fixture-kit-server' };
  /** @param {string} id */
  const kitLoad = function approvedKitLoad(id) { return kitCode[id] ?? null; };
  assertLifecycle(callback !== identicalCallback && callback.toString() === identicalCallback.toString(), 'callback-identity-fixture');
  /** @type {Record<string,string>} */
  const members = {
    '@sveltejs/kit/src/exports/vite/index.js': '48a56f687eeb0429ee4a2138fe15e4ab4d93621d07e47c5dacc44647ea4215f6',
    '@sveltejs/kit/src/core/env.js': '95f4c3419ed4b33657c4b86450fc839f3795e2c46f73f2d9524521b79f92a000',
    'vite/dist/node/chunks/node.js': '5a604cb8f97126675dbdf9044c919b0fd1fe1280bfa4077de225e6adfa213e4a',
    'rolldown/dist/shared/constructors-xEvVj3lN.mjs': '087234cdd6903f7d5d1fd5e44a4cec61965c8755fa36c8d06f26a1a486d65de3',
    'rolldown/dist/experimental-index.mjs': 'c7e3856c8d6b65cbacccc4b1c54aa582d0c34bd5e6040b0a6415c0dbd42e4905',
    'rolldown/dist/shared/normalize-string-or-regex-F14uvr6D.mjs': 'e1cff9111ea8819b0890ae35b1cfd2938a53bf755c6c176d79387133ed7e5f1c',
    'rolldown/dist/shared/binding-BY0qR5iS.mjs': '8c571a4e4ac9561df9d6d7370d6c0d506922b6c106fd693cb2b75b47c3ab028a',
    'rolldown/dist/shared/bindingify-input-options-XrReX_BJ.mjs': 'a778028ca12765b4604b9cb04edf80e1dc6dc096bccbc893317aa03e02ab4890',
    'rolldown/dist/shared/create-bundler-option-YGKfBl_D.mjs': 'fe167cc4ec4b9432074978952993d0f2d18f0fab73a6dfd028b6f00f678727d9',
    '@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node': '34e3f5cc135d0fec7f0d9837e30413f1a151037b1568911f074048bf941d68e5',
  };
  /** @type {Record<string,string>} */
  const versions = { '@sveltejs/kit': '2.70.1', vite: '8.3.1', rolldown: '1.2.11', '@rolldown/binding-linux-x64-gnu': '1.2.11' };
  let positives = 0;
  let negatives = 0;
  let writes = 0;
  /** @type {{schema:number,virtualModules:{id:string}[]}[]} */
  const simulatedGraphs = [];
  /** @param {()=>unknown} action @param {string} expected */
  const refused = async (action, expected) => {
    let message = '';
    try { await action(); } catch (error) { if (error instanceof Error) message = error.message; }
    assertLifecycle(message === expected && !message.includes('PRIVATE-SENTINEL'), 'rejection:' + expected + ':got:' + message);
    negatives++;
  };
  /** @param {string} name @param {Record<string,unknown>} hooks @returns {FixturePlugin} */
  const actor = (name, hooks) => Object.assign({ name }, hooks);

  /** @param {ReturnType<GuardDependencies['createNativePluginFixture']>} [sharedFixture] @param {boolean} [fresh] */
  const harness = (sharedFixture, fresh = false) => {
    const fixture = sharedFixture ?? guards.createNativePluginFixture();
    const core = fresh ? fixture.freshCore() : fixture.core;
    fixture.stampText(callback.toString(), { bytes: 1076, sha256: 'b2e81ff8fba88a56e0ce4c2ef946bb15a7903cc5d152e75dce33e5dbb0947df1' });
    fixture.stampText(shortCallback.toString(), { bytes: 1000, sha256: '0'.repeat(64) });
    fixture.stampText(changedCallback.toString(), { bytes: 1076, sha256: '0'.repeat(64) });
    fixture.stampText(kitLoad.toString(), { bytes: kitLoad.toString().length, sha256: '42da1ec046c9e229f91a2ed83d7f149768231f40f968815c0f7e361a0b66011f' });
    fixture.stampText('fixture-preload', { bytes: 2198, sha256: 'a4a1c9fde4f431ffef7ef93071a0c5d554b9a5b395854243ff982a880b726a7a' });
    fixture.stampText('fixture-kit-env', { bytes: 359, sha256: '3d31b247580a8cd7a2d8db9ba1461d86d1f3fd8771f888fdce12280895349eb5' });
    fixture.stampText('fixture-kit-server', { bytes: 195, sha256: '044ba569e5e503525a22977de015f67c0bc3f6f5deb1f9cf8a5dfec7b4487904' });
    fixture.stampText('fixture-runtime-ssr', { bytes: 3823, sha256: '6389c99520e98b0f839779e28a31bd13ea03d6177707348822d88cc0f5887a03' });
    fixture.stampText('fixture-runtime-client', { bytes: 4405, sha256: '2027378d81078b5bb25f18920376547f296bebd7be04bd10dc2e0221a5aa0991' });
    let badMember = false;
    let badVersion = false;
    /** @param {string} path */
    const read = (path) => {
      assertLifecycle(path.startsWith('/fixture/node_modules/'), 'bounded-read');
      const member = path.slice('/fixture/node_modules/'.length);
      if (member.endsWith('/package.json')) {
        const name = member.slice(0, -'/package.json'.length);
        assertLifecycle(name in versions, 'known-package-read');
        return JSON.stringify({ name, version: badVersion ? 'PRIVATE-SENTINEL' : versions[name] });
      }
      assertLifecycle(member in members, 'known-member-read');
      const token = (badMember ? 'changed:' : 'member:') + member;
      fixture.stampText(token, { bytes: token.length, sha256: badMember ? '0'.repeat(64) : members[member] });
      return token;
    };
    /** @param {string} algorithm */
    const createHash = (algorithm) => {
      assertLifecycle(algorithm === 'sha256', 'hash-algorithm');
      return { /** @param {string} value */ update(value) {
        return { /** @param {string} encoding */ digest(encoding) {
          assertLifecycle(encoding === 'hex', 'hash-encoding');
          return fixture.digest(value).sha256;
        } };
      } };
    };
    const parameters = ['createHash', 'mkdirSync', 'readFileSync', 'writeFileSync', 'relative', 'resolve', 'viteBuildImportAnalysisPlugin',
      'captureLoad', 'observeHook', 'observeResult', 'rejectLateTransform', 'replaceHandler', 'validateVirtualContext', 'preloadContextOptions', 'createNativePluginGuard', 'nodeTypes', 'Buffer'];
    // Execute the exact imported first-party captureLoad body under this same
    // explicit hash/byte seam. Its source/producer/receipt logic is unchanged;
    // this simulated digest is not actual cryptographic/source proof.
    const captureLoad = /** @type {GuardDependencies['captureLoad']} */ (new Function('createHash', 'Buffer', 'IDS',
      '"use strict"; return (' + Function.prototype.toString.call(guards.captureLoad) + ');')(
      createHash, { /** @param {string} value */ byteLength(value) { return fixture.digest(value).bytes; } },
      new Set(['\0rolldown/runtime.js', '\0vite/preload-helper.js', '\0virtual:__sveltekit/env', '\0virtual:__sveltekit/server'])));
    assertLifecycle(captureLoad.toString() === guards.captureLoad.toString(), 'unchanged-first-party-load-guard-body');
    const exported = /** @type {{factory:(users:readonly FixturePlugin[])=>FixtureObserver,capture:(options:unknown)=>Promise<readonly FixturePlugin[]>}} */ (new Function(...parameters, '"use strict";\n' + source + '\nreturn {factory:sourceModuleGraph,capture:captureUserPlugins};')(
      createHash, () => { writes++; }, read,
      /** @param {string} path @param {string} raw */ (path, raw) => {
        assertLifecycle(path.startsWith('/fixture/.volparossa-source-graphs/'), 'bounded-simulated-graph-path');
        writes++; simulatedGraphs.push(JSON.parse(raw));
      },
      /** @param {string} root @param {string} path */ (root, path) => path.slice(root.length + 1),
      /** @param {string[]} parts */ (...parts) => parts.join('/'),
      /** @param {unknown} options */ (options) => fixture.native('builtin:vite-build-import-analysis', options),
      captureLoad, guards.observeHook, guards.observeResult, guards.rejectLateTransform,
      guards.replaceHandler, guards.validateVirtualContext, guards.preloadContextOptions, guards.createNativePluginGuard,
      { isProxy: fixture.isProxy },
      { /** @param {string} value */ byteLength(value) { return fixture.digest(value).bytes; } }));
    const factory = exported.factory;
    const kit = actor('vite-plugin-sveltekit-virtual-modules', { load: kitLoad });
    const wrong = actor('unrecognized-production-plugin', { load: () => 'same-looking-virtual-code' });
    /** @type {FixtureObserver|undefined} */
    let observer;
    /** Original raw plugin inputs are supplied at factory construction, before
     * Vite or any config hook can replace config.plugins. @param {FixturePlugin[]} extras */
    const initialized = (extras) => {
      if (!observer) observer = factory(Object.freeze([kit, wrong, ...extras]));
      return observer;
    };
    /** @param {boolean} ssr @param {FixturePlugin[]} [extras] @returns {FixtureConfig} */
    const config = (ssr, extras = []) => {
      const selectedObserver = initialized(extras);
      const split = core.findIndex((plugin) => plugin.name === 'native:import-analysis-build');
      const users = [kit, wrong, ...extras, selectedObserver];
      return { root: '/fixture', inlineConfig: {}, command: 'build', mode: 'production', isWorker: false,
        isBundled: true, base: ssr ? '/' : './', consumer: ssr ? 'server' : 'client',
        experimental: { renderBuiltUrl: callback }, build: { ssr, lib: false, watch: null, write: true,
          modulePreload: { polyfill: true }, rolldownOptions: { platform: ssr ? 'node' : 'browser' } },
        plugins: [...core.slice(0, split), ...users, ...core.slice(split)] };
    };
    /** @returns {FixtureConfig} */
    const preprocessing = () => ({ ...config(false), command: 'serve', mode: 'development', base: '/',
      experimental: { renderBuiltUrl: undefined }, plugins: [initialized([])] });
    /** @param {FixtureConfig} resolved @param {FixturePlugin[]} [extras] @param {FixturePlugin[]} [presentedUsers] */
    const configure = async (resolved, extras = [], presentedUsers) => {
      const selectedObserver = initialized(extras);
      const users = presentedUsers ?? [selectedObserver, kit, wrong, ...extras];
      await selectedObserver.config.handler({ plugins: users }, { command: resolved.command, mode: resolved.mode });
      const receiver = { environment: { name: resolved.build.ssr ? 'ssr' : 'client', config: resolved, plugins: resolved.plugins } };
      // Vite's Promise.all starts every selected configResolved callback without
      // awaiting preceding ones; first-party native seals permit only controlled
      // wrapper transitions while original user Promises are pending.
      const pending = resolved.plugins.filter((plugin) => Reflect.get(plugin, 'configResolved'))
        .map((plugin) => fixtureHook(plugin, 'configResolved').call(receiver, resolved));
      await Promise.all(pending);
    };
    /** @param {FixtureConfig} resolved @returns {FixtureEnvironment} */
    const environment = (resolved) => {
      /** @type {FixtureEnvironment} */
      const env = { name: resolved.build.ssr ? 'ssr' : 'client', config: resolved, plugins: [] };
      /** @param {unknown} value @param {FixturePlugin} producer */
      const append = (value, producer) => {
        if (value === true) { env.plugins.push(producer); return; }
        if (!value) return;
        if (Array.isArray(value)) { for (const child of value) append(child, producer); return; }
        assertLifecycle(typeof value === 'object' && 'name' in value && typeof value.name === 'string', 'selected-plugin-shape');
        if (typeof value === 'object' && 'name' in value && typeof value.name === 'string') env.plugins.push(value);
      };
      for (const plugin of resolved.plugins) {
        const apply = Reflect.get(plugin, 'applyToEnvironment');
        append(typeof apply === 'function' ? Reflect.apply(apply, undefined, [env]) : plugin, plugin);
      }
      return env;
    };
    /** @param {FixtureEnvironment} env @returns {FixtureInput} */
    const normalized = (env) => ({ plugins: fixture.clones(env.plugins), moduleTypes: { '.css': 'js' }, output: { format: 'es' } });
    /** @param {FixtureEnvironment} env @param {FixtureInput} options */
    const runOptions = async (env, options) => {
      const receiver = { environment: env };
      let current = options;
      for (const plugin of options.plugins) {
        if (!Reflect.get(plugin, 'options')) continue;
        const result = await fixtureHook(plugin, 'options').call(receiver, current);
        if (result) {
          assertLifecycle(typeof result === 'object' && 'plugins' in result, 'options-result-shape');
          current = /** @type {FixtureInput} */ (result);
        }
      }
      return current;
    };
    /** @param {FixtureEnvironment} env @param {FixtureInput} input @param {object} [output] */
    const runOutput = (env, input, output = { format: 'es' }) => {
      const receiver = { environment: env };
      for (const plugin of input.plugins) {
        if (Reflect.get(plugin, 'outputOptions')) fixtureHook(plugin, 'outputOptions').call(receiver, output);
      }
      return output;
    };
    return { fixture, capture: exported.capture, get observer() { assertLifecycle(observer !== undefined, 'observer-created-after-raw-users'); if (!observer) throw new Error('fixture'); return observer; },
      kit, wrong, config, preprocessing, configure, environment, normalized, runOptions, runOutput,
      setBadMember(value = true) { badMember = value; }, setBadVersion(value = true) { badVersion = value; } };
  };

  {
    const h = harness(); const first = { name: 'captured-first' }; const second = { name: 'captured-second' };
    /** @type {unknown[]} */
    const nested = [Promise.resolve(second), false, null];
    const original = [first, nested];
    const captured = await h.capture(original);
    nested.splice(0, nested.length, { name: 'late-untrusted-substitution' });
    assertLifecycle(captured.length === 2 && captured[0] === first && captured[1] === second
      && Object.isFrozen(captured) && Reflect.set(captured, 0, { name: 'replacement' }) === false,
    'private-original-user-capture-finishes-before-config-hooks');
    positives++;
    /** @type {unknown[]} */
    const cycle = []; cycle.push(cycle);
    await refused(() => h.capture(cycle), 'P14_NATIVE_USER_PLUGIN_CYCLE');
    let deep = /** @type {unknown} */ (first);
    for (let index = 0; index < 18; index++) deep = [deep];
    await refused(() => h.capture(deep), 'P14_NATIVE_USER_PLUGIN_BOUND');
    await refused(() => h.capture(Array.from({ length: 1025 }, () => first)), 'P14_NATIVE_USER_PLUGIN_BOUND');
  }

  // Full load-config/preprocessor source sequence: initial serve changes absent
  // NODE_ENV to development, the style binding reuses the exact config, and the
  // old missing-binding failure selects a distinct nested serve fallback.
  /** @param {string|undefined} initialNodeEnv @param {boolean} [legacyFailure] */
  const replayLifecycle = (initialNodeEnv, legacyFailure = false) => {
    let nodeEnv = initialNodeEnv;
    let fallback = false;
    let oldMissingBinding = false;
    let stylesheetCalls = 0;
    /** @type {{command:string,mode:string,config:FixtureConfig,observer:FixtureObserver}[]} */
    const resolutions = [];
    /** @type {{__resolvedConfig:FixtureConfig|null}} */
    const style = { __resolvedConfig: null };
    /** @type {Promise<FixtureConfig>|undefined} */
    let cached;
    /** @param {string} command @param {string} mode */
    const resolve = async (command, mode) => {
      if (nodeEnv === undefined) nodeEnv = mode;
      const h = harness();
      const config = command === 'serve' ? h.preprocessing() : h.config(true);
      config.command = command; config.mode = mode;
      resolutions.push({ command, mode, config, observer: h.observer });
      if (legacyFailure && resolutions.length === 1) {
        oldMissingBinding = config.experimental.renderBuiltUrl === undefined;
        assertLifecycle(oldMissingBinding, 'legacy-first-failing-missing-callback');
        throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:unreviewed-source');
      }
      await h.configure(config);
      return config;
    };
    const loadFromDirectory = async () => {
      try { style.__resolvedConfig = await resolve('serve', 'development'); }
      catch (error) {
        assertLifecycle(legacyFailure && error instanceof Error
          && error.message === 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:unreviewed-source', 'bounded-legacy-catch');
        fallback = true;
      }
    };
    /** @param {FixtureConfig} [provided] */
    const stylesheet = (provided) => {
      stylesheetCalls++;
      if (!cached) {
        if (style.__resolvedConfig) cached = Promise.resolve(style.__resolvedConfig);
        else if (provided?.inlineConfig) cached = Promise.resolve(provided);
        else { const build = !nodeEnv || nodeEnv === 'production'; cached = resolve(build ? 'build' : 'serve', build ? 'production' : 'development'); }
      }
      return cached;
    };
    return { loadFromDirectory, stylesheet, resolutions, get nodeEnv() { return nodeEnv; }, get fallback() { return fallback; },
      get oldMissingBinding() { return oldMissingBinding; }, get stylesheetCalls() { return stylesheetCalls; } };
  };
  const discovered = replayLifecycle(undefined);
  await discovered.loadFromDirectory();
  const firstStyle = await discovered.stylesheet();
  assertLifecycle(discovered.nodeEnv === 'development' && !discovered.fallback && discovered.resolutions.length === 1
    && firstStyle === discovered.resolutions[0].config && await discovered.stylesheet() === firstStyle
    && discovered.resolutions.length === 1 && discovered.stylesheetCalls === 2, 'discovery-reuse-and-cache');
  positives++;
  const initial = discovered.resolutions[0];
  const initialReceiver = { environment: { name: 'client', config: initial.config, plugins: initial.config.plugins } };
  await refused(() => initial.observer.options.handler.call(initialReceiver, { plugins: [], moduleTypes: { '.css': 'js' } }), 'P14_VIRTUAL_CONFIGURATION:production-required');
  await refused(() => initial.observer.outputOptions.handler.call(initialReceiver, {}), 'P14_VIRTUAL_CONFIGURATION:production-required');
  await refused(() => initial.observer.buildStart.handler.call(initialReceiver, { platform: 'browser' }), 'P14_VIRTUAL_CONFIGURATION:production-required');
  await refused(() => initial.observer.transform.handler.call(initialReceiver, 'fixture', '\0virtual:__sveltekit/env'), 'P14_VIRTUAL_ENVIRONMENT_CHANGED');
  await refused(() => initial.observer.transform.handler.call(initialReceiver, 'fixture', '\0unknown'), 'UNREVIEWED_VIRTUAL_MODULE');
  await refused(() => initial.observer.generateBundle.handler.call(initialReceiver, { format: 'es' }, {}), 'P14_VIRTUAL_ENVIRONMENT_CHANGED');
  await refused(() => initial.observer.configResolved(initial.config), 'P14_VIRTUAL_CONFIGURATION:repeated');
  const noAuthority = harness();
  const noConfig = noAuthority.preprocessing();
  const untouched = actor('unrecognized-preprocess-plugin', { load: () => 'PRIVATE-SENTINEL' });
  noConfig.plugins.unshift(untouched);
  const originalLoad = Reflect.get(untouched, 'load');
  await noAuthority.configure(noConfig);
  assertLifecycle(Reflect.get(untouched, 'load') === originalLoad, 'preprocess-no-producer-wrapping');
  await refused(() => noAuthority.observer.configResolved(noAuthority.config(true)), 'P14_VIRTUAL_CONFIGURATION:repeated');
  positives++;
  const legacy = replayLifecycle(undefined, true);
  await legacy.loadFromDirectory();
  const fallbackStyle = await legacy.stylesheet();
  assertLifecycle(legacy.oldMissingBinding && legacy.fallback && legacy.nodeEnv === 'development'
    && legacy.resolutions.length === 2 && legacy.resolutions[1].command === 'serve'
    && legacy.resolutions[0].observer !== legacy.resolutions[1].observer
    && fallbackStyle === legacy.resolutions[1].config && await legacy.stylesheet() === fallbackStyle, 'legacy-fallback-distinct-serve-cache');
  positives++;
  const standalone = replayLifecycle(undefined);
  const standaloneConfig = await standalone.stylesheet();
  assertLifecycle(standalone.nodeEnv === 'production' && standalone.resolutions.length === 1
    && standalone.resolutions[0].command === 'build' && await standalone.stylesheet() === standaloneConfig, 'standalone-build-config-only');
  positives++;
  const supplied = replayLifecycle(undefined);
  assertLifecycle(await supplied.stylesheet(firstStyle) === firstStyle && await supplied.stylesheet() === firstStyle
    && supplied.resolutions.length === 0 && supplied.nodeEnv === undefined, 'provided-resolved-config-cache');
  positives++;

  for (const mutation of ['mode', 'worker', 'callback']) {
    const h = harness(); const config = h.preprocessing();
    if (mutation === 'mode') config.mode = 'production';
    if (mutation === 'worker') config.isWorker = true;
    if (mutation === 'callback') config.experimental.renderBuiltUrl = callback;
    await refused(() => h.configure(config), 'P14_VIRTUAL_CONFIGURATION:preprocessing-context');
  }
  for (const [value, reason] of [[undefined, 'missing-binding'], [null, 'invalid-type'], [true, 'invalid-type'],
    [shortCallback, 'source-bytes'], [changedCallback, 'source-hash']]) {
    const h = harness(); const config = h.config(true); config.experimental.renderBuiltUrl = value;
    await refused(() => h.configure(config), 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:' + reason);
    await refused(() => h.observer.configResolved(h.config(true)), 'P14_VIRTUAL_CONFIGURATION:repeated');
  }
  for (const mutation of ['command', 'mode', 'worker']) {
    const h = harness(); const config = h.config(true);
    if (mutation === 'command') config.command = 'unknown';
    if (mutation === 'mode') config.mode = 'development';
    if (mutation === 'worker') config.isWorker = true;
    await refused(() => h.configure(config), 'P14_VIRTUAL_CONFIGURATION:production-context');
  }
  for (const kind of ['member', 'version']) {
    const h = harness(); if (kind === 'member') h.setBadMember(); else h.setBadVersion();
    await refused(() => h.configure(h.config(true)), kind === 'member' ? 'P14_VIRTUAL_PRODUCER_MEMBER' : 'P14_VIRTUAL_DEPENDENCY_VERSION');
  }

  // Nested SvelteKit client configuration reuses the cached Rolldown module's
  // exact constructor/prototype after SSR finalization has made them immutable.
  const sharedNativeFixture = guards.createNativePluginFixture();
  for (const ssr of [true, false]) {
    const h = harness(sharedNativeFixture, !ssr); const config = h.config(ssr);
    if (!ssr) assertLifecycle(Object.isFrozen(sharedNativeFixture.prototype)
      && Object.isFrozen(sharedNativeFixture.prototype.constructor), 'nested-client-reuses-frozen-ssr-class');
    await h.configure(config);
    const env = h.environment(config); const receiver = { environment: env }; const input = h.normalized(env);
    config.experimental.renderBuiltUrl = identicalCallback;
    await refused(() => h.runOptions(env, input), 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:function');
    config.experimental.renderBuiltUrl = callback;
    await h.runOptions(env, input);
    h.runOutput(env, input); // Original Rolldown outputOptions precedes buildStart.
    h.observer.buildStart.handler.call(receiver, { platform: ssr ? 'node' : 'browser' });
    await refused(() => h.observer.options.handler.call(receiver, input), 'P14_VIRTUAL_BUILD_OPTIONS');
    await refused(() => h.observer.buildStart.handler.call(receiver, { platform: ssr ? 'node' : 'browser' }), 'P14_VIRTUAL_BUILD_OPTIONS');
    await refused(() => fixtureHook(h.wrong, 'load').call(receiver, '\0virtual:__sveltekit/env'), 'P14_WRONG_VIRTUAL_LOADER');
    if (ssr) {
      for (const id of ['\0virtual:__sveltekit/env', '\0virtual:__sveltekit/server']) {
        const code = fixtureHook(h.kit, 'load').call(receiver, id);
        assertLifecycle(typeof code === 'string' && code === kitCode[id], 'actual-kit-load-receipt');
        if (typeof code === 'string') assertLifecycle(h.observer.transform.handler.call(receiver, code, id) === null, 'actual-kit-transform-receipt');
        await refused(() => fixtureHook(h.kit, 'load').call(receiver, id), 'P14_AMBIGUOUS_VIRTUAL_LOADER');
      }
    }
    assertLifecycle(h.observer.transform.handler.call(receiver, ssr ? 'fixture-runtime-ssr' : 'fixture-runtime-client', '\0rolldown/runtime.js') === null, 'actual-runtime-transform-receipt');
    if (!ssr) assertLifecycle(h.observer.transform.handler.call(receiver, 'fixture-preload', '\0vite/preload-helper.js') === null, 'actual-preload-transform-receipt');
    h.observer.generateBundle.handler.call(receiver, { format: 'es' }, {});
    await refused(() => h.observer.transform.handler.call(receiver, 'fixture', '\0unknown'), 'UNREVIEWED_VIRTUAL_MODULE');
    await refused(() => h.observer.configResolved(config), 'P14_VIRTUAL_CONFIGURATION:repeated');
    assertLifecycle(env.plugins.filter((plugin) => plugin.name.startsWith('builtin:')).length === 11, 'complete-native-context');
    positives++;
  }

  // ConfigResolved guard covers synchronous and Promise continuations while
  // Vite's Promise.all permits the observer's own controlled wrappers to run.
  for (const asynchronous of [false, true]) {
    const h = harness(); let calls = 0;
    const modify = /** @param {FixtureConfig} resolved */ (resolved) => {
      calls++;
      assertLifecycle(Reflect.set(resolved.plugins, resolved.plugins.length, h.fixture.native('builtin:vite-alias', {})) === false,
        'config-native-insertion-is-read-only');
      assertLifecycle(Reflect.set(resolved, 'plugins', [...resolved.plugins, { name: 'PRIVATE-SENTINEL' }]) === false,
        'config-topology-reference-is-read-only');
      negatives += 2;
    };
    const user = actor('config-mutator', { configResolved: asynchronous ? async (/** @type {FixtureConfig} */ resolved) => { await Promise.resolve(); modify(resolved); } : modify });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    assertLifecycle(calls === 1 && Object.isFrozen(config.plugins), 'config-mutator-executed-behind-guard');
    const env = h.environment(config); const input = h.normalized(env);
    await h.runOptions(env, input); h.runOutput(env, input);
    h.observer.buildStart.handler.call({ environment: env }, { platform: 'node' });
  }
  {
    const h = harness(); const late = actor('late-config', { enforce: 'post', config: { order: 'post', handler() {} } });
    await refused(() => h.configure(h.config(true, [late]), [late]), 'P14_NATIVE_LATE_CONFIG_HOOK');
  }
  {
    const h = harness(); const foreign = h.fixture.native('builtin:vite-json', { namedExports: true, stringify: 'auto', minify: true });
    await refused(() => h.configure(h.config(true, [foreign]), [foreign]), 'P14_NATIVE:user-native');
  }
  {
    const h = harness(); let calls = 0;
    const user = actor('hidden-original-config-mutator', { configResolved: /** @param {FixtureConfig} resolved */ (resolved) => {
      calls++;
      assertLifecycle(Reflect.set(resolved.plugins, resolved.plugins.length, h.fixture.native('builtin:vite-alias', {})) === false,
        'hidden-original-native-insertion-is-read-only');
      negatives++;
    } });
    const config = h.config(true, [user]);
    // An earlier config hook removed this actor from the visible config.plugins
    // field, but Vite's precomputed user list and factory's original input copy
    // still contain it. It must be wrapped before it can mutate native state.
    await h.configure(config, [user], [h.observer]);
    assertLifecycle(calls === 1, 'hidden-original-config-hook-still-intercepted');
  }
  {
    const h = harness(); const foreign = h.fixture.native('builtin:vite-json', { namedExports: true, stringify: 'auto', minify: true });
    const config = h.config(true, [foreign]);
    await refused(() => h.configure(config, [foreign], [h.observer]), 'P14_NATIVE:user-native');
  }
  {
    const h = harness(); let foreignCalls = 0;
    /** @type {(()=>void)|undefined} */
    let release;
    /** @type {Promise<void>} */
    const gate = new Promise((resolve) => { release = () => resolve(); });
    /** @type {Promise<void>|undefined} */
    let queued;
    const foreign = actor('unknown-queued-producer', { options: () => { foreignCalls++; } });
    const user = actor('queued-config-mutator', { configResolved: /** @param {FixtureConfig} resolved */ (resolved) => {
      queued = gate.then(() => {
        assertLifecycle(Reflect.set(resolved.plugins, resolved.plugins.length, foreign) === false, 'queued-config-plugin-insertion-denied');
        assertLifecycle(Reflect.set(resolved, 'plugins', [...resolved.plugins, foreign]) === false, 'queued-config-list-replacement-denied');
        negatives += 2;
      });
    } });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    assertLifecycle(release !== undefined && queued !== undefined, 'queued-config-awaits-final-topology');
    if (release) release();
    await queued;
    const env = h.environment(config); const input = h.normalized(env);
    await h.runOptions(env, input); h.runOutput(env, input);
    h.observer.buildStart.handler.call({ environment: env }, { platform: 'node' });
    assertLifecycle(foreignCalls === 0 && !env.plugins.includes(foreign), 'queued-foreign-producer-never-executed');
  }
  for (const asynchronous of [false, true]) {
    const h = harness();
    const modify = /** @param {FixtureInput} options */ (options) => { options.plugins.push({ name: 'PRIVATE-SENTINEL-input' }); };
    const user = actor('options-mutator', { options: asynchronous ? async (/** @type {FixtureInput} */ options) => { await Promise.resolve(); modify(options); } : modify });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    const env = h.environment(config);
    await refused(() => h.runOptions(env, h.normalized(env)), 'P14_NATIVE:input-count');
  }
  for (const key of ['plugins', 'output']) {
    const h = harness(); let reads = 0; let calls = 0;
    const user = actor('getter-boundary', { options: () => { calls++; } });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    const env = h.environment(config); const input = h.normalized(env);
    const original = Reflect.get(input, key);
    Object.defineProperty(input, key, { get() { reads++; return original; }, enumerable: true, configurable: true });
    // Invoke the actual observer-installed hook boundary without a fixture
    // dispatcher reading the hostile accessor first.
    await refused(() => fixtureHook(user, 'options').call({ environment: env }, input), 'P14_NATIVE:input-accessor');
    assertLifecycle(reads === 0 && calls === 0, 'getter-never-observed-before-original-options');
  }
  {
    const h = harness(); const config = h.config(true); await h.configure(config);
    const env = h.environment(config); const input = h.normalized(env); let reads = 0;
    const proxy = h.fixture.proxy(input, { get(target, key, receiver) { reads++; return Reflect.get(target, key, receiver); } });
    await refused(() => h.observer.options.handler.call({ environment: env }, proxy), 'P14_NATIVE:input-owner');
    assertLifecycle(reads === 0, 'proxy-input-owner-not-observed');
  }
  {
    const h = harness(); const config = h.config(true); await h.configure(config);
    const env = h.environment(config); const input = h.normalized(env); await h.runOptions(env, input);
    const original = input.plugins;
    assertLifecycle(Reflect.set(input, 'plugins', [...original]) === false && input.plugins === original,
      'late-input-owner-reference-is-read-only');
    assertLifecycle(Reflect.set(input, 'output', { plugins: [{ name: 'PRIVATE-SENTINEL' }] }) === false,
      'late-input-owner-output-is-read-only');
    negatives += 2;
    h.runOutput(env, input);
    h.observer.buildStart.handler.call({ environment: env }, { platform: 'node' });
  }
  {
    const h = harness();
    const user = actor('output-mutator', { outputOptions: /** @param {object} output */ (output) => { Reflect.set(output, 'plugins', [h.fixture.native('builtin:vite-alias', {})]); } });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    const env = h.environment(config); const input = h.normalized(env); await h.runOptions(env, input);
    await refused(() => h.runOutput(env, input), 'P14_NATIVE:output-plugins');
  }
  {
    const h = harness(); const config = h.config(true); await h.configure(config);
    const env = h.environment(config); const input = h.normalized(env);
    input.output = { plugins: [h.fixture.native('builtin:vite-alias', {})] };
    await refused(() => h.runOptions(env, input), 'P14_NATIVE:output-plugins');
  }
  {
    const h = harness();
    /** @type {(()=>void)|undefined} */
    let release;
    /** @type {Promise<void>} */
    const gate = new Promise((resolve) => { release = () => resolve(); });
    /** @type {Promise<void>[]} */
    const queued = [];
    const user = actor('queued-late-mutator', {
      options: /** @param {FixtureInput} options */ (options) => { queued.push(gate.then(() => {
        const cloned = options.plugins.find((plugin) => plugin.name === 'queued-late-mutator');
        assertLifecycle(cloned !== undefined, 'queued-clone-present');
        assertLifecycle(Reflect.set(options, 'plugins', []) === false, 'queued-owner-write-denied');
        assertLifecycle(Reflect.set(options.plugins, '0', { name: 'foreign' }) === false, 'queued-input-entry-write-denied');
        assertLifecycle(Reflect.set(options.plugins[0], 'name', 'builtin:foreign') === false, 'queued-native-name-write-denied');
        if (cloned) assertLifecycle(Reflect.set(cloned, 'transform', () => null) === false, 'queued-clone-hook-write-denied');
        negatives += 4;
      })); },
      outputOptions: /** @param {object} output */ (output) => { queued.push(gate.then(() => {
        assertLifecycle(Reflect.set(output, 'plugins', [{ name: 'foreign' }]) === false, 'queued-output-plugin-write-denied');
        negatives++;
      })); },
    });
    const config = h.config(true, [user]); await h.configure(config, [user]);
    const env = h.environment(config); const input = h.normalized(env);
    await h.runOptions(env, input); h.runOutput(env, input);
    assertLifecycle(queued.length === 2 && release !== undefined, 'queued-writes-await-final-boundaries');
    if (release) release();
    await Promise.all(queued);
    h.observer.buildStart.handler.call({ environment: env }, { platform: 'node' });
  }
  for (const kind of ['object-getter', 'object-proxy', 'array-proxy', 'array-getter', 'plugins-proxy']) {
    const h = harness(); const config = h.config(true); await h.configure(config);
    const env = h.environment(config); const input = h.normalized(env); let reads = 0;
    /** @type {unknown} */
    let output;
    let reason = 'P14_NATIVE:proxy';
    if (kind === 'object-getter') {
      output = { get plugins() { reads++; return []; } }; reason = 'P14_NATIVE:output-plugin-accessor';
    } else if (kind === 'array-getter') {
      const array = [{}]; Object.defineProperty(array, '0', { get() { reads++; return {}; }, enumerable: true });
      output = array; reason = 'P14_NATIVE:output-array-accessor';
    } else if (kind === 'plugins-proxy') {
      output = { plugins: h.fixture.proxy([], { get() { reads++; return []; } }) };
      reason = 'P14_NATIVE:output-plugins';
    } else {
      output = h.fixture.proxy(kind === 'array-proxy' ? [{}] : { plugins: [] }, {
        get() { reads++; return []; }, getOwnPropertyDescriptor() { reads++; return undefined; },
      });
    }
    input.output = output;
    await refused(() => h.runOptions(env, input), reason);
    assertLifecycle(reads === 0, 'configured-output-' + kind + '-is-never-observed');
  }
  for (const mutation of ['prototype', 'hook']) {
    const h = harness(); const config = h.config(true); await h.configure(config);
    const env = h.environment(config); const input = h.normalized(env); await h.runOptions(env, input); h.runOutput(env, input);
    const changed = mutation === 'prototype' ? Reflect.setPrototypeOf(h.fixture.json, {})
      : Reflect.set(h.fixture.json, 'load', () => 'PRIVATE-SENTINEL');
    assertLifecycle(changed === false, 'late-native-' + mutation + '-is-read-only');
    negatives++;
    h.observer.buildStart.handler.call({ environment: env }, { platform: 'node' });
  }
  assertLifecycle(writes === 4 && simulatedGraphs.length === 2
    && simulatedGraphs[0].schema === 2 && simulatedGraphs[0].virtualModules.length === 3
    && simulatedGraphs[1].schema === 2 && simulatedGraphs[1].virtualModules.length === 2,
  'simulated-graph-contains-only-bound-positive-receipts');
  return { passed: true, positive_sequences: positives, negative_cases: negatives,
    actual_observer_factory_and_hooks: true, complete_ssr_and_client_native_inventory: true,
    original_config_then_input_clones_then_output_before_buildStart: true,
    sequential_ssr_client_same_frozen_native_class: true, late_native_and_input_authority_read_only: true, queued_late_plugin_authority_writes_denied: true,
    successful_config_reuse: true, fallback_nested_serve: true, source_derived_resolution_order_and_node_env: true,
    repeated_stylesheet_transform_cache: true, standalone_and_provided_resolved_config: true,
    legacy_missing_binding_replayed: true, preprocessing_cannot_authorize_virtual_modules: true,
    production_callback_identity: true, common_member_and_version_guards: true,
    user_config_sync_and_promise_mutation_denied: true, queued_config_topology_writes_denied: true, input_options_sync_and_promise_mutation_denied: true,
    output_plugins_denied_before_buildStart: true, digest_and_native_interfaces_mocked: true,
    actual_positive_load_transform_and_graph_receipts: true, simulated_graphs: simulatedGraphs.length,
    dependency_execution: false, filesystem_or_network_execution: false };
}
