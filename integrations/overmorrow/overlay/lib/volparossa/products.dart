// SPDX-License-Identifier: GPL-3.0-only
import 'dart:convert';
import 'dart:math' as math;

typedef JsonObject = Map<String, dynamic>;

enum ProductClockRejection { futureAcquired, expired }

// A closed first-failed freshness predicate, not payload/error text or a new
// clock authority. Still a FormatException with the same public message.
class ProductClockException extends FormatException {
  final ProductClockRejection reason;
  const ProductClockException(this.reason)
    : super('Invalid VOLPAROSSA product');
}

void requireProduct(bool condition) {
  if (!condition) throw const FormatException('Invalid VOLPAROSSA product');
}

JsonObject object(dynamic value) {
  requireProduct(value is Map<String, dynamic>);
  return value as JsonObject;
}

DateTime utc(dynamic value) {
  requireProduct(
    value is String &&
        RegExp(
          r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$',
        ).hasMatch(value),
  );
  final result = DateTime.parse(value as String);
  requireProduct(result.toUtc().toIso8601String() == value);
  return result;
}

String boundedText(dynamic value) {
  requireProduct(
    value is String &&
        value.isNotEmpty &&
        value.length <= 400 &&
        !RegExp(r'[\x00-\x1f\x7f]').hasMatch(value),
  );
  return value as String;
}

bool same(dynamic a, dynamic b) => jsonEncode(a) == jsonEncode(b);

/// Missing values stay null. Native samples are not observations, daily extrema,
/// interpolated hours, precipitation rates or a synthetic air-quality index.
class NativeSample {
  final DateTime validAt;
  final int leadHours;
  final Map<String, num?> values;
  final DateTime? accumulationStart;
  final DateTime? accumulationEnd;
  NativeSample(
    this.validAt,
    this.leadHours,
    this.values,
    this.accumulationStart,
    this.accumulationEnd,
  );
}

class NativeProduct {
  final bool airQuality;
  final double latitude, longitude;
  final String model, attribution, license, licenseUrl, changes;
  final DateTime modelRun, acquiredAt, expiresAt;
  final List<NativeSample> samples;
  NativeProduct._(
    this.airQuality,
    this.latitude,
    this.longitude,
    this.model,
    this.attribution,
    this.license,
    this.licenseUrl,
    this.changes,
    this.modelRun,
    this.acquiredAt,
    this.expiresAt,
    this.samples,
  );

  bool staleAt(DateTime now) =>
      now.isBefore(acquiredAt) || !now.isBefore(expiresAt);
  String get areaLabel => 'Public community area: $latitude, $longitude';

  factory NativeProduct.parse(
    dynamic input, {
    required bool airQuality,
    required DateTime now,
  }) {
    final value = object(input);
    requireProduct(
      value['schema'] ==
              (airQuality
                  ? 'volparossa.air-quality.provider.v1'
                  : 'volparossa.weather.provider.v1') &&
          value['kind'] == 'forecast' &&
          value['verification_scope'] == 'forecast-schema-and-freshness-only',
    );
    final delivery = object(value['delivery']);
    final freshness = object(value['freshness']);
    requireProduct(
      delivery['mode'] == 'core-cache' &&
          delivery['upstream_origin_attested'] == false &&
          delivery['manifest_media_type_checked'] == false &&
          freshness['publication_expires_at'] ==
              delivery['publication_expires_at'],
    );
    final original = object(value['forecast']);
    requireProduct(
      original['schema'] ==
              (airQuality
                  ? 'volparossa.air-quality.forecast.v1'
                  : 'volparossa.forecast.v1') &&
          original['kind'] == 'forecast',
    );
    final area = object(original['area']);
    final lat = area['latitude'], lon = area['longitude'];
    requireProduct(
      area['sharing'] == 'public-community' &&
          lat is num &&
          lon is num &&
          lat.isFinite &&
          lon.isFinite &&
          lat >= -90 &&
          lat <= 90 &&
          lon >= -180 &&
          lon <= 180,
    );
    final source = object(original['source']);
    final model = boundedText(source['model']);
    final attribution = boundedText(source['attribution']);
    final license = boundedText(source['license']);
    final licenseUrl = boundedText(source['license_url']);
    final changes = boundedText(source['changes']);
    requireProduct(source['acquisition'] == 'origin-https');
    requireProduct(
      airQuality
          ? source['provider'] == 'noaa' &&
                model == 'gefs-aerosols' &&
                license == 'LicenseRef-NOAA-NODD' &&
                licenseUrl == 'https://registry.opendata.aws/noaa-gefs/'
          : source['provider'] == 'ecmwf' &&
                ['ifs', 'aifs-single'].contains(model) &&
                license == 'CC-BY-4.0' &&
                licenseUrl == 'https://creativecommons.org/licenses/by/4.0/',
    );
    final run = utc(source['model_run_at']),
        acquired = utc(source['acquired_at']);
    final originalExpiry = utc(object(original['freshness'])['expires_at']);
    final publicationExpiry = utc(delivery['publication_expires_at']);
    final expires = originalExpiry.isBefore(publicationExpiry)
        ? originalExpiry
        : publicationExpiry;
    requireProduct(
      !acquired.isBefore(run) &&
          acquired.difference(run).inSeconds < 72 * 3600 &&
          originalExpiry.isAfter(acquired) &&
          originalExpiry.difference(acquired).inMilliseconds <= 1800000 &&
          !originalExpiry.isAfter(run.add(const Duration(hours: 72))) &&
          utc(freshness['expires_at']) == expires,
    );
    // Preserve the original conjunction's order and strict boundaries.
    if (now.isBefore(acquired)) {
      throw const ProductClockException(ProductClockRejection.futureAcquired);
    }
    if (!now.isBefore(expires)) {
      throw const ProductClockException(ProductClockRejection.expired);
    }
    requireProduct(freshness['stale'] == false);
    final units = object(original['units']);
    final implemented = airQuality
        ? <String, String>{'pm2_5': 'ug/m3', 'pm10': 'ug/m3'}
        : <String, String>{
            'temperature_2m': 'degC',
            'wind_speed_10m': 'm/s',
            'wind_direction_10m': 'degree',
            'precipitation': 'mm',
          };
    final available = implemented.keys
        .where(
          (key) =>
              airQuality ||
              key == 'temperature_2m' ||
              units.containsKey(
                key == 'precipitation' ? 'precipitation' : 'wind_10m',
              ),
        )
        .toList();
    requireProduct(
      airQuality
          ? units['pm2_5'] == 'ug/m3' && units['pm10'] == 'ug/m3'
          : units['temperature_2m'] == 'degC' &&
                (!units.containsKey('wind_10m') ||
                    units['wind_10m'] == 'm/s' &&
                        units['wind_direction_10m'] == 'degree') &&
                (!units.containsKey('precipitation') ||
                    units['precipitation'] == 'mm'),
    );
    final capabilities = object(value['capabilities']);
    requireProduct(
      same(capabilities['implemented_variables'], implemented.keys.toList()) &&
          same(capabilities['available_variables'], available) &&
          capabilities['time_axis'] == 'native-model-valid-times' &&
          capabilities['interpolation'] == false &&
          capabilities['current_observations'] == false &&
          capabilities['trained_corrections'] == false,
    );
    final rawSamples = original['samples'];
    requireProduct(
      rawSamples is List && rawSamples.isNotEmpty && rawSamples.length <= 16,
    );
    final timeline = object(value['timeline']);
    requireProduct(
      timeline['time_zone'] == 'UTC' &&
          same(
            timeline['valid_at'],
            rawSamples.map((s) => object(s)['valid_at']).toList(),
          ) &&
          same(
            timeline['lead_hours'],
            rawSamples.map((s) => object(s)['lead_hours']).toList(),
          ),
    );
    final series = value['series'];
    requireProduct(series is List && series.isNotEmpty && series.length <= 16);
    final fields = <String, JsonObject>{};
    for (final raw in series) {
      final field = object(raw), name = boundedText(object(raw)['variable']);
      requireProduct(!fields.containsKey(name));
      fields[name] = field;
      if (!available.contains(name)) {
        requireProduct(
          field['availability'] == 'unavailable' &&
              field['values'] == null &&
              field['unit'] == null &&
              field['value_status'] == null,
        );
      } else {
        requireProduct(
          field['availability'] == 'supported' &&
              field['unit'] == implemented[name] &&
              field['values'] is List &&
              field['values'].length == rawSamples.length &&
              field['value_status'] is List &&
              field['value_status'].length == rawSamples.length,
        );
      }
    }
    int previous = -1;
    final samples = <NativeSample>[];
    for (var i = 0; i < rawSamples.length; i++) {
      final sample = object(rawSamples[i]),
          lead = object(rawSamples[i])['lead_hours'];
      requireProduct(
        lead is int &&
            lead > previous &&
            lead <= (airQuality ? 120 : 360) &&
            (!airQuality || lead % 3 == 0),
      );
      previous = lead;
      final valid = utc(sample['valid_at']);
      requireProduct(valid == run.add(Duration(hours: lead)));
      final grid = object(sample['grid']);
      requireProduct(
        grid['method'] == 'nearest-grid-no-interpolation' &&
            grid['distance_km'] is num &&
            grid['distance_km'] >= 0 &&
            grid['distance_km'] <= 50,
      );
      final values = <String, num?>{};
      DateTime? start, end;
      for (final name in implemented.keys) {
        final field = fields[name];
        if (field == null || field['availability'] != 'supported') {
          values[name] = null;
          continue;
        }
        dynamic originalValue;
        String status;
        if (name.startsWith('wind_')) {
          final wind = object(sample['wind_10m']);
          originalValue =
              wind[name == 'wind_speed_10m' ? 'speed' : 'direction_from'];
          status = wind['status'] as String;
          final u = wind['eastward'], v = wind['northward'];
          if (u == null || v == null) {
            requireProduct(
              status == 'missing' &&
                  wind['speed'] == null &&
                  wind['direction_from'] == null,
            );
          } else {
            requireProduct(u is num && v is num && u.isFinite && v.isFinite);
            final speed = math.sqrt(u * u + v * v);
            final direction =
                ((180 +
                            math.atan2(u.toDouble(), v.toDouble()) *
                                180 /
                                math.pi) %
                        360 +
                    360) %
                360;
            requireProduct(
              wind['speed'] is num &&
                  (wind['speed'] - speed).abs() <= 1e-10 * math.max(1, speed) &&
                  (speed == 0
                      ? status == 'calm' && wind['direction_from'] == null
                      : status == 'available' &&
                            wind['direction_from'] is num &&
                            (wind['direction_from'] - direction).abs() <=
                                1e-10),
            );
          }
        } else if (name == 'precipitation') {
          final rain = object(sample['precipitation']);
          originalValue = rain['amount'];
          start = utc(rain['start_at']);
          end = utc(rain['end_at']);
          requireProduct(
            rain['start_lead_hours'] is int &&
                rain['start_lead_hours'] >= 0 &&
                rain['end_lead_hours'] == lead &&
                !start.isBefore(run) &&
                !start.isAfter(end) &&
                start == run.add(Duration(hours: rain['start_lead_hours'])) &&
                end == valid &&
                field['statistic'] == 'accumulation' &&
                field['accumulation_windows'] is List &&
                field['accumulation_windows'].length == rawSamples.length &&
                field['accumulation_windows'][i]['start_at'] ==
                    rain['start_at'] &&
                field['accumulation_windows'][i]['end_at'] == rain['end_at'],
          );
          requireProduct(
            originalValue ==
                (rain['source_value'] == null
                    ? null
                    : rain['source_value'] * (model == 'ifs' ? 1000 : 1)),
          );
          status = originalValue == null ? 'missing' : 'available';
        } else {
          originalValue = sample[name];
          status = originalValue == null ? 'missing' : 'available';
          if (airQuality) requireProduct(field['statistic'] == 'instant');
        }
        requireProduct(
          originalValue == null ||
              originalValue is num &&
                  originalValue.isFinite &&
                  (name == 'temperature_2m'
                      ? originalValue >= -273.15
                      : originalValue >= 0),
        );
        requireProduct(
          field['values'][i] == originalValue &&
              field['value_status'][i] == status,
        );
        values[name] = originalValue as num?;
      }
      samples.add(
        NativeSample(valid, lead, Map.unmodifiable(values), start, end),
      );
    }
    return NativeProduct._(
      airQuality,
      lat.toDouble(),
      lon.toDouble(),
      model,
      attribution,
      license,
      licenseUrl,
      changes,
      run,
      acquired,
      expires,
      List.unmodifiable(samples),
    );
  }
}

class NativeProducts {
  final NativeProduct? weather, airQuality;
  final String? weatherError, airQualityError;
  NativeProducts(
    this.weather,
    this.airQuality,
    this.weatherError,
    this.airQualityError,
  ) {
    if (weather != null && airQuality != null)
      requireProduct(
        weather!.latitude == airQuality!.latitude &&
            weather!.longitude == airQuality!.longitude,
      );
  }
  NativeProduct? get areaSource => weather ?? airQuality;
}
