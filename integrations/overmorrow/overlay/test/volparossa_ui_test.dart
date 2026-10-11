// SPDX-License-Identifier: GPL-3.0-only
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:overmorrow/decoders/weather_data.dart';
import 'package:overmorrow/hourly.dart';
import 'package:overmorrow/new_displays.dart';
import 'package:overmorrow/main_ui.dart';
import 'package:overmorrow/main_screens.dart';
import 'package:overmorrow/services/preferences_service.dart';
import 'package:overmorrow/l10n/app_localizations.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:overmorrow/volparossa/products.dart';
import 'package:overmorrow/volparossa/provider.dart';
import 'package:overmorrow/volparossa/views.dart';

void main() {
  late final WeatherData Function() data;
  setUpAll(() async {
    SharedPreferences.setMockInitialValues({});
    await PreferenceUtils.init();
  });
  for (final width in [390.0, 900.0]) {
    testWidgets(
      'existing responsive main layout at width $width exposes refresh readiness',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final d = data();
        Widget app(bool isLoading) => MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => SettingsProvider()),
            ChangeNotifierProvider(create: (_) => ThemeProvider()),
          ],
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: NewMain(
              data: d,
              updateLocation: (String _, String __) async {},
              imageService: null,
              isLoading: isLoading,
            ),
          ),
        );
        await tester.pumpWidget(app(true));
        await tester.pump();
        expect(find.byType(NewHourly), findsOneWidget);
        expect(find.byType(AqiWidget), findsOneWidget);
        expect(
          find.text('Current observations: not available'),
          findsOneWidget,
        );
        final refresh = find.widgetWithText(FilledButton, 'Refresh forecasts');
        if (width < 680) {
          // The existing phone layout lazily builds its footer. Exercise the
          // real vertical list rather than replacing the responsive layout.
          final verticalList = find.descendant(
            of: find.byType(PhoneLayout),
            matching: find.byWidgetPredicate(
              (widget) => widget is Scrollable &&
                  widget.axisDirection == AxisDirection.down,
            ),
          ).first;
          await tester.scrollUntilVisible(
            refresh,
            350,
            scrollable: verticalList,
            maxScrolls: 15,
          );
        }
        expect(refresh, findsOneWidget);
        expect(
          tester.widget<ProviderSelector>(find.byType(ProviderSelector)).isLoading,
          true,
        );
        expect(tester.widget<FilledButton>(refresh).onPressed, null);
        await tester.pumpWidget(app(false));
        await tester.pump();
        expect(
          tester.widget<ProviderSelector>(find.byType(ProviderSelector)).isLoading,
          false,
        );
        expect(tester.widget<FilledButton>(refresh).onPressed, isNotNull);
        expect(tester.takeException(), null);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
  testWidgets(
    'actual provider selector disables repeat input during a delayed native product pair',
    (tester) async {
      final fixture = jsonDecode(
        File('test/volparossa/fixtures/products.json').readAsStringSync(),
      );
      final weatherReply = Completer<http.Response>();
      final qualityReply = Completer<http.Response>();
      final requests = <String>[];
      final results = <NativeProducts>[];
      var loading = false;
      var callbacks = 0;
      http.Response product(bool quality) => http.Response(
        jsonEncode(fixture[quality ? 'air_quality' : 'weather']),
        200,
        headers: {'content-type': 'application/json'},
      );
      final native = NativeProviderClient(
        Uri.parse('http://127.0.0.1:43210'),
        clock: () => DateTime.parse(fixture['now']),
        createClient: () => MockClient((request) {
          expect(request.url.origin, 'http://127.0.0.1:43210');
          expect(request.url.hasQuery, false);
          expect(request.followRedirects, false);
          requests.add(request.url.path);
          if (requests.length == 1) return weatherReply.future;
          if (requests.length == 2) return qualityReply.future;
          return Future.value(
            product(request.url.path.endsWith('air-quality')),
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) => ProviderSelector(
                loc: 'Configured public area',
                latLon: '52.52, 13.41',
                isLoading: loading,
                updateLocation: (String _, String __) async {
                  callbacks++;
                  setState(() => loading = true);
                  try {
                    results.add(await native.load());
                  } finally {
                    setState(() => loading = false);
                  }
                },
              ),
            ),
          ),
        ),
      );
      final refresh = find.widgetWithText(FilledButton, 'Refresh forecasts');
      await tester.tap(refresh);
      await tester.pump();
      expect(callbacks, 1);
      expect(requests, ['/api/volparossa/forecast']);
      expect(tester.widget<FilledButton>(refresh).onPressed, null);
      await tester.tap(refresh);
      await tester.pump();
      expect(callbacks, 1);
      expect(requests, ['/api/volparossa/forecast']);

      weatherReply.complete(product(false));
      await tester.pump();
      expect(requests, [
        '/api/volparossa/forecast',
        '/api/volparossa/air-quality',
      ]);
      expect(tester.widget<FilledButton>(refresh).onPressed, null);
      await tester.tap(refresh);
      await tester.pump();
      expect(callbacks, 1);
      qualityReply.complete(product(true));
      await tester.pump();
      expect(results, hasLength(1));
      expect(results.single.weather, isNotNull);
      expect(results.single.airQuality, isNotNull);
      expect(tester.widget<FilledButton>(refresh).onPressed, isNotNull);

      await tester.tap(refresh);
      await tester.pump();
      expect(callbacks, 2);
      expect(requests, [
        '/api/volparossa/forecast',
        '/api/volparossa/air-quality',
        '/api/volparossa/forecast',
        '/api/volparossa/air-quality',
      ]);
      expect(results, hasLength(2));
      expect(tester.widget<FilledButton>(refresh).onPressed, isNotNull);
      expect(tester.takeException(), null);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'an idle visible product expires and hides values without a network request',
    (tester) async {
      final fixture = jsonDecode(
        File('test/volparossa/fixtures/products.json').readAsStringSync(),
      );
      var now = DateTime.parse(fixture['now']);
      final p = NativeProduct.parse(
        fixture['weather'],
        airQuality: false,
        now: now,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: NativeProductView(
                product: p,
                error: null,
                clock: () => now,
              ),
            ),
          ),
        ),
      );
      expect(find.byType(DataTable), findsOneWidget);
      now = p.expiresAt;
      await tester.pump(const Duration(seconds: 121));
      expect(find.byType(DataTable), findsNothing);
      expect(
        find.text('Expired — refresh required; values are hidden'),
        findsOneWidget,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  data = () {
    final fixture = jsonDecode(
      File('test/volparossa/fixtures/products.json').readAsStringSync(),
    );
    final now = DateTime.fromMillisecondsSinceEpoch(
      DateTime.now().millisecondsSinceEpoch,
      isUtc: true,
    );
    final fixtureDate = DateTime.parse(fixture['now']);
    final delta = DateTime.utc(now.year, now.month, now.day)
        .difference(
          DateTime.utc(fixtureDate.year, fixtureDate.month, fixtureDate.day),
        )
        .inMilliseconds;
    dynamic shift(dynamic v) {
      if (v is Map<String, dynamic>)
        return v.map((k, value) => MapEntry(k, shift(value)));
      if (v is List) return v.map(shift).toList();
      if (v is String && RegExp(r'^\d{4}-\d{2}-\d{2}T.*Z$').hasMatch(v)) {
        return DateTime.parse(
          v,
        ).add(Duration(milliseconds: delta)).toIso8601String();
      }
      return v;
    }

    dynamic fresh(dynamic input) {
      final v = shift(input);
      final acquired = now.subtract(const Duration(seconds: 1));
      final publicationExpiry = acquired
          .add(const Duration(seconds: 120))
          .toIso8601String();
      v['forecast']['source']['acquired_at'] = acquired.toIso8601String();
      v['forecast']['freshness']['expires_at'] = acquired
          .add(const Duration(minutes: 30))
          .toIso8601String();
      v['delivery']['publication_expires_at'] = publicationExpiry;
      v['freshness']['publication_expires_at'] = publicationExpiry;
      v['freshness']['expires_at'] = publicationExpiry;
      v['freshness']['checked_at'] = now.toIso8601String();
      v['freshness']['age_seconds'] = 1;
      v['freshness']['model_age_seconds'] = now
          .difference(DateTime.parse(v['forecast']['source']['model_run_at']))
          .inSeconds;
      return v;
    }

    final w = NativeProduct.parse(
      fresh(fixture['weather']),
      airQuality: false,
      now: now,
    );
    final a = NativeProduct.parse(
      fresh(fixture['air_quality']),
      airQuality: true,
      now: now,
    );
    return WeatherData(
      place: w.areaLabel,
      lat: w.latitude,
      lng: w.longitude,
      provider: 'volparossa',
      nativeProducts: NativeProducts(w, a, null, null),
      sunStatus: null,
      aqi: null,
      radar: null,
      days: [],
      hourly72: [],
      current: null,
      fetchDatetime: now,
      isOnline: true,
      updatedTime: w.acquiredAt,
      localTime: now,
      minutely15Precip: null,
      alerts: [],
      dailyMinMaxTemp: [],
    );
  };

  testWidgets(
    'actual hourly surface uses native times/windows rather than invented hours',
    (tester) async {
      final d = data();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: NewHourly(
                hours: d.hourly72,
                elevated: false,
                nativeProducts: d.nativeProducts,
              ),
            ),
          ),
        ),
      );
      expect(find.text('Native weather forecast'), findsOneWidget);
      for (final sample in d.nativeProducts!.weather!.samples) {
        expect(find.text(sample.validAt.toIso8601String()), findsOneWidget);
      }
      expect(find.text('Accumulation window (UTC)'), findsOneWidget);
      expect(find.text('0.01'), findsOneWidget);
      expect(
        find.textContaining('hourly interpolation: not available'),
        findsOneWidget,
      );
      expect(tester.takeException(), null);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'actual AQ card opens the existing detail route without an Open-Meteo request',
    (tester) async {
      final d = data();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: AqiWidget(data: d)),
          ),
        ),
      );
      expect(find.text('Native particulate forecast'), findsOneWidget);
      await tester.ensureVisible(find.text('Air quality details'));
      await tester.tap(find.text('Air quality details'));
      await tester.pumpAndSettle();
      expect(find.text('Air quality'), findsOneWidget);
      expect(find.byType(NativeProductView), findsOneWidget);
      expect(find.text('5.53071'), findsOneWidget);
      expect(
        find.text('AQI, pollen and health advice: not available'),
        findsOneWidget,
      );
      expect(tester.takeException(), null);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'normal current header/metrics cannot display a synthetic current observation',
    (tester) async {
      final d = data();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                TempAndConditionText(data: d, textRegionColor: null),
                Circles(data: d),
              ],
            ),
          ),
        ),
      );
      expect(find.text('Current observations: not available'), findsOneWidget);
      expect(find.textContaining('Current feels-like'), findsOneWidget);
      expect(find.byType(SmoothTempTransition), findsNothing);
      expect(tester.takeException(), null);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
