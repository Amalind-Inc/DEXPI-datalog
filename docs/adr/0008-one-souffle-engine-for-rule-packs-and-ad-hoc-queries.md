# One Souffle Engine for Rule Packs and Ad-Hoc Queries

Both trusted rule-pack evaluation and the QA chat's ad-hoc generated-Datalog
capability will execute against one real `souffle` engine, over the same
`graph_topology_semantics.dl`/`graph_facts_schema.dl` EDB/IDB schema, instead
of two separate execution paths. As of this decision, neither path actually
runs Souffle: the bundled `pump_discharge_check_valve` rule is hand-written
Python graph traversal labeled `"language": "python_traversal"`, and
`propose_temporary_datalog`'s executor is a two-shape regex shim that
silently returns no evidence for anything beyond its two recognized query
shapes. The only real `souffle` invocation anywhere in the repo today is a
narrow source-resolution lookup in `source_selection.py`. A prior session
handoff claiming rule-pack verification already runs real recursive Datalog
was incorrect and should not be treated as prior art.

The two paths remain separate trust tiers on top of the shared engine, not
merged into one permission model: repository-bundled rule packs run
immediately with full EDB+IDB access (maintainer-reviewed, per
`bundled rule-pack trust`), while model-generated ad-hoc queries stay behind
the mandatory `generated-Datalog confirmation gate` regardless of whether the
query is read-only, and receive a narrower dynamically-derived predicate
contract (the generic topology-semantics layer plus the IDB predicates of
whichever rule pack(s) are loaded in the session, read-only). Rejected: a
read-only exception to the confirmation gate — this was the original
proposal but contradicts the PRD's actual trust axis, which is
trust-of-author (reviewed vs. unreviewed logic), not read/write.

Schema extension: a typed numeric-attribute predicate (e.g.
`node_attribute_number(id, attr_name, attr_value:number)`, derived from the
existing symbol-typed `node_attribute` via `to_number()`) is added so rules
can compare source-provided numeric values against thresholds. This does not
extend to calculations requiring external formulas, correlations, or physical
constants not present in the source graph — those remain out of scope and
must surface as `source_data_unavailable` rather than being computed inside a
"rule."

Consequence: existing rule-pack tests (`test_bundled_rule_pack.py`) assert on
the `evaluate_bundled_rule` outcome/evidence contract, not on Python-traversal
internals, so they serve as regression coverage for the Souffle rewrite
rather than needing separate migration. `grounded_qa_harness`'s intent
classifier must be wired to actually raise `needs_datalog_confirmation` and
pause via the existing `TurnLifecycleStore` mechanism for
`propose_temporary_datalog` — that pause/resume/confirmation-card
infrastructure already exists (built for a different, non-conversational
Datalog flow) and is being reused, not rebuilt.
