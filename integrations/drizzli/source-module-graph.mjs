// SPDX-License-Identifier: GPL-3.0-only
// New-source recipe only. Observations never authorize code or product admission.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { viteBuildImportAnalysisPlugin } from 'rolldown/experimental';
import { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler } from './virtual-module-guards.mjs';

/** @typedef {import('vite').Plugin<unknown>} VitePlugin */
/** @typedef {import('vite').Environment} Environment */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['load']>>} LoadHandler */
/** @typedef {import('vite').HookHandler<NonNullable<VitePlugin['transform']>>} TransformHandler */
/** @typedef {NonNullable<VitePlugin['applyToEnvironment']>} ApplyHandler */
/** @typedef {{sha256:string,bytes:number}} Digest */
/** @typedef {'sveltekit'|'vite'|'rolldown'} Producer */
/** @typedef {{kind:'kit-load'|'native-dispatch'|'runtime-task',sha256:string,bytes:number}} LoadReceipt */
/** @typedef {{id:string,producer:Producer,plugin:string,hook_sha256:string|null,load:LoadReceipt,transformed:Digest,native_member_sha256:string|null}} VirtualReceipt */
/** @typedef {{name:string,consumer:string,ssr:boolean,base:string,platform:string}} GraphEnvironment */
/** @typedef {{plugin:VitePlugin,load:VitePlugin['load'],transform:VitePlugin['transform'],apply:VitePlugin['applyToEnvironment'],state:string}} PluginSeal */
/** @typedef {{context:GraphEnvironment,plugins:readonly VitePlugin[],seals:PluginSeal[],receipts:Map<string,VirtualReceipt>,loads:Map<string,import('./virtual-module-guards.mjs').LoadReceipt>,preload:VitePlugin|null}} EnvironmentState */

const KIT_PLUGIN = 'vite-plugin-sveltekit-virtual-modules';
const KIT_HOOK = '42da1ec046c9e229f91a2ed83d7f149768231f40f968815c0f7e361a0b66011f';
const VITE_HOOK = 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376';
const NATIVE_MEMBER = '34e3f5cc135d0fec7f0d9837e30413f1a151037b1568911f074048bf941d68e5';
const RUNTIME = '\0rolldown/runtime.js';
const PRELOAD = '\0vite/preload-helper.js';
const KIT_ENV = '\0virtual:__sveltekit/env';
const KIT_SERVER = '\0virtual:__sveltekit/server';
const IDS = new Set([RUNTIME, PRELOAD, KIT_ENV, KIT_SERVER]);
const NATIVE_NAMES = new Set([
  'builtin:oxc-runtime', 'builtin:vite-json', 'builtin:vite-resolve',
  'builtin:vite-transform', 'builtin:vite-dynamic-import-vars', 'builtin:vite-import-glob',
  'builtin:vite-build-import-analysis', 'builtin:vite-manifest', 'builtin:vite-reporter',
  'builtin:vite-load-fallback', 'builtin:vite-module-preload-polyfill', 'builtin:vite-web-worker-post',
]);
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
  'rolldown/dist/shared/normalize-string-or-regex-F14uvr6D.mjs': 'e1cff9111ea8819b0890ae35b1cfd2938a53bf755c6c176d79387133ed7e5f1c',
  'rolldown/dist/shared/binding-BY0qR5iS.mjs': '8c571a4e4ac9561df9d6d7370d6c0d506922b6c106fd693cb2b75b47c3ab028a',
  'rolldown/dist/shared/bindingify-input-options-XrReX_BJ.mjs': 'a778028ca12765b4604b9cb04edf80e1dc6dc096bccbc893317aa03e02ab4890',
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
/** @param {Environment} environment @returns {GraphEnvironment} */
function contextOf(environment) {
  const config = environment.config;
  const ssr = environment.name === 'ssr';
  const platform = config.build.rolldownOptions.platform ?? (ssr ? 'node' : 'browser');
  if (!['ssr', 'client'].includes(environment.name) || config.command !== 'build' || config.mode !== 'production'
      || config.isBundled !== true || config.isWorker || config.build.lib || config.build.watch || config.build.write !== true
      || config.consumer !== (ssr ? 'server' : 'client') || config.build.ssr !== ssr
      || config.base !== (ssr ? '/' : './') || platform !== (ssr ? 'node' : 'browser')
      || config.experimental.renderBuiltUrl || config.build.rolldownOptions.experimental?.devMode
      || config.build.rolldownOptions.moduleTypes !== undefined
      || !config.build.modulePreload || config.build.modulePreload.polyfill !== true) throw new Error('P14_VIRTUAL_CONTEXT');
  return { name: environment.name, consumer: config.consumer, ssr, base: config.base, platform };
}

/** @returns {VitePlugin} */
export default function sourceModuleGraph() {
  let root = '';
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
  /** @type {Map<string,VitePlugin>} Native instance returned by the authenticated Vite callback. */
  const nativePreloads = new Map();
  /** @type {Map<string,EnvironmentState>} */
  const states = new Map();
  /** @type {Set<VitePlugin>} */
  const kitPlugins = new Set();
  const nativePrototype = Object.getPrototypeOf(viteBuildImportAnalysisPlugin({
    preloadCode: '', insertPreload: false, optimizeModulePreloadRelativePaths: false, renderBuiltUrl: false, isRelativeBase: true,
  }));

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
      plugin.load = typeof plugin.load === 'function' ? wrapper : replaceHandler(plugin.load, wrapper);
    }
    if (plugin.transform && !transformWrappers.has(plugin) && plugin !== observer) {
      const original = typeof plugin.transform === 'function' ? plugin.transform : plugin.transform.handler;
      const wrapper = observeHook(original, (result, [, id], context) => {
        if (IDS.has(id)) rejectLateTransform(result, states.get(context.environment.name)?.receipts.has(id) ?? false);
      });
      transformWrappers.set(plugin, wrapper);
      plugin.transform = typeof plugin.transform === 'function' ? wrapper : replaceHandler(plugin.transform, wrapper);
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
      const wrapper = observeHook(original, (value, [environment]) => prepared(value, environment));
      applyWrappers.set(plugin, wrapper);
      plugin.applyToEnvironment = wrapper;
    }
  };
  /** @param {Environment} environment */
  const checkState = (environment) => {
    const state = stateOf(environment);
    if (environment.plugins.length !== state.plugins.length) throw new Error('P14_PLUGIN_SET_CHANGED');
    for (let index = 0; index < state.seals.length; index++) {
      const seal = state.seals[index];
      if (environment.plugins[index] !== seal.plugin || seal.plugin.load !== seal.load
          || seal.plugin.transform !== seal.transform || seal.plugin.applyToEnvironment !== seal.apply
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
    }
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
    configResolved(config) {
      root = resolve(config.root);
      plugins = config.plugins.map((plugin) => plugin.name);
      for (const [member, sha256] of Object.entries(MEMBERS)) {
        if (digest(readFileSync(resolve(root, 'node_modules', member))).sha256 !== sha256) throw new Error('P14_VIRTUAL_PRODUCER_MEMBER');
      }
      for (const [name, version] of [['@sveltejs/kit', '2.70.1'], ['vite', '8.3.1'], ['rolldown', '1.2.11'], ['@rolldown/binding-linux-x64-gnu', '1.2.11']]) {
        /** @type {unknown} */
        const metadata = JSON.parse(readFileSync(resolve(root, 'node_modules', name, 'package.json'), 'utf8'));
        if (!metadata || typeof metadata !== 'object' || !('name' in metadata) || !('version' in metadata)
            || metadata.name !== name || metadata.version !== version) throw new Error('P14_VIRTUAL_DEPENDENCY_VERSION');
      }
      for (const plugin of config.plugins) preparePlugin(plugin);
    },
    options: {
      order: 'post',
      handler(options) {
        const environment = this.environment;
        contextOf(environment);
        if (validatedInputs.has(environment.name) || options.experimental?.devMode
            || JSON.stringify(options.moduleTypes) !== JSON.stringify({ '.css': 'js' })) throw new Error('P14_VIRTUAL_BUILD_OPTIONS');
        const ownIndex = environment.plugins.indexOf(observer);
        for (let index = 0; index < environment.plugins.length; index++) {
          const plugin = environment.plugins[index];
          if (!plugin.options || plugin === observer) continue;
          const order = typeof plugin.options === 'function' ? undefined : plugin.options.order;
          if (order !== undefined && order !== null && order !== 'pre' && order !== 'post') throw new Error('P14_UNREVIEWED_OPTIONS_ORDER');
          if (order === 'post' && index > ownIndex) throw new Error('P14_LATE_OPTIONS_HOOK');
        }
        validatedInputs.add(environment.name);
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
          if (Object.getPrototypeOf(plugin) === nativePrototype) {
            if (!NATIVE_NAMES.has(plugin.name)) throw new Error('P14_UNREVIEWED_NATIVE_PLUGIN');
            if (plugin.name === 'builtin:vite-build-import-analysis' && plugin !== preload) throw new Error('P14_WRONG_NATIVE_PRODUCER');
          } else if (plugin.name.startsWith('builtin:')) throw new Error('P14_WRONG_NATIVE_PRODUCER');
        }
        if (kits !== 1 || kitPlugins.size !== 1 || !preload) throw new Error('P14_AMBIGUOUS_VIRTUAL_PRODUCER');
        if (!('_options' in preload) || !preload._options || typeof preload._options !== 'object') throw new Error('P14_PRELOAD_OPTIONS');
        const native = preload._options;
        const keys = Object.keys(native).sort().join(',');
        if (keys !== 'insertPreload,isRelativeBase,optimizeModulePreloadRelativePaths,preloadCode,renderBuiltUrl'
            || !('preloadCode' in native) || typeof native.preloadCode !== 'string'
            || !('insertPreload' in native) || native.insertPreload !== !context.ssr
            || !('optimizeModulePreloadRelativePaths' in native) || native.optimizeModulePreloadRelativePaths !== false
            || !('renderBuiltUrl' in native) || native.renderBuiltUrl !== false
            || !('isRelativeBase' in native) || native.isRelativeBase !== !context.ssr) throw new Error('P14_PRELOAD_OPTIONS');
        // The SSR helper is not emitted, but its immutable native option still
        // has the absolute-base producer derivation (2162 bytes).
        const expectedPreload = context.ssr ? { bytes: 2162, sha256: 'ab3f9fab077f29a47a120a90458f39d11f615e42e66ad92810cb3c49ba582400' }
          : EXPECTED.client[PRELOAD];
        const preloadCode = digest(native.preloadCode);
        if (preloadCode.sha256 !== expectedPreload.sha256 || preloadCode.bytes !== expectedPreload.bytes) throw new Error('P14_PRELOAD_OPTIONS');
        states.set(context.name, { context, plugins: [...environment.plugins], loads: new Map(), receipts: new Map(), preload,
          seals: environment.plugins.map((plugin) => ({ plugin, load: plugin.load, transform: plugin.transform,
            apply: plugin.applyToEnvironment, state: pluginState(plugin) })) });
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
