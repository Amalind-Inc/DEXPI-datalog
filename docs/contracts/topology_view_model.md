# Topology View Model Contract

The topology view model is the compact process-topology payload returned after a
single-file review session reaches `ready`.

It is a web-facing contract. The UI should not parse `graph_facts.json`,
`graph_facts.dl`, or `derived_graph_semantics.dl` directly to render the default
process-topology view.

## Shape

The payload uses `schema_version: topology-view.v1` and contains:

- `session_id`: the review session that produced the model.
- `source_path`: the uploaded DEXPI source path used for local provenance.
- `nodes`: curated topology objects with stable `id` values.
- `edges`: curated process-topology relationships with stable `id` values.
- `evidence_map`: a resolver from every topology node and edge ID to the
  canonical source fact it came from.
- `evidence_highlight`: the current highlight payload, with `source_scope_ids`,
  `matched_object_ids`, and `paths`.

## IDs

Topology IDs are stable web-facing IDs derived from canonical fact attributes.
They are not raw pyDEXPI graph IDs.

Every node and edge carries:

- `id`: the stable topology ID used by the UI, source scope, and evidence
  highlighting.
- `canonical_fact_id`: the same stable ID for v1 callers that need a generic
  canonical identifier.

Nodes also carry `source_graph_node_id`. Edges carry `source_graph_edge`. Those
fields are provenance back to the canonical base fact layer, not the UI's public
selection IDs.

## Evidence Resolution

`evidence_map` must contain exactly one entry for every topology node and edge
ID. A resolver entry has:

- `kind`: `node` or `edge`.
- `topology_id`: the stable ID being resolved.
- `canonical_fact`: the source fact reference.

Node resolver entries point to:

```json
{"fact_type": "node", "node_id": "<source graph node id>"}
```

Edge resolver entries point to:

```json
{
  "fact_type": "edge",
  "source_id": "<source graph node id>",
  "target_id": "<target graph node id>",
  "edge_key": "<source graph edge key>"
}
```

## Evidence Highlighting

Evidence highlights use topology IDs only:

```json
{
  "source_scope_ids": ["node-or-edge-id"],
  "matched_object_ids": ["node-or-edge-id"],
  "paths": [
    {
      "id": "path-1",
      "node_ids": ["node-id"],
      "edge_ids": ["edge-id"]
    }
  ]
}
```

All IDs in a highlight payload must exist in `evidence_map`. Unknown IDs are
invalid because the UI would not be able to trace them to source facts.

## Curated View Boundary

The default topology view is not a raw graph dump. Edges are limited to curated
process-topology relationships from the derived graph/topology vocabulary, such
as connection, connector reference, piping-network-system, source, and target
relationships.
