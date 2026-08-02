"""Transform deterministic topology evidence into engineer-facing structure.

This module owns presentation structure, not engineering inference. It only
renames relationships that the topology engine already returned, preserves the
engine's evidence identities, and carries retrieval limitations forward.
"""

from __future__ import annotations

from collections.abc import Mapping

_DIRECT_RELATIONSHIPS = frozenset(
    {"source", "target", "sourceItem", "targetItem", "sourceNode", "targetNode"}
)
_COMPOSITION_RELATIONSHIPS = frozenset({"nodes", "segments", "pipingNetworkSystems"})
_CONNECTOR_RELATIONSHIPS = frozenset(
    {"connector", "connectors", "connectorReference", "connectorReferences"}
)
_CATEGORY_NOUNS = {
    "equipment": "equipment item",
    "nozzle": "nozzle",
    "line": "line",
    "piping": "piping connection",
    "connection": "connection point",
    "structural": "topology object",
    "other": "topology object",
}


def narrate_reachable_result(
    *, source_label: str, result: Mapping[str, object]
) -> dict[str, object]:
    """Build a bounded, claim-linked narrative from deterministic paths.

    The returned dictionary is JSON-compatible because it is intended to be
    included in a read-only tool result. Stable and raw identities appear only
    below each evidence item's ``provenance`` field; the claim text never
    contains graph plumbing or direction that the witness did not establish.
    """

    source = _label(source_label) or "the selected source object"
    reachable = _mapping_items(result.get("reachable"))
    coverage = _mapping(result.get("coverage"))
    complete = bool(coverage.get("complete"))
    limitations = _limitations(result.get("limitations"))
    error = str(result.get("error") or "").strip()

    if error:
        limitations.insert(0, {"code": "retrieval.error", "message": error})
        claim = {
            "text": f"The structural trace from {source} was not evaluated.",
            "conclusion_status": "Not evaluated",
            "coverage": "Insufficient",
        }
    elif reachable:
        claim = {
            "text": _reachable_claim_text(source, reachable),
            "conclusion_status": "Established",
            "coverage": "Complete" if complete else "Partial",
        }
    elif complete:
        claim = {
            "text": (
                f"No additional topology object was reached from {source} "
                "within the evaluated structural scope."
            ),
            "conclusion_status": "Established",
            "coverage": "Complete",
        }
    else:
        claim = {
            "text": (
                f"The available trace from {source} did not establish a "
                "complete reachability result."
            ),
            "conclusion_status": "Not established",
            "coverage": _partial_or_insufficient(coverage, reachable),
        }

    evidence: list[dict[str, object]] = []
    relationship_phrases: list[str] = []
    entity_labels = [source]
    citations: list[str] = []
    for item in reachable:
        evidence_id = _label(item.get("evidence_id"))
        label = _label(item.get("label")) or "Unlabeled topology object"
        phrase = _relationship_phrase(item)
        if phrase not in relationship_phrases:
            relationship_phrases.append(phrase)
        if label not in entity_labels:
            entity_labels.append(label)
        if evidence_id and evidence_id not in citations:
            citations.append(evidence_id)
        evidence.append(
            {
                "evidence_id": evidence_id,
                "label": label,
                "relationship_phrase": phrase,
                "provenance": _provenance(item.get("witness")),
            }
        )

    return {
        "schema_version": 1,
        "claim": claim,
        "relationship_phrases": relationship_phrases,
        "entity_labels": entity_labels,
        "evidence": evidence,
        "limitations": limitations,
        "citations": citations,
    }


def _reachable_claim_text(source: str, reachable: list[Mapping[str, object]]) -> str:
    categories = {_label(item.get("category")) for item in reachable}
    if len(reachable) == 1:
        category = _CATEGORY_NOUNS.get(next(iter(categories)), "topology object")
        article = "an" if category[0].lower() in "aeiou" else "a"
        return f"The available trace from {source} reaches {article} {category}."
    if len(categories) == 1:
        category = _CATEGORY_NOUNS.get(next(iter(categories)), "topology object")
        return (
            f"The available trace from {source} reaches {len(reachable)} {category}s."
        )
    return (
        f"The available trace from {source} reaches "
        f"{len(reachable)} connected source objects."
    )


def _relationship_phrase(item: Mapping[str, object]) -> str:
    witness = _mapping(item.get("witness"))
    relationships = {
        str(value) for value in _strings(witness.get("relationships")) if str(value)
    }
    direction_status = _label(item.get("direction_status"))
    if direction_status == "explicit" and relationships <= _DIRECT_RELATIONSHIPS:
        return "an explicit process-flow connection"
    if relationships & _COMPOSITION_RELATIONSHIPS:
        return "a topology composition relationship"
    if relationships & _CONNECTOR_RELATIONSHIPS:
        return "a connector reference"
    return "a structural connection"


def _partial_or_insufficient(
    coverage: Mapping[str, object], reachable: list[Mapping[str, object]]
) -> str:
    if reachable or any(
        key in coverage for key in ("examined_paths", "examined_rows", "returned_paths")
    ):
        return "Partial"
    return "Insufficient"


def _provenance(raw_witness: object) -> dict[str, object]:
    witness = _mapping(raw_witness)
    return {
        "topology_node_ids": _strings(witness.get("node_ids")),
        "topology_edge_ids": _strings(witness.get("edge_ids")),
        "raw_node_ids": _strings(witness.get("raw_node_ids")),
        "raw_edges": [
            dict(edge)
            for edge in witness.get("raw_edges", [])
            if isinstance(edge, Mapping)
        ],
    }


def _limitations(raw_limitations: object) -> list[dict[str, object]]:
    if not isinstance(raw_limitations, list):
        return []
    return [dict(item) for item in raw_limitations if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _label(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _join_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"
