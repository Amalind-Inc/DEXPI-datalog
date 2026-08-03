# Host-agent versus guest-agent integration comparison

Bead: `pydexpi-datalog-1-23bh.6`

## Answer

For PortLog's current Electron runtime, **Hybrid is the better integration path**: keep Pi core+AI and all PortLog domain operations on the host, and place only the untrusted native command toolchain in an isolated guest.

This conclusion is about topology and adapter depth. It does not select the final virtualization package, packaging strategy, or production rollout; beads `.3`, `.7`, and `.8` retain those decisions.

Hybrid wins because it preserves the existing deep `createTurn` module and its host-owned credential, event, persistence, posture, and cancellation behavior. It requires one new internal isolated-command module with a bounded request/result interface. Full guest would replace the entire turn implementation and additionally require safe model mediation, host-authorized PortLog capability RPC, guest event translation, guest Pi lifecycle/session suppression, and bounded artifact transfer. None of those Full-guest protocols exists today, and unmodified VMPI fails the required mount and credential boundaries.

## Compared topologies

### Hybrid

- Electron main and the worker keep their current responsibilities.
- The existing in-memory Pi 0.80.6 agent remains host-side and continues using the provider credential directly.
- Existing `portlog_evidence` and `portlog_rule_check` tools remain bounded host callbacks to the sidecar/flow.
- A new `portlog_isolated_command` tool invokes an isolated-command module.
- The module alone owns guest setup, exact read-only input projection, ephemeral scratch, process supervision, network denial, cancellation, candidate retrieval, validation, and destruction.
- Pi receives only the admitted bounded result or a bounded host rejection/failure.

### Full guest

- A new adapter behind `createTurn` starts Pi and the native command toolchain in the guest.
- Model traffic must cross a host-mediated protocol that never reveals a reusable provider credential.
- Every PortLog tool call must cross a separate host authorization protocol.
- Guest Pi events must be translated back into the three permitted nonterminal PortLog event forms.
- Result candidates, cancellation, process state, and cleanup must cross the VM seam without creating an alternate transcript/session store.

## Decision matrix

| Criterion | Hybrid | Full guest |
| --- | --- | --- |
| Pi reuse | Reuses exact current Pi core+AI 0.80.6 and current in-memory orchestration unchanged. | Pi core+AI can be reused, but model transport, tools, event subscription, configuration, and lifecycle must be reconstructed in the guest adapter. |
| Existing seam | Keeps `createTurn` implementation and wrapper ownership unchanged. The isolated-command seam is internal to the current Pi adapter. | Requires a second whole-turn adapter at `createTurn`; the interface can remain stable, but much more behavior moves behind the new adapter. |
| Credential safety | Provider key stays in the existing host Pi process and is never needed by the risky guest. | Hard-gated on a new model proxy/opaque authorization protocol. Passing the current key is a scenario failure; VMPI's secret injection is therefore unusable. |
| PortLog authorization | Existing bounded callbacks execute on the host exactly as today. The risky guest receives none. | Requires a guest-to-host capability protocol with request validation, cancellation, correlation, bounds, and no sidecar/project authority leakage. |
| Structured Electron integration | Existing Pi-to-PortLog event translation, terminal ownership, and record construction remain local. One command tool contributes ordinary request/result events. | Guest Pi events and tool calls must be framed, correlated, bounded, translated, and separated from raw VM/PTY output. VMPI supplies no such protocol. |
| Provenance and artifacts | Host already owns the deterministic check and manifest. The new module admits exactly one candidate before Pi sees it. | Must combine host deterministic artifacts, guest Pi events, and guest command candidate transfer while preventing guest sessions/transcripts from becoming authoritative stores. |
| Cancellation | Existing Electron → worker → wrapper → Pi cancellation remains. The command module adds one bounded abort/close chain for the active guest. | Cancellation must stop host mediation, guest Pi, its active tool, native descendants, event delivery, and artifact export while still resolving the host `TurnRuntime` exactly once. |
| Persistence | Current PortLog records and artifacts stay host-owned; guest state can be disposable per command. | Must suppress Pi/OMP/VMPI session persistence and prove no guest agent state survives or is copied back. Unmodified VMPI does copy sessions back when enabled. |
| Isolation scope | Smaller trusted computing base inside the guest: uploaded inputs plus one command toolchain. Host Pi is trusted orchestration, not untrusted native code. | Pi joins the guest attack surface and must be supplied model and capability channels. This isolates more code but creates more privileged ingress paths. |
| Packaging/runtime coupling | Guest image needs the risky command toolchain, not Pi/provider configuration. | Guest image and adapter are coupled to Pi version, model transport behavior, tool schemas, event semantics, and command dependencies. |
| Measured VMPI fit | Its Gondolin/QEMU substrate is relevant, but fixed VMPI workspace/config behavior must be bypassed or changed for the command module. | Unmodified VMPI directly fails the no-workspace and no-credential requirements and lacks all host mediation protocols. |
| Regression radius | Concentrated in one new tool plus one isolated-command module; wrapper, renderer, IPC, manifest, sidecar, and existing domain tools remain stable. | Spans turn construction, model access, all tool calls, event mapping, cancellation, guest image, artifact exchange, and session behavior. |

## Deep-module reading

The current `runLocalReviewInspection`/`createTurn` module has useful depth: a small interface hides event sequencing, posture enforcement, terminal classification, persistence timing, and cleanup. Hybrid leaves that leverage and locality intact.

The proposed isolated-command module should also be deep. Its callers should not learn Gondolin, QEMU, VM mounts, PTYs, checkpoint details, or candidate-pickup mechanics. A suitable conceptual interface is:

```text
runIsolatedCommand({
  runId,
  immutableInputBundle,
  commandProfile,
  limits,
  signal
}) -> admitted bounded result | bounded rejection | terminal failure
```

The interface includes strict invariants: no host paths, no ambient credentials/config, deny-all network, read-only input, ephemeral scratch, one schema/size-bounded candidate, host-side admission, complete descendant termination, and no durable guest state. Production Gondolin execution and an in-memory conformance adapter make this an actual internal seam; tests exercise the same interface as Pi.

Full guest can technically preserve the external `createTurn` interface, but its implementation needs several internal ports. The deletion test exposes the difference: deleting Hybrid's isolated-command module would spread guest lifecycle and admission concerns into one tool implementation; deleting a Full-guest adapter would re-expose model proxying, capability RPC, event framing, session policy, and whole-turn lifecycle across Electron/worker/runtime code. The latter is a substantially larger module and integration commitment without compensating product capability for this scenario.

## Security reading

The security concern is not Datalog as a language. It is the untrusted uploaded bundle plus command-line toolchain and any native processes that toolchain can start. Hybrid places that execution in the guest while keeping trusted orchestration and authorization outside.

Full guest would reduce exposure if Pi itself or its model parser/tool dispatcher were treated as untrusted. That is not the current threat model: Pi core+AI is pinned application code, exposes only PortLog-selected tools, creates no coding-agent session, and runs in the already trusted Electron worker. Moving it into the guest therefore adds privileged bridges without removing the native-process risk that Hybrid already isolates.

Reconsider Full guest only if the threat model changes to distrust Pi/model-driven orchestration itself, or if a future upstream runtime provides all of the following as demonstrated, narrow interfaces:

1. credentialless or one-turn opaque host-mediated model access;
2. host-authorized, schema-bounded capability calls;
3. structured nonterminal event transport compatible with `createTurn`;
4. read-only input plus ephemeral scratch with bounded artifact export;
5. cancellation and cleanup covering Pi and all descendants;
6. no guest session/config persistence.

## Minimal Hybrid adapter ownership

| Concern | Owner |
| --- | --- |
| Provider credential and model stream | Existing host Pi adapter |
| PortLog evidence/rule authorization | Existing worker callbacks and sidecar/flow |
| Command request schema and tool result | Host Pi adapter |
| VM/image/mount/network/process lifecycle | New isolated-command module using the selected substrate |
| Candidate bounds and admission/rejection | New module, host side |
| PortLog events, terminal state, manifest | Existing `runLocalReviewInspection` wrapper |
| Electron worker supervision | Existing Electron main/worker chain |

This ownership preserves the settled Electron-only module split and gives the next architecture bead a clear default: select Hybrid unless macOS packaging evidence in `.3` disqualifies the underlying guest substrate.

## Evidence and limits

This comparison rests on the checked-in current-runtime map (`.1`), pinned upstream inventory (`.2`), frozen representative scenario (`.4`), executable VMPI Apple Silicon prototype (`.5`), and direct inspection of `frontend/desktop/local-review-inspection.ts` and `frontend/desktop/pi-turn-adapter.ts`.

The configured `sol-teacher` agent type was unavailable when the required architecture consultation was attempted. The conclusion therefore relies on repository and executable evidence only. No production adapter was implemented, and missing Hybrid confinement behavior remains work to prove rather than an assumed pass.
