"""Compact, answer-neutral inspection view over graph-mirrored facts."""

from __future__ import annotations

import json
from collections.abc import Mapping


def build_graph_inspection_index(artifact: Mapping[str, object]) -> str:
    """Render stable node/edge identity fields without deriving an answer."""
    facts = artifact.get("facts")
    if not isinstance(facts, Mapping):
        raise ValueError("graph artifact has no facts object")
    raw_nodes = facts.get("nodes")
    raw_edges = facts.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("graph artifact facts must contain node and edge lists")

    nodes = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise ValueError("graph node fact must be an object")
        attributes = raw.get("attributes")
        if not isinstance(attributes, Mapping):
            attributes = {}
        nodes.append(
            {
                "id": raw.get("node_id"),
                "label": attributes.get("label"),
                "proteus_id": attributes.get("proteusId"),
                "tag_name": attributes.get("tagName"),
            }
        )

    edges = []
    for raw in raw_edges:
        if not isinstance(raw, Mapping):
            raise ValueError("graph edge fact must be an object")
        attributes = raw.get("attributes")
        if not isinstance(attributes, Mapping):
            attributes = {}
        edges.append(
            {
                "source_id": raw.get("source_id"),
                "target_id": raw.get("target_id"),
                "edge_key": raw.get("edge_key"),
                "label": attributes.get("label"),
                "attr_name": attributes.get("attr_name"),
            }
        )

    nodes.sort(key=lambda item: str(item["id"]))
    edges.sort(
        key=lambda item: (
            str(item["source_id"]),
            str(item["target_id"]),
            str(item["edge_key"]),
        )
    )
    return json.dumps(
        {
            "schema_version": 1,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        },
        indent=2,
        sort_keys=True,
    )
