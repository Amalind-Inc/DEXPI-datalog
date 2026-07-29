# Pi Agent Loop Fit Assessment

**Date:** 2026-07-28  
**Question:** Should PortLog use Pi's agent loop for a local, OSS/BYOK, PortLog-authoritative process-review harness?

## Bottom line

**Recommendation: adopt the small `pi-agent-core` loop behind a narrow PortLog adapter; do not adopt `pi-coding-agent` / `AgentSession` as the runtime shell.**

Pi's core loop is materially useful: it solves streamed model turns, validated tool dispatch, tool-result continuation, explicit lifecycle events, queues, and cancellation propagation. Rebuilding that loop first would be needless risk.

But `pi-coding-agent` adds coding-agent concerns that are wrong for PortLog: JSONL session ownership, filesystem/resource discovery, built-in coding tools, compaction and branch/session behavior, and provider/auth machinery. PortLog must retain project/review/artifact/evidence authority.

This is not a claim that Pi is drop-in. The first technical proof must show that `pi-agent-core` can run with a PortLog-provided `Model`, `streamFn`, `getApiKey`, and strictly PortLog-defined tools **without** constructing Pi's `AgentSession` or activating its session/auth/resource conventions.

## What the actual core loop is

The core package is `@earendil-works/pi-agent-core`, implemented in `packages/agent`. Its public `Agent` is a stateful wrapper over `runAgentLoop` / `runAgentLoopContinue`.

Its state is an in-memory system prompt, model, thinking level, tool list, message transcript, streaming state, pending tool calls, and errors. The constructor accepts all of the seams PortLog needs: initial state, `streamFn`, `getApiKey`, `beforeToolCall`, `afterToolCall`, `prepareNextTurn`, `sessionId`, and tool execution mode. It does **not** require session files or an auth store.

A normal turn does this:

1. Append the user prompt and emit `agent_start`, `turn_start`, `message_start`, and `message_end`.
2. Transform PortLog/agent messages into provider messages at the LLM boundary.
3. Resolve a key by calling `getApiKey(provider)` first, falling back to `config.apiKey`.
4. Stream the assistant response, emitting incremental message updates including text, thinking, and tool-call events.
5. Validate and execute declared tool calls; append tool-result messages to the context.
6. Continue the inner loop until no tool calls remain, or terminate after an explicit stop condition.
7. Emit `turn_end` and finally `agent_end`.

This is the loop PortLog should reuse—not Pi's UI, coding tools, or persistence conventions.

## Fit against PortLog requirements

| PortLog requirement | Pi core evidence | Assessment |
|---|---|---|
| Strict PortLog tool whitelist | The `Agent` accepts initial `state.tools`; an unknown model-requested tool becomes an error. `pi-coding-agent` additionally supports `baseToolsOverride`, allowlist, denylist, and custom tools, but PortLog should avoid that wrapper initially. | **Good, with discipline.** Construct the core agent with only PortLog tools. Never register built-in read/bash/edit/write tools. |
| Tool-call validation and governance | Core validates tool arguments before execution; `beforeToolCall` can block a call with a reason; `afterToolCall` can observe/alter result flow. | **Good seam.** PortLog should authorize, execute, trace, and return its own tool results through those hooks/tool functions. |
| Event fidelity / visible execution | Core emits start/update/end events for messages, tool execution start/end, tool-result messages, turns, and agent settlement. | **Good transport primitive.** PortLog must persist its own normalized trace; do not call ephemeral Pi events the audit record. |
| Cancellation during model/tool work | The active run owns an `AbortController`; the signal reaches streaming and tool hooks. Core checks `signal.aborted` between sequential operations. | **Useful, not enough by itself.** PortLog tools and the Python/Soufflé subprocess must actively honor the signal and terminate their own work. |
| Deterministic replay/audit | Core transcript is mutable in memory; message conversion/context transforms may be custom; parallel tools run concurrently. | **Insufficient alone.** PortLog must write immutable turn request, tool invocation, tool result, evidence refs, deterministic trace IDs, model metadata, and outcome records. Prefer sequential execution for governed dependent tools. |
| Persistence ownership | Core `Agent` only owns in-memory state. In contrast, `pi-coding-agent`'s `AgentSession` explicitly owns session management and automatic session persistence. | **Core: good. `AgentSession`: reject.** PortLog owns durable review/session artifacts. Pi transcript persistence may be optional debugging output only. |
| Provider injection / PortLog OAuth | The core resolves credentials through an injected `getApiKey(provider)` before falling back to `apiKey`; a custom `streamFn` is injectable. | **Promising but unproven.** A spike must prove externally supplied credentials/model configuration work without Pi's auth runtime. OAuth itself stays PortLog-owned. |
| Error and retry behavior | Core reports provider error/aborted terminal messages and executes tool calls in sequential or parallel mode. The `pi-coding-agent` wrapper adds retries, compaction, model switching, and richer session behavior. | **Core is appropriate.** PortLog should own policy: retry limits, model fallback, timeout, and whether a failed check becomes `indeterminate`. |

## How Pi helps

1. **It eliminates the most failure-prone generic-agent plumbing.** Streaming assistant output, tool-call assembly, tool-result continuation, pending prompts, and cancellation are a nontrivial state machine.
2. **Its tool cycle matches the harness interaction.** A review model asks PortLog for evidence/checks, receives structured results, and continues its answer.
3. **It has meaningful interception points.** `beforeToolCall`, `afterToolCall`, custom stream function, API-key resolution, context transform, and event subscription can all be adapted without forking the loop.
4. **It separates the loop from the coding shell at package level.** `pi-agent-core` is the candidate; `pi-coding-agent` is a different layer.

## How Pi can hurt us

1. **Wrong abstraction if we import the full coding-agent shell.** `AgentSession` couples the loop to session manager, settings manager, resource loader, working directory, built-in tool policy, compaction, and automatic persistence. Those are coding-agent requirements, not process-review requirements.
2. **Transcript confusion.** Pi messages describe what the model saw and did; PortLog review truth must include source-derived facts, deterministic traces, evidence references, and user-confirmed scope. A Pi transcript cannot reconstruct that safely.
3. **Tool concurrency can violate review semantics.** Core defaults to parallel tool execution. For related checks/evidence selection, PortLog should start with `toolExecution: "sequential"` or declare explicit safe parallel classes.
4. **Cancellation is cooperative.** Passing an abort signal is not the same as killing a long-running Soufflé/Python subprocess. PortLog needs sidecar-level cancellation and a durable cancelled outcome.
5. **Provider/auth separability is a hypothesis.** The injected core interfaces look suitable, but a version-pinned local spike must prove that they work with PortLog-supplied provider credentials and model definitions without constructing `AgentSession`.

## Required PortLog-owned code even if we adopt the core loop

- desktop launch/supervision and local runtime lifecycle;
- local project/document/artifact catalog;
- DEXPI ingestion, graph facts, drawing artifacts, Soufflé execution;
- governed tool definitions and JSON schemas;
- authorization gate: tool policy, scope, confirmation, rate/size/resource limits;
- abort propagation into Python and Soufflé processes;
- immutable review trace: tool arguments/results, evidence IDs, model/provider metadata, deterministic trace IDs, outcome class;
- answer-posture enforcement (`Inspect`, `Verify`, `Propose`, `Redirect`);
- PortLog-owned credential/OAuth storage and provider selection;
- renderer/UI and evidence-on-drawing behavior.

## The first proof, before product adoption

Build a narrow, disposable integration spike—not the desktop app:

```text
PortLog-supplied Model + streamFn + getApiKey
  → pi-agent-core Agent
  → only one PortLog tool: inspect_prepared_document
  → PortLog records request/tool/result/evidence trace
  → cancellation aborts the model and tool invocation
  → no Pi session file and no Pi auth file is created or read
```

Pass criteria:

1. Pi emits a complete event sequence that PortLog can map to its trace.
2. The model can invoke only the declared PortLog tool.
3. Tool invocation is rejected by PortLog policy before execution when out of scope.
4. PortLog controls credentials; no Pi auth/session persistence is touched.
5. A cancellation produces explicit PortLog cancellation records and stops the active tool/model work.
6. The same captured PortLog review trace explains the result without needing Pi JSONL.

If this passes, use `pi-agent-core` as an internal loop dependency behind a PortLog adapter. If it fails because core cannot operate cleanly without Pi-owned credential/session infrastructure, reject Pi for the core runtime rather than bending PortLog ownership around it.

## Primary sources

- Pi core `Agent`, options, state, event subscription, active run and injected seams: <https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/agent/src/agent.ts>
- Pi core loop: prompt/stream/tool/result continuation and lifecycle events: <https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/agent/src/agent-loop.ts>
- Pi coding-agent `AgentSession` wrapper and its stated responsibilities (state, event subscription with automatic session persistence, model management, compaction, bash execution, session switching): <https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/coding-agent/src/core/agent-session.ts>
- Pi monorepo package layout for agent core: <https://github.com/badlogic/pi-mono/tree/main/packages/agent>


## Exact-version verification addendum — `@earendil-works/pi-agent-core@0.80.6`

This addendum supersedes any version-general claim above. The desktop adapter spike locks `@earendil-works/pi-coding-agent@0.80.6`, whose lockfile resolves a nested `@earendil-works/pi-agent-core@0.80.6`. PortLog must add core as a **direct, exact dependency** if it adopts it; a nested transitive import is not an integration contract.

| Requirement | Exact 0.80.6 evidence | Result |
|---|---|---|
| 1. Direct core import | Package exports its root `.` as `dist/index.js` / `dist/index.d.ts`; `Agent` is exported from `agent.js`. | **Pass, with dependency rule.** Add direct `@earendil-works/pi-agent-core@0.80.6`; import `Agent` from the public root export. |
| 2. PortLog credential/model injection | `AgentOptions` has injectable `streamFn` and `getApiKey(provider)`. The 0.80.6 loop resolves `getApiKey(model.provider)` first, then `config.apiKey`, and passes that plus the abort signal to `streamFn`. | **Pass at API level.** OAuth/secret storage can be PortLog-owned. The executable spike must confirm no provider-specific hidden lookup occurs in the chosen `streamFn`. |
| 3. PortLog-only tools | Initial state supplies `tools`; dispatch searches only `currentContext.tools`; unknown tool names yield a tool error. The core constructor itself creates no builtin filesystem/shell tools. | **Pass.** PortLog must construct the list rather than inherit a coding-agent tool registry. |
| 4. Sequential execution + complete events | 0.80.6 constructor defaults `toolExecution` to `parallel`, but accepts `toolExecution: "sequential"`; tool-level sequential mode also forces it. It emits agent/turn/message and tool-execution start/end plus tool-result events. | **Pass with mandatory configuration.** PortLog sets sequential by default and persists normalized events itself. |
| 5. Abort and no forced persistence | `Agent.abort()` aborts an active `AbortController`; the signal is forwarded to `streamFn`, before/after hooks, and execution, with sequential loop checks between calls. `Agent` state is in memory. However root `index.js` re-exports optional JSONL/session/harness modules, so importing the root evaluates those modules even though it does not itself instantiate storage. | **Conditional pass.** Static artifact shows no root-level creation call; executable proof must run in an empty temporary home/cwd and assert no Pi/JSONL files are read or written. PortLog subprocess cancellation remains its own responsibility. |

### Updated decision

**Proceed to a disposable executable isolation spike, not product adoption yet.** The exact 0.80.6 public API has all five required seams. The remaining uncertainty is behavioral: whether a real controlled turn with a PortLog `streamFn` and tool list creates any filesystem/session/auth side effects.

### Immutable exact sources

- Published `0.80.6` package metadata and export map: <https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/package.json>
- Published `0.80.6` public declarations: <https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent.d.ts>
- Published `0.80.6` `Agent` implementation (constructor defaults, event/abort state): <https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent.js>
- Published `0.80.6` loop implementation (credential injection, stream abort signal, dispatch and ordering): <https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/agent-loop.js>
- Published `0.80.6` root exports (including optional JSONL/session modules): <https://unpkg.com/@earendil-works/pi-agent-core@0.80.6/dist/index.js>
- PortLog spike lockfile proving the currently evaluated dependency resolution: `spikes/electron-pi-adapter/package-lock.json` lines 19–29 and 518–532.


## Executable isolation spike — 2026-07-29

**Verdict: adopt the exact low-level pair behind a narrow PortLog adapter.** The disposable spike passed its executable proof against direct, exact `@earendil-works/pi-agent-core@0.80.6` and `@earendil-works/pi-ai@0.80.6` dependencies. This is an adoption decision for Pi's in-memory mechanics only; it is not adoption of `pi-coding-agent`, `AgentSession`, Pi credential storage, or Pi persistence.

### Observed evidence

- The lockfile installs direct public-root dependencies for core and AI, each at `0.80.6`; the test imports `Agent` from the core root and `Model` from the Pi AI root.
- The controlled turn made two model requests through a PortLog-provided `streamFn`; credential resolution ran twice through PortLog's `getApiKey`; the sole declared `inspect_prepared_document` tool ran sequentially and returned evidence `evidence-1`; the second response cited that evidence.
- PortLog captured the complete Pi lifecycle sequence plus its own structured tool-result trace, so the turn can be reconstructed without Pi JSONL.
- A requested `bash` tool was rejected as undeclared and never executed.
- An isolated child process imported the core package root and constructed `Agent` with empty HOME, XDG config, PI home, and cwd; its directory tree was unchanged. The controlled-turn isolation run also left its redirected state directory empty.
- Abort reached both the active injected model stream and active sequential tool and each settled within one second. Tool cancellation is cooperative: the PortLog tool returns `terminate: true` after observing abort so core does not initiate another model request. PortLog must retain that convention and separately terminate Python/Souffle subprocesses.
- The spike checks the developer Node runtime and Electron's embedded Node runtime against Pi's `>=22.19.0` requirement. The validated test environment used Node `24.3.0`; Electron is checked dynamically in its Node mode.
- `npm test` (14 tests) and `npm run typecheck` both pass.

### Reuse and exclusions reaffirmed

PortLog may reuse the core `Agent`, injected streaming and credential seams, Pi AI protocol/model types, sequential tool dispatch, lifecycle events, validation, and abort-signal plumbing. PortLog remains responsible for tool authorization, provider policy, durable review/evidence/trace records, credential and OAuth storage, cancellation of sidecars, and all UI. Do not construct `AgentSession`, register coding tools, read or write Pi auth/session/config state, or treat Pi's in-memory transcript as PortLog's audit record.
