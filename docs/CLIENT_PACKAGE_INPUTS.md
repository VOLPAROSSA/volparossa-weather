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
