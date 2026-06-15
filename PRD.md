## Problem Statement

Process engineering teams need a deterministic substrate for logical
programming over DEXPI 1.3 P&IDs before they can trust richer operator-facing
verification workflows.

The current repository already has useful scaffolding, a graph-mirrored export
seed, and an initial tracer-bullet verifier. What it does not yet have is a
fully explicit contract for turning the supported DEXPI 1.3 fixture corpus into
graph-mirrored facts and then deriving reusable Souffle semantics from those
facts. Without that substrate, later rule work risks drifting into ad hoc
predicate design, fixture-specific shortcuts, or AI-generated rules without a
stable deterministic execution boundary.

## Solution

Build the next verifier substrate slice around DEXPI 1.3 graph-mirrored facts
and derived Souffle graph semantics.

The solution should treat `pyDEXPI` as the trusted extraction dependency for
DEXPI 1.3 XML-to-graph conversion, persist a verbose and generic canonical base
fact layer over the `pyDEXPI` full graph, and add a hand-authored generic graph
utility layer plus repo-owned edge-family classification policy in Souffle.

This slice should prove the substrate over the parseable DEXPI 1.3 fixture
corpus, document the contract sharply, and establish the behavioral test seams
that later pump-specific rules, rule packs, and AI-assisted rule synthesis can
rely on.

## User Stories

1. As a process engineer, I want DEXPI 1.3 to be the explicit authoritative input contract, so that the repository does not imply support for a different semantic ingestion model than the code actually uses.
2. As a maintainer, I want `pyDEXPI` to be treated as the trusted DEXPI 1.3 XML-to-graph extraction dependency, so that the project boundary between extraction and interpretation stays explicit.
3. As a rules author, I want the canonical base fact layer to mirror the `pyDEXPI` full graph, so that every downstream rule begins from a reproducible graph substrate.
4. As a rules author, I want the base export to remain intentionally verbose and generic, so that I do not lose evidence through premature schema curation.
5. As a maintainer, I want one persisted fact per extracted node, one per extracted edge, and one per attached attribute, so that the fact grain remains stable and auditable.
6. As a maintainer, I want previously unseen upstream attributes to survive export automatically, so that new DEXPI 1.3 fixture shapes do not break the substrate.
7. As a rules author, I want the base export to avoid convenience predicates such as `pump/1`, so that interpretation stays out of the persisted contract.
8. As a maintainer, I want the contract to be defined over the parseable DEXPI 1.3 fixture corpus, so that the substrate proves itself against real fixture breadth rather than one narrow example.
9. As a reviewer, I want the checked-in golden fixtures to be clearly documented as a seed set rather than the full contract boundary, so that future work does not mistake current goldens for full coverage.
10. As a rules author, I want the first derived Souffle layer to be generic and reusable, so that later rule families can build on it without rewriting graph logic.
11. As a rules author, I want reusable edge-family predicates such as `composition_edge/3` and `reference_edge/3`, so that downstream rules do not repeatedly join raw edge attributes by hand.
12. As a rules author, I want a cautious `candidate_topology_edge/3` predicate, so that topology traversal can begin before the project commits to a stronger process-topology interpretation.
13. As a rules author, I want family-specific direct adjacency helpers, so that each rule can choose the correct traversal semantics explicitly.
14. As a rules author, I want a simple recursive `reachable/2` predicate over candidate topology edges, so that I can ask whether something is downstream without building full path provenance first.
15. As a maintainer, I want the first utility layer to stay small and explicit, so that it does not accumulate broad helper predicates before real rules require them.
16. As a maintainer, I want the edge-family classification policy to live in Souffle, so that interpretation can evolve without changing the persisted export format.
17. As a reviewer, I want the derived graph semantics contract to name the initial predicate surface explicitly, so that the next implementation slice cannot drift into vague “some utilities later” language.
18. As a process engineer, I want verification to be documented as downstream of graph export plus derived semantics, so that the architecture is understood as layered rather than verifier-first.
19. As a maintainer, I want the contract docs to state clearly that convenience predicates and domain predicates belong in derived Souffle layers, so that no one silently moves interpretation into the exporter.
20. As a maintainer, I want outdated `DEXPI 2.0 semantic IR` language removed from the active glossary and contract docs, so that the written architecture matches the implemented boundary.
21. As a rules author, I want the first validation seam to be stable graph export over the DEXPI 1.3 corpus, so that later logic failures can be isolated from extraction/export failures.
22. As a rules author, I want the second validation seam to be focused tests over representative fixtures such as `E03`, `E06`, and `C01`, so that recursive and classified predicates can be checked against real graph shapes.
23. As a maintainer, I want synthetic examples to remain available for later isolated rule verification, so that future rule generation can be tested behaviorally and not only on noisy corpus fixtures.
24. As a future operator, I want later trusted rules to execute deterministically over the fact layer instead of relying on ad hoc AI answers, so that verification remains reproducible and auditable.
25. As a future AI-assisted rules author, I want a stable graph-mirrored substrate and reusable graph utilities, so that generated rules have a deterministic target surface to compile against.
26. As a compliance engineer, I want rule packs to remain distinct from policy source documents, so that natural-language standards can later synthesize candidate rules without being confused for executable logic.
27. As a reviewer, I want AI-generated rules to be treated as candidates that require behavioral examples, so that trust comes from deterministic execution rather than raw Datalog readability.
28. As a maintainer, I want the next slice to defer policy-document-to-rule-pack synthesis, so that the foundational substrate work is not swallowed by a much larger AI problem.
29. As a maintainer, I want the repo PRD and Beads issue record to describe the same substrate plan, so that future contributors do not read contradictory planning artifacts.
30. As an engineer extending the verifier later, I want explicit derived graph semantics contracts in the docs, so that new rule families can reuse the same vocabulary and testing seams.

## Implementation Decisions

- The authoritative input contract for this slice is DEXPI 1.3 only.
- `pyDEXPI` is the trusted extraction dependency for XML-to-graph conversion; this repository owns graph-to-facts export and Souffle-derived interpretation above that export.
- The canonical persisted layer is a graph-mirrored base fact layer over the `pyDEXPI` full graph rather than a raw XML fact tree or an early domain-curated schema.
- The canonical base fact layer is intentionally verbose and generic. It should preserve extracted nodes, extracted edges, and attached attributes without introducing rule-specific predicates.
- Unknown or newly observed upstream attributes should survive export automatically through generic attribute facts rather than causing schema failures.
- The canonical base layer should persist only the `pyDEXPI` full graph for now. Explicit raw XML containment facts are deferred unless a concrete future rule proves they are needed.
- The intended regression surface for the substrate is the parseable DEXPI 1.3 fixture corpus, not only the current `E03`, `E06`, and `C01` golden seed set.
- The first derived Souffle layer should be hand-authored rather than generated from observed graph schema.
- The repo-owned classification policy should live in Souffle rather than in exporter code, so classified semantics can evolve without re-exporting the canonical fact layer.
- The initial derived predicate surface should be explicit: `composition_edge/3`, `reference_edge/3`, `candidate_topology_edge/3`, `downstream_candidate/2`, `downstream_composition/2`, `downstream_reference/2`, and `reachable/2`.
- `candidate_topology_edge/3` should be intentionally conservative rather than claiming that topology traversal is already fully trusted in every case.
- Direct adjacency helpers should stay family-specific. Broader union predicates such as `downstream/2` should be introduced only when a real rule or operator-facing query needs them.
- The first recursive utility should be `reachable/2` over `candidate_topology_edge/3`; ordered path reconstruction and full path provenance are deferred.
- Pump discharge YAML rules should sit above the generic base fact layer and derived graph semantics layer rather than embedding graph semantics themselves.
- Verification commands should be documented and treated as consumers of the export-plus-derived-semantics substrate, not as the primary architectural center.
- The rule trust model for later AI-assisted work should be behavioral: candidate rules become trustworthy only after deterministic execution against positive and negative examples.
- Single rules and rule packs remain distinct units. Individual rules are the unit of behavioral debugging; rule packs are the unit of versioned promotion and deployment.
- Policy source documents, rule packs, and rule-pack synthesis are distinct concepts and should remain separate in the glossary and contract docs.

## Testing Decisions

- Good tests should assert external behavior and stable contracts, not implementation details or private helper structure.
- The highest seam for this slice is the `export-facts` behavior over the parseable DEXPI 1.3 fixture corpus. Tests at this seam should verify deterministic persisted graph-mirrored facts, provenance, and automatic preservation of observed attributes.
- A second high seam should cover the derived graph semantics layer on representative fixtures such as `E03`, `E06`, and `C01`, validating classified edge families, family-specific downstream helpers, and recursive `reachable/2`.
- Later synthetic examples should be used for isolated rule-shape verification, but the current substrate slice should prefer real DEXPI 1.3 fixtures wherever possible.
- Tests should confirm that the base export does not emit convenience predicates or domain predicates in the persisted artifact contract.
- Tests should verify that the current checked-in golden fixtures remain a seed set and that broader corpus coverage can be expanded without redefining the base contract.
- Tests should confirm that the derived classification policy lives above the persisted export and can change without changing the base fact artifact shape.
- Documentation-facing tests or fixture assertions should continue to use the repo’s existing black-box style around CLI commands and persisted artifacts rather than internal function mocks.
- Prior art already exists in the repository for export-facts CLI tests, checked-in golden graph facts, compile-rule CLI tests, and verifier-suite artifact tests. The new tests should extend those existing seams instead of inventing lower-level unit seams.
- Future AI-assisted rule verification should rely on positive and negative examples evaluated by the deterministic engine, not human review of raw Datalog syntax.

## Out of Scope

- DEXPI 2.0 as an active ingestion contract.
- A raw XML fact layer or XML-tree-first substrate.
- Automatic generation of domain predicates from unseen graph shapes.
- Full path reconstruction or ordered path evidence in the first derived utility slice.
- Pump-specific or rule-specific domain predicates in the persisted base export.
- DEXPI 1.2 as part of the current canonical substrate contract.
- Policy-document-to-rule-pack synthesis.
- Operator-facing dropdown UX for rule or rule-pack selection.
- Trusting AI to answer operator verification questions directly without deterministic execution.
- Human approval workflows for AI-generated rules beyond the defined behavioral-verification model.

## Further Notes

- The most important architectural protection in this slice is the boundary between generic persisted facts and derived Souffle interpretation.
- The base fact layer should be allowed to be verbose if that preserves reproducibility and future extensibility.
- The current checked-in documentation cleanup is part of the work because stale contract language would otherwise undermine the implementation slice.
- This PRD intentionally narrows the next step to substrate work. Richer operator rules, compliance rule packs, and AI-assisted synthesis remain downstream consumers of this layer rather than part of it.
