# PortLog Harvey-Style Review Doctrine

## Status

Product doctrine for PortLog's OSS/BYOK review workspace. It locks product
boundaries and review semantics; it does not authorize an implementation,
apply a change to a plant model, or create a commercial Harborfield product.

## Product identity

PortLog is a process-engineering review workspace. It helps an engineer inspect
an evidenced project, verify an explicit formal rule when one exists, and
prepare reviewable recommendations. It is not chat with a drawing, a digital
twin/simulation deliverable, an OCR-first product, or an automatic DEXPI
write-back tool.

The near-horizon pillars are:

1. **Answer posture** — the product says what kind of answer it is giving and
   what supports it.
2. **Document analysis** — engineering documents produce grounded, provisional
   review material rather than hidden prompt context.
3. **Patch proposals** — the product produces reviewable, non-applying
   recommendations rather than silent fixes.

Harborfield is a guiding principle only. PortLog remains an OSS/BYOK harness.

## Corpus and trust boundaries

A DEXPI source is the spine for verified graph facts in a single-file review
session. A chat may attach multiple such sessions and chat-scoped documents;
requests fan out to their separate session scopes and combine results in prose.
PortLog does not join those fact bases into a fused cross-diagram traversal in
this doctrine horizon.

PortLog distinguishes three trust strata:

- **Verified graph facts** — deterministically present in the active DEXPI
  graph representation. They do not, by themselves, establish current physical
  plant truth.
- **Provisional document claims** — revision-pinned assertions extracted from
  or inferred from attached engineering documents. They never promote
  themselves to graph facts.
- **Judgments** — disclosed human or model interpretations. They are not
  evidence or a formal verdict.

A governing-source selection is a separate, auditable operator decision about
which evidenced assertion controls a named review scope and as-of date. Later
uploads do not silently win, and a selection neither erases historical claims
nor mutates a graph fact.

## Answer posture

Every material answer discloses its mode, outcome class, source/evidence
boundary, and limitations.

### Inspect

Inspect is the default for directed, grounded engineering questions. It may
cite graph facts, document claims, evidence references, and disclosed
judgments. Its outcomes are `evidence_cited` and `evidence_insufficient`; it
never emits a Verify verdict.

### Verify

Verify is explicit-only. It evaluates an explicitly selected, validated
executable rule against the defined graph scope and returns only `satisfied`,
`violated`, or `indeterminate`, with deterministic evidence. Advisory guidance,
model prose, and document claims do not create a Verify premise or outcome.

### Propose

Propose is explicit-only. It prepares a reviewable recommendation with its
provenance, baseline, expected impact, and limitations. It does not apply a
DEXPI edit, document edit, graph mutation, rule-pack promotion, governing-source
selection, or field change.

### Redirect

PortLog redirects unrelated requests toward relevant process-engineering review
work rather than acting as open general chat.

## Document analysis

Document analysis creates one generic, typed **provisional claim ledger**.
Claim kinds include properties, relationships, requirements, and document-control
assertions. A usable claim has:

- an explicit origin: `document_extracted` or `model_inference`;
- a link state: `linked`, `orphan`, or `ambiguous`;
- one or more revision-pinned typed evidence references; and
- preserved modality, applicability conditions, and exceptions.

Evidence references are typed anchors, not mandatory text excerpts: for example,
a PDF page/region or section/span, spreadsheet sheet/cell range, or drawing
region. Excerpts or OCR text are optional where meaningful. An unanchored
potential assertion produces a diagnostic or coverage gap, not a claim.

A deterministic, unambiguous identity mapping may link a claim to a graph
entity. Model or fuzzy matches remain ambiguous candidates until engineer
confirmation. Candidate sets and their matching bases persist in a
link-resolution queue; an engineer-confirmed mapping may be reused only for
claims from that exact document revision.

Analysis automatically creates non-verdict reconciliation items when linked
claims conflict with the active graph or an active source selection. A
reconciliation item preserves the competing assertions, their evidence, and the
comparison basis. Its lifecycle is `open`, `acknowledged`, or `superseded`; none
of those states is a finding, a Verify outcome, a patch, or a mutation.

Claims from all document revisions remain immutable. A review scope may select
a governing source with explicit operator identity, rationale, scope, and time.
Without that selection, competing assertions remain an unresolved disagreement;
Inspect presents the evidence and Verify abstains when it requires one value.

Standards, procedures, and narratives produce provisional requirement claims.
Only an explicit Propose/formalize request may create a non-executable candidate
logic expression against PortLog's known logic schema and predicate vocabulary.
It may mention approved EDB or derived/IDB predicates, but it creates no EDB
facts, executable rule, or compliance outcome.

## Curated guidance skills and rules

Hybrid advisory rule packs are not a normal user-facing Markdown upload
workflow. PortLog/operator-managed, versioned guidance skills may be bundled or
installed outside ordinary review work. Engineers attach normal engineering
documents instead.

A skill may guide Inspect and Propose: it can prioritize questions or retrieval,
shape an explanation, or inform a candidate proposal. When it materially guides
a result, PortLog discloses the skill name and version and distinguishes its
advisory guidance from actual graph or document evidence.

A skill never supplies a Verify premise, activates a rule pack, or executes a
rule. It may recommend a compatible validated rule pack or help draft an
explicit formalization proposal. Verify still requires explicit rule selection
and deterministic execution.

## Patch proposals

A proposal uses one common, non-applying envelope and one of three kinds:

1. **Graph/topology change recommendation** — typed suggested graph or
   topology operations plus an engineer-readable rationale.
2. **Document/reconciliation resolution recommendation** — a typed suggested
   source or authority resolution plus rationale.
3. **Engineering action/change-order recommendation** — a structured requested
   action, recipient/owner, and verification request plus rationale.

Every proposal links to a review trigger — a finding, reconciliation item,
requirement claim, or explicit user request — and has revision-pinned evidence.
It records its graph/document/review-scope baseline, affected targets, expected
benefit, assumptions, and unknowns. A changed baseline makes the proposal stale
or in need of rebase; it does not make the recommendation silently applicable.

A proposal may contain multiple individually identified edits when they form one
engineering change package. Each child can be accepted, rejected, or marked
needs-revision. Accepted children form an explicit accepted subset; the
remaining children become a separately identified derived remainder proposal.

Proposal lifecycle is `draft`, `proposed`, `accepted`, `rejected`,
`needs-revision`, or `superseded`. Acceptance endorses the recommendation for
export or downstream work only; PortLog does not apply it.

Every Propose result states that it is non-applied, identifies whether its
rationale rests on graph evidence, provisional document claims, and/or judgment,
and lists validation and approval still required. It never implies design
approval, field implementation, or compliance satisfaction.

## Desktop delivery boundary

PortLog is moving to an Electron desktop harness while preserving the
repository-owned Python/Souffle engine, typed review API, artifact/catalog
authority, and review state machine. The desktop shell reuses review workspace
surfaces; hosted-web fate remains deferred.

Pi is an optional replaceable agent adapter, not PortLog's project or transcript
authority. PortLog owns user-visible chat/turn state, deterministic artifacts,
evidence, findings, proposals, and decisions. The first planned integration
layer is the upstream `@earendil-works/pi-coding-agent` SDK behind a
PortLog-owned adapter with PortLog capability tools; its Electron sidecar and
OAuth fit-gap remains a separately charted implementation spike.

## Explicit exclusions

This doctrine does not authorize:

- applied or silent DEXPI rewrites;
- automatic promotion of document claims to verified graph facts;
- automatic trusted compliance claims from model prose;
- fused cross-diagram graph reasoning or joined multi-spine Verify verdicts;
- OCR-first ingestion;
- a twin/world-model simulation deliverable;
- Harborfield commercial packaging; or
- selection of the first engineering implementation wedge.
