"""Behavioral contracts for flow-direction review helpers (37x.22.18)."""
from __future__ import annotations

from pydexpi_datalog.qa.flow_direction import (
    classify_edge_direction_basis,
    classify_path_direction_basis,
    detect_directed_intent,
    direction_annotation_key,
    effective_direction,
    evaluation_boundary,
    opposite_direction,
)


def test_directed_dexpi_relationships_are_explicit():
    assert classify_edge_direction_basis("sourceItem") == "explicit"
    assert classify_edge_direction_basis("targetItem") == "explicit"


def test_structural_composition_relationships_are_inferred():
    assert classify_edge_direction_basis("nodes") == "inferred"
    assert classify_edge_direction_basis("connections") == "inferred"


def test_path_is_explicit_only_when_every_edge_is_explicit():
    assert classify_path_direction_basis(["sourceItem", "targetItem"]) == "explicit"


def test_path_with_any_structural_edge_is_inferred():
    assert classify_path_direction_basis(["sourceItem", "nodes"]) == "inferred"
    assert classify_path_direction_basis(["connections"]) == "inferred"


def test_path_with_no_edges_is_unknown():
    assert classify_path_direction_basis([]) == "unknown"


def test_detect_directed_intent():
    assert detect_directed_intent("What is downstream of P-101?") == "downstream"
    assert detect_directed_intent("What discharges from the pump?") == "downstream"
    assert detect_directed_intent("What is upstream of V-102?") == "upstream"
    assert detect_directed_intent("What feeds from the tank?") == "upstream"
    assert detect_directed_intent("What is connected to the nozzle?") is None


def test_opposite_direction():
    assert opposite_direction("downstream") == "upstream"
    assert opposite_direction("upstream") == "downstream"
    assert opposite_direction("unknown") == "unknown"


def test_effective_direction_reflects_review_status():
    assert (
        effective_direction(proposed_direction="downstream", review_status="confirmed")
        == "downstream"
    )
    assert (
        effective_direction(proposed_direction="downstream", review_status="reversed")
        == "upstream"
    )
    assert (
        effective_direction(proposed_direction="downstream", review_status="unknown")
        == "unknown"
    )


def test_annotation_key_is_stable_for_same_inputs():
    key_a = direction_annotation_key(
        source_id="source-1",
        evaluation_boundary=evaluation_boundary("downstream"),
        node_ids=["n1", "n2"],
        edge_ids=["e1"],
    )
    key_b = direction_annotation_key(
        source_id="source-1",
        evaluation_boundary=evaluation_boundary("downstream"),
        node_ids=["n1", "n2"],
        edge_ids=["e1"],
    )
    assert key_a == key_b


def test_annotation_key_changes_with_source_path_or_boundary():
    base = dict(
        source_id="source-1",
        evaluation_boundary=evaluation_boundary("downstream"),
        node_ids=["n1", "n2"],
        edge_ids=["e1"],
    )
    base_key = direction_annotation_key(**base)

    # Different source.
    assert direction_annotation_key(**{**base, "source_id": "source-2"}) != base_key
    # Different evaluation boundary (direction).
    assert (
        direction_annotation_key(
            **{**base, "evaluation_boundary": evaluation_boundary("upstream")}
        )
        != base_key
    )
    # Different path.
    assert direction_annotation_key(**{**base, "node_ids": ["n1", "n3"]}) != base_key
    assert direction_annotation_key(**{**base, "edge_ids": ["e2"]}) != base_key
