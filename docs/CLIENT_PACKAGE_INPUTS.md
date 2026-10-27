# Hosted client package-input inventory

The existing Drizz.li and Overmorrow producer workflows have three explicit
manual modes. `historical-v1` preserves the historical build path.
`source-input-inventory` acquires candidate data without installing it.
`installed-environment-inventory` provisions the fixed reviewed Ubuntu package
inputs on the disposable GitHub-hosted Ubuntu 24.04 runner and captures the
installed state. It does not run Node, npm, Flutter, a browser or a compiler.

The versioned `third_party/client-package-inputs-*-v1.json` records authorize
package inputs only. Each record is pinned by exact bytes in the helper, with
no command-line lock, URL, expected hash or target override. The records retain
upstream source/lock identity, Linux/x64/glibc target, independent review and
candidate digests, all archive identities, signed repository/index provenance,
and SHA256 of each entire canonical member map. Canonical JSON is sorted,
ASCII-escaped, compact JSON plus one newline. Original member metadata and
notice text participate in the digest. Excluded npm entries and the two
explicit inactive optional musl inputs remain distinct and unchanged.
Runtime/SDK pins are references; this mode neither materializes nor executes
them. A missing or changed fixed record fails before acquisition or privilege.

The helper repeats the existing signed snapshot verification and reconstructs
all APT archive member maps. It requires exact equality to the fixed input
record before privilege. Every local archive is rehashed before simulation
and again before installation. APT receives only the verified local archives,
an isolated early configuration, an empty source/list set and `--no-download`.
The simulation must reinstall every exact package/version/architecture and
must contain no additional package, removal or failure. Installed package
versions/status and all unrelated baseline package rows are checked afterward.

The runner's existing root-owned sudo/APT/dpkg/interpreters are a deliberately
limited trusted hosted-platform bootstrap. Their identities and hashes are
observations, not independently pinned compiler authority. Existing package
triggers and their interpreters also remain part of this trusted platform
bootstrap; new archive hashes do not authenticate their existing bytes. The
isolated APT config and empty environment permit no caller hook or config. The exact planned
package changes are printed before privilege. Maintainer scripts and generated
configuration may change, and package services may start on this disposable
runner. The installer has a fixed privileged timeout. Cleanup holds its leader
unreaped until final privileged group termination and inspection; permission,
process-inspection or drain failures fail closed and preserve private recovery
data. The receipt covers the owned installer group and does not claim package
services were stopped. The disposable runner is destroyed by the platform.

Public projection remains a fixed bounded UTF-8 JSON/log allowlist. It contains
before/after package tables and member-file comparisons plus hashes/types for
fixed loader/font/alternatives configuration paths. It contains no installed file
contents, symlink target text, package archives, dependency caches, SDKs,
compiled assets or private directory copy. Unknown intermediate symlinks are
not followed; only the four fixed distro usrmerge directory aliases may be
traversed. Source-export file/total limits remain unchanged.

All installed receipts retain `admitted=false`,
`build_environment_admitted=false` and `consumer_admitted=false`. File or
configuration differences are observations requiring review and cannot become
expected hashes automatically. Generated loader/font configuration and actual
compiler/runtime/library/header inputs must be independently bound before
build execution. Actual npm installation state, inactive module no-load and
no-emission, complete module/notices coverage, SDK tree binding, two cold
builds and real UI/Core consumer trials remain separate gates. Local inert
source/data tests prove none of those runtime properties.

## Fixed installer companions after the first rejected plan

Run `40063804727` correctly stopped before installation: the pinned empty-root
closure and the preinstalled Ubuntu runner were at different update levels.
The runner's systemd family was `255.4-1ubuntu8.17`; the fixed closure requires
`255.4-1ubuntu8.18`. Existing `udev`, `libnss-systemd`, `systemd-resolved` and
`systemd-coredump` have exact dependencies on that family. The runner also had
GLib `2.80.0-6ubuntu3.9` and zlib `1:1.3.dfsg-3.1ubuntu2.2`, while the fixed
closure requires GLib `2.80.0-6ubuntu3.10` and zlib `1:1.3.dfsg-3.1ubuntu2.3`.
The existing GLib binaries/GI and zlib development package require their exact
matching library versions. The offline resolver had no matching companion
archives, so it proposed removing those packages and their reverse dependencies:
52 packages, including Ubuntu metapackages, Python development tools and udev
consumers. Git's separate PPA-to-Ubuntu downgrade was already explicitly
permitted; it does not resolve these exact-version conflicts.

`third_party/client-installer-companions-v1.json` supplies only those seven
matching preservation packages from the same authenticated fixed snapshot.
The original 227/235-package records and npm/pub pins are unchanged. The new
record binds both original input digests, signed repository/index identities,
package control dependencies, exact archive bytes and complete member-map
digests. All seven were present in the rejected runner baseline. They preserve
its existing package relationships; they are not new Weather feature roots.

The installed inventory always reinstalls the fixed union (234/242 packages),
including every companion. Its exact `Inst`/`Conf` simulation, no-removal,
no-download, archive rehash, installed-transition and unrelated-package guards
cover the entire union. `installer-companions.json` records the verified maps;
the installed receipt binds both original and companion input digests. The
supplement remains installer-only authority. No observed installed difference
becomes compiler authority. Source exports include the fixed companion record
with the existing per-file and total bounds.

This addresses the concrete retained baseline, not every future hosted image.
A different runner may still fail closed on another incompatible package,
missing dependency or installed/configuration check. The actual hosted plan,
installation, complete input/configuration review and cleanup remain required;
this document alone does not admit a usable client build environment.

## Offline APT cache and private cleanup

Run `40427827447` resolved the complete fixed union with **zero removals**, but
installation failed before unpacking: APT reported a relative internal archive
pathname, although every supplied numbered `.deb` argument was absolute.
APT 2.8.3's `pkgAcqArchive` first constructs a canonical basename from package,
version and architecture. Its cache-hit branch sets an absolute completed path.
With `--no-download`, local-only pending items survive filtering, then the
fetcher shuts down before their completion callback can normalize the path.
The numbered acquisition files did not provide the canonical cache hits.

The installer now makes exclusive regular copies under APT's exact canonical
names in its existing private archive cache, preserving epoch/underscore
percent encoding. The original acquired archives remain intact and rehashed.
The cache copies are independently rehashed immediately before simulation and
installation, with absolute private directory, ownership, mode, hardlink,
symlink and inode checks. Existing no-download/no-removal flags, package pins,
closed source/list configuration and exact simulation requirements are unchanged.

The same failed run's cleanup encountered an inaccessible `partial` directory.
The acquisition helper originally creates `archives/partial` as the runner
user at mode `0700`. APT 2.8.3's privileged cache `GetLock` calls
`SetupAPTPartialDirectory`, which changes that existing directory to its
configured sandbox user (default `_apt`), group root, mode `0700`. This source
explains the permission error; the failed run did not retain numeric owner/mode
observations. New before/after cache receipts record those actual observations.

After all started installer groups have confirmed drain receipts, cleanup
removes only that fixed **empty** directory via its verified runner-owned parent
descriptor. It never opens the inaccessible child, changes permissions or uses
privileged deletion. Nonempty directories, aliases, unexpected ownership/modes
or changed directory identities fail closed and retain recovery data. Cleanup
logs the observed owner/group/mode, successful directory absence and final
private/public directory absence. Existing timeout and interruption handling
remain in force. Local tests exercise these guards without invoking APT or
installing packages; actual installation and cleanup still require hosted proof.

Primary source: [Ubuntu APT 2.8.3 source archive](https://archive.ubuntu.com/ubuntu/pool/main/a/apt/apt_2.8.3.tar.xz),
SHA256 `088522b3613b28fdbcfa61f1f7e476bf6dc6b0120a8f74409e9527580c9f9d3b`;
`apt-pkg/acquire-item.cc`, `apt-pkg/acquire.cc`, `apt-private/private-install.cc`,
`apt-pkg/contrib/strutl.cc`, `apt-pkg/init.cc` and `apt-pkg/deb/dpkgpm.cc`.

## P13c: concrete remaining build-input binding stop

The retained successful installation baseline is Weather
`f5ab9e4437df17be1aa6cadee61f5988b6898191`, run `40430225596`, artifact SHA256
`a6021ca59641577d961fbcc22c383808c4d22586f92c8af887690305fb244862`.
Its 234 exact package installations and cleanup remain verified. P13c reuses
that evidence without another hosted run, package installation or application
build. All three original package-input/supplement records and npm/pub pins
remain byte-identical.

The approved `libc-bin` member `/etc/ld.so.conf` has 34 bytes and SHA256
`d4b198c463418b493208485def26a6f4c57279467b9dfa491b70433cedb602e8`.
Its exact bytes contain `include /etc/ld.so.conf.d/*.conf` followed by two newline
bytes. The retained configuration matches **four** files: the approved
`libc.conf` and `x86_64-linux-gnu.conf`, plus two files without an owner in the
fixed package-member maps:

| Included generator input | Bytes | Observed SHA256 |
| --- | ---: | --- |
| `/etc/ld.so.conf.d/fakeroot-x86_64-linux-gnu.conf` | 38 | `af7edc777dd224bade078ba540538444db69856533c02e18a7f9fbbdd23bd181` |
| `/etc/ld.so.conf.d/zz_i386-biarch-compat.conf` | 56 | `4e3c617050427d51497a0e5969b0159421580cf5e7c9649e39f45b5e2fcb47b6` |

These are unbound inputs to the host `ldconfig` generator. The existing compile
namespace consumes the generated `/etc/ld.so.cache`; it does not expose those
configuration files themselves. The retained cache evidence contains only its
size/type/mode/hash, without its semantic entry map or actual library-selection
trace. This establishes an incomplete generator-input binding, **not proof that
a client selected a foreign library**. Promoting the observed cache hash to an
expected value would leave that gap open. Upstream glibc 2.39's
[`ldconfig.c`](https://sourceware.org/git/?p=glibc.git;a=blob;f=elf/ldconfig.c;hb=refs/tags/glibc-2.39),
[`dl-cache.c`](https://sourceware.org/git/?p=glibc.git;a=blob;f=elf/dl-cache.c;hb=refs/tags/glibc-2.39)
and [`dl-load.c`](https://sourceware.org/git/?p=glibc.git;a=blob;f=elf/dl-load.c;hb=refs/tags/glibc-2.39)
support this distinction; they are semantic references, not an attestation of
the exact downstream Ubuntu build.

The 22 retained file differences have separate roles. Seven are directory
aliases, subject to the existing fixed usrmerge rules where relevant. Twelve
have identical file bytes but different permissions on privileged utilities
outside the declared client tool entrypoints. Eleven match after the archive
inventory's `0777` mask; the D-Bus launcher is specifically `04754` versus archive
`0755`, so a mask-only exception would be incorrect. None receives blanket
execution approval. The three retained conffiles, `/etc/security/limits.conf`,
`/etc/sysctl.conf` and `/etc/systemd/system.conf`, are absent from the build
namespace's `/etc` mounts. All 51 observed font-configuration paths have fixed
package owners; the actual selected font corpus remains unproven.

Existing full-tree guards cover the materialized Node/npm/Firefox trees and
the Flutter SDK, including its narrow mutable-metadata rules. The sandbox still
exposes the complete read-only host `/usr`; those guards do not close the used
host executable/library/header/font/configuration inputs. The new fixed build
lock remains absent, and `load_build_lock` is an unwired fail-closed helper for
that future path. Historical build modes retain their existing behavior.

The fixed-data replay under Weather's local
`.git/ci-evidence/p13c-20261027/implementation/` verifies the retained artifact,
projection, source/input digests and approved top-level include before reporting
`UNBOUND_LDCONFIG_INPUTS` (expected exit 2). It is an inert diagnostic, not a new
production binding guard or admission. No additional hosted run is justified
by this replay alone.

P13 remains incomplete and P14/P15 compilation remains blocked. The next
contract must close visibility or file-use enforcement within the existing
bwrap harness and bind the relevant loader resolutions to independently
authorized executable/library/configuration inputs, including a semantic cache
rule and the selected fonts. That boundary must be reviewed before new build
execution; another installation inventory or an observed-hash pin cannot
establish it. No new rootfs/platform, consumer admission or output acceptance
is introduced by this checkpoint.
