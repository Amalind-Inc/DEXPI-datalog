from __future__ import annotations

from pydexpi_datalog.qa.evidence_narratives import narrate_reachable_result


def _reachable_result(
    *, complete: bool = True, with_limit: bool = False
) -> dict[str, object]:
    limitations: list[dict[str, object]] = []
    if with_limit:
        limitations.append(
            {
                "code": "retrieval.path_limit",
                "message": "Retrieval stopped at the configured path limit.",
                "limit": 1,
            }
        )
    return {
        "source_id": "equipment-t4750",
        "reachable": [
            {
                "evidence_id": "connection-n1",
                "label": "Unlabeled piping connection from T4750/N1",
                "node_class": "PipingNetworkSegment",
                "category": "piping",
                "direction_status": "inferred",
                "source_id": "pid-001",
                "witness": {
                    "node_ids": ["equipment-t4750", "connection-n1"],
                    "edge_ids": ["edge-n1"],
                    "raw_node_ids": ["raw-t4750", "raw-segment-1"],
                    "raw_edges": [
                        {
                            "source_id": "raw-t4750",
                            "target_id": "raw-segment-1",
                            "edge_key": "sourceItem",
                        }
                    ],
                    "relationships": ["sourceItem"],
                },
            }
        ],
        "coverage": {
            "complete": complete,
            "examined_paths": 1,
            "returned_paths": 1,
            "returned_evidence_objects": 1,
        },
        "limitations": limitations,
    }


def test_reachable_narrative_uses_engineering_claims_and_expandable_provenance() -> (
    None
):
    narrative = narrate_reachable_result(
        source_label="T4750", result=_reachable_result()
    )

    assert narrative["claim"] == {
        "text": "The available trace from T4750 reaches a piping connection.",
        "conclusion_status": "Established",
        "coverage": "Complete",
    }
    assert narrative["relationship_phrases"] == ["a structural connection"]
    assert narrative["entity_labels"] == [
        "T4750",
        "Unlabeled piping connection from T4750/N1",
    ]
    assert narrative["citations"] == ["connection-n1"]
    assert narrative["evidence"][0]["label"] == (
        "Unlabeled piping connection from T4750/N1"
    )
    assert narrative["evidence"][0]["provenance"] == {
        "topology_node_ids": ["equipment-t4750", "connection-n1"],
        "topology_edge_ids": ["edge-n1"],
        "raw_node_ids": ["raw-t4750", "raw-segment-1"],
        "raw_edges": [
            {
                "source_id": "raw-t4750",
                "target_id": "raw-segment-1",
                "edge_key": "sourceItem",
            }
        ],
    }
    assert "node-" not in narrative["claim"]["text"]
    assert "edge-" not in narrative["claim"]["text"]


def test_partial_reachable_narrative_preserves_limitations_without_overclaiming() -> (
    None
):
    narrative = narrate_reachable_result(
        source_label="T4750",
        result=_reachable_result(complete=False, with_limit=True),
    )

    assert narrative["claim"]["conclusion_status"] == "Established"
    assert narrative["claim"]["coverage"] == "Partial"
    assert narrative["limitations"] == [
        {
            "code": "retrieval.path_limit",
            "message": "Retrieval stopped at the configured path limit.",
            "limit": 1,
        }
    ]
    assert "downstream" not in narrative["claim"]["text"].lower()


def test_unavailable_reachable_narrative_is_not_evaluated() -> None:
    narrative = narrate_reachable_result(
        source_label="T4750",
        result={
            "source_id": "equipment-t4750",
            "reachable": [],
            "error": "unknown equipment_id: equipment-t4750",
            "coverage": {"complete": False},
            "limitations": [],
        },
    )

    assert narrative["claim"] == {
        "text": "The structural trace from T4750 was not evaluated.",
        "conclusion_status": "Not evaluated",
        "coverage": "Insufficient",
    }
    assert narrative["entity_labels"] == ["T4750"]
    assert narrative["citations"] == []
    assert narrative["limitations"] == [
        {"code": "retrieval.error", "message": "unknown equipment_id: equipment-t4750"}
    ]
