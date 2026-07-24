# Witness-Grounded QA Contract

## Purpose

The OSS assistant answers open-ended P&ID questions conversationally while
grounding source-specific claims in deterministic evidence. The application
controls execution and evidence boundaries. The configured model controls
language interpretation, retrieval planning, ambiguity handling, and prose.

## Source Boundary

- One chat accepts one successfully prepared DEXPI XML source file.
- The pyDEXPI full NetworkX graph remains the only graph representation.
- Canonical base facts persist that graph with stable provenance.
- A DEXPI source is not assumed to equal one graphical drawing page.
- Upload, XML, extraction, graph, artifact, and preparation resource limits are
  configurable and produce explicit diagnostics when exceeded.
- Future pairwise comparison and bulk review operate over separate source
  sessions; they do not merge source graphs.

## Topology Interpretation

- Shared read-only topology operations interpret the pyDEXPI full graph.
- A process-facing relationship is a computed conclusion, not a stored second
  graph edge.
- Every process-facing relationship includes its complete ordered structural
  path witness.
- A relationship without its structural witness is not grounded.
- Flow direction is classified as explicit, inferred, or unknown.
- Model-only direction inference is disclosed and cannot independently prove a
  formal rule outcome.
- Users may confirm, reverse, or mark inferred direction unknown. The resulting
  session annotation does not modify source evidence.
- Direction annotations are reusable only while the exact path witness and
  evaluation boundary remain unchanged.

## Model And Tool Boundary

- The application exposes constrained domain tools; the model plans their use.
- Tool arguments, permissions, budgets, outputs, and evidence references are
  validated by the backend.
- Read-only topology retrieval and bundled-rule execution may run immediately.
- Generated temporary Datalog is an allowed read-only capability: after
  mechanical safety validation and layered semantic-faithfulness gates pass,
  it executes automatically through the restricted harness. It never executes
  directly from an unvalidated model request.
- Models must support native tool calls and tool-result continuation. Text-only
  pseudo-tool parsing is unsupported.
- The product does not certify, score, or label model answer quality.
- Internal model evaluations are regression tests, not product eligibility
  tiers. Inherent model-quality risk remains visible.
- The harness exposes no arbitrary shell, filesystem mutation, graph mutation,
  or unrestricted network tools.

## Retrieval And Claims

- The model may perform a bounded sequence of read-only operations.
- Ambiguity handling is model-led. The model may answer for multiple retrieved
  candidates, disclose an interpretation, or ask conversationally.
- The application does not implement a deterministic intent compiler or
  mandatory candidate-selection UI.
- Execution reports all grounded evidence obtained plus coverage and
  limitations.
- Truncated coverage may establish an existential match or counterexample when
  the returned witness is logically sufficient.
- Truncated coverage never establishes a universal or absence conclusion.
- General P&ID and process-engineering education may use model knowledge with
  disclosed source posture.
- Claims about the loaded source require valid retrieved or executed evidence.
- Unsupported source-specific calculations disclose missing data rather than
  relying on fabricated inputs.

## Datalog And Rules

- Generated Datalog receives the predicate contract, allowed output shape,
  execution restrictions, prior conversational context, and relevant object
  identities resolved through retrieval.
- The complete session fact database is not sent to the model by default.
- Backend validation establishes execution safety, not semantic correctness.
- A generated Datalog query and its engineer-readable restatement form one
  exact query pair. After automatic validated execution, the product discloses
  that pair for audit; disclosure is not reusable-rule approval. Promotion into
  a reusable authored rule remains a separate explicit authoring action.
- All model-generated logic remains temporary, even when it appears
  source-independent.
- OSS v1 reusable rules come only from repository-bundled, versioned rule packs.
- User-uploaded executable packs, policy-document ingestion, generated-rule
  promotion, and durable user rule storage are outside OSS v1.
- Bundled demo packs are explicitly non-authoritative and make no certification
  or compliance claim.
- The pack contract supports multiple packs and rules; the first complete rule
  is the pump discharge check-valve requirement.

## Rule Outcomes

- Every rule evaluation returns satisfied, violated, or indeterminate.
- Every outcome includes evidence.
- Satisfaction requires evidence proving the requirement over its defined
  scope.
- Absence-based violation requires the fully evaluated bounded scope and scope
  completeness evidence.
- Missing start, direction, completeness, or termination evidence produces an
  indeterminate outcome.
- No violation found is not proof of satisfaction.

## Conversation And Presentation

- The Python backend owns resumable conversation, turn, item, tool, evidence,
  review, interruption, and completion state.
- Web and future CLI clients consume the same lifecycle.
- Follow-up questions receive prior conversational context.
- Prior model prose is conversational context, not engineering evidence.
- New claims resolve to still-valid existing evidence or fresh deterministic
  evidence.
- Older prose may be compacted, but user decisions, resolved objects, evidence
  identities, confirmations, direction annotations, and limitations are
  preserved structurally.
- Users receive free-form natural language, not raw model response envelopes.
- Claim-level evidence chips connect prose to structural witnesses. Model-authored
  labels may vary, while backend metadata controls provenance, direction,
  review status, trust, and limitations.
- Selecting an evidence chip opens the topology view, highlights the witness,
  and exposes its details.

## Product Scope

- OSS v1 is a web-native, single-source conversational review workflow.
- Pairwise P&ID comparison is a separate future workflow.
- Multi-source project review, bulk rule execution, uploaded rule packs, and
  policy-to-rule authoring belong to future product tiers.
- Multi-agent checking may supplement the same evidence boundary later but is
  not required for OSS v1.
