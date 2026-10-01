# Project VOLPAROSSA Weather

**Direct public weather models. Shared evidence. Learning that must earn its accuracy.**

A framework-independent forecast contract for future cross-platform VOLPAROSSA
apps, with direct public-data acquisition and a consumer for the existing core's
shared content cache. The first adapter reads **ECMWF Open Data directly**;
no intermediate weather API is required.

## The first executable slice

- Select an explicit IFS or AIFS Single initialization and forecast lead times.
- Read that file's official JSON-lines index and request only the selected GRIB2
  field's exact HTTP byte range. Never fall back to downloading the whole file.
- Use an explicitly pinned official ecCodes decoder to find the nearest model
  grid point, check its run/validity/parameter/unit metadata and convert 2 m
  temperature from Kelvin to Celsius. Missing values remain `null`.
- Read an explicitly trusted publisher's forecast through core `content fetch-name`,
  checking receipt identity, hash, bytes, requested location/model/run/steps and
  both original forecast expiry and signed publication expiry.

This is a **temperature-first development component**, not yet a complete weather
app. Wind, rain, observations, trained corrections, model comparison, automatic
shared acquisition and platform UIs remain future work. Rain accumulation must
not be presented as hourly rainfall; unsupported values are not invented.

The [real IFS origin-to-native-decoder smoke](third_party/ecmwf-smoke.json) passes:
658,325 selected GRIB bytes produced a 15.396 °C nearest-grid forecast for the
explicit public Berlin test point, with exact initialization/valid time and full
temporary-process cleanup. This establishes decoding, not measured accuracy.
The AIFS request contract is supported but its native end-to-end run is not yet
proven. Fourteen focused tests use synthetic payloads and a real subprocess
fixture; those are not a live Weather-to-core overlay proof.

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

The original field covers a global grid, but contains **only one parameter at one
lead time**, not an entire multi-parameter model file. A field can supply many
local points. Coordinates are used locally and are not included in upstream URLs;
the HTTPS server still sees the acquiring connection's IP and requested model
files. There is no geolocation, location history, telemetry or implicit training
publication. Explicit stdout output may contain the chosen location.

Requests are sequential, require exact HTTP 206 ranges, and bound each index to
512 KiB and field to 8 MiB. Each transfer has a 30-second deadline. ecCodes receives
a single temporary field with a 512 MiB address-space limit, 20 CPU seconds and a
30-second wall deadline. Its subprocess is joined on cancellation; the exact new
temporary directory is removed. There is no installer in the forecast command.

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
