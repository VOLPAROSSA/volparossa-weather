# Drizz.li: first VOLPAROSSA client integration

This integration connects the **actual Drizz.li week route** to VOLPAROSSA's
shared weather provider. It is a reproducible source patch and client overlay,
not a separate weather demonstration or a complete replacement for Drizz.li.

The current view shows temperature and wind at the model's native UTC forecast
times. It identifies the configured coordinates, model run, expiry, ECMWF
attribution, licence and processing changes. It does not invent hourly values,
current observations, daily extrema, weather icons, precipitation or air quality.

## What works, and what remains

Verified in this development slice:

- Eleven tests cover the client validator, fixed request boundary, native and
  missing values, upstream integration guards, actual Svelte rendering, escaped
  source descriptions, and client/server compilation of the real week route.
- The full staged app passes `svelte-check` and a production Vite client/SSR
  build with the static adapter.
- The local HTTP bridge has separate functional tests in
  [provider-http.test.mjs](../../tests/provider-http.test.mjs).
- The actual built static directory is accepted by the bridge: the root and
  week-route shell plus 16 referenced assets return successfully, without any
  core request. This checks static serving, not JavaScript execution.
- An isolated Firefox run exercises the actual page and HTTP bridge with
  **synthetic weather**: hydration, exact native timestamps, temperature/wind,
  refresh, missing values, unavailable/stale responses, expiry while displayed,
  location-route redirection and the disabled maps view all pass. The test makes
  seven provider requests and verifies normal browser/bridge shutdown and
  private-profile cleanup. [The retained receipt](browser-smoke.json) binds the
  source, built assets, runtime and driver hashes; it does not claim a live core,
  overlay or weather-origin fetch.

A joined live core-to-browser trial, additional location selection,
precipitation/air-quality inputs, and the Overmorrow mobile integration remain
open. Synthetic browser success does not prove those capabilities.

## Data and privacy boundary

In `VITE_VOLPAROSSA_WEATHER=1` mode the client makes one fixed, same-origin
`GET /api/volparossa/forecast` request, without parameters or a request body.
The local bridge selects one explicitly configured **public-community** forecast
through the existing core-cache provider. The browser cannot choose a publisher,
file path, control socket or location through this endpoint.

The returned coordinates are shown prominently. City-specific routes redirect to
the configured week view before geocoding; location selection, automatic
geolocation, nearby weather, maps and other unsupported weather views are
disabled. There is no fallback to Open-Meteo or another weather service. A stale,
unavailable or invalid forecast produces a visible unavailable state. Missing
precipitation is not zero rain; missing air quality is not clean air.

This mode does not publish a location. Choosing `communityArea: true` means the
operator has deliberately selected an already public community area; it is not
permission to publish someone's GPS position. Core publication signatures do
not independently attest that the publisher's data came from ECMWF.

The original upstream provider behavior is retained when VOLPAROSSA mode is off.
That ordinary upstream build is not the privacy-constrained integration described
here. Use the local bridge below, not the upstream development/preview server.

## Source and licences

[Drizz.li upstream](https://github.com/open-meteo/drizz.li) is pinned to
`d2a6839e2b3f2e561b849d83014fc5959bed39cc`, deliberately retaining the inspected
pre-SvelteKit-3 baseline. [upstream.json](upstream.json) records its tree, original
licence, lockfile, patch and copied Weather-module hashes. Updating that pin
requires a joint framework/integration review.

Drizz.li is AGPL-3.0-or-later. Its original `LICENSE` and notices remain unchanged.
Original VOLPAROSSA code is GPL-3.0-only and the stage includes
`LICENSE.VOLPAROSSA`; preserve both notices and provide the corresponding source
when distributing or operating the combined modified app as required by its
licences. ECMWF data remains attributed under CC BY 4.0. No external fork is
created by these scripts.

Two upstream localization build plugins are separately pinned in
[build-plugins.json](build-plugins.json). Preparation verifies their npm archive
SHA512 integrity and retains both MIT notices. Their original CDN imports are
replaced with local files before compilation. Application dependencies use the
unchanged upstream `package-lock.json`; installation scripts are not run.

## Stage and build

Run from this repository on a Linux development system with Git, Python 3, and
an independently verified Node/npm installation. The verified run used Node
24.19.0 and npm 11.17.0. Keep downloads, dependency cache and generated files
inside the ignored `build/` directory. Allow at least 1 GiB of working memory
in addition to the host's reserved headroom; the dependency tree uses about
590 MiB of disk space on the verified Linux amd64 stage.

`stage.py` requires a **new** direct child of `build/`. It fetches only the pinned
source, verifies the recorded inputs and applies the local patch and overlay.
An optional `--source-clone /absolute/reviewed/checkout` reuses local Git objects,
not that checkout's working-tree modifications. Failed stages are retained for
inspection, not automatically deleted. Without `--execute`, both preparation
scripts only print their plans.

```sh
umask 077
mkdir -p build
python3 integrations/drizzli/stage.py --execute --destination build/drizzli-volparossa
python3 integrations/drizzli/prepare_build.py --execute --stage build/drizzli-volparossa
cd build/drizzli-volparossa
export NODE_OPTIONS=--max-old-space-size=768
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
export VITE_VOLPAROSSA_WEATHER=1
timeout 300s prlimit --cpu=300 -- npm ci --ignore-scripts --no-audit --no-fund --cache ../npm-cache-drizzli
timeout 120s prlimit --cpu=120 -- ./node_modules/.bin/paraglide-js compile --project ./project.inlang --outdir ./src/lib/paraglide
timeout 120s prlimit --cpu=120 -- ./node_modules/.bin/svelte-kit sync
timeout 120s prlimit --cpu=120 -- ./node_modules/.bin/svelte-check --tsconfig ./tsconfig.json
timeout 180s prlimit --cpu=180 -- ./node_modules/.bin/vite build
```

Do not substitute `npm run build`: its upstream `prebuild` downloads mutable
external assets and prunes local assets. Those operations are not needed for
this view and were not run. Do not run dependency lifecycle scripts, browser
downloads or unpinned `npx` installers. The explicit commands above generate
localization output, type-check the app and build `build/drizzli-volparossa/build`
without that asset prehook. Tooling packages may still contain native binaries;
their upstream lockfile integrity is checked by npm, not replaced with a claim
that they were built from source here.

From the Weather repository root, test the client and actual staged components:

```sh
DRIZZLI_STAGE="$PWD/build/drizzli-volparossa" NODE_OPTIONS=--max-old-space-size=768 \
  timeout 120s prlimit --cpu=120 -- node --test \
  integrations/drizzli/test-client.mjs integrations/drizzli/test-render.mjs
node --test tests/provider-http.test.mjs
```

The render tests use clearly synthetic fixtures and the staged app's real Svelte
compiler. They do not contact a weather origin, launch a browser or claim to
verify the overlay.

### Optional isolated browser proof

The Linux browser smoke additionally requires `bubblewrap`, a sibling
`volparossa-browser` checkout containing its reviewed runtime-validation and
Marionette helpers, and an already staged Firefox 140.16.0 runtime with the exact
hashes accepted by those helpers. It does not install or download a browser.
The Node executable must match the recorded Node 24.19.0 SHA256. Provide your
actual verified executable path below, and choose a new output directory.

```sh
python3 -B integrations/drizzli/test_smoke_browser.py
timeout 150s prlimit --cpu=120 -- python3 -B integrations/drizzli/smoke_browser.py \
  --stage build/drizzli-volparossa \
  --browser-stage ../volparossa-browser/build/firefox-esr-smoke-v3 \
  --node /ABSOLUTE/PATH/TO/VERIFIED/node \
  --output build/drizzli-browser-smoke-01
```

The retained successful run used `--stage build/drizzli-volparossa-03`,
`--output build/drizzli-browser-smoke-03` and the workspace-verified executable at
`build/tooling/node-v24.19.0-linux-x64-drizzli-20261011/node-v24.19.0-linux-x64/bin/node`.
All other arguments match the command above. Earlier failed runs remain failed;
they exposed test-fixture shutdown/readiness bugs which were corrected before
the retained pass.

Four inert tests cover environment isolation, process-exit races and guarded
cleanup. The browser driver then tests actual fixture child shutdown via a stop
command, EOF and SIGTERM before starting Firefox. `--fixture-only` runs just those
lifecycle cases. This is a test-only dependency injection into the actual HTTP
bridge, not a production synthetic-weather mode.

The driver requires at least 3 GiB available memory, stops if the host falls below
a 2 GiB reserve, disables core dumps, and bounds the namespace lifetime to 120
seconds. Firefox and the bridge share a new loopback-only user/network/PID
namespace with read-only host/runtime mounts and private writable test state.
No ordinary browser profile, external connectivity or host network change is
used. Cleanup checks and a closed result survive failure; no raw browser log or
page contents are exported. Source and built-asset identity are checked before
launch, and the receipt records the helper hashes actually used.

## Serve through the local core bridge

First obtain an existing, fresh, trusted core-cache publication as described in
the [root README](../../README.md). Its area, model run, lead times, wind presence,
publisher, name and revision must match the bridge configuration exactly.
Expired publications must be replaced with genuinely fresh data, not given new
timestamps. The bridge does not acquire data from an Internet origin or publish
it when a request fails.

Create a private JSON file in an owner-controlled directory using your editor.
The following is a template: replace the uppercase placeholders and example
coordinates/steps with the actual publication. The `cache` and `scratchParent`
locations are dedicated core-provider working directories, not the static site.

```json
{
  "core": {
    "mode": "core-cache",
    "executable": "/ABSOLUTE/PATH/TO/volparossa",
    "controlSocket": "/ABSOLUTE/PATH/TO/control.sock",
    "cache": "/ABSOLUTE/PATH/TO/weather-cache",
    "scratchParent": "/ABSOLUTE/PATH/TO/private-weather-scratch",
    "publisherKey": "REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS",
    "name": "REPLACE_WITH_TRUSTED_PUBLICATION_NAME",
    "minRevision": 1,
    "query": {
      "latitude": 52.52,
      "longitude": 13.41,
      "run": "REPLACE_WITH_ACTUAL_FRESH_MODEL_RUN_UTC",
      "model": "ifs",
      "steps": [3, 9, 24],
      "communityArea": true,
      "includeWind": true
    },
    "reuseCache": false
  },
  "variables": ["temperature_2m", "wind_speed_10m", "wind_direction_10m", "precipitation", "air_quality"]
}
```

`includeWind` must match the publication, not merely the desired UI fields.
Precipitation and air quality currently return explicit unavailable capabilities;
requesting them does not add a data source. A temperature-only publication can
use `includeWind: false`; the view then reports missing wind rather than zero.

Set this **specific file** to mode `0600`, keep scratch space private (`0700`),
and start from the Weather repository root:

```sh
chmod 600 /ABSOLUTE/PATH/TO/weather-bridge.local.json
node scripts/serve-provider.mjs \
  --config /ABSOLUTE/PATH/TO/weather-bridge.local.json \
  --static-root "$PWD/build/drizzli-volparossa/build" --port 8788
```

Open `http://127.0.0.1:8788/en/weather/week/` in a disposable development browser
profile. Stop the bridge with Ctrl-C. It listens only on IPv4 loopback, checks
Host/Origin, has no cross-origin API permission, and uses a restrictive policy
that blocks external connections, frames and workers. Requests cannot supply
query parameters or bodies. It admits one forecast request at a time, with a
180-second retrieval deadline; the client waits up to 185 seconds.

Select only the dedicated built-site directory, never the repository or a folder
containing private configuration. The bridge snapshots owner-controlled regular
assets, rejects symlinks, hardlinks and group/world-writable entries, and caps
the tree at 1,024 entries, 32 MiB total and 8 MiB per asset. Files are served
without directory listings. These development boundaries do not replace a
future authenticated, packaged application integration.
