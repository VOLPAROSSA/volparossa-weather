# Overmorrow shared provider integration

The pinned Overmorrow Flutter app consumes the same VOLPAROSSA weather and
air-quality provider as Drizz.li. It uses the existing app provider dispatcher,
phone/tablet layouts, forecast view and air-quality detail route—not a separate
demonstration page. Peer discovery, retrieval and source acquisition stay in the
shared core/provider layer.

## Verified scope

The release web build succeeds with Flutter 3.38.5 and the unchanged upstream
dependency lock. Twenty-three Flutter tests pass with synthetic products: native times
and accumulation windows, missing versus zero values, independent weather/AQ
failures, expiry while idle, phone/tablet layouts and the existing detail route.
The local HTTP profile passes thirty-four focused bridge tests; thirteen build
driver and twelve deployment tests cover its workspace boundaries.
Seven of the Flutter tests cover slow retrieval, exact bounded busy retries,
request/body cancellation and rejection of late results. Twenty additional
core-process adapter tests include preservation of an unconfirmed-cleanup error
when removing temporary output also fails.

A bounded, isolated Firefox trial now passes against the actual CanvasKit UI and
local HTTP bridge, using synthetic weather and particulate products. It verifies
native timelines and values, missing current observations/AQI, the configured area
and source attribution. Nine real pointer refreshes each request one weather and
one air-quality product. Independent failures and stale responses preserve the
other valid product; idle expiry hides old values without a new request. The
existing air-quality detail page opens without another fetch.

The refresh control is disabled while the app is loading, so it no longer offers
a refresh that the busy app would ignore. Twelve browser-harness tests and four
fixture tests pass separately. The browser loads only same-origin resources;
browser and fixture processes exit, the private profile is removed and the host
network namespace is unchanged.

The [build record](build-verification.json) identifies the pinned inputs, assets
and current full browser evidence. The shared harness has been rechecked after
adding the table trial: all nine pointer refreshes, independent failures, idle
expiry and cleanup pass on the current source. The earlier reports remain
unchanged.

A separate [table record](table-verification.json)
now proves exact ordered table extraction in the actual browser: four weather
rows and five particulate rows match their captured HTTP responses, both on
initial display and after a real pointer refresh. Missing values, calm zero wind,
native timestamps and precipitation windows remain distinct. Each product is
requested exactly twice; the browser uses only loopback resources and cleanup
passes. This additional trial uses synthetic products and does not replace the
full browser trial.

The separate joined core delivery trial below now passes. An Android debug APK
build and strict offline rebuild also pass; installed-app behavior, iOS packaging,
mobile background lifecycle and native home-screen widgets remain unverified.
The synthetic browser proof establishes neither forecast accuracy nor mobile
execution.

## Hosted build and browser trials

The [hosted workflow](../../.github/workflows/hosted-overmorrow.yml) prepares a
public, source-bound Overmorrow build for the core integration trial. It
keeps the existing local results above unchanged. The
[hosted sequence](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38235992570)
passes compilation, all 23 Flutter tests, both browser trials and cleanup. These
synthetic trials are separate from the joined core delivery proof below.

The workflow uses the same pinned Flutter 3.38.5 archive and upstream dependency
lock. SDK acquisition is explicit and verifies the official archive before
extracting it; it does not install a global SDK. Dependency acquisition is
separate from offline compilation and tests. The existing real CanvasKit UI is
then exercised in Firefox with synthetic products, followed by the separate
ordered-table trial. Both are needed: the first checks refresh, independent
failures, expiry and navigation; the second checks exact rows, cells and source
time windows.

Only successful public web assets, the reviewed browser/fixture runtimes and
their notices are exported for later admission into the core trial. Original
build and browser reports remain separate. SDKs, dependency caches, browser
profiles and Git data are not uploaded. These synthetic trials make no weather
source requests and do not prove core delivery or native Android/iOS operation.

## Android trial candidate

The [Android hosted workflow](../../.github/workflows/hosted-android.yml) now passes
the debug APK build and strict offline rebuild; the installed-app emulator trial
has not yet passed.

### Current result

[Trial 32](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38438989104)
at `cd13a93a` passes the APK build and offline rebuild, then stops before
installation. The first basic link query returns complete, valid JSON:
6,259 stdout bytes, empty stderr and exit zero. Strict metadata validation
rejects it as `link_unknown`; the original receipt does not identify the
particular predicate or field. Detail queries, qdisc/route checks and the app UI
are not reached. All 45 original artifact members, fifteen step logs and pinned
source/toolchain bindings are audited. Artifact SHA256 is
`a10cba7d854f080da0408a58323d860a33344439b9ccace2e50c3c4540d79021`;
original log ZIP SHA256 is
`d1ba9822cfa67d84d41052403e0cd362ed2d4438e6bc4580ea8940c96700a472`.
Both builds produce the same 74,366,059-byte APK. Process drain, private-state
cleanup, KVM restoration and unchanged host network namespace all pass.

The preceding [trial 31](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38432510721)
at `79090a88` also passes both builds, but its detailed link query produces
malformed JSON at position 5,435. Its complete stdout and empty stderr rule out
stderr contamination in that command, not every possible producer defect.
Its original 45-member artifact has SHA256
`404df873966001646625b5134974116f002375db58eaf31a10a3f4a671ee2e4a`;
cleanup passes, while installation and UI checks are not reached.

Primary [AOSP GRE formatter source](https://android.googlesource.com/platform/external/iproute2/+/refs/tags/android-16.0.0_r1/ip/link_gre.c#510)
contains an unconditional plain-text write inside detailed JSON output.
The [link inventory code](https://android.googlesource.com/platform/external/iproute2/+/refs/tags/android-16.0.0_r1/ip/ipaddress.c#1244)
invokes those detailed printers for down devices too. This is a concrete source
defect, but not proof of which path produced trial 31's malformed output.

The current candidate keeps the complete basic inventory and obtains full details
through two fixed queries: loopback and interfaces whose kernel-reported type
is dummy. Every
candidate sink must match the inventory's identity and all overlapping fields.
Both the inventory and detail sets must remain unchanged across the route/qdisc
checks. Other interfaces must still be administratively down; unknown metadata,
unsafe qdiscs and routes remain rejected. No malformed JSON is repaired or
ignored. The original ten-second observation deadline, stream bounds, observer
guards and cleanup remain in force.

Schema-eight diagnostics add the first rejected metadata predicate and field
category, with a closed classification of unknown keys. No raw keys, interface
names, addresses or values are exported. The observation is bound to the exact
exception, query and poll; command or JSON failures cannot inherit stale metadata
diagnostics. Optional diagnostic failures preserve the original rejection.
Historical schemas one through seven and the ten-read boundary schema four
retain their meaning. All 185 inert Android checks pass, including comparisons
against the previous parser's acceptance and short-circuit behavior. These checks
do not replace the next actual emulator trial or prove installation.

### Earlier attempts and corrections

The
[first attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38242345261)
stopped during input preparation because two nested process alarms conflicted.
The correction keeps the total and per-step deadlines without nesting alarms.
The [second attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38243122640)
verifies and materializes all eight Android/Gradle archives, then stops before
app staging because the root-owned Java launcher is passed to a runner-owned
artifact hash check. Cleanup restores the original KVM access.

The Java correction hashes only the fixed apt launcher with root-ownership,
no-follow, same-descriptor and size checks, and rechecks its bytes after the
version probe. Generic artifact ownership requirements are unchanged. The
[third attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38245213294)
passes that check, app staging and all ten native Node contracts. It reaches
Gradle configuration, then fails the Maven-only repository type check before
producing an APK. Process cleanup and restoration of the original KVM access
pass.

The next correction recognizes Gradle 8.13's plugin-repository wrapper through
its Maven descriptor, keeping the same HTTPS allowlist for both base and
additional artifact URLs. A new offline Gradle fixture must exercise three real
wrappers and six rejected repository cases before the app build. The
[fourth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38247823514)
passes this real fixture, then reaches further into Android plugin configuration
before exhausting the inherited 1,024-file-descriptor limit. It does not produce
an APK; process drain, policy cleanup and KVM access restoration pass.

The correction gives only the three fixed Gradle invocations a finite
4,096-descriptor limit. Other build, browser and emulator profiles keep their
existing limits; the parent process and development host are unchanged. The
fixture must report the actual JVM's soft and hard limits. All 47
hosted-preparation tests and 11 native preparer tests pass locally, including a
real inert child-process reproduction of descriptor exhaustion. They do not
execute Gradle. The [fifth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38249512469)
passes the real fixture with JVM soft/hard limits of 4,096, then stops during the
app build because a locked plugin requires the missing Android 34 platform.
Other locked plugins require Android 35. Process drain, policy cleanup and KVM
access restoration pass; no APK or emulator result is produced.

The [sixth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38251506516)
adds those two official platform archives to the read-only SDK preparation and
passes the same Gradle fixture. Flutter debug compilation then exceeds the
3 GiB aggregate process-memory limit and is stopped. Process drain cannot be
confirmed, so the sandbox policy and staging are retained rather than reporting
successful cleanup. The original KVM access is restored and the host network
namespace is unchanged. No APK, offline rebuild or emulator result is produced.

The [seventh attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38254164363)
uses one Gradle worker and a 1,024 MiB JVM heap, but Flutter compilation again
exceeds the 3 GiB aggregate limit. Cleanup remains unconfirmed after the stop;
the Gradle fixture, original KVM access restoration and unchanged host network
namespace pass separately. The aggregate measurement alone does not identify
which tool dominates memory use.

The [eighth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38256253721)
gives only the two fixed app builds a finite 4 GiB process
RSS budget. They require at least 6 GiB available before launch and retain the
2 GiB host reserve throughout execution. Other Android steps keep their 3 GiB
budgets; workers, JVM heap, deadlines and conservative cleanup are unchanged.
An optional measurement records Java/Dart/other process counts and RSS from the
same total-peak sample, without paths, process IDs or command lines. Shared RSS
can be counted more than once; this is a conservative process-tree measurement,
not unique physical memory. The separate resource receipt remains configuration
only. The build reaches `:app:compileDebugKotlin` after Flutter compilation,
then exits 1 because Jetifier exhausts its Java heap while transforming the
exact Flutter `x86_64_debug` native-library JAR. The 533-second step peaks at
4,012,879,872 bytes, below the aggregate limit; that sample contains
2,615,971,840 bytes of Java RSS, 1,393,250,304 bytes of Dart RSS and 3,657,728
bytes from other processes. Process drain, policy/staging removal, KVM access
restoration and unchanged host network namespace are confirmed. All nine
retained step-log hashes match. No APK, offline rebuild or installed-app result
is produced.

Commit `f40711e` skips only that exact engine-version/native-JAR cache path
in Jetifier, with strict absolute-path anchors and Java-properties escaping.
Flutter's pinned [Android target](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/engine/src/flutter/shell/platform/android/BUILD.gn#L501)
and [JAR writer](https://github.com/flutter/flutter/blob/f6ff1529fd6d8af5f706051d9251ac9231c83407/engine/src/build/android/gyp/create_flutter_jar.py#L51)
show that this separate artifact contains native libraries only; the Java
embedding is separate. The official [AGP 8.11.1 source archive](https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/8.11.1/gradle-8.11.1-sources.jar)
(`65bc5d04cc52655664894e196f274da781091602a219126b67fd13bd2621ddd6`)
defines `android.jetifier.ignorelist` and passes a matched input through
unchanged before transformation. Jetifier remains enabled for embedding and
plugins. The one-worker/1,024 MiB heap, 4 GiB RSS cap, 2 GiB host reserve and
deadlines are unchanged. Inert tests check the exact match, escaping and
rejection of other coordinates, versions, ABIs and paths; they do not establish
that a real build or installed-app trial succeeds.

The [ninth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38259586563)
passes Kotlin/Java compilation, then loses its Gradle daemon during
`:app:mergeExtDexDebug`. The build exits 1 after 487.238 seconds; observed peak
RSS is 4,060,364,800 bytes, below the 4 GiB cap, with no recorded resource-monitor
stop. All nine original step-log hashes match. Process drain, policy/staging
removal, KVM access restoration and host network-namespace preservation pass.
There is still no APK, offline rebuild or installed-app result. Only the final
twenty daemon-log lines were retained, so the underlying cause remains unknown.
The next probe collects bounded JVM/daemon error markers, changes in the shared
runner's memory-event counters and the maximum sampled CPU time of one Java
process with its actual soft/hard limits. Only the two app-build steps opt in;
resource limits and other clients' receipts stay unchanged. No raw daemon logs,
process IDs, cgroup paths or dumps are exported. Missing, changed or truncated
sources remain explicitly unknown. Sampled counters are indicators, not proof
of a particular kill signal or a successful build. All 119 targeted inert tests
pass.

The [tenth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38272739293)
on `29bf7c4` now records actual `OutOfMemoryError: Java heap space` messages
during dex merging. It exits 1 after 558.643 seconds with peak RSS of
3,969,150,976 bytes, below the aggregate cap. One sampled Java process reaches
902.140 CPU seconds with 900-second soft/hard limits; this does not identify the
daemon or establish its final kill cause. Shared cgroup memory-event deltas are
zero, without child-level attribution. All nine original step-log hashes match;
process drain, policy/staging removal and KVM-access restoration pass. No APK,
offline rebuild or installed-app result exists.

Commit `c9392fb` sets `-Pandroid.r8.threadPoolSize=1` only on the two fixed
app-build commands. The same pinned AGP 8.11.1 source shows that external dex
merging uses an internal D8 work-stealing pool, independent of Gradle's worker
limit. Its `IntegerOption` is supplied through a Gradle project property. This
reduces that pool's concurrency; it does not increase the JVM heap, RSS budget,
CPU/wall deadlines or host reserve. The configuration receipt is not a runtime
measurement. All 120 targeted inert checks and independent review pass, including
exact acquisition/offline argument parity. Actual build fit and app execution
still require the next hosted trial.

The [eleventh attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38279184264)
on that source still loses the Gradle daemon during `:app:mergeExtDexDebug`,
exiting 1 after 614.585 seconds. No heap-exhaustion markers were observed in
the complete bounded new daemon log or step log. One sampled Java process
reaches 902.940 CPU seconds against its actual 900-second soft/hard limits;
that is an indication, not proof of the daemon's kill cause. Aggregate RSS
peaks at 3,970,863,104 bytes, below 4 GiB. All nine original log hashes match;
process drain, policy/staging removal, network-namespace preservation and
KVM-access restoration pass. There is still no APK, offline rebuild or
installed-app proof.

Commit `1da6f2a` gives only the two fixed app-build commands a
1,800-second per-process CPU budget. Their 900-second wall-time deadline,
4 GiB aggregate RSS cap, 2 GiB host reserve, one Gradle worker, 1,024 MiB heap
and D8 pool of one remain unchanged. CPU time across a process's threads can
exceed elapsed wall time. The single outer `prlimit` sets both CPU limits
before starting the build sandbox; an insufficient inherited hard limit is
rejected before launch, without changing the parent or attempting a privileged
raise. The schema-2 configuration receipt distinguishes CPU limits from the
wall-time deadline. All 126 targeted inert Python/Node checks and independent
review pass, including tiny real child processes checking the limits and
unchanged parent.

The [twelfth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38282437155)
on that source ends at the 900-second acquisition-build deadline after
900.130 seconds. The last logged task is `:app:mergeExtDexDebug`; the logs do
not measure that task's duration separately. Maximum sampled individual Java
CPU is 1,662.590 seconds under the actual 1,800-second limit. Peak aggregate RSS
is 3,988,389,888 bytes, below 4 GiB. All nine original step-log hashes match.
Process drain and policy/staging cleanup remain unconfirmed; daemon-log scanning
is therefore skipped and heap-marker status is unknown. Unchanged host network
namespace and restored KVM access do not establish full cleanup. No APK,
offline rebuild or installed-app evidence was produced. The deadline is proved;
an internal D8 or garbage-collection cause is not.

Commit `809cc44e` makes the existing Kotlin in-process setting apply to both
the app and Flutter's included Gradle build. The app's `gradle.properties` alone
does not configure that separate build; Gradle's
[property loader](https://github.com/gradle/gradle/blob/v8.13.0/subprojects/core/src/main/java/org/gradle/initialization/DefaultGradlePropertiesLoader.java)
also reads the private Gradle user home shared by both builds. The fixed setting
is therefore written there before Gradle starts, checked before each app build,
and mounted read-only while caches remain writable. The original app setting
stays in place; Flutter SDK source is not modified.

The offline repository fixture now includes a real dependency-free second build
that must observe the same property. Its receipt establishes property scope,
not a completed Kotlin compiler run or improved build performance. JVM heap,
RSS reserve/cap, CPU/wall deadlines, Gradle workers and D8 pool size are unchanged.
The previous three-Java-process observation does not identify which process was
a Kotlin daemon; a successful actual build remains required.
All 138 targeted Python/Node checks, workflow parsing and independent review
pass; none executes Gradle, the Android toolchain or an emulator locally.

The [thirteenth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38288008577)
on that source verifies the Kotlin property in both real Gradle builds through
the schema-3 repository fixture, then fails during dex merging with explicit
`OutOfMemoryError: Java heap space` messages. The build exits 1 after 663.058
seconds. Peak aggregate RSS is 3,299,090,432 bytes, with two sampled Java
processes; maximum sampled individual Java CPU is 1,257.580 seconds under the
1,800-second limit. All nine original step-log hashes match. Process drain,
policy/staging cleanup, original KVM access restoration and unchanged host
network namespace pass. No APK, offline rebuild or installed-app evidence exists.

The next candidate gives only the acquisition and offline app-build JVM a
1,536 MiB heap instead of 1,024 MiB. This addresses observed heap exhaustion;
successful build fit remains unproved. The 4 GiB aggregate cap, 2 GiB host
reserve, 6 GiB launch requirement, 900-second wall deadline, 1,800-second CPU
limit, one Gradle worker and one-thread D8 setting are unchanged. The independent
repository fixture retains its 256 MiB heap and Kotlin remains in-process for
both app and included builds.

The [fourteenth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38290352014)
on `7f071b2b` fails before native execution at the download `ARCHIVE_DIGEST`
check. The retained traceback does not distinguish a short download from a
digest mismatch or name the failed package. Only preparation artifacts exist;
this attempt does not exercise the larger app heap, Gradle, KVM or an APK.
Original logs and artifacts are retained without replacing any source pin.

Download failures now have a bounded receipt identifying the known package,
expected and received byte counts, and expected and observed digests. Rejection
still stops before extraction or execution; there is no automatic retry or
checksum fallback. The receipt excludes URLs, response bodies and headers.
All 79 targeted lightweight checks and independent review pass; actual preparation
and native execution are assessed by the next trial below.

The [fifteenth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38291836603)
on `68059b02` passes input preparation and the real Gradle repository fixture,
then reaches `:app:configureCMakeDebug[arm64-v8a]`. It fails because CMake 3.22.1
is missing from the read-only SDK. The build exits 1 after 705.209 seconds;
peak aggregate RSS is 3,539,718,144 bytes, below 4 GiB. No heap-exhaustion marker
is observed in this run. All nine original step-log hashes match, and process
drain, policy/staging removal, KVM access restoration and unchanged host network
namespace pass. No completed APK, offline rebuild or installed-app proof exists.

The correction adds the exact official CMake 3.22.1 Linux archive, including
Ninja and the original notices. Its size and checksum are pinned from Google's
[repository metadata](https://dl.google.com/android/repository/repository2-3.xml).
Only this package uses the verified rootless layout with `bin`, `doc`, `share`
and `source.properties`; all other archives retain the single-root rule.
Extraction and inventory checks still reject unsafe paths, links, file types,
excessive expansion and changed bytes. There is no SDK auto-installation,
blanket license acceptance or ABI filtering. All 82 inert Android tests and
independent review pass; actual full-archive verification and native execution
remain required. Resource limits and the upstream dependency lock are unchanged.

The [sixteenth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38295005766)
on `bf6004f9` verifies that CMake input and successfully builds the debug APK.
The following networkless build uses Gradle `clean`, strict captured dependency
checksums and the same source inputs. It succeeds too, with the same APK size
(74,366,059 bytes) and SHA256
`501c0b2a2d658df7388b75f11d61407c5dbf774c8c0d94655491af55d2ea3184`.
This is a successful pair of builds in one runner, not a general reproducibility
or release-signing claim. Their durations are 551.094 and 93.814 seconds, with
peak aggregate RSS of 3,831,435,264 and 2,733,920,256 bytes, both below 4 GiB.

The installed emulator trial then exits 1 after 333 milliseconds with a generic
child failure. Its internal failed operation is not recorded. All 13 original
step-log hashes match; process drain, policy/staging removal, private emulator
state removal, KVM restoration and unchanged host network namespace pass.
Installation, UI operation and mobile lifecycle behavior remain unproved.
Bounded emulator substep diagnostics are needed before another attempt.

The [twenty-fourth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38314299583)
on `6fb0114cbbd13a73f7a5e00c3b3a0ccfb9194813` passes actual AVD creation
after the exact emulator-only local metadata registration. Its separate
preflight cleanup passes. Acquisition and the clean, strict-checksum offline
APK rebuild both succeed, with receipt size 74,366,059 bytes and SHA256
`94c84cd6980bd26a59a8dda16db9fe5f03c25a90c05e6d6c8b0fd4643efb1595`.
The APK itself is not exported by this failed run.

The installed emulator phase then crosses its 3 GiB RSS guard after 34.075
seconds: 3,240,882,176 bytes against 3,221,225,472. Forced termination does not
confirm descendant drain, so scoped policy/staging cleanup remains unconfirmed;
KVM access restoration and the unchanged host network namespace do pass. There
is no inner installation/UI report or full-trial cleanup receipt.

Candidate `cdf604e` permits 4 GiB RSS only for this fixed installed emulator
phase, with at least 6 GiB available at launch and the same continuous 2 GiB
host reserve. Other preflights stay at 3 GiB. Guest RAM (1536 MiB), two cores,
graphics, CPU/wall deadlines, sandbox and conservative cleanup gates are
unchanged.

The [twenty-fifth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38316868986)
on that exact candidate passes AVD creation, boot and guest-identity checks, then
fails before installation at `guest_network / GUEST_NETWORK_STILL_ACTIVE`.
The original diagnostic does not identify the rejected route or address family;
an active Ethernet path or a conservatively rejected route form is not yet an
established cause. The installed phase runs for 63.209 seconds, with peak aggregate
RSS 3,652,395,008 bytes below 4 GiB. This is not another memory-bound failure.
Inner process/AVD/home and outer policy/staging cleanup pass, as do KVM restoration
and the unchanged host network namespace. No app or final network-boundary report
exists, so installation and UI operation remain unproved.

Acquisition and the clean strict-offline rebuild also pass in that run, with
matching 74,366,059-byte APK receipt hash
`a90742fcb4d92dea29e424826526ecf162e16995b928560e81308df38603142f`.
No APK binary is exported after failure. The 44 original artifact members,
all fifteen step-log hashes and input/provenance bindings are checked.
Separate component CI passes 305 tests on its actual PR merge; it does not
replace the installed-app trial.

The follow-up observes both IPv4 and IPv6 during each successful route-query
poll, even when the first family is rejected. A separate, at-most-2-KiB failure
receipt records only the last poll's fixed rejection, route-type and device-name
categories; unknown or unobserved results stay explicit. No addresses, interface
names or raw command text are exported, and a name category is not proof of a
device's link type. The original admission predicate, deadlines, resource limits
and cleanup remain unchanged. Diagnostic publication cannot replace the primary
failure or create an app-success report. All 139 inert Android and 40 shared-helper
tests pass for that diagnostic candidate.

The [twenty-sixth attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38319732906)
on `7f0af248fa4339d8d85e67857ab1343df4a2d132` again fails before installation
at the guest-network gate. The last observed poll rejects one of four IPv4
routes and four of five IPv6 routes, with one default in each family. The
non-loopback device names fall into the closed `other` category; that does not
establish their kernel type or prove usable egress. Original artifact SHA256 is
`c9896a8e1c48d113ae04521b36a673450b03a48b03c776bbdc27d758be867d4c`;
all 45 members and fifteen step logs are verified. Both APK builds pass with
matching receipt size 74,366,059 bytes and SHA256
`b6d9e6470718bfa5cea11b8cc70507691b6f2c1d2f59d39c4bcbd9da75cc9da6`;
the failed run does not export the APK itself. The installed phase lasts 48.887
seconds and peaks at 3,622,367,232 bytes RSS, below 4 GiB. Inner and outer cleanup,
KVM restoration and unchanged host network namespace pass. There is no app or
network-boundary success report. Separate component CI passes 314 tests.

Candidate `fae274e0` distinguishes usable routes from positively identified kernel
dummy sinks. Android 16's
[netd](https://android.googlesource.com/platform/system/netd/+/refs/tags/android-16.0.0_r1/server/RouteController.cpp)
installs direct IPv4/IPv6 default routes for its dummy network; a familiar name
alone is not proof that the observed route uses that mechanism. The candidate
checks paired `ip -details -json link show` identities and `tc qdisc show`
snapshots around both all-table route queries. Android's
[tc implementation](https://android.googlesource.com/platform/external/iproute2/+/refs/tags/android-16.0.0_r1/tc/tc_qdisc.c)
provides the strict text form used here, without a JSON-command fallback.

Only plain direct routes to genuine loopback or standalone kernel-kind `dummy`
interfaces with exactly a root `noqueue` qdisc are accepted. Active non-sinks,
gateway/nexthop/encapsulation, master/peer links, visible XDP, ingress/clsact or
other sink qdiscs, unknown data and changed observations are not admitted.
Active/changing configurations may settle within the original absolute ten
seconds; malformed or unsupported observations fail immediately. Each command
retains its existing output bound and must finish within that same deadline.

Boundary schema 2 states no usable guest egress under this controlled, pinned
emulator fixture, not absence of all default or non-loopback routes. It assumes
the trusted guest kernel and an unprivileged app; paired observations do not
prove resistance to a compromised kernel, concurrent privileged changes or the
universal absence of BPF hooks. The historical route predicate remains intact.
The separate schema-2 failure diagnostic keeps only bounded last-poll counts,
never names, addresses or raw output. SDK inputs, permissions, resource limits,
cleanup and full installed-app acceptance are unchanged. This candidate has not
yet passed an actual installed-app trial.

The [twenty-seventh attempt](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/38323147074)
on `fae274e0c372b58ab64d2ee50d9d517707fa5e3a` fails at `guest_network`:
an ADB command returns exit 1 with a complete 39-byte response and an observed
access-denied marker. Both route families remain unobserved in the first poll.
The retained reports cannot distinguish the first link query from the following
qdisc query; neither the failing command nor its underlying policy cause is
established. No network-boundary or installed-app success report is produced.

Both APK builds pass, including the clean strict-offline rebuild, with matching
74,366,059-byte receipt SHA256
`8ed9df95945ec4b5a0104011f0316c5aa2cf492747bf1e8a088de3a4d19c6978`.
The installed phase lasts 42.040 seconds and peaks at 3,580,866,560 bytes RSS,
below 4 GiB. Inner/outer process and private-state cleanup, KVM restoration and
unchanged host network namespace pass. Original artifact SHA256 is
`73f5894f5ed4b0494dc10a668cdcbb709112fd1ddd6404714394f28a150aa4fb`;
all 45 members, fifteen step logs and input bindings are checked. Separate
component CI passes 322 tests; the failed run exports no APK binary.

The diagnostic-only follow-up records the last fixed query as `link_before`,
`qdisc_before`, `ipv4`, `ipv6`, `qdisc_after` or `link_after`, with its command
outcome. A failed-command label is bound to the same propagated exception;
`returned` does not mean that parsing or route admission passed. Diagnostic
schema 3 retains the 2 KiB limit and exports no arguments, addresses, interface
names or raw responses. Boundary schema 2, query order, rights, deadlines,
resource limits, cleanup and app acceptance remain unchanged. This diagnoses a
failure location; it does not fix the observed denial or prove mobile operation.

The [native preparer](prepare_native_android.py) modifies only a disposable
Android stage, using package `org.volparossa.weather.trial`. Its test-only
`lib/volparossa_native_trial.dart` entrypoint starts the real app with
`VOLPAROSSA_WEATHER=true` and
`VOLPAROSSA_CORE_ORIGIN=http://127.0.0.1:43210`. The existing dependency lock,
shared overlay and web/iOS sources stay unchanged.

The [trial driver](native-android-driver.mjs) uses real Android taps and
background/resume actions. A read-only debug observer checks mounted weather and
air-quality tables against the synthetic HTTP responses: four weather rows,
five particulate rows, native times, precipitation windows and missing values.
The trial also requires expired values to disappear after resuming, without
another provider request. Mounted widget contents are not proof of pixel
visibility. The separate fixture-control port is not exposed to the app. This
candidate does not prove live weather, mobile core delivery, physical-device or
iOS operation, home-screen widgets or release readiness.

The [official Android and Gradle input pins](../../scripts/prepare_hosted_android.py)
record exact archive URLs, sizes and published checksums. The native stage uses
Android API 36, additional compile platforms 34/35 for locked plugins,
build-tools 35.0.0, NDK 28.2.13676358, CMake 3.22.1 and Gradle 8.13; its
Android-only plugin change selects AGP 8.11.1. Java 17 comes from the disposable
runner's recorded system packages. Google archive pins use the published SHA1;
an observed SHA256 is additional provenance, not independent authorization.
Gradle's distribution has a published SHA256, and its wrapper comes from the
already pinned Flutter archive. All original archive licenses and notices are
preserved. Public dependency acquisition precedes an offline rebuild; captured
Gradle checksums demonstrate consistency, not prior independent review. Only
successful debug APKs, application notices and bounded reports may be exported,
not SDKs, caches, signing keys, emulator state or debug-service credentials.

## Joined core delivery trial

The core's version-five Weather bundle selects this actual Overmorrow client,
the production HTTP bridge and the existing protected peer-delivery path. It
acquires weather and particulate products separately, publishes both, removes
the original publisher inputs and retrieves each product through the core before
opening the UI. Drizz.li's earlier bundle profiles remain unchanged.

The [preparer](prepare_core_browser.mjs) binds the raw products and cold-transfer
receipts to expected native values. The [browser driver](smoke_core_browser.py)
checks ordered Flutter table rows and cells, source metadata and a real pointer
refresh. It distinguishes missing values from zero, preserves precipitation
windows and keeps weather and particulate timelines separate. Tables are
identified by their exact static ordered headers, independently of expected
values. Metadata is checked under the actual product titles. This matters
because Flutter can merge both metadata labels before the table children;
the last preceding title does not establish table ownership. Missing, duplicate
or unknown tables and changed cells still fail. Five pure DOM regressions cover
this correction; CI includes the pinned Browser helper sources.

The [joined trial](https://github.com/VOLPAROSSA/volparossa/actions/runs/38241212407)
passes with core `8b795e98739153196603a17c14cf5c6f3b656642` and this consumer at
`992054c2680e6ef00837b214e7dbd106ba69cc82`. Both public products are retrieved
cold from peers after removal of the original publisher inputs, with no origin
body or range transfer during retrieval. Initial display and a real pointer
refresh match the weather and particulate responses, including native times,
windows, missing values and attribution. Cleanup passes. These changes are
integrated through core PR #230 and Weather PR #18.

This proves cold core transfer followed by UI use of those publications, not
that opening the browser initiated the first cold fetch. It is not mobile
delivery or a forecast-accuracy claim. The retained synthetic browser result,
historical origin results and earlier frozen bundles keep their original scope.

## Data and privacy

`--dart-define=VOLPAROSSA_WEATHER=true` selects the shared provider. The web client
sequentially requests `/api/volparossa/forecast` and `/api/volparossa/air-quality`
from its own loopback origin. Requests cannot choose a location, model, publisher,
file or command. The configured public-community area is displayed explicitly.
Weather and particulates retain separate runs, sample times and expiry.

Each product has one 195-second deadline, including up to two seconds for local
cancellation. This accommodates the bridge's 180-second retrieval deadline and
185-second socket bound; cold retrieval no longer fails after twenty seconds.
Cancellation aborts the request and response body. A late result cannot replace
the unavailable state or start another attempt.

Only the local bridge's exact `429 FORECAST_BUSY` response with `Retry-After: 1`
permits a retry: at most five one-second waits, all within the original product
deadline. There is no request queue, renewed deadline or retry of other errors.
The next request must pass the bridge's single-operation admission check; waiting
alone does not prove cleanup finished. Unconfirmed core-process cleanup blocks
further retrieval in that bridge instance and prevents a successful shutdown
report. Weather and air quality keep independent results.

Missing observations, daily forecasts, radar, UV and air-quality indices are not
invented. Accumulated rain is not hourly rain. A failed product does not erase an
independently valid other product or trigger Open-Meteo. Geolocation, location
search, external imagery/fonts and ordinary background/widget provider fallbacks
are disabled in this profile. Private location tracking is not introduced.

## Reproduce the build

Use Linux with Python 3, Git, bubblewrap, taskset and an existing Node.js 22+.
Place a verified Flutter SDK in this repository's `build/flutter` directory.
The [pin](upstream.json) records its official archive checksum, exact SDK and
upstream commits, license, dependency lock and patch checksum. The build driver
also verifies the archived Dart executable and Flutter tool snapshot. It never
downloads or globally installs an SDK.

From the repository root:

```sh
python3 integrations/overmorrow/stage.py \
  --destination "$PWD/build/overmorrow-01" --execute

python3 integrations/overmorrow/build.py \
  --sdk "$PWD/build/flutter" --stage "$PWD/build/overmorrow-01" \
  --work "$PWD/build/overmorrow-tools" --action dependencies --execute

mkdir -p build/overmorrow-01/test/volparossa/fixtures
node integrations/overmorrow/test-fixtures.mjs \
  build/overmorrow-01/test/volparossa/fixtures/products.json

for action in test build; do
  python3 integrations/overmorrow/build.py \
    --sdk "$PWD/build/flutter" --stage "$PWD/build/overmorrow-01" \
    --work "$PWD/build/overmorrow-tools" --action "$action" --execute
done

python3 integrations/overmorrow/deploy.py \
  --stage "$PWD/build/overmorrow-01" \
  --destination "$PWD/build/overmorrow-web-01" --execute
```

For a stage using an already populated workspace dependency cache, replace
`--action dependencies` with `--action dependencies-offline` to resolve the same
lockfile without network access.

Only the explicit `dependencies` action has Internet access. Build/test execution uses
an isolated network namespace, private workspace caches, two available CPUs and
suppressed analytics. The developer's real home/configuration is not mounted.
Stages and deployment destinations must be new, dedicated build directories;
failed outputs are retained for inspection instead of overwritten.

Serve the deployment directory through `scripts/serve-provider.mjs` with
`--static-profile flutter-canvaskit` and an existing private provider configuration.
This explicit profile permits local WebAssembly and required asset types, while
retaining the original 8 MiB asset/32 MiB total limits, loopback binding, fixed
products, origin checks and prohibition on workers/external resource origins.
The default Drizz.li profile is unchanged.

The deployment keeps both CanvasKit variants, all application assets and notices.
Unused Skwasm renderers, debug symbols and inactive service workers are omitted
from the copied tree; the original build output is preserved. Upstream Overmorrow
remains GPL-3.0-or-later. Original VOLPAROSSA integration files are GPL-3.0-only;
both licenses and dependency notices accompany the deployment.
