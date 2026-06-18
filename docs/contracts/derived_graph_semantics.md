# Derived Graph Semantics Contract

This contract defines the first derived Souffle layer that sits above the
graph-mirrored base fact export.

The derived layer is repo-owned interpretation logic. It is not part of the
persisted export contract. Python emits generated Datalog EDB from
`graph_facts.json`; reusable graph topology semantics live as Datalog IDB in
`pydexpi_datalog/datalog/idb/graph_topology_semantics.dl`.

## Inputs

The derived layer consumes the generic persisted facts from
[Graph-to-Facts Contract](./graph_to_facts.md):

- graph nodes
- graph edges
- generic node attributes
- generic edge attributes

`derive-graph-semantics` writes two generated artifacts for each fixture:

- `graph_facts.dl`: generated EDB facts over graph objects, graph attributes,
  graph edges, and graph edge attributes
- `derived_graph_semantics.dl`: combined executable Datalog assembled from the
  generated EDB plus the reusable graph topology IDB

## Responsibilities

This layer owns three jobs:

1. object identity and label exposure for deterministic query output
2. edge-family classification over generated EDB facts
3. graph topology IDB predicates for downstream rule layers

This layer should remain domain-agnostic enough to support more than one rule
family, while still being explicit about stable predicate names.

## Initial predicate surface

The initial documented predicate surface is:

- `node/1`
- `node_label/2`
- `node_tag/2`
- `node_proteus_id/2`
- `composition_edge/3`
- `reference_edge/3`
- `candidate_topology_edge/3`
- `downstream_candidate/2`
- `downstream_composition/2`
- `downstream_reference/2`
- `direct_process_connection/2`
- `reachable/2`

These predicates are derived. They are not part of the persisted base export.

`node/1` exposes graph object identity directly in the Datalog layer.
`node_label/2` exposes the graph object's DEXPI class label, when the generic
node attributes include a `label` value.
`node_tag/2` exposes a human-readable equipment tag, when the generic node
attributes include a `tagName` value. `node_proteus_id/2` exposes the source
Proteus identifier, when the generic node attributes include a `proteusId`
value. These aliases are for selection and display; graph joins should continue
to use `node/1` identities.

## Classification policy

Edge-family classification should be expressed in Souffle IDB over generated EDB
facts, not baked into the exporter.

The first policy should derive:

- `composition_edge/3` from structural edge evidence
- `reference_edge/3` from cross-reference edge evidence
- `candidate_topology_edge/3` from cautious topology-carrying evidence

`candidate_topology_edge/3` is intentionally conservative. It does not claim
that every such edge is already fully trusted process-topology traversal.

## Utility policy

The first utility layer should favor explicit families over one overly broad
union predicate.

- `downstream_candidate/2` should be defined from
  `candidate_topology_edge/3`
- `downstream_composition/2` should be defined from `composition_edge/3`
- `downstream_reference/2` should be defined from `reference_edge/3`
- `direct_process_connection/2` is an experimental process-facing predicate
  derived only from direct `sourceItem` and `targetItem` references. It is useful
  for comparison queries, but is not yet trusted process-flow semantics.
- `reachable/2` should initially compute recursive reachability over
  `candidate_topology_edge/3`

If a broader union predicate such as `downstream/2` is later needed, it should
be introduced only when a real rule or operator-facing query requires it.

## Non-goals for this slice

This contract does not yet include:

- path reconstruction with ordered evidence
- rule-specific pump predicates such as `discharge_nozzle/2`
- exporter-side classified facts
- automatic generation of domain predicates from unseen graph shapes

Those concerns belong to later slices above this layer.
