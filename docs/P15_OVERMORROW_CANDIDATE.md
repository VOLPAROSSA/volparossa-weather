# P15 Overmorrow candidate, 2026-10-28

**P15i preflight, 2026-10-31:** the complete hook-state contract is checked
jointly against original producers for test and test-plus-web lifecycles. The
shared-directory closure now requires both original 32- and 10-character names
per profile. The audit also corrects native signed-64-bit stamp bookkeeping,
requires both original compiler-stamp roles and strengthens generated-file and
phase/manifest checks. All 310 relevant inert tests pass. This task prepares
verification only: **no P15i hosted build, Flutter tests or web compilation is
started**. The latest actual runtime evidence remains P15h run 41225196544.

**P15h final result, 2026-10-31:** the corrected 32-character test task
identity passes hosted, and all 24 real Flutter tests pass. The next existing
check rejects `P15_HOOK_SHARED_CHECKSUMS`. The preflight missed the tool-side
eager creation of a second, 32-character shared child beside the app's
10-character child. This separate contract defect is recorded without another
code correction, authorization change or hosted retry. No web compilation runs;
all cleanup flags pass. P15 remains draft and has no successful full candidate,
verified reproducibility or product admission.

**P15g final result, 2026-10-29:** the cache correction is hosted-verified.
All 73 cache entries and six metadata files pass; all 24 actual Flutter tests
also pass. The existing post-test hook-state validation then stops at
`P15_HOOK_TASK_SET` for objective_c 9.5.0. No web build follows. Cleanup passes,
and no retry or new hook allowance is performed. P15 still has no successful
first web candidate, independently verified reproducibility or product admission.

**P15f final result: STOP at a new cache-integrity predicate.** The complete
post-pub filename set and four previously rejected Darwin outputs are identified.
The one real candidate attempt passes both offline pub commands and reaches the
closed metadata checks, then stops at `P15_PUB_METADATA_CACHE_HASH`. No fixtures,
hook profile, Flutter application tests or web compilation follow. All cleanup
passes. There is no successful first web build, reproducibility or product
admission; no automatic retry or code correction follows this new blocker.

**P15e result:** the plugin-symlink blocker is resolved in the one hosted
attempt. Both actual namespace proofs verify all 16 aliases against 13 original
packages and their file identities. Post-pub package/configuration/plugin
binding also passes. The full source check then stops at
`P15_UNKNOWN_GENERATED_SOURCE`, before hook authorization, Flutter tests or
web compilation. All six cleanup flags pass. No automatic retry followed.

## P15i: complete hook-state preflight for both profiles

P15i resumes exact head `bb1892d43d72c9f1d78a3cbfed854a6494ae1139` in the
existing isolated P15 worktree. The original failed reports, incomplete P15h
preflight proof, corrective addendum and independently reviewed hosted result
are preserved. The 224-archive/package policy, source/SDK pins, package versions,
P13 Boundary, sandbox permissions, P14 and Core remain unchanged.

### Exact shared-directory semantics

Runner `hooks_runner 0.23.0` uses tool `hooks 0.20.1`. During
`inputBuilder.build()`, the tool-side `HookInput` constructor eagerly evaluates
`outputDirectory`, creating a child named with the full 32-character checksum.
Executing original objective_c 9.5.0 uses app `hooks 2.0.2`, whose own constructor
creates a child with the first ten characters. Both hash the same original
compact UTF-8 configuration bytes. This is two producers sharing one parent,
not a new hook, native output or alternate configuration authority.

| Lifecycle | Task directories | Exact shared children |
| --- | --- | --- |
| test | `6b4ebf10e70ccf8d154076a186bfba3b` | `6b4ebf10e70ccf8d154076a186bfba3b`, `6b4ebf10e7` |
| test then web | preceding task plus `6782ff62a082d25dd9788598e67912e5` | preceding two plus `6782ff62a082d25dd9788598e67912e5`, `6782ff62a0` |

The relative shape is:

```text
.dart_tool/hooks_runner/
  objective_c/<config32>/
    .lock, input.json, output.json, hook.dill, hook.dill.d,
    hook.dependencies_hash_file.json, dependencies.dependencies_hash_file.json,
    stdout.txt, stderr.txt, out/
  shared/objective_c/
    .lock
    build/<config32>/
    build/<config10>/
```

The shared scan bound is exactly two children per authorized profile: two after
test, four after both profiles. Exact set equality is required, followed by
ownership/alias/permissions checks and emptiness of **every** short and long
child. All task `out/` directories remain empty. No arbitrary hexadecimal name,
other profile, unknown task, package version, native output or directory-wide
exception is authorized.

### Remaining protocol and state closure, audited together

| Check family | Original producer and accepted contract |
| --- | --- |
| Freshness, phase order, root source | Fresh private state; original pubspec SHA256, no user-defines/workspace overrides; test precedes web. |
| Owner/task names | Exact Objective-C owner plus shared root; exact original profile checksums; unknown/missing/extra tasks denied. |
| Shared owner and lock | Exactly `.lock` and `build`; private bounded single-link lock retained until stage cleanup. |
| Shared children | Both eager constructors; exact 32+10 names for every completed profile. |
| Native output | All task `out/` and all shared children empty; original callback returns before Linux/native work or when web has no code assets. |
| Task files | Exactly nine original runner files plus `out/`; missing or extra files denied. |
| Ownership, paths, file identity | Owned non-writable-by-group/others directories, owned single-link regular mode-0600 files, no aliases/special files, bounded reads. |
| Kernel and depfile | Original SDK compiler produces nonempty kernel and depfile; fixture payloads are inert structural representatives, never executed binaries. |
| Input protocol | Exactly six fields: original `config`, empty `assets`, exact owner/root/output/shared-parent paths; no user-defines or extra fields. |
| Output protocol | Exactly empty `assets_for_linking`, `status=success` and timestamp; no extra assets/dependencies/failure payload. |
| Timestamp | Original app helper truncates to whole seconds before local DateTime serialization; bounded valid timestamp with zero microseconds. |
| Logs | Private bounded stdout may include original runner command/environment metadata; stderr empty for these successful no-op profiles. |
| Compiler stamp | Original runner retains app package-config and SDK version plus SDK compiler inputs; no environment rows, duplicates or external paths. |
| Dependency stamp | No files for empty callback outputs; exactly HOME/PATH from the existing purged environment. |
| Stamp integer type | Exact native signed-int64 representation of original MD5 bookkeeping; booleans and out-of-range integers denied. |
| Linux manifest | Exact empty `format-version:[1,0,0]` / `native-assets:{}` after test and retained unchanged after web. |
| Web build state | Original web target tree has no `InstallCodeAssets`; writes are under its existing web/build roots, not extra hook state. Separate source/output contracts remain authoritative. |
| Cleanup | Original process/policy drain, descriptor closure, owned-root identity and enclosing-stage deletion; no assumption that hooks delete their lock files. |

### Native stamp representation and bounded safety corrections

The original runner's `_md5int64` reads the first eight MD5 bytes through a native
Uint64 view. The pinned Linux/x64 Dart VM returns the raw 64 bits as a signed
Dart integer. The old `0 <= hash < 2**64` predicate therefore rejected valid
negative bookkeeping. The corrected predicate is exactly
`-2**63 <= hash < 2**63`, with `type(value) is int`, for both stamp collections.
It does not accept the union of signed and unsigned ranges.

This is proven against the already pinned Dart revision
`a0daa5004ec02c0638ba6e50791ba9338a87374c`: original revision/typed-data SDK bytes
match the original SDK inventory; the immutable Git tree authenticates the
relevant VM C++ blobs. The recognized Uint64 getter normalizes to
`kUnboxedInt64`, defined as native `int64_t`; the x64 load and `BoxInt64` store
those raw bits in a Mint. Public Uint64 API wording alone is insufficient to
infer this pinned native JSON representation. No Dart or C++ code is executed,
compiled or added to the build inputs.

For fixture bytes `{"configVersion":2,"packages":[]}\n`, ordinary MD5 is
`3d26e2b8da5af2d242d9600c84855151`; its first eight bytes in little-endian native
representation become `-3246432485929507267`. The old predicate rejects that
source-derived fixture; the corrected native predicate accepts it. MD5 remains
cache bookkeeping only. Original SHA256/source/package/SDK checks retain all
integrity and execution authority.

The compiler stamp now explicitly requires both app
`.dart_tool/package_config.json` and SDK `bin/cache/dart-sdk/version`, which the
original compiler path unconditionally appends. Existing SDK-root restrictions,
row bounds and duplicate rejection remain. A phase is committed as completed
only after its full state and Linux manifest validate; the Linux manifest is
checked again after web because the original web target preserves it.

The hook controller's own generated-file reader additionally rejects ancestor
aliases and compares device/inode/mode/owner/link/size/mtime/ctime before opening,
on the nofollow descriptor, after reading and at the final pathname. Descriptors
close even on identity failure. The shared input/runtime reader is unchanged.
These checks tighten generated-state safety without adding filesystem rights.

### Source-derived fixtures, tests and verification boundary

The complete private source matrix authenticates six original archives and
membermaps/notices, 28 original producer/VM/SDK files and all eighteen families
above. Proof SHA256:
`f2da8c725209a880497df907ec66655c6c23b2d0cbc39914ac14ce656f4db163`
(`build/p15i-source/complete-state-source-proof.json`). Original VM source reads
are targeted, immutable-revision source inspection, not dependency downloads or
new SDK authorization. Original source hashes, records and notices are retained.

Independent whole-tree fixture JSON SHA256:
`88553580166352bcdfe998b592799b37bb8a08419486fe94866b0bb0b2c4a0ca`
(`build/p15i-source/hook-state-fixtures.json`). These fixtures do not import
production CONFIGS/TASK_FILES. They include both full trees, six-field inputs,
three-field outputs, both shared producers, all file roles/modes and real signed
bookkeeping vectors. Exact canonical tree hashes embedded in tracked tests are
`9e7495951938b5eb2bc76dea2afdb35eb1226a51032996d66ad8deb3dcba0a75`
after test and
`ffdf0fe966a030447c0c2fe03c82c16ecab227c67d549560acf0ee0cee854122`
after test plus web. Task lists in fixture metadata use lifecycle order; actual
directory-set authority remains unordered exact equality.

All 310 relevant inert tests pass, including 42 hook tests. Coverage includes
both full before/after lifecycles and golden trees; missing/unknown/extra short
or long shared children; native files in every task/shared location; missing
nine-file roles; changed config/version/paths; malformed protocol/outputs;
signed-int64 boundaries/booleans/unknown stamp paths/environment/missing required
roles; manifests before and after web; symlinks/hardlinks/ancestor aliases;
write permissions, ownership and byte bounds; inode replacement, failed-phase
rollback and descriptor cleanup. Candidate cleanup/source/plugin/cache/dependency
and unchanged workflow checks also pass. Temporary fixture directories are empty
after the suites; original evidence remains private and preserved.

No P15i hosted command, upstream SDK/package execution, actual Flutter test or
web compilation is performed. Prior P15h evidence still establishes 24 passing
actual Flutter tests and six passing cleanup flags but stops before successful
hook protocol verification and any web build. Source-derived fixture acceptance
is not actual hook/runtime acceptance, candidate success, cold-build
reproducibility or production/consumer/release admission.

### Independent review and one prepared verification

Independent review repeats 116 affected tracked tests (42 hook, 43 candidate,
31 dependency) and 63 separately constructed whole-state cases across both
profiles. It independently authenticates the signed-native-int source chain,
checks the full producer matrix/fixtures and the original web target's retention
of the Linux manifest. All pass, with no remaining source-contract finding.
The reviewed hook-controller SHA256 is
`0e7639daf11ebc93e1b5106aaeea7c8e442aca1d8751ff0c17f8e0c5af2cfd09`;
the tracked hook-test SHA256 is
`ab23ab6a597594b810092becac26eb4fd73b998f38ad98647635355addd97a38`.
Private final review is retained as
`build/p15i-review/candidate-preflight-review.json` and binds the exact final
source, tests, fixture proof and concrete prepared plan.

**GO for one prepared bounded candidate verification**, limited to this source
and the existing workflow/Boundary. This is source-contract readiness, not a
successful application build or runtime acceptance. There is no claim that the
unknown historical shared directories were inspected or admitted.

The private plan `build/p15i-verification-plan/plan.json` binds the concrete PR
commit, all fifteen reviewed controller-source hashes and three affected test
hashes. It is marked prepared/report-first, `dispatch_performed=false`, with no
execution authorization from this report. It specifies exactly one manual
`workflow_dispatch`, attempt 1, `source-candidate-build` on the existing P15
branch; unchanged 45-minute job and 2,400-second whole-command deadline with
90-second TERM-to-KILL grace, original 180-second pub and 900-second test/web
limits. No sandbox capability or network permission is added.

The prepared order is original input/runtime guards and both offline pub steps;
closed preparation/source/plugin metadata; 24 actual Flutter tests and complete
one-task/two-shared-child state; web compilation only after all prior predicates
pass; complete two-task/four-shared-child state with retained empty Linux
manifest; original source/SDK/dependency rechecks; output/assets/font/notices;
and mandatory process/policy drain, all six cleanup flags and descriptor closure.
Any unknown state or new independent failure stops execution with no retry.

**No dispatch is performed in P15i.** Report the GO/NO-GO first, as requested.
P13/P14/Core, all original source pins and dependency versions remain unchanged.
PR #35 stays draft; no merge, release, product admission or reproducibility
claim follows this prepared plan.

## P15h: exact hook task identity from original source

The retained P15g artifact/run 40797200583 establishes 24 successful Flutter
tests, followed by `HookRun.after('test')` rejecting the Objective-C task set.
It contains no actual task-directory names or input JSON. The historical actual
set remains unknown; no retrospective hook execution or harmlessness is inferred.
A full hosted diagnostic build merely to discover a name is unnecessary: the
original producers prove a concrete wrong expected value.

Tool `code_assets 0.19.7`, `lib/src/code_assets/extension.dart:66–68`, adds
`CodeAssetType.type` to the build-asset list. `code_asset.dart:132–136` binds it
to `NativeCodeAssetNewSyntax.typeValue`, `syntax.g.dart:824–826`, which is
`code_assets/code`. The extension map is separately named `code_assets`.
The previous controller confused the discriminator and extension namespace.
Linux/x64 test configuration has no compiler configuration, dynamic link mode
preference and linking disabled. Web release has no code extension, default
data-assets disabled, empty build-asset types and linking enabled. No upstream
version or hook input authority changes.

The exact test configuration before hashing is:

```json
{"build_asset_types":["code_assets/code"],"extensions":{"code_assets":{"link_mode_preference":"dynamic","target_architecture":"x64","target_os":"linux"}},"linking_enabled":false}
```

The web configuration remains:

```json
{"build_asset_types":[],"linking_enabled":true}
```

`hooks_runner 0.23.0/lib/src/build_runner/build_runner.dart:379–411` invokes
tool `hooks 0.20.1`'s `computeChecksum()` before `setupShared`. That method
(`lib/src/config.dart:177–201`) hashes only the current configuration using
compact UTF-8 JSON and SHA256, retaining 32 hex characters. The checksum method
itself does not sort; the original generated constructors, extension setters
and config construction sort the relevant nested maps and omit absent optional
fields first. For these two fixed ASCII configurations, the controller's
existing sorted compact JSON is byte-equivalent. No paths, timestamps,
package-root fields or hook outputs enter the checksum.

| Profile | Task name (32 hex) | Shared child (10 hex) |
| --- | --- | --- |
| corrected test | `6b4ebf10e70ccf8d154076a186bfba3b` | `6b4ebf10e7` |
| old incorrect test expectation | `1af93f274159ce57893667012f2e9aca` | `1af93f2741` |
| unchanged web build | `6782ff62a082d25dd9788598e67912e5` | `6782ff62a0` |

The shared child uses app `hooks 2.0.2/lib/src/config.dart:48–60` with the same
configuration bytes but a ten-character prefix. Its `HookInput` constructor
(`:96–100`) evaluates `outputDirectory` unconditionally, creating that child
even for an empty-assets hook. The existing `out_dir_shared` input expectation
is correctly the parent `shared/objective_c/build/`. The existing fresh-state,
test-before-build ordering, one-task test set and two-task final union remain.
The preflight concluded that no further identity-dependent path correction was
required. That conclusion was incomplete: it missed the tool-side constructor
side effect described in the P15h hosted result below. The original preflight
proof is preserved; it is not evidence of successful shared-directory binding.

Private proof `build/p15h-source/identity-source-proof.json`, SHA256
`d6584356603b391088f7dc446f93573a5f12679b4752889e1e7c2c33f1eda254`,
reauthenticates five existing original archives and complete membermaps/notices:
tool hooks_runner 0.23.0, hooks 0.20.1 and code_assets 0.19.7; app hooks 2.0.2
and code_assets 1.2.1. Thirteen relevant producer files are checked against those
archives or the unchanged original 17,240-file Flutter SDK inventory. Relevant
original file SHA256 values include:

- tool runner: `a2709baea77022c2e8dd2f99e0e55057925f518b11bdabc0c85d867697c6d70f`;
- tool hook config: `78d475f41c4ef78bd7142b7b882e36e9e0943327cd4bd784e65b7be8b45af6cc`;
- tool code-assets extension: `8493cf6e68ad0930687640367c4c84bc17afcdb2ef2555bde8f86e9184a3bfc6`;
- tool code-assets syntax: `b69249308104240071d261362a587d9f0af8f40cf49f40a65d92cdb87846752d`;
- app hook config: `5d0b2f4c9cdac23fd4d843956651bdb12585409d5354dba50f10f841515feae0`.

Only the wrong test discriminator is corrected. Full exact config equality,
original package/hook SHA256 and all 224 archive/membermap bindings remain.
Unknown/extra/missing tasks, extra hooks, old test names, altered profiles,
unsafe paths, unknown files and native outputs still fail closed. On task-set
failure the controller now retains at most two observed 32-lowercase-hex names;
other names become only bytecount and SHA256. Expected action/digest pairs are
fixed by the contract. No private directory, raw malformed label, environment,
command, kernel or stdout is published. Observed names never authorize anything;
the existing entry bound still stops excess tasks before further enumeration.

27 hook tests use independent literal wire fixtures and fixed source-derived
identities, including both profiles, their final union, legacy/unknown/missing/
extra tasks, mismatched shared prefixes, correct names with altered configs,
unauthorized native outputs in both task/shared directories, aliases and bounded
privacy-safe diagnostics. The old test contract rejects the new original-wire
fixture; the corrected one accepts it. All 295 relevant inert tests pass,
including the existing source, cache, dependency, plugin and candidate controls.
The existing workflow's `umask 077` is used; an initial local test invocation
under default `0002` correctly rejected writable fixture directories. No guard
was changed to accommodate that test harness condition. All private fixtures
are cleaned up; no SDK, Dart, Flutter or package code ran locally.

Independent preflight review reauthenticates the five original archive/membermap/
notice bindings and thirteen producer files, reproduces both wire hashes, repeats
101 affected tests (27 hook, 43 candidate, 31 dependency), checks the full 295-test
receipt and confirms eleven protected helpers byte-identical to their original
base. All fifteen existing controller bindings are retained. Review SHA256:
`863e97e99778c02429da36abb5351c0d190f460515a8e96806045c59a84bfb1c`
(`build/p15h-review/candidate-preflight-review.json`). Decision:
`GO_EXACTLY_ONE_BOUNDED_SOURCE_CANDIDATE_ATTEMPT`, unchanged workflow and Boundary,
manual attempt 1, no retry, stop at any new independent failure. The purpose is
complete hook/test/web candidate verification after a source-proven correction,
not a full build solely to recover an unknown historical name.

### P15h hosted result and explicit source-proof correction

The one [P15h candidate run 41225196544](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/41225196544)
uses implementation commit `fd714adc2aeef918c72f9d48838f6a18b1d955ed`, manual
attempt 1. All 257 hosted inert tests pass. Both real offline pub commands and
all ten harness commands return exit 0 and confirm process drain. All 224
archive/package bindings, all 73 cache entries and six metadata files pass up
to test entry, together with fifteen SDK Git controls and three plugin namespace
proofs. Source sealing and original SHA256 controls are retained; no completed
post-test source/SDK revalidation is claimed.

All 24 actual Flutter tests pass again. `HookRun.after('test')` now passes the
exact Objective-C task-set predicate, establishing the corrected 32-character
identity by equality against its fixed source-derived expectation. It then
fails closed with `HookContractError / P15_HOOK_SHARED_CHECKSUMS` for
`objective_c 9.5.0/hook/build.dart`. The new task-set mismatch diagnostic is not
emitted because that predicate passes. The observed shared child names and
contents are not retained. No successful `hook_execution` receipt, task-file/
protocol/native-manifest validation, later post-test source acceptance or web
build follows. `compiled=false`, `flutter_tests=24`, `candidate_success=false`.

Bounded reinspection of the same authenticated sources identifies a separate
preflight omission. Tool `hooks 0.20.1`'s own `HookInput` constructor also eagerly
evaluates `outputDirectory`; its getter creates the shared child using its
**32-character** checksum. After `setupShared`, runner `inputBuilder.build()`
constructs this tool-side input before protocol validation and package execution.
App `hooks 2.0.2` subsequently creates its **10-character** shared child. The
preflight and independent preflight review considered the app-side side effect
but missed the tool-side one. Positive shared-state fixtures also modeled only
the app-side child and did not cover that producer overlap. This was an
incomplete source proof, not evidence
of changed configuration, source pins or unauthorized native execution.

For test, the source therefore predicts both
`6b4ebf10e70ccf8d154076a186bfba3b` and `6b4ebf10e7`; the build profile would add
`6782ff62a082d25dd9788598e67912e5` and `6782ff62a0`. That is two shared children
for test and four after both profiles. The existing contract expects only the
ten-character children and bounds the directory to two entries. These complete
source-derived sets are recorded as a remaining contract correction, not newly
authorized runtime state. Actual child names, their emptiness and the subsequent
protocol predicates still require closed verification. No general alias or
checksum whitelist is justified.

The original private source proof and preflight approval remain intact. The
separate source addendum `build/p15h-source/shared-checksum-proof-addendum.json`
has SHA256
`63d74f1ca95c6c8e432837908df2871ba7d676fc608e1be2bb912cf7385b6d7c`.
It explicitly corrects the missed tool constructor path without modifying code,
expanding accepted task/shared sets or starting another attempt.

Artifact `13051113501` is 5,968 bytes, contains only `result.json` and
`cleanup.json`, and has API-matching SHA256
`eb8393a04cf70e2b2dcbdb2352a3b6435fdf9d50364792824dfe190069a12e90`.
All fifteen source bindings match the immutable reviewed trial commit. All six
cleanup flags and source-inventory descriptor closure pass, with both cleanup
failure fields null. Public artifacts contain no raw logs, credentials, private paths,
SDK/cache copies or compiled binaries. Private API, original job log, artifact,
verification, source addendum and reviews are retained under `build/p15h-*`.
Original archive/membermap/license notices remain unchanged; final built-output,
font and notice checks were not reached.

Independent final review verifies the artifact/API/source/preflight bindings,
257 hosted inert tests, ten successful drained commands, fifteen Git checks,
three plugin namespace proofs, all preparation metadata, 24 actual tests and
cleanup. It independently identifies the missed tool-side shared-directory
producer and explicitly corrects the preflight conclusion. Final-review SHA256:
`be5faf7cbf41c479baad2b26cc00ee030eaa369be003ee1c65b872e754801fd1`
(`build/p15h-review/candidate-result-review.json`). Decision:
`STOP_NEW_SHARED_CHECKSUM_STATE_BLOCKER`.

Technical decision: stop at the new shared-state contract failure, preserve the
successful task correction and test results, and keep PR #35 draft. The single
P15h hosted attempt is consumed. No executable changes follow this failure,
no second hosted run is dispatched, and no P13/P14/Core, pin, dependency,
sandbox, merge or release change is made. The first actual Overmorrow webbuild
has **not** been produced; independently verified reproducibility and production/
consumer admission remain separate unfulfilled gates.

## P15g: original Flutter filecache hash semantics

P15g resumes the exact P15f report source
`d426e96fbd373e04d093e96372de0a5e8f5fcea8` and reuses the retained candidate
run, logs, artifact and independent result review. No earlier runtime/architecture
trial is repeated. The original Flutter 3.38.5 / Dart 3.10.4 / Overmorrow pins,
224 dependency archives, original SDK inventory and P15f output record remain
unchanged. The correction concerns the validator's cache-format assumption.

The original `packages/flutter_tools/lib/src/build_system/hash.dart`, 5,125 bytes,
SHA256 `78abfb964a4611e1ce81ee53b44245c291229a80e27d6536e0890ca651ac549d`,
and its original upstream tests are reauthenticated against the retained SDK
inventory. `FileStore._hashFile` reads regular file bytes through a 64 KiB buffer
and invokes this custom `Md5Hash`. On the pinned amd64 target the final Uint32List
buffer is serialized little-endian. The finalizer always compresses one final
64-byte block: it appends 0x80, then overwrites bytes 56..63 with the original
bit length. For byte lengths modulo 64 in 56..63, the marker and up to seven
payload bytes are overwritten, and the required second final block is absent.
Consequently this cache producer differs from ordinary MD5 on those lengths.
The SDK is preserved; only the validator mirrors this original format.

All 73 relevant original byte inputs are reconstructed and individually checked
against their original sizes/SHA256: 36 ARBs, l10n.yaml, the SDK localization
target and 35 unchanged localization Dart outputs. Inert source-derived digest
reproduction gives exactly twelve differences and 61 ordinary-MD5 matches.
The differences below are calculated from original source bytes, not observed
historical cache entries:

| Original relative path | Bytes | Standard MD5 | Original Flutter cache digest |
|---|---:|---|---|
| `lib/l10n/app_fr.arb` | 9343 | `e34fdd3b080bbbfec0c0e8273a9776d6` | `0c2ef055b49fb58c6f1b479fb059326f` |
| `lib/l10n/app_he.arb` | 1466 | `b0e6887c96ed250d8c23572e9e5c9046` | `e6f8919d57dd606f6e85cd59185e26a9` |
| `lib/l10n/app_localizations_en.dart` | 10683 | `39de0e8293c156972eeb8cf683d1b223` | `d8a0506d04c14f8c19e64ef08297a9eb` |
| `lib/l10n/app_localizations_it.dart` | 11262 | `57955f7203bbcc9b34b9676f26bacd15` | `9c151387460dc7dddc62f0575d8125e5` |
| `lib/l10n/app_localizations_mk.dart` | 13052 | `5ad2a6a53b96fc3b219373ce8eb4a24d` | `a82dad2cad99ac18ee08bdd2b568f3ac` |
| `lib/l10n/app_localizations_ro.dart` | 11262 | `3405c69768c04336fd35ba022dfa9beb` | `3ebad78f71a649007a2daff54352799a` |
| `lib/l10n/app_localizations_sr.dart` | 10939 | `a760258ae3d926b4d97896f7991da6a6` | `74022606b0ee8b415cbd422158ed2107` |
| `lib/l10n/app_localizations_tr.dart` | 11135 | `673831259e95f15123202abb1772fba3` | `99c54c48d1a3372260d90c99122c428f` |
| `lib/l10n/app_localizations_uk.dart` | 13052 | `bb1d5d66e0b2e705568c35b297141dd7` | `4a50c8cc2f013692a7e7b21cfc18d7f4` |
| `lib/l10n/app_localizations_uz.dart` | 10875 | `6a386fb0c716d1f2e8aa848eac268f76` | `789d9d4dfb729ce48aa7eb815e78442a` |
| `lib/l10n/app_localizations_zh.dart` | 20990 | `f5e4e86fe371b3e385f0f089f029b386` | `9cee4e91c79bfc2b480966b999f4688b` |
| `lib/l10n/app_uk.arb` | 12091 | `0e8df231a2ce7c94c08ad3829cbc4d95` | `1b1743c1fe862ea47cb54749f8ac3b09` |

The first entry rejected in run 40758942786 remains unknown: neither its raw
cache rows nor values were exported, and HashMap iteration order is not an
identity contract. No particular historical scan position is inferred. The
complete original-byte reproduction proves the validator algorithm mismatch
without a hosted diagnostic run merely to obtain a missing hash.

The timing and remaining metadata rules are audited together. On this fresh
stage the depfile does not yet exist, so the early input-hash pass is skipped.
The build system awaits localization generation and its awaited Dart formatter,
then resolves and hashes all 38 inputs and 35 outputs. `persist` serializes the
73 currentAssetKeys; the metadata files themselves are not cache-hashed. Source,
generation, bookkeeping and SHA256 admission are separate. Existing stamp/list
sets, source-proven depfile order/escaping and the build-ID scalar checks remain.
The build ID explicitly uses ordinary `crypto.md5(engineRevision + 'build')`,
not this custom filecache implementation. No analogous producer mismatch was
found in these remaining predicates.

The P15-only [semantics record](../third_party/overmorrow-filecache-semantics-v1.json)
binds original SDK/source hashes, all 73 source roles and digest vectors, source
timing, exact version/architecture, provenance and independent source review.
Record SHA256:
`314a60c54b76753e2fda91a77357e7de22da2764ad1f1b33f510e1075d8d0edc`.
All vectors derive from authenticated original bytes; no current cache value
becomes an expected source or integrity hash. The validator's ordinary MD5
build-ID calculation remains separate. SHA256, unchanged original files,
normalized generated-source hashes, package/membermap checks, plugin identities,
hooks, SDK Git controls and the existing Boundary retain execution authority.
A demonstrated last-seven-byte cache collision is rejected by the original
source SHA256 gate; the cache digest alone cannot admit changed bytes.

Independent source review uses its own compression reconstruction, six original
upstream vectors and 269 boundary lengths, then rechecks the complete 73-file
matrix. Source-review SHA256:
`d39428c80c4fec266eb4cd6c9bf53fb5ab2c7d82eb638057efbd73ac4b26c98e`.
Private evidence is retained in `build/p15g-source-hash/`,
`build/p15g-metadata-audit/` and `build/p15g-review/`. No SDK, Dart, Flutter,
packagehook, sandbox or native code runs locally. These are inert data tests;
a final implementation review is still required before the one authorized
hosted candidate attempt.

The complete relevant inert suite now passes 287 tests, including 26 metadata,
13 complete-output and 43 controller tests. The real-data reproduction runs
the old exact validator against the source-derived cache and confirms its
rejection; the corrected validator accepts all 73 roles and all six metadata
files. Both a changed depfile and wrong build-ID scalar remain rejected.
Controlled fixture roots/engine are synthetic; all 73 file bytes and digest
vectors are authenticated original inputs. This is no claim that historical
raw `.filecache` rows were retained.

On a future cache mismatch the pure validator first validates the complete
73-entry path set, detects unknown/duplicate paths, then reports all digest
mismatches with fixed relative input/output labels. Only valid lowercase
32-hex digest values are emitted; other values receive bounded type, length
and SHA256 observations, never raw strings/objects or host paths. The controller
catches this exact cache exception separately from existing hook diagnostics.
Original Flutter copyright and the full original 1,519-byte BSD notice are
retained in the compatibility module and checked by hash. No upstream SDK,
application source, dependency record or shared runtime helper is changed.

The final independent P15g preflight review repeats 82 affected tests and its
own complete 73-role/six-metadata reproduction. It confirms source/diagnostic
privacy, exact BSD notice retention and full SHA256 authority. There are no
open findings. Review SHA256:
`153a01a0eda511bf9d0811a879685bbfe4d758d4bb0a8c588a50143abbe48325`.
GO permits at most one bounded manual candidate attempt on the reviewed bytes;
a new independent error requires a stop without retry. It grants neither
successful-build evidence nor reproducibility or production/release admission.

### Hosted P15g verification and remaining independent blocker

Exactly one [P15g candidate run 40797200583](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40797200583)
was dispatched on implementation source
`a2945e48205c40c81893af9898c6cd7645806125`, manual attempt 1. No diagnostic-only
hosted run was needed or performed. All 249 hosted inert tests pass; local
preflight covered 287 relevant tests and the independent review repeated 82
changed tests plus separate source/data/composite checks.

Both real offline pub commands exit 0. The original 224-archive dependency and
configuration binders pass. Fifteen SDK Git controls and three actual plugin
namespace proofs pass; the latter authenticate all 16 aliases against the
13 original packages. The source gate before test entry retains all 386 original
file hashes and the source-derived preparation policy. The fixture generator
runs and its closed delta/final fingerprint checks pass. The actual pub-output
receipt confirms 407 regular files, 53 source/platform outputs, four Dart-tool
roles and all six metadata files. The nested metadata receipt confirms all
73 cache entries, 38 inputs and 35 outputs, including the later depfile and
build-ID scalar checks: 40,501 metadata bytes, aggregate SHA256
`e45c0e5503882d68c09b4e0a432b3fcbfb1211a7280bf93f26140b7275ca449c`.
Thus the previous cache-integrity blocker is resolved as a complete metadata
set, not just a single previously unknown entry.

The test profile is explicitly authorized as
`linux-x64-tests-no-native-output`, with native compilation and additional
network/filesystem rights both false. The real `p15-flutter-tests` command
returns exit 0 and the controlled success marker confirms all 24 tests pass.
Raw Flutter stdout remains private; this claim is bound to the exact reviewed
controller's exit/marker gate and its retained command receipt, not to an
exported raw test transcript. All ten harness commands return exit 0 and confirm
process drain.

After the passing tests, `HookRun.after('test')` rejects the hook task set with
`P15_HOOK_TASK_SET` / `HookContractError`, identifying the already known
`objective_c 9.5.0/hook/build.dart`. Expected/observed task names and their
cause are not retained in the closed artifact. No cause, harmlessness, actual
hook execution or unauthorized native operation is inferred. No successful
`hook_execution` receipt exists. The later post-test `verify_inputs` phase,
web-build command, final SDK/output/font/notice checks and output copier are
not reached. `compiled=false`, `success=false` and `candidate_success=false`;
this is a successful cache correction and test command, not a successful
full web candidate or reproducible/production admission.

Artifact `12864179265` contains exactly two bounded UTF-8 JSON files, ZIP
5,957 bytes, SHA256
`4ed5d6b25dc8fd0b216a2763cdd7f30da3d2ae8191974b1f28709cfc504e6209`.
The API digest, all fifteen controller-source hashes and final failed run/job
status match the implementation source and reviewed bytes. Every one of the
six cleanup flags passes; descriptor closure is confirmed and cleanup failure
fields are null. Private inputs, stage and outputs are absent, the policy is
removed, processes are drained and the host network namespace is unchanged.
Local inert test temporary directories are empty. P15g's public-source input
copies and unique proof/review files remain private, hashed evidence.
Original application/dependency notices remain unchanged; the translated cache
compatibility code retains the exact original BSD notice. Web output notices
are not claimed because no web output was produced.

The independent final-result review verifies source/API/ZIP bindings, all 249
hosted inert checks, ten exit-zero/drained commands, fifteen SDK Git controls,
three namespace payload hashes, successful metadata receipt, actual test gate
and complete cleanup. Review SHA256:
`05cf407ec34f46e85071b1649a9e7e20c54251887d45bc085cb11822c1b02eec`.
Evidence is retained under `build/p15g-candidate-hosted/` and
`build/p15g-review/candidate-result-review.json`; earlier failed results and
preflight reviews remain preserved separately.

**Decision: STOP_NEW_POST_TEST_HOOK_STATE_BLOCKER.** P15g resolves and verifies
the requested filecache hash correction. The remaining acceptance dependency
is the distinct post-test hook task-set contract, with sufficient bounded
expected/observed task identities before any correction or authorization.
No hook guard, sandbox right, source/dependency pin or shared helper is changed
after this failure; no second attempt is started. PR #35 remains draft/open on
the unchanged P13/#33 base. P13, P14 and Core are untouched. First web-build,
reproducibility, browser/product and release acceptance remain unproven.

## P15f: complete post-pub measurement before authorization

The P15e source and runtime results above remain authoritative. Its closed
artifact does not contain the rejected filename, scan order or complete
post-pub inventory. Consequently, no historical rejected filename is claimed.
A new diagnostic-only verification is required before deciding output admission.

The original application is staged inertly at the same source pin. Its 386-file
map is SHA256 `94a0f9632f425453887f41b8b3e9926e3d4c3516f3fd4ce3d8db1540d7e48baf`,
exactly matching the retained P15e pre-pub receipt. Flutter remains 3.38.5 and
Dart 3.10.4. The bundled Dart revision is
`a0daa5004ec02c0638ba6e50791ba9338a87374c`; its original DEPS binds pub to
`f7f1891e2de3d795532f45ec214f88ac912ffcd6`. No SDK/package code ran locally.

The [source producer catalogue](../third_party/overmorrow-pub-source-observations-v1.json)
is explicitly observational, SHA256
`5dfda4d8a1716b798f9c3b5979cd18b3a7b3c7256304d5a2f8f3c4556d2918f9`.
It records 53 regular writer/touched paths outside build state: 35 localization
Dart files and 18 platform/metadata files. Forty-two already exist and eleven
are potential additions. Sixteen desktop links remain separately authenticated
by the unchanged plugin helper. Four source-predicted paths are absent from the
old acceptance set: the two iOS ephemeral LLDB files and the macOS ephemeral
configuration/environment files. These are predictions, not observed historical
rejections or output authorizations. Three old allowances have no producer in
this source profile: `.flutter-plugins` and separate pt_BR/zh_Hant Dart files.

The [metadata supplement](../third_party/overmorrow-pub-metadata-observations-v1.json),
SHA256 `bc96728fd748e61420e3e9770035ddee8fac535f8e2e32b143d3c6d7f4c2b561`,
records four app `.dart_tool` files and six persistent localization build-system
metadata files, their exact producers and expected schemas. Build identifiers
are source-derived lowercase MD5 values; the actual engineRevision input is
not inferred from an unrelated SDK artifact stamp. Diagnostic labels recognize
only the five exact leaves under a lowercase hex32 directory and `.last_build_id`;
the identifier is rendered as `<pub-build-id>`. This grants no output authority.

The explicit `source-pub-diagnostic` mode uses the existing Boundary and the same
two locked offline pub commands, dependency/plugin checks and fixture prefix.
Four descriptor-anchored inventories cover before pub, after tool pub, after
app pub and after fixtures. Complete additions, changes and removals are
recorded with bounded relative labels or redacted path hashes. Reviewed source
outputs also receive root-normalized hashes and occurrence counts; neither
source bytes nor host paths are exported. Original sources, file types,
permissions, directory identities and no-follow Git metadata remain checked.
The source gate runs unchanged; only its measured source-admission failure may
be collected, and its full inventory fingerprint must equal the published final
checkpoint. Any different integrity failure remains fatal.

Diagnostic completion stops before hook authorization, Flutter application
tests and web compilation. It is separate from candidate success; output and
production admission remain false. Process cleanup, persistent descriptor
cleanup and all six existing cleanup invariants remain required. Unknown
redacted entries remain unresolved. A diagnostic result cannot authorize a
candidate: the complete observed closure still needs explicit content checks,
negative tests and an independent candidate review before one real attempt.

All 237 relevant inert tests pass, including 52 inventory/privacy tests and
39 candidate lifecycle tests. Unknown files, changed originals, directory and
Git-admin replacement, symlinks, hardlinks, resource limits, diagnostic gate
races and attempted fall-through are covered negatively. Twelve existing
shared/runtime and P15 dependency/hook/plugin helpers remain byte-identical.

Independent diagnostic-only preflight review: SHA256
`19d6248282f6a22eb7a09e2f0e284aaf8c4b38a7cecf8224532f29befb73ae5b`.
The final metadata-label delta is independently approved, SHA256
`95fe671ca5f6622d7fdbdadb2dc277e46eb73654e8f96e465ed41300483b3fa9`,
with 91 affected tests independently repeated and no open findings. This is
GO only for one diagnostic run, not a candidate or generated-output admission.

Private source/provenance evidence is retained under `build/p15f-source/`,
inert checks under `build/p15f-inert-tests/`, and independent reviews under
`build/p15f-review/`. No shared P13/runtime input, P14 or Core file changes.

### Hosted P15f diagnostic result

The one [diagnostic run 40754938838](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40754938838)
completed on `f522a786c5932d22b840f4ad9b6b0d42af16ae23`, manual attempt 1.
It actually reproduces the complete rejected set, in sorted reporting order:

- `ios/Flutter/ephemeral/flutter_lldb_helper.py`
- `ios/Flutter/ephemeral/flutter_lldbinit`
- `macos/Flutter/ephemeral/Flutter-Generated.xcconfig`
- `macos/Flutter/ephemeral/flutter_export_environment.sh`

The two iOS LLDB files are rendered by the original SDK's Xcode debug template
writer. The macOS pair is written by the original Xcode configuration updater.
Flutter's controlled pub preparation calls these platform-file generators even
on this Linux runner when the original platform scaffolds are present. They
are outputs of the reviewed SDK, not original app sources or packagehooks. The
web/test commands do not execute these LLDB, shell or Xcode files. The old
policy simply omitted their precise paths; the historical P15e first scan entry
still cannot be reconstructed and is not claimed.

All 199 hosted inert tests pass. Both real offline pub commands exit 0; twelve
SDK Git checks and both namespace
proofs pass. Tool pub changes no application nodes. App pub adds exactly 21
regular files, 14 directories and 16 verified aliases: 386 -> 407 files and
98 -> 112 directories. The 21 files are eleven new source/platform files, four
`.dart_tool` files and six localization metadata files. All 53 predicted
source/platform outputs are present. No original file changes or disappears;
all 386 original bytes/hashes remain identical, including the 42 existing
generated outputs. The fixture step then adds just its file and two parents:
408 regular files and 114 directories. No unsafe node is present. The only
opaque directory label independently resolves to the fixed `build` parent by
its five-byte SHA256; every file and alias is identified. Dynamic build IDs are
masked but remain distinguished by path hashes.

Artifact `12845867953` contains exactly two bounded UTF-8 JSON files, ZIP
93,548 bytes, SHA256
`f1b80f90f4a46c4755125315d0b8a7730dfb11d3e743ca77ac7c2b7235c97cfb`.
The API digest and all eleven controller-source bindings match the trial
commit. Four complete checkpoint inventories and all deltas are retained.
The old source gate still rejects those four names; its rejection fingerprint
matches the published final state. `diagnostics_complete=true` is distinct
from `success=false`, `candidate_success=false` and `admitted=false`.
No hook authorization, Flutter application test or web compilation occurs.
All six cleanup flags pass, descriptor cleanup is confirmed, and both failure
fields are null. Private raw logs, contents, host paths and inode identities
are not published. Evidence is retained in `build/p15f-diagnostic-hosted/`.

The independent diagnostic-result review confirms the complete deltas, all
386 original files, all controller bindings, namespace payload hashes and
cleanup. Review SHA256:
`1e1b549e929b37ccca848b0638a466ff37fb211cddc8bc3821ce914195da5359`. This review grants evidence-only GO.

### Complete first-post-pub authorization contract

The new P15-only [output record](../third_party/overmorrow-pub-outputs-v1.json)
binds the original 386-file map, the producer and metadata catalogues, the
original SDK inventory, and the actual diagnostic source/artifact/review.
Its SHA256 is `c8d87288da4897bb2baf04b8f00c89c2816ced78abd94b5cdaa621c61e638509`.
Its exact path sets describe all 53 source/platform outputs, the four fixed
Dart-tool roles and six symbolic metadata paths. The concrete metadata directory
ID is derived from the original SDK manifest's engineRevision and Flutter's
literal `build` argument. It is never guessed from an unrelated engine stamp.

The [output validator](../scripts/prepare_hosted_overmorrow_pub_outputs.py)
requires exactly 407 regular files and 112 directories before fixtures, the
original 386 files unchanged in bytes/hash/mode, exactly the 16 independently
verified plugin alias names, and no unsafe or unexplained nodes. All directories
must be original or exact parents of those files/aliases; extra empty directories
are refused. Fifty-two source outputs bind exact context-normalized hashes,
mode and SDK/app-root occurrence counts observed in the diagnostic run. Only
the two caller-bound SDK/app roots are normalized; paths cannot choose a new
root or introduce placeholder tokens. The date-bearing plugin manifest retains
the original dependency/plugin semantic binders, plus an exact valid Dart
timestamp shape and false SPM flags. The four tool files retain original
package-config/graph verification, exact Flutter version bytes and an observed
Dartpad registry hash. No Darwin output is granted execution authority.

The original SDK manifest and localization target are separately bound to their
original SDK inventory hashes before deriving metadata values. The
[pure metadata validator](../scripts/prepare_hosted_overmorrow_pub_metadata.py)
then checks all six exact names, closed JSON schemas, 36 ARB roles, 35 generated
Dart roles, 38 stamp inputs, 73 exact private MD5 cache entries, source-proven
ordered depfile bytes and the exact build ID. MD5 mirrors Flutter's metadata
format; SHA256, original roots and source identities remain the authority.
Metadata never supplies a path to open. Private reads use the existing held,
no-follow directory descriptors and compare every selected file to its captured
mode/byte count/SHA256, with per-file, aggregate and count bounds.

After this complete preparation check, the fixture action may add only its one
fixed file and required parent directories. It may change or remove no existing
node. The full resulting fingerprint must still match before the first hook
profile authorization. Thereafter the existing source sealing, hook/package,
SDK, Boundary and output checks continue unchanged. The later source gate uses
only the exact 53 reviewed source paths, removing the three unreachable old
allowances rather than adding a generic generated-file rule. Before app pub,
the candidate gate requires the original source hashes without mutable outputs.

The complete expected file/directory set is also checked inertly against the
actual diagnostic inventories; all 407 files, 112 directories, 16 aliases and
52 normalized content pins agree, with no unresolved entry. The updated suite
has 277 passing inert tests, including 59 descriptor/privacy, 18 metadata,
12 complete-output and 42 controller tests. Negative cases cover unknown and
extra files, modified originals, wrong hashes/modes/roles, duplicate metadata,
wrong roots/build IDs, unsafe links, directory replacement, extra empty
directories, fixture escapes and phase/fingerprint mismatches. This is
preflight evidence; it is not Flutter application-test or compilation evidence.

The independent complete candidate review approves exactly one bounded hosted
`source-candidate-build` attempt with no retry or release authority. It repeats
131 affected tests and four independent compound-negative fixtures, verifies
the actual closure and original metadata producers, and has no open finding.
Review SHA256:
`eddacd5820f13b20cdcd4309370ef8ac3c4f9655eb234b937b6a5095b826dd79`.
Raw metadata bytes were not exported by the diagnostic; their exact predicates
are source-derived and must pass against the real bound runtime values.


### Hosted P15f candidate result and stop decision

Exactly one real [candidate run 40758942786](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40758942786)
was dispatched on source `19198e9c30ed425f2e5b4c20c4c9080859fa20da`, manual
attempt 1, using the final independently approved executable hashes. It fails
closed during `p15-pub-offline` with `P15_PUB_METADATA_CACHE_HASH`.

All 239 hosted inert tests pass. Both actual offline pub commands exit 0. Six
harness commands return exit 0 and confirm process drain; nine SDK Git checks
pass. Post-pub dependency/configuration binding again verifies the 224 original
package trees. The host plugin seal and one actual namespace proof verify the
16 aliases against 13 original packages. Source fonts/assets remain checked;
output fonts/notices are not reached because compilation never starts.

The failure is in the known `build/<pub-build-id>/.filecache`, produced by
`FlutterBuildSystem.build` / `FileStore` during localization preparation.
Its exact hash entry and observed/expected values were not exported. The new
validator requires a string equal to the independently computed private MD5
of each authorized input/output. At least one such entry fails that predicate.
The artifact does not prove which entry, whether its type/value differs, or
why. The retained producer uses the SDK's custom `Md5Hash`; that implementation
reference is unresolved here and is not asserted to explain the mismatch.
Neither corruption nor an SDK/application modification is inferred.

The precise approved source flow establishes that the following earlier gates
were reached successfully before that code: original SDK manifest/target hashes,
exact 407-file / 112-directory closure, all 386 original file rows unchanged,
16 alias names, 52 normalized source hashes/root counts, plugin scalars, version
and Dartpad binding, localization input/output lists, stamp lists, output list,
filecache version 2 and 73-entry count. This is a control-flow inference from
the exact bound code and typed failure, not a separate `pub_outputs` success
receipt: the validator throws before returning that receipt. Complete cache
membership/hash validity, the later depfile comparison and final build-ID
scalar comparison are not established. No fixture generator, hook-profile
authorization, Flutter application-test command or web-build command is reached.

Artifact `12847772815` is exactly two bounded UTF-8 JSON files, ZIP 5,180 bytes,
SHA256 `09646594fe4536cce6c932bb55609ba125bf219de8b0fcbcbb84e3976dc6bd9f`.
The API digest, all fourteen controller-source bindings and final run/job failure
status match the trial source. All six cleanup flags pass; both failure fields
for cleanup are null, and descriptor closure is confirmed. Runner-private
inputs, source stage, outputs and policy are removed, processes drained and the
host network namespace unchanged. The local inert 386-file source copy was
also rehashed and removed; private source/provenance and review evidence remain.

The independent final-result review confirms the artifact/source/proof/cleanup
bindings and distinguishes direct receipts from the earlier-gate inference.
Review SHA256:
`e0c9504232f546f0aba06069698aee56350796dbbff51fbc575e811635ddee42`.
Evidence is retained under `build/p15f-candidate-hosted/` and
`build/p15f-review/candidate-result-review.json`. Original failures, the diagnostic
review and preflight GO remain separate and unchanged.

**Acceptance decision: STOP_NEW_BLOCKER_NO_BUILD_ACCEPTANCE.** The complete
preparation filename closure is demonstrated, but the full post-pub content
integrity gate is not closed. The next bounded acceptance dependency is proof
of the original SDK's `.filecache` hash representation/semantics against the
validator, with sufficient non-sensitive typed observations to explain the
mismatch. No cache-hash exception, source/dependency change, runtime correction,
further diagnostic/candidate run or general Flutter rebuild is performed here.
A new attempt requires new user authorization. PR #35 remains draft/open on
unchanged #33. P13, P14, Core, sandbox permissions and shared helpers are unchanged.

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
`8d03a1a322da9b4da1a646c716f953a414a73bc34bcb982dc45611fc6f1093bb`,
repeats 64 affected tests, verifies all six changed executable/data/test inputs
and gives GO for exactly one bounded manual attempt with no open findings.
Private evidence is retained in `build/p15e-investigation/`,
`build/p15e-inert-tests/` and `build/p15e-review/`. Earlier failures remain
separate. No P13/P14/Core change, dependency upgrade or release follows.

### Hosted P15e result

Exactly one [P15e run 40735268382](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40735268382)
was dispatched, manual attempt 1, on source
`adfc787848accde04390d8907ecaa2a543a12801`; implementation commit
`99d23547d68e007593accf989fc4c118c6385151` has identical executable inputs.
The intervening commit binds the finalized preflight-review hash in this report.
All 139 hosted inert tests pass (19 hook, 33 plugin, 31 dependency, 31 candidate,
13 build-contract and 12 deployment tests).

Both real offline pub commands return exit 0. The first full post-pub dependency
verification now succeeds: all 224 original archives/package trees remain bound,
the application configuration/graph has 158 authorized roots, the tool state
has 102, and the plugin metadata binds 53 platform entries and 42 graph entries
to original package source declarations. Twelve SDK-Git checks, four complete
triplets, all return exit 0. All ten compile isolation/negative flags are true.

The host seals all 16 actual aliases. Two subsequent probes through the existing
compile Boundary independently verify the same 16 alias/package/version/archive
and membermap identities and every original selected file identity. Both
proofs have `namespace_identity_verified=true` and match the sealed host proof
apart from that flag. Thus the absolute trailing-slash producer spelling is
now **actually observed and accepted** for all eight Windows and eight Linux
aliases. For example,
`windows/flutter/ephemeral/.plugin_symlinks/dynamic_system_colors` binds exactly
to `/state/pub-cache/hosted/pub.dev/dynamic_system_colors-1.9.0/`.
This first newly verified alias does not identify the historical first rejected
P15d alias, whose scan order/owner/raw bytes were not retained.

Eight recorded sandbox steps return exit 0 and drain: cache generation/listing,
compile preflight, tool pub, application pub, `p15-plugins-0`, Node test-fixture
generation, and `p15-plugins-1`. The fixture step is not a Flutter application
test. Full source rechecking after these steps fails closed with category
`ValueError`, code `P15_UNKNOWN_GENERATED_SOURCE`, phase `p15-pub-offline`.
The existing `recheck_source()` extra-file gate found a path absent from the
original source and the exact authorized generated-output set. Its filename
was not retained and the cleaned stage cannot supply it afterward. No output
name, producer or harmlessness is guessed, and no generated-file allowance is
expanded. Source/output admission remains incomplete despite the now successful
package and alias binding.

No hook-profile authorization, Flutter application test or web compilation is
reached; `compiled=false` and `flutter_tests=null`. Hook runtime remains
unverified. There is no first successful web candidate, reproducible output or
production/consumer admission.

Artifact `12837916565` is the original 4,944-byte ZIP, SHA256
`a79a5b388974888ee472bba6507fb485f71460655591cc393439eb23ac753e04`,
matching the API. It contains exactly two bounded UTF-8 JSON files and all eight
controller source hashes match the trial commit. The retained proofs contain
controlled relative names and original hashes, not raw targets, inode numbers,
host paths or raw private logs. All six cleanup flags pass: processes drained,
policy removed, private inputs/stage/output absent and host network namespace
unchanged; both cleanup failure fields are null.
The independent result review has SHA256
`85e91d5ca018be7ad846d69775ded27a23c076aa8dd61b025abec55cdd864ba3`.
It also reconstructs the canonical probe payloads from the closed proofs and
matches their recorded 5,788-byte output lengths and hashes. It accepts the
bounded alias correction while preserving the new source/output acceptance
blocker and all hook/test/build/reproducibility/product limitations above.

The next separate dependency is a bounded review of the rejected generated
source/output and its precise provenance. This P15e attempt is consumed. The
unknown-file guard stays closed, and no further fix, hosted retry, merge or
release is performed in this task.

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
