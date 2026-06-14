# Graph-to-Facts Contract

This repository treats `pyDEXPI` as the trusted extraction dependency for v1.
The project-owned contract starts at the exported graph and ends at persisted
base facts.

## Scope

The current contract is defined over `pyDEXPI` 1.2.0 full graph export from
DEXPI 1.3 fixtures. The exporter uses the `GraphLoader` full graph, not an
abstracted process or conceptual graph.

The vendored upstream reference currently pinned for this verifier work is:

- upstream remote: `https://github.com/process-intelligence-research/pyDEXPI.git`
- vendored commit: `83e5a11c4af3635ad12290a4dbe310480eb6d7a3`

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
It does not emit recursive relations, inferred neighborhoods, or rule-specific
predicates.

## Determinism

Artifacts are sorted deterministically:

- nodes by `node_id`
- edges by `source_id`, `target_id`, `edge_key`
- attribute maps by key

This keeps golden outputs diffable across runs.

## Provenance

Each artifact records:

- `source_path`
- `fixture_id`
- `provenance.extractor`
- `provenance.extractor_path`
- `provenance.extractor_version`

This pins the observed upstream graph shape to a concrete `pyDEXPI` build.

## Golden fixtures

The current golden contract fixtures are:

- `fixtures/graph_contract/e03-pump/graph_facts.json`
- `fixtures/graph_contract/e06-pump-hex/graph_facts.json`
- `fixtures/graph_contract/c01-reference-pid/graph_facts.json`
- `fixtures/graph_contract/manifest.json`

These files are the regression surface for future graph-to-facts changes.
