// SPDX-License-Identifier: GPL-3.0-only
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:overmorrow/volparossa/provider.dart';
import 'package:overmorrow/volparossa/products.dart';

class _RequestClient extends http.BaseClient {
  final Future<http.StreamedResponse> Function(http.BaseRequest) handler;
  final void Function()? onClose;
  _RequestClient(this.handler, {this.onClose});

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) => handler(request);

  @override
  void close() => onClose?.call();
}

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
  http.StreamedResponse streamed(http.Response response) => http.StreamedResponse(
    Stream<List<int>>.value(response.bodyBytes),
    response.statusCode,
    headers: response.headers,
    contentLength: response.bodyBytes.length,
  );
  http.Response busy() => http.Response(
    '{"error":"FORECAST_BUSY"}',
    429,
    headers: {'content-type': 'application/json', 'retry-after': '1'},
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
      final observed = providerObservation();
      for (final key in ['weather', 'air_quality']) {
        expect(observed[key], {
          'stage': 'complete', 'outcome': 'success', 'http_class': 'ok',
          'clock_relation': 'withinWindow', 'attempts': 1,
          'response_received': true, 'status_accepted': true, 'body_complete': true,
          'json_decoded': true, 'product_validated': true,
        });
      }
      // A new load resets BOTH products; a late older load cannot overwrite it.
      final late = Completer<http.Response>();
      final older = NativeProviderClient(origin, clock: () => now,
        createClient: () => MockClient((request) async => request.url.path.endsWith('air-quality')
          ? http.Response('', 503) : await late.future)).load();
      expect((providerObservation()['weather'] as Map)['outcome'], 'pending');
      expect((providerObservation()['air_quality'] as Map)['outcome'], 'unobserved');
      await NativeProviderClient(origin, clock: () => now,
        createClient: () => MockClient((request) async => product(request.url.path.endsWith('air-quality')))).load();
      final newer = providerObservation();
      late.complete(http.Response('', 503));
      await older;
      expect(providerObservation(), newer);
    },
  );

  test(
    'weather failures preserve independent AQ and never trigger an origin fallback',
    () async {
      var index = 0;
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
        http.Response('private-invalid-json', 200, headers: {'content-type': 'application/json'}),
        http.Response.bytes([255], 200, headers: {'content-type': 'application/json'}),
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
        final observed = providerObservation()['weather'] as Map;
        expect(observed['outcome'], ['httpStatus', 'httpStatus', 'contentType',
          'contentLength', 'schema', 'jsonEncoding', 'jsonEncoding'][index++]);
        expect(observed['response_received'], true);
        expect(observed['product_validated'], false);
        expect(observed['clock_relation'], 'unknown');
        expect((providerObservation()['air_quality'] as Map)['outcome'], 'success');
        expect(jsonEncode(providerObservation()), isNot(contains('private-invalid')));
      }
      // These clock categories arise only from the actual parser's ordered
      // predicates, using its existing injected clock, never HTTP Date headers.
      for (final quality in [false, true]) {
        final parsed = NativeProduct.parse(fixture[quality ? 'air_quality' : 'weather'],
          airQuality: quality, now: now);
        for (final entry in [
          (parsed.acquiredAt.subtract(const Duration(microseconds: 1)), 'futureAcquired', 'beforeAcquired'),
          (parsed.expiresAt, 'expired', 'atOrAfterExpiry'),
        ]) {
          await NativeProviderClient(origin, clock: () => entry.$1,
            createClient: () => MockClient((request) async => product(request.url.path.endsWith('air-quality')))).load();
          final observed = providerObservation()[quality ? 'air_quality' : 'weather'] as Map;
          expect(observed['outcome'], entry.$2);
          expect(observed['clock_relation'], entry.$3);
          expect(observed['json_decoded'], true);
          expect(observed['product_validated'], false);
        }
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
        final observation = providerObservation()['air_quality'] as Map;
        expect(observation['outcome'], mismatch ? 'areaMismatch' : 'httpStatus');
        expect(observation['product_validated'], mismatch);
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
      for (final entry in <(String, Future<http.StreamedResponse> Function(http.BaseRequest))>[
        ('transport', (_) async => throw const FormatException('private-transport')),
        ('bodyStream', (_) async => http.StreamedResponse(Stream<List<int>>.error(
          const FormatException('private-stream')), 200, headers: {'content-type': 'application/json'})),
        ('bodyTooLarge', (_) async => http.StreamedResponse(Stream<List<int>>.value(
          List<int>.filled(maxProviderBytes + 1, 0)), 200, headers: {'content-type': 'application/json'})),
      ]) {
        final result = await NativeProviderClient(origin, clock: () => now,
          createClient: () => _RequestClient(entry.$2)).load();
        expect(result.areaSource, null);
        for (final key in ['weather', 'air_quality']) {
          final observed = providerObservation()[key] as Map;
          expect(observed['outcome'], entry.$1);
          expect(observed['response_received'], entry.$1 != 'transport');
          expect(observed['body_complete'], false);
          expect(observed['product_validated'], false);
        }
        expect(jsonEncode(providerObservation()), isNot(contains('private-')));
      }
    },
  );

  testWidgets('cold products can finish after the old 20 second timeout', (tester) async {
    final calls = <String>[];
    final requests = <http.BaseRequest>[];
    var closed = 0;
    NativeProducts? result;
    final client = NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => _RequestClient((request) async {
        requests.add(request);
        calls.add(request.url.path);
        await Future<void>.delayed(const Duration(seconds: 120));
        return streamed(product(request.url.path.endsWith('air-quality')));
      }, onClose: () => closed++),
    );
    unawaited(client.load().then((value) => result = value));
    await tester.pump();
    await tester.pump(const Duration(seconds: 20));
    expect(result, null);
    expect(calls.length, 1);
    expect(closed, 0);
    await tester.pump(const Duration(seconds: 100));
    await tester.pump(); // Drain the streamed-response continuation; no elapsed time.
    expect(calls.length, 2);
    expect(closed, 1);
    await tester.pump(const Duration(seconds: 120));
    await tester.pump();
    expect(result!.weather, isNotNull);
    expect(result!.airQuality, isNotNull);
    expect(closed, 2);
    for (final request in requests) {
      expect(request, isA<http.AbortableRequest>());
      expect(request.followRedirects, false);
      expect(request.url.origin, origin.origin);
      expect(request.url.hasQuery, false);
    }
  });

  testWidgets('only exact busy admission is retried, at most five waits per product', (tester) async {
    var weatherAttempts = 0;
    var aqAttempts = 0;
    var closed = 0;
    final closedBeforeRequest = <int>[];
    NativeProducts? result;
    unawaited(NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => _RequestClient((request) async {
        closedBeforeRequest.add(closed);
        if (request.url.path.endsWith('air-quality')) {
          aqAttempts++;
          return streamed(product(true));
        }
        weatherAttempts++;
        return streamed(busy());
      }, onClose: () => closed++),
    ).load().then((value) => result = value));
    await tester.pump();
    await tester.pump();
    expect(weatherAttempts, 1);
    expect(closed, 1); // The busy body is consumed before its pacing timer starts.
    for (var retry = 1; retry <= 5; retry++) {
      await tester.pump(const Duration(milliseconds: 999));
      expect(weatherAttempts, retry);
      await tester.pump(const Duration(milliseconds: 1));
      await tester.pump();
      expect(weatherAttempts, retry + 1, reason: 'retry $retry; closed=$closed; result=${result?.weatherError}/${result?.airQualityError}');
    }
    expect(weatherAttempts, 6);
    expect(aqAttempts, 1);
    expect(closed, 7);
    expect(closedBeforeRequest, [0, 1, 2, 3, 4, 5, 6]);
    expect(result!.weather, null);
    expect(result!.weatherError, isNotNull);
    expect(result!.airQuality, isNotNull);
    expect((providerObservation()['weather'] as Map)['outcome'], 'busyLimit');
    expect((providerObservation()['weather'] as Map)['attempts'], 6);
    expect((providerObservation()['weather'] as Map)['product_validated'], false);
  });

  testWidgets('busy cleanup admission can recover independently for either product', (tester) async {
    final attempts = <String, int>{};
    NativeProducts? result;
    unawaited(NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => MockClient((request) async {
        final count = attempts.update(request.url.path, (value) => value + 1, ifAbsent: () => 1);
        return count <= 2 ? busy() : product(request.url.path.endsWith('air-quality'));
      }),
    ).load().then((value) => result = value));
    await tester.pump();
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    expect(attempts.values.toList(), [3, 3]);
    expect(result!.weather, isNotNull);
    expect(result!.airQuality, isNotNull);
    for (final key in ['weather', 'air_quality']) {
      final observed = providerObservation()[key] as Map;
      expect(observed['outcome'], 'success');
      expect(observed['attempts'], 3);
    }
  });

  test('other failures and malformed busy responses are never retried', () async {
    final invalid = [
      http.Response('{"error":"FORECAST_BUSY"}', 429, headers: {'content-type': 'application/json'}),
      http.Response('{"error":"FORECAST_BUSY"}', 429, headers: {'content-type': 'application/json', 'retry-after': '2'}),
      http.Response('{"error":"OTHER"}', 429, headers: busy().headers),
      http.Response('{"error":"FORECAST_BUSY","extra":true}', 429, headers: busy().headers),
      http.Response('{"error":"FORECAST_BUSY"}', 503, headers: busy().headers),
      http.Response('{"error":"FORECAST_BUSY"}', 429, headers: {'content-type': 'text/html', 'retry-after': '1'}),
      http.Response('{"error":"FORECAST_BUSY"}', 429, headers: {'content-type': 'application/json-evil', 'retry-after': '1'}),
      http.Response('x' * 1025, 429, headers: busy().headers),
      http.Response('not JSON', 429, headers: busy().headers),
    ];
    for (final response in invalid) {
      var calls = 0;
      final result = await NativeProviderClient(
        origin,
        clock: () => now,
        createClient: () => MockClient((request) async {
          calls++;
          return request.url.path.endsWith('air-quality') ? product(true) : response;
        }),
      ).load();
      expect(calls, 2);
      expect(result.weather, null);
      expect(result.airQuality, isNotNull);
    }
  });

  testWidgets('retries share the original deadline and a late resistant response is ignored', (tester) async {
    var weatherAttempts = 0;
    var aqAttempts = 0;
    var aborts = 0;
    var closed = 0;
    final late = Completer<http.StreamedResponse>();
    NativeProducts? result;
    unawaited(NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => _RequestClient((request) async {
        if (request.url.path.endsWith('air-quality')) {
          aqAttempts++;
          return streamed(product(true));
        }
        weatherAttempts++;
        if (weatherAttempts <= 4) return streamed(busy());
        (request as http.AbortableRequest).abortTrigger!.then((_) => aborts++);
        return late.future; // Deliberately ignores cancellation until completed below.
      }, onClose: () => closed++),
    ).load().then((value) => result = value));
    await tester.pump();
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    expect(weatherAttempts, 5);
    await tester.pump(const Duration(seconds: 188));
    expect(aborts, 0);
    await tester.pump(const Duration(seconds: 1));
    expect(aborts, 1); // 193s since product start, not since its fifth attempt.
    expect(closed, 5);
    expect(aqAttempts, 0); // The bounded local drain has not finished yet.
    await tester.pump(const Duration(seconds: 2));
    expect(aqAttempts, 1);
    expect(result!.weather, null);
    expect(result!.weatherError, isNotNull);
    expect(result!.airQuality, isNotNull);
    final observationBeforeLate = providerObservation();
    expect((observationBeforeLate['weather'] as Map)['outcome'], 'deadline');
    late.complete(streamed(product(false)));
    await tester.pump();
    expect(weatherAttempts, 5);
    expect(aqAttempts, 1);
    expect(closed, 6);
    expect(result!.weather, null);
    expect(providerObservation(), observationBeforeLate);
  });

  testWidgets('deadline aborts a response body and drains it before independent AQ', (tester) async {
    var bodyCancelled = false;
    var aborted = false;
    var aqAttempts = 0;
    final stateBeforeAq = <bool>[];
    NativeProducts? result;
    late final StreamController<List<int>> body;
    body = StreamController<List<int>>(onCancel: () => bodyCancelled = true);
    unawaited(NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => _RequestClient((request) async {
        if (request.url.path.endsWith('air-quality')) {
          stateBeforeAq.addAll([aborted, bodyCancelled]);
          aqAttempts++;
          return streamed(product(true));
        }
        (request as http.AbortableRequest).abortTrigger!.then((_) {
          aborted = true;
          body.addError(http.RequestAbortedException(request.url));
          unawaited(body.close());
        });
        return http.StreamedResponse(body.stream, 200, headers: {'content-type': 'application/json'});
      }),
    ).load().then((value) => result = value));
    await tester.pump();
    await tester.pump(const Duration(seconds: 193));
    await tester.pump(); // Settle the stream's cancellation future without advancing time.
    expect(aborted, true);
    expect(bodyCancelled, true);
    expect(aqAttempts, 1);
    expect(stateBeforeAq, [true, true]);
    expect(result!.weather, null);
    expect(result!.airQuality, isNotNull);
  });

  testWidgets('a deadline during busy pacing cannot launch a late retry', (tester) async {
    var weatherAttempts = 0;
    var aqAttempts = 0;
    NativeProducts? result;
    unawaited(NativeProviderClient(
      origin,
      clock: () => now,
      createClient: () => MockClient((request) async {
        if (request.url.path.endsWith('air-quality')) {
          aqAttempts++;
          return product(true);
        }
        weatherAttempts++;
        await Future<void>.delayed(const Duration(milliseconds: 192500));
        return busy();
      }),
    ).load().then((value) => result = value));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 192500));
    await tester.pump(const Duration(milliseconds: 500));
    expect(weatherAttempts, 1);
    expect(aqAttempts, 0);
    await tester.pump(const Duration(milliseconds: 500));
    expect(weatherAttempts, 1);
    expect(aqAttempts, 1);
    expect(result!.weather, null);
    expect(result!.airQuality, isNotNull);
  });
}
