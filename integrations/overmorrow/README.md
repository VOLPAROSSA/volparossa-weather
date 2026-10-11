# Overmorrow shared provider integration

The pinned Overmorrow Flutter app consumes the same VOLPAROSSA weather and
air-quality provider as Drizz.li. It uses the existing app provider dispatcher,
phone/tablet layouts, forecast view and air-quality detail route—not a separate
demonstration page. Peer discovery, retrieval and source acquisition stay in the
shared core/provider layer.

## Verified scope

The release web build succeeds with Flutter 3.38.5 and the unchanged upstream
dependency lock. Fifteen Flutter tests pass with synthetic products: native times
and accumulation windows, missing versus zero values, independent weather/AQ
failures, expiry while idle, phone/tablet layouts and the existing detail route.
The local HTTP profile passes thirty-one focused bridge tests; thirteen build
driver and twelve deployment tests cover its workspace boundaries.

The [build record](build-verification.json) identifies the pinned inputs and
produced assets. Actual browser interaction, core-to-Overmorrow delivery and
Android/iOS packaging remain unverified. The web build is not mobile execution
evidence; background lifecycle and native home-screen widgets remain open.

The first bounded Firefox trial to reach the actual CanvasKit UI verifies initial
rendering through the local bridge: independent native timelines, values, missing
current observations/AQI, the configured area and attribution. The trial then
times out during refresh and remains failed. It does not yet distinguish click
dispatch, request handling or UI completion as the cause. Browser and fixture
processes exit, the private profile is removed and the host network namespace is
unchanged. Five harness checks and four synthetic-fixture checks pass separately;
they do not establish successful refresh, failure handling or idle expiry in the
browser.

## Data and privacy

`--dart-define=VOLPAROSSA_WEATHER=true` selects the shared provider. The web client
sequentially requests `/api/volparossa/forecast` and `/api/volparossa/air-quality`
from its own loopback origin. Requests cannot choose a location, model, publisher,
file or command. The configured public-community area is displayed explicitly.
Weather and particulates retain separate runs, sample times and expiry.

Missing observations, daily forecasts, radar, UV and air-quality indices are not
invented. Accumulated rain is not hourly rain. A failed product does not erase an
independently valid other product or trigger Open-Meteo. Geolocation, location
search, external imagery/fonts and ordinary background/widget provider fallbacks
are disabled in this profile. Private location tracking is not introduced.

## Reproduce the build

Use Linux with Python 3, Git, bubblewrap, taskset and an existing Node.js 22+.
Place a verified Flutter SDK in this repository's `build/flutter` directory.
The [pin](upstream.json) records its official archive checksum, exact SDK and
upstream commits, license, dependency lock and patch checksum. The build driver
also verifies the archived Dart executable and Flutter tool snapshot. It never
downloads or globally installs an SDK.

From the repository root:

```sh
python3 integrations/overmorrow/stage.py \
  --destination "$PWD/build/overmorrow-01" --execute

python3 integrations/overmorrow/build.py \
  --sdk "$PWD/build/flutter" --stage "$PWD/build/overmorrow-01" \
  --work "$PWD/build/overmorrow-tools" --action dependencies --execute

mkdir -p build/overmorrow-01/test/volparossa/fixtures
node integrations/overmorrow/test-fixtures.mjs \
  build/overmorrow-01/test/volparossa/fixtures/products.json

for action in test build; do
  python3 integrations/overmorrow/build.py \
    --sdk "$PWD/build/flutter" --stage "$PWD/build/overmorrow-01" \
    --work "$PWD/build/overmorrow-tools" --action "$action" --execute
done

python3 integrations/overmorrow/deploy.py \
  --stage "$PWD/build/overmorrow-01" \
  --destination "$PWD/build/overmorrow-web-01" --execute
```

Only locked dependency acquisition has Internet access. Build/test execution uses
an isolated network namespace, private workspace caches, two available CPUs and
suppressed analytics. The developer's real home/configuration is not mounted.
Stages and deployment destinations must be new, dedicated build directories;
failed outputs are retained for inspection instead of overwritten.

Serve the deployment directory through `scripts/serve-provider.mjs` with
`--static-profile flutter-canvaskit` and an existing private provider configuration.
This explicit profile permits local WebAssembly and required asset types, while
retaining the original 8 MiB asset/32 MiB total limits, loopback binding, fixed
products, origin checks and prohibition on workers/external resource origins.
The default Drizz.li profile is unchanged.

The deployment keeps both CanvasKit variants, all application assets and notices.
Unused Skwasm renderers, debug symbols and inactive service workers are omitted
from the copied tree; the original build output is preserved. Upstream Overmorrow
remains GPL-3.0-or-later. Original VOLPAROSSA integration files are GPL-3.0-only;
both licenses and dependency notices accompany the deployment.
