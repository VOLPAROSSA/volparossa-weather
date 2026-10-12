# Project-local ecCodes decoder

`../eccodes-sources.json` pins the original source commits, archive lengths and
SHA-256 hashes for ecCodes 2.44.0, its ecbuild 3.8.5 build macros and libaec 1.1.4.
These are source archives, not downloaded executables. ecbuild 3.8.5 is the
fallback version named by this exact ecCodes source. No local source patches are
applied. The official DKRZ GitHub repository and DKRZ GitLab contain the same
libaec commit; the pinned archive is from the former (the latter returned HTTP
429 during initial preparation).

With the existing Debian C/C++ toolchain, CMake, Make, Python and bubblewrap:

```sh
python3 scripts/build_eccodes.py --fetch --build
```

`--fetch` is explicit permission to download these three exact source archives.
Omit it to require already-cached, hash-verified archives. `--build` performs the
source build; without it the script only prepares sources. There is no `sudo`,
package-manager installation, host network change or global installation.
Build subprocesses run without network access, with only `build/eccodes`
writable and a disposable `/tmp`. Two compiler jobs are used. Build logs and
the final binary/hash receipt remain under that ignored directory. Interrupted
or unknown files are not automatically deleted.

The resulting executable is:

```text
build/eccodes/eccodes-build/bin/grib_ls
```

It links ecCodes and libaec statically and embeds GRIB definitions/samples.
It does not require `LD_LIBRARY_PATH`, `ECCODES_DEFINITION_PATH` or
`ECCODES_SAMPLES_PATH`. The platform C/C++ runtime remains dynamically linked;
this is not a portable, fully static binary. The caller must use a clean
environment rather than inherit arbitrary `ECCODES_*` overrides.

This minimal decoder supports GRIB geography and AEC/CCSDS compression. BUFR,
Fortran, NetCDF conversion, JPEG2000, PNG and extended downloadable test data
are deliberately outside this build. A successful build/version probe is not
an ECMWF download/decode proof; those are separate functional checks.

## Hosted input preparation

The separate [hosted workflow](../../.github/workflows/hosted-inputs.yml) prepares
inputs for a future joined core/browser trial without using a developer's private
bundle. It downloads the same three pinned source archives, records the actual
runner toolchain, and builds through
[`prepare_hosted_decoder.py`](../../scripts/prepare_hosted_decoder.py).
The existing builder, historical decoder hash and earlier trial receipts remain
unchanged. Inspect the workflow result before treating a build as successful.

The new recipe supports Debian 13 and Ubuntu 24.04 amd64. It uses two compiler
jobs, one thirty-minute build deadline, a network-free namespace, a fixed
`/build` path and an explicit build date. Success requires the upstream libaec
tests, the ecCodes version check, and encoding and decoding a nonconstant
CCSDS fixture at two known grid points. The recipe records effective flags,
source hashes, tool versions, output hashes and original licenses. Toolchain
capture describes the runner; it is not independent decoder authorization or a
fully hermetic, bit-reproducible build claim.

On the disposable Ubuntu GitHub runner, the workflow uses a separate
[`CI wrapper`](../../scripts/prepare_hosted_decoder_ci.py) for the runner's
user-namespace restrictions. It records bounded diagnostics, refuses conflicting
AppArmor profiles, and temporarily adds only the pinned Bubblewrap setup and
capability-denying child profiles. It verifies the actual decoder sandbox before
capturing tools or compiling, then removes its own policy after stopping its
processes. The build stays unprivileged and offline; no system-wide restriction
is disabled. Unconfirmed process termination or policy cleanup fails the job;
the wrapper does not remove a policy that surviving processes might still need.
This wrapper is not for a developer machine or a self-hosted runner.
Its original policy license and provenance are retained under
[`third_party/apparmor-ci`](../apparmor-ci/).

Preview the recipe without downloads, compilation or toolchain execution:

```sh
python3 -B scripts/prepare_hosted_decoder.py plan
python3 -B -m unittest discover -s tests -p 'test_hosted_*.py'
```

[`prepare_hosted_runtime.py`](../../scripts/prepare_hosted_runtime.py) separately
materializes pinned historical Node and Debian Firefox archives into a new
private directory under `build/`. It requires an explicit `--fetch` or existing
archives supplied with `--archives`; it checks archive and extracted runtime
hashes, preserves licenses, and never executes the runtimes or package scripts.
These historical artifacts are not a current browser-update recommendation.

The workflow installs build tools only on its disposable GitHub runner and
publishes bounded diagnostics, provenance and successful source-built decoder
outputs with notices. It does not acquire weather data, run a browser or admit
the decoder to the core. The new binary still needs separate byte admission,
actual Debian 13 compatibility checks, a fresh browser proof and joined delivery.

## Original licenses and notices

- ecCodes: Apache-2.0; original `LICENSE` and `NOTICE` retained. Its `COPYING`
  is a symlink to `LICENSE` in the original archive.
- ecbuild: Apache-2.0 with the additional third-party macro notices listed in
  its original `NOTICE`; original `LICENSE`, `NOTICE` and `COPYING` retained.
- libaec: BSD-2-Clause; original `LICENSE.txt` retained.
- ecCodes' bundled expected implementation: original CC0-1.0 `COPYING` retained.

The complete original sources remain in the verified archives and extracted
source trees. Redistribution of decoder binaries must retain these applicable
notices and comply with the licenses; this repository does not commit binaries
or ECMWF forecast datasets. Forecast-data attribution is separate from software
licensing.

Primary sources:
[ecCodes pinned source](https://github.com/ecmwf/eccodes/tree/aa85928d05036a1bce3cab330bc75681dc26c234),
[ECMWF build instructions](https://confluence.ecmwf.int/pages/viewpage.action?pageId=358882802),
[ecbuild pinned source](https://github.com/ecmwf/ecbuild/tree/a07c0a5caeec13214b3c7b0542c2427f46d417b3),
[libaec pinned source](https://github.com/Deutsches-Klimarechenzentrum/libaec/tree/7204505af7d6635734fc12a38d6bd0a6253c9c6d).
