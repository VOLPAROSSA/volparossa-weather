{{flutter_js}}
{{flutter_build_config}}
// Self-host the pinned CanvasKit assets. No Google CDN or service worker.
_flutter.loader.load({config: {renderer: 'canvaskit', canvasKitBaseUrl: 'canvaskit/'}});
