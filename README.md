![Project VOLPAROSSA Weather — a fox-shaped weather vane between storm clouds and a golden sky](docs/assets/banner-volparossa-weather.png)

# Project VOLPAROSSA Weather

**Direct public weather models. Shared evidence. Learning that must earn its accuracy.**

A framework-independent forecast contract for future cross-platform VOLPAROSSA
apps, with direct public-data acquisition and a consumer for the existing core's
shared content cache. The first adapter reads **ECMWF Open Data directly**;
no intermediate weather API is required.

## The first executable slice

- Select an explicit IFS or AIFS Single initialization and forecast lead times.
- Read that file's official JSON-lines index once per lead time and request only
  each selected GRIB2 field's exact HTTP byte range. Never download the whole file.
- Use an explicitly pinned official ecCodes decoder to find the nearest model
  grid point, check its run/validity/parameter/unit metadata and convert 2 m
  temperature from Kelvin to Celsius. Missing values remain `null`.
- Opt into real 10 m wind components, speed and meteorological direction with
  `--include-wind`. Decode `2t`, `10u` and `10v` independently and require matching
  initialization, valid time, full grid geometry and nearest grid point.
- Add native precipitation totals with `--include-precipitation`, independently
  of wind. Retain the source accumulation window and normalize to millimetres;
  do not turn cumulative totals into invented hourly rain.
- Read an explicitly trusted publisher's forecast through core `content fetch-name`,
  checking receipt identity, hash, bytes, requested location/model/run/steps and
  both original forecast expiry and signed publication expiry.
- Build the pinned Drizz.li web client with a VOLPAROSSA forecast view, served by
  an explicit local HTTP bridge to that same core-cache consumer.

This is a **temperature, wind and precipitation development component**, not yet a complete weather
app. Air quality, observations, trained corrections, model comparison,
automatic shared acquisition and native mobile integration remain future work.
The Drizz.li build and isolated browser interaction pass with synthetic weather;
displaying a real forecast delivered through the live overlay still needs a
joined trial. Rain accumulation must
not be presented as hourly rainfall; unsupported values are not invented.

The [real IFS origin-to-native-decoder smoke](third_party/ecmwf-smoke.json) passes:
658,325 selected GRIB bytes produced a 15.396 °C nearest-grid forecast for the
explicit public Berlin test point, with exact initialization/valid time and full
temporary-process cleanup. This establishes decoding, not measured accuracy.
The original twenty-two focused tests use synthetic payloads and a real subprocess
fixture; those are not a live Weather-to-core overlay proof.

The [real opt-in wind smoke](third_party/ecmwf-wind-smoke.json) also passes through
the CLI and the same pinned native decoder: one IFS initialization, three selected
fields totaling 2,292,842 bytes, and a co-located Berlin vector of −1.87405 m/s
eastward and 1.56929 m/s northward. That gives 2.444327 m/s from 129.942097°;
it is a decoded forecast, not evidence that the forecast is accurate.

The [native precipitation trial](third_party/ecmwf-precipitation-smoke.json)
passes for both IFS and AIFS Single. It checks three native lead times per model,
including AIFS step-zero precipitation, through the actual CLI and decoder.
IFS additionally includes wind. These are bounded origin/decoder trials, not
proof of forecast accuracy or complete overlay-to-browser delivery.

## Try a deliberately chosen model run

Use an existing Node.js 22+ installation. The ESM JSON contract has no framework
dependency. The current ecCodes/core process adapters run on Linux; native mobile
decoders and UI packaging are not implemented.

The explicit [source-only decoder builder](third_party/eccodes/README.md) uses
pinned official ecCodes/ecbuild/libaec sources and workspace-local output. It
does not install system packages or silently download a binary. Supply the real
binary hash from its build receipt; no runtime definitions download is needed.

```sh
# Preview: no network or decoder execution. Choose an available run explicitly.
node scripts/forecast.mjs origin --latitude 52.52 --longitude 13.41 \
  --run 2026-09-30T12:00:00.000Z --model ifs --steps 12

# Use a decoder built from the recorded official source and its actual binary SHA.
# PRIVATE_PARENT must already exist, be owned by you and have mode 0700.
node scripts/forecast.mjs origin --latitude 52.52 --longitude 13.41 \
  --run 2026-09-30T12:00:00.000Z --model ifs --steps 12 \
  --decoder /absolute/path/to/grib_ls --decoder-sha256 VERIFIED_BINARY_SHA256 \
  --scratch-parent /absolute/PRIVATE_PARENT --execute --accept-data-license

node --test tests/*.test.mjs
```

The date above is an example, not an automatically maintained latest run. The
real-time upstream archive is rolling; unavailable runs fail explicitly. The
client does not silently substitute another initialization or provider.

Add `--include-wind` to either `origin` or `core-cache` for the optional v1
`wind_10m` extension. Without it, temperature-only output and cache requests stay
unchanged. Use a distinct published cache name for the wind-inclusive field set:
a request never silently substitutes a temperature-only forecast for wind, or
vice versa. Existing temperature-only consumers need not adopt the extension.

Each wind block retains the signed components (`eastward`, `northward`), derived
`speed`, `direction_from`, `status` and both fields' individual range/hash evidence.
Direction follows the [ECMWF meteorological convention](https://confluence.ecmwf.int/pages/viewpage.action?pageId=133262398):
clockwise **from** true north, not the direction of travel. A missing decoded
component remains `null`, with derived speed/direction `null` and status `missing`.
Actual `(0, 0)` components produce speed `0`, direction `null` and status `calm`;
no arbitrary calm threshold is imposed. Missing or ambiguous whole model fields,
rotated vectors, or mismatched grids fail explicitly. These are instantaneous
10 m vectors, not gusts, observations or newly interpolated hourly values.

### Precipitation totals with explicit time windows

Add `--include-precipitation` to `origin` or `core-cache` to request the optional
`precipitation` block. It contains `amount` in millimetres, `source_value`, native
start/end lead hours and UTC times, and the field's evidence. The cache request
must match that field set exactly; selecting a display variable alone does not
enable acquisition or change the requested publication.

IFS total precipitation uses parameter 228 in metres; AIFS Single uses 228228
in kilograms per square metre. The adapter checks the model-specific identity
and unit before converting to millimetres of water equivalent. See the
[ECMWF AIFS field definitions](https://confluence.ecmwf.int/plugins/viewsource/viewpagesrc.action?pageId=496875126).
All requested fields must share the model run, grid and nearest point.

Each amount covers its **own source accumulation window**. Windows may overlap;
do not add their totals together. The adapter neither differences adjacent
samples nor derives a rain rate or probability. Nonconsecutive requested lead
times do not define new intervals. Missing values remain `null`, genuine zero
remains zero, and a zero-length window is accepted only at model step zero with
a zero or missing value. Unknown statistical metadata fails explicitly.

The original field covers a global grid, but contains **only one parameter at one
lead time**, not an entire multi-parameter model file. A field can supply many
local points. Coordinates are used locally and are not included in upstream URLs;
the HTTPS server still sees the acquiring connection's IP and requested model
files. There is no geolocation, location history, telemetry or implicit training
publication. Explicit stdout output may contain the chosen location.

Requests are sequential, require exact HTTP 206 ranges, and bound each index to
512 KiB and field to 8 MiB; wind selects three fields per lead instead of one,
and precipitation adds one field. All fields reuse the same index for that lead.
Each transfer has a 30-second deadline. ecCodes receives
a single temporary field with a 512 MiB address-space limit, 20 CPU seconds and a
30-second wall deadline. Its subprocess is joined on cancellation; the exact new
temporary directory is removed; decoded GRIB files are removed as soon as consumed.
There is no installer in the forecast command.

## Reuse a shared forecast through the core

Trust the publisher key independently of the provider response. The core daemon,
contribution configuration and protected routes must already be set up. `--cache`
is an explicitly configured agent-owned cache; the private scratch directory is
owned by the invoking account.

```sh
node scripts/forecast.mjs core-cache \
  --executable /absolute/path/to/volparossa \
  --control-socket /run/volparossa-agent/control.sock \
  --cache /absolute/agent-owned/weather-cache \
  --scratch-parent /absolute/user-owned/private-weather \
  --publisher-key TRUSTED_64_HEX_KEY --name weather.berlin.ifs --min-revision 1 \
  --latitude 52.52 --longitude 13.41 --run 2026-09-30T12:00:00.000Z \
  --model ifs --steps 12 --community-area --execute
```

Add `--reuse-cache` only for the exact previously owned agent cache. Retrieval does
not publish a location or fall back to direct origin traffic. Temporary local
output is deleted after verification; the core's owned cache is kept for reuse.

This calls real core interfaces inspected at
[`208883bc`](https://github.com/VOLPAROSSA/volparossa/tree/208883bc38d739184cb317cd68f2807d6aa16d87).
The JSON body type is checked. The current CLI receipt does not expose the signed
media type, so no extra manifest-media-type check is claimed. A publisher signature
authenticates that publisher's bytes, **not** ECMWF's endorsement or a reusable
ECMWF origin signature. Name lookup is not a globally-latest guarantee.

Publication stays an explicit owner operation: acquire a representative public
community area with `--community-area`, deliberately save the result, and use
core `content publish --contribute` with the existing identity/passphrase controls,
new owned cache/manifest paths, an explicit name/revision and content type
`application/vnd.volparossa.forecast.v1+json`. Use a short lifetime within the
remaining forecast window. Do not automatically publish a private location.
The public-area flag records intent; it is not anonymization.

## Shared application provider

The opt-in `volparossa.weather.provider.v1` contract provides one common data
boundary for application adapters. Drizz.li now has a source integration and a
local HTTP bridge; Overmorrow remains to be connected. Neither introduces a
second network scheduler or an external weather fallback.

[`toProviderForecast`](src/provider.mjs) is a framework-independent, read-only
function over an already acquired forecast. It preserves the complete validated
forecast under `forecast`, including source, initialization, original acquisition,
license, grid and per-field evidence. This conversion is not a new acquisition or
a learned prediction. Its `verification_scope` explicitly covers schema and
freshness only; accepting this shape does not authenticate a publisher or ECMWF.

[`fetchCachedProvider`](src/provider-core.mjs) uses the existing real
`fetchCachedForecast` path, then projects that result. It retains the verified
delivery receipt's publisher/name/revision/hash/manifest binding and its limits:
`upstream_origin_attested` and `manifest_media_type_checked` remain `false`.
Pure projection has `delivery: null`; a core-cache result contains `delivery`.
Neither case claims that a reused forecast was freshly downloaded from ECMWF.

| Provider field | Meaning |
| --- | --- |
| `timeline.valid_at` and `lead_hours` | Original UTC model-valid times in the supplied order, not an invented hourly grid |
| `capabilities.implemented_variables` | Temperature, wind speed, wind direction and precipitation understood by this version |
| `capabilities.available_variables` | Fields present in this particular forecast; individual samples may still be missing |
| `series` | Requested variables with units, values and an aligned `value_status` array |
| `freshness.expires_at` | Earlier of the original forecast expiry and supplied signed-publication expiry |

The variables are `temperature_2m` in `degC`, `wind_speed_10m` in `m/s`,
`wind_direction_10m` in degrees clockwise **from** north and `precipitation` in
`mm`. Precipitation additionally carries `statistic: accumulation` and an aligned
`accumulation_windows` array. `availability: supported`
does not mean every value is known: `value_status: missing` retains `null`.
Actual calm wind retains speed `0`, direction `null` and status `calm`.
An unsupported variable, such as AQI, has
`availability: unavailable`, reason `unsupported_variable` and no units or values.
Wind or precipitation requested from a forecast without that field instead has reason
`field_not_in_forecast`. The adapter never fills these gaps with zeros, weather
icons, current observations, interpolation or an external provider.

Use the existing CLI with `--output-contract provider` and optional `--variables`.
The default output contract and temperature-only behaviour remain unchanged.
Selecting wind or precipitation does not silently add its acquisition flag or choose another
published field set. Variable lists are bounded to 16 distinct identifiers and
are validated before retrieval; the underlying forecast retains its 16-sample limit.

```sh
# Preview only. Add the explicit core-cache arguments shown above and --execute
# to retrieve a deliberately selected publication through an already configured core.
node scripts/forecast.mjs core-cache \
  --latitude 52.52 --longitude 13.41 --run 2026-09-30T12:00:00.000Z \
  --model ifs --steps 12,15,24 --community-area --include-wind --include-precipitation \
  --output-contract provider \
  --variables temperature_2m,wind_speed_10m,wind_direction_10m,precipitation
```

This is an example initialization, not a current run. Origin mode can also request
the provider output, but still requires the original explicit license acceptance,
pinned decoder and execution flag. Cache mode never falls back to origin mode.
Provider output deliberately includes the requested location and original evidence;
stdout is not permission to publish it. Recheck the expiry when reusing or displaying
the result: `checked_at` records validation time and never resets acquisition age.

### Drizz.li web integration

The [Drizz.li integration guide](integrations/drizzli/README.md) stages a pinned
upstream checkout with a VOLPAROSSA mode in its actual weekly forecast route.
It displays the configured area's native UTC temperature and wind points and,
when present, precipitation amounts with their source accumulation windows,
publication expiry, source attribution and missing capabilities. Unsupported
views, geolocation, geocoding, maps and the original weather-service calls are
disabled in this mode. The ordinary upstream build remains unchanged.

The [local development server](scripts/serve-provider.mjs) serves that built app
and one fixed forecast from `127.0.0.1`. Its private configuration selects the
trusted publisher, public community area and model run; browser requests cannot
choose arbitrary locations, publishers, files or commands. One bounded retrieval
uses the existing core-cache adapter, cancels on disconnect and never falls back
to an origin service. No CORS access or automatic location publication is enabled.
Initialize the exact agent-owned cache with an explicit successful CLI retrieval
first, then configure the long-lived bridge with `reuseCache: true`; one-shot
cache creation is rejected by the bridge so refreshes do not try to recreate it.

The full Drizz.li production build, Svelte/TypeScript checks and actual forecast
component rendering pass. Isolated Firefox trials verify the real page and HTTP
bridge with synthetic [temperature/wind](integrations/drizzli/browser-smoke.json)
and [precipitation](integrations/drizzli/precipitation-browser-smoke.json): initial
display, refresh, missing and stale values, expiry, route guards and cleanup.
The precipitation trial also preserves zero, small amounts and native time windows.
Separate functional tests exercise the bridge's core-process boundary using a
synthetic core executable. These trials do not yet prove a real overlay
publication reaching the rendered app. That joined trial, interactive location
selection and deployment packaging remain required; this is not yet a complete
cross-platform weather app.

### Overmorrow integration still required

Overmorrow's current Flutter provider dispatch defaults unknown providers to
Open-Meteo, including widget paths, and its full weather structure requires more
fields than this slice supplies. Add an explicit provider branch and missing-data
handling before connecting it. The author plans a Kotlin/Compose successor to the
current Android release; choosing that target versus the existing Flutter app is
separate from this shared contract.
[Pinned Overmorrow dispatch](https://github.com/bmaroti9/Overmorrow/blob/97995e2e00e454389e00e35f1e65654afe3e8bed/lib/decoders/weather_data.dart),
[upstream transition](https://github.com/bmaroti9/Overmorrow/discussions/238).

Overmorrow needs its own explicit provider adapter and capability-aware UI;
the Drizz.li build is not evidence of a working mobile integration. Both clients
must preserve absent data, expiry, units and provenance, without hidden provider
fallback or location publication.

### Additional weather data

- [x] Precipitation source and shared provider: IFS/AIFS native totals, checked
  units/time windows and missing values, with real origin/decoder trials.
- [x] Drizz.li precipitation display and interaction: actual isolated Firefox
  with synthetic values and native accumulation windows, including refresh.
- [ ] Complete precipitation delivery through the overlay and application clients;
  the joined real core-to-browser proof and Overmorrow
  integration remain separate requirements.
- [ ] Air quality: acquire suitable licensed pollutant data, retain concentration
  units and averaging periods, explicitly identify any derived index and its
  definition, test those transformations, then add application display.

Air quality and the remaining application work are required, not dropped.
Continue to use direct authorized sources without an Open-Meteo fallback.
Air quality returns `unsupported_variable`; precipitation absent from a selected
forecast returns `field_not_in_forecast`. Neither means a measured zero.

## Time, models and evidence

Every sample carries the exact initialization, forecast lead/valid time, grid
point/distance, parameter, unit, statistic, index/field hashes, byte range and
decoder hash. Native IFS 3-/6-hour or AIFS 6-hour steps are preserved; no artificial
hourly interpolation or fabricated issuance timestamp is supplied. `issued_at`
remains unknown: initialization is not the time a file became available.
The current [dataset catalogue](https://www.ecmwf.int/en/forecasts/datasets/open-data)
sets IFS 00/12 UTC horizons to 360 hours and 06/18 UTC to 144 hours; it takes
precedence over older examples with shorter horizons. This adapter supports the
post-50r1 layout from 13 May 2026 onwards.

Cache freshness is capped by original acquisition age (30 minutes), model-run age
(72 hours), and the original signed publication expiry. Re-signing or re-reading
a forecast never resets its embedded acquisition clock. Missing values are not
zero; wrong units, inconsistent run/valid time and ambiguous ranges fail closed.
These are data-integrity checks, not a forecast-accuracy guarantee.

The [source/protocol reference pin](third_party/ecmwf.json) records the official
client and ecCodes source used to verify the interfaces. It does not pretend the
live upstream deployment is pinned. ECMWF data is CC BY 4.0: display linked
attribution to [ECMWF](https://www.ecmwf.int/en/forecasts/datasets/open-data), retain
the license and identify nearest-point selection/unit conversion. Respect source
capacity; no retry storm, quota rotation or bulk ingestion is implemented.
[Official index/range documentation](https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS).

## Shared forecasting and learning, next

The intended next integration is one permitted acquisition per requested public
model field/run, many readers through the core cache, and incremental specialist
calibration only when it demonstrably improves the upstream baseline. Keep source,
run, grid, lead time and model resolution distinct; do not average incompatible
forecasts blindly. Additional direct providers can complement ECMWF later without
turning them into mandatory network authorities.

Training needs licensed, quality-controlled **actual observations**, with temporal
and geographic holdouts. Archived forecasts are predictions, not ground truth.
Small bias corrections and evaluated ensemble calibration are a practical first
step; an LLM explanation is not a numerical weather forecast. More participants
can improve coverage/capacity but do not guarantee greater accuracy.

Publish only authorized public data/models through existing core content objects.
Resource-budgeted weather workers must still be integrated with core compute:
CPU, memory, battery, storage and network pressure should pause contribution in
favour of the device owner. No private-coordinate history enters training, and no
second autonomous daemon or unsupported weather-training API is introduced here.
