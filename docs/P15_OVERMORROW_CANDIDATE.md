# P15 Overmorrow candidate, 2026-10-28

**P15c status:** the exact package hook closure is now identified and narrowly
authorized for the original web and Linux-test profiles. Independent review
approves one bounded manual attempt. Actual P15c execution is pending; the failed
P15b evidence below remains preserved. P13, P14 and Core stay unchanged.

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
