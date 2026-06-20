# Graph-to-Facts Contract

This repository treats `pyDEXPI` as the trusted extraction dependency for the
current contract. `pyDEXPI` owns DEXPI 1.3 XML-to-graph extraction. This
repository owns graph-to-facts export and the Souffle-derived interpretation
layers above that export.

## Scope

The current contract is defined over `pyDEXPI` 1.2.0 full graph export from
DEXPI 1.3 fixtures. The exporter uses the `GraphLoader` full graph, not an
abstracted process graph, conceptual graph, or raw XML tree.

The vendored upstream reference currently pinned for this verifier work is:

- upstream remote: `https://github.com/process-intelligence-research/pyDEXPI.git`
- vendored commit: `83e5a11c4af3635ad12290a4dbe310480eb6d7a3`

## Contract boundary

The persisted base fact layer is intentionally verbose and generic.

- It mirrors the `pyDEXPI` full graph one node, one edge, and one attribute at
  a time.
- It preserves previously unseen upstream attributes automatically.
- It does not emit convenience predicates or domain predicates such as
  `pump/1`, `composition_edge/3`, or `discharge_nozzle/2`.

Convenience predicates and domain predicates belong in derived Souffle layers,
not in the persisted export.

## Base fact vocabulary

The persisted artifact in `graph_facts.json` is intentionally close to the
`pyDEXPI` graph:

- `facts.nodes[]`
  - one entry per graph node
  - preserves the graph node id as `node_id`
  - preserves upstream node attributes under `attributes`
- `facts.edges[]`
  - one entry per graph edge
  - preserves `source_id`, `target_id`, and `edge_key`
  - preserves upstream edge attributes under `attributes`

This is a graph-mirrored contract, not a derived verifier-language contract.
It does not emit recursive relations, inferred neighborhoods, classified edge
families, or rule-specific predicates.

## Determinism

Artifacts are sorted deterministically:

- nodes by `node_id`
- edges by `source_id`, `target_id`, `edge_key`
- attribute maps by key

This keeps exports diffable across runs.

## Provenance

Each artifact records:

- `source_path`
- `fixture_id`
- `provenance.extractor`
- `provenance.extractor_path`
- `provenance.extractor_version`

This pins the observed upstream graph shape to a concrete `pyDEXPI` build.

## Regression surface

The intended regression surface for this contract is the parseable DEXPI 1.3
fixture corpus in `TrainingTestCases/dexpi 1.3/example pids`.

The current checked-in golden seed set is:

- `testdata/graph_contract/e03-pump/graph_facts.json`
- `testdata/graph_contract/e06-pump-hex/graph_facts.json`
- `testdata/graph_contract/c01-reference-pid/graph_facts.json`
- `testdata/graph_contract/manifest.json`

Those goldens are a narrow seed set, not the full intended contract boundary.

## Related contracts

- [Derived Graph Semantics Contract](./derived_graph_semantics.md)
- [Minimal Pump Discharge Rule Schema](./minimal_pump_discharge_rule_schema.md)
