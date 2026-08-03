# PortLog isolated runtime architecture decision

Bead: `pydexpi-datalog-1-23bh.7`

## Decision

PortLog will adopt a **Hybrid isolated-command architecture** for its Electron-only desktop product:

- Pi core+AI and every PortLog-owned capability remain in the trusted host worker.
- Only the untrusted uploaded-bundle command-line toolchain and its native descendants execute in a disposable Linux micro-VM.
- PortLog integrates directly with upstream Gondolin through one PortLog-owned isolated-command adapter.
- The first packaged backend experiment is Gondolin's Darwin-arm64 `krun` runner. QEMU/HVF remains the executable development reference and a possible later fallback only after independently passing the same release gates.
- VMPI and OMP are not production runtime dependencies.
- Isolation fails closed. PortLog never silently executes the risky command on the host or falls back to TCG, Homebrew, an unsigned helper, or a less restrictive policy.

This is the selected whole-runtime architecture and reuse level. The adoption sequence remains bead `.8`; production implementation and release certification are not performed here.

## Why Hybrid

The threat is the untrusted review bundle processed by a command-line toolchain that may start native processes. Pi core+AI is pinned application code running with a PortLog-selected tool set; Datalog itself is not the reason to virtualize the whole agent.

Hybrid isolates that threat directly while retaining the current deep `createTurn` module. Provider credentials, model streaming, bounded PortLog callbacks, event normalization, posture enforcement, terminal classification, manifest writes, and durable artifacts keep their existing host owners. The guest receives none of those ambient authorities.

Full guest would isolate Pi too, but it would require new privileged model mediation, PortLog capability RPC, event framing, whole-agent cancellation, session suppression, and artifact-transfer protocols. Unmodified VMPI supplies none of those protocols and exposes a read-write host workspace plus guest-readable configuration/secrets. For the accepted threat model, Full guest adds a larger interface and regression radius without a compensating security benefit.

## Runtime shape

```text
Electron main
  └─ supervised host worker
       ├─ runLocalReviewInspection / createTurn
       │    ├─ host Pi core+AI
       │    ├─ portlog_evidence ────────> host sidecar/flow
       │    ├─ portlog_rule_check ──────> host sidecar/flow
       │    └─ portlog_isolated_command
       │          └─ isolated-command adapter
       │               └─ Gondolin
       │                    └─ disposable krun or qualified QEMU/HVF guest
       └─ PortLog record and manifest ownership
```

The isolated-command adapter is an internal deep module. Its callers know a bounded request/result interface, not Gondolin, VMPI, krun, QEMU, mounts, PTYs, checkpoints, image paths, or candidate-pickup mechanics.

Conceptually:

```text
runIsolatedCommand({
  runId,
  immutableInputBundle,
  commandProfile,
  limits,
  signal
}) -> admitted result | bounded rejection | terminal failure
```

## Reuse and ownership

| Module | Decision | Evidence and rationale |
| --- | --- | --- |
| Pi core+AI 0.80.6 | **Reuse unchanged on host** | Current in-memory agent already provides model streaming and sequential tool orchestration while PortLog owns tools, credentials, events, and persistence. |
| Existing PortLog Pi adapter | **Retain and extend narrowly** | Add one bounded isolated-command tool; do not replace `createTurn` or move domain authority into the guest. |
| OMP | **Design evidence only** | Its interfaces inform lifecycle design, but its coding shell, auth, tools, and session persistence are not PortLog product modules. |
| VMPI 0.4.1 | **Prototype evidence only; do not ship** | It proved Gondolin/QEMU execution on Apple Silicon but hardcodes a read-write `/workspace`, exposes Pi config/secrets, copies sessions, and lacks PortLog protocols. |
| Gondolin | **Reuse upstream directly** | Its VM, VFS, network-policy, process, and lifecycle mechanisms are the useful substrate. PortLog supplies product policy through the adapter. |
| Gondolin krun runner | **Preferred packaged experiment** | Compact Darwin-arm64 native payload and explicit Hypervisor entitlement make it a better packaging candidate, but it remains experimental and unqualified in the packaged app. |
| QEMU/HVF | **Measured reference; conditional fallback** | The prototype passed boot/native execution/network/cancellation at 2 GiB. Shipping requires a minimized relocatable bundle, signatures, licenses/source compliance, and clean-machine proof. |
| PortLog isolated-command adapter | **New PortLog-owned module** | Product-specific command profiles, provenance, limits, admission, PortLog terminal semantics, and Electron cancellation do not belong in generic Gondolin. |

Generic missing mechanisms should be contributed upstream to Gondolin when they are broadly reusable. PortLog will not fork or replace Pi, VMPI, or Gondolin without new executable evidence of a blocker that cannot be resolved by upstream contribution or this adapter.

## Fixed isolation policy

Every risky command execution must satisfy all of these invariants:

1. The guest receives exactly the uploaded immutable input bundle through read-only projection.
2. Scratch is per-run, ephemeral, bounded, and destroyed at terminal completion.
3. There is no `/workspace` host-project mount and no ambient host filesystem, PortLog project, sidecar endpoint, Pi config, credential, or artifact-store access.
4. Network is deny-all. Any future exception requires a separately authorized, destination-bound host mediation design; unrestricted guest networking is not permitted.
5. The guest exports at most one schema-, count-, and size-bounded candidate. The host validates and admits or rejects it before Pi receives a tool result.
6. Failed or cancelled runs export no successful candidate. Late guest output cannot change the PortLog terminal record.
7. Cancellation closes the guest and all descendants within the accepted bound; no process, scratch, session, transcript, or mutable checkpoint survives.
8. Each retry is cold with new run identity and scratch. Immutable signed base assets may be reused, but no prior guest process or mutable session state is resumed.
9. Raw VM/PTY data is bounded supervisor evidence, never the PortLog event or persistence contract.

## Fail-closed runtime selection

The adapter must select an explicitly packaged, arm64 hardware-virtualized backend by absolute path and verify its expected identity/configuration. If initialization, entitlement, signature, image verification, mount policy, network policy, cancellation wiring, or cleanup cannot be established, the command tool returns an isolated-execution-unavailable failure.

Forbidden fallbacks:

- host Bash or another host native-process path;
- QEMU TCG, because QEMU does not treat it as a supported guest-isolation configuration;
- user-installed Homebrew QEMU or PATH discovery;
- an ad-hoc/unsigned VMM helper in a production build;
- VMPI's fixed workspace/config/session behavior;
- a backend that weakens the fixed input, network, artifact, or cleanup policy.

QEMU/HVF may become a fallback only after it passes the same contract as krun. Backend variation stays inside the isolated-command implementation and does not change its PortLog-facing interface.

## Packaging and release gates

Virtualization is feasible for the direct-distribution, arm64-only macOS 14+ product, but the current development DMG is not production-eligible. Before enabling the command tool in a public build, the selected backend must pass all of the following:

1. All spawned native executables and dylibs are outside ASAR, arm64, relocatable, and included without Homebrew or developer-tool dependencies.
2. Nested code is signed inside-out with Developer ID and secure timestamps; the actual Hypervisor API caller carries `com.apple.security.hypervisor`; Electron uses an explicit least-privilege hardened-runtime entitlement set.
3. Hardened Runtime and strict verification are enabled, signing exclusions are removed, and the final DMG is notarized and stapled.
4. Guest kernel/rootfs/initrd and other base assets are immutable, checksum-pinned, versioned, and resolved from signed resources or PortLog-owned state—not the app bundle's writable path or an implicit first-use registry.
5. A clean non-admin macOS 14+ Apple Silicon machine with no Homebrew, Node, Python, QEMU, or developer tools passes install, boot, representative review, confinement probes, cancellation, cold retry, quit/relaunch, offline/error recovery, and cleanup.
6. Third-party notices and corresponding-source obligations are complete for the exact backend, dylibs, kernel, firmware, and guest payload shipped.

Until krun passes these gates, it is a packaging experiment rather than production evidence. QEMU remains the known-working development reference, not an automatic production fallback.

## Rejected alternatives

### Ship unmodified VMPI

Rejected. Its product semantics violate the accepted isolation policy, and changing those semantics plus adding PortLog mediation would make it a different integration rather than unchanged reuse.

### Put Pi in the guest

Rejected for the current threat model. It adds privileged channels and lifecycle complexity while host Pi is already a bounded trusted orchestrator. Reconsider only if PortLog begins treating Pi/model-driven orchestration itself as untrusted and a runtime demonstrates credentialless model mediation, host-authorized capabilities, structured events, bounded artifacts, and complete guest-agent cleanup.

### Run risky commands locally with Bash restrictions

Rejected. Shell quoting, environment filtering, working-directory controls, or application-level allowlists do not isolate arbitrary native descendants from the host user account.

### Depend on user-installed QEMU

Rejected. It breaks clean-machine installation, reproducibility, signing/notarization, version pinning, license inventory, and fail-closed backend selection.

### Select krun as already production-ready

Rejected. Its smaller package is promising, but no signed/notarized PortLog build has executed the representative scenario with it. Architecture preference is not release qualification.

## Reconsideration triggers

Reopen this decision only if one of these changes materially:

- Pi/model orchestration enters the untrusted threat model;
- krun cannot satisfy a fixed isolation or packaging gate and QEMU/HVF also fails it;
- Gondolin cannot expose a required generic mechanism through upstream contribution or a thin adapter;
- macOS platform policy removes the required direct-distribution Hypervisor capability;
- the product expands beyond arm64 macOS or beyond the Electron-only surface;
- executable evidence shows the adapter cannot keep PortLog authority, credentials, events, or persistence on the host.

## Evidence base

- `.1`: current Electron runtime ownership and `createTurn` seam.
- `.2`: pinned Pi, OMP, VMPI, and Gondolin capability/reuse inventory.
- `.3`: Apple Silicon packaging, signing, notarization, entitlement, architecture, and redistribution constraints.
- `.4`: representative Hybrid/Full-guest review and confinement contract.
- `.5`: executable unmodified VMPI/Gondolin/QEMU prototype on the target workstation.
- `.6`: topology comparison selecting Hybrid on reuse, credential safety, structured integration, provenance, lifecycle, packaging coupling, and regression radius.

The user explicitly confirmed Hybrid, direct Gondolin integration, krun-first/QEMU-reference backend posture, the reuse levels above, the disposable deny-all isolation policy, and fail-closed behavior during the `.7` grilling sequence.
