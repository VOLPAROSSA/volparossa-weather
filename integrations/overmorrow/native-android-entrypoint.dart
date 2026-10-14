// SPDX-License-Identifier: GPL-3.0-only
// TEST ONLY. Run the real app; expose bounded READ-ONLY observations on its
// debug VM service. Input/taps/lifecycle changes must come from Android itself.
import 'dart:convert';
import 'dart:developer';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'main.dart' as app;
import 'volparossa/profile.dart';
import 'volparossa/provider.dart';
import 'volparossa/views.dart';

class _Lifecycle extends WidgetsBindingObserver {
  final List<String> observed = [];
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    observed.add(state.name);
    if (observed.length > 16) observed.removeAt(0);
  }
}

String _text(Widget widget) {
  if (widget is! Text || widget.data == null || widget.data!.length > 1024) {
    throw const FormatException('Unexpected table text');
  }
  return widget.data!;
}

Map<String, Object?> _snapshot(_Lifecycle lifecycle) {
  final tables = <Map<String, Object?>>[];
  final labels = <String>[];
  final refresh = <Map<String, Object?>>[];
  var homes = 0;
  app.MyHomePageState? home;
  var weatherView = false, airQualityView = false, frameworkError = false;
  var visited = 0;
  final root = WidgetsBinding.instance.rootElement;
  if (root == null) throw const FormatException('No mounted app');
  final view = WidgetsBinding.instance.platformDispatcher.views.single;
  // Flutter hit testing cannot see Android system-window interception. These
  // are actual physical view metrics, not guessed navigation-bar dimensions.
  final physical = view.physicalSize;
  final padding = view.viewPadding, insets = view.viewInsets;
  final safeLeft = math.max(padding.left, insets.left);
  final safeTop = math.max(padding.top, insets.top);
  final safeRight = physical.width - math.max(padding.right, insets.right);
  final safeBottom = physical.height - math.max(padding.bottom, insets.bottom);
  final hasSafeArea = [safeLeft, safeTop, safeRight, safeBottom].every((v) => v.isFinite) &&
      safeLeft >= 0 && safeTop >= 0 && safeRight <= physical.width && safeBottom <= physical.height &&
      safeLeft < safeRight && safeTop < safeBottom;
  void visit(Element element) {
    if (++visited > 25000) throw const FormatException('Widget traversal bound');
    final widget = element.widget;
    if (element is StatefulElement && element.state is app.MyHomePageState) {
      homes++;
      home = element.state as app.MyHomePageState;
    }
    if (widget is NativeProductView) {
      if (widget.airQuality) {
        airQualityView = true;
      } else {
        weatherView = true;
      }
    }
    if (widget is ErrorWidget) frameworkError = true;
    if (widget is Text && widget.data != null) {
      final text = widget.data!;
      if (text.length > 1024 || labels.length >= 2048) {
        throw const FormatException('Text observation bound');
      }
      labels.add(text);
    }
    if (widget is DataTable) {
      if (tables.length >= 4 || widget.columns.length > 8 || widget.rows.length > 16) {
        throw const FormatException('Table observation bound');
      }
      bool? quality;
      element.visitAncestorElements((ancestor) {
        if (ancestor.widget is NativeProductView) {
          quality = (ancestor.widget as NativeProductView).airQuality;
          return false;
        }
        return true;
      });
      if (quality == null) throw const FormatException('Unknown native table owner');
      tables.add({
        'product': quality! ? 'air_quality' : 'weather',
        'headers': widget.columns.map((column) => _text(column.label)).toList(),
        'rows': widget.rows.map((row) => row.cells.map((cell) => _text(cell.child)).toList()).toList(),
      });
    }
    if (widget is FilledButton) {
      var isRefresh = false;
      void buttonText(Element child) {
        if (child.widget is Text && (child.widget as Text).data == 'Refresh forecasts') isRefresh = true;
        child.visitChildren(buttonText);
      }
      element.visitChildren(buttonText);
      if (isRefresh) {
        final box = element.findRenderObject();
        if (box is RenderBox && box.attached && box.hasSize) {
          final topLeft = box.localToGlobal(Offset.zero);
          final center = box.localToGlobal(box.size.center(Offset.zero));
          final scale = view.devicePixelRatio;
          final tapX = (center.dx * scale).roundToDouble();
          final tapY = (center.dy * scale).roundToDouble();
          final safeTarget = hasSafeArea && topLeft.dx * scale >= safeLeft && topLeft.dy * scale >= safeTop &&
              (topLeft.dx + box.size.width) * scale <= safeRight &&
              (topLeft.dy + box.size.height) * scale <= safeBottom &&
              tapX > safeLeft && tapX < safeRight && tapY > safeTop && tapY < safeBottom;
          final hit = HitTestResult();
          WidgetsBinding.instance.hitTestInView(hit, center, view.viewId);
          final hitTestable = hit.path.any((entry) {
            Object? target = entry.target;
            while (target is RenderObject) {
              if (identical(target, box)) return true;
              target = target.parent;
            }
            return false;
          });
          // A child can be hit-testable while a bouncing ScrollPosition is
          // settling. Read every enclosing position; never stop or move it.
          var scrollAncestors = 0, ancestorsVisited = 0;
          var scrollIdle = true;
          element.visitAncestorElements((ancestor) {
            if (++ancestorsVisited > 256) throw const FormatException('Ancestor observation bound');
            if (ancestor is StatefulElement && ancestor.state is ScrollableState) {
              if (++scrollAncestors > 16) throw const FormatException('Scroll observation bound');
              final position = (ancestor.state as ScrollableState).position;
              scrollIdle = scrollIdle && position.hasPixels && position.hasContentDimensions &&
                  !position.isScrollingNotifier.value;
            }
            return true;
          });
          refresh.add({
            'enabled': widget.onPressed != null,
            'hit_testable': hitTestable,
            'safe_target': safeTarget,
            'x': center.dx * scale, 'y': center.dy * scale,
            'visible': topLeft.dx >= 0 && topLeft.dy >= 0 &&
                (topLeft.dx + box.size.width) * scale <= physical.width &&
                (topLeft.dy + box.size.height) * scale <= physical.height,
            'scroll': {'ancestors': scrollAncestors, 'idle': scrollAncestors == 0 ? null : scrollIdle},
          });
        }
      }
    }
    element.visitChildren(visit);
  }
  visit(root);
  if (refresh.length > 1) throw const FormatException('Duplicate refresh button');
  // Observe existing state only. Neither parsing success nor a mounted widget
  // is a substitute for the driver's exact native rows/lifecycle acceptance.
  final state = homes == 1 ? home : null;
  return {
    'schema': 3, 'kind': 'overmorrow-native-mounted-ui',
    'package': 'org.volparossa.weather.trial', 'platform': 'android',
    'profile': volparossaProfile, 'origin': volparossaNativeOrigin,
    'tables': tables, 'labels': labels, 'refresh': refresh,
    'lifecycle': lifecycle.observed,
    'current_lifecycle': WidgetsBinding.instance.lifecycleState?.name,
    'screen': {'width': physical.width, 'height': physical.height,
      'safe_area': hasSafeArea ? {'left': safeLeft, 'top': safeTop, 'right': safeRight, 'bottom': safeBottom} : null},
    'diagnostic': {
      'schema': 1, 'provider': providerObservation(),
      'app': {
        'home': homes == 0 ? 'absent' : homes == 1 ? 'single' : 'multiple',
        'loading': state?.isLoading,
        'has_data': state == null ? null : state.data != null,
        'has_error': state == null ? null : state.weatherError != null,
        'has_weather': state == null ? null : state.data?.nativeProducts?.weather != null,
        'has_air_quality': state == null ? null : state.data?.nativeProducts?.airQuality != null,
        'weather_view_mounted': weatherView,
        'air_quality_view_mounted': airQualityView,
        'framework_error_mounted': frameworkError,
      },
    },
  };
}

Future<void> main() async {
  if (!kDebugMode || kIsWeb || !Platform.isAndroid || !volparossaProfile ||
      volparossaNativeOrigin != 'http://127.0.0.1:43210') {
    throw StateError('This entrypoint is only for the isolated Android debug trial');
  }
  WidgetsFlutterBinding.ensureInitialized();
  final lifecycle = _Lifecycle();
  WidgetsBinding.instance.addObserver(lifecycle);
  registerExtension('ext.volparossa.native_snapshot', (method, parameters) async {
    // The VM supplies isolateId. No parameter may command or alter the app.
    if (parameters.keys.any((key) => key != 'isolateId')) {
      return ServiceExtensionResponse.error(ServiceExtensionResponse.invalidParams, 'No commands accepted');
    }
    try {
      final result = jsonEncode(_snapshot(lifecycle));
      if (result.length > 65536) throw const FormatException('Snapshot bound');
      return ServiceExtensionResponse.result(result);
    } catch (_) {
      return ServiceExtensionResponse.error(ServiceExtensionResponse.extensionError, 'Snapshot not ready');
    }
  });
  await app.main();
}
