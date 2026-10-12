// SPDX-License-Identifier: GPL-3.0-only
// Inert observer/fixture contracts: no adb, emulator, server, SDK or app launch.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { HEADERS, PACKAGE, COMPONENT, numberEqual, validateSnapshot, verifyTable, vmAddress } from './native-android-driver.mjs';
import { nativeFixtureState, API_PORT, CONTROL_PORT } from './native-android-fixture.mjs';

const NOW = '2026-10-12T02:00:00.000Z';
function fixture() {
  const state = nativeFixtureState(NOW);
  return { state, weather: state.product(false, NOW), air_quality: state.product(true, NOW) };
}
function table(product, quality = false) {
  return { product: quality ? 'air_quality' : 'weather', headers: HEADERS[quality ? 'air_quality' : 'weather'],
    rows: product.forecast.samples.map(sample => [sample.valid_at,
      ...(quality ? [sample.pm2_5, sample.pm10] : [sample.temperature_2m,
        sample.wind_10m.speed, sample.wind_10m.direction_from, sample.precipitation.amount])
        .map(value => value === null ? 'Not available' : String(value)),
      ...(!quality ? [sample.precipitation.start_at === null ? 'Not available'
        : `${sample.precipitation.start_at} → ${sample.precipitation.end_at}`] : [])]) };
}
function snapshot(tables = []) {
  return { schema: 1, kind: 'overmorrow-native-mounted-ui', package: PACKAGE, platform: 'android',
    profile: true, origin: 'http://127.0.0.1:43210', tables, labels: [], refresh: [],
    lifecycle: ['resumed'], current_lifecycle: 'resumed', screen: { width: 1080, height: 1920 } };
}

test('fixture separates loopback API/control and makes no core claim', () => {
  assert.equal(API_PORT, 43210); assert.equal(CONTROL_PORT, 43211);
  const { state } = fixture(), status = state.status();
  assert.equal(status.core_executed, false); assert.equal(status.overlay_proven, false);
  assert.equal(status.synthetic_weather, true); assert.equal(status.synthetic_air_quality, true);
  assert.deepEqual(status.calls, { weather: 1, air_quality: 1 });
});
test('fixture phases require real prior requests and preserve missing values', () => {
  const state = nativeFixtureState(NOW);
  assert.throws(() => state.setPhase('refresh'));
  state.product(false, NOW); state.product(true, NOW); state.setPhase('refresh');
  const weather = state.product(false, NOW); state.product(true, NOW);
  assert.equal(weather.forecast.samples[0].temperature_2m, null);
  state.setPhase('short-lived');
  const short = state.product(false, NOW); state.product(true, NOW);
  assert.equal(Date.parse(short.freshness.expires_at) - Date.parse(NOW), 4500);
  assert.throws(() => state.product(false, NOW)); assert.throws(() => state.setPhase('initial'));
});
test('exact ordered weather and independent AQ rows pass', () => {
  const values = fixture();
  assert.equal(verifyTable(table(values.weather), values.weather).rows, 4);
  assert.equal(verifyTable(table(values.air_quality, true), values.air_quality).rows, 5);
  validateSnapshot(snapshot([table(values.weather), table(values.air_quality, true)]));
});
test('numeric comparison permits redundant decimals but no missing-to-zero coercion or rounding', () => {
  assert.equal(numberEqual('2.0', 2), true); assert.equal(numberEqual('20e-1', 2), true);
  assert.equal(numberEqual('Not available', null), true); assert.equal(numberEqual('0', null), false);
  assert.equal(numberEqual('2.0000000000000000001', 2), false);
  assert.equal(numberEqual('NaN', NaN), false); assert.equal(numberEqual('', 0), false);
});
test('time, order, rows, exact precipitation windows and missing values cannot be substituted', () => {
  const { weather } = fixture();
  for (const mutate of [value => value.rows.reverse(), value => value.rows.pop(),
    value => { value.rows[0][0] = '2026-10-12T00:00:01.000Z'; },
    value => { value.rows[1][5] = 'Not available'; },
    value => { value.rows[0][1] = '0'; }, value => value.headers.reverse()]) {
    const value = structuredClone(table(weather)); mutate(value);
    assert.throws(() => verifyTable(value, weather));
  }
});
test('duplicated or unknown mounted table ownership rejected', () => {
  const { weather } = fixture(), value = table(weather);
  assert.throws(() => validateSnapshot(snapshot([value, value])));
  assert.throws(() => validateSnapshot(snapshot([{ ...value, product: 'other' }])));
});
test('wrong app/profile/origin and unbounded data rejected', () => {
  for (const change of [{ package: 'other' }, { profile: false }, { origin: 'https://example.com' },
    { labels: ['x'.repeat(1025)] }, { lifecycle: Array(17).fill('resumed') },
    { screen: { width: 99999, height: 10 } }]) {
    assert.throws(() => validateSnapshot({ ...snapshot(), ...change }));
  }
});
test('visible refresh is bounded and carries independent hit-test observation', () => {
  const value = snapshot(); value.refresh = [{ x: 500, y: 900, enabled: true, visible: true, hit_testable: true }];
  validateSnapshot(value);
  delete value.refresh[0].hit_testable; assert.throws(() => validateSnapshot(value));
  value.refresh[0].hit_testable = false; value.refresh[0].x = -2;
  assert.throws(() => validateSnapshot(value));
});
test('VM address is one loopback service from bounded log text, never arbitrary authority', () => {
  const line = 'I/flutter ( 1234): The Dart VM service is listening on http://127.0.0.1:34567/Ab_c-123=/';
  assert.deepEqual(vmAddress(line, '1234'), { port: 34567, token: 'Ab_c-123=' });
  for (const value of [line + '\n' + line, line.replace('127.0.0.1', 'example.com'),
    line.replace('34567', '65536'), 'x'.repeat(65537)]) assert.throws(() => vmAddress(value, '1234'));
});
test('driver owns exact Android component and uses only observation RPC methods', async () => {
  assert.equal(COMPONENT, 'org.volparossa.weather.trial/com.marotidev.overmorrow.MainActivity');
  const source = await readFile(new URL('./native-android-driver.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes("['getVM', 'getIsolate', EXTENSION].includes(method)"));
  assert.ok(source.includes("['shell', 'input', 'tap'"));
  assert.ok(source.includes("['shell', 'input', 'keyevent', 'KEYCODE_HOME']"));
  assert.ok(source.includes('pixel_visibility_proven: false'));
  assert.ok(!source.includes("vm.request('evaluate'"));
  assert.ok(!source.includes('report.token') && !source.includes('report.logs'));
});
