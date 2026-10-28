// SPDX-License-Identifier: GPL-3.0-only
// Pure first-party guards; this module never imports or executes a producer.
import { createHash } from 'node:crypto';

/** @typedef {{sha256:string,bytes:number}} Digest */
/** @typedef {{kind:'kit-load',sha256:string,bytes:number}} LoadReceipt */
const IDS = new Set(['\0rolldown/runtime.js', '\0virtual:__sveltekit/env', '\0virtual:__sveltekit/server', '\0vite/preload-helper.js']);

/** Preserve a hook's synchronous/Promise distinction and its resolved value identity.
 * The generic assertion expresses that observing a native Promise replaces only
 * that Promise, with one resolving to its original value (or rejecting a guard).
 * @template Result
 * @param {Result} result
 * @param {(value:Awaited<Result>)=>void} inspect
 * @returns {Result}
 */
export function observeResult(result, inspect) {
  if (result instanceof Promise) {
    const observed = result.then(/** @param {Awaited<Result>} value */ (value) => {
      inspect(value);
      return value;
    });
    return /** @type {Result} */ (observed);
  }
  inspect(/** @type {Awaited<Result>} */ (result));
  return result;
}

/** Preserve this, every argument, synchronous exceptions, and the result contract.
 * F captures the original complete function signature, including hook context.
 * @template {(this:never,...args:never[])=>unknown} F
 * @param {F} original
 * @param {(value:Awaited<ReturnType<F>>,args:Parameters<F>,context:ThisParameterType<F>)=>void} inspect
 * @returns {F}
 */
export function observeHook(original, inspect) {
  /** @this {ThisParameterType<F>} @param {Parameters<F>} args @returns {ReturnType<F>} */
  function observed(...args) {
    const result = /** @type {ReturnType<F>} */ (Reflect.apply(original, this, args));
    return observeResult(result, (value) => inspect(value, args, this));
  }
  return /** @type {F} */ (observed);
}

/** Clone only to replace the handler; retain all other descriptors/prototype.
 * @template {object} Hook
 * @param {Hook} hook
 * @param {unknown} handler
 * @returns {Hook}
 */
export function replaceHandler(hook, handler) {
  const descriptors = Object.getOwnPropertyDescriptors(hook);
  Object.defineProperty(descriptors, 'handler', { value: {
    value: handler, enumerable: descriptors.handler?.enumerable ?? true,
    configurable: descriptors.handler?.configurable ?? true, writable: true,
  }, enumerable: true, configurable: true, writable: true });
  return /** @type {Hook} */ (Object.create(Object.getPrototypeOf(hook), descriptors));
}

/** Actual selected JS loader output guard. Identical code from another loader
 * is refused before it can become a successful load result.
 * @template Result
 * @param {{id:string,producer:object,expectedProducer:object|null,expected:Digest|undefined,receipts:Map<string,LoadReceipt>}} binding
 * @param {Result} result
 * @returns {Result}
 */
export function captureLoad(binding, result) {
  if (result === null || result === undefined) return result;
  if (!IDS.has(binding.id)) throw new Error('UNREVIEWED_VIRTUAL_MODULE');
  if (binding.expectedProducer === null || binding.producer !== binding.expectedProducer) throw new Error('P14_WRONG_VIRTUAL_LOADER');
  const code = typeof result === 'string' ? result
    : typeof result === 'object' && 'code' in result ? result.code : undefined;
  if (typeof code !== 'string') throw new Error('P14_VIRTUAL_LOAD_CODE');
  const actual = { sha256: createHash('sha256').update(code).digest('hex'), bytes: Buffer.byteLength(code) };
  if (!binding.expected || actual.bytes !== binding.expected.bytes || actual.sha256 !== binding.expected.sha256) throw new Error('P14_VIRTUAL_SOURCE_MISMATCH');
  if (binding.receipts.has(binding.id)) throw new Error('P14_AMBIGUOUS_VIRTUAL_LOADER');
  binding.receipts.set(binding.id, { kind: 'kit-load', ...actual });
  return result;
}

/** No late string, MagicString, or metadata result can change a captured module.
 * @param {unknown} value @param {boolean} captured
 */
export function rejectLateTransform(value, captured) {
  if (captured && value !== null && value !== undefined) throw new Error('P14_LATE_VIRTUAL_TRANSFORM');
}
