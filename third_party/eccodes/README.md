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
