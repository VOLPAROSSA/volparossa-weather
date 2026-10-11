// SPDX-License-Identifier: GPL-3.0-only
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:overmorrow/volparossa/provider.dart';

void main() {
  final fixture = jsonDecode(
    File('test/volparossa/fixtures/products.json').readAsStringSync(),
  );
  final now = DateTime.parse(fixture['now']);
  final origin = Uri.parse('http://127.0.0.1:43210');
  http.Response product(bool aq) => http.Response(
    jsonEncode(fixture[aq ? 'air_quality' : 'weather']),
    200,
    headers: {'content-type': 'application/json'},
  );

  test(
    'one sequential shared-provider request per product, no source/location requests',
    () async {
      final calls = <String>[];
      var active = false;
      final client = NativeProviderClient(
        origin,
        clock: () => now,
        createClient: () => MockClient((request) async {
          expect(active, false);
          active = true;
          expect(request.method, 'GET');
          expect(request.followRedirects, false);
          expect(request.url.origin, origin.origin);
          expect(request.url.hasQuery, false);
          calls.add(request.url.path);
          await Future<void>.delayed(Duration.zero);
          active = false;
          return product(request.url.path.endsWith('air-quality'));
        }),
      );
      final result = await client.load();
      expect(calls, [
        '/api/volparossa/forecast',
        '/api/volparossa/air-quality',
      ]);
      expect(result.weather, isNotNull);
      expect(result.airQuality, isNotNull);
      expect(result.weatherError, null);
      expect(result.airQualityError, null);
    },
  );

  test(
    'weather failures preserve independent AQ and never trigger an origin fallback',
    () async {
      for (final response in [
        http.Response('', 503),
        http.Response(
          '',
          302,
          headers: {'location': 'https://example.invalid'},
        ),
        http.Response('{}', 200, headers: {'content-type': 'text/html'}),
        http.Response(
          'x' * (maxProviderBytes + 1),
          200,
          headers: {'content-type': 'application/json'},
        ),
        http.Response('{}', 200, headers: {'content-type': 'application/json'}),
      ]) {
        var count = 0;
        final result = await NativeProviderClient(
          origin,
          clock: () => now,
          createClient: () => MockClient((request) async {
            count++;
            return request.url.path.endsWith('air-quality')
                ? product(true)
                : response;
          }),
        ).load();
        expect(count, 2);
        expect(result.weather, null);
        expect(result.weatherError, isNotNull);
        expect(result.airQuality, isNotNull);
        expect(result.airQualityError, null);
      }
    },
  );

  test(
    'AQ failure and configured-area mismatch never erase a valid weather product',
    () async {
      for (final mismatch in [false, true]) {
        final aq = jsonDecode(jsonEncode(fixture['air_quality']));
        aq['forecast']['area']['latitude'] = 40.0;
        var calls = 0;
        final result = await NativeProviderClient(
          origin,
          clock: () => now,
          createClient: () => MockClient((request) async {
            calls++;
            if (!request.url.path.endsWith('air-quality'))
              return product(false);
            return mismatch
                ? http.Response(
                    jsonEncode(aq),
                    200,
                    headers: {'content-type': 'application/json'},
                  )
                : http.Response('', 503);
          }),
        ).load();
        expect(calls, 2);
        expect(result.weather, isNotNull);
        expect(result.airQuality, null);
        expect(result.airQualityError, isNotNull);
      }
    },
  );

  test(
    'two unavailable products stay unavailable; no old disk cache or fake values',
    () async {
      final result = await NativeProviderClient(
        origin,
        clock: () => now,
        createClient: () => MockClient((_) async => http.Response('', 503)),
      ).load();
      expect(result.areaSource, null);
      expect(result.weather, null);
      expect(result.airQuality, null);
      expect(result.weatherError, isNotNull);
      expect(result.airQualityError, isNotNull);
    },
  );
}
