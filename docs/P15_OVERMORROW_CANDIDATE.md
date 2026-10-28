# P15 Overmorrow candidate, 2026-10-28

**P15e preflight:** the exact pinned producer spells desktop plugin targets as
absolute package roots with one trailing slash. A P15-only identity binding
authenticates the original packages and exact aliases, then checks the same
file identities inside the unchanged compile Boundary. All 177 relevant inert
tests pass; independent implementation review approves exactly one newly
authorized hosted attempt. No application build is claimed yet.

## P15e: exact plugin targets and namespace identities

The original [P15d run 40726035128](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40726035128)
and its independent review are reused unchanged. They establish successful
offline tool/app pub and a strict raw plugin-target rejection before source
sealing. Neither the first rejected alias owner, its actual raw bytes nor the
scanner order was retained. Those historical details cannot be recovered from
that artifact and are not inferred from producer generation order.

The necessary producer source was read only as data and matched to the original
17,240-file SDK inventory and the already pinned `path 1.9.1` and
`package_config 2.2.0` archive/membermap identities. No SDK/Dart code or sandbox
ran locally. `package_config` resolves absolute directory URIs and preserves
one trailing slash; POSIX `path.fromUri()` decodes the URI path without removing
it. Flutter preserves that path in plugin metadata and passes it directly to
`Link.createSync()`. The producer target is therefore exactly
`/state/pub-cache/hosted/pub.dev/<name>-<app-version>/`. The old guard expected
the spelling without the final slash. Only the reviewed producer spelling is
now admitted; relative paths, the no-slash spelling, extra slashes, traversal,
encoded aliases, wrong versions and other roots are rejected.

The new [plugin record](../third_party/overmorrow-plugin-inputs-v1.json), SHA256
`e30efbcab48d215b1a545727d075a63692b8bbca5b23d6c09d629b07838b2d9e`,
reuses 13 original complete package membermaps, exact app versions/archive
hashes/pubspecs and 16 source-derived alias definitions. There are eight Linux
and eight Windows entries, including eight Dart-only entries: Flutter creates
links for all desktop metadata rows, not only native-build rows. Actual alias
presence is conditional on the original project platform roots (Windows also
requires `CMakeLists.txt`), using the original default feature settings.

The original `.flutter-plugins-dependencies` desktop rows must exactly match
their source-derived names, paths, dependency lists, native flags and dev flags.
Full post-pub dependency/configuration/plugin verification runs before alias
admission. Original source and generated-file checks remain active.

The [P15 plugin helper](../scripts/prepare_hosted_overmorrow_plugins.py) captures
cache/package/file identities before pub. It walks directories with
`O_DIRECTORY|O_NOFOLLOW`, reads files through bounded no-follow descriptors,
authenticates complete membership/bytes/hashes/modes, and rejects inode or
directory replacement even with identical bytes. Each alias inode is held via
Linux `O_PATH|O_NOFOLLOW` and read with `readlinkat`; its raw target is never
opened. Only the separately authorized cache/package path is opened through
non-following components. Persistent host ancestor identities, sealed alias
identities and pre/post checks prevent path substitution. There is no generic
`resolve()` approval or whole plugin-directory exception.

A private hash- and identity-bound plan carries that original baseline through
the existing `/state` mount. The same pure-stdlib helper runs inline through the
unchanged compile Boundary, comparing the actual stage/cache/private bind roots
and every selected package/file identity to the host baseline. Different
namespace prefix-directory identities are not confused with bind-root identity.
The plan is checked before and after each proof. The public proof contains only
controlled alias/package/version identities, original source/membermap hashes
and fixed booleans; rejection metadata contains a controlled alias identity,
target form, length and hash, never a raw target, host path or environment.
No shared source export, sandbox mount, capability or runtime helper changes.

Validation: 177 relevant inert tests pass, including 33 plugin tests and the
existing 31 candidate tests. Coverage includes actual producer spelling,
absolute/relative variants, versions, escapes/chains, unknown/missing/extra
aliases, changed bytes, identical-byte inode replacement, ancestor/private-plan
replacement, FD cleanup, incrementally bounded scans, single sealing and the
actual probe main/response protocol with an inert namespace-path mapping.
The separate real-data proof authenticates all 13 original archives, 5,381,052
expanded bytes, all 16 aliases and repeat identity checks; all temporary
materialized package data is removed. This is source/data proof, not a real
namespace, hook or application build claim.
The exact SDK lifecycle source also confirms that the fixed `test --no-pub`
and `build web --no-pub` paths skip desktop platform regeneration; they do not
require resealing recreated aliases. Runtime identity checks remain active.
This bounded source proof has SHA256
`35184197ab04181071a91ca2332961d89b02014ab7aafa2414b0f774873c2238`.

Independent source/data review SHA256:
`0dfaa89f85d071ad6b6edb5a5a3d5d7ecdd8400ba18258bc4f8137c4a19a2ca5`.
The independent final implementation review, SHA256
`10c8bc36e56547b521efac33a9fcec51c62360c18eba6639ccc072cf46851791`,
repeats 64 affected tests, verifies all six changed executable/data/test inputs
and gives GO for exactly one bounded manual attempt with no open findings.
Private evidence is retained in `build/p15e-investigation/`,
`build/p15e-inert-tests/` and `build/p15e-review/`. Earlier failures remain
separate. No P13/P14/Core change, dependency upgrade or release follows.

## P15d: immutable SDK index and Git 2.43.0

The original [P15c run 40718328100](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40718328100)
artifact and independent review are preserved unchanged. That artifact lost the
structured Git command failure: its historical exact command/exit status cannot
be recovered directly. The following is an exact-input local reproduction,
consistent with the proven failure location before Dart, not newly recovered
historical stderr.

The original SDK archive was acquired as inert data at its unchanged fixed URL,
length and SHA256. Its complete 17,240-file inventory again matches P13's
`98df602485d0dd66195f614e950dc59ed3f7dddf5169431ece5a4c2a92ace5c7`.
Only Git runs locally; no Flutter, Dart, pub hooks, application code or sandbox
starts locally.
The previously authorized Ubuntu package `git 1:2.43.0-1ubuntu7.4` was privately
extracted without installation or lifecycle scripts: 3,680,654 bytes, SHA256
`c79b7948ef9860c97ec74293a90178676e63368a0711c95c28a55af4edf1adab`.
Its Git binary has SHA256
`eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201`.
Local host libraries differ from the hosted Ubuntu runtime; this is a targeted
Git reproduction, not another P13 runtime acceptance claim.

Under the original helper's exact `PATH/LANG/LC_ALL` environment, Git 2.43.0
returns `rev-parse HEAD: 0`, `diff --quiet HEAD --: 1` (zero output bytes), and
`ls-files --others bin/internal: 0` (zero output bytes). Git 2.47.3 returns zero
for all three on the same data. The actual commit remains
`f6ff1529fd6d8af5f706051d9251ac9231c83407`. All 31 original Git files and their
exact file closure remain unchanged during these fixed checks.

The archive index is version 2 with 15,102 entries. Every tracked path, blob ID,
Git mode, size and index flag matches after a diagnostic stat refresh; only
cached ctime, device, inode and mtime nanoseconds differ. An initial local
environment probe used the broader sandbox environment and was superseded by
the exact-helper-environment probe. One subsequent diagnostic variant omitted
`diff.autoRefreshIndex=false` and inadvertently refreshed only the temporary
local index despite `--no-optional-locks`. That failure and the refreshed index
are retained privately. The original index was restored from the authenticated
archive and all 17,240 original file bytes/modes and the exact closure rechecked.
Index refresh is **not** the implemented correction or an allowed build step.

Git 2.43.0's stat-based `--quiet`/`--exit-code` result is unsuitable with this
immutable producer index: even `--exit-code --patch` returns one with an empty
patch. The P15 controller recognizes only the adapter's exact fixed SDK diff
call and substitutes `diff --patch --no-ext-diff --no-textconv HEAD --`.
It requires both successful command execution **and exactly empty combined
output**; every patch, diagnostic byte, nonzero exit, deadline or output limit
fails closed. External diff/textconv execution is explicitly disabled.
`--no-optional-locks`, `diff.autoRefreshIndex=false`, disabled Git hooks, the full
HEAD/path scope and original command deadlines remain intact. The original
adapter, helper, source commit checks, bootstrap-file check, complete SDK/cache
inventories, dependency locks and hook policy remain unchanged.

The P15-only proxy also records fixed command names, typed failure categories,
exit status, output length and SHA256. It exports no raw Git output, command
paths, tokens or environment values. Source receipts still require all three
commands; unknown commands or deadlines are rejected.

Validation: 144 existing relevant inert tests pass, including 31 candidate tests.
An additional exact Git 2.43.0 check executes the actual proxy on the original
SDK and nine fresh inert Git fixtures: clean stale stats pass; same-size and
same-mtime content changes, executable-bit changes, deletion, binary changes,
symlink type changes, rename, staged new source and staged changed source fail.
The original SDK Git closure and every fixture's Git metadata remain unchanged
during the comparisons; fixture processes drain and temporary fixtures are
removed. Independent implementation review is recorded before any dispatch.
The independent review has SHA256
`781d088af09b8b40b3c3878df555d7ed9d6fe8661c84d2f472d754e5b92bf160`:
no findings; GO for exactly one manual bounded attempt on candidate source SHA256
`7d48bbeb3a50c9407aa4cb6e88941ca64b0d16b33a7b7db34391cff95ed59f72`.

Private evidence remains under `build/p15d-investigation/`,
`build/p15d-sdk-data/`, `build/p15d-inert-tests/` and `build/p15d-review/`.
P13, P14, Core, shared pins/helpers and all dependency versions are unchanged.
No build success, reproducible output or production admission follows from
these inert results.

### Hosted P15d result

Exactly one [P15d run 40726035128](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40726035128)
was dispatched, manual attempt 1 at executable source
`13a7c62f2c5d2c4781cd633f2175b85fe872fb5e`. All 106 hosted inert tests passed
(19 hook, 31 dependency, 31 candidate, 13 build-contract and 12 deploy tests).
The nine SDK-Git receipts are three complete `rev-parse`/`diff`/`ls-files`
triplets, all exit 0. The original SDK/source/dependency checks therefore passed
before tool resolution, after tool resolution and before application resolution.

Five recorded sandbox steps returned exit 0 and drained: cache generation,
cache listing, compile preflight, `p15-tool-pub-offline` (258 ms), and
`p15-pub-offline` (1,302 ms). The actual offline Dart tool resolver completed;
the generated 102-package tool configuration and graph were reauthenticated
against the original inputs. The 224 original cache archives, original SDK
inventory and tool lock remained bound at that verification. All ten compile
isolation/negative flags were true. The two pub steps' `sdk_download` diagnostic
booleans are only matches for the coarse `(Downloading|download failed)` log
pattern, not evidence of a download. Both commands retained `--offline` and the
unchanged compile Boundary with external networking unavailable.

The next check failed closed with category `ValueError`, code
`P15_PLUGIN_SYMLINK_TARGET`, phase `p15-pub-offline`. `seal_app_sources()` calls
the existing `source_files()` guard, which requires each admitted generated
Linux/Windows plugin symlink's literal target to match its exact original
application-cache package/version root. The rejected package and actual target
were not retained. A relative path, trailing separator, changed version or
other cause is **not established**; the guard was not relaxed.

Application pub exit 0 does not complete application input acceptance: source
sealing and the post-app-pub generated configuration/plugin/dependency/SDK
rechecks were not completed. The retained `dependencies_final` receipt is the
last successful **pre-app-pub** check, with tool state authenticated but
application generated/plugin bindings still null. No test fixtures, hook
authorization, Flutter tests or application compilation were reached. There is
no accepted build output or generated-output notice/asset result.

Artifact `12834260731` is the original 2,868-byte ZIP, SHA256
`6d1b5e0818a18d3dd1ecafadc6b05229d6c4a9193cb5a218d6453e1a92affbcd`,
matching the GitHub API digest. It contains exactly two bounded UTF-8 JSON
files; all six controller source hashes match the trial commit. Cleanup confirms
process drain, policy removal, private-input absence, stage absence, output
absence and unchanged host network namespace; both cleanup failure fields are
null. The locally extracted SDK/archive/Git package were also removed after
their data proof and original notices/index data were retained privately.
The independent result review has SHA256
`d2ed220ba58b95fc13d85371b1b3131a17c56f5f23d7ec1e79d619d7f1e9d84b`.
It confirms the SDK-Git resolution, actual pub progress, new closed stop and
cleanup, while retaining the application-integrity and diagnostic limits above.

The remaining dependency is a separate, inert review of the generated plugin
alias contract and its actual target representation. There is no second P15d
attempt, automatic merge, output/reproducibility admission or production release.
The SDK-Git blocker is resolved; the first successful Overmorrow candidate and
hook runtime remain unverified.

## Initial P15 stop (preserved evidence)

**Status: blocked before the first hosted candidate build.** No P15 application
was compiled, no hosted run was dispatched, and no application/output/consumer
or production admission was granted. The one authorized hosted attempt remains
unused. This is a new application-build dependency/state gap, not a rejection
of the independently accepted P13 runtime boundary.

## Isolated source and reused evidence

The private P15 worktree is
`.volparossa-dev/worktrees/p15-overmorrow-candidate-20261028` in the coordinating
workspace, branch `build/p15-overmorrow-candidate`. It starts at exactly Weather
`e774912e292f339d42ff23f00b4d8fc5d69e5b47`.

The successful [P13 run 40596738646](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40596738646)
was checked against that exact head, manual attempt 1. Its application jobs were
skipped. The original independent acceptance report has SHA256
`3a2988ab6f00ecee1ece59c00c9f1c169c7ef054da4d05fdba7848680bcbd4a9`
and decision `PASS_SHARED_REPRODUCIBLE_CLIENT_RUNTIME_BOUNDARY`. Its 242 exact
installed package identities, runtime/SDK/source/loader/font bindings, negative
controls and cleanup are reused. None of those P13 runtime diagnoses was rerun.

P14 already has its own worktree and an unfinished source-export manifest change.
P15 changed no P14 file, shared manifest, source pin, runtime helper, Core file,
P13 branch or PR #33. Only this report is a tracked P15 change. No P15 PR is
needed for the stopped preflight; nothing is pushed or merged.

## Exact proposed inputs and build

| Input | Identity |
| --- | --- |
| Upstream | [bmaroti9/Overmorrow](https://github.com/bmaroti9/Overmorrow/tree/97995e2e00e454389e00e35f1e65654afe3e8bed), version `2.6.4+64` |
| Commit / tree | `97995e2e00e454389e00e35f1e65654afe3e8bed` / `b9abc6bd3d50e3ec6442a8f19e65fd1c92feef4c` |
| Original pub lock SHA256 | `fdfb5275aac49a1a62f7424a665f88b7db6fe1314d1e7c9f037ad6d32d906ce3` |
| Flutter / Dart | `3.38.5` / `3.10.4`; Flutter commit `f6ff1529fd6d8af5f706051d9251ac9231c83407` |
| Flutter archive SHA256 | `a264940cfc431c1778f34f7413fa6ab71443ad52c71f38c50b0284397a4039b0` |
| Application dependencies | Original 152 exact pub.dev archives and five SDK references; no version changes |
| Package-input record SHA256 | `42fa6761fa56b2b7beb80a493100ec3d65ffd7c61a47e23622d735e874e1328e` |

Inert staging verified the exact upstream commit/tree, canonical integration
patch, original lock and license, overlay and source-notice preparation.
The upstream license remains GPL-3.0-or-later; original integration files retain
GPL-3.0-only. NotoSans retains OFL, and unchanged MaterialIcons retains CC-BY-4.0
and attribution. The staged NotoSans hash matches the existing notice record:
`a33452e68cae1307a4b168c501e12d143e18c210db45102d2e8d852ce7986bb5`.
Generated Flutter notices and actual output asset/font equality remain untested.

The proposed host controller would use the unchanged live `Boundary`, `View`
and resolver APIs, authenticated data-only app-cache materialization, offline
locked pub resolution, the existing 24 Flutter tests and a release **web** build
using `source_web_arguments()` (`--no-tree-shake-icons`). It would preserve the
full MaterialIcons font, original asset bytes and notices, export closed metadata
only and drain processes/remove policy before private cleanup. Android, release
publication and consumer admission are excluded. This plan was **not approved
for execution** after the following dependency check.

## Concrete new blocker

The existing Overmorrow adapter creates empty private Flutter-tool state and
binds it over `packages/flutter_tools/.dart_tool`; see
[`prepare_tool_state()` and `sandbox()`](../scripts/prepare_hosted_overmorrow_ci.py).
In the exact pinned Flutter source:

1. [`PubDependencies.isUpToDate()`](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/packages/flutter_tools/lib/src/flutter_cache.dart#L84)
   rejects the missing tool `package_config.json`. Its `update()` invokes
   `pub.get` for `packages/flutter_tools`.
2. [`FlutterCommand.verifyThenRunCommand()`](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/packages/flutter_tools/lib/src/runner/flutter_command.dart#L1705)
   updates universal artifacts before the application command. `--no-pub` does
   not bypass this tool-cache check. `PackagesGetCommand` uses
   `ArgParser.allowAnything`; its permissive offline parser runs later, so an
   application `pub get --offline` alone does not prove tool initialization
   is offline. Network isolation must remain enforced.
3. [`_getPubCacheIfAvailable()`](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/packages/flutter_tools/lib/src/dart/pub.dart)
   returns the explicit `PUB_CACHE` directly. Possible SDK preload contents
   therefore do not automatically populate this isolated cache.
4. The [exact Flutter-tool pubspec](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/packages/flutter_tools/pubspec.yaml)
   requires inputs absent from the app-only cache:

| Package | Flutter tool | Original Overmorrow app lock |
| --- | --- | --- |
| analyzer | 8.2.0 | 10.0.1 |
| archive | 3.6.1 | 4.0.9 |
| http | 1.5.0 | 1.6.0 |
| hooks | 0.20.1 | 2.0.2 |
| code_assets | 0.19.7 | 1.2.1 |

The app-only closure cannot initialize the tool state. No network fallback,
dependency substitution, invented tool configuration or cache-check bypass was
introduced. The independent reviewer confirmed **NO-GO before hosted execution**.

The required follow-up is a separately reviewed binding of the exact
Flutter-tool dependency closure and generated tool state. First inspect the
original pinned SDK's generated tool lock and possible preload inventory as
data; bind every used package and configuration before execution through the
existing Boundary. This finding does **not** establish that a shared P13 runtime
helper change is necessary. The SDK and app pins need not be changed merely to
add that missing evidence.

## Checks, custody and outcome

- 13 existing inert build-contract tests and 12 deployment tests passed.
- 15 inert tests passed for the unadmitted app-dependency materializer draft.
  These cover preparation/verification guards, not actual pub/Flutter execution.
- Independent source/plan review confirmed both the feasible isolated API route
  and the new tool-initialization blocker. No runtime success is inferred.
- Six exact Flutter source files were retained as inert text with URLs, lengths
  and SHA256 values. The listed version differences were checked directly against
  the original pinned application package record.
- An initial local notice read correctly rejected group-writable checkout
  metadata. Only P15 checkout permissions were tightened; source bytes and guards
  were unchanged. Subsequent inert source-notice preparation passed.
- Own temporary upstream/source stages and test fixtures were removed. No SDK,
  package installation, sandbox child or AppArmor policy was started locally.
  Text evidence, source hashes and explicitly unadmitted implementation drafts
  remain in this worktree's ignored `build/p15-preflight/` directory. Drafts were
  moved out of production script/test paths and are not runnable build authority.

P15 is **not ready for further build/output acceptance**. A successful first
candidate build has not occurred; reproducible output verification would require
separate independent cold-build evidence, and production admission remains a
different gate even after both succeed.


## P15b: original Flutter-tool input closure

The original SDK archive was read as inert data, with the existing fixed URL,
1,464,510,340-byte length and SHA256. Its complete 17,240-file inventory exactly
matches the independent P13 inventory
`98df602485d0dd66195f614e950dc59ed3f7dddf5169431ece5a4c2a92ace5c7`.
No SDK, compiler, package or lifecycle code was executed locally.

The archive contains the generated `packages/flutter_tools/pubspec.lock`
(23,744 bytes, SHA256
`246d46461bdfa97d5734a188d16fc2741dddc88d111eeb49dfe6bc6087bc771f`)
and all 101 matching hosted toolarchives within its 165 preloadarchives.
Independent data review reconstructed all archive/member/notice bindings:
83,036,099 expanded bytes, 8,332 regular source files and 110 original notices.
There are no automatic hook entrypoints or missing notices in this toolclosure.

The new P15-only [tool input record](../third_party/overmorrow-tool-inputs-v1.json)
binds every exact tool version, archive, complete canonical membermap and notice
back to those original SDK bytes. The existing app package-input record and both
upstream version sets remain unchanged. Tool-only notices are accounted for
separately from the application's generated `assets/NOTICES`.

The chosen combination is the original Flutter 3.38.5/Dart 3.10.4 toolclosure
alongside the original Overmorrow app lock: 101 toolarchives + 152 apparchives,
29 identical shared identities, 224 unique archives. The 72 extra tool identities
include 19 additional versions of app package names and 53 tool-only names.
The shared 29 archives are reused from authenticated SDK preloads; only the
remaining 123 original apparchives use the existing controlled acquisition path.
No cache replacement or new tool archive URL is authorized.

The actual tool package state is generated by the pinned Dart runtime, through
the unchanged P13 compile sandbox, before any Flutter artifact initialization:

```text
dart --suppress-analytics pub --directory <sdk>/packages/flutter_tools \
  get --offline --enforce-lockfile --no-precompile --no-example
```

The SDK source and original tool-lock stay read-only; only the existing private
`.dart_tool` overlay is writable. Real pub output is checked against the exact
101 packages plus `flutter_tools`, original source language versions and allowed
logical cache/SDK roots. App state is independently checked against its original
157 references. Cache membermaps, locks, SDK, generated state and plugin roots
are checked around the compiler phases. No hand-written packageconfig, online
pub, broader mount or cache-check bypass is introduced.

The manual `source-candidate-build` mode is limited to attempt 1, 2,400 seconds
with TERM/cleanup grace and a 45-minute job deadline. It retains only two closed
JSON files. A first release web candidate and the existing 24 Flutter tests are
planned; no Android build, browser product admission, second cold build or merge
is authorized by this mode. Output success also requires original fonts/assets,
complete generated notices and confirmed process/policy/private-data cleanup.

<details>
<summary>Exact 72 additional tool identities relative to the app lock</summary>

```json
{
  "_fe_analyzer_shared": "89.0.0",
  "analyzer": "8.2.0",
  "archive": "3.6.1",
  "async": "2.13.0",
  "browser_launcher": "1.1.3",
  "built_value": "8.12.0",
  "cli_config": "0.2.0",
  "code_assets": "0.19.7",
  "code_builder": "4.11.0",
  "completion": "1.0.2",
  "coverage": "1.15.0",
  "crypto": "3.0.6",
  "csslib": "1.0.2",
  "dap": "1.4.0",
  "dart_service_protocol_shared": "0.0.3",
  "dart_style": "3.1.2",
  "data_assets": "0.19.3",
  "dds": "5.0.3",
  "dds_service_extensions": "2.1.0",
  "devtools_shared": "12.0.0",
  "dtd": "4.0.0",
  "dwds": "25.1.0+2",
  "extension_discovery": "2.1.0",
  "ffi": "2.1.4",
  "file_testing": "3.0.2",
  "flutter_template_images": "5.0.0",
  "frontend_server_client": "4.0.0",
  "hooks": "0.20.1",
  "hooks_runner": "0.23.0",
  "html": "0.15.6",
  "http": "1.5.0",
  "http_multi_server": "3.2.2",
  "io": "1.0.5",
  "js": "0.7.2",
  "json_annotation": "4.9.0",
  "json_rpc_2": "3.0.3",
  "mime": "2.0.0",
  "multicast_dns": "0.3.3",
  "mustache_template": "2.0.1",
  "native_stack_traces": "0.6.1",
  "node_preamble": "2.0.2",
  "petitparser": "6.1.0",
  "pool": "1.5.2",
  "process": "5.0.5",
  "pubspec_parse": "1.5.0",
  "shelf": "1.4.2",
  "shelf_packages_handler": "3.0.2",
  "shelf_proxy": "1.0.4",
  "shelf_static": "1.1.3",
  "shelf_web_socket": "2.0.1",
  "source_map_stack_trace": "2.1.2",
  "source_maps": "0.10.13",
  "source_span": "1.10.1",
  "sprintf": "7.0.0",
  "sse": "4.1.8",
  "standard_message_codec": "0.0.1+4",
  "sync_http": "0.3.1",
  "test": "1.26.3",
  "test_core": "0.6.12",
  "unified_analytics": "8.0.5",
  "usage": "4.1.1",
  "uuid": "4.5.1",
  "vm_service": "15.0.2",
  "vm_service_interface": "2.0.1",
  "vm_snapshot_analysis": "0.7.6",
  "watcher": "1.1.4",
  "web_socket": "1.0.1",
  "web_socket_channel": "3.0.3",
  "webdriver": "3.1.0",
  "webkit_inspection_protocol": "1.2.1",
  "xml": "6.5.0",
  "yaml_edit": "2.2.2"
}
```

</details>


P15b pre-dispatch validation: 108 relevant inert tests passed (31 dependency,
14 controller, 30 existing source-recipe, 8 existing workflow, 13 build-contract
and 12 deployment tests). The independent reviewer repeated the 45 new tests
and approved the exact final source hashes for one manual candidate run.
No runtime/application success or output admission follows from these tests.


## P15b hosted result: safe stop before Dart/pub

[Run 40708766504](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40708766504),
manual attempt 1, used exact source
`21d0543c833f32d5ac09f12f916d3636f9807b68`.
The hosted inert contracts passed. The controller stopped in
`controlled-pub-data` with `P15_UNREVIEWED_PACKAGE_HOOK`. Only the two native
loader-cache generation/list commands executed (exit 0, returned and drained).
No Dart tool resolver, app pub, Flutter tests, web compilation or browser trial
was reached. The four other workflow jobs were skipped. This consumes the one
authorized hosted attempt; no automatic or additional run was performed.

Artifact `12826345872` contains exactly two bounded UTF-8 JSON files. Its original
ZIP SHA256 matches the GitHub API digest:
`2dc82744a15a3dd35e38380d65a149bf65b63aad47c259e47da482d068808b31`.
Independent result review verified the ZIP, exact run/source/recipe hashes,
original failure and all six cleanup flags: process drain, policy removal,
private-input absence, source-stage absence, output absence and unchanged hosted
network namespace. Neither result has a cleanup error. This verifies a safe
failed attempt, not build acceptance or successful toolstate generation.

The original ZIP, API/run/job records, job log and extracted metadata are retained
privately under this worktree's ignored `build/p15b-hosted/` tree. The inert SDK
archive and 165 preloadarchives were removed after digest rechecks; original text
locks, inventories and independent data-review receipts remain. No SDK/package
code was executed on the development host and no host network configuration was
changed. No compiled binary or historical artifact was published.

### Narrow remaining hook issue

Separate inert inspection of the original `objective_c 9.5.0` archive establishes
an additional automatic app hook at `hook/build.dart`. Its archive is 421,127
bytes, SHA256
`b7fb95a6d9a4f009edd63dc5ac69f07420b23a16161c6dd8660290b59c602e8e`.
All 283 members were independently inventoried; the complete canonical membermap
SHA256 matches the existing app record:
`7baaadb633c7285b5d140089e34a21a6f06e61c61607d9140c73c61175c75f24`.
The 7,018-byte hook has SHA256
`aa8cd26a22f3d5f7cb1e769f6de647bae2b485db4576a43743c20f9a34301f7e`.
The original package license, pubspec and hook bytes were preserved privately;
no hook code was executed. The archive and independent receipt are kept under
`build/p15b-blocker/`.

The callback checks `buildCodeAssets` and iOS/macOS before native source scanning
and `clang`/`xcrun` calls. Imports and `hooks.build(args, callback)` precede those
callback guards. This is not proof that the hook is never compiled, loaded or
executed for web or Linux Flutter tests. The hosted artifact contains no package
name, so it does not establish that `objective_c` was the first rejected archive.
No broader application-archive scan or hook execution was started after this stop.

The next bounded acceptance step is independent review of this exact app hook's
imports, protocol and actual activation for the intended web/test targets, while
retaining the pinned versions, source guards and sandbox. Do not bypass the hook
guard, substitute versions or start a wider Flutter/native rebuild. Any further
hosted attempt requires new authorization.

The P15b source/input implementation is on draft
[PR #35](https://github.com/VOLPAROSSA/volparossa-weather/pull/35), based on the
unchanged P13 branch/PR #33. Its changes do not overlap P14 #34. Actual offline
toolstate, a successful first application build, independent cold-output
reproducibility and production/consumer admission remain unverified.


## P15c: exact package hooks and first rejection

The full original 224-archive union contains exactly one automatic hook:
`objective_c 9.5.0 / hook/build.dart`. All 123 app-only archives were independently
rehashed and their full original membermaps reconstructed. The 101 tool and 29
shared archive bindings reuse the already independently verified SDK evidence.
All original notices remain preserved. No source/dependency version changed.

Replaying the exact source `21d0543` ordering (SDK-preload identities first, then
app-only identities sorted by key) places this sole predicate match at index 164
from zero, the 64th app-only archive. Therefore it is the first rejection under
that implementation and those exact original inputs. This is a deterministic
source/data reconstruction; the historical hosted artifact itself did not carry
a package name. Both the former broad predicate and exact automatic-entrypoint
inventory contain no other match.

The [P15-only hook record](../third_party/overmorrow-hook-inputs-v1.json), SHA256
`5e3837532d2c6f5638f0125aa24e3daa87f87f3b951a3cb79eafc0968a6d3121`,
binds all 224 original archive/membermap identities, the one original hook's
7,018 bytes and SHA256, its pubspec, BSD-3-Clause notice, original SDK/app/tool
pins and two fixed profiles. Unknown archives, hook paths, versions, hashes,
link hooks and target/feature/environment overrides remain rejected.

### Actual web and test relevance

Exact Flutter `f6ff1529fd6d8af5f706051d9251ac9231c83407` and
`hooks_runner 0.23.0` plan transitive hooks independently of Dart import usage.
Both the release web build and the existing Linux-x64 Flutter tests may compile,
load and execute this hook. Silently pruning the Darwin package or assuming its
callback guards eliminate hook execution would be incorrect.

The relevant tool `hooks 0.20.1` and application `hooks 2.0.2` generated base
protocol schemas are byte-identical (SHA256
`b8afff0aaf9e455d2203cf68c219780206002f28eb81f0a880c5eaac3a176cf1`).
The original application package configuration selects the hook's original
`hooks 2.0.2`, `code_assets 1.2.1` and `logging 1.3.0` imports. Original package
membermaps and SDK source remain reverified around execution.

The exact permitted profiles are:

- `web-js-empty-code-assets`: no code-asset extension, `build_asset_types=[]`,
  linking enabled at protocol level but no link hook or emitted assets.
- `linux-x64-tests-no-native-output`: code-assets extension for Linux/x64,
  dynamic preference, no C compiler configuration and linking disabled. The
  callback rejects Linux before native source scanning or compiler access.

The hook and protocol are explicitly authorized to run inside the unchanged
Boundary. The source proof includes imports, top-level logger setup and
`hooks.build()` before callback guards. They read the controlled input and create
private checksum directories and a successful JSON result even for a no-op.
`clang`, `clang++`, `xcrun`, Apple SDKs, native compilation and native output are
not authorized or added. The original Flutter-test compiler discovery permits
missing `clang++`; it returns no compiler configuration for this profile.

### Enforcement and evidence

[The hook controller](../scripts/prepare_hosted_overmorrow_hooks.py) binds exact
original commands and their purged environment before execution, requires fresh
state and unchanged root pubspec without hook user-defines/workspace/overrides,
and permits only the two profiles. The existing SDK/lock/cache/package-config
checks and source sealing remain preventive input authority; generated files do
not authorize new code, targets or cache inputs.

After tests and web compilation, bounded nofollow checks require exactly the
known Objective-C runner tasks (32-hex config checksum) and empty shared output
children (10-hex config checksum). Only the nine original runner files and an
empty task `out/` directory are allowed. Typed inputs must contain the exact
package/config/path fields, no user-defines or extra assets. Outputs must be the
exact successful empty-assets result. Linux's native-assets manifest must be
empty. Aliases, special/hardlinked files, native outputs, unknown task files,
path escapes, wrong targets and resource overruns fail closed.

Runner stdout contains its own command/environment/cwd line; it is bounded and
private, together with locks, timestamps, paths, PIDs, dependency stamps and
stderr. Public projection contains only fixed identities, profiles, counters and
success/rejection codes. Typed hook rejection observations now retain the known
package/version/entrypoint; a failed Flutter command is not itself claimed to
have reached the hook.

P15c pre-dispatch evidence: 64 new/affected inert tests passed and were repeated
independently (19 hook, 31 dependency, 14 candidate). Existing workflow/source
recipe checks also passed. Both author and reviewer passed all 123 original
app-only archives through the actual new archive/membermap/policy code, with
exactly one authorized hook. No package or SDK code ran locally. Independent
review of the exact executable bytes approved one manual bounded attempt, with
no retry or product/reproducibility/release admission.

Private evidence is retained under `build/p15c-hook-inventory/` and
`build/p15c-hook-review/`, including the complete immutable source-archive set,
original membermaps/notices, exact pinned protocol/runner/Flutter sources and
independent review. Earlier failed reports remain separate and unchanged.


## P15c hosted result: hook data gate passed, SDK-Git check stopped execution

The one authorized [P15c run 40718328100](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40718328100)
used exact commit `a0ab43f5890ff54a26c4594eeb7316f968693d40`, manual attempt 1.
The hosted preflight passed all 89 inert tests (19 hook, 31 dependency,
14 candidate, 13 original build-contract and 12 original deployment tests).
The four other workflow jobs were skipped.

Actual closed metadata verifies:

- All 224 original archives materialized and reverified: 152 app archives,
  101 tool archives, 29 identical reused SDK/app archives, five SDK references.
- Exactly one hook found and authorized. Original cache bytes and membermaps
  remained unchanged; the hook rejection from P15b did not recur.
- All ten existing compile-Boundary negative/isolation flags passed. Loader
  cache generation/listing and the compile preflight returned exit 0 and drained.
- Phase `p15-tool-pub-offline` stopped with category `CommandFailure` and public
  code `P15_OPERATION_FAILED`, before the corresponding `H.run` launch. No Dart
  command, hook kernel/protocol, Flutter test or application compiler executed.
- All six cleanup checks passed: process drain, policy removal, private inputs
  absent, stage absent, output absent, hosted network namespace unchanged.
  Both cleanup-error fields are null.

Artifact `12830565481` contains only two bounded UTF-8 JSON files. The original
2,423-byte ZIP SHA256 matches the API:
`21f7892042b6ed8e909463788599d279172de31fd2476c9c9a67c4ba18ea6b0f`.
Independent review checked ZIP contents, source hashes, exact run/attempt,
full-cache/hook-gate and preflight receipts and cleanup. Private original API,
job log, ZIP and independent result review are retained separately under
`build/p15c-hosted/`; no historical evidence was replaced or binaries published.

### Exact remaining evidence limit and decision

The source sets `p15-tool-pub-offline` before `verify_inputs()`. The failure
occurs before its source-receipt assignment. In that prefix, a helper
`CommandFailure` can originate from the three existing SDK Git calls in
`prepare_hosted_overmorrow_ci.py:verify_phase_inputs`: SDK `rev-parse HEAD`,
`diff --quiet HEAD --`, or `ls-files --others bin/internal`. Source pin mismatches
would use a different exception. Neither the closed artifact nor retained job
log identifies which Git call failed, its exit status, category or diagnostic.
The original helper has structured failure fields, but the candidate's generic
exception projection did not retain them. Do not infer a dirty SDK, hook failure,
resolver failure, changed upstream bytes or invalidated P13 acceptance.

Technical decision: keep the closed hook correction and its passing actual
224-archive data gate; stop before any source/permission change or forced build.
A further bounded task must establish the SDK-Git failure with P15-local typed
command/category/exit/hash diagnostics or independently retained original
failure data. This does not justify a broad Flutter rebuild, altered pins,
shared P13 runtime correction or automatic rerun. The P15c attempt is consumed.

[PR #35](https://github.com/VOLPAROSSA/volparossa-weather/pull/35) stays draft
above unchanged P13 PR #33. Hook execution, the first successful application
candidate, independent cold-build reproducibility, consumer/product acceptance
and release remain unverified. No automatic merge or release was performed.
