# Drawing bundle: e06-trap-drawing

This directory is a self-contained, read-only input for an agentic sandbox.

## Files

- `drawing.xml`: the original DEXPI source drawing.
- `graph_facts.json`: the canonical base fact layer extracted from `drawing.xml`.
- `graph.json`: a NetworkX node-link JSON export of those same graph facts.
- `README.md`: this orientation and witness-citation guide.

## Witness IDs

- Cite a node with its `node_id` from `graph_facts.json` under `facts.nodes`.
- Cite an edge with its `source_id`, `target_id`, and `edge_key` under `facts.edges`.
- The node and edge IDs in `graph.json` are the same IDs as in `graph_facts.json`.

## Extraction provenance

`graph_facts.json` was produced by pyDEXPI 1.2.0.

Graph size: 18 nodes and 21 edges.
