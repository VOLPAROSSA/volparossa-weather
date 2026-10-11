// SPDX-License-Identifier: GPL-3.0-only
import 'dart:async';
import 'package:flutter/material.dart';
import 'products.dart';

class MissingCapability extends StatelessWidget {
  final String name;
  const MissingCapability(this.name, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(16),
    child: Text('$name: not available from this provider'),
  );
}

class NativeCurrentHeader extends StatelessWidget {
  final Color? color;
  const NativeCurrentHeader({super.key, this.color});
  @override
  Widget build(BuildContext context) => DefaultTextStyle.merge(
    style: TextStyle(color: color),
    child: const Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('VOLPAROSSA', style: TextStyle(fontSize: 28)),
        Text('Current observations: not available'),
        Text('Source-native forecasts below; no interpolation'),
      ],
    ),
  );
}

/// Used within the existing hourly forecast, AQ card and AQ detail surfaces.
/// A timer changes only display freshness; it performs no background networking.
class NativeProductView extends StatefulWidget {
  final NativeProduct? product;
  final String? error;
  final bool airQuality;
  final DateTime Function()? clock;
  const NativeProductView({
    super.key,
    required this.product,
    required this.error,
    this.airQuality = false,
    this.clock,
  });
  @override
  State<NativeProductView> createState() => _NativeProductViewState();
}

class _NativeProductViewState extends State<NativeProductView>
    with WidgetsBindingObserver {
  Timer? timer;
  DateTime get now => (widget.clock?.call() ?? DateTime.now()).toUtc();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    schedule();
  }

  @override
  void didUpdateWidget(covariant NativeProductView oldWidget) {
    super.didUpdateWidget(oldWidget);
    schedule();
  }

  void schedule() {
    timer?.cancel();
    final expiry = widget.product?.expiresAt;
    if (expiry != null) {
      final delay = expiry.difference(now);
      if (delay > Duration.zero)
        timer = Timer(delay + const Duration(milliseconds: 1), () {
          if (mounted) setState(() {});
        });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && mounted) {
      setState(() {});
      schedule();
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final title = widget.airQuality
        ? 'Native particulate forecast'
        : 'Native weather forecast';
    final expired = p != null && p.staleAt(now);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          if (p == null) Text(widget.error ?? 'Not available'),
          if (p != null) ...[
            Text(p.areaLabel),
            Text('Model ${p.model}; run ${p.modelRun.toIso8601String()}'),
            Text('Acquired ${p.acquiredAt.toIso8601String()}'),
            Text('Expires ${p.expiresAt.toIso8601String()}'),
            if (expired)
              const Text('Expired — refresh required; values are hidden'),
            if (!expired)
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: [
                    const DataColumn(label: Text('Native valid time (UTC)')),
                    ...(widget.airQuality
                            ? ['PM2.5 (µg/m³)', 'PM10 (µg/m³)']
                            : [
                                'Temperature (°C)',
                                'Wind (m/s)',
                                'Wind from (°)',
                                'Precipitation (mm)',
                                'Accumulation window (UTC)',
                              ])
                        .map((s) => DataColumn(label: Text(s))),
                  ],
                  rows: p.samples
                      .map(
                        (sample) => DataRow(
                          cells: [
                            DataCell(Text(sample.validAt.toIso8601String())),
                            ...(widget.airQuality
                                    ? ['pm2_5', 'pm10']
                                    : [
                                        'temperature_2m',
                                        'wind_speed_10m',
                                        'wind_direction_10m',
                                        'precipitation',
                                      ])
                                .map(
                                  (key) => DataCell(
                                    Text(
                                      sample.values[key]?.toString() ??
                                          'Not available',
                                    ),
                                  ),
                                ),
                            if (!widget.airQuality)
                              DataCell(
                                Text(
                                  sample.accumulationStart == null
                                      ? 'Not available'
                                      : '${sample.accumulationStart!.toIso8601String()} → ${sample.accumulationEnd!.toIso8601String()}',
                                ),
                              ),
                          ],
                        ),
                      )
                      .toList(),
                ),
              ),
            Text(p.attribution),
            Text('${p.license}: ${p.licenseUrl}'),
            Text(p.changes),
            const Text(
              'Core-cache delivery; schema and freshness checked. Origin authenticity is not attested.',
            ),
          ],
          Text(
            widget.airQuality
                ? 'AQI, pollen and health advice: not available'
                : 'Current observations, daily totals/extrema, UV, humidity and hourly interpolation: not available',
          ),
        ],
      ),
    );
  }
}
