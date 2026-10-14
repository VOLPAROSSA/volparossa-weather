// SPDX-License-Identifier: GPL-3.0-only
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../decoders/weather_data.dart';
import 'profile.dart';
import 'products.dart';

const maxProviderBytes = 524288;
// The bridge owns a 180s operation deadline and a 185s socket safety bound.
// Reserve the last 2s of this one product deadline for local cancellation.
const providerProductDeadline = Duration(seconds: 195);
const providerAbortDrain = Duration(seconds: 2);
const providerBusyDelay = Duration(seconds: 1);
const providerBusyRetries = 5;

enum _Stage { unobserved, request, headers, body, decode, validate, complete }
enum _Outcome {
  unobserved, pending, transport, httpStatus, contentType, contentLength,
  bodyTooLarge, bodyStream, jsonEncoding, schema, futureAcquired, expired,
  success, busy, busyLimit, deadline, areaMismatch,
}
enum _Http { unobserved, ok, busy, redirect, clientError, serverError, other }
enum _Clock { unknown, beforeAcquired, atOrAfterExpiry, withinWindow }

class _ProductObservation {
  var stage = _Stage.unobserved;
  var outcome = _Outcome.unobserved;
  var httpStatus = _Http.unobserved;
  var clock = _Clock.unknown;
  var attempts = 0;
  var responseReceived = false, statusAccepted = false, bodyComplete = false;
  var jsonDecoded = false, productValidated = false;
  var closed = false;

  void begin() {
    if (closed) return;
    attempts++;
    stage = _Stage.request;
    outcome = _Outcome.pending;
    httpStatus = _Http.unobserved;
    clock = _Clock.unknown;
    responseReceived = statusAccepted = bodyComplete = false;
    jsonDecoded = productValidated = false;
  }

  void fail(Object error) {
    if (closed || outcome != _Outcome.pending) return;
    if (error is ProductClockException) {
      final future = error.reason == ProductClockRejection.futureAcquired;
      outcome = future ? _Outcome.futureAcquired : _Outcome.expired;
      clock = future ? _Clock.beforeAcquired : _Clock.atOrAfterExpiry;
    } else {
      outcome = switch (stage) {
        _Stage.request => _Outcome.transport,
        _Stage.body => _Outcome.bodyStream,
        _Stage.decode => _Outcome.jsonEncoding,
        _ => _Outcome.schema,
      };
    }
  }

  // Clock relation is the parser's instant, not a later display-freshness or
  // host/guest synchronisation assertion. Unknown stays unknown after schema
  // failure even if some earlier timestamp predicates happened to pass.
  Map<String, Object> snapshot() => {
    'stage': stage.name, 'outcome': outcome.name, 'http_class': httpStatus.name,
    'clock_relation': clock.name, 'attempts': attempts,
    'response_received': responseReceived, 'status_accepted': statusAccepted,
    'body_complete': bodyComplete, 'json_decoded': jsonDecoded,
    'product_validated': productValidated,
  };
}

class _LoadObservation {
  final weather = _ProductObservation(), airQuality = _ProductObservation();
}

// Bounded transient observation only. A new load replaces both products at
// once; late work retains its own object and cannot overwrite the newer load.
// No payloads, timestamps, URLs, exception messages or history are retained.
var _lastLoad = _LoadObservation();
Map<String, Object> providerObservation() => {
  'schema': 1, 'weather': _lastLoad.weather.snapshot(),
  'air_quality': _lastLoad.airQuality.snapshot(),
};

Uri providerOrigin() {
  final origin = kIsWeb
      ? Uri.parse(Uri.base.origin)
      : Uri.tryParse(volparossaNativeOrigin);
  if (origin == null ||
      origin.scheme != 'http' ||
      origin.host != '127.0.0.1' ||
      !origin.hasPort ||
      origin.port <= 0 ||
      origin.userInfo.isNotEmpty ||
      (origin.path.isNotEmpty && origin.path != '/') ||
      origin.hasQuery ||
      origin.hasFragment) {
    throw const FormatException('VOLPAROSSA loopback provider unavailable');
  }
  return origin;
}

/// This client is only a consumer of the same shared provider as Drizz.li.
/// No model/source acquisition, disk cache, geolocation or peer scheduler here.
class NativeProviderClient {
  final Uri origin;
  final http.Client Function() createClient;
  final DateTime Function() clock;
  NativeProviderClient(
    this.origin, {
    http.Client Function()? createClient,
    DateTime Function()? clock,
  }) : createClient = createClient ?? http.Client.new,
       clock = clock ?? DateTime.now;

  Future<NativeProduct> _product(bool airQuality, _ProductObservation observed) async {
    var cancelled = false;
    http.Client? activeClient;
    Completer<void>? activeAbort;

    void checkCancelled() {
      if (cancelled) throw TimeoutException('VOLPAROSSA product deadline');
    }

    void cancel() {
      cancelled = true;
      if (activeAbort != null && !activeAbort!.isCompleted) {
        activeAbort!.complete();
      }
      activeClient?.close();
      activeClient = null;
    }

    Future<NativeProduct?> attempt() async {
      checkCancelled();
      observed.begin();
      final client = createClient();
      final abort = Completer<void>();
      activeClient = client;
      activeAbort = abort;
      try {
        final request =
            http.AbortableRequest(
                'GET',
                origin.resolve(
                  airQuality
                      ? '/api/volparossa/air-quality'
                      : '/api/volparossa/forecast',
                ),
                abortTrigger: abort.future,
              )
              ..followRedirects = false
              ..headers['Accept'] = 'application/json';
        final response = await client.send(request);
        checkCancelled();
        observed.stage = _Stage.headers;
        observed.responseReceived = true;
        final busy =
            response.statusCode == 429 &&
            response.headers['retry-after'] == '1';
        final byteLimit = busy ? 1024 : maxProviderBytes;
        observed.httpStatus = response.statusCode == 200 ? _Http.ok
            : busy ? _Http.busy
            : response.statusCode >= 300 && response.statusCode < 400 ? _Http.redirect
            : response.statusCode >= 400 && response.statusCode < 500 ? _Http.clientError
            : response.statusCode >= 500 && response.statusCode < 600 ? _Http.serverError
            : _Http.other;
        // Split the original ordered rejection without changing its predicates.
        if (response.statusCode != 200 && !busy) {
          observed.outcome = _Outcome.httpStatus;
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        observed.statusAccepted = true;
        if ((response.headers['content-type'] ?? '')
                    .split(';').first.trim().toLowerCase() !=
                'application/json') {
          observed.outcome = _Outcome.contentType;
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        if (response.contentLength != null && response.contentLength! > byteLimit) {
          observed.outcome = _Outcome.contentLength;
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        observed.stage = _Stage.body;
        final bytes = BytesBuilder(copy: false);
        await for (final chunk in response.stream) {
          checkCancelled();
          if (bytes.length + chunk.length > byteLimit) {
            observed.outcome = _Outcome.bodyTooLarge;
            throw const FormatException('VOLPAROSSA product too large');
          }
          bytes.add(chunk);
        }
        checkCancelled();
        observed.bodyComplete = true;
        observed.stage = _Stage.decode;
        final decoded = jsonDecode(utf8.decode(bytes.takeBytes()));
        observed.jsonDecoded = true;
        observed.stage = _Stage.validate;
        if (busy) {
          if (decoded is Map &&
              decoded.length == 1 &&
              decoded['error'] == 'FORECAST_BUSY') {
            observed.outcome = _Outcome.busy;
            return null;
          }
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        final product = NativeProduct.parse(
          decoded,
          airQuality: airQuality,
          now: clock().toUtc(),
        );
        observed.productValidated = true;
        observed.clock = _Clock.withinWindow;
        observed.outcome = _Outcome.success;
        observed.stage = _Stage.complete;
        return product;
      } catch (error) {
        observed.fail(error);
        rethrow;
      } finally {
        // Abort also cancels a response body after headers have arrived; merely
        // closing BrowserClient is not enough for that stage of its lifecycle.
        if (!abort.isCompleted) abort.complete();
        if (identical(activeClient, client)) {
          client.close();
          activeClient = null;
        }
        if (identical(activeAbort, abort)) activeAbort = null;
      }
    }

    Future<NativeProduct> acquire() async {
      for (var retries = 0; ; retries++) {
        final product = await attempt();
        checkCancelled();
        if (product != null) return product;
        if (retries == providerBusyRetries) {
          observed.outcome = _Outcome.busyLimit;
          throw const FormatException('VOLPAROSSA provider remains busy');
        }
        // Pacing, not a claim that remote cleanup finished. Only the next
        // server admission can establish that its single slot is available.
        await Future<void>.delayed(providerBusyDelay);
        checkCancelled();
      }
    }

    final operation = acquire();
    try {
      return await operation.timeout(
        providerProductDeadline - providerAbortDrain,
        onTimeout: () async {
          observed.outcome = _Outcome.deadline;
          observed.closed = true;
          cancel();
          // Give the abortable request/stream time to settle locally without
          // extending the original deadline. Uncooperative late completion is
          // ignored and cannot parse a product or launch another attempt.
          try {
            await operation.timeout(providerAbortDrain);
          } catch (_) {}
          throw TimeoutException('VOLPAROSSA product deadline');
        },
      );
    } catch (error) {
      observed.fail(error);
      rethrow;
    } finally {
      observed.closed = true;
      cancel();
    }
  }

  Future<NativeProducts> load() async {
    final observed = _LoadObservation();
    _lastLoad = observed;
    NativeProduct? weather, airQuality;
    String? weatherError, airQualityError;
    // The shared bridge has one bounded active operation. Independent failures
    // are preserved; neither product silently substitutes for the other.
    try {
      weather = await _product(false, observed.weather);
    } catch (_) {
      weatherError = 'Weather unavailable or expired';
    }
    try {
      airQuality = await _product(true, observed.airQuality);
    } catch (_) {
      airQualityError = 'Air quality unavailable or expired';
    }
    if (weather != null &&
        airQuality != null &&
        (weather.latitude != airQuality.latitude ||
            weather.longitude != airQuality.longitude)) {
      airQuality = null;
      airQualityError = 'Air quality rejected: configured area mismatch';
      observed.airQuality.outcome = _Outcome.areaMismatch;
    }
    return NativeProducts(weather, airQuality, weatherError, airQualityError);
  }
}

Future<WeatherData> volparossaWeatherData() async {
  final products = await NativeProviderClient(providerOrigin()).load();
  final area = products.areaSource;
  if (area == null)
    throw const FormatException(
      'VOLPAROSSA weather and air quality unavailable',
    );
  final now = DateTime.now().toUtc();
  return WeatherData(
    place: area.areaLabel,
    lat: area.latitude,
    lng: area.longitude,
    provider: 'volparossa',
    nativeProducts: products,
    sunStatus: null,
    aqi: null,
    radar: null,
    days: const [],
    hourly72: const [],
    current: null,
    fetchDatetime: now,
    isOnline: true,
    updatedTime: area.acquiredAt,
    localTime: now,
    minutely15Precip: null,
    alerts: const [],
    dailyMinMaxTemp: const [],
  );
}
