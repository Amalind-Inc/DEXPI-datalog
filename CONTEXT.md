# Context

This repository turns DEXPI 1.3 source files into graph-mirrored facts and
then derives deterministic Souffle predicates for verification. The current
trust boundary is `pyDEXPI` for XML-to-graph extraction and this repository
for graph-to-facts export plus derived classification and utility layers.

## Product

**PortLog** is a neurosymbolic **P&ID workbench**. Process engineers use it to
**create, edit, and optimize** piping and instrumentation diagrams (DEXPI). The
model proposes and explains; deterministic facts, rules, and host-owned policy
verify and gate changes. Inspect, Verify, and review QA are **modes inside the
workbench**, not the product itself.

**Product face:** macOS desktop GUI — an agent-workbench shell (Synara / Codex /
Cursor grammar for projects, documents, agent transcript, and accessible VM).
PortLog owns the drawing surface, multi-doc project workspace, evidence and
authority UX, propose→validate→apply edit path, and reopen provenance.

**Not the product:** interactive TUI; web UI as the product face; a chat-only
review viewer with no edit/apply path; silent DEXPI mutation or compliance
claims from model prose alone.

**Agent filter:** a task belongs in scope only if it helps someone create, edit,
or optimize a P&ID under grounded checks (or is required plumbing for that
loop). See `docs/agents/commodity-vs-core.md` and
`docs/agents/portlog-interaction-taste.md`.

## Language

**P&ID workbench**:
The PortLog product: a desktop workspace where process engineers create, edit,
and optimize P&IDs with a neurosymbolic engine (model + facts + rules +
host-owned policy and isolation). Review and QA are modes on this workbench.
_Avoid_: review-only chatbot, chat viewer, TUI product, web-as-product-face,
coding-agent clone without a drawing/edit path

**proposed edit**:
A structured candidate change to a P&ID / DEXPI / derived artifacts that the
model or a tool may suggest. It has no authority until host validation and an
explicit engineer accept/apply.
_Avoid_: silent rewrite, automatic DEXPI mutation, prose-as-applied-change

**apply (host-owned)**:
The explicit, host-authorized commit of an accepted proposed edit into PortLog-
owned document and artifact state, with provenance. The renderer and the model
never apply on their own.
_Avoid_: auto-apply, Pi session as source of truth, implicit save from chat

**DEXPI 1.3 source file**:
A single DEXPI 1.3 XML export that acts as the authoritative engineering input
to this repository.
_Avoid_: DEXPI 2.0 input, semantic IR source

**pyDEXPI full graph**:
The upstream directed graph export produced from a DEXPI 1.3 source file by
`pyDEXPI` without project-owned semantic abstraction.
_Avoid_: canonical graph, normalized graph

**canonical base fact layer**:
The persisted project-owned fact export that mirrors the pyDEXPI full graph
with stable ordering and provenance.
_Avoid_: semantic IR, curated predicate layer

**graph-shaped fact export**:
A fact export whose stable unit is one extracted node, one extracted edge, or
one attribute attached to a node or edge.
_Avoid_: XML-shaped export, domain-shaped export

**generic attribute fact**:
A persisted fact that records an attribute as a key-value pair instead of
committing that attribute to a dedicated predicate name.
_Avoid_: typed base predicate

**graph-mirrored fact vocabulary**:
The deterministic logic fact vocabulary emitted from the canonical base fact
layer.
_Avoid_: rule-specific fact vocabulary, inferred fact vocabulary

**generic graph utility layer**:
The first derived Datalog layer built over the canonical base fact layer using
reusable graph predicates such as traversal, containment, adjacency, and
attribute filtering.
_Avoid_: operator rule layer, pump-specific logic layer

**classification policy**:
The repo-owned derived-logic policy that maps generic exported graph facts into
stable edge families and later semantic helpers.
_Avoid_: exporter schema, rule-specific hardcoding

**supported DEXPI 1.3 fixture corpus**:
The set of parseable DEXPI 1.3 training fixtures that the repository uses as
its broad regression and coverage surface for graph-mirrored export.
_Avoid_: fuzz corpus, random test input

**rule**:
One executable logical check evaluated against the fact layer and its derived
utility predicates. Only a rule may produce a rule evaluation outcome.
_Avoid_: policy document, rule pack, advisory pack guidance

**rule pack**:
A versioned hybrid collection that may contain advisory pack guidance and zero
or more rules. Advisory content and executable rules share packaging and
browse/attach UX, but never share trust or verdict semantics.
_Avoid_: document, single rule, all-clauses-are-executable pack

**advisory pack guidance**:
Non-executable natural-language instructions, checklists, or excerpts inside a
rule pack that may guide human or agent review behavior but never produce a
rule evaluation outcome on their own.
_Avoid_: rule, soft advisory finding, engine verdict, trusted compliance check

**policy source document**:
A human-authored natural-language source such as a regulation, standard,
operator procedure, or internal compliance memo from which candidate rules may
be derived. Excerpts may be pasted into a rule pack only as advisory pack
guidance; they do not become rules by default and are never auto-compiled into
trusted executable logic.
_Avoid_: executable rule pack, silent compilation of regulation text into rules

**rule-pack synthesis**:
The explicit, human-initiated process of promoting selected advisory material
into one or more draft rules (restatement + candidate Datalog) for review. It
never runs automatically on ingest of a policy source document or pack
markdown.
_Avoid_: direct trusted execution, bulk auto-compile on upload

**LLM-assisted query synthesis**:
The process of deriving a candidate deterministic query or rule from a natural
language question, then grounding any answer in deterministic execution output.
_Avoid_: direct LLM compliance answer, ungrounded answer generation

**enterprise frontier inference boundary**:
A customer-approved cloud or provider boundary for using frontier LLMs without
requiring local model deployment or uncontrolled public data sharing.
_Avoid_: local-only inference, unrestricted public LLM calls

**deployment-tiered LLM privacy**:
The product model in which smaller customers may use managed frontier model APIs,
larger customers may use approved cloud or private-network frontier endpoints,
and exceptional customers may require customer-controlled model deployment.
_Avoid_: one-size-fits-all LLM deployment, local-only privacy model

**managed frontier API tier**:
The initial LLM deployment tier in which a customer supplies API credentials for
a managed frontier model provider and accepts that configured provider boundary.
_Avoid_: BYOC default, local model default

**model provider credential**:
A user-supplied credential for a configured frontier model provider used by the
BYOK logic-request workflow.
_Avoid_: OpenAI-only key, app-owned model credential

**deployment profile**:
The single explicit choice of how one running instance persists work: `local`
keeps every artifact on the operator's own machine with no accounts, `hosted`
persists per-user work behind sign-in. It is resolved once at the composition
root and is invisible below it, so no workflow, verification, or QA module
asks which profile it is running under. There is no default: an instance that
does not say which profile it is refuses to start.
_Avoid_: build flavour, deployment mode branch inside business logic,
defaulting to local when unset

**local provider credential store**:
The local-profile credential boundary in which model provider credentials are
retained only on the user's own device or session, including credentials
entered through local application settings, rather than in an application
account or hosted workspace. The hosted profile keeps credentials per
signed-in user, encrypted at rest and never readable by a browser client.
_Avoid_: account credential vault in a local deployment, server-managed
customer key store in a local deployment, plaintext hosted credential

**app-managed credit tier**:
The planned small-customer product tier in which the application manages model
provider access and bills usage through included credits plus overage.
_Avoid_: unlimited flat-rate usage, required customer API key

**text-only frontier inference**:
The initial model interaction mode that uses text prompts and artifacts rather
than image, SVG, or diagram-vision inputs.
_Avoid_: multimodal diagram interpretation, vision-based extraction

**predicate contract**:
The customer-independent relation vocabulary and usage constraints that describe
which deterministic facts and derived predicates a query may use.
Generated-query context includes this contract, allowed output shape, execution
restrictions, and relevant object identities already resolved through retrieval,
rather than the complete session fact database by default.
_Avoid_: plant facts, full graph disclosure

**advanced raw-attribute mode**:
An explicit query mode that allows generated logic to use generic source
attributes directly when stable curated predicates are not available.
_Avoid_: default attribute querying, hidden dependence on raw attribute names

**synthetic tutorial facts**:
Small non-customer examples used to teach query shape and predicate usage without
disclosing a customer's actual plant topology or object identities.
_Avoid_: customer-derived examples, production fact samples

**draft rule**:
A reusable rule candidate synthesized from user-provided rule text that is not
trusted until its engineer-readable semantics are reviewed and promoted.
Promotion may draft Datalog only inside the expressible predicate island;
clauses outside that island remain advisory pack guidance.
_Avoid_: trusted rule, automatic compliance rule, ambitious bulk regulation
compiler

**expressible predicate island**:
The bounded set of checks the engine may honestly compile and execute today:
topology/reachability over the shared EDB/IDB, component/class presence, and
comparisons of source-provided numeric attributes against thresholds. External
formulas, adequacy judgments, and open-ended defeasible prose are outside the
island and must abstain rather than be invented. OSS v1 stays on stratified
Souffle/Datalog (no ASP); exception-heavy clauses stay advisory unless made
crisp via explicit session exception/waiver facts. The island grows on demand
when recurring abstentions are groundable in DEXPI facts.
_Avoid_: full EPA/HAZOP compiler, ASP-before-packs, unbounded Datalog
generation, silent extra-diagram physics, freeze-forever toy topology island

**session exception fact**:
An explicit, engineer-entered fact (such as a scoped waiver or stated
exception) that a crisp Datalog rule may consult. It does not interpret free-text
“unless” clauses by itself and does not require ASP.
_Avoid_: model-inferred waiver, silent suppression of findings, defeasible ASP
layer in OSS v1

**engineer-readable rule restatement**:
A natural-language restatement of generated rule logic using explicit if-then
conditions, negation, and logical operators for process-engineer review.
_Avoid_: free-form summary, raw Datalog review

**reviewable rule artifact**:
The paired generated rule logic and engineer-readable restatement used for human
promotion, where the restatement is the object the engineer reviews.
_Avoid_: Datalog-only rule draft, unpaired rule summary

**validated generated query pair**:
An instance-bound generated Datalog query and its engineer-readable restatement
that have passed the required safety and semantic-faithfulness gates. The pair
may execute automatically as a temporary read-only query. Promotion into a
reusable rule remains a separate, explicit authoring action (see draft rule,
authored rule pack); automatic execution never grants reusable-rule trust.
_Avoid_: approved reusable rule, persistent rule approval, unvalidated generated query

**reusable rule**:
A source-independent, parameterized rule distributed through a versioned rule
pack and intended to evaluate compatible P&IDs without embedding source-specific
object identities. Reusable rules come from two distinct trust origins that are
never conflated: maintainer-bundled rules carrying bundled rule-pack trust, and
user-authored rules promoted from a draft rule into an authored rule pack,
carrying only author-confirmed rule trust. The model never promotes a generated
query into this category on its own; promotion always requires the user's
explicit authoring action.
_Avoid_: instance-bound topology query, validated generated query pair, authored
rule silently granted bundled rule-pack trust

**logic request**:
A user-authored natural-language request that may be turned into generated
logic, validated, and executed against the active review session.
_Avoid_: reusable rule, automatic rule promotion

**standard rule pack**:
A bundled collection of validated reusable checks for a recognized review
framework, regulation, or operator standard such as HAZOP or EPA-related review.
Repository-bundled packs carry bundled rule-pack trust; user markdown may
reference the same frameworks only as advisory pack guidance until individual
clauses are promoted into rules.
_Avoid_: ad hoc saved logic request, treating pasted regulation text as a
standard rule pack

**loaded standard pack**:
A rule pack attached to the active review session. Its advisory pack guidance
becomes active skill context for the agent; its rules become available for
deterministic evaluation. Attachment alone does not execute rules.
_Avoid_: arbitrary regulation text from model memory, unloaded compliance
source, treat attach as run

**attached pack skill context**:
The advisory pack guidance from attached rule packs that is injected into the
agent's session instructions while those packs remain attached. It may guide
questions and review behavior but cannot mint a rule evaluation outcome.
_Avoid_: engine finding, soft advisory finding presented as rule outcome,
detached documentation-only pack text

**demo rule pack**:
A repository-bundled, non-authoritative collection of example engineering checks
used to demonstrate reusable rule execution, justified outcomes, and evidence
behavior in OSS v1. The pack model supports multiple packs and rules; the first
complete tracer implementation is the pump discharge check-valve requirement,
and additional example rules may be added independently. It carries no external
certification or compliance claim.
_Avoid_: demo standard pack, certified rule pack, legal compliance source

**paid rule-authoring tier**:
A potential future billing tier gating the volume or governance sophistication
of rule authoring, such as team-shared authored packs or durable rule
governance across an organization. The core interactive authoring flow — draft
rule, reviewable rule artifact, promotion into a personal authored rule pack —
is not gated behind this tier. OSS v1 may accept user markdown that includes
advisory pack guidance (including pasted policy excerpts); it does not accept
pre-made packs that skip promotion and claim trusted executable rules on
upload.
_Avoid_: paid LLM model, silent trusted pack import, feature-gated authoring

**markdown pack ingest**:
The OSS v1 flow that accepts user markdown into an authored rule pack
immediately as advisory pack guidance (and any already-promoted rules if
present). It does not bulk-compile clauses to Datalog on upload; compilation
starts only from an explicit per-clause promote into a draft rule.
_Avoid_: async deontic compile-on-upload gate, attach blocked until compilation,
silent trusted executable import

**hybrid pack vertical slice**:
The OSS v1 completion bar for the hybrid rule-pack bet: one authored markdown
pack with mixed advisory pack guidance and at least one promoted rule that
runs end-to-end through markdown pack ingest, attach (skill context), explicit
promote, generic rule outcome convention execution, and in-thread evidence.
_Avoid_: UI-only MikeOSS theater, engine-only runner with no authoring path,
declare complete after demo-pack-only Souffle

**authored rule pack**:
A user-owned, non-authoritative rule pack that accumulates rules the user has
authored and promoted from a draft rule. Kept distinct from repository-bundled
rule packs but browsable and attachable the same way. It carries no external
certification or compliance claim and is never elevated to bundled rule-pack
trust.
_Avoid_: bundled rule pack, certified pack, shared team pack

**author-confirmed rule trust**:
The trust granted to one exact version of a user-authored reusable rule after
its author explicitly promotes the generated Datalog and restatement into an
authored rule pack. Subsequent runs of that exact saved version execute without
repeating author review. This trust is scoped to the promoted version and its
author: it never elevates to bundled rule-pack trust, is not shared with other
users, and any logic edit produces a new version requiring fresh promotion.
_Avoid_: ad-hoc query execution consent, bundled rule-pack trust, cross-user
trust, silent trust carryover across edited versions

**demo pump discharge check**:
The first demo standard-pack check, proving whether a pump has a reachable
downstream valve or control element in the prepared topology.
_Avoid_: synthetic legal EPA claim, hydraulic sufficiency check

**unloaded-standard response**:
A missing-capability response for standards or compliance requests when the
referenced standard pack is not loaded for the active review session.
_Avoid_: model-memory compliance answer, silent substitution of another standard

**topology QA logic request**:
A v1 logic request answered only by generated Datalog over approved graph and
topology predicates, with unsupported needs reported as missing facts or policy.
_Avoid_: hydraulic calculation request, simulation request, autocorrection request

**derived-semantics execution input**:
The v1 logic-request execution input consisting of an existing combined derived
graph semantics Datalog artifact rather than raw DEXPI XML.
_Avoid_: raw XML execution input, implicit extraction during logic execution

**hybrid QA request routing**:
The process of classifying a user request to the cheapest faithful answer path,
such as Datalog execution, metadata lookup, documentation answer, clarification,
or unsupported-capability response.
_Avoid_: force every question into Datalog, free-form compliance answer

**route receipt**:
A backend-issued, auditable artifact proving that a routing prerequisite reached
a specific outcome, such as template no-fit, exhausted binding correction, or
template faithfulness failure. It is bound to normalized semantic intent, source
snapshot, template-catalog version, and policy version; exact semantic retries
may reuse it, while a relevant change invalidates it. Models may consume valid
receipts but cannot create, assert, or widen them.
_Avoid_: session-wide fallback permission, model-claimed routing result, free-form fallback explanation

**cheap-first capability gating**:
The runtime policy that preserves model-planned capability choice while requiring
a valid route receipt before a more expensive generated-logic path becomes
available. It enforces cascade order without introducing a second intent
classifier.
_Avoid_: model honor system, unrestricted direct generation, duplicate router

**quiet route decision**:
A routing result that stays internal unless it requires user confirmation,
clarification, or a diagnostic message.
_Avoid_: debug route label in normal answer, noisy route explanation

**bounded engineering answer**:
A non-Datalog answer constrained to P&ID, process engineering, loaded source
facts, or loaded reference material, rather than open-ended general chat.
_Avoid_: open general knowledge answer, casual chatbot response

**model-led domain redirection**:
The conversational behavior where the model answers relevant general P&ID or
process-engineering questions with disclosed source posture and redirects
unrelated requests toward P&ID-specific work. The application does not duplicate
this judgment with a deterministic topic classifier.
_Avoid_: open general chatbot, application-owned topic keyword filter

**answer source posture**:
The user-visible indication of whether a bounded engineering answer is based on
general engineering knowledge, loaded P&ID facts, loaded reference material, or
a combination of those sources.
_Avoid_: hidden source boundary, raw route label

**graph lookup request**:
A request answered from direct local facts such as component type, immediate
connections, selected objects, or source attributes without derived inference.
_Avoid_: recursive query, compliance check, path reasoning

**graph lookup capability**:
A deterministic backend capability for searching prepared topology, resolving
tags, reading attributes, and retrieving immediate neighbors.
_Avoid_: model-owned graph query tool, generated graph lookup logic

**process-facing relationship**:
An engineering conclusion derived from a path through the pyDEXPI full graph,
such as one tagged object being reachable downstream of another. It is grounded
only when returned with the complete structural path that supports the
conclusion; it does not replace or outrank that path.
_Avoid_: standalone collapsed edge, provenance-free process connection

**structural path witness**:
The complete ordered path of pyDEXPI full-graph nodes and edges supporting a
process-facing relationship, including structural objects such as nozzles,
piping connections, piping nodes, and network segments. A process-facing
relationship without this witness is not grounded.
_Avoid_: optional provenance, hidden traversal path

**topology interpretation layer**:
The shared deterministic operations that interpret paths in the pyDEXPI full
graph as process-facing relationships and return the complete structural path
witness for every conclusion. It operates over the pyDEXPI full graph rather
than maintaining a second engineering graph.
_Avoid_: materialized engineering graph, consumer-specific traversal semantics

**direction evidence status**:
The grounding classification for process-flow direction. Allowed values are
`explicit`, when encoded by source DEXPI evidence; `inferred`, when concluded
from documented topology or engineering signals; and `unknown`, when direction
cannot be established. Inferred direction must be visible to the user, and an
unreviewed model-only inference cannot prove a formal rule outcome.
_Avoid_: hidden direction assumption, graph-edge orientation equals process flow

**session direction annotation**:
A user-reviewed assertion attached to an exact structural path witness in the
active review session. It records confirmation, reversal, or unknown direction
without modifying the pyDEXPI full graph or relabeling inferred direction as
explicit source evidence. It may be reused only while the exact witnessed path
and evaluation boundary remain unchanged; a new upload, changed path, or changed
boundary invalidates it and requires new review.
_Avoid_: source graph mutation, inferred direction promoted to explicit

**direction review card**:
An inline evidence-review interaction showing the proposed direction, its basis,
and the complete structural path witness with equal choices to confirm, reverse,
or mark direction unknown. Review blocks formal outcomes that require direction
but remains optional and visibly qualified for explanatory answers.
_Avoid_: free-text confirmation prompt, preselected approval, hidden path evidence

**model-selected read-only retrieval**:
The interaction in which the model translates an open-ended user question into
an approved, non-mutating topology operation whose arguments are validated and
executed by the backend. The operation returns deterministic evidence for the
model's final answer without requiring user confirmation.
_Avoid_: model-owned graph execution, unrestricted tool call, generated logic

**model-planned topology retrieval**:
The boundary where the application exposes constrained read-only topology
capabilities and the model decides which capabilities to use, in what bounded
sequence, and whether conversational clarification is useful. The application
does not duplicate this judgment with a deterministic intent compiler.
_Avoid_: application-owned prompt classifier, unrestricted model execution

**tool-capable model**:
A configured model that supports native application-defined tool calls, receives
tool results, and can continue a governed retrieval conversation. OSS v1
grounded QA accepts only tool-capable models; text-only structured-output
emulation is not a supported fallback.
_Avoid_: text-only model, parsed pseudo-tool call, provider-wide capability assumption

**restricted grounded-QA harness**:
The server-side model run loop that exposes only domain-approved tools under
allow, confirmation-required, or deny permissions; applies capability policy
and operational ceilings; supports user steering and optional user-configured
run constraints; and records tool and evidence history. It does not expose
arbitrary shell, filesystem mutation, graph mutation, or unrestricted network
access.
_Avoid_: coding-agent runtime, unrestricted autonomous agent

**model-driven agent run**:
An agent run that continues while the model emits authorized tool calls or
handoffs and ends when the model returns a final response without further tool
calls, the user steers or stops it, policy blocks it, or operation becomes
unavailable. It has no fixed semantic repair-attempt count by default.
_Avoid_: application-authored reasoning loop, mandatory semantic attempt budget

**user-configured run constraint**:
An optional user-selected bound on turns, duration, provider cost, or available
capabilities for an agent run. It may narrow runtime freedom but cannot disable
validation, widen capability permissions, or replace operational ceilings.
_Avoid_: hidden default reasoning cutoff, user override of safety policy

**operational ceiling**:
A provider, infrastructure, account, or deployment limit needed for cancellation,
resource safety, or service availability. It bounds runtime operation without
serving as the reasoning strategy or a target number of semantic repairs.
_Avoid_: arbitrary answer-quality cutoff, unlimited server process

**Answer Now steering**:
A user interruption that stops further agent work and responds from completed,
validated artifacts. If no grounded verdict exists, it reports established
facts, rejected attempts, and the current blocker without guessing or bypassing
validation.
_Avoid_: ungrounded preliminary verdict, execute-latest-invalid-query, forced completion

**capability effect policy**:
The authorization policy that classifies harness capabilities by effect rather
than by trace event kind. Approved read-only retrieval and validated logic may
run automatically; mutation, persistent promotion, customer-data transmission,
material external cost, and other side effects require separate authorization
or remain denied. Emitting a trace event never grants capability permission.
_Avoid_: trace-driven authorization, automatic side effects, capability-by-name trust

**tool-eligible model**:
A model that satisfies the technical requirement for native tool calls and
tool-result continuation in the restricted grounded-QA harness. Eligibility does
not certify answer quality; model capability and grounding risk remain inherent,
especially for smaller or open-weight models.
_Avoid_: text-only model, model-quality guarantee

**model-led ambiguity handling**:
The conversational behavior in which the model uses backend-returned candidate
objects to decide whether to answer for multiple candidates, disclose a likely
interpretation, or ask the user for clarification. The application does not
force a deterministic candidate-selection UI, but topology claims remain
limited to retrieved objects and witnessed evidence.
_Avoid_: mandatory ambiguity dropdown, silent invented object identity

**GraphML-backed topology graph**:
An interactive abstract graph view derived from DEXPI topology data, optionally
via a GraphML conversion layer, optimized for selection, filtering, paths, and
evidence. It is the implementation basis of the topology-inspection view, not
the default review presentation.
_Avoid_: default review view, force-directed node cloud as product face

**drawing-faithful schematic view**:
A rendering of the source P&ID that places equipment symbols, piping runs, and
labels using drawing geometry carried in the DEXPI source file itself, labeled
as drawn. Displaying source geometry is grounded source data, not layout
reconstruction, and carries no claim to substitute for the stamped drawing.
_Avoid_: invented layout, certified drawing substitute, reconstruction claim

**auto-layout schematic view**:
A schematic rendering used when source drawing geometry is missing or unusable,
in which connectivity is exactly what the source file states while positions are
inferred by automatic layout, and that inference is visibly labeled.
_Avoid_: as-drawn claim, silent position invention, force-directed node cloud

**file-defined symbol shape**:
A vector symbol definition carried inside the DEXPI source file's shape
catalogue, consisting of drawing primitives that the authoring tool exported.
Rendering it reproduces the original drawing's visual vocabulary.
_Avoid_: house-style substitution, symbol name without geometry

**bundled symbol library**:
The repository-owned ISO 10628-style symbol set keyed by DEXPI component class,
used when a source file provides no usable symbol shape and for all auto-layout
schematic rendering.
_Avoid_: exporter-specific shapes, per-customer symbol pack

**symbol resolution order**:
The per-element preference order for schematic symbols: file-defined symbol
shape first, bundled symbol library second, generic labeled placeholder last.
_Avoid_: bundled-first rendering in drawing-faithful view, silent symbol substitution

**topology-inspection view**:
A debug-oriented abstract graph view of extracted nodes and edges used to
inspect raw topology, not the default face of the product.
_Avoid_: default review view, primary evidence surface

**geometry sanity gate**:
The file-level admission decision for the drawing-faithful schematic view. It
requires a non-degenerate drawing extent, pipe-geometry coverage above a
calibrated threshold, and unpositioned equipment below a calibrated share.
Files failing the gate present as the auto-layout schematic view; positions
from the source are never mixed with invented in-frame positions.
_Avoid_: binary render-or-fail, silent mixing of real and invented positions

**unplaced-equipment shelf**:
The drawing-faithful presentation for equipment that lacks a source position:
rendered with its proper symbol and tag in a visually distinct region outside
the drawing frame, linked to its real connection points, with its missing
position disclosed. The drawn region itself remains exactly as the source
states.
_Avoid_: in-frame invented equipment position, hidden omission of unplaced items

**inferred pipe routing**:
The per-element fallback that routes a pipe run between its true source-stated
endpoints when the source provides no centerline geometry, drawn in the shared
schematic visual language with one uniform inferred-style cue and disclosed in
the geometry report.
_Avoid_: invented endpoints, per-element ad hoc styling

**schematic scene**:
The backend-prepared, renderer-agnostic description of one topology review
view: placed symbols, pipe polylines, labels, inferred-style cues, and the
object identities needed for selection and evidence highlighting. All symbol
resolution, routing, gating, and disclosure decisions are made in the backend
where the source is parsed; the frontend paints and handles interaction only.
Auto-layout position computation may execute client-side, but the decision to
auto-layout and its disclosure remain backend-owned.
_Avoid_: frontend geometry semantics, renderer that re-derives the source, report and render computed in different codebases

**geometry report**:
The typed per-file record of geometry coverage, sanity-gate outcome, and every
demotion or inference decision made during preparation. The renderer and the
user-facing health summary read the same report; the report describes and
demotes but never repairs source geometry in OSS v1.
_Avoid_: silent renderer judgment, geometry auto-repair, prose-only warning

**topology graph panel lifecycle**:
The OSS v1 graph panel starts hidden, opens automatically after a successful
DEXPI upload prepares topology data, and can then be manually closed or reopened.
_Avoid_: always-visible graph sidebar, hidden evidence-only graph

**topology graph visual language**:
The process-engineer-facing node labels, shapes, colors, and edge styles used
to distinguish equipment, instruments, lines, nozzles, piping nodes, segments,
and raw structural DEXPI objects in the topology graph.
_Avoid_: one-shape raw graph dump, unlabeled generic node cloud

**visual topology selection**:
A graph interaction used for inspection, details, and evidence highlighting
without implicitly becoming the source scope for an OSS v1 logic request.
_Avoid_: selection-to-query, hidden query scope

**text-derived query scope**:
An explicit query scope inferred from object tags or identifiers mentioned in
the user's prompt and included in execution progress and semantic disclosure.
_Avoid_: graph-click-derived scope, implicit selected-node scope

**Datalog reasoning request**:
A request that requires derived relationships, recursion, standards, absence,
constraints, multi-hop paths, or compliance logic over prepared facts.
_Avoid_: direct attribute lookup, unvalidated generated logic

**structured logic intent**:
A validated intermediate representation of a Datalog reasoning request, such as
intent, subject tag, standard, and condition, that can be compiled into bundled
query templates where possible.
_Avoid_: model-generated Datalog as first representation, free-form query text

**restatement-first semantic disclosure**:
The post-execution presentation where the plain-language meaning and structured
logic intent appear before the generated Datalog, result, and evidence details.
_Avoid_: Datalog-first disclosure, approval prompt

**collapsed generated Datalog**:
The post-execution disclosure rule where generated executable Datalog is behind
an expandable section by default while remaining available for inspection.
_Avoid_: mandatory raw Datalog display, hidden executable logic

**Datalog execution safety validation**:
Mechanical validation that generated Datalog stays within the prepared session's
fact base, approved predicate vocabulary, allowed output shape, filesystem
boundary, and execution limits before automatic deterministic execution.
_Avoid_: semantic proof of query correctness, arbitrary executable logic

**semantic-faithfulness gate**:
A backend-owned blocking evaluation that the generated Datalog and its
restatement preserve the structured meaning of the user's engineering question.
It runs before automatic execution and after every revision; failure or
uncertainty prevents execution, and exhausted repair yields a missing-capability
artifact rather than a best-effort answer.
_Avoid_: model self-attestation, post-execution-only review, tidy wrong result

**layered faithfulness verification**:
The authorization model in which deterministic structured-intent checks,
Datalog contract inspection, and applicable counterfactual probes establish
faithfulness before execution. A model-produced back-translation may veto or
request repair but can never be the sole evidence authorizing execution.
_Avoid_: LLM judge as authority, single-signal faithfulness approval

**missing-capability artifact**:
A structured response that records the facts, predicates, policy, or external
tools required before a user request can be answered faithfully.
_Avoid_: best-effort invented answer, silent unsupported answer

**LLM context policy**:
The tenant-controlled maximum customer context that may be sent to a configured
model provider for a request.
_Avoid_: implicit prompt data sharing, unlimited default context

**full-topology context**:
An LLM context policy level that permits sending the customer's complete graph or
fact topology to the configured model provider when explicitly allowed.
_Avoid_: default model context, unapproved plant disclosure

**logic-request audit record**:
A minimal persisted record of routing, model, context policy, generated artifacts,
validation, execution, semantic disclosure, and diagnostics for one logic request.
_Avoid_: full prompt transcript by default, sensitive prompt archive

**logic-request draft artifact**:
A compact persisted artifact containing the generated logic request state,
formal restatement, diagnostics, model metadata, and validation status.
_Avoid_: many-file draft bundle, prompt transcript archive

**automatic generated-query execution**:
The execution of a temporary read-only generated Datalog query without
per-request user confirmation after backend safety and semantic-faithfulness
validation succeeds. The user's engineering question supplies execution intent;
the model never controls validation or execution.
_Avoid_: unvalidated execution, model-controlled execution, generated-Datalog confirmation gate

**Datalog generation capability**:
A backend-governed capability the model may select when read-only retrieval and
bundled query templates are insufficient. It produces generated Datalog and an
engineer-readable restatement for backend validation and automatic deterministic
execution; selecting the capability never gives the model direct execution control.
_Avoid_: application-owned intent classifier, direct model execution

**post-execution query disclosure**:
A structured chat-thread state shown after automatic generated-query execution.
It presents the semantic restatement, source scope, route, validation outcomes,
inspectable Datalog, deterministic result, and evidence as disclosure rather
than an approval request.
_Avoid_: chain-of-thought trace, hidden generated logic, confirmation card

**grounded logic-request answer**:
A concise user-facing answer to a validated logic request that is backed by
deterministic execution output and an inspectable evidence trail.
_Avoid_: standalone LLM answer, evidence-free response

**evidence-linked natural-language answer**:
The free-form user-facing response generated from deterministic retrieval or
execution evidence, with references that connect its claims to inspectable
structural witnesses. Structured model output may support rendering internally,
but the user receives natural language rather than raw JSON.
_Avoid_: raw response envelope, evidence-free prose, application-authored answer template

**claim-level evidence chip**:
A compact selectable reference placed beside a natural-language claim. Selecting
it opens the topology review view, highlights the supporting structural witness,
and exposes its evidence details without replacing the answer with raw data. The
model may supply useful wording, while backend evidence metadata controls trust,
provenance, direction, review status, and limitations. Unknown evidence kinds
render as generic evidence rather than failing the answer.
_Avoid_: answer-level evidence dump, noninteractive citation label

**evidence summary with expandable details**:
The answer presentation pattern where a short evidence summary is always visible
and raw rows, bindings, paths, or provenance are available behind expansion.
_Avoid_: evidence hidden behind a single button, one-line answer only

**CLI-artifact logic workflow**:
The initial delivery mode for LLM-assisted logic requests in which commands write
inspectable artifacts before any application or API server wraps the behavior.
_Avoid_: UI-first workflow, hidden service-only execution

**orchestrated LLM workflow**:
An LLM-assisted workflow in which repository-owned code controls routing,
validation, execution, artifacts, and tool calls instead of delegating tool use
to an autonomous agent.
_Avoid_: autonomous agent execution, model-controlled tool loop

**logic-request refinement**:
An optional pre-draft step that turns a vague user request into a clearer logic
request with assumptions, clarifying questions, and a recommended scope.
_Avoid_: mandatory prompt rewriting, hidden change of user intent

**send-to-execution flow**:
The interaction where sending a Datalog reasoning prompt triggers bounded
routing, generation when needed, validation, deterministic execution, and
post-execution semantic disclosure without a per-query approval interruption.
_Avoid_: generated-Datalog confirmation gate, unvalidated automatic execution

**execution-before-graph-modernization**:
The implementation sequencing choice to complete the chat-thread Datalog
execution and disclosure workflow before replacing the graph panel with a
collapsible GraphML/Cytoscape topology view.
_Avoid_: combining execution workflow and graph renderer rewrite in one slice

**user-facing logic-request workflow**:
The interactive product flow in which a user uploads one DEXPI source file,
asks an engineering question, and receives a disclosed answer grounded in
automatically validated deterministic execution output.
_Avoid_: harness, ungrounded direct chat answer

**single-file review session**:
The OSS product session scoped to one uploaded DEXPI source file, its derived
artifacts, validations, disclosures, and deterministic answers. The source may
represent a broad conceptual model; a session's fact base, predicate contract,
and evidence trail are never merged with another session's. A chat may attach
more than one session; the one-file boundary is per session, not per chat.
_Avoid_: one-page guarantee, vault, project corpus, one-file-per-chat

**DEXPI source resource limits**:
Configurable preparation limits for one uploaded source, including input bytes,
XML complexity, extraction time, graph size, and artifact size. Exceeding a
limit produces an explicit diagnostic; drawing-element count alone is not an
adequate size or product-tier boundary.
_Avoid_: unlimited single-file processing, drawing count as workload proxy

**session preparation job**:
The asynchronous work that turns one uploaded DEXPI source file into a ready
single-file review session with derived artifacts and a topology review view.
_Avoid_: synchronous upload result, background vault indexing

**review workflow job**:
An asynchronous unit of work in the user-facing logic-request review workflow
whose completion produces a status, diagnostics, or result artifact.
_Avoid_: blocking UI action, hidden background side effect

**review project**:
A workspace that groups one or more chats. In the hosted profile it belongs to
a signed-in user; in the local profile it belongs to the single local operator
and requires no sign-in.
_Avoid_: flat chat history, unscoped document vault, one-chat-per-project,
sign-in treated as a precondition for grouping work

**chat**:
A conversation thread that may have zero or more single-file review sessions
and zero or more rule packs attached. The distinction between a chat and a
review project is that a project groups multiple chats; a chat itself may
already be multi-document and multi-rule-pack. A request addressing more than
one attached session fans out to each session's own scoped execution and
combines the separate results in prose; attached sessions' fact bases are
never joined into a single cross-diagram traversal.
_Avoid_: one-file-per-chat, diagram-scoped chat, project-level chat, joined
multi-file query, fused cross-diagram graph, cross-diagram structural path
witness

**temporary session artifact**:
An artifact that lives and dies with its review session and never becomes a
durable record of its own unless the user explicitly saves, exports, or
downloads it. "Temporary" describes whether the user saved the artifact, not
where the deployment runs: the term means the same thing for a local operator
and for a signed-in hosted user, because both keep their sessions until they
discard them.
_Avoid_: durable record created without an explicit save, "temporary" read as
"local", artifact outliving the session that produced it

**session-scoped logic reuse**:
Reuse of an exact validated generated query within its own review session,
without promoting it to a rule library or a reusable rule. The bound is the
session, not the process or the browser tab: while the session is available,
so is its validated query. Promotion stays a separate, explicit authoring
action.
_Avoid_: saved rule library, reuse in a different session, promotion implied
by reuse

**generated-query execution record**:
The backend-owned temporary-session artifact recording the exact generated
Datalog query, engineer-readable restatement, validation outcomes, and
deterministic execution identity. It is verified before reuse and is not inferred
from chat history or model context.
_Avoid_: conversational memory as validation, reusable-rule approval

**rule-pack picker**:
The rule-pack selection surface: searchable pack list beside a detail pane that
distinguishes advisory pack guidance from rules, presenting each rule's
engineer-readable restatement first with executable logic behind disclosure.
Selecting a pack attaches it (advisory guidance becomes attached pack skill
context); applying the pack is a separate explicit rule-pack run.
_Avoid_: run-on-select, Datalog-first pack listing, hidden pack loading,
advisory text shown as if it were a rule

**rule-pack run**:
The explicit action that applies an attached rule pack: evaluate its promoted
rules deterministically when any exist; if the pack is advisory-only, run an
agentic walkthrough from attached pack skill context without emitting rule
evaluation outcomes. A pack with both may do rules and guidance-driven review
in one apply action, but guidance never mints engine verdicts.
_Avoid_: run-on-select, advisory checklist results labeled as rule outcomes,
silent no-op with no explanation when no rules exist

**in-thread rule results**:
The presentation rule that rule-pack evaluation results arrive in the chat
thread as a stepped turn — one step per rule with its evaluation outcome and
evidence — rather than in a separate results surface. The chat thread remains
the single narrative of the review session.
_Avoid_: separate results silo, findings page detached from conversation

**bundled rule-pack trust**:
The durable OSS v1 trust assigned by repository maintainers to an exact published
version of a bundled rule pack. Rules from that version may execute immediately
without per-session semantic confirmation.
_Avoid_: model-approved rule, implicit trust of user-generated logic

**bundled query template**:
A source-independent, parameterized query shape published by repository
maintainers under bundled rule-pack trust. When the user's read-only engineering
question faithfully matches the template and its bindings validate, the exact
published template may execute without per-request confirmation. Binding
parameters does not create new logic, approve the design, or promote generated
logic into the trusted library.
_Avoid_: reviewed template, generated Datalog, implicit trust of user-authored logic

**template binding rejection**:
A bundled query template matches the requested query shape, but one or more
runtime bindings are invalid, incomplete, or inconsistent with the requested
classes, graph scope, or direction. The binding may be corrected without
changing the trusted template.
_Avoid_: template no-fit, generated-logic failure

**template no-fit**:
The determination that no bundled query template can faithfully express the
requested engineering question. It is a semantic routing outcome, not a
validation error or an execution outage.
_Avoid_: malformed binding, low-confidence template guess

**conservative template routing**:
The policy of selecting a bundled query template only when it can faithfully
represent the requested semantics. Unresolved route uncertainty becomes template
no-fit and may use generated logic; clarification is reserved for ambiguity in
the user's intended question. Lower template coverage is preferred to a
plausible but meaning-changing match.
_Avoid_: approximate template match, maximum-coverage routing, confidence cutoff

**reasoning-engine unavailability**:
An operational failure that prevents trusted deterministic logic from executing,
regardless of whether the logic came from a bundled query template or a
validated generated query. Changing the query-authoring path does not resolve it.
_Avoid_: template no-fit, generated-Datalog fallback

**stepped turn presentation**:
The chat presentation model in which an assistant turn renders as an ordered
sequence of step rows derived from turn lifecycle events — retrieval,
validation, execution, evidence — each with a status indicator and expandable
detail, with required human reviews appearing inline as blocking steps and the
grounded answer as the final block.
_Avoid_: single prose blob turn, tool dump without disclosure, review prompt outside the step sequence

**structured execution trace**:
The user-visible projection of routing, validation, execution, tool, and evidence
events for an engineering request. It presents concise status and summaries by
default with expandable artifact-backed details, while excluding private model
reasoning and policy-forbidden content.
_Avoid_: chain-of-thought transcript, fixed prose log, unbounded tool dump

**trace event envelope**:
The stable metadata shared by execution-trace events, including identity,
parentage, namespaced kind, status, summary, timestamps, and optional detail or
evidence references. Event kinds remain extensible; visibility, redaction,
grouping, size, and evidence requirements are enforced by policy and rendering
rather than by a closed event-kind list.
_Avoid_: closed trace-step enum, arbitrary ungoverned event content

**grounded conversational follow-up**:
A user request interpreted with prior conversation turns so references such as
"that path," "the other pumps," or "run the same check" retain their intended
context. Prior model prose provides conversational context but is not engineering
evidence; new topology claims must resolve to existing valid evidence items or
fresh deterministic retrieval or execution results.
_Avoid_: context-free turn, prior model claim treated as source fact

**grounded conversation compaction**:
The reduction of older conversational prose while preserving structured user
decisions, resolved object references, evidence identities, confirmations,
direction annotations, and limitations. Compaction may summarize language but
must not turn prior model prose into evidence or discard the provenance needed
for later follow-ups.
_Avoid_: full transcript forever, evidence-free conversation summary

**topology review view**:
The interactive visual view used to inspect equipment, connections, selections,
and answer evidence. It is presented as a drawing-faithful schematic view when
source geometry allows and as an auto-layout schematic view otherwise, and it
never claims to be a certified substitute for the stamped source drawing.
_Avoid_: certified drawing substitute, stamped-drawing replacement

**process-topology view**:
The default topology review view showing curated process-facing equipment and
connection relationships rather than every extracted graph fact.
_Avoid_: raw graph dump, full extraction graph view

**evidence highlighting**:
Visual emphasis in the topology review view for the source scope, matched
objects, and evidence paths behind a grounded logic-request answer or rule-pack
result.
_Avoid_: decorative diagram animation, unsupported visual inference

**visible source scope**:
The explicit source object or whole-file scope shown in execution progress and
post-execution disclosure for a logic request.
_Avoid_: hidden selected object, implicit prompt context

**Datalog-grounded restatement**:
An engineer-readable rule restatement generated from the candidate Datalog and
predicate contract rather than from the user's original wording alone.
_Avoid_: intent-only restatement, prompt summary

**manifest**:
The immutable run configuration that identifies the input source, rule pack
version, execution mode, and output destination for one run.
_Avoid_: input file, request

**finding**:
A single rule-evaluation result tied to a specific subgraph, with a severity,
evidence trail, and provenance.
_Avoid_: issue, anomaly blob

**finding severity**:
The project-facing classification used for rule evaluation results and review
artifacts.
Allowed values: `hard violation`, `soft advisory`, and `informational`.
_Avoid_: parser severity

**evidence trail**:
The structured record of the rule, facts, object identities, and context that
justify a finding or patch proposal.
_Avoid_: explanation only, free-text rationale

**rule evaluation outcome**:
The justified result of evaluating one rule against its defined scope. Allowed
states are `satisfied`, `violated`, and `indeterminate`. Every state carries
supporting evidence; absence of a violation is not proof of satisfaction.
_Avoid_: pass-by-default, binary result without evidence, no finding means valid

**satisfied rule outcome**:
A rule evaluation outcome supported by evidence that proves the requirement was
met throughout the rule's defined scope.
_Avoid_: no violation found, assumed compliance

**violated rule outcome**:
A rule evaluation outcome supported by evidence that the defined scope was
evaluated and the requirement was not met.
_Avoid_: unsupported failure, missing-object assertion without evaluated scope

**scope completeness evidence**:
The record showing that a rule's bounded evaluation scope was exhaustively
traversed, including its start, traversal policy, examined structural paths,
termination boundaries, and the reason traversal was considered complete. It
is required to justify a violated outcome based on absence.
_Avoid_: no match found, partial traversal presented as complete

**claim-aware truncation**:
The rule that bounded execution reports all grounded evidence obtained while
limiting conclusions according to coverage. A witnessed existential match or
counterexample may establish its corresponding claim, but truncated coverage
cannot establish a universal or absence conclusion and must produce an
indeterminate outcome with explicit limitations.
_Avoid_: discarded partial evidence, partial coverage presented as exhaustive

**indeterminate rule outcome**:
A rule evaluation outcome supported by evidence that missing, ambiguous, or
contradictory source structure prevents either satisfaction or violation from
being established.
_Avoid_: silent skip, forced pass, forced failure

**patch proposal**:
A non-applied, reviewable recommendation triggered by a finding, reconciliation
item, requirement claim, or explicit user request. It may contain multiple
individually reviewable operations, each with revision-pinned evidence, baseline,
impact, and explicit approval/validation limits.
_Avoid_: implicit mutation, free-floating model suggestion, applied write-back

**validation state**:
The persisted status assigned to an affected connected subgraph, such as
valid, needs review, blocked, or conflicted.
_Avoid_: whole-file verdict

**review-only**:
A run mode that reports raw findings and evidence without producing patch
proposals.
_Avoid_: dry-run

**dry-run**:
A preflight mode that validates the run configuration, source file, and
structural derivations without emitting findings or patch proposals.
_Avoid_: review-only

**affected connected subgraph**:
The minimal connected portion of the engineering graph required to evaluate a
rule, justify a finding, and explain the proposed patch.
_Avoid_: full graph, arbitrary neighborhood

**pump discharge-path rule family**:
A class of verification rules that evaluates the downstream discharge-side
topology of a pump against required protection and control expectations.
_Avoid_: generic topology rule

**discharge neighborhood**:
The rule-bounded directed downstream path that starts at a pump discharge
connection and stops at the first terminating boundary of interest.
_Avoid_: whole plant neighborhood

**first unbranched downstream segment**:
The default evaluation scope for the initial pump discharge-path tracer-bullet.
It starts at the pump discharge connection and stops at the first branch or
terminal object.
_Avoid_: arbitrary downstream closure

**evaluation depth**:
The strict policy-defined traversal scope used when evaluating a topology rule.
Evaluation depth is owned by the rule pack and is not widened by the manifest
at runtime.
_Avoid_: user-expanded path depth

**discharge nozzle**:
The process nozzle of a centrifugal pump identified as the source of the first
outgoing downstream segment for rule evaluation.
_Avoid_: synthetic nozzle role

**inline continuity item**:
A simple in-line piping item that the verifier may ignore while traversing a
first unbranched downstream segment toward a required component.
_Avoid_: required boundary component

**branch boundary**:
The first downstream topology point at which more than one distinct
continuation path exists from the current path.
_Avoid_: any multi-edge node

**evaluation diagnostic**:
A diagnostic emitted when the verifier cannot determine or traverse the rule's
required evaluation scope from the source model with sufficient certainty.
_Avoid_: standards finding

**off-page bounded failure**:
A local standards failure emitted when the first unbranched downstream segment
reaches an off-page connector before the required component is found.
_Avoid_: generic traversal failure

**check-valve presence requirement**:
The initial tracer-bullet acceptance rule that a centrifugal pump discharge
path is satisfied by the presence of any downstream DEXPI `CheckValve`
subclass on the first unbranched downstream segment.
_Avoid_: generic valve requirement

**discharge check-valve requirement**:
The initial pump discharge-path tracer-bullet rule stating that the first
unbranched downstream segment from a centrifugal pump discharge must contain a
check valve before the first terminal object or branch.
_Avoid_: all pump rules

**strict rule severity**:
Any rule the operator has provided as a strict requirement produces a hard
violation by default unless the rule explicitly specifies a different severity.
_Avoid_: parser severity

**discharge segment finding identity**:
The stable verifier finding identity for the initial discharge check-valve
rule.
_Avoid_: transient finding id

**findings-only rule**:
A rule execution mode that emits findings and evidence without producing patch
proposals.
_Avoid_: auto-fix rule

**discharge rule evidence set**:
The minimum evidence required for every v1 discharge-rule finding.
_Avoid_: free-form explanation

**answer posture**:
The disclosed mode and outcome class of a material PortLog response: Inspect,
Verify, Propose, or Redirect. It makes source/evidence boundaries and limitations
visible rather than treating all assistant prose as equally authoritative.
_Avoid_: hidden answer authority, generic chatbot response

**Inspect**:
The answer posture for a directed engineering question grounded in graph facts,
document claims, evidence references, and disclosed judgments. Its outcomes are

evidence cited or evidence insufficient; it does not issue a Verify verdict.
_Avoid_: compliance verdict, unsupported source claim

**Verify**:
The explicit-only answer posture that evaluates a selected validated executable
rule against its defined graph scope and reports satisfied, violated, or
indeterminate with deterministic evidence.
_Avoid_: advisory guidance treated as rule logic, model-prose verdict

**Propose**:
The explicit-only answer posture that prepares a non-applied reviewable
recommendation with provenance, baseline, impact, and outstanding validation or
approval limits.
_Avoid_: silent fix, applied DEXPI write-back, implied design approval

**provisional document claim**:
A revision-pinned assertion from an attached engineering document, with explicit
origin, link state, and one or more typed evidence references. It may be linked,
orphaned, or ambiguous, but it never automatically becomes a verified graph fact.
_Avoid_: hidden prompt context, source fact, unanchored model assertion

**typed evidence reference**:
A revision-pinned anchor to source material, such as a PDF page/region or
section/span, spreadsheet sheet/cell range, or drawing region. An excerpt is
optional when meaningful; the anchor, not invented text, establishes provenance.
_Avoid_: fabricated quote, text-only citation, unpinned source link

**reconciliation item**:
A non-verdict review record of a disagreement between evidenced assertions, such
as a provisional document claim and an active graph fact or governing source. It
is open, acknowledged, or superseded; it is not a finding, patch, graph mutation,
or Verify outcome.
_Avoid_: automatic compliance finding, silent conflict resolution

**governing-source selection**:
An auditable operator decision selecting the evidenced assertion that controls a
named review scope and as-of date. It records basis and scope without deleting
competing historical claims or changing graph facts.
_Avoid_: latest-upload-wins, permanent project truth, automatic source authority

**guidance skill**:
A versioned PortLog/operator-managed advisory artifact that may guide Inspect and
Propose while remaining distinct from engineering evidence and executable rules.
It may recommend but never activate or execute a rule pack.
_Avoid_: user-uploaded hybrid pack, hidden evidence, Verify premise

**link-resolution queue**:
The persistent review queue for orphaned or ambiguously linked document claims,
including their evidence references and any candidate graph mappings. Claims in
this queue do not participate in reconciliation until their identity link is
resolved.
_Avoid_: fuzzy match treated as graph link, hidden unmatched document content
