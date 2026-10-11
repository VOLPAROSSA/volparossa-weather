# Overmorrow shared provider integration

The pinned Overmorrow Flutter app consumes the same VOLPAROSSA weather and
air-quality provider as Drizz.li. It uses the existing app provider dispatcher,
phone/tablet layouts, forecast view and air-quality detail route—not a separate
demonstration page. Peer discovery, retrieval and source acquisition stay in the
shared core/provider layer.

## Verified scope

The release web build succeeds with Flutter 3.38.5 and the unchanged upstream
dependency lock. Twenty-three Flutter tests pass with synthetic products: native times
and accumulation windows, missing versus zero values, independent weather/AQ
failures, expiry while idle, phone/tablet layouts and the existing detail route.
The local HTTP profile passes thirty-four focused bridge tests; thirteen build
driver and twelve deployment tests cover its workspace boundaries.
Seven of the Flutter tests cover slow retrieval, exact bounded busy retries,
request/body cancellation and rejection of late results. Twenty additional
core-process adapter tests include preservation of an unconfirmed-cleanup error
when removing temporary output also fails.

A bounded, isolated Firefox trial now passes against the actual CanvasKit UI and
local HTTP bridge, using synthetic weather and particulate products. It verifies
native timelines and values, missing current observations/AQI, the configured area
and source attribution. Nine real pointer refreshes each request one weather and
one air-quality product. Independent failures and stale responses preserve the
other valid product; idle expiry hides old values without a new request. The
existing air-quality detail page opens without another fetch.

The refresh control is disabled while the app is loading, so it no longer offers
a refresh that the busy app would ignore. Twelve browser-harness tests and four
fixture tests pass separately. The browser loads only same-origin resources;
browser and fixture processes exit, the private profile is removed and the host
network namespace is unchanged.

The [build record](build-verification.json) identifies the pinned inputs, assets
and browser evidence. Core-to-Overmorrow delivery and Android/iOS packaging remain
unverified. This synthetic browser proof establishes neither forecast accuracy
nor mobile execution; background lifecycle and native home-screen widgets remain
open.

## Joined core delivery trial

The core's version-three Weather bundle selects this actual Overmorrow client,
the production HTTP bridge and the existing protected peer-delivery path. It
acquires weather and particulate products separately, publishes both, removes
the original publisher inputs and retrieves each product through the core before
opening the UI. Drizz.li's earlier bundle profiles remain unchanged.

The [preparer](prepare_core_browser.mjs) binds the raw products and cold-transfer
receipts to expected native values. The [browser driver](smoke_core_browser.py)
checks ordered Flutter table rows and cells, source metadata and a real pointer
refresh. It distinguishes missing values from zero, preserves precipitation
windows and keeps weather and particulate timelines separate. Three Node tests
and ten Python tests pass; CI includes their pinned Browser helper sources.

The joined Overmorrow trial has not yet run. These component checks do not prove
live table extraction or core-to-client delivery. Even a successful joined trial
would prove a prior cold core transfer followed by UI use of those publications,
not that opening the browser initiated the first cold fetch. The retained
synthetic browser result and historical origin results keep their original scope.

## Data and privacy

`--dart-define=VOLPAROSSA_WEATHER=true` selects the shared provider. The web client
sequentially requests `/api/volparossa/forecast` and `/api/volparossa/air-quality`
from its own loopback origin. Requests cannot choose a location, model, publisher,
file or command. The configured public-community area is displayed explicitly.
Weather and particulates retain separate runs, sample times and expiry.

Each product has one 195-second deadline, including up to two seconds for local
cancellation. This accommodates the bridge's 180-second retrieval deadline and
185-second socket bound; cold retrieval no longer fails after twenty seconds.
Cancellation aborts the request and response body. A late result cannot replace
the unavailable state or start another attempt.

Only the local bridge's exact `429 FORECAST_BUSY` response with `Retry-After: 1`
permits a retry: at most five one-second waits, all within the original product
deadline. There is no request queue, renewed deadline or retry of other errors.
The next request must pass the bridge's single-operation admission check; waiting
alone does not prove cleanup finished. Unconfirmed core-process cleanup blocks
further retrieval in that bridge instance and prevents a successful shutdown
report. Weather and air quality keep independent results.

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

For a stage using an already populated workspace dependency cache, replace
`--action dependencies` with `--action dependencies-offline` to resolve the same
lockfile without network access.

Only the explicit `dependencies` action has Internet access. Build/test execution uses
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
