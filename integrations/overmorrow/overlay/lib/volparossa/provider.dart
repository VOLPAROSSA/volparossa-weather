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

  Future<NativeProduct> _product(bool airQuality) async {
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
        final busy =
            response.statusCode == 429 &&
            response.headers['retry-after'] == '1';
        final byteLimit = busy ? 1024 : maxProviderBytes;
        if ((response.statusCode != 200 && !busy) ||
            (response.headers['content-type'] ?? '')
                    .split(';').first.trim().toLowerCase() !=
                'application/json' ||
            (response.contentLength != null &&
                response.contentLength! > byteLimit)) {
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        final bytes = BytesBuilder(copy: false);
        await for (final chunk in response.stream) {
          checkCancelled();
          if (bytes.length + chunk.length > byteLimit) {
            throw const FormatException('VOLPAROSSA product too large');
          }
          bytes.add(chunk);
        }
        checkCancelled();
        final decoded = jsonDecode(utf8.decode(bytes.takeBytes()));
        if (busy) {
          if (decoded is Map &&
              decoded.length == 1 &&
              decoded['error'] == 'FORECAST_BUSY') {
            return null;
          }
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        return NativeProduct.parse(
          decoded,
          airQuality: airQuality,
          now: clock().toUtc(),
        );
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
    } finally {
      cancel();
    }
  }

  Future<NativeProducts> load() async {
    NativeProduct? weather, airQuality;
    String? weatherError, airQualityError;
    // The shared bridge has one bounded active operation. Independent failures
    // are preserved; neither product silently substitutes for the other.
    try {
      weather = await _product(false);
    } catch (_) {
      weatherError = 'Weather unavailable or expired';
    }
    try {
      airQuality = await _product(true);
    } catch (_) {
      airQualityError = 'Air quality unavailable or expired';
    }
    if (weather != null &&
        airQuality != null &&
        (weather.latitude != airQuality.latitude ||
            weather.longitude != airQuality.longitude)) {
      airQuality = null;
      airQualityError = 'Air quality rejected: configured area mismatch';
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
