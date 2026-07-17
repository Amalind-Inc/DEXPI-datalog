from __future__ import annotations

from pydexpi_datalog.benchmark.audit_trace import verify_audit_trace
from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_GROUNDED,
    StructuredAnswer,
    VERDICT_VIOLATION_FOUND,
    VERDICT_NO_VIOLATION,
)


def graph_facts() -> dict[str, object]:
    return {
        "facts": {
            "nodes": [
                {"node_id": "P-101", "attributes": {"label": "CentrifugalPump"}}
            ],
            "edges": [],
        }
    }


def supported_answer() -> StructuredAnswer:
    return StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101",),
        posture=POSTURE_SOURCE_GROUNDED,
        support={
            "steps": [
                {
                    "id": "source-p101",
                    "kind": "graph_node",
                    "node_id": "P-101",
                    "dependencies": [],
                },
                {
                    "id": "execution",
                    "kind": "souffle_execution",
                    "artifact": "analysis.dl",
                    "relation": "result_witness",
                    "witness_ids": ["P-101"],
                    "dependencies": ["source-p101"],
                },
            ],
            "claims": [
                {"claim": "verdict", "step_ids": ["execution"]},
                {"claim": "witness:P-101", "step_ids": ["execution"]},
            ],
        },
    )


def test_complete_grounded_replayed_support_graph_is_trace_safe() -> None:
    report = verify_audit_trace(
        answer=supported_answer(),
        graph_facts=graph_facts(),
        replay_souffle=lambda artifact, relation: ("P-101",),
    )

    assert report.trace_safe is True
    assert report.coverage == 1.0
    assert report.grounded_premise_rate == 1.0
    assert report.replay_success == 1.0
    assert report.final_support_steps == 2


def test_missing_witness_claim_and_invented_source_are_trace_unsafe() -> None:
    answer = supported_answer()
    answer.support["claims"] = [
        {"claim": "verdict", "step_ids": ["execution"]}
    ]
    answer.support["steps"][0]["node_id"] = "INVENTED"

    report = verify_audit_trace(
        answer=answer,
        graph_facts=graph_facts(),
        replay_souffle=lambda artifact, relation: ("P-101",),
    )

    assert report.trace_safe is False
    assert "witness:P-101" in report.uncovered_claims
    assert "source-p101" in report.invalid_step_ids


def test_superseded_cyclic_or_free_form_support_cannot_be_relied_upon() -> None:
    answer = supported_answer()
    steps = answer.support["steps"]
    steps[0]["superseded"] = True
    steps[0]["dependencies"] = ["execution"]
    steps.append(
        {
            "id": "prose",
            "kind": "free_form_reasoning",
            "dependencies": [],
        }
    )
    answer.support["claims"][0]["step_ids"] = ["prose"]

    report = verify_audit_trace(
        answer=answer,
        graph_facts=graph_facts(),
        replay_souffle=lambda artifact, relation: ("P-101",),
    )

    assert report.trace_safe is False
    assert report.history_integrity is False
    assert report.dependency_validity is False
    assert report.policy_compliance is False
    assert report.superseded_steps == 1
    assert "prose" in report.invalid_step_ids


def test_negative_conclusion_uses_complete_graph_scope_and_empty_replay() -> None:
    answer = StructuredAnswer(
        verdict=VERDICT_NO_VIOLATION,
        posture=POSTURE_SOURCE_GROUNDED,
        support={
            "steps": [
                {
                    "id": "scope",
                    "kind": "graph_scope",
                    "node_count": 1,
                    "edge_count": 0,
                    "dependencies": [],
                },
                {
                    "id": "execution",
                    "kind": "souffle_execution",
                    "artifact": "analysis.dl",
                    "relation": "result_witness",
                    "witness_ids": [],
                    "dependencies": ["scope"],
                },
            ],
            "claims": [{"claim": "verdict", "step_ids": ["execution"]}],
        },
    )

    report = verify_audit_trace(
        answer=answer,
        graph_facts=graph_facts(),
        replay_souffle=lambda artifact, relation: (),
    )

    assert report.trace_safe is True
