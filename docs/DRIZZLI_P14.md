# P14: bounded Drizz.li candidate build

This package depends on draft [PR #33](https://github.com/VOLPAROSSA/volparossa-weather/pull/33)
at `e774912e292f339d42ff23f00b4d8fc5d69e5b47`. Its shared runtime was independently
accepted against [P13 run 40596738646](https://github.com/VOLPAROSSA/volparossa-weather/actions/runs/40596738646),
artifact `12777367515`, ZIP SHA256
`a40da70138886f464e96f9636124127b85c40f543868dbe0d49a6476006861c5`.
P14 does not replace that evidence or alter its security boundary.

## Fixed inputs

- Drizz.li commit `d2a6839e2b3f2e561b849d83014fc5959bed39cc`, tree
  `7b36709f84a10e082119d245e3bddfe67b209e9b`.
- Original lock SHA256 `9b04f44d254fff82180b32716353c2e7b4e444de7da26cd3fad7eb92512f3454`:
  347 exact entries, of which 298 have selector-compatible archive inputs,
  47 are target-excluded and two are authenticated inactive optional musl data.
  Selector compatibility does not imply that npm installs every optional entry.
- Existing Drizz.li package-input record SHA256
  `775192250323cb74dd0e1f07c77fd4ab9a7c45706a8e0436e88f7eafa9fdd0d0`.
  Provision its unchanged 227-package closure and seven preservation companions
  with the existing offline installer. These 234 identities are the Drizz.li
  subset of P13's verified shared 242-package installation; no Flutter is needed.
- Node 24.19.0, npm 11.17.0 and the existing pinned Firefox 140.16.0 runtime.
  Browser helper commit `08bac388a0abfd06426bebe8f6fabd0157d2e709` supplies the
  existing Boundary's verified configuration; no browser consumer trial runs.
- Svelte 5.57.0, SvelteKit 2.70.1, Vite 8.3.1, svelte-check 4.7.3,
  Paraglide 2.25.0. All transitive versions and SRIs remain in the original lock.
- Separate MIT plugins `@inlang/plugin-message-format` 4.4.0 and
  `@inlang/plugin-m-function-matcher` 2.2.6 retain the original exact SRIs and
  complete archive member-map bindings from the existing package-input record.

## One candidate procedure

Only explicit manual `hosted-clients.yml` mode `drizzli-candidate-build` executes
this controller. Exact source, P13 ancestry, hosted-runner guards and inert tests
precede provisioning. No automatically retried candidate round is provided.

1. Use the existing fixed installer with `--no-download` and `--no-remove`;
   validate archive maps, exact plan and baseline preservation.
2. Materialize the existing runtime and stage the pinned source with the source
   module observer. Fetch only the two exact localization plugin inputs. Hash
   original staged source/configuration/plugin files before dependency execution.
3. Prepare the existing `View` and live `Boundary`, scoped AppArmor policy,
   semantically validated private loader cache and compile preflight. All npm
   and compiler children use the existing capability-denied, networkless sandbox.
4. Acquire approved tarballs strictly as data; compare each complete canonical
   member map, archive digest, exact identity and lock binding to the fixed
   record. Run pinned npm `cache add --offline --ignore-scripts` on those local
   files, followed by `ci --offline --ignore-scripts --no-audit --no-fund`.
5. Verify installed regular-file bytes, generated hidden lock and manifest-bound
   CLI links. Reject unbound files, unsafe aliases and target-excluded packages.
   Record actual optional-package state; remove any of the two authenticated
   inactive musl trees plus every tarball and the npm cache before application
   execution. This deliberate removal is not a claim of npm-native exclusion.
6. Run explicit localization, Svelte synchronization, typecheck and Vite
   production commands. Never run upstream `prebuild`, `npm run build` or
   dependency lifecycle scripts. Recheck source, plugins, installed dependencies,
   inactive absence and live Boundary before and after each command.
   The outer Vite command uses `--configLoader native` with Node 24's type
   stripping. Pinned Kit 2.70.1 invokes a nested Vite build using its default
   loader: only the exact `node_modules/.vite-temp` directory is permitted,
   empty at every drained verification checkpoint. Its temporary config code
   derives from sealed inputs through pinned Vite 8.3.1 and must be deleted by
   that loader's `finally`; no generated file is accepted as a dependency.
   Paraglide 2.25.0's optional `project.inlang/cache` is precreated empty at
   mode 0500; the same inode, mode and empty contents are checked around each
   phase. Optional cache write failures are caught in the pinned source. No
   wildcard generated state in `project.inlang` is authorized.
7. Hash generated output, retain original licenses/notices and collect module
   graphs. Existing graph/notice closure rejects unreviewed virtual modules;
   output observations never authorize new producers or become expected pins.
8. Confirm process drain and remove the scoped policy. Project only bounded
   UTF-8 metadata, exact child logs and original notices. Upload no application
   assets, tarballs, SDKs, runtime files or dependency caches. Finally remove
   private/public input directories and staged output only with confirmed
   installer/runtime cleanup receipts; failures preserve runner-local recovery.

The job is bounded to 45 minutes, its controller to 2400 seconds, with existing
per-command time, memory and log bounds. Source/compiler/network boundaries and
cleanup failures stop the round. No automatic merge, release, Android/Overmorrow
build or Core/F04 edit is part of this package.

## Evidence and acceptance

`p14-result.json` distinguishes an actual production command exiting zero
(`build_produced`) from complete candidate checks, independent reproduction and
output/product/consumer admission. A later integrity or module-closure failure
does not erase that command's original outcome, and it does not admit its output.
All original failures and logs remain available within the bounded projection.

Original Drizz.li AGPL-3.0-or-later, Weather GPL-3.0-only and the plugin MIT
notices are preserved separately. The existing npm notice bundle contains 54
components and 41 original notice records; full actual-output notice coverage
requires the real emitted-module graph, including independently bound virtual
producers. Input notice coverage alone is insufficient.

One first build cannot establish two cold matching builds or independent
reproducibility. Consumer/UI/Core delivery and full product acceptance remain
separate, ungranted gates. Hosted results and the independent procedure review
must be attached to the P14 PR on their exact source revision.

The generated-state contract was independently checked as inert data against
the existing approved complete member maps, including Vite archive SHA256
`d1e2250c6eb956e84df6b5d4f8127d420efa9142f393652c77a06906e79d69c3`
and Kit archive SHA256
`e6b95e341d93f11b611cf0df5a76f1eaec8817e4ee4a0a3a91846c5b4f336ca4`.
No code from that source inspection was executed.
