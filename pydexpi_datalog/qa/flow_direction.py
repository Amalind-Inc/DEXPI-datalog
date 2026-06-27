"""Pure helpers for reviewing inferred flow direction in grounded QA.

Direction *basis* (how we know the direction) is represented separately from
the user's *review status* (their judgement after seeing the witness):

- basis: "explicit" | "inferred" | "unknown"
- review_status: "pending" | "confirmed" | "reversed" | "unknown"
"""
from __future__ import annotations

import hashlib
import json

# DEXPI relationships that carry an explicit flow orientation (source -> target).
DIRECTED_RELATIONSHIPS = frozenset(
    {"source", "target", "sourceItem", "targetItem", "sourceNode", "targetNode"}
)

_DOWNSTREAM_TOKENS = ("downstream", "discharge", "feeds", "flows to", "flow to", "outlet")
_UPSTREAM_TOKENS = ("upstream", "feeds from", "supplied by", "inlet", "suction")


def classify_edge_direction_basis(relationship: str) -> str:
    return "explicit" if relationship in DIRECTED_RELATIONSHIPS else "inferred"


def classify_path_direction_basis(relationships: list[str]) -> str:
    """A path is explicit only if every edge is explicitly directional; it is
    unknown when there are no edges to orient; otherwise it is inferred."""
    if not relationships:
        return "unknown"
    if all(classify_edge_direction_basis(rel) == "explicit" for rel in relationships):
        return "explicit"
    return "inferred"


def detect_directed_intent(question: str) -> str | None:
    """Return 'downstream'/'upstream' when the question asks about flow direction."""
    normalized = question.lower()
    if any(token in normalized for token in _UPSTREAM_TOKENS):
        return "upstream"
    if any(token in normalized for token in _DOWNSTREAM_TOKENS):
        return "downstream"
    return None


def opposite_direction(direction: str) -> str:
    if direction == "downstream":
        return "upstream"
    if direction == "upstream":
        return "downstream"
    return direction


def evaluation_boundary(direction: str) -> str:
    return f"directed_reachable:{direction}"


def direction_annotation_key(
    *,
    source_id: str | None,
    evaluation_boundary: str,
    node_ids: list[str],
    edge_ids: list[str],
) -> str:
    payload = {
        "source_id": source_id,
        "evaluation_boundary": evaluation_boundary,
        "node_ids": list(node_ids),
        "edge_ids": list(edge_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"direction-{digest}"


def effective_direction(*, proposed_direction: str, review_status: str) -> str:
    if review_status == "confirmed":
        return proposed_direction
    if review_status == "reversed":
        return opposite_direction(proposed_direction)
    return "unknown"
