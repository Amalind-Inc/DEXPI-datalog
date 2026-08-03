# Reversible adoption outline for isolated command execution

Bead: `pydexpi-datalog-1-23bh.8`

## Outcome

Introduce the selected Hybrid runtime as an optional isolated-command capability inside the existing host Pi adapter. Preserve `runLocalReviewInspection`, `createTurn`, Electron worker supervision, PortLog callbacks, event/record ownership, sidecar domain operations, and manifest persistence.

Adoption is incremental and reversible:

- the capability begins disabled by default;
- absence or disablement means Pi does not receive the command tool;
- risky commands never run on the host, even during rollout or rollback;
- QEMU/HVF establishes the development reference before krun is promoted as the packaged candidate;
- rollout creates no project-data migration and no guest-owned durable state;
- disabling the capability restores the current bounded host Pi tool set without rewriting projects or records.

The current host Pi and PortLog domain path is the retained architecture, not a legacy path scheduled for removal.

## Stable production seam

Keep the external turn interface unchanged:

```text
createTurn({
  emit,
  getEvidence?,
  getRuleCheck?
}) -> { prompt, abort, dispose }
```

The isolated command is an internal tool dependency of the existing host Pi implementation, not a second whole-turn implementation. Conceptually, the worker constructs one additional optional callback:

```text
createGovernedPiReviewTurn({
  ...existingOptions,
  runIsolatedCommand?: (boundedRequest, signal) -> boundedHostResult
})
```

When the callback is absent, disabled, or unavailable, `portlog_isolated_command` is absent from Pi's tool set. When present, it delegates to the deep isolated-command module selected in `.7`. Pi never sees Gondolin, krun, QEMU, VM paths, host admission internals, or raw supervisor streams.

This placement preserves existing ownership:

| Concern | Retained owner |
| --- | --- |
| Runtime composition and capability enablement | Electron main |
| Provider credentials and model stream | Host worker / current Pi adapter |
| Bounded callback construction and abort signal | Per-turn worker |
| PortLog evidence and deterministic checks | Existing sidecar/flow callbacks |
| Isolated guest lifecycle and candidate admission | New isolated-command module on host |
| Event normalization, posture, terminal status | `runLocalReviewInspection` |
| Project manifest and durable PortLog artifacts | Existing host modules |

## Adoption phases

### Phase 0 — Freeze the contract

Specify one backend-neutral request/result interface and observable conformance suite before integrating a VM backend. Freeze:

- command profiles rather than arbitrary host command paths;
- immutable input identity and exact guest-visible paths;
- CPU, memory, time, scratch, output-count, and output-size limits;
- deny-all networking and forbidden ambient access;
- normal candidate, host admission, rejection, failure, unavailable, and cancellation outcomes;
- process/descendant termination and cleanup evidence;
- bounded host-authored provenance fields.

Use an in-memory conformance adapter for interface tests. It is a test implementation, not a security claim or product fallback.

Exit gate: callers and tests depend only on the isolated-command interface; no Gondolin/QEMU/krun types or paths escape it.

### Phase 1 — QEMU development reference

Implement direct upstream Gondolin/QEMU execution behind the interface, using the already measured QEMU/HVF path to reproduce the representative scenario. Replace VMPI's fixed workspace/config/session policy with PortLog's exact read-only input, ephemeral scratch, deny-all network, bounded pickup, and disposable lifecycle.

Run the normal, rejected, failed, cancellation, and cold-retry cases plus every confinement probe. Capture bounded supervisor evidence and host admission records.

Exit gate: all scenario cells applicable to the isolated command are pass, not blocked; no host fallback, TCG, PATH/Homebrew discovery in product selection, workspace exposure, or surviving guest state exists.

QEMU remains development-only at this phase. Passing local behavior does not qualify its package for release.

### Phase 2 — Integrate the optional host Pi tool

Add the optional worker-supplied callback to the existing host Pi adapter and expose `portlog_isolated_command` only when Electron main enables the capability and the isolated backend passes startup checks.

Exercise the full Electron turn through the existing `createTurn` seam. Verify:

- the current provider key remains host-only;
- existing evidence and rule-check tools are unchanged;
- command request/result events use the current normalized PortLog event path;
- terminal classification, manifest upserts, and deterministic-result posture remain host-owned;
- Electron cancellation reaches the guest and rejects late tool results;
- disabling the capability removes only the command tool.

Exit gate: existing Electron inspection tests remain green, new behavior is observable through the same interface, and rollback requires only disabling the capability.

### Phase 3 — krun backend parity

Implement Gondolin krun behind the same isolated-command interface. Reuse the Phase 1 conformance suite and representative scenario unchanged. Compare outcomes and host-authored provenance; do not fork the PortLog interface by backend.

Exit gate: krun matches QEMU on mounts, network, native descendants, candidate bounds, cancellation, cleanup, cold retry, and failure behavior. Any generic missing Gondolin mechanism is proposed upstream first. A PortLog workaround may remain only when it is product-specific and contained inside the adapter.

### Phase 4 — Packaged internal opt-in

Stage krun, its dylibs, and immutable guest assets outside ASAR in the arm64 Electron package. Sign nested code inside-out, preserve the Hypervisor entitlement on the actual runner, enable Hardened Runtime/strict verification, notarize, staple, and run the clean-machine release contract.

Keep the capability disabled by default. Enable it only through an Electron-main-controlled internal opt-in; do not store rollout state in a project manifest.

Exit gate: a clean non-admin macOS 14+ Apple Silicon machine with no Homebrew or developer tools passes installation, representative review, confinement, cancellation, quit/relaunch, offline/error recovery, signature/notarization verification, and cleanup.

### Phase 5 — Default enablement

Enable the command capability by default only after all promotion gates below pass. Backend initialization still fails closed: unavailable isolation means the command tool is unavailable, never host execution.

Exit gate: released behavior remains within the existing PortLog event/artifact contract, support diagnostics are bounded and actionable, and disabling the capability has been exercised against real projects without migration or data loss.

## Promotion gates

All gates are required before default enablement:

1. Representative normal, rejection, failure, cancellation, and cold-retry outcomes pass.
2. Every confinement probe passes with host corroboration; no row remains blocked-by-missing-adapter/protocol.
3. Read-only input, ephemeral scratch, deny-all network, sole bounded candidate, and no ambient host authority are proved.
4. Cancellation terminates the guest and descendants within the accepted bound; no successful result or late artifact survives.
5. PortLog event ordering, deterministic checks, artifacts, terminal state, and manifest behavior remain compatible through the existing seam.
6. Signed, hardened, notarized, stapled krun packaging passes on a clean non-admin Mac without Homebrew.
7. Crash, app quit, worker death, setup failure, and offline/error recovery leave no guest process or per-run scratch.
8. Exact backend/image/policy versions and third-party notices/source obligations are complete.
9. Rollback by capability disablement is tested and requires no project-data migration.

## Persisted provenance and data compatibility

Persist only host-authored, bounded command provenance through the existing tool-result/artifact flow:

- run ID;
- backend and backend version;
- immutable image and policy digests;
- command-profile identifier;
- terminal outcome and timing;
- admitted artifact identity or bounded rejection reason.

Do not persist guest Pi/OMP sessions, scratch, raw transcripts, mutable checkpoints, VM disks, rollout flags, or unbounded PTY output in project manifests. Raw supervisor evidence remains bounded operational evidence under the retention policy selected during implementation.

No project migration is required. Old projects remain readable, and records created while the capability is enabled remain ordinary PortLog tool events/artifacts when the capability is later disabled.

## Rollback behavior

Rollback disables the capability at Electron composition time. New turns then construct the current Pi tool set without `portlog_isolated_command`; evidence and rule-check behavior continue unchanged.

Rollback must not:

- execute the requested risky command on the host;
- switch to VMPI, TCG, Homebrew QEMU, or an unsigned backend;
- reinterpret a prior failed/unavailable command as success;
- delete or rewrite existing PortLog records;
- require guest state to answer or reopen existing reviews.

If isolated execution is required for a requested operation, the user receives a bounded unavailable result with remediation guidance.

## What may later be removed

The following are temporary rollout machinery and may be removed after one released krun version has met every promotion gate and rollback evidence shows they are no longer needed:

- experimental backend selectors exposed outside the adapter;
- the disabled-by-default rollout switch after the feature is permanently enabled;
- QEMU development support, but only when krun diagnostics and regression coverage no longer depend on it;
- temporary migration-free compatibility branches introduced solely for internal opt-in builds.

Removal requires a separate, scoped bead and validation against the isolated-command interface.

The following are retained architecture and are **not** legacy cleanup targets:

- host Pi core+AI and its current model transport;
- `runLocalReviewInspection` and `createTurn`;
- Electron main/worker supervision;
- PortLog evidence and rule-check callbacks;
- loopback sidecar/flow domain implementations;
- PortLog event, record, artifact, and manifest ownership.

Browser/hosted paths are outside this adoption. Their removal requires separately authorized cleanup and must not be bundled with isolated-command rollout.

## Stop conditions

Pause promotion and return to the architecture decision if:

- either backend requires weakening a fixed isolation invariant;
- krun and qualified QEMU/HVF both fail a required macOS release gate;
- cancellation cannot reliably terminate descendants and prevent late export;
- PortLog authority or a reusable credential must enter the guest;
- backend details leak through the stable Pi/PortLog interfaces;
- a project migration or alternate authoritative persistence store becomes necessary;
- the threat model expands to distrust host Pi/model orchestration.

## Explicit deferrals

- Detailed implementation tickets and estimates.
- Production code, package changes, certificates, notarization credentials, or release builds.
- Final operational telemetry retention values beyond the bounded-evidence requirement.
- QEMU removal, feature-flag cleanup, or browser/hosted code deletion.
- Expansion beyond Electron-only arm64 macOS 14+.

The user explicitly confirmed the disabled-by-default capability rollout, QEMU-then-krun backend sequence, optional callback inside the existing host Pi adapter, retained host/domain path, promotion and cleanup gates, and migration-free host-authored provenance model during the `.8` grilling sequence.
