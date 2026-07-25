"""Behavior tests for the harder controlled compliance slice (rmso.7).

The slice exists to stress multi-hop deduction and exhaustive enumeration a
reader cannot shortcut, with size-matched small/large drawing variants and a
permission/defeasible negative control that expects abstention.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.contract import (
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
)
from pydexpi_datalog.benchmark.dataset import (
    CATEGORY_COMPLIANCE_UNIVERSAL,
    SLICE_HAND_AUTHORED,
    load_question_manifest,
)
from pydexpi_datalog.benchmark.hand_authored import (
    derive_ground_truth,
    verify_hand_authored_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "testdata" / "benchmark" / "harder_questions_manifest.json"


# --- oracle vocabulary: the new multi-hop and control operations ---------

CHAIN_GRAPH = {
    "facts": {
        "nodes": [
            {"node_id": "pump-1", "attributes": {"label": "Pump"}},
            {"node_id": "pipe-1", "attributes": {"label": "Pipe"}},
            {"node_id": "tank-1", "attributes": {"label": "Tank"}},
            {"node_id": "tank-2", "attributes": {"label": "Tank"}},
        ],
        "edges": [
            {
                "source_id": "pump-1",
                "target_id": "pipe-1",
                "attributes": {"label": "reference", "attr_name": "targetItem"},
            },
            {
                "source_id": "pipe-1",
                "target_id": "tank-1",
                "attributes": {"label": "reference", "attr_name": "targetItem"},
            },
        ],
    }
}


def test_not_reachable_from_walks_multi_hop_forward_paths() -> None:
    truth = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "not_reachable_from",
            "node": {"label": "Tank"},
            "source_node": {"label": "Pump"},
        },
    )

    # tank-1 is two hops downstream of the pump; tank-2 is disconnected.
    assert truth.verdict == VERDICT_VIOLATION_FOUND
    assert truth.witness_ids == ("tank-2",)


def test_not_reachable_from_reverse_direction_asks_who_cannot_reach() -> None:
    truth = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "not_reachable_from",
            "node": {"label": "Pump"},
            "source_node": {"label": "Tank"},
            "direction": "reverse",
        },
    )

    # The pump reaches tank-1, so it is not a witness.
    assert truth.verdict == VERDICT_NO_VIOLATION
    assert truth.witness_ids == ()


def test_not_reachable_from_supports_undirected_and_edge_filters() -> None:
    undirected = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "not_reachable_from",
            "node": {"label": "Pump"},
            "source_node": {"label": "Tank"},
            "direction": "undirected",
        },
    )
    assert undirected.verdict == VERDICT_NO_VIOLATION

    filtered = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "not_reachable_from",
            "node": {"label": "Tank"},
            "source_node": {"label": "Pump"},
            "edges": [{"attr_name": "no_such_relation"}],
        },
    )
    # With every edge filtered out, no tank is reachable.
    assert filtered.witness_ids == ("tank-1", "tank-2")


def test_match_values_accept_membership_lists() -> None:
    truth = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "match_nodes",
            "node": {"label": ["Pump", "Pipe"]},
        },
    )

    assert truth.witness_ids == ("pipe-1", "pump-1")


def test_no_incoming_edge_of_any_flags_unattached_nodes() -> None:
    truth = derive_ground_truth(
        CHAIN_GRAPH,
        {
            "operation": "no_incoming_edge_of_any",
            "node": {"label": "Tank"},
            "edges": [
                {"label": "reference", "attr_name": "sourceItem"},
                {"label": "reference", "attr_name": "targetItem"},
            ],
        },
    )

    assert truth.verdict == VERDICT_VIOLATION_FOUND
    assert truth.witness_ids == ("tank-2",)


def test_reachability_with_no_matching_sources_is_rejected_as_vacuous() -> None:
    with pytest.raises(ValueError, match="matches no nodes"):
        derive_ground_truth(
            CHAIN_GRAPH,
            {
                "operation": "not_reachable_from",
                "node": {"label": "Tank"},
                "source_node": {"label": "Compressor"},
            },
        )


def test_abstention_expected_derives_unanswerable_with_no_witnesses() -> None:
    truth = derive_ground_truth(CHAIN_GRAPH, {"operation": "abstention_expected"})

    assert truth.verdict == VERDICT_UNANSWERABLE
    assert truth.witness_ids == ()


def test_unknown_operation_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported hand-authored oracle"):
        derive_ground_truth(CHAIN_GRAPH, {"operation": "clairvoyance"})


# --- the harder-questions manifest itself ---------------------------------


def test_manifest_is_loader_valid_with_five_size_matched_pairs() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    assert len(dataset.questions) == 10
    assert all(question.slice == SLICE_HAND_AUTHORED for question in dataset.questions)
    assert all(
        question.category == CATEGORY_COMPLIANCE_UNIVERSAL
        for question in dataset.questions
    )
    assert Counter(question.size_bucket for question in dataset.questions) == {
        "small": 5,
        "large": 5,
    }

    # Size-matched pairs share a core stem and ask the same question.
    stems = Counter(
        question.question_id.rsplit("-", 1)[0] for question in dataset.questions
    )
    assert len(stems) == 5
    assert set(stems.values()) == {2}
    by_id = {question.question_id: question for question in dataset.questions}
    for stem in stems:
        small = by_id[f"{stem}-small"]
        large = by_id[f"{stem}-large"]
        assert small.size_bucket == "small"
        assert large.size_bucket == "large"
        assert small.drawing_ref != large.drawing_ref


def test_size_pairs_use_genuinely_different_drawing_sizes() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    def node_count(question) -> int:
        graph_facts = json.loads(
            (question.drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        return len(graph_facts["facts"]["nodes"])

    for question in dataset.questions:
        if question.size_bucket == "small":
            assert node_count(question) <= 30
        else:
            assert node_count(question) >= 50


def test_slice_carries_multi_witness_and_abstention_structure() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    verdicts = Counter(question.ground_truth.verdict for question in dataset.questions)
    # Mixed profile: majority-class guessing cannot pass this slice.
    assert verdicts[VERDICT_VIOLATION_FOUND] >= 3
    assert verdicts[VERDICT_NO_VIOLATION] >= 3
    assert verdicts[VERDICT_UNANSWERABLE] == 2

    multi_witness = [
        question
        for question in dataset.questions
        if len(question.ground_truth.witness_ids) >= 3
    ]
    assert len(multi_witness) >= 3

    for question in dataset.questions:
        if question.ground_truth.verdict == VERDICT_UNANSWERABLE:
            assert question.ground_truth.witness_ids == ()


def test_questions_state_the_verdict_contract() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    for question in dataset.questions:
        if question.ground_truth.verdict == VERDICT_UNANSWERABLE:
            assert "unanswerable" in question.question
        else:
            assert "violation_found" in question.question
            assert "no_violation" in question.question
            assert "witness" in question.question


def test_questions_use_real_dexpi_training_fixtures() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    for drawing_ref in {question.drawing_ref for question in dataset.questions}:
        graph_facts = json.loads(
            (drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        assert graph_facts["source_path"].startswith("TrainingTestCases/dexpi 1.3/")
        assert graph_facts["provenance"]["extractor"] == "pyDEXPI"


def test_every_ground_truth_is_reproduced_from_canonical_graph_facts() -> None:
    assert verify_hand_authored_manifest(MANIFEST_PATH) == 10
