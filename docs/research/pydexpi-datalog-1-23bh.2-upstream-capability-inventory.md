# pydexpi-datalog-1-23bh.2 — Upstream Capability Inventory

**Scope.** This is a synthesis of the fixed sources listed below, frozen on
2026-08-03. It is not an executable proof, packaging decision, topology
selection, or runtime-architecture decision.

## Concise answer

**Observed fact.** PortLog already pins and uses
`@earendil-works/pi-agent-core@0.80.6` and `@earendil-works/pi-ai@0.80.6`
directly, with a PortLog-owned tool whitelist, credential injection,
sequential execution, event translation, abort wiring, and no `AgentSession`.
The exact Pi core `Agent` and Pi AI provider/model modules are the upstream
modules reused unchanged in the current production adapter; PortLog's adapter
owns their translation into the `createTurn` interface. [P1] [L1] [L2] [L3]

**Inference.** The most useful reuse boundary is not a whole upstream runtime:
it is the internal `RunLocalReviewInspectionOptions.createTurn` seam. Its
depth hides runtime mechanics while preserving locality: Electron main keeps
composition, credentials, manifest creation, and worker supervision; the
worker keeps bounded callbacks; the loopback sidecar keeps domain operations
and artifacts; and `runLocalReviewInspection` keeps normalized records,
events, posture, terminal mapping, and manifest upserts. Pi remains the sole
production adapter at that seam. [L3]

Electron is the sole product surface; its renderer, main process, worker, and
loopback sidecar remain internal Electron modules/adapters, not public browser
or backend products. [L3]

**Recommendation.** Keep the exact Pi core+AI modules unchanged behind the
existing adapter. Treat OMP as evidence of useful interfaces, not a shell to
adopt. Use unmodified VMPI only for bead `.5`'s prototype. Treat Gondolin as a
potential lower-level implementation behind a **thin PortLog adapter**, not as
the chosen runtime. This report does not choose host-agent versus guest-agent
(`.6`) or the whole runtime (`.7`).

**Explicit deferrals.** Apple Silicon proof belongs to `.5`; packaging,
signing, notarization, entitlement, redistribution, and installation
feasibility belong to `.3`; topology belongs to `.6`; final architecture and
reuse selection belong to `.7`. A README claim is documented behavior, not
executable proof.

## Evidence snapshot

| Project | Fixed primary source | Observed module/interface boundary | Initial inventory posture |
| --- | --- | --- | --- |
| Pi | [`f0deb8d`](https://github.com/earendil-works/pi/tree/f0deb8dd8e9611e89b5bc4145ca92c03ae6ed4ee); published exact `0.80.6` packages [P1] | `pi-agent-core` `Agent` is an in-memory loop; `pi-ai` supplies model/protocol types. `pi-coding-agent`/`AgentSession` is a separate coding shell. | Reuse the exact low-level pair unchanged; exclude the coding shell. |
| OMP | [`c0fab5a` / v0.12.4](https://github.com/open-horizon-labs/oh-omp/tree/c0fab5aae3189191a2cd03524c2abea64318acfb), MIT [O1] | Its SDK and RPC expose an `AgentSession`; tools, extensions, auth, discovery, context, and file/session persistence are assembled around it. | Mine interface evidence only; do not adopt OMP wholesale. |
| VMPI | [`@the-agency/vmpi@0.4.1`](https://pi.dev/packages/%40the-agency/vmpi) and [`b3742ee`](https://github.com/JoshMock/the-agency/tree/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi), MIT [V1] | A CLI implementation resumes a Gondolin checkpoint, mounts workspace/config, launches guest Pi in an attached PTY, and copies sessions back. | Reuse unchanged only for `.5`'s unmodified prototype. |
| Gondolin | [`29fa74d`](https://github.com/earendil-works/gondolin/tree/29fa74d802112f29c720990aced26165e0d57d84), Apache-2.0 [G1] | `VM`, VFS providers, HTTP/TLS hooks, checkpoint/resume, exec streams, ingress, and SSH are host-side policy interfaces. | Potential substrate behind a thin PortLog adapter; no selection yet. |

## Cross-project seven-family matrix

`RU` means **reuse unchanged**; `TPA` means **thin PortLog adapter**;
`CU` means **contribute upstream** if later evidence requires an extraction or
missing capability; `NA` means do not adopt that implementation.

| Capability family | Pi | OMP | VMPI | Gondolin |
| --- | --- | --- | --- | --- |
| 1. harness/agent loop | `Agent` prompt/stream/tool continuation: RU. [P1] | `AgentSession` loop exists, but is the coding-shell aggregate: NA. [O2] | Runs Pi CLI inside a VM; no embeddable loop interface observed: prototype-only RU. [V2] | Executes guest processes, not an LLM agent loop: TPA only if `.6` selects a guest path. [G2] |
| 2. general tools/tool execution | Declared tools, validation, sequential mode, hooks: RU with PortLog-defined tools only. [P1] | Broad builtin registry (bash, files, browser, Python, SSH, task, etc.) is coupled to shell state/settings: NA. [O2] | Guest Pi has its normal tools over a writable workspace: prototype-only RU; not PortLog authorization. [V1] | `vm.exec`/`vm.shell` run guest commands; it is an execution implementation, not governed-tool policy: TPA. [G2] |
| 3. isolation/policy enforcement | No VM/filesystem/network isolation; PortLog governs its own tools: RU for loop only. [P1] | Tool allowlists/hooks can block calls, but shell tools retain host-oriented authority: NA for product isolation. [O4] | QEMU VM, VFS mounts, HTTP/TLS policy, host-scoped secrets: RU for `.5` only. [V1] | Programmable VFS, HTTP/TLS hooks, host allowlists, placeholders, ingress/SSH policy: TPA. [G3] [G4] |
| 4. lifecycle/cancellation/checkpointing | Abort signal reaches model/tool work; subprocess stop remains PortLog-owned: RU. [P1] | `abort`, retry, compaction, sessions, and tool jobs are `AgentSession` behavior: NA. [O2] | `setup` checkpoints; run resumes and closes VM on SIGINT/SIGTERM. No host API or proof of durable cancellation observed: prototype-only RU. [V2] | create/close, disk checkpoint/resume, exec streams; aborting `exec` does not yet guarantee guest termination: TPA, possibly CU. [G2] [G5] |
| 5. extensions/custom tools/hooks | Core tool hooks and supplied tool list: RU; PortLog owns schemas/policy. [P1] | Extension factories, event handlers, interception, custom tools, and UI/session APIs exist but depend on `AgentSession`: CU only for a future narrowly extracted interface; otherwise NA. [O3] [O4] | Guest Pi extensions are installed/configured as Pi behavior; not a PortLog extension seam: NA. [V1] | JS HTTP/VFS/ingress hooks are host policy extension points: TPA. [G3] [G4] |
| 6. structured event streaming/control protocol | `Agent` lifecycle and tool events map through current adapter: RU, with PortLog normalization. [P1] [L3] | SDK subscription and JSONL RPC have prompt/abort/session control and typed event frames, but include coding-session semantics: TPA only as a protocol shape; do not import it now. [O2] [O3] | Attached PTY exposes terminal I/O, not a documented structured PortLog event/control protocol: UNKNOWN; `.5` must capture it. [V2] | `exec` exposes buffered/piped stdout/stderr and terminal attachment, not agent-event semantics: TPA. [G2] |
| 7. sessions/context/persistence | Core state is in memory: RU; PortLog remains durable-record authority. [P1] | JSONL session trees, compaction, branches, blobs, auth/model/context discovery are coding-shell persistence: NA. [O2] [O5] | Copies a Pi config snapshot; translates `/workspace` Pi sessions and merges them to host config: prototype-only RU. [V2] [V3] | Disk-only checkpoints, VFS/rootfs modes, VM attach metadata; no PortLog review record model: TPA. [G2] [G5] |

## Per-project module findings and reuse levels

### Pi

| Module/interface | Observed fact | Reuse level |
| --- | --- | --- |
| `@earendil-works/pi-agent-core@0.80.6` `Agent` | Injected `streamFn` and `getApiKey`, declared tools, lifecycle events, sequential tool execution, and abort-signal plumbing are present. The local controlled spike already exercised these without Pi persistence. [P1] [L1] [L2] | **reuse unchanged** behind the current Pi adapter. |
| `@earendil-works/pi-ai@0.80.6` | PortLog imports its `Model` types and provider stream functions in the production adapter. [L1] | **reuse unchanged** with core. |
| Pi coding-agent / `AgentSession` | It owns coding tools, session/auth/config conventions, compaction, and persistence; that conflicts with PortLog ownership. [P1] | Do not adopt or wrap. |
| Pi event shape | It is an upstream interface, not the PortLog event contract; current code translates it below `createTurn`. [L3] | **thin PortLog adapter** (already present). |

### OMP

| Module/interface | Observed fact | Reuse level |
| --- | --- | --- |
| `createAgentSession` SDK | Defaults discover file-backed sessions, auth/model stores, settings, skills/context, extensions, builtins, MCP, and LSP; it can be configured in-memory, but remains an `AgentSession` composition API. [O2] | Do not adopt as a PortLog module. |
| RPC mode | Newline-delimited JSON over stdio accepts prompt/abort/session commands and emits responses plus `AgentSessionEvent` frames. Its control protocol has leverage for an external shell, but it carries coding-session concepts. [O3] | **thin PortLog adapter** only if `.6` needs that exact external protocol; no dependency decision now. |
| Extensions/custom tools/hooks | Extensions register tools/events/UI and intercept all tool calls/results; contexts expose session manager, UI, model registry, compaction, and commands. [O4] | **contribute upstream** only if a future requirement justifies extracting a small host-neutral tool/event interface; do not port the runtime. |
| Builtin tool registry | The registry builds host-oriented filesystem, shell, browser, Python, LSP, SSH, task, checkpoint, and web tools from a shell-specific `ToolSession`. [O2] | Do not adopt or reimplement. |
| Session/context storage | JSONL session tree, compaction, branches, blob externalization, history DB, and persistent settings are an alternate authority for transcript/context. [O5] | Do not adopt or wrap. |

### VMPI

| Module/interface | Observed fact | Reuse level |
| --- | --- | --- |
| `vmpi setup` / base checkpoint | Setup builds a QEMU guest, installs Pi/packages/hooks, writes a qcow2 base checkpoint, then closes the setup VM. [V2] | **reuse unchanged** only for the `.5` prototype. |
| `vmpi` run lifecycle | It resumes the checkpoint, mounts the current directory at `/workspace`, mounts a temporary copied Pi-config snapshot at `/root/.pi`, runs Pi through `vm.shell({ attach: true })`, merges sessions, and closes. [V2] [V3] | **reuse unchanged** only for `.5`; not yet a product integration interface. |
| Network/secrets/config | `custom`, `deny-all`, and `allow-all` policy; provider/domain lists; host TCP mappings; per-host secret config; and extra mounts are configured before resume. Secrets use a tmpfs env file in VMPI's run path. [V1] [V2] [V3] | Prototype evidence only; a production adapter is not justified before `.5`. |
| PTY/events/cancellation | VMPI attaches a terminal; it emits human/debug stdout/stderr. SIGINT/SIGTERM close the VM and exit. A structured Electron protocol, cancellation classification, and artifact behavior are unproven. [V2] | UNKNOWN; `.5` must test before any adapter proposal. |
| Platform statement | VMPI 0.4.1 README says macOS and aarch64 are untested. [V1] | No Apple Silicon support claim. |

### Gondolin

| Module/interface | Observed fact | Reuse level |
| --- | --- | --- |
| `VM`, `vm.exec`, `vm.shell` | The VM API creates/closes VMs, streams stdout/stderr with backpressure, and can attach a PTY. `ExecOptions.signal` aborts the local wait but does not yet guarantee guest termination. [G2] | **thin PortLog adapter** for lifecycle/output translation, conditional on `.5`/`.6`. |
| VFS / rootfs / mounts | Programmable VFS mounts and rootfs `readonly`, `memory`, and `cow` modes exist; host-backed mounts are policy-sensitive. [G5] | **thin PortLog adapter**; PortLog must choose and constrain mounts. |
| HTTP/TLS hooks and secret placeholders | Host allowlists, request/response hooks, placeholder secret injection, ingress hooks, and restricted SSH egress exist. Hooks can observe expanded secrets, so logging is a security boundary. [G3] [G4] | **thin PortLog adapter**; credentials remain Electron-owned. |
| checkpoint/resume | qcow2 disk checkpoint/resume exists; it is not full memory save/restore, and tmpfs paths are excluded. [G5] [G6] | **thin PortLog adapter** for a future selected lifecycle only. |
| QEMU / krun | QEMU is default; krun is experimental with caveats and backend compatibility constraints. [G6] | No backend selection here; `.3` qualifies packaging and `.5` proves target behavior. |

## What not to adopt or reimplement

- Do not adopt Pi coding-agent/`AgentSession`, OMP wholesale, OMP's builtin
  coding tools, OMP persistence/auth/context authority, or VMPI's session files
  as PortLog's durable review record.
- Do not reimplement Pi's generic streamed agent/tool loop, Pi AI types, or
  Gondolin's VM/VFS/HTTP-TLS policy mechanisms before the successor evidence
  says a module is unsuitable.
- Do not move Electron composition, credential resolution, worker callback
  construction, sidecar deterministic operations, PortLog record/event
  normalization, posture, cancellation mapping, or manifest writes across the
  `createTurn` seam. That would reduce depth and locality rather than increase
  leverage. [L3]
- Do not use OMP tool hooks as isolation proof: they are application-level
  interception around a large coding shell, whereas Gondolin is the candidate
  hardware/process policy implementation. [O4] [G3]
- Do not fork or replace an upstream module without documented blocking evidence. No
  such evidence exists yet; `.3`, `.5`, and `.6` must first show a necessary
  interface cannot be reused, adapted, or contributed upstream.

## Explicit unknowns and risks

| Unknown or risk | Evidence boundary | Required test/decision owner |
| --- | --- | --- |
| Apple Silicon behavior | VMPI documents macOS/aarch64 as untested; Gondolin documentation is not VMPI executable proof. [V1] | `.5`: run the unmodified package on the target workstation; `.3`: qualify packaged constraints. |
| VM termination semantics | Gondolin documents that aborting `vm.exec` does not guarantee guest process termination; VMPI signal cleanup closes its VM. [G2] [V2] | `.5`: interrupt model and tool work, inspect process exit, session merge, and artifacts; `.6`: compare cancellation chain by topology. |
| Structured Electron observability | VMPI attaches a PTY; Gondolin streams process I/O, neither establishes PortLog's three nonterminal events or terminal record mapping. [V2] [G2] | `.5`: capture actual raw output/control behavior; `.6`: determine adapter translation cost. |
| Mount and session provenance | VMPI snapshots Pi config, maps a writable workspace, translates `--workspace--` sessions, and merges files by size. This is not PortLog provenance. [V2] [V3] | `.5`: inspect read/write scope and surviving files; `.6`: compare host/guest authority. |
| Network/secret boundary | HTTP/TLS hooks provide host policy, but mapped TCP is a separate exception path and hooks may see expanded secrets. [G3] [G4] | `.5`: test allow/deny and provider credential use without logging secrets; `.6`: map authority boundary. |
| Checkpoint limits | Gondolin checkpoints disk, not VM memory; tmpfs paths do not persist. [G5] [G6] | `.5`: verify setup/run timing and surviving state; `.7`: decide whether it meets lifecycle needs. |

## Concrete inputs to successor beads

| Bead | This inventory supplies | It must still decide/prove |
| --- | --- | --- |
| `pydexpi-datalog-1-23bh.3` | VMPI requires QEMU; Gondolin has QEMU default and an experimental krun path with platform runner artifacts and backend caveats. [V1] [G1] [G6] | Packaging, signing, notarization, entitlements, redistribution, installation, architecture, and runtime feasibility. No conclusion here. |
| `pydexpi-datalog-1-23bh.5` | Run **unmodified** VMPI 0.4.1: checkpoint build/resume, workspace and Pi-config mounts, session transfer, allowlisted network, host-scoped secrets, raw PTY observability, SIGINT/SIGTERM, and surviving artifacts. [V1] [V2] [V3] | Apple Silicon execution proof and measured behavior; do not infer support from README text. |
| `pydexpi-datalog-1-23bh.6` | Compare two paths against the `.1` `createTurn` interface: complete Pi in guest versus host Pi with guest-executed tools. Pi core is already reusable unchanged; VMPI/Gondolin only expose process/VM mechanisms. [P1] [L3] [V2] [G2] | Select neither path until `.5` evidence covers lifecycle, observability, mounts, credentials, and cancellation. |
| `pydexpi-datalog-1-23bh.7` | Candidate module levels: Pi core+AI = reuse unchanged; current Pi translation/Gondolin policy layer = thin PortLog adapter; narrowly extracted OMP interface = contribute upstream only if needed; fork/replace requires blocking evidence. | Select the whole runtime only after `.3` and `.6`; preserve the Electron-only responsibility split. |

## Primary-source index

- **[P1] Pi exact packages:** [core declarations](https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent.d.ts), [Agent implementation](https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent.js), [agent loop](https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent-loop.js), [root exports](https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/index.js), and [Pi snapshot](https://github.com/earendil-works/pi/tree/f0deb8dd8e9611e89b5bc4145ca92c03ae6ed4ee).
- **[O1] OMP snapshot/README:** [fixed commit README](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/README.md).
- **[O2] OMP SDK/tool composition:** [SDK documentation](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/docs/sdk.md), [SDK source](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/packages/coding-agent/src/sdk.ts), and [tool registry](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/packages/coding-agent/src/tools/index.ts).
- **[O3] OMP RPC:** [fixed-commit RPC documentation](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/docs/rpc.md).
- **[O4] OMP extensions:** [fixed-commit extension documentation](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/docs/extensions.md) and [extension types](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/packages/coding-agent/src/extensibility/extensions/types.ts).
- **[O5] OMP sessions:** [fixed-commit session model](https://github.com/open-horizon-labs/oh-omp/blob/c0fab5aae3189191a2cd03524c2abea64318acfb/docs/session.md).
- **[V1] VMPI README/package:** [README](https://github.com/JoshMock/the-agency/blob/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi/README.md) and [package metadata](https://github.com/JoshMock/the-agency/blob/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi/package.json).
- **[V2] VMPI lifecycle:** [fixed-commit `vmpi.ts`](https://github.com/JoshMock/the-agency/blob/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi/vmpi.ts).
- **[V3] VMPI config/sessions:** [configuration](https://github.com/JoshMock/the-agency/blob/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi/config.ts) and [session mapping](https://github.com/JoshMock/the-agency/blob/b3742eea7afad8f6da8fe87a36efa1463d183af7/packages/vmpi/sessions.ts).
- **[G1] Gondolin overview:** [fixed-commit README](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/README.md).
- **[G2] Gondolin VM SDK:** [fixed-commit VM lifecycle, exec, PTY, and cancellation documentation](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/sdk-vm.md).
- **[G3] Gondolin network SDK:** [fixed-commit HTTP/TLS, ingress, and SSH policy documentation](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/sdk-network.md).
- **[G4] Gondolin secrets:** [fixed-commit placeholder and host-scoping documentation](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/secrets.md).
- **[G5] Gondolin storage/checkpoints:** [fixed-commit VFS and snapshot documentation](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/sdk-storage.md).
- **[G6] Gondolin backend/limitations:** [backend matrix](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/backends.md) and [limitations](https://github.com/earendil-works/gondolin/blob/29fa74d802112f29c720990aced26165e0d57d84/docs/limitations.md).
- **[L1] Current dependency and adapter:** [frontend package pins](../../frontend/package.json) and [Pi turn adapter](../../frontend/desktop/pi-turn-adapter.ts).
- **[L2] Local Pi assessment:** [Pi agent-loop fit assessment](../pi-agent-loop-fit-assessment.md).
- **[L3] Governing current seam:** [Electron runtime and candidate isolated-turn seam](pydexpi-datalog-1-23bh.1-current-runtime-seam.md).
