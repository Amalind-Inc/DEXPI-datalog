---
status: accepted
---

# Use a persistent full-Pi PortLog agent harness with host-owned policy and provenance

## Problem Statement

PortLog currently runs a narrow, per-turn Pi agent. The current seam creates an in-memory Pi `Agent`, registers only PortLog-specific callbacks, runs tools sequentially, and projects the result into a PortLog-owned `LocalInspectionRecord`. This works for bounded review demonstrations, but it does not provide the normal Pi coding-agent experience.

The current seam does not register familiar filesystem and shell capabilities such as `read`, `write`, `edit`, or `bash`. It also does not provide a persistent Pi session, native Pi JSONL history, native steering and follow-up behavior, durable queued input, child sessions, conversation branches, or a reusable multi-client coordinator. The result is a product-specific interaction loop that reimplements responsibilities already solved by mature agent harnesses.

PortLog also has requirements that a generic coding-agent harness cannot satisfy by itself:

- the DEXPI 1.3 source file and the persisted canonical base fact layer must retain source and revision provenance;
- only validated PortLog evidence and deterministic rule evaluation outcomes may establish PortLog authority;
- ordinary filesystem, shell, web, isolated-guest, and verifier output must remain ordinary context;
- risky native commands must execute only through the fail-closed Hybrid Gondolin boundary;
- credentials, protected paths, network access, workspace identity, approval, and resource ceilings remain host-owned;
- persisted sessions require one canonical writer, crash recovery, cancellation, and explicit authority semantics;
- existing review and domain behavior must be replaced without silently rewriting historical records.

The product therefore needs a durable Pi-native harness without replacing PortLog's process-engineering domain model or weakening its security and authority boundaries.

## Solution

PortLog will use one persistent, host-owned Pi Agent harness as the interaction and session seam. The Electron main/host worker will own the coordinator, native Pi JSONL session, writer lease, PortLog capability registry, policy snapshot, workspace identity, child sessions, approvals, event stream, and authority/provenance records.

The model will receive familiar Pi-compatible tool shapes and result behavior. PortLog will provide thin policy and provenance wrappers around those tools rather than importing an entire coding-agent product or reimplementing shell, session, provider, child-agent, and event-loop mechanics.

The model may choose among registered tools. PortLog will not remove tools based on an intent classifier or let the model choose the trust boundary. Soft tool descriptions, model guidance, interceptor hints, and result feedback may improve tool selection, but hard policy evaluates every call independently.

The first delivery is a human-in-the-loop experience prototype, not a persistence or migration slice. It uses a real Pi `Agent`, normal Pi-compatible `read`, and one real PortLog domain evidence capability in an ephemeral, clearly marked prototype harness. A human must be able to complete a useful task, see the tool calls and results, distinguish ordinary Pi context from PortLog evidence, and observe bounded failure and cancellation behavior through one runnable command or desktop entry point.

The second delivery is a separate Gondolin execution spike. It uses one approved immutable command profile, staged input, deny-all network, no credentials, bounded output, cancellation, visible host/guest routing, and no host fallback. It does not begin with open-ended bash, mutation, PTY, background jobs, or a durable guest workspace.

The first production slice follows the prototypes: a persistent coordinator with native Pi JSONL, workspace and policy identity, single-writer fencing, cancellation, reopen, event streaming, normal Pi `read`, and PortLog evidence. Later tools and replacement domain adapters attach only after this human-tested seam is accepted.

The old per-turn interaction and domain-facing adapter path will be removed after an opt-in migration period and hard cutover gates. Validated pure domain engines and storage primitives may be reused. All production authority-producing operations must enter through the new capability registry and host authority seam before the old adapters are deleted.

## User Stories

1. As a PortLog reviewer, I want a normal Pi agent conversation, so that I can ask follow-up questions without being constrained by a one-turn review wrapper.
2. As a PortLog reviewer, I want the agent to use familiar `read`, `write`, `edit`, and `bash` capabilities, so that ordinary workspace work feels like a capable Pi coding session.
3. As a PortLog reviewer, I want PortLog-specific evidence and rule tools available beside normal Pi tools, so that I can move naturally between exploration and grounded review.
4. As a PortLog reviewer, I want the model to choose tools from descriptions and results, so that the system does not need a brittle intent classifier.
5. As a PortLog reviewer, I want hard policy to remain independent of model tool choice, so that a persuasive prompt or incorrect tool selection cannot bypass safety.
6. As a PortLog reviewer, I want a conversation to survive application restart, so that I can reopen the same review without losing its canonical history.
7. As a PortLog reviewer, I want the session to remain bound to the same workspace and policy identity, so that old evidence cannot be silently applied to another project.
8. As a PortLog reviewer, I want a moved or copied workspace to require an explicit rebind or new session, so that project identity is never inferred from a convenient current directory.
9. As a PortLog reviewer, I want to see assistant text, tool calls, tool results, cancellations, approvals, and child activity as they occur, so that long reviews are inspectable.
10. As a PortLog reviewer, I want a slow renderer or terminal not to stall the agent, so that runtime progress does not depend on client event consumption.
11. As a PortLog reviewer, I want a disconnected client to resynchronize from canonical session history, so that missed events do not create a misleading UI.
12. As a PortLog reviewer, I want to cancel an active turn, so that long model or tool work stops without closing the entire session.
13. As a PortLog reviewer, I want cancellation to distinguish cancelled work from an uncertain side effect, so that I do not mistake an interrupted command for a successful result.
14. As a PortLog reviewer, I want prompts submitted while a turn is active to remain in a durable coordinator queue, so that they are not executed out of order or duplicated.
15. As a PortLog reviewer, I want a queued prompt to become a Pi user message only after explicit coordinator admission, so that waiting input is not mistaken for conversation history.
16. As a PortLog reviewer, I want one client to own session writes while other clients observe, so that renderer and terminal attachments cannot create competing transcripts.
17. As an authorized attached client, I want to answer a specific approval request when the original client is disconnected, so that a safe operation is not blocked by client availability.
18. As a PortLog reviewer, I want every approval to bind to one exact normalized action, target, workspace, policy revision, and expiry state, so that an approval cannot be replayed for changed arguments.
19. As a PortLog reviewer, I want normal read-only calls to run concurrently when they share a stable snapshot, so that exploration remains responsive.
20. As a PortLog reviewer, I want writes, edits, shell mutations, Datalog execution, isolated commands, and conflicting operations serialized, so that concurrent effects cannot corrupt state or provenance.
21. As a PortLog reviewer, I want ordinary file reads and shell output to be clearly distinguished from PortLog evidence, so that useful context is not mistaken for a verified engineering claim.
22. As a PortLog reviewer, I want topology and evidence results to carry stable references, so that I can inspect exactly which source revision supports a grounded claim.
23. As a PortLog reviewer, I want deterministic rule results to identify the rule, scope, source revision, evaluation coverage, and limitations, so that a satisfied, violated, or indeterminate outcome is inspectable.
24. As a PortLog reviewer, I want a rule with incomplete coverage to report indeterminate rather than pass or fail by assumption, so that claim-aware truncation remains visible.
25. As a PortLog reviewer, I want source and rule revisions to remain immutable in historical answers, so that a later upload or rule-pack change cannot rewrite what an earlier answer meant.
26. As a PortLog reviewer, I want short evidence labels such as `[E1]` or `[D2]` to expand in the UI, so that answers remain readable while exact provenance remains available.
27. As a PortLog reviewer, I want an uncited claim to remain unbound rather than be fuzzy-matched to a file or URL, so that the system never silently attaches authority to the wrong source.
28. As a PortLog reviewer, I want unsupported and conflicting claims to be visible without an automatic semantic retry loop, so that the system does not hide uncertainty or create surprise model turns.
29. As a PortLog reviewer, I want `bash` to retain familiar request fields, so that existing Pi-compatible model behavior remains useful.
30. As a PortLog reviewer, I want a simple read-only command to use a narrow host-safe route, so that ordinary inspection does not require a guest for every operation.
31. As a PortLog reviewer, I want compound or risky shell text to run atomically in a disposable Gondolin guest, so that no part of a sandbox-required command can fall back to the host.
32. As a PortLog reviewer, I want shell environment values to be sanitized and host authority variables denied, so that model-provided environment changes cannot alter host execution authority.
33. As a PortLog reviewer, I want a workspace-bound `cwd`, so that shell execution cannot select arbitrary host paths.
34. As a PortLog reviewer, I want unsupported PTY or asynchronous behavior to report `unavailable`, so that the tool never silently changes requested semantics.
35. As a PortLog reviewer, I want command output to stream live but persist as one bounded final result with artifact references, so that the UI is responsive without duplicating unbounded output in the transcript.
36. As a PortLog reviewer, I want web search to provide bounded external context and source URLs, so that I can research general information without treating search results as PortLog evidence.
37. As a PortLog reviewer, I want provider selection and credentials to remain host-controlled, so that the model cannot choose secrets or arbitrary network destinations.
38. As a PortLog reviewer, I want web-search provider failures to return partial results and per-provider statuses, so that one unavailable provider does not hide useful results.
39. As a PortLog reviewer, I want search content marked as untrusted external context, so that prompt injection in a result cannot change system policy or authorize tools.
40. As a PortLog reviewer, I want page retrieval to be a separate future capability, so that search does not silently expand into browser execution or unbounded external content.
41. As a PortLog reviewer, I want to ask a verifier subagent for a bounded assessment, so that independent checking is available without giving the child workspace or authority access.
42. As a PortLog reviewer, I want verifier input to be host-normalized and bounded, so that a child cannot inspect arbitrary paths or receive hidden credentials.
43. As a PortLog reviewer, I want verifier output validated against a strict versioned schema, so that malformed model prose cannot become PortLog authority.
44. As a PortLog reviewer, I want verifier recursion bounded to two descendant levels, so that nested checking cannot become an unbounded agent tree.
45. As a PortLog reviewer, I want verifier children to have cumulative and per-child limits, so that depth limits do not hide unbounded cost or latency.
46. As a PortLog reviewer, I want independent verifier siblings to run in bounded parallel, so that read-only checking is efficient without losing canonical ordering.
47. As a PortLog reviewer, I want async verifier results to append as linked child records without automatically starting another parent turn, so that background completion does not create hidden model activity.
48. As a PortLog reviewer, I want child histories separate from parent history but coordinator-owned, so that recursive work remains inspectable without creating competing canonical writers.
49. As a PortLog reviewer, I want interrupted child and tool work to receive typed outcomes and no automatic retry, so that uncertain operations are never silently repeated.
50. As a PortLog maintainer, I want the harness to reuse mature Pi session, streaming, cancellation, compaction, branching, provider, and task mechanics, so that PortLog-specific code stays focused on process-engineering policy and provenance.
51. As a PortLog maintainer, I want Oh My Pi contracts to guide compatible tool schemas and behavior, so that PortLog does not invent a second coding-agent dialect.
52. As a PortLog maintainer, I want Oh My Pi provider and shell implementations reused or adapted only when their policy boundaries are compatible, so that PortLog does not import an uncontrolled product runtime.
53. As a PortLog maintainer, I want Codex App Server and similar durable-agent systems used as design references rather than dependencies, so that PortLog keeps one trusted local coordinator and no second session authority.
54. As a PortLog maintainer, I want Gondolin reused directly through a thin adapter, so that disposable Linux execution is not reimplemented in PortLog.
55. As a PortLog maintainer, I want validated DEXPI graph export, canonical base facts, rule execution, manifest identity, and storage primitives reused, so that the new harness does not rewrite proven process-engineering logic.
56. As a PortLog maintainer, I want every authoritative operation represented in one capability inventory, so that no old callback or direct engine path bypasses policy and provenance.
57. As a PortLog maintainer, I want the old per-turn API removed after migration, so that future code cannot create a second session or authority path.
58. As a PortLog maintainer, I want old sessions to remain inspectable as read-only legacy data, so that hard cutover does not destroy historical review context.
59. As a PortLog maintainer, I want packaged Electron validation before deletion, so that development-only success cannot hide worker, entitlement, signing, or isolation failures.
60. As a PortLog operator, I want release-level rollback rather than hidden per-request fallback, so that a failed release can be recovered without retaining duplicate runtime authority.

## Implementation Decisions

### One host-owned seam

The highest testable seam is one `PortLogAgentHarness`/session coordinator boundary. It owns session creation and reopen, prompt admission, Pi Agent lifecycle, native JSONL persistence, writer fencing, client attachment, event streaming, cancellation, approvals, child supervision, policy snapshots, and capability invocation. The coordinator is the only production owner that writes canonical parent history.

The capability registry is an internal part of that seam, not a second public runtime. It registers both normal Pi-compatible tools and PortLog domain capabilities. Every capability declares its request/result shape, policy effect, authority class, provenance origin, persistence behavior, cancellation behavior, idempotency, and reconciliation contract.

### Human-in-the-loop delivery sequence

Every delivery must end in a runnable experience that a person can use and evaluate. Infrastructure that cannot support a concrete human task is not considered a completed slice.

The experience prototype answers one question: can a person naturally combine ordinary Pi file reading with PortLog-governed domain evidence in one conversation? It remains ephemeral, does not write `LocalInspectionRecord`, does not invent a durable session schema, and exposes normal `read` separately from an explicitly named PortLog evidence capability. Human acceptance requires a task that genuinely needs both tools, visible source identity for the evidence result, understandable tool/error states, and no false authority when evidence fails.

The Gondolin spike answers a different question: can a person understand and verify that one approved command ran in a disposable guest under fail-closed policy? It must demonstrate immutable input, deny-all network, no credential visibility, bounded sole output, cancellation, and no host fallback. Its mechanics are disposable unless they already satisfy the later production interface.

Only after both questions have human evidence does the work become the persistent production coordinator slice. Human observations are recorded as acceptance evidence alongside deterministic fixtures; they are not informal polish applied after the architecture is complete.

### Pi reuse preference

Use `@earendil-works/pi-agent-core` and `@earendil-works/pi-ai` as the runtime foundation, preserving native `Agent` lifecycle, model streaming, tool-call continuation, abort behavior, steering/follow-up behavior, compaction, branching, child-session concepts, and JSONL session semantics wherever the current versions support them.

PortLog should add a thin host adapter instead of reimplementing the Pi event loop, model provider dispatch, session transcript, or child-session machinery. The current in-memory per-turn construction is a migration source and comparison oracle, not the target seam.

### Oh My Pi reuse preference

Use Oh My Pi documentation and source contracts as behavioral reference for familiar `read`, `write`, `edit`, `bash`, `web_search`, and `task` shapes. Reuse an upstream implementation or extension when its registration and policy boundaries can be proven compatible; otherwise write the smallest PortLog-owned adapter around the same public contract.

Do not import the complete Oh My Pi coding-agent runtime merely to obtain normal tools. Do not treat Oh My Pi interceptors, allow patterns, model prompts, or shell heuristics as PortLog security boundaries. Interceptors may suggest a dedicated tool, but hard PortLog policy independently classifies every request.

For hashline editing, perform the previously agreed compatibility probe against `pi-hashline-edit`. If compatible, use a thin PortLog policy/provenance adapter around its paired hashline `read` and `edit` mechanics. PortLog remains responsible for workspace identity, `.portlogignore`, credential/private-key denial, approval, snapshot identity, and result authority. A fresh read is required after session reopen. The prototype and first production slice remain read-only.

### Codex and other harness preferences

Use Codex App Server and similar mature agent systems as architectural reference for a single durable session owner, client attachment, streamed events, approvals, and resumable coordination. PortLog must not add Codex App Server, OMP, VMPI, or another coding-agent product as a production runtime dependency, and must not create a second canonical transcript.

The desired reuse order is: use an upstream capability unchanged when it fits; contribute a needed general improvement upstream when practical; add a thin PortLog adapter for policy, provenance, and lifecycle; replace or reimplement only when a documented compatibility or security blocker exists.

### Session and client ownership

The trusted Electron main/host worker owns the coordinator and all session files. Renderer and terminal clients use one authenticated request/event protocol. Terminal attachment uses a high-entropy per-session capability token stored outside the workspace, with scoped operations and revocation.

One persistent writer lease and monotonic fencing epoch control canonical writes. Observers receive events and may answer an explicitly authorized approval request, but cannot submit prompts or invoke tools directly while they lack the writer lease. Queued prompts live in a coordinator-owned durable queue and become Pi user messages only after admission.

Native Pi JSONL is the canonical conversation history. PortLog adds versioned custom entries for policy, authority, provenance, queue admission, cancellation, approval, child links, and recovery. A separate database or synchronized duplicate transcript is not introduced.

Session identity includes canonical workspace root, project/manifest identity, source identity, policy and ignore digest, tool-profile version, and provider/model policy identity. Reopen requires compatibility validation. Moved workspaces, incompatible policies, or incompatible profiles require explicit rebind, migration, or a new session. Old sessions are read-only legacy views.

### Normal Pi tool surface

The base registry exposes familiar `read`, `write`, `edit`, `bash`, `web_search`, and `task` names where the corresponding PortLog capability is available. Tool availability is stable; missing context or disabled capability returns a structured result such as `unavailable` rather than silently changing the registry or creating a second tool profile.

Normal filesystem tools are workspace-bound and PortLog-policy-enforced. Durable mutations create a new source/workspace revision and preserve old evidence as immutable historical data. Mutation does not silently rebind prior claims.

### Bash and Gondolin

The model-facing `bash` request accepts the full compatible Oh My Pi shape, including command, workspace-bound working directory, bounded environment, timeout, PTY, and asynchronous/background fields. Host ceilings always apply; `timeout: 0` never creates an unbounded process.

PortLog validates and classifies the entire request before execution. A narrow parsed direct-execution allowlist may run approved non-mutating operations on the host with a minimal host-owned environment. Compound, shell-composing, risky, or ambiguous commands are routed atomically to a separate bounded Gondolin script capability. They receive a disposable guest, deny-all network, sanitized environment, bounded resources, ephemeral scratch, and no durable host mutation. Guest changes return as non-authoritative bounded diff artifacts and require a separate explicit apply capability.

No request may partially execute on the host and partially in Gondolin. Isolation initialization, classification, policy, cancellation, cleanup, or backend failure returns unavailable/failure and never falls back to the host. PTY is honored only when an explicit terminal-capable client/backend exists. Async execution uses native Pi job lifecycle when available; otherwise it is unavailable. Non-PTY stdin is closed/EOF.

Bash interceptors and user patterns are advisory or narrowing controls only. They cannot authorize host execution, credentials, network, unsafe paths, or bypass the Gondolin route. Live output streams to clients; durable persistence stores one bounded final result plus truncation, artifact, policy, backend, and command-digest metadata.

### Web search

`web_search` follows the native Oh My Pi model-facing result contract. The request exposes a query and bounded result, recency/date, and domain hints. Provider selection, credentials, limits, concurrency, and deadlines remain host-controlled.

The default is a small bounded credential-free public provider strategy. Explicitly configured credentialed adapters may be enabled only by host/deployment configuration. Provider failures return bounded partial results and per-provider statuses; all-provider failure is `unavailable`. Search-only results contain bounded native snippets, URLs, source metadata, and truncation status. Page retrieval and browser fallback are separate future capabilities.

Search content is external and untrusted. It may inform ordinary answers but cannot establish PortLog or deterministic authority, change policy, authorize tools, or supply credentials. Bounded result metadata and source references persist in the session; full-page corpus persistence is out of scope.

### Task and verifier supervision

The model-facing `task` shape follows native Pi semantics, but v1 exposes a host-defined verifier role first. The parent supplies a role ID and bounded task description; the host constructs child system instructions, tools, model alias, limits, normalized input, and strict output schema.

The verifier receives host-normalized bounded input only. It has no arbitrary workspace, filesystem, shell, web, PortLog authority, credentials, or network access. It returns a strict versioned bounded assessment with claim/reference IDs, assessment, uncertainty, and diagnostics. Invalid or oversized output is typed failure/unavailable and never authority.

The root session is recursion depth 0. A verifier child is depth 1, and may use only a verifier-restricted task capability to request verifier grandchildren at depth 2. A depth-2 verifier is a leaf. The coordinator enforces global and per-child time, token, output, child-count, and concurrency ceilings. Independent verifier siblings may run in bounded parallel.

Child sessions have separate coordinator-owned Pi-compatible JSONL streams. The parent receives coordinator-authored lifecycle and result references; child Agents never append parent canonical history directly. Side-effect-free verifier children may outlive a parent turn, but completion appends a linked result and does not automatically resume the parent model. Failures are typed and are not automatically retried.

### Authority and provenance

Every capability result receives a host-generated versioned envelope. Stable authority classes remain `ordinary`, `portlog`, and `deterministic`; origin/provenance separately records workspace, external web, isolated guest, verifier, rule engine, or other source.

Only an explicit host-owned promotion whitelist may establish authority. Validated PortLog evidence may establish `portlog` authority. Validated rule-engine/Datalog outcomes may establish `deterministic` authority. Filesystem reads, write/edit results, bash, web search, isolated guest output, verifier output, and model prose remain ordinary context.

Short host-generated labels such as `[E1]` and `[D2]` map to immutable workspace/project and source/revision-scoped records. The UI expands them to source, scope, revision, rule, evidence, backend, and limitation details. Unknown or stale labels remain visibly unresolved. Uncited claims receive no implicit binding.

Claim status uses explicit answer posture and intent. In ordinary analysis, uncited prose may remain ordinary. In Inspect or Verify contexts that require PortLog evidence, unbound claims are visibly unsupported. Multiple qualifying references may support a claim; ordinary, external, or verifier references add context but cannot promote authority. Conflicting authoritative records remain immutable and produce a visible conflict until explicit reconciliation or a new deterministic evaluation resolves them.

Compaction may summarize ordinary model context but never replaces structured evidence, rule outcomes, claim bindings, authority envelopes, or provenance. Branches have independent trace identity and do not automatically merge authority or mutations.

### Migration and deletion

During migration, the new harness runs through a clearly opt-in path while the old path remains only as a temporary comparison oracle. There is no per-request fallback and no permanent dual runtime.

Replacement adapters reuse validated pure graph engines, canonical fact storage, rule execution, manifest/project identity, and Gondolin primitives where those components remain domain-correct. The new capability registry replaces the old per-turn and domain-facing adapters. A capability inventory must cover topology/evidence, rule checks, generated/bundled Datalog, manifest operations, isolated commands, and all authority-producing paths. No production direct engine call, sidecar callback, manifest write, or hidden session path may bypass registry admission.

Before deletion, the project maintains golden source bundles, normalized expected outcomes, authority/provenance invariants, confinement cases, crash/recovery cases, and representative old/new behavior comparisons. Public behavior and authority semantics must match; byte-identical old records are not required because the canonical session contract changes.

The hard cutover removes the old per-turn API, active legacy record projection, old domain-facing adapters, migration interaction flag, and hidden fallback path together. Existing legacy records remain opaque and read-only. Post-cutover recovery is release-level rollback or forward fix, not a retained hidden runtime.

## Testing Decisions

- Tests must exercise observable behavior at the highest seam: the host-owned session coordinator and its authenticated request/event protocol. Tests should not assert private helper functions, internal Pi object layout, or incidental JSON serialization beyond the documented native/custom event contract.
- The first experience prototype should use a real Pi `Agent` with deterministic scripted model/provider fixtures where repeatability is needed, plus a live provider mode for human evaluation. It should exercise native model output, normal Pi `read`, PortLog evidence, visible tool results, cancellation, and bounded failure without depending on persistence.
- Every prototype must have one obvious launch path, a short human task script, visible current state after each action, and an explicit verdict: keep, revise, or delete. Prototype traces are disposable and must not become an accidental production schema.
- The coordinator suite should cover session creation, native JSONL append order, writer fencing, observer attachment, queued prompt admission, event sequence gaps and resynchronization, cancellation, crash recovery, reopen compatibility, legacy read-only sessions, and explicit deletion cascade.
- The capability-registry suite should verify that every registered capability has policy admission, structured result status, authority/provenance envelope, cancellation, persistence, and reconciliation behavior. A migration inventory test should fail if an authoritative operation has no registry entry or a production bypass remains.
- The first `read` behavior test should verify workspace identity, bounded content, path denial, `.portlogignore` handling, truncation metadata, source digest, and native Pi result delivery through one full coordinator turn.
- Normal tool tests should cover write/edit snapshot preconditions, durable revision creation, hashline compatibility when adopted, protected-path denial, stale evidence behavior, and no silent mutation on conflict.
- Bash tests should cover simple host-safe execution, compound command routing, exact guest mapping, sanitized environment, hard timeout clamping, closed stdin, PTY/async unavailable results, cancellation, no host fallback after Gondolin failure, bounded output, and non-authoritative guest diffs.
- Web tests should use deterministic provider fixtures to verify bounded native result shape, host limits, provider partial failure, credential isolation, external-context labeling, cancellation, and no page/browser fallback.
- Verifier tests should cover strict input normalization, role/tool restrictions, depth-two recursion, global and per-child budgets, bounded sibling parallelism, child JSONL ownership, malformed output, cancellation, no automatic retry, and no authority promotion.
- Authority tests should verify promotion only from approved PortLog and deterministic backends, explicit evidence-label binding, stale and conflicting revisions, compaction preservation, branch isolation, unsupported claim projection, and ordinary/external/verifier non-promotion.
- Migration tests should compare old and replacement public behavior using golden source bundles and normalized outcomes, then verify no old production callsites, no hidden fallback, opaque legacy sessions, packaged Electron behavior, Gondolin confinement, and release-gate invariants.
- Prior art includes the existing local Pi review integration tests, native Electron acceptance tests, release verification tests, scripted provider/model fixtures, and the existing DEXPI graph/rule regression corpus. New tests should extend those public-behavior seams rather than create private unit-test seams for the old per-turn implementation.

## Out of Scope

- Moving Pi or the PortLog coordinator into the Gondolin guest.
- Adding VMPI or OMP as production runtime dependencies.
- Importing the full Oh My Pi coding-agent shell as a product dependency.
- Adding Codex App Server as a dependency or creating a second local coordinator.
- Rewriting Pi core, Pi AI provider implementations, Gondolin, DEXPI graph extraction, canonical fact export, or the Souffle engine without a demonstrated compatibility or security blocker.
- A model intent compiler, hard semantic routing based on the user question, or tool removal based on guessed intent.
- Host fallback when Gondolin is unavailable or isolation classification is ambiguous.
- Arbitrary host filesystem paths, arbitrary host environment variables, credentials in the guest, unrestricted host networking, or automatic browser fallback.
- Full page retrieval, browser automation, or unrestricted web research in the initial web capability.
- PTY support without an explicit terminal-capable client and backend.
- A PortLog-specific background job registry when native Pi job lifecycle is unavailable.
- General-purpose discovered project/user roles, arbitrary child system prompts, child-selected providers, unrestricted recursive subagents, or side-effecting verifier children in the initial task capability.
- Automatic model semantic repair loops, generic retries, replay of uncertain non-idempotent operations, or automatic parent continuation after async child completion.
- Automatic migration of old LocalInspectionRecord data or old sessions into new Pi JSONL.
- Automatic cross-project evidence rebinding, latest-revision-wins conflict resolution, or model-selected authority promotion.
- New hosted/browser deployment architecture, public server APIs, account persistence, or hosted provider-key stores.
- Deleting unrelated browser, hosted, or legacy desktop code outside the explicit old PortLog review/runtime path.

## Further Notes

This document is the superseding architecture decision for the full-Pi PortLog harness. It supersedes the prior reversible-adoption guidance that retained the old per-turn interaction and domain-facing adapter path, while preserving the accepted Hybrid isolated-command security model and the model-driven agent-loop contract where this document does not explicitly refine persistence, retry, child, or authority behavior.

The current narrow per-turn adapter and `LocalInspectionRecord` implementation are migration sources and historical terms, not supported compatibility APIs after hard cutover. Historical records remain useful for inspection but do not become new authoritative Pi events.

The architecture is intentionally upstream-first. PortLog-specific code should focus on process-engineering boundaries: DEXPI source identity, canonical base facts, rule-pack and rule authority, evidence references, answer posture, workspace policy, protected paths, Gondolin confinement, and provenance. Pi, Oh My Pi, and other mature harnesses should supply the general session, tool, model, task, streaming, and persistence mechanics wherever their contracts can be safely adapted.

The non-negotiable deletion gates are: one exhaustive authoritative capability registry; one fenced coordinator writer; host-owned authority promotion; end-to-end fail-closed routing; and packaged equivalence/data-safety evidence including opaque legacy records. Perfect live-model first-tool selection is an optimization metric, not a deletion gate.

The first delivery is the human-in-the-loop Pi-read plus PortLog-evidence prototype, followed by the separate bounded Gondolin spike. The first production deliverable is the persistent coordinator plus the validated read/evidence seam. All later capabilities must attach to that seam rather than create a parallel runtime.
