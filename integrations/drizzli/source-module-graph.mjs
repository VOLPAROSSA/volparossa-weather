// SPDX-License-Identifier: GPL-3.0-only
// New-source recipe only. Observations never authorize code or product admission.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { types as nodeTypes } from 'node:util';
import { viteBuildImportAnalysisPlugin } from 'rolldown/experimental';
import { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler } from './virtual-module-guards.mjs';
import { validateVirtualContext, preloadContextOptions } from './virtual-module-context.mjs';
import { createNativePluginGuard } from './native-plugin-guards.mjs';

/** @typedef {import('vite').Plugin<unknown>} VitePlugin */
/** @typedef {import('vite').Environment} Environment */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['load']>>} LoadHandler */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['transform']>>} TransformHandler */
/** @typedef {NonNullable<VitePlugin['applyToEnvironment']>} ApplyHandler */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['configResolved']>>} ConfigResolvedHandler */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['options']>>} OptionsHandler */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['outputOptions']>>} OutputOptionsHandler */
/** @typedef {{sha256:string,bytes:number}} Digest */
/** @typedef {'sveltekit'|'vite'|'rolldown'} Producer */
/** @typedef {{kind:'kit-load'|'native-dispatch'|'runtime-task',sha256:string,bytes:number}} LoadReceipt */
/** @typedef {{id:string,producer:Producer,plugin:string,hook_sha256:string|null,load:LoadReceipt,transformed:Digest,native_member_sha256:string|null}} VirtualReceipt */
/** @typedef {import('./virtual-module-context.mjs').GraphEnvironment} GraphEnvironment */
/** @typedef {{plugin:VitePlugin,prototype:object|null,load:VitePlugin['load'],transform:VitePlugin['transform'],apply:VitePlugin['applyToEnvironment'],options:VitePlugin['options'],outputOptions:VitePlugin['outputOptions'],state:string}} PluginSeal */
/** @typedef {{context:GraphEnvironment,plugins:readonly VitePlugin[],seals:PluginSeal[],receipts:Map<string,VirtualReceipt>,loads:Map<string,import('./virtual-module-guards.mjs').LoadReceipt>,preload:VitePlugin|null}} EnvironmentState */

const KIT_PLUGIN = 'vite-plugin-sveltekit-virtual-modules';
const KIT_HOOK = '42da1ec046c9e229f91a2ed83d7f149768231f40f968815c0f7e361a0b66011f';
// Exact Kit 2.70.1 config hook method in the already member-bound index.js.
const KIT_RENDER_BUILT_URL = 'b2e81ff8fba88a56e0ce4c2ef946bb15a7903cc5d152e75dce33e5dbb0947df1';
const VITE_HOOK = 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376';
const NATIVE_MEMBER = '34e3f5cc135d0fec7f0d9837e30413f1a151037b1568911f074048bf941d68e5';
const RUNTIME = '\0rolldown/runtime.js';
const PRELOAD = '\0vite/preload-helper.js';
const KIT_ENV = '\0virtual:__sveltekit/env';
const KIT_SERVER = '\0virtual:__sveltekit/server';
const IDS = new Set([RUNTIME, PRELOAD, KIT_ENV, KIT_SERVER]);
/** Independently derived from the approved generators; never learned from a run.
 * @type {Record<string,Record<string,Digest>>} */
const EXPECTED = {
  ssr: {
    [RUNTIME]: { bytes: 3823, sha256: '6389c99520e98b0f839779e28a31bd13ea03d6177707348822d88cc0f5887a03' },
    [KIT_ENV]: { bytes: 359, sha256: '3d31b247580a8cd7a2d8db9ba1461d86d1f3fd8771f888fdce12280895349eb5' },
    [KIT_SERVER]: { bytes: 195, sha256: '044ba569e5e503525a22977de015f67c0bc3f6f5deb1f9cf8a5dfec7b4487904' },
  },
  client: {
    [RUNTIME]: { bytes: 4405, sha256: '2027378d81078b5bb25f18920376547f296bebd7be04bd10dc2e0221a5aa0991' },
    [PRELOAD]: { bytes: 2198, sha256: 'a4a1c9fde4f431ffef7ef93071a0c5d554b9a5b395854243ff982a880b726a7a' },
  },
};
/** @type {Record<string,string>} */
const MEMBERS = {
  '@sveltejs/kit/src/exports/vite/index.js': '48a56f687eeb0429ee4a2138fe15e4ab4d93621d07e47c5dacc44647ea4215f6',
  '@sveltejs/kit/src/core/env.js': '95f4c3419ed4b33657c4b86450fc839f3795e2c46f73f2d9524521b79f92a000',
  'vite/dist/node/chunks/node.js': '5a604cb8f97126675dbdf9044c919b0fd1fe1280bfa4077de225e6adfa213e4a',
  'rolldown/dist/shared/constructors-xEvVj3lN.mjs': '087234cdd6903f7d5d1fd5e44a4cec61965c8755fa36c8d06f26a1a486d65de3',
  'rolldown/dist/experimental-index.mjs': 'c7e3856c8d6b65cbacccc4b1c54aa582d0c34bd5e6040b0a6415c0dbd42e4905',
  'rolldown/dist/shared/normalize-string-or-regex-F14uvr6D.mjs': 'e1cff9111ea8819b0890ae35b1cfd2938a53bf755c6c176d79387133ed7e5f1c',
  'rolldown/dist/shared/binding-BY0qR5iS.mjs': '8c571a4e4ac9561df9d6d7370d6c0d506922b6c106fd693cb2b75b47c3ab028a',
  'rolldown/dist/shared/bindingify-input-options-XrReX_BJ.mjs': 'a778028ca12765b4604b9cb04edf80e1dc6dc096bccbc893317aa03e02ab4890',
  'rolldown/dist/shared/create-bundler-option-YGKfBl_D.mjs': 'fe167cc4ec4b9432074978952993d0f2d18f0fab73a6dfd028b6f00f678727d9',
  '@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node': NATIVE_MEMBER,
};
/** @param {string|Uint8Array} code @returns {Digest} */
const digest = (code) => ({ sha256: createHash('sha256').update(code).digest('hex'), bytes: Buffer.byteLength(code) });
/** @param {string} id @param {GraphEnvironment} context @param {string} code */
function exactCode(id, context, code) {
  const expected = EXPECTED[context.name]?.[id];
  const actual = digest(code);
  if (!expected || expected.sha256 !== actual.sha256 || expected.bytes !== actual.bytes) {
    throw new Error('P14_VIRTUAL_SOURCE_MISMATCH:' + JSON.stringify({ id, environment: context.name, expected: expected ?? null, actual }));
  }
  return actual;
}
/** Bounded snapshots include callback source and regexes, rather than dropping them as JSON does.
 * @param {unknown} value @param {number} [depth] @returns {unknown} */
function snapshot(value, depth = 0) {
  if (depth > 12) throw new Error('P14_PLUGIN_STATE_BOUND');
  if (typeof value === 'function') return { function_sha256: digest(Function.prototype.toString.call(value)).sha256 };
  if (value instanceof RegExp) return { regex: value.source, flags: value.flags };
  if (value === null || typeof value !== 'object') return value === undefined ? { undefined: true } : value;
  if (Array.isArray(value)) return value.map((entry) => snapshot(entry, depth + 1));
  const names = Object.getOwnPropertyNames(value);
  if (names.length > 4096) throw new Error('P14_PLUGIN_STATE_BOUND');
  return Object.fromEntries(names.sort().map((key) => [key, snapshot(Reflect.get(value, key), depth + 1)]));
}
/** @param {VitePlugin} plugin */
function pluginState(plugin) {
  return JSON.stringify(snapshot({ name: plugin.name, load: plugin.load, transform: plugin.transform,
    apply: plugin.applyToEnvironment, enforce: plugin.enforce,
    native: '_options' in plugin ? plugin._options : null }));
}
/** Complete a private flat identity capture while the config is loading, before
 * Vite executes any config hook. The original exported plugin options retain
 * their original structure; only this private security record is flattened.
 * @param {import('vite').PluginOption[]} options @returns {Promise<readonly VitePlugin[]>} */
export async function captureUserPlugins(options) {
  /** @type {VitePlugin[]} */
  const users = [];
  const active = new WeakSet();
  let entries = 0;
  /** @param {import('vite').PluginOption} option @param {number} depth @returns {Promise<void>} */
  const collect = async (option, depth) => {
    if (depth > 16 || ++entries > 1024) throw new Error('P14_NATIVE_USER_PLUGIN_BOUND');
    const value = await option;
    if (!value) return;
    if (Array.isArray(value)) {
      if (active.has(value)) throw new Error('P14_NATIVE_USER_PLUGIN_CYCLE');
      active.add(value);
      for (const child of value) await collect(child, depth + 1);
      active.delete(value);
    } else users.push(value);
  };
  await collect(options, 0);
  return Object.freeze(users);
}
/** The exact staging generator passes original user options before Vite runs
 * any config hook. A later config.plugins mutation cannot hide a user producer.
 * @param {readonly VitePlugin[]} userOptions @returns {VitePlugin} */
export default function sourceModuleGraph(userOptions) {
  if (!Array.isArray(userOptions)) throw new Error('P14_NATIVE:original-user-options');
  const originalUsers = [...userOptions];
  let root = '';
  /** A resolved serve configuration is used by pinned load-config/Svelte CSS
   * preprocessing. It never installs producer wrappers or binds graph state.
   * @type {'unconfigured'|'resolving'|'preprocessing'|'production-ready'} */
  let configuration = 'unconfigured';
  /** @type {import('vite').RenderBuiltAssetUrl|undefined} */
  let renderBuiltUrlCallback;
  /** @type {Set<string>} */
  const validatedInputs = new Set();
  /** @type {string[]} */
  let plugins = [];
  /** @type {WeakMap<VitePlugin,LoadHandler>} */
  const loadWrappers = new WeakMap();
  /** @type {WeakMap<VitePlugin,TransformHandler>} */
  const transformWrappers = new WeakMap();
  /** @type {WeakMap<VitePlugin,ApplyHandler>} */
  const applyWrappers = new WeakMap();
  /** @type {WeakMap<VitePlugin,OptionsHandler>} */
  const optionsWrappers = new WeakMap();
  /** @type {WeakMap<VitePlugin,OutputOptionsHandler>} */
  const outputOptionsWrappers = new WeakMap();
  /** @type {Map<string,VitePlugin>} Native instance returned by the authenticated Vite callback. */
  const nativePreloads = new Map();
  /** @type {Map<string,EnvironmentState>} */
  const states = new Map();
  /** @type {Set<VitePlugin>} */
  const kitPlugins = new Set();
  const nativePrototype = Object.getPrototypeOf(viteBuildImportAnalysisPlugin({
    preloadCode: '', insertPreload: false, optimizeModulePreloadRelativePaths: false, renderBuiltUrl: false, isRelativeBase: true,
  }));
  const nativePlugins = createNativePluginGuard(nativePrototype, digest, snapshot, nodeTypes.isProxy);
  let membersRoot = '';
  /** Protect the input object's actual dispatch fields, rather than evaluating
   * a getter whose later result could differ at native binding time.
   * @type {Map<object,{plugins:unknown,output:unknown}>} */
  const inputOwners = new Map();

  /** @param {object} options @param {string} key @param {boolean} required @returns {unknown} */
  const inputField = (options, key, required) => {
    if (nodeTypes.isProxy(options) || Object.getPrototypeOf(options) !== Object.prototype) throw new Error('P14_NATIVE:input-owner');
    const descriptor = Object.getOwnPropertyDescriptor(options, key);
    if (!descriptor) {
      if (required || key in options) throw new Error('P14_NATIVE:input-field');
      return undefined;
    }
    if (!('value' in descriptor)) throw new Error('P14_NATIVE:input-accessor');
    return descriptor.value;
  };
  /** @param {import('rolldown').InputOptions} options */
  const inputFields = (options) => ({ plugins: inputField(options, 'plugins', true), output: inputField(options, 'output', false) });
  const checkInputOwners = () => {
    for (const [owner, expected] of inputOwners) {
      if (inputField(owner, 'plugins', true) !== expected.plugins || inputField(owner, 'output', false) !== expected.output) {
        throw new Error('P14_NATIVE:input-owner-changed');
      }
    }
  };
  /** @param {Environment} environment @param {import('rolldown').InputOptions} options */
  const checkInputs = (environment, options) => {
    checkInputOwners();
    const fields = inputFields(options);
    nativePlugins.inputs(environment.name, environment.plugins, fields.plugins);
    checkConfiguredOutputs(fields.output);
    inputOwners.set(options, fields);
  };
  /** Final post-options protection changes only the already verified dispatch
   * fields. Rolldown subsequently maps these lists into fresh arrays.
   * @param {Environment} environment @param {import('rolldown').InputOptions} options */
  const finalizeInputs = (environment, options) => {
    checkInputs(environment, options);
    const fields = inputFields(options);
    nativePlugins.finalizeInputs(environment.name, environment.plugins, fields.plugins);
    for (const [owner, expected] of inputOwners) {
      for (const key of ['plugins', 'output']) {
        const descriptor = Object.getOwnPropertyDescriptor(owner, key);
        const value = key === 'plugins' ? expected.plugins : expected.output;
        Object.defineProperty(owner, key, { value, enumerable: descriptor?.enumerable ?? false,
          writable: false, configurable: false });
      }
      nativePlugins.finalizeOutput(expected.output);
    }
    checkInputOwners();
  };

  /** Check the original approved members before any user configResolved hook.
   * A source-derived native registry cannot be initialized after user mutation.
   * @param {import('vite').ResolvedConfig} config */
  const verifyProducerMembers = (config) => {
    const directory = resolve(config.root);
    if (membersRoot) {
      if (membersRoot !== directory) throw new Error('P14_VIRTUAL_PRODUCER_ROOT');
      return;
    }
    for (const [member, sha256] of Object.entries(MEMBERS)) {
      if (digest(readFileSync(resolve(directory, 'node_modules', member))).sha256 !== sha256) throw new Error('P14_VIRTUAL_PRODUCER_MEMBER');
    }
    for (const [name, version] of [['@sveltejs/kit', '2.70.1'], ['vite', '8.3.1'], ['rolldown', '1.2.11'], ['@rolldown/binding-linux-x64-gnu', '1.2.11']]) {
      /** @type {unknown} */
      const metadata = JSON.parse(readFileSync(resolve(directory, 'node_modules', name, 'package.json'), 'utf8'));
      if (!metadata || typeof metadata !== 'object' || !('name' in metadata) || !('version' in metadata)
          || metadata.name !== name || metadata.version !== version) throw new Error('P14_VIRTUAL_DEPENDENCY_VERSION');
    }
    membersRoot = directory;
  };

  /** Configured output plugins are not present in the original Kit/Vite build.
   * Reject before their outputOptions hooks could receive execution authority.
   * @param {unknown} output */
  const checkConfiguredOutputs = (output) => {
    nativePlugins.output(output);
  };
  /** Vite has completed resolvePlugins before any configResolved callback.
   * Later environment selection builds fresh arrays; this source-derived core
   * topology is never a place to introduce another user/native producer.
   * @param {import('vite').ResolvedConfig} config */
  const checkConfiguration = (config) => {
    verifyProducerMembers(config);
    const value = inputField(config, 'plugins', true);
    if (!Array.isArray(value) || nodeTypes.isProxy(value)) throw new Error('P14_NATIVE:configuration-list');
    Object.freeze(value);
    nativePlugins.configuration(value);
    const descriptor = Object.getOwnPropertyDescriptor(config, 'plugins');
    Object.defineProperty(config, 'plugins', { value, enumerable: descriptor?.enumerable ?? true,
      writable: false, configurable: false });
  };

  /** Vite's environment proxy supplies shared fields from resolved config and
   * build/consumer fields from the actual environment. Never substitute another
   * environment or admit an arbitrary observed callback as its authority.
   * @param {Environment} environment @returns {GraphEnvironment} */
  const contextOf = (environment) => {
    if (configuration !== 'production-ready') throw new Error('P14_VIRTUAL_CONFIGURATION:production-required');
    const config = environment.config;
    return validateVirtualContext({ name: environment.name, command: config.command,
      mode: config.mode, isBundled: config.isBundled, isWorker: config.isWorker,
      lib: config.build.lib, watch: config.build.watch, write: config.build.write,
      consumer: config.consumer, ssr: config.build.ssr, base: config.base,
      platform: config.build.rolldownOptions.platform ?? (environment.name === 'ssr' ? 'node' : 'browser'),
      renderBuiltUrl: config.experimental.renderBuiltUrl,
      devMode: config.build.rolldownOptions.experimental?.devMode,
      moduleTypes: config.build.rolldownOptions.moduleTypes,
      modulePreload: config.build.modulePreload }, renderBuiltUrlCallback);
  };

  /** @param {Environment} environment */
  const stateOf = (environment) => {
    const state = states.get(environment.name);
    if (!state || JSON.stringify(contextOf(environment)) !== JSON.stringify(state.context)) throw new Error('P14_VIRTUAL_ENVIRONMENT_CHANGED');
    return state;
  };
  /** @param {VitePlugin} plugin @param {string} id @param {Environment} environment @param {import('rolldown').LoadResult} result */
  const loaded = (plugin, id, environment, result) => {
    if (!IDS.has(id) || result === null || result === undefined) return result;
    const state = stateOf(environment);
    captureLoad({ id, producer: plugin, expectedProducer: kitPlugins.has(plugin) && (id === KIT_ENV || id === KIT_SERVER) ? plugin : null,
      expected: EXPECTED[state.context.name]?.[id], receipts: state.loads }, result);
    return result;
  };
  /** Install before Vite binds hooks. The original hook object metadata is retained.
   * @param {VitePlugin} plugin */
  const preparePlugin = (plugin) => {
    if (plugin.load && !loadWrappers.has(plugin)) {
      const original = typeof plugin.load === 'function' ? plugin.load : plugin.load.handler;
      if (plugin.name === KIT_PLUGIN) {
        if (digest(Function.prototype.toString.call(original)).sha256 !== KIT_HOOK) throw new Error('P14_KIT_LOADER_SOURCE');
        kitPlugins.add(plugin);
      }
      const wrapper = observeHook(original, (result, [id], context) => {
        if (IDS.has(id)) loaded(plugin, id, context.environment, result);
      });
      loadWrappers.set(plugin, wrapper);
      const previous = plugin.load;
      plugin.load = typeof plugin.load === 'function' ? wrapper : replaceHandler(plugin.load, wrapper);
      nativePlugins.controlledHook(plugin, 'load', previous, plugin.load);
    }
    if (plugin.transform && !transformWrappers.has(plugin) && plugin !== observer) {
      const original = typeof plugin.transform === 'function' ? plugin.transform : plugin.transform.handler;
      const wrapper = observeHook(original, (result, [, id], context) => {
        if (IDS.has(id)) rejectLateTransform(result, states.get(context.environment.name)?.receipts.has(id) ?? false);
      });
      transformWrappers.set(plugin, wrapper);
      const previous = plugin.transform;
      plugin.transform = typeof plugin.transform === 'function' ? wrapper : replaceHandler(plugin.transform, wrapper);
      nativePlugins.controlledHook(plugin, 'transform', previous, plugin.transform);
    }
    if (plugin.applyToEnvironment && !applyWrappers.has(plugin)) {
      const original = plugin.applyToEnvironment;
      const preloadProducer = plugin.name === 'native:import-analysis-build';
      if (preloadProducer && digest(Function.prototype.toString.call(original)).sha256 !== VITE_HOOK) throw new Error('P14_VITE_PRODUCER_SOURCE');
      /** @param {Awaited<ReturnType<ApplyHandler>>} value @param {Parameters<ApplyHandler>[0]} environment */
      const prepared = (value, environment) => {
        if (value === true || !value) return;
        if (Array.isArray(value)) {
          for (let index = 0; index < value.length; index++) value[index] = prepareOption(value[index], environment);
          return;
        }
        if (preloadProducer) {
          if (nativePreloads.has(environment.name) || Object.getPrototypeOf(value) !== nativePrototype
              || value.name !== 'builtin:vite-build-import-analysis') throw new Error('P14_AMBIGUOUS_NATIVE_PRODUCER');
          nativePreloads.set(environment.name, value);
        }
        preparePlugin(value);
      };
      /** @param {import('vite').PluginOption} value @param {Parameters<ApplyHandler>[0]} environment @returns {import('vite').PluginOption} */
      const prepareOption = (value, environment) => observeResult(value, (entry) => prepared(entry, environment));
      const wrapper = observeHook(original, (value, [environment]) => {
        nativePlugins.captureApply(plugin, environment.name, value);
        prepared(value, environment);
      });
      applyWrappers.set(plugin, wrapper);
      plugin.applyToEnvironment = wrapper;
      nativePlugins.controlledHook(plugin, 'applyToEnvironment', original, wrapper);
    }
    if (plugin.options && plugin !== observer && !optionsWrappers.has(plugin)) {
      const previous = plugin.options;
      const original = typeof previous === 'function' ? previous : previous.handler;
      /** @type {OptionsHandler} */
      const wrapper = function(options) {
        contextOf(this.environment);
        checkInputs(this.environment, options);
        return observeResult(original.call(this, options), (result) => {
          const current = result || options;
          checkInputs(this.environment, current);
        });
      };
      optionsWrappers.set(plugin, wrapper);
      plugin.options = typeof previous === 'function' ? wrapper : replaceHandler(previous, wrapper);
      nativePlugins.controlledHook(plugin, 'options', previous, plugin.options);
    }
    if (plugin.outputOptions && plugin !== observer && !outputOptionsWrappers.has(plugin)) {
      const previous = plugin.outputOptions;
      const original = typeof previous === 'function' ? previous : previous.handler;
      /** @type {OutputOptionsHandler} */
      const wrapper = function(options) {
        contextOf(this.environment);
        checkInputOwners();
        nativePlugins.environment(this.environment.name, this.environment.plugins);
        nativePlugins.output(options);
        const result = original.call(this, options);
        nativePlugins.output(result || options);
        checkInputOwners();
        nativePlugins.environment(this.environment.name, this.environment.plugins);
        return result;
      };
      outputOptionsWrappers.set(plugin, wrapper);
      plugin.outputOptions = typeof previous === 'function' ? wrapper : replaceHandler(previous, wrapper);
      nativePlugins.controlledHook(plugin, 'outputOptions', previous, plugin.outputOptions);
    }
  };
  /** @param {Environment} environment */
  const checkState = (environment) => {
    const state = stateOf(environment);
    if (environment.plugins.length !== state.plugins.length) throw new Error('P14_PLUGIN_SET_CHANGED');
    for (let index = 0; index < state.seals.length; index++) {
      const seal = state.seals[index];
      if (environment.plugins[index] !== seal.plugin || Object.getPrototypeOf(seal.plugin) !== seal.prototype || seal.plugin.load !== seal.load
          || seal.plugin.transform !== seal.transform || seal.plugin.applyToEnvironment !== seal.apply
          || seal.plugin.options !== seal.options || seal.plugin.outputOptions !== seal.outputOptions
          || pluginState(seal.plugin) !== seal.state) throw new Error('P14_PLUGIN_SET_CHANGED');
      if (seal.plugin.load) {
        const handler = typeof seal.plugin.load === 'function' ? seal.plugin.load : seal.plugin.load.handler;
        if (handler !== loadWrappers.get(seal.plugin)) throw new Error('P14_UNWRAPPED_LOAD_HOOK');
      }
      if (seal.plugin.transform) {
        const handler = typeof seal.plugin.transform === 'function' ? seal.plugin.transform : seal.plugin.transform.handler;
        const expected = seal.plugin === observer ? observerTransform : transformWrappers.get(seal.plugin);
        if (handler !== expected) throw new Error('P14_UNWRAPPED_TRANSFORM_HOOK');
      }
      if (seal.plugin.applyToEnvironment && seal.plugin.applyToEnvironment !== applyWrappers.get(seal.plugin)) throw new Error('P14_UNWRAPPED_ENVIRONMENT_HOOK');
      if (seal.plugin.options && seal.plugin !== observer) {
        const handler = typeof seal.plugin.options === 'function' ? seal.plugin.options : seal.plugin.options.handler;
        if (handler !== optionsWrappers.get(seal.plugin)) throw new Error('P14_UNWRAPPED_OPTIONS_HOOK');
      }
      if (seal.plugin.outputOptions && seal.plugin !== observer) {
        const handler = typeof seal.plugin.outputOptions === 'function' ? seal.plugin.outputOptions : seal.plugin.outputOptions.handler;
        if (handler !== outputOptionsWrappers.get(seal.plugin)) throw new Error('P14_UNWRAPPED_OUTPUT_OPTIONS_HOOK');
      }
    }
    nativePlugins.environment(environment.name, environment.plugins);
    checkInputOwners();
    return state;
  };
  /** @param {string} id @param {EnvironmentState} state */
  const normalize = (id, state) => {
    if (id.startsWith('\0')) {
      const receipt = state.receipts.get(id);
      if (!receipt) throw new Error('P14_UNBOUND_VIRTUAL_REFERENCE');
      return { id, kind: 'virtual', producer: receipt.producer };
    }
    const path = relative(root, id.split('?')[0]);
    if (path.startsWith('../') || path.startsWith('/')) throw new Error('SOURCE_GRAPH_EXTERNAL_MODULE');
    return { id: path + (id.includes('?') ? '?' + id.split('?').slice(1).join('?') : ''), kind: 'file' };
  };

  /** @type {VitePlugin} */
  const observer = {
    name: 'volparossa-source-module-graph-v2',
    enforce: 'post',
    config: {
      order: 'post',
      async handler(config, environment) {
        if (environment.command !== 'build' || environment.mode !== 'production') return;
        const users = [observer, ...originalUsers];
        const sortedUsers = [
          ...users.filter((plugin) => plugin.enforce === 'pre'),
          ...users.filter((plugin) => plugin.enforce !== 'pre' && plugin.enforce !== 'post'),
          ...users.filter((plugin) => plugin.enforce === 'post'),
        ];
        const ownIndex = sortedUsers.indexOf(observer);
        if (ownIndex < 0) throw new Error('P14_NATIVE_USER_PLUGIN_CONTEXT');
        for (let index = ownIndex + 1; index < sortedUsers.length; index++) {
          const hook = sortedUsers[index].config;
          if (hook && typeof hook !== 'function' && hook.order === 'post') throw new Error('P14_NATIVE_LATE_CONFIG_HOOK');
        }
        nativePlugins.setUsers(users);
        // Vite invokes configResolved hooks concurrently. Capture the original
        // core plugin objects before the first user hook, then check again on
        // resolution of each user Promise. Only our own wrapping updates seals.
        for (const plugin of users) {
          if (!plugin.configResolved || plugin === observer) continue;
          const previous = plugin.configResolved;
          const original = typeof previous === 'function' ? previous : previous.handler;
          /** @type {ConfigResolvedHandler} */
          const wrapper = function(resolved) {
            checkConfiguration(resolved);
            return observeResult(original.call(this, resolved), () => checkConfiguration(resolved));
          };
          plugin.configResolved = typeof previous === 'function' ? wrapper : replaceHandler(previous, wrapper);
        }
      },
    },
    configResolved(config) {
      if (configuration !== 'unconfigured') throw new Error('P14_VIRTUAL_CONFIGURATION:repeated');
      configuration = 'resolving';
      root = resolve(config.root);
      plugins = config.plugins.map((plugin) => plugin.name);
      verifyProducerMembers(config);
      const callback = config.experimental.renderBuiltUrl;
      // load-config 0.2.0 resolves serve/development before returning Svelte's
      // preprocessors. Kit 2.70.1 supplies no renderBuiltUrl in that context.
      // Successful vite-plugin-svelte configuration attaches this exact config
      // to style.__resolvedConfig; CSS preprocessing does not run bundler hooks.
      if (config.command === 'serve') {
        if (config.mode !== 'development' || config.isWorker !== false || callback !== undefined) {
          throw new Error('P14_VIRTUAL_CONFIGURATION:preprocessing-context');
        }
        configuration = 'preprocessing';
        return;
      }
      if (config.command !== 'build' || config.mode !== 'production' || config.isWorker !== false) {
        throw new Error('P14_VIRTUAL_CONFIGURATION:production-context');
      }
      if (callback === undefined) throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:missing-binding');
      if (typeof callback !== 'function') throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:invalid-type');
      const source = digest(Function.prototype.toString.call(callback));
      if (source.bytes !== 1076) throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:source-bytes');
      if (source.sha256 !== KIT_RENDER_BUILT_URL) throw new Error('P14_VIRTUAL_CONTEXT:renderBuiltUrl:source-hash');
      renderBuiltUrlCallback = callback;
      checkConfiguration(config);
      for (const plugin of config.plugins) preparePlugin(plugin);
      configuration = 'production-ready';
    },
    options: {
      order: 'post',
      handler(options) {
        const environment = this.environment;
        contextOf(environment);
        checkInputs(environment, options);
        if (validatedInputs.has(environment.name) || options.experimental?.devMode
            || JSON.stringify(options.moduleTypes) !== JSON.stringify({ '.css': 'js' })) throw new Error('P14_VIRTUAL_BUILD_OPTIONS');
        const ownIndex = environment.plugins.indexOf(observer);
        for (let index = 0; index < environment.plugins.length; index++) {
          const plugin = environment.plugins[index];
          if (!plugin.options || plugin === observer) continue;
          const actual = typeof plugin.options === 'function' ? plugin.options : plugin.options.handler;
          if (actual !== optionsWrappers.get(plugin)) throw new Error('P14_UNWRAPPED_OPTIONS_HOOK');
          const order = typeof plugin.options === 'function' ? undefined : plugin.options.order;
          if (order !== undefined && order !== null && order !== 'pre' && order !== 'post') throw new Error('P14_UNREVIEWED_OPTIONS_ORDER');
          if (order === 'post' && index > ownIndex) throw new Error('P14_LATE_OPTIONS_HOOK');
        }
        validatedInputs.add(environment.name);
        finalizeInputs(environment, options);
        return null;
      },
    },
    outputOptions: {
      order: 'post',
      handler(options) {
        const environment = this.environment;
        contextOf(environment);
        checkInputOwners();
        if (!validatedInputs.has(environment.name)) throw new Error('P14_VIRTUAL_BUILD_OPTIONS');
        nativePlugins.environment(environment.name, environment.plugins);
        nativePlugins.output(options);
        const ownIndex = environment.plugins.indexOf(observer);
        for (let index = 0; index < environment.plugins.length; index++) {
          const plugin = environment.plugins[index];
          if (!plugin.outputOptions || plugin === observer) continue;
          const actual = typeof plugin.outputOptions === 'function' ? plugin.outputOptions : plugin.outputOptions.handler;
          if (actual !== outputOptionsWrappers.get(plugin)) throw new Error('P14_UNWRAPPED_OUTPUT_OPTIONS_HOOK');
          const order = typeof plugin.outputOptions === 'function' ? undefined : plugin.outputOptions.order;
          if (order !== undefined && order !== null && order !== 'pre' && order !== 'post') throw new Error('P14_UNREVIEWED_OUTPUT_OPTIONS_ORDER');
          if (order === 'post' && index > ownIndex) throw new Error('P14_LATE_OUTPUT_OPTIONS_HOOK');
        }
        nativePlugins.finalizeOutput(options);
        return null;
      },
    },
    buildStart: {
      order: 'post',
      handler(options) {
        const environment = this.environment;
        const context = contextOf(environment);
        if (states.has(context.name) || !validatedInputs.has(context.name)
            || options.platform !== context.platform) throw new Error('P14_VIRTUAL_BUILD_OPTIONS');
        nativePlugins.environment(context.name, environment.plugins);
        checkInputOwners();
        let kits = 0;
        const preload = nativePreloads.get(context.name) ?? null;
        for (const plugin of environment.plugins) {
          if (plugin.name === KIT_PLUGIN) kits++;
          if (plugin.load) {
            const actual = typeof plugin.load === 'function' ? plugin.load : plugin.load.handler;
            if (actual !== loadWrappers.get(plugin)) throw new Error('P14_UNWRAPPED_LOAD_HOOK');
          }
          if (plugin.transform && plugin !== observer) {
            const actual = typeof plugin.transform === 'function' ? plugin.transform : plugin.transform.handler;
            if (actual !== transformWrappers.get(plugin)) throw new Error('P14_UNWRAPPED_TRANSFORM_HOOK');
            const order = typeof plugin.transform === 'function' ? undefined : plugin.transform.order;
            if (order !== undefined && order !== null && order !== 'pre' && order !== 'post') throw new Error('P14_UNREVIEWED_TRANSFORM_ORDER');
          }
          if (plugin.applyToEnvironment && plugin.applyToEnvironment !== applyWrappers.get(plugin)) throw new Error('P14_UNWRAPPED_ENVIRONMENT_HOOK');
          if (plugin.name === 'builtin:vite-build-import-analysis' && plugin !== preload) throw new Error('P14_WRONG_NATIVE_PRODUCER');
        }
        if (kits !== 1 || kitPlugins.size !== 1 || !preload) throw new Error('P14_AMBIGUOUS_VIRTUAL_PRODUCER');
        if (!('_options' in preload) || !preload._options || typeof preload._options !== 'object') throw new Error('P14_PRELOAD_OPTIONS');
        const native = preload._options;
        const expectedOptions = preloadContextOptions(context);
        const keys = Object.keys(native).sort().join(',');
        if (keys !== 'insertPreload,isRelativeBase,optimizeModulePreloadRelativePaths,preloadCode,renderBuiltUrl'
            || !('preloadCode' in native) || typeof native.preloadCode !== 'string'
            || !('insertPreload' in native) || native.insertPreload !== expectedOptions.insertPreload
            || !('optimizeModulePreloadRelativePaths' in native) || native.optimizeModulePreloadRelativePaths !== expectedOptions.optimizeModulePreloadRelativePaths
            || !('renderBuiltUrl' in native) || native.renderBuiltUrl !== expectedOptions.renderBuiltUrl
            || !('isRelativeBase' in native) || native.isRelativeBase !== expectedOptions.isRelativeBase) throw new Error('P14_PRELOAD_OPTIONS');
        // Exact Kit renderBuiltUrl is present in both contexts. Pinned Vite
        // chooses the already approved relative helper even for SSR base '/'.
        const expectedPreload = EXPECTED.client[PRELOAD];
        const preloadCode = digest(native.preloadCode);
        if (preloadCode.sha256 !== expectedPreload.sha256 || preloadCode.bytes !== expectedPreload.bytes) throw new Error('P14_PRELOAD_OPTIONS');
        states.set(context.name, { context, plugins: [...environment.plugins], loads: new Map(), receipts: new Map(), preload,
          seals: environment.plugins.map((plugin) => ({ plugin, prototype: Object.getPrototypeOf(plugin), load: plugin.load, transform: plugin.transform,
            apply: plugin.applyToEnvironment, options: plugin.options, outputOptions: plugin.outputOptions, state: pluginState(plugin) })) });
      },
    },
    transform: {
      order: 'post',
      handler(code, id) {
        if (!id.startsWith('\0')) return null;
        if (!IDS.has(id)) throw new Error('UNREVIEWED_VIRTUAL_MODULE');
        const state = checkState(this.environment);
        if (state.receipts.has(id)) throw new Error('P14_AMBIGUOUS_VIRTUAL_TRANSFORM');
        const transformed = exactCode(id, state.context, code);
        const kit = id === KIT_ENV || id === KIT_SERVER;
        const load = kit ? state.loads.get(id) : { kind: id === RUNTIME ? 'runtime-task' : 'native-dispatch', ...transformed };
        if (!load) throw new Error('P14_MISSING_VIRTUAL_LOAD');
        state.receipts.set(id, { id, producer: kit ? 'sveltekit' : id === RUNTIME ? 'rolldown' : 'vite',
          plugin: kit ? KIT_PLUGIN : id === RUNTIME ? 'rolldown-runtime-module-task' : 'builtin:vite-build-import-analysis',
          hook_sha256: kit ? KIT_HOOK : id === PRELOAD ? VITE_HOOK : null,
          load: /** @type {LoadReceipt} */ (load), transformed, native_member_sha256: kit ? null : NATIVE_MEMBER });
        return null;
      },
    },
    generateBundle: {
      order: 'post',
      handler(options, bundle) {
        const state = checkState(this.environment);
        const outputs = Object.fromEntries(Object.entries(bundle).sort().map(([name, item]) => {
          if (item.type === 'asset') return [name, { type: 'asset', names: item.names ?? [], originalFileNames: item.originalFileNames ?? [], ...digest(item.source) }];
          return [name, {
            type: 'chunk', ...digest(item.code), isEntry: item.isEntry, isDynamicEntry: item.isDynamicEntry,
            imports: [...item.imports].sort(), dynamicImports: [...item.dynamicImports].sort(),
            facadeModuleId: item.facadeModuleId === null ? null : normalize(item.facadeModuleId, state),
            moduleIds: item.moduleIds.map((id) => normalize(id, state)),
            modules: Object.entries(item.modules).sort().map(([id, info]) => {
              if (id.startsWith('\0') && info.code === null) throw new Error('P14_MISSING_VIRTUAL_RENDERED_CODE');
              return {
                ...normalize(id, state), renderedLength: info.renderedLength, renderedExports: info.renderedExports,
                rendered_sha256: info.code === null ? null : digest(info.code).sha256,
                rendered_bytes: info.code === null ? null : digest(info.code).bytes,
              };
            }),
          }];
        }));
        const raw = JSON.stringify({ schema: 2, kind: 'volparossa-drizzli-module-graph', admitted: false,
          format: options.format, plugins, environment: state.context,
          virtualModules: [...state.receipts.values()].sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0), outputs });
        if (Buffer.byteLength(raw) > 8 * 1024 * 1024) throw new Error('SOURCE_GRAPH_BOUND');
        const directory = resolve(root, '.volparossa-source-graphs');
        mkdirSync(directory, { recursive: true, mode: 0o700 });
        writeFileSync(resolve(directory, digest(raw).sha256 + '.json'), raw + '\n', { flag: 'wx', mode: 0o600 });
      },
    },
  };
  const observerTransform = observer.transform && (typeof observer.transform === 'function' ? observer.transform : observer.transform.handler);
  return observer;
}
