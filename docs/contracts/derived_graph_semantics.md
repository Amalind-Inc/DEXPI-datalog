# Derived Graph Semantics Contract

This contract defines the first derived Souffle layer that sits above the
graph-mirrored base fact export.

The derived layer is repo-owned interpretation logic. It is not part of the
persisted export contract.

## Inputs

The derived layer consumes the generic persisted facts from
[Graph-to-Facts Contract](./graph_to_facts.md):

- graph nodes
- graph edges
- generic node attributes
- generic edge attributes

## Responsibilities

This layer owns two jobs:

1. edge-family classification over generic exported graph facts
2. generic graph utility predicates for downstream rule layers

This layer should remain domain-agnostic enough to support more than one rule
family, while still being explicit about stable predicate names.

## Initial predicate surface

The initial documented predicate surface is:

- `composition_edge/3`
- `reference_edge/3`
- `candidate_topology_edge/3`
- `downstream_candidate/2`
- `downstream_composition/2`
- `downstream_reference/2`
- `reachable/2`

These predicates are derived. They are not part of the persisted base export.

## Classification policy

Edge-family classification should be expressed in Souffle over generic facts,
not baked into the exporter.

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
