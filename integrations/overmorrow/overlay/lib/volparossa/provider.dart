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
    final client = createClient();
    try {
      return await (() async {
        final request =
            http.Request(
                'GET',
                origin.resolve(
                  airQuality
                      ? '/api/volparossa/air-quality'
                      : '/api/volparossa/forecast',
                ),
              )
              ..followRedirects = false
              ..headers['Accept'] = 'application/json';
        final response = await client.send(request);
        if (response.statusCode != 200 ||
            !(response.headers['content-type'] ?? '').startsWith(
              'application/json',
            ) ||
            (response.contentLength != null &&
                response.contentLength! > maxProviderBytes)) {
          throw const FormatException('VOLPAROSSA product unavailable');
        }
        final bytes = BytesBuilder(copy: false);
        await for (final chunk in response.stream) {
          if (bytes.length + chunk.length > maxProviderBytes) {
            throw const FormatException('VOLPAROSSA product too large');
          }
          bytes.add(chunk);
        }
        return NativeProduct.parse(
          jsonDecode(utf8.decode(bytes.takeBytes())),
          airQuality: airQuality,
          now: clock().toUtc(),
        );
      })().timeout(const Duration(seconds: 20));
    } finally {
      client.close();
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
