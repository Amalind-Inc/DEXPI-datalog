# `pydexpi-datalog-1-23bh.1` — Current PortLog Runtime and Isolated-Agent Seam

## Scope and evidence boundary

This is a source-grounded map of the current PortLog desktop and web/backend
runtime. It distinguishes observed code behavior from a narrow prototype
recommendation. It does not propose a runtime refactor, change a public
interface, or treat an upstream agent transcript as PortLog's audit record.

PortLog's governing boundary is explicit: the backend owns the resumable,
provider-neutral grounded-QA loop and authority for capabilities, route
receipts, validation, deterministic execution, artifacts, and interruption;
clients render state and submit actions. See [ADR-0003, *Use a Web-Native
Grounded Agent Harness*](../adr/0003-web-native-grounded-agent-harness.md).
The runtime is model-driven but remains bounded by capability policy and
operational safeguards, including user Stop and Answer Now steering. See
[ADR-0012, *Use model-driven runs with user steering and optional
constraints*](../adr/0012-model-driven-agent-runs.md).

Terminology follows the repository's definitions of a restricted grounded-QA
harness, deployment profile, structured execution trace, and trace event
envelope in [`CONTEXT.md`](../../CONTEXT.md).

## Concise answer

**Observed fact.** The narrowest existing runtime-replacement seam is the
optional `createTurn` factory supplied to
[`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts).
It accepts exactly PortLog-facing callbacks (`emit`, optional evidence lookup,
and optional deterministic rule check) and returns only `prompt`, `abort`, and
`dispose`; the default factory below it is the Pi-specific adapter. The
wrapper, rather than Pi, creates the PortLog local record, applies posture
rules, handles cancellation state, and persists the final local record.
[`RunLocalReviewInspectionOptions.createTurn` and
`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts)
are therefore a real insertion point, not an inferred architectural wish.

**Recommendation.** A parallel host/guest experiment should implement an
isolated-turn adapter behind that `createTurn` contract. Keep
`runLocalReviewInspection` on the PortLog host side; make the guest provide
only the three runtime operations and use PortLog-owned callbacks for evidence
and deterministic checks. This preserves the desktop UI, Electron IPC,
sidecar API, local record shape, and current domain authority while swapping
only agent-loop mechanics.

**Qualification.** This is an internal desktop seam, not a claim that the
current web backend already has a generic `AgentRuntime` abstraction. The web
`/turns` boundary intentionally owns request identity, turn persistence,
progress, cancellation, trace normalization, and review resume; replacing it
would be materially broader. Its current route delegates to
[`TurnLifecycleStore.start`](../../pydexpi_datalog/web/turn_lifecycle.py) and
[`ChainlitReviewFlow.run_qa_turn`](../../pydexpi_datalog/web/chainlit_review_flow.py),
not to an injected agent-runtime port. See
[`start_turn`](../../pydexpi_datalog/web/review_api.py).

## Observed current runtime call/path map

### Local desktop inspection and chat

| Stage | Observed path and owner | Contract that matters for an isolated path |
| --- | --- | --- |
| UI composition | The Assistant UI model adapter detects the Electron preload bridge, then calls `runDesktopInspection`; without that bridge it uses the web turn path. The desktop branch resolves a selected provider, subscribes to inspection events, invokes `runLocalInspection` or `runLocalChat`, and maps a cancelled/failed `LocalInspectionRecord` to UI behavior. [`PidRuntimeProvider.run` and `runDesktopInspection`](../../frontend/components/chat/pid-runtime-provider.tsx) | Do not alter the renderer-facing chat adapter or the preload API just to test a different loop. |
| Electron composition root | `electron-main.cjs` starts the local Python sidecar with `HARBORFIELD_DEPLOYMENT_PROFILE=local`, exposes IPC handlers, resolves the local model runtime, spawns the TypeScript worker, and relays worker event frames over `portlog:inspection-event`. [`startSidecar`, `resolveLocalRuntime`, and `runLocalTurn`](../../frontend/desktop/electron-main.cjs) | Electron remains the desktop composition root and credential broker. |
| Per-turn worker | `local-inspection-worker.ts` creates an `AbortController` from `SIGTERM`/`SIGINT`, writes a temporary `models.json`, maps the two PortLog tool callbacks to the loopback sidecar's topology and governed-check routes, runs the inspection wrapper, emits JSON event frames to stdout, and removes the temporary agent directory in `finally`. [`local-inspection-worker`](../../frontend/desktop/local-inspection-worker.ts) | A guest adapter needs an explicit event and capability bridge; it must not acquire its own permanent model/session directory by accident. |
| PortLog runtime wrapper | `runLocalReviewInspection` creates `LocalInspectionRecord` version 1, appends a sequenced/timestamped PortLog event union, collects evidence and deterministic-check results, applies Inspect/Verify/Chat posture rules, handles abort/failure, disposes the runtime, and upserts the local record. [`LocalInspectionEvent`, `LocalInspectionRecord`, and `runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts) | This is the selected host-side seam. Preserve record status, `finalText`, evidence IDs, deterministic checks, and event shape. |
| Current loop adapter | The wrapper's default is `createPiRuntime`, which calls `createGovernedPiReviewTurn`, subscribes to Pi events, and translates only text deltas and tool execution start/end into the PortLog event union. [`createPiRuntime` and `normalizePiEvent`](../../frontend/desktop/local-review-inspection.ts) | Raw Pi event names are deliberately not the boundary proposed for a guest. |
| Governed tool boundary | `createGovernedPiReviewTurn` constructs an in-memory Pi `Agent` with only `portlog_evidence` and/or `portlog_rule_check`, validates their argument shapes, sets sequential tool execution, injects a PortLog API key and stream function, and forwards `AbortSignal` to the tool callbacks. [`createGovernedPiReviewTurn`](../../frontend/desktop/pi-turn-adapter.ts) | Retain the allowlisted tool semantics; prohibit generic shell, filesystem, editing, or arbitrary-network tools with ambient host, project, or PortLog-domain access; host-authorized model transport remains separate. Isolated guest-internal utilities remain open to downstream evaluation. |
| Domain execution | The worker's evidence callback requests prepared topology from the local sidecar; its rule-check callback posts a scoped `check_id` and `scope_entity_id` to `/governed-checks`. The sidecar routes that check to `ChainlitReviewFlow.execute_governed_check`, which reads prepared facts, runs the allowlisted check, derives evidence/highlights, and writes a result artifact. [`local-inspection-worker`](../../frontend/desktop/local-inspection-worker.ts), [`execute_governed_check`](../../pydexpi_datalog/web/review_api.py), and [`ChainlitReviewFlow.execute_governed_check`](../../pydexpi_datalog/web/chainlit_review_flow.py) | The guest may request an operation; PortLog decides and executes it. |

### Web and backend grounded-QA path

| Stage | Observed path and owner | Contract that matters for an isolated path |
| --- | --- | --- |
| Deployment composition | `web/asgi.py` resolves one explicit local or hosted profile and constructs the API with either a fixed local principal or a hosted principal resolver. The API factory creates one workspace-scoped service graph containing `ArtifactStore`, `ChainlitReviewFlow`, `TurnLifecycleStore`, and `AuthoredRulePackStore`. [`asgi` composition root](../../pydexpi_datalog/web/asgi.py) and [`create_review_api_app` / `WorkspaceServices`](../../pydexpi_datalog/web/review_api.py) | Profile resolution and workspace scoping stay outside any agent guest. This is the ADR-0016 composition rule. |
| Browser-to-backend transport | `turn-client.startTurn` sends the question, deterministic request ID, conversation, selected scope, and active browser BYOK settings to the Next turn route. The route validates provider settings before forwarding. [`startTurn`](../../frontend/lib/turn-client.ts) and [`POST /api/review/sessions/[sessionId]/turns`](../../frontend/app/api/review/sessions/%5BsessionId%5D/turns/route.ts) | Do not change the HTTP request/response shape or turn-ID formula for an experiment. |
| Turn-start lifecycle | FastAPI's `POST /api/review/sessions/{session_id}/turns` derives `turn_id`, gives the harness a progress callback and a steering callback, and passes the work through `TurnLifecycleStore.start`. [`start_turn`](../../pydexpi_datalog/web/review_api.py) | This endpoint is a durable lifecycle boundary, not the narrow loop replacement seam. |
| Agent-loop adapter | `ChainlitReviewFlow._compute_qa_answer` builds `TopologyTools` from prepared artifacts and calls `run_grounded_qa_turn`. That function asks a `QATurnProvider` for a native tool call or final answer, executes only `TopologyTools.execute`, records the tool result, then returns it to the provider for the next round. [`_compute_qa_answer`](../../pydexpi_datalog/web/chainlit_review_flow.py) and [`run_grounded_qa_turn`](../../pydexpi_datalog/qa/grounded_qa_harness.py) | A `QATurnProvider` is only a model-wire adapter; it does not replace the backend loop or governance. |
| Model protocol adapter | `OpenAICompatibleQATurnProvider` sends the constrained tool schema plus `provide_answer`, accepts only native structured tool calls, and treats text that resembles a tool call as plain final text. [`OpenAICompatibleQATurnProvider.complete_with_tools`](../../pydexpi_datalog/qa/openai_compatible_qa_provider.py) | Preserve native-tool and final-answer validation if a future backend runtime is introduced. |
| Governance boundary | `TopologyTools.execute` resolves a capability from the manifest, denies unknown/denied tools, returns confirmation-required responses where applicable, applies budgets, and dispatches only implemented read-only operations. Generated-Datalog authorization is bound to backend-issued receipts and the active request. [`TopologyTools.execute`](../../pydexpi_datalog/qa/topology_tools.py) | This is PortLog domain authority, not guest-owned prompt policy. |
| Durable event transport | `TurnLifecycleStore` persists the initial turn before execution, appends progress, projects raw result trace events through `render_execution_trace`, appends text/evidence/review/cancellation/failure/completion events, and persists the turn JSON through `ArtifactStore`. The API exposes the stored turn and an NDJSON event view; the web UI polls the stored turn. [`TurnLifecycleStore`](../../pydexpi_datalog/web/turn_lifecycle.py), [`render_execution_trace`](../../pydexpi_datalog/web/execution_trace.py), and [`getTurn` / `reduceTurn`](../../frontend/lib/turn-client.ts) | Preserve this PortLog event and persistence contract rather than emitting an upstream transcript to the client. |

## Observed authority and persistence boundaries

### Domain modules that remain PortLog-owned

**Observed fact.** Preparation is not agent state. `ReviewSessionService`
derives and writes graph facts, Datalog facts, derived semantics, a topology
view, and readiness metadata into session-scoped artifacts; later code reloads
the same prepared materials by session ID. [`ReviewSessionService` and
`session_artifact_keys`](../../pydexpi_datalog/workflow/review_session.py)
are therefore domain/persistence owners that an agent guest must consume only
through a PortLog-mediated interface.

**Observed fact.** `ChainlitReviewFlow` converts prepared facts into
`TopologyTools`, compacts prior conversation, invokes the grounded harness, and
derives evidence-highlight state and review state. It is also the sidecar owner
of the desktop's explicit governed check. [`ChainlitReviewFlow._compute_qa_answer`
and `ChainlitReviewFlow.execute_governed_check`](../../pydexpi_datalog/web/chainlit_review_flow.py)
show that this is more than a model prompt builder.

**Observed fact.** The deterministic pump check allows a model to supply only
the check ID and scope; PortLog fixes the permitted check, its version, rule
source, required facts, execution engine, outcome vocabulary, and evidence.
[`run_governed_check`](../../pydexpi_datalog/verification/governed_check.py)
is the authoritative outcome boundary. The desktop Verify posture reinforces
this by replacing model prose with a PortLog restatement of a completed
deterministic result. [`verifyPrompt` and
`restateDeterministicCheck`](../../frontend/desktop/local-review-inspection.ts)

### Authentication and model-credential paths

**Observed fact — desktop.** The renderer selects a connected desktop provider
through preload IPC, while Electron resolves the usable runtime credential:
Anthropic and OpenAI Codex come from provider OAuth controllers backed by the
macOS Keychain; OpenRouter comes from process configuration (or `.env` for an
unpackaged development run). Electron passes the selected API key only into
the per-turn worker environment, and the Pi adapter receives it as an injected
`apiKey`/`getApiKey` value. [`resolveDesktopProvider`](../../frontend/components/chat/pid-runtime-provider.tsx),
[`resolveLocalRuntime` / `runLocalTurn`](../../frontend/desktop/electron-main.cjs),
[`createProviderAuthController`](../../frontend/desktop/provider-auth-controller.cjs),
and [`createGovernedPiReviewTurn`](../../frontend/desktop/pi-turn-adapter.ts)
locate those responsibilities.

**Observed fact — web local profile.** Browser BYOK keys live in
`localStorage` under `pydexpi.byok.v1`; `startTurn` includes active settings
with the turn, and the Next route validates them before calling the Python
backend. The local profile deliberately has no server-side key store, while
the in-process flow keeps the credential only in its session memory for
provider resolution. [`byok-keys`](../../frontend/lib/byok-keys.ts),
[`turn-client.startTurn`](../../frontend/lib/turn-client.ts),
[`configure_provider_settings`](../../pydexpi_datalog/web/chainlit_review_flow.py),
and [`_no_key_store`](../../pydexpi_datalog/web/deployment.py)
show the current local path. This is the local rule in [ADR-0014, *BYOK Keys
Live in the Browser, Not on the Server*](../adr/0014-byok-keys-live-in-the-browser.md).

**Observed fact — web hosted profile.** The Next backend fetch helper attaches
a Better Auth JWT only in the hosted profile; FastAPI verifies it and derives
a workspace principal. A hosted `ProviderKeyStore` encrypts credentials per
user/provider and is consulted only when a session credential does not take
precedence. [`backendFetch`](../../frontend/lib/backend-auth.ts),
[`HostedPrincipalResolver`](../../pydexpi_datalog/web/hosted_auth.py),
[`_effective_settings`](../../pydexpi_datalog/web/review_api.py), and
[`ProviderKeyStore`](../../pydexpi_datalog/workflow/provider_keys.py) establish
that authority chain. It implements the hosted split required by
[ADR-0016, *Local and Hosted Deployment Profiles*](../adr/0016-local-and-hosted-deployment-profiles.md).

**Observed fact.** Both profile paths gate a selected provider/model against
the native-tool-capable catalog before configuration or stored-key use.
[`require_native_tool_capable_model`](../../pydexpi_datalog/llm/model_access.py)
and [`configure_provider_settings`](../../pydexpi_datalog/web/chainlit_review_flow.py)
are the validation points; a guest must not widen that catalog or substitute a
different provider authentication policy.

### Event contracts and durable storage

**Observed fact — desktop.** The local contract is the PortLog
`LocalInspectionEvent` union: `turn_started`, text deltas, tool request/result,
and terminal completed/cancelled/failed events. `normalizePiEvent` maps only a
subset of Pi events into that union; the wrapper gives the copied event an
incrementing sequence and timestamp. [`LocalInspectionEvent`,
`runLocalReviewInspection`, and `normalizePiEvent`](../../frontend/desktop/local-review-inspection.ts)
make raw Pi events an input to PortLog normalization, not a PortLog event
contract of their own.

**Observed fact — desktop persistence limitation.** For inspection turns,
the wrapper saves the local record before runtime work and again in `finally`
through `upsertLocalTurn`; `upsertLocalTurn` rewrites the `turns` array in the
local `portlog-project.json` manifest. It does not persist each streamed event
as it arrives. [`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts)
and [`upsertLocalTurn`](../../frontend/desktop/local-project-manifest.cjs)
therefore establish a recoverable local record at current write points, but
not evidence that an interrupted Pi event stream is PortLog's durable audit
record.

**Observed fact — backend.** Backend turn state is durable and replayable:
`TurnLifecycleStore.begin` writes an active turn, `append_progress` writes
redacted/bounded progress, and `_append_result_events` stores the execution
trace projection plus terminal lifecycle events. `render_execution_trace`
persists its bounded detail artifacts independently from any raw model
transcript. [`TurnLifecycleStore`](../../pydexpi_datalog/web/turn_lifecycle.py)
and [`render_execution_trace`](../../pydexpi_datalog/web/execution_trace.py)
are the relevant authority. This matches [ADR-0010, *Use an extensible,
governed execution trace*](../adr/0010-extensible-governed-execution-trace.md):
the user-visible trace is a redacted projection, not chain-of-thought or a
tool dump.

**Observed fact — profile storage.** `ProfileBundle` chooses the local
filesystem `ArtifactStore` plus SQLite catalog or the hosted S3-compatible
store plus libSQL catalog and encrypted key store. The principal's workspace
is part of the storage scope in both profiles. [`ProfileBundle` and
`bundle_for`](../../pydexpi_datalog/web/deployment.py),
[`Principal`](../../pydexpi_datalog/workflow/principal.py), and
[`SessionCatalog`](../../pydexpi_datalog/workflow/session_catalog.py) are the
durable-storage boundary; an agent guest must not create an alternate project,
chat, session, key, or artifact authority.

### Cancellation, recovery, and resume

**Observed fact — desktop.** A renderer abort calls the preload cancellation
IPC. Electron waits until the worker has started then sends it `SIGTERM`; the
worker turns that signal into `AbortController.abort`; the local wrapper calls
the runtime's `abort`, records `turn_cancelled`, and disposes it. The Pi adapter
calls `Agent.abort()` and passes the same signal to its tool callbacks.
[`runDesktopInspection`](../../frontend/components/chat/pid-runtime-provider.tsx),
[`cancelLocalInspection`](../../frontend/desktop/electron-main.cjs),
[`local-inspection-worker`](../../frontend/desktop/local-inspection-worker.ts),
[`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts),
and [`createGovernedPiReviewTurn`](../../frontend/desktop/pi-turn-adapter.ts)
show a cooperative desktop cancellation chain.

**Observed fact — backend.** Cancelling a backend turn persists a `canceled`
status and `cancellation` event. The run's steering callback rereads that
stored turn and returns `stop`; the grounded harness polls steering between
rounds. If a cancellation wins while work is returning, `TurnLifecycleStore`
does not append the result over the canceled state. [`TurnLifecycleStore.cancel`,
`steering_directive`, and `start`](../../pydexpi_datalog/web/turn_lifecycle.py),
[`start_turn`](../../pydexpi_datalog/web/review_api.py), and
[`run_grounded_qa_turn`](../../pydexpi_datalog/qa/grounded_qa_harness.py)
show that backend cancellation is durable and cooperative; current code does
not expose an `AbortSignal` from this path to an in-flight provider HTTP call
or Soufflé invocation.

**Observed fact — resume.** Only a paused backend turn is resumable: the
lifecycle store appends `tool-progress: resumed`, re-runs the relevant
direction-review or Datalog-review callback, then appends the final result
events. The FastAPI turn-scoped `direction-review` and `datalog-review` routes
use that operation. [`TurnLifecycleStore.resume`](../../pydexpi_datalog/web/turn_lifecycle.py)
and [`resume_direction_review` / `resume_datalog_review`](../../pydexpi_datalog/web/review_api.py)
are the source. The current local desktop inspection record has terminal
cancel/fail/complete states but no corresponding persisted pause/resume API.
[`LocalInspectionRecord`](../../frontend/desktop/local-review-inspection.ts)

## Candidate seam comparison

| Candidate | What current source actually separates | Why it is or is not the narrowest viable isolated-agent seam |
| --- | --- | --- |
| `RunLocalReviewInspectionOptions.createTurn` in `local-review-inspection.ts` | Runtime construction is separated from PortLog event recording, posture enforcement, local record persistence, and cancellation handling. The injected factory sees PortLog `emit`, evidence, and rule-check callbacks and returns `prompt`/`abort`/`dispose`. [`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts) | **Selected.** It is the smallest existing seam that replaces the whole turn loop while keeping PortLog's surrounding behavior intact. |
| `createGovernedPiReviewTurn` in `pi-turn-adapter.ts` | It separates Pi's direct `Agent` construction, stream-function selection, API-key injection, and two tools. However its caller subscribes to Pi-shaped events and normalizes them. [`createGovernedPiReviewTurn`](../../frontend/desktop/pi-turn-adapter.ts) and [`createPiRuntime`](../../frontend/desktop/local-review-inspection.ts) | Smaller in source lines but worse as an isolation contract: a non-Pi guest would have to emulate Pi event semantics or force the host to know guest events. Keep it as the current default implementation beneath `createTurn`, not the preferred replacement boundary. |
| Electron desktop chat-provider selection | It persists only `anthropic`/`openai-codex` selection and Electron maps the selected provider to OAuth or OpenRouter credentials. [`createDesktopChatProviderStore`](../../frontend/desktop/desktop-chat-provider.cjs) and [`resolveLocalRuntime`](../../frontend/desktop/electron-main.cjs) | Not a loop seam. Replacing here changes provider/auth routing while the exact same worker and Pi loop still run. |
| Worker-process/stdio bridge | Electron already isolates each desktop turn in `local-inspection-worker.ts` and relays JSON event/result frames. [`runLocalTurn`](../../frontend/desktop/electron-main.cjs) and [`local-inspection-worker`](../../frontend/desktop/local-inspection-worker.ts) | Useful transport evidence for a guest prototype, but not selected as the seam: it currently passes a resolved API key via worker environment and gives the worker direct loopback sidecar access. Substituting the entire worker would widen credential and capability-boundary decisions before they are tested. |
| FastAPI `POST /api/review/sessions/{session_id}/turns` | It couples HTTP request validation, deterministic IDs, provider resolution, progress, cancellation steering, durable lifecycle, and flow execution. [`start_turn`](../../pydexpi_datalog/web/review_api.py) | Too broad. Replacing it would reimplement PortLog lifecycle/persistence and risk changing the API contract merely to compare agent topologies. |
| `QATurnProvider` in the grounded harness | It adapts one model completion request to a `ToolCall` or `FinalAnswer`; `run_grounded_qa_turn` still owns the model/tool continuation loop and `TopologyTools` governance. [`QATurnProvider` / `run_grounded_qa_turn`](../../pydexpi_datalog/qa/grounded_qa_harness.py) and [`OpenAICompatibleQATurnProvider`](../../pydexpi_datalog/qa/openai_compatible_qa_provider.py) | Too small. It can compare provider wire protocols, not host-agent versus guest-agent runtime topologies. |

## Selected seam: placement and rationale

### Recommendation

Place a thin `GuestTurnRuntime` adapter at the existing `createTurn` factory
input. It should implement the current internal structural contract:

```text
PortLog host                    isolated runtime adapter / guest
-------------                   --------------------------------
emit(LocalInspectionEvent)  <-  normalized text/tool events
getEvidence(request)        <-  explicit PortLog capability request
getRuleCheck(request)       <-  explicit PortLog capability request
prompt(text)                ->  start/continue one guest turn
abort()                     ->  stop one guest turn
dispose()                   ->  release transient guest resources
```

This preserves the existing vertical slice: the UI/Electron worker still owns
the user turn; PortLog still issues domain capabilities; the wrapper still
enforces posture and records the result. The guest becomes an implementation
of turn mechanics only. The source support is the current separation between
`runLocalReviewInspection` and its default `createPiRuntime` factory.
[`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts)

### Material judgment calls

1. **Select the semantically narrow interface, not the shortest function.**
   `createGovernedPiReviewTurn` is physically smaller but leaks Pi lifecycle
   event shapes into its caller. `createTurn` is a few methods wider but is
   already expressed in PortLog's own event and tool vocabulary. This is the
   lowest-blast-radius place to compare a non-Pi runtime without teaching the
   wrapper about an upstream protocol.

2. **Keep the FastAPI turn-start boundary out of the first topology
   comparison.** It is the backend's durable lifecycle authority. A guest can
   later be considered for backend use, but only after it can produce the same
   PortLog turn and trace contracts; that is a new deliberate port, not an
   unnoticed substitute at the HTTP route.

3. **Treat the desktop worker as transport, not credential authority.** The
   current worker sees a resolved API key and a sidecar endpoint. A guest
   prototype should explicitly test a narrower credential delivery and a
   capability proxy rather than normalize the current environment-variable
   handoff into a durable guest convention.

4. **Do not equate copied Pi events with durable audit.** The prototype needs
   PortLog-normalized events and PortLog persistence. If it later reaches the
   web lifecycle, `TurnLifecycleStore` plus `render_execution_trace` remain
   the durable/replayable record; a Pi or guest transcript can be optional
   diagnostic material only.

## Retain / replace map for later prototypes

| Area | Retain as PortLog authority | What an isolated runtime may replace or provide | Why |
| --- | --- | --- | --- |
| Prepared-review domain | `ReviewSessionService` artifacts; `ChainlitReviewFlow` session loading; `TopologyTools`; rule packs; `run_governed_check`. [`ReviewSessionService`](../../pydexpi_datalog/workflow/review_session.py), [`TopologyTools`](../../pydexpi_datalog/qa/topology_tools.py), and [`run_governed_check`](../../pydexpi_datalog/verification/governed_check.py) | The guest may request a bounded evidence or check operation and consume its result. | These modules own source-derived facts, validation, rules, evidence, and deterministic outcomes. |
| Desktop posture and presentation | Prompt construction, Inspect/Verify/Chat restrictions, result restatement, local record assembly, renderer/IPC behavior. [`runLocalReviewInspection`](../../frontend/desktop/local-review-inspection.ts) and [`runDesktopInspection`](../../frontend/components/chat/pid-runtime-provider.tsx) | Only `TurnRuntime.prompt/abort/dispose` and normalized runtime event production. | A loop replacement must not let model prose become a verification outcome or bypass posture rules. |
| Desktop authentication | Provider selection, OAuth refresh/login/logout, macOS Keychain storage, and OpenRouter environment resolution. [`resolveLocalRuntime`](../../frontend/desktop/electron-main.cjs), [`createProviderAuthController`](../../frontend/desktop/provider-auth-controller.cjs), and [`resolveOpenRouterEnv`](../../frontend/desktop/electron-openrouter-config.cjs) | At most a scoped, transient credential use authorized by the host. | Provider identity and secret persistence are not generic agent responsibilities. |
| Web authentication | Browser BYOK flow in local profile; Better Auth JWT attachment; hosted JWT-to-Principal verification; encrypted hosted provider-key store. [`byok-keys`](../../frontend/lib/byok-keys.ts), [`backendFetch`](../../frontend/lib/backend-auth.ts), [`HostedPrincipalResolver`](../../pydexpi_datalog/web/hosted_auth.py), and [`ProviderKeyStore`](../../pydexpi_datalog/workflow/provider_keys.py) | Nothing in the first desktop prototype. A later backend adapter may receive an opaque per-turn provider client/lease, never a new account/key store. | ADR-0014 and ADR-0016 require profile-specific credential ownership and workspace isolation. |
| Event contracts | `LocalInspectionEvent` + IPC frame protocol for desktop; backend turn events, extensible trace envelopes, redaction, and trace-detail artifacts for web. [`normalizePiEvent`](../../frontend/desktop/local-review-inspection.ts), [`TurnLifecycleStore`](../../pydexpi_datalog/web/turn_lifecycle.py), and [`render_execution_trace`](../../pydexpi_datalog/web/execution_trace.py) | A guest can emit data that the host maps into those contracts. | Existing clients already interpret these events and terminal statuses. |
| Persistence | `ArtifactStore`, `SessionCatalog`, principal workspace scoping, `TurnLifecycleStore`, prepared artifacts, and the desktop local project manifest. [`ProfileBundle`](../../pydexpi_datalog/web/deployment.py), [`SessionCatalog`](../../pydexpi_datalog/workflow/session_catalog.py), [`TurnLifecycleStore`](../../pydexpi_datalog/web/turn_lifecycle.py), and [`upsertLocalTurn`](../../frontend/desktop/local-project-manifest.cjs) | Ephemeral guest scratch space only, with an explicit discard/retention policy to be decided downstream. | The agent must not become a competing source of projects, sessions, evidence, or audit artifacts. |
| Cancellation and recovery | Desktop abort-to-`SIGTERM` chain; backend durable cancellation, Answer Now steering, paused-review resume, and result suppression after cancel. [`cancelLocalInspection`](../../frontend/desktop/electron-main.cjs), [`TurnLifecycleStore`](../../pydexpi_datalog/web/turn_lifecycle.py), and [`start_turn`](../../pydexpi_datalog/web/review_api.py) | Guest abort/terminate mechanics, provided they settle into the current terminal semantics. | A faster stop mechanism is acceptable; changing `canceled`/paused/replay behavior is not. |

## Compatibility invariants for isolated-runtime prototypes

The following are recommendations inferred from the observed contracts above;
they are compatibility requirements for later `23bh` prototypes, not changes
made by this research ticket.

1. Preserve the existing Electron IPC, frontend HTTP, `LocalInspectionRecord`,
   backend `TurnLifecycleStore`, and provider/model selection interfaces.

2. Keep PortLog-facing domain tools host-authorized and explicitly named. The
   PortLog-facing capability surface remains no broader than the current
   evidence and governed-check callbacks.

   The guest has no ambient access to host/project files, PortLog domain state,
   host credentials, guest-owned PortLog rule execution, or uncontrolled host
   networking.

   Whether an isolated guest may use internal shell, filesystem, or network
   utilities, or non-authoritative reusable Pi/session behavior, remains an
   empirical question for `23bh.2`, `23bh.5`, and `23bh.6`.

   That evaluation remains subject to the existing scratch-state
   retention/discard policy and no competing PortLog authority.

3. Keep prepared source facts, graph semantics, deterministic result artifacts,
   route receipts, and evidence identities on the PortLog side. A guest may be
   given an intentionally bounded view or tool result, never implicit project
   filesystem authority.

4. Keep credentials in their current owner: Electron/main-process plus
   Keychain or configuration for desktop; browser/hosted key-store paths for
   web. Do not use Pi, VMPI, or a guest session directory as a credential store.

5. Normalize guest lifecycle output before it crosses the current boundaries.
   Desktop output must become `LocalInspectionEvent`; backend output must become
   the current bounded execution-trace/lifecycle projection. Neither raw guest
   events nor a guest transcript is PortLog's durable audit record.

6. Preserve cancellation precedence: once PortLog records `canceled`, a late
   guest result must not overwrite it. A backend follow-on must also preserve
   pause/resume for human reviews and Answer Now behavior.

7. Preserve profile scoping. All durable PortLog artifacts remain under the
   current local workspace or hosted principal workspace; no guest-created
   session index, persistent transcript, provider-key table, or cross-workspace
   cache may become authoritative.

8. Preserve model eligibility and protocol checks. A guest can change how a
   model/tool turn is orchestrated, but it must not make a non-tool-capable
   provider/model eligible or accept pseudo-tool-call text as executable.

## Open questions routed to downstream `23bh` tickets

These are open questions, not unverified claims about current code.

| Downstream ticket | Question it should answer using the seam above |
| --- | --- |
| `pydexpi-datalog-1-23bh.2` — *Inventory reusable Pi, OMP, VMPI, and Gondolin capabilities* | Which guest lifecycle events, tool-result formats, and abort primitives map losslessly into `createTurn`, and can reused coding-agent/session state remain non-authoritative without becoming a competing PortLog authority for credentials, persistence, tools, or projects? |
| `pydexpi-datalog-1-23bh.3` — *Qualify packaged macOS virtualization constraints* | Can a packaged Apple Silicon guest be created, stopped, and discarded within the desktop cancellation budget, and what host-only mounts/network routes are technically enforceable? |
| `pydexpi-datalog-1-23bh.4` — *Define the representative end-to-end review scenario* | Which prepared topology/evidence lookup and governed check demonstrate the full PortLog-owned capability boundary, event normalization, cancellation, and result-artifact behavior? |
| `pydexpi-datalog-1-23bh.5` — *Run the unmodified VMPI Apple Silicon review prototype* | Does an unmodified guest leave no implicit session/auth/config persistence, and can it receive only the intended per-turn capability and credential transport? |
| `pydexpi-datalog-1-23bh.6` — *Compare host-agent and guest-agent integration paths* | Compare host-held versus guest-scoped credentials, guest-to-host tool RPC, event mapping, mount/network scope, cancellation propagation, and artifact retention against the invariants above. |
| `pydexpi-datalog-1-23bh.7` — *Decide the PortLog runtime architecture and reuse level* | Decide whether later backend use warrants a deliberately introduced `AgentRuntime` port, rather than repurposing the HTTP turn-start route; select the smallest upstream reuse level that preserves PortLog authority. |
| `pydexpi-datalog-1-23bh.8` — *Outline adoption behind the existing agent seam* | Stage a desktop prototype behind `createTurn`, prove compatibility with the local record/event contract, then specify any separately approved backend work needed for durable lifecycle parity. |

## Primary sources

All sources below are first-party repository code or repository ADRs inspected
for this report.

| Source | Role in this map |
| --- | --- |
| [ADR-0003](../adr/0003-web-native-grounded-agent-harness.md), [ADR-0012](../adr/0012-model-driven-agent-runs.md), [ADR-0014](../adr/0014-byok-keys-live-in-the-browser.md), [ADR-0016](../adr/0016-local-and-hosted-deployment-profiles.md), and [ADR-0010](../adr/0010-extensible-governed-execution-trace.md) | Product authority, model-driven run, credential, deployment-profile, and governed-trace decisions. |
| [`frontend/desktop/local-review-inspection.ts`](../../frontend/desktop/local-review-inspection.ts) and [`frontend/desktop/pi-turn-adapter.ts`](../../frontend/desktop/pi-turn-adapter.ts) | Selected runtime factory, PortLog event normalizer, default Pi adapter, tool allowlist, and abort path. |
| [`frontend/desktop/local-inspection-worker.ts`](../../frontend/desktop/local-inspection-worker.ts), [`electron-main.cjs`](../../frontend/desktop/electron-main.cjs), and [`preload.cjs`](../../frontend/desktop/preload.cjs) | Desktop composition root, per-turn process, loopback capability calls, IPC transport, credentials, and cancellation signal. |
| [`frontend/components/chat/pid-runtime-provider.tsx`](../../frontend/components/chat/pid-runtime-provider.tsx) and [`frontend/lib/turn-client.ts`](../../frontend/lib/turn-client.ts) | Renderer selection between desktop and web paths, UI cancellation, polling, turn ID, and client event reduction. |
| [`pydexpi_datalog/web/asgi.py`](../../pydexpi_datalog/web/asgi.py), [`review_api.py`](../../pydexpi_datalog/web/review_api.py), [`turn_lifecycle.py`](../../pydexpi_datalog/web/turn_lifecycle.py), and [`execution_trace.py`](../../pydexpi_datalog/web/execution_trace.py) | Backend composition, identity/workspace routing, turn lifecycle, cancellation/resume, and durable trace projection. |
| [`pydexpi_datalog/web/chainlit_review_flow.py`](../../pydexpi_datalog/web/chainlit_review_flow.py), [`qa/grounded_qa_harness.py`](../../pydexpi_datalog/qa/grounded_qa_harness.py), [`qa/topology_tools.py`](../../pydexpi_datalog/qa/topology_tools.py), and [`verification/governed_check.py`](../../pydexpi_datalog/verification/governed_check.py) | Current agent-loop adapter, tool governance, prepared-domain use, and deterministic-check authority. |
| [`workflow/review_session.py`](../../pydexpi_datalog/workflow/review_session.py), [`workflow/artifact_store.py`](../../pydexpi_datalog/workflow/artifact_store.py), [`workflow/session_catalog.py`](../../pydexpi_datalog/workflow/session_catalog.py), [`workflow/principal.py`](../../pydexpi_datalog/workflow/principal.py), [`workflow/provider_keys.py`](../../pydexpi_datalog/workflow/provider_keys.py), and [`web/deployment.py`](../../pydexpi_datalog/web/deployment.py) | Prepared artifacts, profile-specific durable storage, catalog, workspace isolation, and encrypted hosted credentials. |
