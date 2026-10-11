// SPDX-License-Identifier: GPL-3.0-only
// Explicit synthetic provider responses; never upstream weather or delivery proof.
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:overmorrow/volparossa/products.dart';

void main() {
  final fixture = jsonDecode(
    File('test/volparossa/fixtures/products.json').readAsStringSync(),
  );
  final now = DateTime.parse(fixture['now']);
  dynamic copy(dynamic value) => jsonDecode(jsonEncode(value));
  NativeProduct weather(dynamic value) =>
      NativeProduct.parse(value, airQuality: false, now: now);
  NativeProduct aq(dynamic value) =>
      NativeProduct.parse(value, airQuality: true, now: now);

  test(
    'native timelines and independent runs survive without observations or AQI',
    () {
      final w = weather(fixture['weather']), a = aq(fixture['air_quality']);
      expect(w.samples.map((s) => s.leadHours), [3, 9, 24]);
      expect(a.samples.map((s) => s.leadHours), [3, 6, 12]);
      expect(w.modelRun, isNot(a.modelRun));
      expect(w.latitude, a.latitude);
      expect(w.longitude, a.longitude);
      expect(a.samples.first.values.containsKey('aqi'), false);
      expect(w.samples[1].accumulationStart, w.modelRun);
      expect(w.samples[1].accumulationEnd, w.samples[1].validAt);
      expect(
        w.samples[2].accumulationStart,
        w.modelRun.add(const Duration(hours: 6)),
      );
    },
  );

  test(
    'missing, real zero and small precipitation/particulates stay distinct',
    () {
      final w = weather(fixture['weather']), a = aq(fixture['air_quality']);
      expect(w.samples.map((s) => s.values['precipitation']), [null, 0, 0.01]);
      expect(a.samples.map((s) => s.values['pm2_5']), [null, 0, 5.53071]);
      expect(a.samples.map((s) => s.values['pm10']), [11.5959, null, 0]);
    },
  );

  test('expiry is strict, immutable and independent between products', () {
    final w = weather(fixture['weather']);
    expect(
      w.staleAt(w.expiresAt.subtract(const Duration(milliseconds: 1))),
      false,
    );
    expect(w.staleAt(w.expiresAt), true);
    expect(
      w.staleAt(w.acquiredAt.subtract(const Duration(milliseconds: 1))),
      true,
    );
    expect(
      () => NativeProduct.parse(
        fixture['weather'],
        airQuality: false,
        now: w.expiresAt,
      ),
      throwsFormatException,
    );
    final different = copy(fixture['air_quality']);
    final expiry = now.add(const Duration(seconds: 30)).toIso8601String();
    different['delivery']['publication_expires_at'] = expiry;
    different['freshness']['publication_expires_at'] = expiry;
    different['freshness']['expires_at'] = expiry;
    final products = NativeProducts(w, aq(different), null, null);
    expect(
      products.weather!.staleAt(now.add(const Duration(seconds: 31))),
      false,
    );
    expect(
      products.airQuality!.staleAt(now.add(const Duration(seconds: 31))),
      true,
    );
  });

  test(
    'projection, native times, units, windows and privacy claims are checked',
    () {
      final changes = <void Function(dynamic)>[
        (v) => v['timeline']['valid_at'][0] = v['timeline']['valid_at'][1],
        (v) => v['timeline']['time_zone'] = 'local',
        (v) => v['series'][0]['values'][0] = 999,
        (v) => v['series'][0]['unit'] = 'K',
        (v) => v['capabilities']['interpolation'] = true,
        (v) => v['capabilities']['current_observations'] = true,
        (v) => v['forecast']['area']['sharing'] = 'private',
        (v) => v['delivery']['mode'] = 'origin',
        (v) => v['delivery']['upstream_origin_attested'] = true,
        (v) => v['freshness']['expires_at'] = now
            .add(const Duration(days: 5))
            .toIso8601String(),
        (v) => v['forecast']['samples'][0]['lead_hours'] = -1,
        (v) => v['forecast']['samples'][0]['temperature_2m'] = -999,
        (v) => v['forecast']['samples'][0]['wind_10m']['speed'] = 999,
        (v) => v['series'][3]['accumulation_windows'][2]['start_at'] = now
            .toIso8601String(),
        (v) => v['forecast']['source']['license_url'] = 'javascript:bad',
      ];
      for (final change in changes) {
        final bad = copy(fixture['weather']);
        change(bad);
        expect(() => weather(bad), throwsA(anything));
      }
    },
  );

  test('product types and public areas cannot be mixed', () {
    expect(() => aq(fixture['weather']), throwsFormatException);
    expect(() => weather(fixture['air_quality']), throwsFormatException);
    final wrongArea = copy(fixture['air_quality']);
    wrongArea['forecast']['area']['latitude'] = 50.0;
    expect(
      () => NativeProducts(
        weather(fixture['weather']),
        aq(wrongArea),
        null,
        null,
      ),
      throwsFormatException,
    );
    final unavailable = NativeProducts(
      null,
      aq(fixture['air_quality']),
      'Weather unavailable',
      null,
    );
    expect(unavailable.weather, null);
    expect(unavailable.areaSource, unavailable.airQuality);
  });
}
