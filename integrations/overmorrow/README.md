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
and current full browser evidence. The shared harness has been rechecked after
adding the table trial: all nine pointer refreshes, independent failures, idle
expiry and cleanup pass on the current source. The earlier reports remain
unchanged.

A separate [table record](table-verification.json)
now proves exact ordered table extraction in the actual browser: four weather
rows and five particulate rows match their captured HTTP responses, both on
initial display and after a real pointer refresh. Missing values, calm zero wind,
native timestamps and precipitation windows remain distinct. Each product is
requested exactly twice; the browser uses only loopback resources and cleanup
passes. This additional trial uses synthetic products and does not replace the
full browser trial.

Core-to-Overmorrow delivery and Android/iOS packaging remain
unverified. This synthetic browser proof establishes neither forecast accuracy
nor mobile execution; background lifecycle and native home-screen widgets remain
open.

## Hosted build and browser trials

The [hosted workflow](../../.github/workflows/hosted-overmorrow.yml) prepares a
public, source-bound Overmorrow build for the next core integration trial. It
keeps the existing local results above unchanged. The new hosted sequence is not
verified until its build, both browser trials and cleanup have passed.

The workflow uses the same pinned Flutter 3.38.5 archive and upstream dependency
lock. SDK acquisition is explicit and verifies the official archive before
extracting it; it does not install a global SDK. Dependency acquisition is
separate from offline compilation and tests. The existing real CanvasKit UI is
then exercised in Firefox with synthetic products, followed by the separate
ordered-table trial. Both are needed: the first checks refresh, independent
failures, expiry and navigation; the second checks exact rows, cells and source
time windows.

Only successful public web assets, the reviewed browser/fixture runtimes and
their notices are exported for later admission into the core trial. Original
build and browser reports remain separate. SDKs, dependency caches, browser
profiles and Git data are not uploaded. These synthetic trials make no weather
source requests and do not prove core delivery or native Android/iOS operation.

## Android trial candidate

The [Android hosted workflow](../../.github/workflows/hosted-android.yml) is ready
for its first debug APK build and installed-app emulator trial; neither has yet
run. The [native preparer](prepare_native_android.py) modifies only a disposable
Android stage, using package `org.volparossa.weather.trial`. Its test-only
`lib/volparossa_native_trial.dart` entrypoint starts the real app with
`VOLPAROSSA_WEATHER=true` and
`VOLPAROSSA_CORE_ORIGIN=http://127.0.0.1:43210`. The existing dependency lock,
shared overlay and web/iOS sources stay unchanged.

The [trial driver](native-android-driver.mjs) uses real Android taps and
background/resume actions. A read-only debug observer checks mounted weather and
air-quality tables against the synthetic HTTP responses: four weather rows,
five particulate rows, native times, precipitation windows and missing values.
The trial also requires expired values to disappear after resuming, without
another provider request. Mounted widget contents are not proof of pixel
visibility. The separate fixture-control port is not exposed to the app. This
candidate does not prove live weather, mobile core delivery, physical-device or
iOS operation, home-screen widgets or release readiness.

The [official Android and Gradle input pins](../../scripts/prepare_hosted_android.py)
record exact archive URLs, sizes and published checksums. The native stage uses
Android API 36, build-tools 35.0.0, NDK 28.2.13676358 and Gradle 8.13; its
Android-only plugin change selects AGP 8.11.1. Java 17 comes from the disposable
runner's recorded system packages. Google archive pins use the published SHA1;
an observed SHA256 is additional provenance, not independent authorization.
Gradle's distribution has a published SHA256, and its wrapper comes from the
already pinned Flutter archive. All original archive licenses and notices are
preserved. Public dependency acquisition precedes an offline rebuild; captured
Gradle checksums demonstrate consistency, not prior independent review. Only
successful debug APKs, application notices and bounded reports may be exported,
not SDKs, caches, signing keys, emulator state or debug-service credentials.

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
windows and keeps weather and particulate timelines separate. Tables are
identified by their exact static ordered headers, independently of expected
values. Metadata is checked under the actual product titles. This matters
because Flutter can merge both metadata labels before the table children;
the last preceding title does not establish table ownership. Missing, duplicate
or unknown tables and changed cells still fail. Five pure DOM regressions cover
this correction; CI includes the pinned Browser helper sources.

The separate synthetic browser trial proves this exact table verifier, not
separate DOM containers for each product. The joined Overmorrow trial has not yet
run and core-to-client delivery remains unproved. Even a successful joined trial
would prove a prior cold core transfer followed by UI use of those publications,
not that opening the browser initiated the first cold fetch. The retained
synthetic browser result and historical origin results keep their original scope.
The earlier frozen core bundle is unchanged and contains the prior verifier;
a future joined trial must use a newly captured bundle with this correction.

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
