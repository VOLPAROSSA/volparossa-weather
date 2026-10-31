// SPDX-License-Identifier: GPL-3.0-only
// P14-only native provenance. Expected producers derive from the unchanged
// Vite 8.3.1/Rolldown 1.2.11 sources, never from a failed run's plugin names.

/** @typedef {import('vite').Plugin<unknown> & {_options?:unknown}} Plugin */
/** @typedef {{bytes:number,sha256:string}} Digest */
/** @typedef {{value:object,prototype:object|null,descriptors:Map<PropertyKey,PropertyDescriptor>}} IdentityNode */
/** @typedef {{prototype:object|null,descriptors:Map<PropertyKey,PropertyDescriptor>,values:Map<PropertyKey,string>,identities:Map<PropertyKey,IdentityNode[]>}} Seal */
/** @typedef {{id:string,bytes:number,sha256:string}} Producer */
/** @typedef {{value:unknown,object?:Seal}} HookSeal */
/** @typedef {{name:string,prototype:object|null,hooks:Map<string,HookSeal>}} CloneSeal */

/** Complete source-derived native order for both original build environments. */
export const NATIVE_PLUGIN_ORDER = Object.freeze([
  'builtin:vite-alias', 'builtin:vite-module-preload-polyfill', 'builtin:vite-resolve',
  'builtin:vite-transform', 'builtin:vite-json', 'builtin:vite-dynamic-import-vars',
  'builtin:vite-import-glob', 'builtin:vite-build-import-analysis', 'builtin:vite-manifest',
  'builtin:vite-reporter', 'builtin:vite-load-fallback',
]);

/** Original applyToEnvironment method/callback bytes in the member-bound Vite file.
 * @type {Readonly<Record<string,Producer>>} */
const PRODUCERS = Object.freeze({
  alias: { id: 'builtin:vite-alias', bytes: 323, sha256: '9be2df664e95147e3884648a1f3e152f01c46a8d82fadb0327aacca2071e85e2' },
  'vite:modulepreload-polyfill': { id: 'builtin:vite-module-preload-polyfill', bytes: 186, sha256: 'acb56766656716383a2b54e02146b82be6ef68659942ea0dd14dd518628e4875' },
  'vite:resolve-builtin': { id: 'builtin:vite-resolve', bytes: 103, sha256: '8028fce923826504508c554b7219a3174b7c6a543d4fb892839bd709bfda7892' },
  'vite:oxc': { id: 'builtin:vite-transform', bytes: 714, sha256: '9f3b0a4838e11c38bd2cc8e181536a414f985997b8e6fcd17b2c8cfb543c2386' },
  'vite:dynamic-import-vars': { id: 'builtin:vite-dynamic-import-vars', bytes: 411, sha256: '227c58ea194a082b3f03314b39b2b6c218a80c534ee855510adbb85bfbb3f521' },
  'vite:import-glob': { id: 'builtin:vite-import-glob', bytes: 301, sha256: '9569c98bbf185719188aacc8282cfead29981e4081100ad7b26d4a0ae545aa4a' },
  'native:import-analysis-build': { id: 'builtin:vite-build-import-analysis', bytes: 319, sha256: 'e5cb966ffeb7afe04daa03dfc138efe233ae02dec2060ca731072cb5bc35b376' },
  'native:manifest': { id: 'builtin:vite-manifest', bytes: 2731, sha256: '033d2c83675b1300ccbc918ca07ae6a97db60d1f460a9aedabaa9c892414ed10' },
  'native:reporter': { id: 'builtin:vite-reporter', bytes: 631, sha256: '36746a61881d5251859d2c592146459c43f93138708262a888e7254fbad2bfc4' },
});
const DISABLED_RUNTIME = 'builtin:oxc-runtime';
const CLASS_SOURCE = { bytes: 175, sha256: 'c21074a9c48e2cd73b7dd8bb41390b3c69afa89af987a05d4cb8cd97aed169fd' };
const CALLABLE_SOURCE = { bytes: 335, sha256: 'c840a97efc426bf192c8c1325ed61d87df768202d5de65ab43287889b69da46b' };
const DISABLED_SOURCE = { bytes: 80, sha256: 'ae702863cd45e942b89b489bd64bd78085dc89d89e4e5524d9eb73f35280ab45' };
const CALLABLE_KEYS = new Set(['getOrder', 'resolveId', 'load', 'transform', 'watchChange']);
// Exact ROLLUP_HOOKS in the bound Vite member634-659, plus its environment hook.
const CLONE_HOOKS = ['options', 'buildStart', 'buildEnd', 'renderStart', 'renderError', 'renderChunk',
  'writeBundle', 'generateBundle', 'banner', 'footer', 'augmentChunkHash', 'outputOptions',
  'resolveFileUrl', 'intro', 'outro', 'closeBundle', 'closeWatcher', 'load', 'moduleParsed',
  'watchChange', 'resolveDynamicImport', 'resolveId', 'transform', 'onLog', 'applyToEnvironment', '_parallel'];
/** Vite's original clone bridges in injectEnvironmentToHooks34620-34709.
 * @type {Readonly<Record<string,Digest>>} */
const CLONE_BRIDGES = Object.freeze({
  resolveId: { bytes: 164, sha256: 'ff289755ce31f36756e2b0b19286339848677398c9f2a3a868b24601735635cc' },
  load: { bytes: 144, sha256: '7c54a44a40b1b02d9fdd0c3768169e41bb28d8255bb4e7ce3887f4085255435c' },
  transform: { bytes: 168, sha256: '0c1d95bac0242e4203fd14d8f09a54de3e2ce053374a33a2dfbf42a87ee43d61' },
  watchChange: { bytes: 463, sha256: '856f666b8279dfb5b55b58b8fca41cad3220e34f015346304edbc227d5d39f55' },
});

/** Only fixed error tokens are emitted; no input values, paths or source text.
 * @param {boolean} condition @param {string} code */
function requireNative(condition, code) {
  if (!condition) throw new Error('P14_NATIVE:' + code);
}

/** This registry must first capture Vite's original resolved collection before
 * any original user configResolved handler runs. The caller authenticates the
 * exact package/member/native binary inputs before configuration() is called.
 * First-party wrapper installation is the sole permitted seal update.
 * @param {object} prototype
 * @param {(value:string)=>Digest} digest
 * @param {(value:unknown)=>unknown} snapshot
 * @param {(value:unknown)=>boolean} isProxy */
export function createNativePluginGuard(prototype, digest, snapshot, isProxy) {
  requireNative(typeof isProxy === 'function' && !isProxy(prototype), 'proxy');
  /** Plugin names are original own data, never getter/prototype authority.
   * @param {unknown} value @returns {value is Plugin} */
  const safePlugin = (value) => {
    if (value === null || typeof value !== 'object' || isProxy(value) || isProxy(Object.getPrototypeOf(value))) return false;
    const descriptor = Object.getOwnPropertyDescriptor(value, 'name');
    return descriptor !== undefined && 'value' in descriptor && typeof descriptor.value === 'string' && descriptor.value.length > 0;
  };
  /** Vite constructs dense ordinary arrays. Reject accessors, exotic iterators
   * and proxy-backed lists before reading any plugin entry.
   * @param {unknown} value @returns {value is Plugin[]} */
  const safePluginArray = (value) => {
    if (isProxy(value) || !Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype
        || value.length > 512 || Reflect.ownKeys(value).length !== value.length + 1) return false;
    for (let index = 0; index < value.length; index++) {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (!descriptor || !('value' in descriptor) || !safePlugin(descriptor.value)) return false;
    }
    return true;
  };
  /** @param {unknown} value */
  const serialized = (value) => JSON.stringify(snapshot(value)) ?? 'undefined';
  /** @param {unknown} fn @param {Digest} expected */
  const exactFunction = (fn, expected) => {
    if (typeof fn !== 'function' || isProxy(fn)) return false;
    const actual = digest(Function.prototype.toString.call(fn));
    return actual.bytes === expected.bytes && actual.sha256 === expected.sha256;
  };
  const constructor = Object.getOwnPropertyDescriptor(prototype, 'constructor');
  requireNative(constructor !== undefined && 'value' in constructor && typeof constructor.value === 'function'
    && !isProxy(constructor.value), 'prototype-source');
  /** @type {unknown} */
  const classValue = constructor?.value;
  if (typeof classValue !== 'function') throw new Error('P14_NATIVE:prototype-source');
  const classLength = Object.getOwnPropertyDescriptor(classValue, 'length');
  const className = Object.getOwnPropertyDescriptor(classValue, 'name');
  const classPrototype = Object.getOwnPropertyDescriptor(classValue, 'prototype');
  const frozenClass = Object.isFrozen(prototype) && Object.isFrozen(classValue);
  requireNative(Object.getPrototypeOf(classValue) === Function.prototype && Reflect.ownKeys(classValue).length === 3
    && classLength !== undefined && 'value' in classLength && classLength.value === 2
    && classLength.writable === false && classLength.enumerable === false
    && classLength.configurable === !frozenClass
    && className !== undefined && 'value' in className && className.value === 'BuiltinPlugin'
    && className.writable === false && className.enumerable === false
    && className.configurable === !frozenClass
    && classPrototype !== undefined && 'value' in classPrototype && classPrototype.value === prototype
    && classPrototype.writable === false && classPrototype.enumerable === false && classPrototype.configurable === false,
  'constructor-shape');
  requireNative(Reflect.ownKeys(prototype).length === 1 && typeof constructor?.value === 'function'
    && constructor.enumerable === false
    && ((constructor.writable === true && constructor.configurable === true)
      || (constructor.writable === false && constructor.configurable === false && frozenClass))
    && Object.getPrototypeOf(prototype) === Object.prototype
    && exactFunction(constructor.value, CLASS_SOURCE), 'prototype-source');

  /** Bound only explicit object/function properties, never closure state or
   * native Map/private caches. Reference equality catches a new callback with
   * identical toString bytes, and descriptors are read without invoking getters.
   * @param {unknown} value @returns {IdentityNode[]} */
  const identityGraph = (value) => {
    /** @type {IdentityNode[]} */
    const nodes = [];
    /** @type {Set<object>} */
    const seen = new Set();
    /** @param {unknown} item @param {number} depth */
    const visit = (item, depth) => {
      if (item === null || (typeof item !== 'object' && typeof item !== 'function') || seen.has(item)) return;
      requireNative(!isProxy(item) && !isProxy(Object.getPrototypeOf(item)), 'proxy');
      requireNative(depth <= 12 && nodes.length < 4096, 'identity-bound');
      seen.add(item);
      const keys = Reflect.ownKeys(item);
      requireNative(keys.length <= 4096, 'identity-keys-bound');
      /** @type {Map<PropertyKey,PropertyDescriptor>} */
      const descriptors = new Map();
      const node = { value: item, prototype: Object.getPrototypeOf(item), descriptors };
      nodes.push(node);
      for (const key of keys) {
        const descriptor = Object.getOwnPropertyDescriptor(item, key);
        requireNative(descriptor !== undefined, 'identity-descriptor');
        if (descriptor) {
          requireNative(!descriptor.get && !descriptor.set, 'identity-accessor');
          descriptors.set(key, descriptor);
          if ('value' in descriptor) visit(descriptor.value, depth + 1);
        }
      }
    };
    visit(value, 0);
    return nodes;
  };
  /** @param {IdentityNode[]} nodes */
  const checkIdentityGraph = (nodes) => {
    for (const node of nodes) {
      requireNative(!isProxy(node.value), 'proxy');
      const keys = Reflect.ownKeys(node.value);
      requireNative(Object.getPrototypeOf(node.value) === node.prototype && keys.length === node.descriptors.size, 'identity-prototype-or-keys');
      for (const key of keys) {
        const expected = node.descriptors.get(key);
        const actual = Object.getOwnPropertyDescriptor(node.value, key);
        requireNative(expected !== undefined && actual !== undefined, 'identity-key');
        if (expected && actual) requireNative(expected.get === actual.get && expected.set === actual.set
          && expected.writable === actual.writable && expected.configurable === actual.configurable
          && expected.enumerable === actual.enumerable && Object.is(expected.value, actual.value), 'identity-value');
      }
    }
  };

  /** @param {object} value @returns {Seal} */
  const seal = (value) => {
    requireNative(!isProxy(value) && !isProxy(Object.getPrototypeOf(value)), 'proxy');
    /** @type {Map<PropertyKey,PropertyDescriptor>} */
    const descriptors = new Map();
    /** @type {Map<PropertyKey,string>} */
    const values = new Map();
    /** @type {Map<PropertyKey,IdentityNode[]>} */
    const identities = new Map();
    for (const key of Reflect.ownKeys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      requireNative(descriptor !== undefined, 'descriptor');
      if (descriptor) {
        requireNative(!descriptor.get && !descriptor.set, 'accessor');
        descriptors.set(key, descriptor);
        identities.set(key, identityGraph(descriptor.value));
        values.set(key, serialized(descriptor.value));
      }
    }
    return { prototype: Object.getPrototypeOf(value), descriptors, values, identities };
  };
  /** @param {object} value @param {Seal} expected @param {PropertyKey} [except] */
  const checkSeal = (value, expected, except) => {
    requireNative(!isProxy(value), 'proxy');
    const keys = Reflect.ownKeys(value);
    requireNative(Object.getPrototypeOf(value) === expected.prototype && keys.length === expected.descriptors.size, 'seal-prototype-or-keys');
    for (const key of keys) {
      const before = expected.descriptors.get(key);
      const now = Object.getOwnPropertyDescriptor(value, key);
      requireNative(before !== undefined && now !== undefined, 'seal-key');
      if (before && now) {
        requireNative(now.get === before.get && now.set === before.set && now.writable === before.writable
          && now.enumerable === before.enumerable && now.configurable === before.configurable, 'seal-descriptor');
        if (key !== except) {
          checkIdentityGraph(expected.identities.get(key) ?? []);
          requireNative(now.value === before.value && serialized(now.value) === expected.values.get(key), 'seal-value');
        }
      }
    }
  };
  let prototypeSeal = seal(prototype);
  const checkPrototype = () => checkSeal(prototype, prototypeSeal);
  /** @type {Map<Plugin,Seal>} */
  const records = new Map();
  /** @type {Set<Plugin>} */
  const users = new Set();
  let usersSet = false;
  /** @type {Plugin[]|undefined} */
  let configured;
  /** @type {Plugin[]} */
  let configurationEntries = [];
  /** @type {Map<PropertyKey,PropertyDescriptor>} */
  const configurationDescriptors = new Map();
  /** @type {Map<Plugin,Producer>} */
  const producers = new Map();
  /** @type {Plugin|undefined} */
  let disabled;
  /** @type {Map<string,Plugin>} */
  const direct = new Map();
  /** @type {Map<string,Map<string,Plugin>>} */
  const selected = new Map();
  /** @type {Map<string,{array:Plugin[],arrayDescriptors:Map<PropertyKey,PropertyDescriptor>,plugins:Plugin[],native:Map<Plugin,Seal>,clones:Map<Plugin,CloneSeal>}>} */
  const inputs = new Map();

  /** @param {Plugin} plugin */
  const native = (plugin) => { requireNative(!isProxy(plugin), 'proxy'); return Object.getPrototypeOf(plugin) === prototype; };
  const checkRecords = () => {
    checkPrototype();
    for (const [plugin, expected] of records) checkSeal(plugin, expected);
  };
  /** @param {{array:Plugin[],arrayDescriptors:Map<PropertyKey,PropertyDescriptor>,plugins:Plugin[],native:Map<Plugin,Seal>,clones:Map<Plugin,CloneSeal>}} captured */
  const checkInputs = (captured) => {
    requireNative(!isProxy(captured.array), 'proxy');
    requireNative(captured.array.length === captured.plugins.length, 'input-count');
    requireNative(Reflect.ownKeys(captured.array).length === captured.arrayDescriptors.size, 'input-array-keys');
    for (const [key, before] of captured.arrayDescriptors) {
      const now = Object.getOwnPropertyDescriptor(captured.array, key);
      requireNative(now !== undefined && 'value' in now && now.value === before.value
        && now.writable === before.writable && now.enumerable === before.enumerable
        && now.configurable === before.configurable, 'input-array-descriptor');
    }
    for (let index = 0; index < captured.plugins.length; index++) requireNative(captured.array[index] === captured.plugins[index], 'input-identity');
    for (const [plugin, expected] of captured.native) checkSeal(plugin, expected);
    for (const [plugin, expected] of captured.clones) {
      const name = Object.getOwnPropertyDescriptor(plugin, 'name');
      requireNative(name !== undefined && 'value' in name && name.value === expected.name
        && Object.getPrototypeOf(plugin) === expected.prototype, 'input-clone-continuity');
      for (const key of CLONE_HOOKS) {
        const hook = expected.hooks.get(key);
        requireNative(Object.hasOwn(plugin, key) === (hook !== undefined), 'input-hook-key');
        if (hook) {
          const descriptor = Object.getOwnPropertyDescriptor(plugin, key);
          requireNative(descriptor !== undefined && 'value' in descriptor && !descriptor.get && !descriptor.set, 'input-hook-accessor');
          const value = descriptor?.value;
          requireNative(value === hook.value, 'input-hook-identity');
          if (hook.object && value !== null && typeof value === 'object') checkSeal(value, hook.object);
        }
      }
    }
  };
  /** Freeze only the explicit data objects/arrays carried to native dispatch.
   * Function closures and Map/Set/native private cache state stay untouched.
   * All descriptor/proxy checks precede freezing; this operation never awaits.
   * @param {unknown} value @param {Set<object>} seen @param {number} [depth] */
  const freezeData = (value, seen, depth = 0) => {
    if (value === null || typeof value !== 'object' || seen.has(value)) return;
    requireNative(!isProxy(value) && depth <= 12 && seen.size < 4096, 'freeze-bound');
    const parent = Object.getPrototypeOf(value);
    if (!Array.isArray(value) && parent !== Object.prototype && parent !== null) return;
    seen.add(value);
    for (const key of Reflect.ownKeys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      requireNative(descriptor !== undefined && 'value' in descriptor && !descriptor.get && !descriptor.set, 'freeze-accessor');
      if (descriptor) freezeData(descriptor.value, seen, depth + 1);
    }
    Object.freeze(value);
  };
  /** @param {Plugin[]} array @returns {Map<PropertyKey,PropertyDescriptor>} */
  const arrayDescriptors = (array) => {
    /** @type {Map<PropertyKey,PropertyDescriptor>} */
    const values = new Map();
    for (const key of Reflect.ownKeys(array)) {
      const descriptor = Object.getOwnPropertyDescriptor(array, key);
      requireNative(descriptor !== undefined && 'value' in descriptor, 'input-array-accessor');
      if (descriptor) values.set(key, descriptor);
    }
    return values;
  };
  /** Validate eager native constructor fields before their own snapshots.
   * Callable methods are the exact fixed bridge from the bound native loader.
   * Their enumerability is not guessed; the original constructed interface is
   * captured before untrusted hooks and remains immutable afterwards.
   * @param {Plugin} plugin */
  const register = (plugin) => {
    requireNative(native(plugin) && !records.has(plugin), 'native-instance');
    for (const key of ['name', '_options', 'enforce']) {
      const field = Object.getOwnPropertyDescriptor(plugin, key);
      requireNative(field !== undefined && 'value' in field && field.writable === true
        && field.enumerable === true && field.configurable === true, 'native-base-field');
    }
    requireNative(plugin.enforce === undefined, 'native-enforce');
    for (const key of Reflect.ownKeys(plugin)) {
      if (key === 'name' || key === '_options' || key === 'enforce') continue;
      const descriptor = Object.getOwnPropertyDescriptor(plugin, key);
      requireNative(descriptor !== undefined && 'value' in descriptor && !descriptor.get && !descriptor.set, 'native-accessor');
      if (key === 'perEnvironmentWatchChangeDuringDev') {
        requireNative(plugin.name === 'builtin:vite-resolve'
          && descriptor?.value === true, 'native-resolver-watch');
        continue;
      }
      const value = descriptor?.value;
      requireNative(typeof key === 'string' && CALLABLE_KEYS.has(key)
        && typeof value === 'function' && exactFunction(value, CALLABLE_SOURCE), 'native-callable-source');
    }
    records.set(plugin, seal(plugin));
  };

  return {
    /** @param {Plugin[]} plugins */
    setUsers(plugins) {
      requireNative(!usersSet && !configured, 'users-repeated');
      requireNative(safePluginArray(plugins), 'users-list');
      checkPrototype();
      for (const plugin of plugins) {
        requireNative(safePlugin(plugin) && !native(plugin) && !plugin.name.startsWith('builtin:'), 'user-native');
        requireNative(!users.has(plugin), 'user-duplicate');
        users.add(plugin);
      }
      usersSet = true;
    },
    /** @param {Plugin[]} plugins */
    configuration(plugins) {
      requireNative(usersSet && safePluginArray(plugins), 'configuration-before-users');
      checkRecords();
      if (configured) {
        requireNative(plugins === configured && plugins.length === configurationEntries.length, 'configuration-list');
        requireNative(Reflect.ownKeys(plugins).length === configurationDescriptors.size, 'configuration-array-keys');
        for (const [key, expected] of configurationDescriptors) {
          const actual = Object.getOwnPropertyDescriptor(plugins, key);
          requireNative(actual !== undefined && 'value' in actual && actual.value === expected.value
            && actual.writable === expected.writable && actual.enumerable === expected.enumerable
            && actual.configurable === expected.configurable, 'configuration-array-descriptor');
        }
        for (let index = 0; index < plugins.length; index++) requireNative(plugins[index] === configurationEntries[index], 'configuration-identity');
        return;
      }
      const expectedDirect = ['builtin:vite-json', 'builtin:vite-load-fallback'];
      const foundDirect = plugins.filter(native);
      requireNative(foundDirect.length === expectedDirect.length, 'direct-count');
      for (let index = 0; index < foundDirect.length; index++) {
        const plugin = foundDirect[index];
        requireNative(!users.has(plugin) && plugin.name === expectedDirect[index], 'direct-producer');
        register(plugin);
        if (plugin.name === 'builtin:vite-json') requireNative(serialized(plugin._options) === serialized({ namedExports: true, stringify: 'auto', minify: true }), 'json-options');
        else requireNative(plugin._options === undefined, 'fallback-options');
        direct.set(plugin.name, plugin);
      }
      for (const plugin of plugins) {
        if (native(plugin)) continue;
        const expected = Object.hasOwn(PRODUCERS, plugin.name) ? PRODUCERS[plugin.name] : undefined;
        if (expected) {
          const apply = Object.getOwnPropertyDescriptor(plugin, 'applyToEnvironment');
          requireNative(!users.has(plugin) && ![...producers.values()].some((value) => value.id === expected.id)
            && apply !== undefined && 'value' in apply && typeof apply.value === 'function'
            && exactFunction(apply.value, expected), 'factory-source');
          producers.set(plugin, expected);
          records.set(plugin, seal(plugin));
        } else if (plugin.name.startsWith('builtin:')) {
          const apply = Object.getOwnPropertyDescriptor(plugin, 'applyToEnvironment');
          requireNative(plugin.name === DISABLED_RUNTIME && !disabled && !users.has(plugin)
            && apply !== undefined && 'value' in apply && typeof apply.value === 'function'
            && exactFunction(apply.value, DISABLED_SOURCE), 'disabled-source');
          disabled = plugin;
          records.set(plugin, seal(plugin));
        }
      }
      requireNative(producers.size === Object.keys(PRODUCERS).length && disabled !== undefined, 'factory-count');
      configured = plugins;
      configurationEntries = [...plugins];
      requireNative(Reflect.ownKeys(plugins).length === plugins.length + 1, 'configuration-array-shape');
      for (const key of Reflect.ownKeys(plugins)) {
        const descriptor = Object.getOwnPropertyDescriptor(plugins, key);
        requireNative(descriptor !== undefined && 'value' in descriptor, 'configuration-array-accessor');
        if (descriptor) configurationDescriptors.set(key, descriptor);
      }
    },
    /** The caller installs only its known wrapper, then records that exact
     * transition. No untrusted callback receives this seal-update capability.
     * @param {Plugin} plugin @param {string} key @param {unknown} oldValue @param {unknown} newValue */
    controlledHook(plugin, key, oldValue, newValue) {
      const expected = records.get(plugin);
      if (!expected) return;
      requireNative(['load', 'transform', 'applyToEnvironment', 'options', 'outputOptions'].includes(key), 'controlled-key');
      checkPrototype();
      checkSeal(plugin, expected, key);
      const before = expected.descriptors.get(key);
      const now = Object.getOwnPropertyDescriptor(plugin, key);
      requireNative(before !== undefined && before.value === oldValue && now !== undefined && now.value === newValue, 'controlled-transition');
      records.set(plugin, seal(plugin));
    },
    /** @param {Plugin} producer @param {string} environment @param {unknown} result */
    captureApply(producer, environment, result) {
      requireNative(configured !== undefined && (environment === 'ssr' || environment === 'client'), 'apply-context');
      checkRecords();
      if (producer === disabled) {
        requireNative(result === false, 'disabled-selected');
        return;
      }
      const expected = producers.get(producer);
      /** @type {Plugin[]} */
      const found = [];
      /** @param {unknown} value */
      const visit = (value) => {
        requireNative(!isProxy(value), 'proxy');
        if (Array.isArray(value)) {
          requireNative(value.length <= 64 && Reflect.ownKeys(value).length === value.length + 1, 'apply-array');
          for (let index = 0; index < value.length; index++) {
            const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
            requireNative(descriptor !== undefined && 'value' in descriptor, 'apply-array-accessor');
            if (descriptor) visit(descriptor.value);
          }
          return;
        }
        if (!safePlugin(value)) return;
        if (native(value) || value.name.startsWith('builtin:')) found.push(value);
      };
      visit(result);
      if (!expected) {
        requireNative(found.length === 0, 'foreign-producer');
        return;
      }
      requireNative(found.length === 1 && found[0].name === expected.id && native(found[0]), 'apply-result');
      if (expected.id === 'builtin:vite-manifest') {
        requireNative(Array.isArray(result) && result.length === 3 && result[1] === found[0]
          && safePlugin(result[0]) && result[0].name === 'native:manifest-envs'
          && safePlugin(result[2]) && result[2].name === 'native:manifest-compatible', 'manifest-result');
      } else requireNative(result === found[0], 'apply-shape');
      let values = selected.get(environment);
      if (!values) { values = new Map(); selected.set(environment, values); }
      requireNative(!values.has(expected.id), 'apply-duplicate');
      register(found[0]);
      values.set(expected.id, found[0]);
    },
    /** @param {string} environment @param {Plugin[]} plugins */
    environment(environment, plugins) {
      requireNative((environment === 'ssr' || environment === 'client') && safePluginArray(plugins), 'environment');
      checkRecords();
      const nativePlugins = plugins.filter((plugin) => native(plugin) || plugin.name.startsWith('builtin:'));
      requireNative(nativePlugins.length === NATIVE_PLUGIN_ORDER.length, 'environment-count');
      const values = selected.get(environment);
      for (let index = 0; index < NATIVE_PLUGIN_ORDER.length; index++) {
        const id = NATIVE_PLUGIN_ORDER[index];
        const plugin = nativePlugins[index];
        requireNative(native(plugin) && plugin.name === id && plugin === (direct.get(id) ?? values?.get(id)), 'environment-producer');
      }
      const captured = inputs.get(environment);
      if (captured) checkInputs(captured);
    },
    /** This method runs before every original options hook and on its result.
     * The first call validates Vite's source-derived clone relation; later calls
     * require those exact captured objects, preventing same-name replacements.
     * @param {string} environment @param {Plugin[]} environmentPlugins @param {unknown} pluginOptions */
    inputs(environment, environmentPlugins, pluginOptions) {
      this.environment(environment, environmentPlugins);
      requireNative(safePluginArray(pluginOptions) && pluginOptions.length === environmentPlugins.length, 'input-list');
      if (!safePluginArray(pluginOptions)) return;
      requireNative(Reflect.ownKeys(pluginOptions).length === pluginOptions.length + 1, 'input-array-shape');
      const previous = inputs.get(environment);
      if (previous) {
        requireNative(pluginOptions === previous.array, 'input-array');
        checkInputs(previous);
        return;
      }
      /** @type {Map<Plugin,Seal>} */
      const nativeClones = new Map();
      /** @type {Map<Plugin,CloneSeal>} */
      const cloneSeals = new Map();
      /** @type {Plugin[]} */
      const clones = [];
      /** @type {Map<PropertyKey,PropertyDescriptor>} */
      const arrayDescriptors = new Map();
      for (const key of Reflect.ownKeys(pluginOptions)) {
        const descriptor = Object.getOwnPropertyDescriptor(pluginOptions, key);
        requireNative(descriptor !== undefined && 'value' in descriptor, 'input-array-accessor');
        if (descriptor) arrayDescriptors.set(key, descriptor);
      }
      for (let index = 0; index < pluginOptions.length; index++) {
        const clone = pluginOptions[index];
        const original = environmentPlugins[index];
        requireNative(safePlugin(clone) && clone !== original && clone.name === original.name
          && Object.getPrototypeOf(clone) === Object.getPrototypeOf(original), 'input-clone');
        if (!safePlugin(clone)) continue;
        clones.push(clone);
        const parallel = Object.getOwnPropertyDescriptor(clone, '_parallel');
        requireNative(parallel === undefined || ('value' in parallel && parallel.value === undefined), 'input-parallel');
        /** @type {Map<string,HookSeal>} */
        const hooks = new Map();
        for (const key of CLONE_HOOKS) {
          requireNative(Object.hasOwn(clone, key) === Object.hasOwn(original, key), 'input-hook-source-key');
          if (Object.hasOwn(clone, key)) {
            const descriptor = Object.getOwnPropertyDescriptor(clone, key);
            requireNative(descriptor !== undefined && 'value' in descriptor && !descriptor.get && !descriptor.set, 'input-hook-accessor');
            const value = descriptor?.value;
            hooks.set(key, { value, ...(value !== null && typeof value === 'object' ? { object: seal(value) } : {}) });
          }
        }
        cloneSeals.set(clone, { name: clone.name, prototype: Object.getPrototypeOf(clone), hooks });
        if (!native(original)) continue;
        requireNative(clone._options === original._options, 'input-options-reference');
        const keys = Reflect.ownKeys(original);
        requireNative(Reflect.ownKeys(clone).length === keys.length, 'input-native-keys');
        for (const key of keys) {
          const before = Object.getOwnPropertyDescriptor(original, key);
          const after = Object.getOwnPropertyDescriptor(clone, key);
          // Object.assign creates fresh ordinary writable/enumerable/configurable
          // properties even when a preceding environment froze the originals.
          requireNative(before !== undefined && after !== undefined && before.enumerable === true
            && after.writable === true && after.enumerable === true && after.configurable === true
            && !after.get && !after.set, 'input-descriptor');
          if (!before || !after) continue;
          const bridge = typeof key === 'string' ? CLONE_BRIDGES[key] : undefined;
          if (bridge && typeof before.value === 'function') requireNative(typeof after.value === 'function'
            && exactFunction(after.value, bridge), 'input-bridge-source');
          else requireNative(after.value === before.value, 'input-field');
        }
        nativeClones.set(clone, seal(clone));
      }
      inputs.set(environment, { array: pluginOptions, arrayDescriptors, plugins: clones, native: nativeClones, clones: cloneSeals });
    },
    /** Fixed original output has no output plugins. This runs before and after
     * original outputOptions hooks, and on configured output at input options.
     * @param {unknown} outputOptions @returns {void} */
    output(outputOptions) {
      if (outputOptions === undefined) return;
      requireNative(!isProxy(outputOptions), 'proxy');
      if (Array.isArray(outputOptions)) {
        requireNative(outputOptions.length <= 64 && Reflect.ownKeys(outputOptions).length === outputOptions.length + 1, 'output-array');
        for (let index = 0; index < outputOptions.length; index++) {
          const descriptor = Object.getOwnPropertyDescriptor(outputOptions, String(index));
          requireNative(descriptor !== undefined && 'value' in descriptor, 'output-array-accessor');
          if (descriptor) this.output(descriptor.value);
        }
        return;
      }
      requireNative(outputOptions !== null && typeof outputOptions === 'object', 'output-shape');
      if (outputOptions !== null && typeof outputOptions === 'object') {
        const descriptor = Object.getOwnPropertyDescriptor(outputOptions, 'plugins');
        if (!descriptor) {
          let ancestor = Object.getPrototypeOf(outputOptions);
          let depth = 0;
          while (ancestor !== null) {
            requireNative(depth++ < 12 && !isProxy(ancestor), 'output-prototype');
            requireNative(Object.getOwnPropertyDescriptor(ancestor, 'plugins') === undefined, 'output-inherited-plugins');
            ancestor = Object.getPrototypeOf(ancestor);
          }
          return;
        }
        requireNative('value' in descriptor && !descriptor.get && !descriptor.set, 'output-plugin-accessor');
        const plugins = descriptor.value;
        requireNative(!isProxy(plugins) && (plugins === undefined || (Array.isArray(plugins)
          && plugins.length === 0 && Reflect.ownKeys(plugins).length === 1)), 'output-plugins');
      }
    },
    /** Last own post-options barrier. The original normalizer makes fresh
     * arrays before binding and only reads native name/_options. Restrict that
     * exact dispatch data, then record only these deliberate freeze changes.
     * Actual JS-clone hook/name/parallel authority fields become read-only, while
     * their API/cache fields and all original user plugins stay mutable.
     * @param {string} environment @param {Plugin[]} environmentPlugins @param {unknown} pluginOptions */
    finalizeInputs(environment, environmentPlugins, pluginOptions) {
      this.inputs(environment, environmentPlugins, pluginOptions);
      checkRecords();
      for (const captured of inputs.values()) checkInputs(captured);
      const selectedInput = inputs.get(environment);
      requireNative(selectedInput !== undefined, 'finalize-input');
      if (!selectedInput) return;
      /** @type {Set<object>} */
      const seen = new Set();
      for (const plugin of records.keys()) {
        if (!native(plugin)) continue;
        freezeData(plugin._options, seen);
        Object.freeze(plugin);
      }
      for (const captured of inputs.values()) {
        for (const plugin of captured.native.keys()) {
          freezeData(plugin._options, seen);
          Object.freeze(plugin);
        }
      }
      for (const captured of inputs.values()) {
        for (const [plugin, expected] of captured.clones) {
          if (native(plugin)) continue;
          const name = Object.getOwnPropertyDescriptor(plugin, 'name');
          requireNative(name !== undefined && 'value' in name && name.value === expected.name, 'finalize-clone-name');
          Object.defineProperty(plugin, 'name', { ...name, writable: false, configurable: false });
          for (const key of CLONE_HOOKS) {
            const descriptor = Object.getOwnPropertyDescriptor(plugin, key);
            const value = descriptor?.value;
            if (descriptor) requireNative('value' in descriptor && !descriptor.get && !descriptor.set, 'finalize-clone-accessor');
            if (key === '_parallel') requireNative(value === undefined, 'input-parallel');
            freezeData(value, seen);
            Object.defineProperty(plugin, key, { ...(descriptor ?? { enumerable: true }), value,
              writable: false, configurable: false });
          }
        }
      }
      Object.freeze(selectedInput.array);
      // Constructor immutability also protects instanceof dispatch from a late
      // Symbol.hasInstance override. Ordinary _options callbacks are not frozen.
      if (constructor) Object.freeze(constructor.value);
      Object.freeze(prototype);
      prototypeSeal = seal(prototype);
      for (const plugin of records.keys()) if (native(plugin)) records.set(plugin, seal(plugin));
      for (const captured of inputs.values()) {
        for (const plugin of captured.native.keys()) captured.native.set(plugin, seal(plugin));
        for (const [plugin, expected] of captured.clones) {
          if (native(plugin)) continue;
          /** @type {Map<string,HookSeal>} */
          const hooks = new Map();
          for (const key of CLONE_HOOKS) {
            const descriptor = Object.getOwnPropertyDescriptor(plugin, key);
            requireNative(descriptor !== undefined && 'value' in descriptor, 'finalize-clone-field');
            const value = descriptor?.value;
            hooks.set(key, { value, ...(value !== null && typeof value === 'object' ? { object: seal(value) } : {}) });
          }
          captured.clones.set(plugin, { ...expected, hooks });
        }
        captured.arrayDescriptors = arrayDescriptors(captured.array);
      }
      this.environment(environment, environmentPlugins);
    },
    /** Last own post-outputOptions barrier. Protect only the plugin-authority
     * field and its empty array, preserving the other normalizer output fields.
     * @param {unknown} outputOptions @returns {void} */
    finalizeOutput(outputOptions) {
      this.output(outputOptions);
      if (outputOptions === undefined) return;
      if (Array.isArray(outputOptions)) {
        for (let index = 0; index < outputOptions.length; index++) this.finalizeOutput(outputOptions[index]);
        return;
      }
      if (outputOptions === null || typeof outputOptions !== 'object') return;
      const descriptor = Object.getOwnPropertyDescriptor(outputOptions, 'plugins');
      const value = descriptor?.value;
      if (Array.isArray(value)) Object.freeze(value);
      if (descriptor) {
        Object.defineProperty(outputOptions, 'plugins', { ...descriptor, value, writable: false, configurable: false });
      } else {
        requireNative(Object.isExtensible(outputOptions), 'output-not-extensible');
        Object.defineProperty(outputOptions, 'plugins', { value: undefined, writable: false, configurable: false, enumerable: true });
      }
      this.output(outputOptions);
    },
  };
}
