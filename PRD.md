## Problem Statement

Process engineering teams need a deterministic, auditable way to validate
Smart P&IDs exported as DEXPI XML, detect standards and safety anomalies, and
propose concrete corrections without losing traceability. The current need is
for a workflow that can operate on a single DEXPI source file, preserve the
source-of-truth engineering context, and produce reviewable output that can be
trusted by engineers and auditors.

## Solution

Build a manifest-driven P&ID verification pipeline that ingests one DEXPI XML
source file, normalizes it into a lossless canonical engineering IR, evaluates
versioned rule packs against the affected connected subgraph for each finding,
and emits immutable review artifacts with full provenance. The workflow should
support dry-run preflight validation, review-only raw rule hits, deterministic
patch proposals, explicit waivers/suppressions, and stable human-readable
console output rendered from a machine-readable source-of-truth artifact.

## User Stories

1. As a process engineer, I want to provide a single run manifest for one DEXPI
   source file, so that each evaluation run is explicit and reproducible.
2. As a process engineer, I want the manifest to name the rule pack, version,
   lifecycle state, execution mode, run ID, and output destination, so that the
   run contract is fully declared up front.
3. As a reviewer, I want the run manifest to be stored unchanged with the run,
   so that I can later see exactly what intent produced the output.
4. As a reviewer, I want each rerun to create a new immutable manifest copy,
   so that prior runs remain reproducible.
5. As a rules author, I want rule packs to be human-editable YAML or JSON with a
   strict schema, so that policies can be maintained without editing engine
   code.
6. As a rules author, I want each rule to have a nested structure with separate
   sections for scope, conditions, evidence, and patch intent, so that complex
   logic remains readable.
7. As a rules author, I want condition trees to support arbitrary nesting, so
   that I can express real engineering logic without artificial limits.
8. As a rules author, I want optional labels on condition tree nodes, so that
   complex rules remain understandable to reviewers.
9. As a rules author, I want a fixed, small core predicate set with no
   extension predicates in the first version, so that the vocabulary stays
   predictable.
10. As a rules author, I want predicates to operate on typed entities after
    normalization, so that matching is consistent and less error-prone.
11. As a reviewer, I want ambiguous normalization to generate diagnostics, so
    that I can see when canonical tags were inferred from imperfect input.
12. As an engineer, I want the canonical engineering IR to preserve raw tag
    variants alongside canonical forms, so that no source evidence is lost.
13. As a reviewer, I want findings to carry severity values of hard violation,
    soft advisory, or informational, so that I can triage issues correctly.
14. As a reviewer, I want each finding to include a structured evidence trail,
    so that I can understand why the rule fired.
15. As a reviewer, I want each patch proposal to be a single concrete edit, so
    that I can approve or reject a specific fix.
16. As a reviewer, I want patch proposals to allow additive and modifying
    changes but not deletions initially, so that the correction workflow stays
    safe.
17. As an operator, I want the engine to derive the affected connected
    subgraph automatically using rule-specific required relations, so that the
    review scope is focused and not hand-curated.
18. As an operator, I want a dry-run mode that validates the manifest, source
    file, compatibility, and subgraph shape without producing findings or
    patches, so that I can preflight a run cheaply.
19. As a reviewer, I want review-only mode to show raw findings with evidence
    but no patch proposals, so that I can assess rule hits separately from
    proposed fixes.
20. As an operator, I want normal runs to apply waivers and suppressions only
    after rule resolution, so that the underlying finding remains visible in
    history.
21. As an auditor, I want waived and suppressed findings to remain as historical
    records, so that I can trace what was hidden and why.
22. As an auditor, I want all artifacts to be append-only and immutable, so that
    no run output can be silently rewritten.
23. As an auditor, I want findings, patches, validation state, diagnostics, and
    manifests to share a provenance chain, so that each result is explainable
    end to end.
24. As an engineer, I want the machine-readable artifact to be the source of
    truth, so that the console report can be a pure rendering of the persisted
    record.
25. As an engineer, I want deterministic sorting of artifact lists, so that
    diffs are stable and meaningful.
26. As an operator, I want the console to present a fixed human-readable
    multi-section report, so that I can read the run result without a machine
    parser.
27. As an operator, I want the console to group repeated findings by rule or
    object family and show representative examples, so that large runs remain
    readable.
28. As an operator, I want stable exit codes and categorized failures, so that
    automation can detect parse, validation, evaluation, and output problems.
29. As a maintainer, I want the engine to cache source-derived canonical IR and
    topology by content hash, so that repeated dry-runs and incremental work are
    efficient.
30. As a maintainer, I want cache cleanup to be manual at first, so that I can
    control retention while the system is still small.
31. As a maintainer, I want internal logs to be separate from persisted
    artifacts, so that operational noise does not dilute the audit trail.
32. As a maintainer, I want internal logs to be cleaned up automatically by a
    retention policy, so that the workspace does not accumulate unnecessary
    debugging output.
33. As a maintainer, I want single-run exclusivity enforced for the full run
    context, so that concurrent runs do not collide.
34. As a maintainer, I want the engine to stop on conflicted findings until a
    human resolves them, so that no hidden arbitration occurs.
35. As a maintainer, I want a separate migration tool for manifest schema
    updates, so that old manifests can be upgraded explicitly without runtime
    ambiguity.
36. As a maintainer, I want the manifest schema version to be explicit and
    strictly validated, so that compatibility is auditable.
37. As a maintainer, I want the rule pack, engine, and schema to each have
    independent versioning, so that changes can be traced to the correct layer.
38. As a maintainer, I want all diagnostics to use stable codes, so that
    validation and normalization issues are searchable and testable.
39. As a maintainer, I want extension fields in allowed namespaces to be
    preserved verbatim end to end, so that future metadata is not lost.
40. As a reviewer, I want the system to reject unknown predicates and unknown
    vocabulary in execution, so that rule packs cannot drift silently.

## Implementation Decisions

- The run contract is a single-source manifest with explicit rule pack name,
  version, lifecycle state, execution mode, run ID, and output destination.
- The canonical engineering IR is a lossless superset of source DEXPI data and
  preserves vendor/source IDs, engineering tags, raw tag variants, and
  normalization diagnostics.
- Rule packs are structured YAML/JSON documents with a nested rule schema,
  strict validation, required short rationales, and no extension predicates in
  the first version.
- Rule conditions are represented as arbitrarily nested condition trees with
  `all`, `any`, and `not` blocks plus optional human-readable labels.
- Predicates operate primarily on typed entities and relations after
  normalization; string-based predicates are intentionally limited.
- The engine normalizes before rule evaluation and records ambiguity as
  diagnostics while still preserving a single canonical tag per object.
- Dry-run is a preflight structural validation mode only; it validates the
  manifest, source file, compatibility, and subgraph shape without findings or
  patches.
- Review-only mode emits raw findings with evidence only and does not emit
  patch proposals.
- Normal evaluation uses rule-specific required relations to derive the
  affected connected subgraph automatically.
- Patch proposals are single atomic edits, concrete rather than abstract, and
  may add or modify topology, attributes, and metadata but do not delete
  objects initially.
- Rule evaluation is deterministic: all eligible rules are evaluated and the
  highest explicit numeric priority wins; conflicts block for human resolution.
- Waivers and suppressions are applied after rule resolution in a separate
  suppression layer, while raw findings remain in history.
- The source-of-truth persisted artifact is machine-readable JSON or YAML with
  a single unified schema and typed sections.
- Console output is a pure human-readable rendering of the persisted artifact
  with a fixed multi-section format and grouped repeated findings.
- Artifacts are append-only and immutable, with deterministic ordering and
  stable IDs/hashes for comparison.
- The artifact store is separate from the source code tree and organized by a
  run-based directory hierarchy with a simple file-based index first.
- Internal logs are separate from persisted artifacts and are subject to
  automatic retention cleanup; persisted artifacts are retained as historical
  records.
- The engine caches source-derived canonical IR and topology by content hash
  and current parser/schema versions; cache cleanup is manual at first.
- The first version supports single-run exclusivity on the full run context.
- Failure handling uses a single primary category with optional secondary
  tags, stable exit codes, and persisted diagnostics.
- Manifest validation is schema-first and emits field-level diagnostics for
  all errors before execution.
- The schema supports unknown optional fields only in a namespaced extension
  area, and those extension fields are preserved end to end.

## Testing Decisions

- Favor black-box tests at the highest practical seam: manifest validation,
  source loading and normalization, rule evaluation, suppression handling,
  patch synthesis, artifact serialization, and console rendering.
- Good tests should assert externally visible behavior only: accepted versus
  rejected manifests, emitted diagnostics, preserved provenance, deterministic
  artifact ordering, and the presence or absence of patch proposals under each
  mode.
- Test the manifest schema validator with valid inputs, invalid field values,
  missing required fields, schema version mismatches, execution-mode mismatch,
  and extension-field preservation.
- Test normalization at the canonical IR seam by asserting that raw variants
  are preserved, canonical tags are produced, and ambiguity diagnostics are
  recorded.
- Test rule evaluation against the affected connected subgraph seam by using
  representative source inputs that trigger local and topology-aware rules.
- Test review-only and dry-run separately to ensure dry-run stays structural
  only and review-only emits raw findings with evidence but no patch
  proposals.
- Test suppression and waiver handling as a post-resolution layer by verifying
  that raw findings still exist in history even when hidden from normal output.
- Test artifact generation by verifying stable IDs, stable ordering, grouped
  console summaries, and the unified machine-readable artifact schema.
- Test cache behavior at the source-derived structure boundary by using
  content-hash changes to confirm cache hits, misses, and invalidation.
- Prior art in this workspace is minimal, so the new tests should establish the
  first set of behavior-driven seams for the manifest, normalization, rule
  evaluation, and artifact layers.

## Out of Scope

- Computer vision or PDF digitization of scanned P&IDs.
- Automatic deletion of objects or fully autonomous autocorrection.
- Batch processing across multiple source files in one run.
- Extension predicates and namespaced custom rule vocabulary in the first
  version.
- Free-form natural-language rule definitions as the source of truth.
- Automatic retries for failed runs.
- Automatic migration of manifests inside the runtime path.
- Concurrent multi-run execution against the same run context.
- Database-backed artifact indexing before the file-based index proves
  necessary.
- Advanced waiver approval workflows beyond structured waiver metadata.
- Arbitrary user-defined output path templates.
- Silent rule-pack upgrades or implicit execution-mode switching.

## Further Notes

- The design prioritizes freshness, traceability, reproducibility, and human
  reviewability over raw throughput.
- The most important early implementation seams are manifest validation,
  normalization, affected connected subgraph derivation, rule evaluation,
  suppression, patch synthesis, and artifact rendering.
- The PRD assumes a local issue-tracking setup in this workspace and a
  persistent artifact store separate from the source code tree.

## Success Criteria

- A single-source run manifest can be validated strictly before execution.
- A canonical engineering IR can be produced from a DEXPI export while
  preserving raw variants, provenance, and normalization diagnostics.
- Rule packs can be loaded from structured YAML or JSON and validated against
  the fixed core predicate vocabulary.
- Dry-run can validate the run without producing findings or patches.
- Review-only can produce raw findings with evidence but no patch proposals.
- Normal runs can produce deterministic findings, patch proposals, and
  persisted artifacts with stable ordering and provenance.
- Waivers and suppressions can be applied after rule resolution while the raw
  finding remains in history.
- Console output can be rendered as a fixed human-readable report from the
  persisted machine-readable artifact.
- Artifacts can be stored immutably with content-hash-based reuse of source
  derived structures.
- Failure states can be categorized, surfaced in console output, and persisted
  as artifacts.
