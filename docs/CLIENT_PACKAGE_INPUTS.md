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
