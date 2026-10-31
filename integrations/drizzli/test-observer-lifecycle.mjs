// SPDX-License-Identifier: GPL-3.0-only
// Inert lifecycle integration: execute the actual first-party observer hooks,
// substituting only external IO/crypto/native interfaces. Mock digest receipts
// exercise authentication branches; they are not proof of dependency hashes.

/** @typedef {(this:FixtureReceiver,...args:unknown[])=>unknown} FixtureHook */
/** @typedef {{name:string,load?:FixtureHook,transform?:unknown,applyToEnvironment?:(environment:FixtureEnvironment)=>unknown,options?:unknown}} FixturePlugin */
/** @typedef {{root:string,inlineConfig?:object,command:string,mode:string,isWorker:boolean,isBundled:boolean,base:string,consumer:string,experimental:{renderBuiltUrl:unknown},build:{ssr:boolean,lib:boolean,watch:null,write:boolean,modulePreload:{polyfill:boolean},rolldownOptions:{platform:string}} ,plugins:FixturePlugin[]}} FixtureConfig */
/** @typedef {{name:string,config:FixtureConfig,plugins:FixturePlugin[]}} FixtureEnvironment */
/** @typedef {{environment:FixtureEnvironment}} FixtureReceiver */
/** @typedef {{name:string,configResolved:(config:FixtureConfig)=>void,options:{handler:(this:FixtureReceiver,options:object)=>unknown},buildStart:{handler:(this:FixtureReceiver,options:object)=>unknown},transform:{handler:(this:FixtureReceiver,code:string,id:string)=>unknown},generateBundle:{handler:(this:FixtureReceiver,options:object,bundle:object)=>unknown}} FixtureObserver */
/** @typedef {{captureLoad:typeof import('./virtual-module-guards.mjs').captureLoad,observeHook:typeof import('./virtual-module-guards.mjs').observeHook,observeResult:typeof import('./virtual-module-guards.mjs').observeResult,rejectLateTransform:typeof import('./virtual-module-guards.mjs').rejectLateTransform,replaceHandler:typeof import('./virtual-module-guards.mjs').replaceHandler,validateVirtualContext:typeof import('./virtual-module-context.mjs').validateVirtualContext,preloadContextOptions:typeof import('./virtual-module-context.mjs').preloadContextOptions}} GuardDependencies */

/** @param {boolean} ok @param {string} name */
function assertLifecycle(ok, name) {
  if (!ok) throw new Error('P14_LIFECYCLE_TEST_FAILED:' + name);
}

/** @param {string} source @param {GuardDependencies} guards */
export function runObserverLifecycleTests(source, guards) {
  const imports = [
    "import { createHash } from 'node:crypto';",
    "import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';",
    "import { relative, resolve } from 'node:path';",
    "import { viteBuildImportAnalysisPlugin } from 'rolldown/experimental';",
    "import { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler } from './virtual-module-guards.mjs';",
    "import { validateVirtualContext, preloadContextOptions } from './virtual-module-context.mjs';",
  ];
  for (const line of imports) {
    assertLifecycle(source.split(line + '\n').length === 2, 'exact-import-seam');
    source = source.replace(line + '\n', '');
  }
  const declaration = 'export default function sourceModuleGraph()';
  assertLifecycle(source.split(declaration).length === 2 && !/^import /m.test(source), 'exact-factory-seam');
  source = source.replace(declaration, 'function sourceModuleGraph()');

  const callback = function approvedCallback() {};
  const identicalCallback = function approvedCallback() {};
  const shortCallback = function shortCallback() {};
  const changedCallback = function changedCallback() {};
  const kitLoad = function approvedKitLoad() { return null; };
  /** @type {object|undefined} */
  let selectedNativeResult;
  const nativeApply = function approvedNativeApply() { return selectedNativeResult; };
  const callbackSource = Function.prototype.toString.call(callback);
  const kitSource = Function.prototype.toString.call(kitLoad);
  const nativeSource = Function.prototype.toString.call(nativeApply);
  assertLifecycle(callback !== identicalCallback && callbackSource === identicalCallback.toString(), 'callback-identity-fixture');
  /** @type {Record<string,string>} */
  const members = {
    '@sveltejs/kit/src/exports/vite/index.js': '48a56f687eeb0429ee4a2138fe15e4ab4d93621d07e47c5dacc44647ea4215f6',
    '@sveltejs/kit/src/core/env.js': '95f4c3419ed4b33657c4b86450fc839f3795e2c46f73f2d9524521b79f92a000',
    'vite/dist/node/chunks/node.js': '5a604cb8f97126675dbdf9044c919b0fd1fe1280bfa4077de225e6adfa213e4a',
    'rolldown/dist/shared/constructors-xEvVj3lN.mjs': '087234cdd6903f7d5d1fd5e44a4cec61965c8755fa36c8d06f26a1a486d65de3',
    'rolldown/dist/shared/normalize-string-or-regex-F14uvr6D.mjs': 'e1cff9111ea8819b0890ae35b1cfd2938a53bf755c6c176d79387133ed7e5f1c',
    'rolldown/dist/shared/binding-BY0qR5iS.mjs': '8c571a4e4ac9561df9d6d7370d6c0d506922b6c106fd693cb2b75b47c3ab028a',
    'rolldown/dist/shared/bindingify-input-options-XrReX_BJ.mjs': 'a778028ca12765b4604b9cb04edf80e1dc6dc096bccbc893317aa03e02ab4890',
    '@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node': '34e3f5cc135d0fec7f0d9837e30413f1a151037b1568911f074048bf941d68e5',
  };
  /** @type {Record<string,string>} */
  const versions = { '@sveltejs/kit': '2.70.1', vite: '8.3.1', rolldown: '1.2.11', '@rolldown/binding-linux-x64-gnu': '1.2.11' };
  let badMember = false;
  let badVersion = false;
  let writes = 0;
  const nativePrototype = {};
  /** Mock external interfaces are intentionally private to this test harness.
   * @param {string} path */
  const read = (path) => {
    assertLifecycle(path.startsWith('/fixture/node_modules/'), 'bounded-read');
    const member = path.slice('/fixture/node_modules/'.length);
    if (member.endsWith('/package.json')) {
      const name = member.slice(0, -'/package.json'.length);
      assertLifecycle(name in versions, 'known-package-read');
      return JSON.stringify({ name, version: badVersion ? 'PRIVATE-SENTINEL' : versions[name] });
    }
    assertLifecycle(member in members, 'known-member-read');
    return (badMember ? 'changed:' : 'member:') + member;
  };
  /** @param {string} value */
  const byteLength = (value) => value === callbackSource || value === changedCallback.toString() ? 1076
    : value === shortCallback.toString() ? 1000 : value === 'fixture-preload' ? 2198 : value.length;
  /** @param {string} value */
  const digest = (value) => value.startsWith('member:') ? members[value.slice(7)]
    : value === callbackSource ? 'b2e81ff8fba88a56e0ce4c2ef946bb15a7903cc5d152e75dce33e5dbb0947df1'
    : value === kitSource ? '42da1ec046c9e229f91a2ed83d7f149768231f40f968815c0f7e361a0b66011f'
    : value === nativeSource ? 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376'
    : value === 'fixture-preload' ? 'a4a1c9fde4f431ffef7ef93071a0c5d554b9a5b395854243ff982a880b726a7a' : '0'.repeat(64);
  /** @param {string} algorithm */
  const createHash = (algorithm) => {
    assertLifecycle(algorithm === 'sha256', 'hash-algorithm');
    return { /** @param {string} value */ update(value) {
      return { /** @param {string} encoding */ digest(encoding) {
        assertLifecycle(encoding === 'hex', 'hash-encoding');
        return digest(value);
      } };
    } };
  };
  /** @param {object} options @returns {{name:string,_options:object}} */
  const native = (options) => Object.assign(Object.create(nativePrototype), { name: 'builtin:vite-build-import-analysis', _options: options });
  const parameters = ['createHash', 'mkdirSync', 'readFileSync', 'writeFileSync', 'relative', 'resolve', 'viteBuildImportAnalysisPlugin',
    'captureLoad', 'observeHook', 'observeResult', 'rejectLateTransform', 'replaceHandler', 'validateVirtualContext', 'preloadContextOptions', 'Buffer'];
  const factory = /** @type {()=>FixtureObserver} */ (new Function(...parameters, '"use strict";\n' + source + '\nreturn sourceModuleGraph;')(
    createHash, () => { writes++; }, read, () => { writes++; },
    /** @param {string} root @param {string} path */ (root, path) => path.slice(root.length + 1),
    /** @param {string[]} parts */ (...parts) => parts.join('/'), native,
    guards.captureLoad, guards.observeHook, guards.observeResult, guards.rejectLateTransform,
    guards.replaceHandler, guards.validateVirtualContext, guards.preloadContextOptions, { byteLength }));

  let positives = 0;
  let negatives = 0;
  /** @param {()=>unknown} action @param {string} expected */
  const refused = (action, expected) => {
    let message = '';
    try { action(); } catch (error) { if (error instanceof Error) message = error.message; }
    assertLifecycle(message === expected && !message.includes('PRIVATE-SENTINEL'), 'rejection:' + expected);
    negatives++;
  };
  /** @param {FixtureObserver} observer @param {boolean} ssr @param {unknown} [boundCallback] @returns {FixtureConfig} */
  const configuration = (observer, ssr, boundCallback = callback) => ({ root: '/fixture', inlineConfig: {}, command: 'build', mode: 'production',
    isWorker: false, isBundled: true, base: ssr ? '/' : './', consumer: ssr ? 'server' : 'client',
    experimental: { renderBuiltUrl: boundCallback }, build: { ssr, lib: false, watch: null, write: true,
      modulePreload: { polyfill: true }, rolldownOptions: { platform: ssr ? 'node' : 'browser' } }, plugins: [observer] });
  /** @param {FixtureConfig} config @param {boolean} ssr @returns {FixtureEnvironment} */
  const environment = (config, ssr) => ({ name: ssr ? 'ssr' : 'client', config, plugins: config.plugins });
  /** @param {FixtureObserver} observer @returns {FixtureConfig} */
  const preprocessing = (observer) => ({ ...configuration(observer, false), command: 'serve', mode: 'development',
    experimental: { renderBuiltUrl: undefined }, base: '/' });

  /** Replay the relevant source control flow, not upstream/CSS execution.
   * load-config 0.2.0 explicitly calls resolveConfig(...,'serve'); Vite's
   * default NODE_ENV mutation precedes config hooks. The successful Svelte
   * plugin attaches __resolvedConfig. createCssTransform prefers that object,
   * then a supplied resolved config, then derives build/serve from NODE_ENV.
   * viteStyle caches the chosen transform after the first stylesheet.
   * @param {string|undefined} initialNodeEnv @param {boolean} [legacyFailure] */
  const replayLifecycle = (initialNodeEnv, legacyFailure = false) => {
    let nodeEnv = initialNodeEnv;
    let fallback = false;
    let oldMissingBinding = false;
    let stylesheetCalls = 0;
    /** @type {{command:string,mode:string,config:FixtureConfig,observer:FixtureObserver}[]} */
    const resolutions = [];
    /** @type {{__resolvedConfig:FixtureConfig|null}} */
    const style = { __resolvedConfig: null };
    /** @type {FixtureConfig|undefined} */
    let cachedTransformConfig;
    /** @param {string} command @param {string} mode @returns {FixtureConfig} */
    const resolveConfig = (command, mode) => {
      // Vite's defaultNodeEnv has the same value as defaultMode in both
      // relevant callers, and sets process.env only when it was not set.
      if (nodeEnv === undefined) nodeEnv = mode;
      const observer = factory();
      const config = command === 'serve' ? preprocessing(observer) : configuration(observer, true);
      config.command = command;
      config.mode = mode;
      resolutions.push({ command, mode, config, observer });
      if (legacyFailure && resolutions.length === 1) {
        // The old grouped authentication rejected this exact missing binding.
        // This is a source-derived counterfactual, not a logged runtime value.
        const priorBinding = undefined;
        const observed = config.experimental.renderBuiltUrl;
        const oldSource = typeof observed === 'function' ? { bytes: 1076 } : null;
        oldMissingBinding = priorBinding === undefined && observed === undefined && oldSource === null;
        assertLifecycle(oldMissingBinding, 'legacy-first-failing-missing-callback');
        if (!oldSource) throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:unreviewed-source');
      }
      observer.configResolved(config);
      return config;
    };
    const loadFromDirectory = () => {
      try {
        const resolved = resolveConfig('serve', 'development');
        // The actual pinned Svelte plugin configResolved hook tags each
        // vite-preprocess style function with this exact resolved object.
        style.__resolvedConfig = resolved;
      } catch (error) {
        assertLifecycle(legacyFailure && error instanceof Error
          && error.message === 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:unreviewed-source', 'bounded-legacy-catch');
        fallback = true;
        style.__resolvedConfig = null;
      }
    };
    /** @param {FixtureConfig} [providedConfig] @returns {FixtureConfig} */
    const stylesheet = (providedConfig) => {
      stylesheetCalls++;
      if (!cachedTransformConfig) {
        if (style.__resolvedConfig) cachedTransformConfig = style.__resolvedConfig;
        else if (providedConfig?.inlineConfig) cachedTransformConfig = providedConfig;
        else {
          const useBuild = !nodeEnv || nodeEnv === 'production';
          const command = useBuild ? 'build' : 'serve';
          const mode = useBuild ? 'production' : 'development';
          cachedTransformConfig = resolveConfig(command, mode);
        }
      }
      return cachedTransformConfig;
    };
    return { loadFromDirectory, stylesheet, resolutions,
      get nodeEnv() { return nodeEnv; }, get fallback() { return fallback; },
      get oldMissingBinding() { return oldMissingBinding; },
      get stylesheetCalls() { return stylesheetCalls; } };
  };

  const discovered = replayLifecycle(undefined);
  discovered.loadFromDirectory();
  assertLifecycle(discovered.nodeEnv === 'development' && !discovered.fallback
    && discovered.resolutions.length === 1 && discovered.resolutions[0].command === 'serve'
    && discovered.resolutions[0].mode === 'development', 'initial-serve-config-discovery');
  const firstStyleConfig = discovered.stylesheet();
  const secondStyleConfig = discovered.stylesheet();
  assertLifecycle(firstStyleConfig === discovered.resolutions[0].config && secondStyleConfig === firstStyleConfig
    && discovered.resolutions.length === 1 && discovered.stylesheetCalls === 2 && writes === 0,
  'successful-preprocess-reuse-and-cache-no-additional-resolution');
  positives++;

  const initial = discovered.resolutions[0].observer;
  const initialConfig = discovered.resolutions[0].config;
  const initialReceiver = { environment: environment(initialConfig, false) };
  refused(() => initial.options.handler.call(initialReceiver, { moduleTypes: { '.css': 'js' } }), 'P14_VIRTUAL_CONFIGURATION:production-required');
  refused(() => initial.buildStart.handler.call(initialReceiver, { platform: 'browser' }), 'P14_VIRTUAL_CONFIGURATION:production-required');
  refused(() => initial.transform.handler.call(initialReceiver, 'fixture', '\0virtual:__sveltekit/env'), 'P14_VIRTUAL_ENVIRONMENT_CHANGED');
  refused(() => initial.transform.handler.call(initialReceiver, 'fixture', '\0unknown'), 'UNREVIEWED_VIRTUAL_MODULE');
  refused(() => initial.generateBundle.handler.call(initialReceiver, { format: 'es' }, {}), 'P14_VIRTUAL_ENVIRONMENT_CHANGED');
  refused(() => initial.configResolved(initialConfig), 'P14_VIRTUAL_CONFIGURATION:repeated');
  refused(() => initial.configResolved(configuration(initial, true)), 'P14_VIRTUAL_CONFIGURATION:repeated');

  const noAuthority = factory();
  const noAuthorityConfig = preprocessing(noAuthority);
  const unrecognized = { name: 'unrecognized-preprocess-plugin', load: () => 'PRIVATE-SENTINEL' };
  noAuthorityConfig.plugins.unshift(unrecognized);
  const originalLoad = unrecognized.load;
  noAuthority.configResolved(noAuthorityConfig);
  assertLifecycle(unrecognized.load === originalLoad && writes === 0, 'preprocess-no-producer-wrapping');
  positives++;

  const legacy = replayLifecycle(undefined, true);
  legacy.loadFromDirectory();
  assertLifecycle(legacy.oldMissingBinding && legacy.fallback && legacy.nodeEnv === 'development'
    && legacy.resolutions.length === 1, 'legacy-missing-binding-caught-before-direct-config-fallback');
  const fallbackStyleConfig = legacy.stylesheet();
  const repeatedFallbackConfig = legacy.stylesheet();
  assertLifecycle(legacy.resolutions.length === 2 && legacy.resolutions[1].command === 'serve'
    && legacy.resolutions[1].mode === 'development'
    && legacy.resolutions[0].observer !== legacy.resolutions[1].observer
    && fallbackStyleConfig === legacy.resolutions[1].config && repeatedFallbackConfig === fallbackStyleConfig
    && legacy.stylesheetCalls === 2 && writes === 0, 'fallback-nested-serve-and-cached-repeated-style');
  positives++;

  const standalone = replayLifecycle(undefined);
  const standaloneConfig = standalone.stylesheet();
  assertLifecycle(standalone.nodeEnv === 'production' && standalone.resolutions.length === 1
    && standalone.resolutions[0].command === 'build' && standalone.resolutions[0].mode === 'production'
    && standalone.stylesheet() === standaloneConfig && standalone.resolutions.length === 1 && writes === 0,
  'standalone-unset-env-build-preprocess-no-bundler-output');
  positives++;

  const supplied = replayLifecycle(undefined);
  assertLifecycle(supplied.stylesheet(firstStyleConfig) === firstStyleConfig
    && supplied.stylesheet() === firstStyleConfig && supplied.resolutions.length === 0
    && supplied.nodeEnv === undefined, 'provided-resolved-config-branch-and-cache');
  positives++;
  for (const mutation of [
    { ...preprocessing(factory()), mode: 'production' },
    { ...preprocessing(factory()), isWorker: true },
    { ...preprocessing(factory()), experimental: { renderBuiltUrl: callback } },
  ]) {
    const observer = factory();
    refused(() => observer.configResolved(mutation), 'P14_VIRTUAL_CONFIGURATION:preprocessing-context');
  }

  // Every authentication failure is separate and a failed resolution cannot
  // subsequently be retried or promoted on the same observer instance.
  for (const [value, reason] of [[undefined, 'missing-binding'], [null, 'invalid-type'], [true, 'invalid-type'],
    [shortCallback, 'source-bytes'], [changedCallback, 'source-hash']]) {
    const observer = factory();
    const config = configuration(observer, true);
    config.experimental.renderBuiltUrl = value;
    refused(() => observer.configResolved(config), 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:' + reason);
    refused(() => observer.configResolved(configuration(observer, true)), 'P14_VIRTUAL_CONFIGURATION:repeated');
  }
  for (const mutation of [{ command: 'unknown' }, { mode: 'development' }, { isWorker: true }]) {
    const observer = factory();
    refused(() => observer.configResolved({ ...configuration(observer, true), ...mutation }), 'P14_VIRTUAL_CONFIGURATION:production-context');
  }
  for (const kind of ['member', 'version']) {
    const observer = factory();
    badMember = kind === 'member';
    badVersion = kind === 'version';
    refused(() => observer.configResolved(configuration(observer, true)), kind === 'member' ? 'P14_VIRTUAL_PRODUCER_MEMBER' : 'P14_VIRTUAL_DEPENDENCY_VERSION');
    badMember = false;
    badVersion = false;
  }

  for (const ssr of [true, false]) {
    const observer = factory();
    const config = configuration(observer, ssr);
    /** @type {FixturePlugin} */
    const kit = { name: 'vite-plugin-sveltekit-virtual-modules', load: kitLoad };
    const apply = /** @type {FixturePlugin} */ ({ name: 'native:import-analysis-build', applyToEnvironment: nativeApply });
    /** @type {FixturePlugin} */
    const wrong = { name: 'unrecognized-production-plugin', load: () => 'same-looking-virtual-code' };
    config.plugins.unshift(kit, apply, wrong);
    observer.configResolved(config);
    assertLifecycle(kit.load !== kitLoad && apply.applyToEnvironment !== nativeApply, 'production-wrappers-installed');
    const env = environment(config, ssr);
    const receiver = { environment: env };
    config.experimental.renderBuiltUrl = identicalCallback;
    refused(() => observer.options.handler.call(receiver, { moduleTypes: { '.css': 'js' } }), 'P14_VIRTUAL_CONTEXT:renderBuiltUrl:function');
    config.experimental.renderBuiltUrl = callback;
    observer.options.handler.call(receiver, { moduleTypes: { '.css': 'js' } });
    refused(() => observer.options.handler.call(receiver, { moduleTypes: { '.css': 'js' } }), 'P14_VIRTUAL_BUILD_OPTIONS');
    // The authenticated apply hook's actual selected result is required. The
    // fake native prototype contains no executable native/upstream code.
    const preload = native({ preloadCode: 'fixture-preload', insertPreload: !ssr,
      optimizeModulePreloadRelativePaths: false, renderBuiltUrl: true, isRelativeBase: !ssr });
    selectedNativeResult = preload;
    const producer = apply.applyToEnvironment;
    assertLifecycle(typeof producer === 'function', 'wrapped-apply');
    if (producer) assertLifecycle(producer(env) === preload, 'native-result-identity');
    observer.buildStart.handler.call(receiver, { platform: ssr ? 'node' : 'browser' });
    refused(() => observer.buildStart.handler.call(receiver, { platform: ssr ? 'node' : 'browser' }), 'P14_VIRTUAL_BUILD_OPTIONS');
    if (producer) refused(() => producer(env), 'P14_AMBIGUOUS_NATIVE_PRODUCER');
    // The real imported captureLoad guard rejects this actual selected loader
    // before digesting its arbitrary text: only the bound Kit object may load it.
    const selectedLoader = wrong.load;
    assertLifecycle(typeof selectedLoader === 'function', 'selected-wrong-loader');
    if (selectedLoader) refused(() => selectedLoader.call(receiver, '\0virtual:__sveltekit/env'), 'P14_WRONG_VIRTUAL_LOADER');
    selectedNativeResult = undefined;
    refused(() => observer.transform.handler.call(receiver, 'fixture', '\0unknown'), 'UNREVIEWED_VIRTUAL_MODULE');
    refused(() => observer.configResolved(config), 'P14_VIRTUAL_CONFIGURATION:repeated');
    positives++;
  }
  assertLifecycle(writes === 0, 'no-test-graph-output-or-filesystem-write');
  return { passed: true, positive_sequences: positives, negative_cases: negatives,
    actual_observer_factory_and_hooks: true, successful_config_reuse: true, fallback_nested_serve: true,
    source_derived_resolution_order_and_node_env: true, repeated_stylesheet_transform_cache: true,
    standalone_and_provided_resolved_config: true, legacy_missing_binding_replayed: true,
    preprocessing_cannot_authorize_virtual_modules: true, production_callback_identity: true,
    common_member_and_version_guards: true, digest_and_native_interfaces_mocked: true,
    dependency_execution: false, filesystem_or_network_execution: false };
}
