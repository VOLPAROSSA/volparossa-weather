# P15 Overmorrow candidate, 2026-10-28

**P15b update:** the missing tool input closure is now bound to the original SDK
archive. Independent implementation review approves exactly one bounded candidate
execution. The candidate execution is pending. The first-stop record below is preserved as historical evidence.

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
