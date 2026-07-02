"""Derive engineer-facing display names for topology objects.

The raw DEXPI graph identifies objects by internal class (e.g. "PipingNode") and
opaque ids. Process engineers reference:
- equipment by tag (P-4713, H-1009),
- nozzles by sub-tag qualified by their equipment (P-4713 / N-1),
- piping by line number (Line 47132).

This module turns the raw graph facts into those human identifiers, using the
composition hierarchy (owner -> owned) to qualify and inherit names.
"""
from __future__ import annotations

import re

# Composition edges run from owner to owned (equipment -> nozzle -> piping node).
_COMPOSITION_LABEL = "composition"

_STRUCTURAL_CLASSES = frozenset({"ConceptualModel"})


def derive_display_names(
    fact_nodes: list[dict[str, object]],
    fact_edges: list[dict[str, object]],
) -> dict[str, dict[str, str]]:
    """Return {raw_node_id: {display_name, class_name, category, description}}."""
    attrs: dict[str, dict[str, object]] = {
        str(node["node_id"]): dict(node["attributes"]) for node in fact_nodes
    }
    parent_of = _build_parent_map(fact_edges, attrs)

    resolved: dict[str, dict[str, str]] = {}
    resolving: set[str] = set()

    def display_for(raw_id: str) -> str:
        if raw_id in resolved:
            return resolved[raw_id]["display_name"]
        if raw_id in resolving or raw_id not in attrs:
            # Cycle guard or dangling reference: fall back to a class name.
            return _friendly_class(str(attrs.get(raw_id, {}).get("label", raw_id)))
        resolving.add(raw_id)
        a = attrs[raw_id]
        label = str(a.get("label", raw_id))
        name = _compute_display(raw_id, a, label, parent_of, display_for)
        resolving.discard(raw_id)
        resolved[raw_id] = {
            "display_name": name,
            "class_name": _friendly_class(label),
            "category": _category(a, label),
            "description": str(a.get("label_description", "")),
        }
        return name

    for raw_id in attrs:
        display_for(raw_id)
    return resolved


def _build_parent_map(
    fact_edges: list[dict[str, object]], attrs: dict[str, dict[str, object]]
) -> dict[str, str]:
    parent_of: dict[str, str] = {}
    for edge in fact_edges:
        edge_attrs = edge.get("attributes", {})
        if edge_attrs.get("label") != _COMPOSITION_LABEL:
            continue
        source = str(edge["source_id"])
        target = str(edge["target_id"])
        # First composition owner wins; keep deterministic.
        if target in attrs and target not in parent_of:
            parent_of[target] = source
    return parent_of


def _compute_display(
    raw_id: str,
    a: dict[str, object],
    label: str,
    parent_of: dict[str, str],
    display_for,
) -> str:
    tag_name = a.get("tagName")
    if tag_name:
        return str(tag_name)

    line_number = a.get("lineNumber")
    if line_number:
        return f"Line {line_number}"

    sub_tag = a.get("subTagName")
    if sub_tag:
        parent = parent_of.get(raw_id)
        if parent:
            return f"{display_for(parent)} / {sub_tag}"
        return str(sub_tag)

    if label == "PipingNode":
        parent = parent_of.get(raw_id)
        if parent:
            return f"{display_for(parent)} (connection)"
        return "Piping connection"

    if label == "PipingNetworkSegment":
        parent = parent_of.get(raw_id)
        if parent:
            return f"{display_for(parent)} (segment)"
        return "Piping segment"

    return _friendly_class(label)


def _category(a: dict[str, object], label: str) -> str:
    if a.get("tagName"):
        return "equipment"
    if a.get("subTagName"):
        return "nozzle"
    if a.get("lineNumber"):
        return "line"
    if label == "PipingNode":
        return "connection"
    if label in {"Pipe", "PipingNetworkSegment", "PipingNetworkSystem"}:
        return "piping"
    if label in _STRUCTURAL_CLASSES:
        return "structural"
    return "other"


def _friendly_class(label: str) -> str:
    """Turn a CamelCase class label into spaced words: CentrifugalPump -> Centrifugal Pump."""
    if not label:
        return ""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", label)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced
