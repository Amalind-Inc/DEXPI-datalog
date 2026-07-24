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
`bundled rule-pack trust`), while model-generated ad-hoc queries receive a
narrower dynamically-derived predicate contract (the generic
topology-semantics layer plus the IDB predicates of whichever rule pack(s)
are loaded in the session, read-only) and execute only after backend
mechanical safety and layered faithfulness validation. **Superseded by
ADR 0009 / cutover 3qo.9.9:** temporary read-only generated queries no longer
pause behind a generated-Datalog confirmation gate; confirmation remains only
for reusable-rule promotion and unrelated human-review surfaces such as
inferred direction review.

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
rather than needing separate migration. The grounded-QA harness follows the
accepted model-driven restricted-harness contract (ADR 0003 / 0012): the model
plans among backend-owned capabilities, and validated temporary Datalog
executes automatically without a read-only confirmation pause.
