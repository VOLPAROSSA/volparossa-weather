// SPDX-License-Identifier: GPL-3.0-only
// Executes only these pure first-party guards, inside the existing P13 Boundary.
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler } from './virtual-module-guards.mjs';
import { validateVirtualContext, preloadContextOptions } from './virtual-module-context.mjs';
import { runVirtualContextTests } from './test-virtual-module-context.mjs';
import { runObserverLifecycleTests } from './test-observer-lifecycle.mjs';

const contextTests = runVirtualContextTests(validateVirtualContext, preloadContextOptions);
const lifecycleTests = runObserverLifecycleTests(readFileSync(new URL('./volparossa-source-module-graph.mjs', import.meta.url), 'utf8'),
  { captureLoad, observeHook, observeResult, rejectLateTransform, replaceHandler, validateVirtualContext, preloadContextOptions });

const id = '\0virtual:__sveltekit/env';
const code = 'export const value = 1;\n';
const expected = { bytes: 24, sha256: '5d8f65d2774e206bc9f7a7a4ad39ca2dc563b5c31e46ab57ef4874961237ce29' };
const producer = {};
const otherProducer = {};
/** @type {Map<string,import('./virtual-module-guards.mjs').LoadReceipt>} */
const receipts = new Map();
const binding = { id, producer, expectedProducer: producer, expected, receipts };
const output = { code, map: null };
const context = { identity: {} };
const options = { ssr: true };
const extra = {};
let inspected = 0;

/** @this {typeof context} @param {string} receivedId @param {typeof options} receivedOptions @param {object} receivedExtra */
function original(receivedId, receivedOptions, receivedExtra) {
  assert.equal(this, context);
  assert.equal(receivedId, id);
  assert.equal(receivedOptions, options);
  assert.equal(receivedExtra, extra);
  return output;
}
const observed = observeHook(original, (value, args, receiver) => {
  assert.equal(receiver, context);
  assert.equal(args[0], id);
  assert.equal(args[1], options);
  assert.equal(args[2], extra);
  captureLoad(binding, value);
  inspected++;
});
assert.equal(observed.call(context, id, options, extra), output);
assert.equal(inspected, 1);
assert.equal(receipts.get(id)?.sha256, expected.sha256);
assert.throws(() => observed.call(context, id, options, extra), /P14_AMBIGUOUS_VIRTUAL_LOADER/);

// An otherwise authentic result from a different actual selected loader fails.
const wrongLoader = observeHook(original, (value) => captureLoad({ ...binding, producer: otherProducer }, value));
assert.throws(() => wrongLoader.call(context, id, options, extra), /P14_WRONG_VIRTUAL_LOADER/);
assert.throws(() => captureLoad({ ...binding, id: '\0unknown' }, output), /UNREVIEWED_VIRTUAL_MODULE/);
assert.throws(() => captureLoad({ ...binding, receipts: new Map() }, { code: code + '// changed\n' }), /P14_VIRTUAL_SOURCE_MISMATCH/);
assert.throws(() => captureLoad({ ...binding, expected: undefined }, output), /P14_VIRTUAL_SOURCE_MISMATCH/);
assert.throws(() => captureLoad(binding, { code: {} }), /P14_VIRTUAL_LOAD_CODE/);
assert.equal(captureLoad(binding, null), null);
assert.equal(captureLoad(binding, undefined), undefined);

// Promise observation preserves asynchronous execution and the exact loaded object.
receipts.clear();
const asynchronous = observeHook(async () => output, (value) => captureLoad(binding, value));
const promise = asynchronous();
assert.ok(promise instanceof Promise);
assert.equal(receipts.size, 0);
assert.equal(await promise, output);
assert.equal(receipts.size, 1);
const wrongAsync = observeHook(async () => output, (value) => captureLoad({ ...binding, producer: otherProducer }, value));
await assert.rejects(wrongAsync(), /P14_WRONG_VIRTUAL_LOADER/);
const nativePromise = Promise.resolve(output);
assert.equal(await observeResult(nativePromise, (value) => assert.equal(value, output)), output);
assert.equal(observeResult(output, (value) => assert.equal(value, output)), output);

const failure = new Error('original synchronous failure');
const throwing = observeHook(() => { throw failure; }, () => assert.fail('unexpected observation'));
assert.throws(() => throwing(), (error) => error === failure);
const rejected = observeHook(() => Promise.reject(failure), () => assert.fail('unexpected observation'));
await assert.rejects(rejected(), (error) => error === failure);

// The very same transform-result guard called by the observer rejects every
// later effect, including a RolldownMagicString-shaped object rather than text.
const magicString = { toString: () => 'changed module' };
for (const result of ['changed', { code: 'changed' }, { code: magicString }, {}, { moduleSideEffects: false }]) {
  const late = observeHook(() => result, (value) => rejectLateTransform(value, true));
  assert.throws(() => late(), /P14_LATE_VIRTUAL_TRANSFORM/);
  rejectLateTransform(result, false);
}
const lateAsync = observeHook(async () => ({ code: magicString }), (value) => rejectLateTransform(value, true));
await assert.rejects(lateAsync(), /P14_LATE_VIRTUAL_TRANSFORM/);
assert.equal(observeHook(() => null, (value) => rejectLateTransform(value, true))(), null);
assert.equal(observeHook(() => undefined, (value) => rejectLateTransform(value, true))(), undefined);

// Hook object filters/order/accessors and nonenumerable descriptors survive.
const filter = { id: { include: /\.svelte$/ } };
const prototype = { sentinel: {} };
const hook = Object.setPrototypeOf({ handler: original, order: 'post', filter }, prototype);
Object.defineProperty(hook, 'filter', { get: () => filter, enumerable: false, configurable: false });
Object.defineProperty(hook, 'order', { value: 'post', enumerable: false, configurable: false, writable: false });
const replaced = replaceHandler(hook, observed);
assert.equal(Object.getPrototypeOf(replaced), prototype);
assert.equal(replaced.handler, observed);
assert.equal(replaced.filter, filter);
assert.deepEqual(Object.getOwnPropertyDescriptor(replaced, 'order'), Object.getOwnPropertyDescriptor(hook, 'order'));
assert.deepEqual(Object.getOwnPropertyDescriptor(replaced, 'filter'), Object.getOwnPropertyDescriptor(hook, 'filter'));
assert.equal(hook.handler, original);

process.stdout.write(JSON.stringify({ kind: 'p14-virtual-module-guard-tests', passed: true,
  causal_wrong_producer: true, unknown_id: true, changed_code: true, duplicate_receipt: true,
  late_magic_string: true, sync_promise_context_arguments_and_hook_metadata: true,
  context_tests: contextTests, lifecycle_tests: lifecycleTests }) + '\n');
