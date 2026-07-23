from __future__ import annotations

import pytest

from pydexpi_datalog.qa.faithfulness_gate import (
    evaluate_layered_faithfulness_gate,
)


INTENT = {
    "source_classes": ["Tank"],
    "target_classes": ["CentrifugalPump"],
    "source_role": "process_equipment",
    "target_role": "pump",
    "graph_scope": "piping_only",
    "direction": "undirected",
    "quantifier": "all",
    "negated": True,
    "output_obligations": ["violating_source_ids"],
}


def _evaluate(*, model_review: object, semantic_diagnostics=None):
    return evaluate_layered_faithfulness_gate(
        mechanical_validation={"status": "safe_to_confirm", "diagnostics": []},
        requested_intent=INTENT,
        encoded_intent=INTENT,
        semantic_diagnostics=semantic_diagnostics or [],
        counterfactual_validation={"status": "passed", "diagnostics": []},
        model_review=model_review,
    )


def test_all_deterministic_layers_and_matching_back_translation_pass() -> None:
    result = _evaluate(
        model_review={
            "status": "faithful",
            "back_translated_intent": INTENT,
            "diagnostics": [],
        }
    )

    assert result["status"] == "passed"
    assert all(layer["status"] == "passed" for layer in result["layers"].values())


def test_deterministic_gate_can_pass_without_optional_model_verifier() -> None:
    result = _evaluate(model_review=None)

    assert result["status"] == "passed"
    assert result["layers"]["model_review"]["status"] == "not_applicable"


@pytest.mark.parametrize(
    ("model_review", "expected_code"),
    [
        ({}, "faithfulness.model_review_incomplete"),
        (
            {
                "status": "faithful",
                "back_translated_intent": INTENT,
            },
            "faithfulness.model_review_incomplete",
        ),
        (
            {
                "status": "uncertain",
                "back_translated_intent": INTENT,
                "diagnostics": ["Direction could not be established."],
            },
            "faithfulness.model_review_uncertain",
        ),
        (
            {
                "status": "unfaithful",
                "back_translated_intent": INTENT,
                "diagnostics": ["The query reverses the requested relation."],
            },
            "faithfulness.model_review_veto",
        ),
        (
            {
                "status": "faithful",
                "back_translated_intent": {**INTENT, "direction": "directed"},
                "diagnostics": [],
            },
            "faithfulness.model_review_conflict",
        ),
        (
            {
                "status": "faithful",
                "back_translated_intent": INTENT,
                "diagnostics": ["The review also reports a semantic mismatch."],
            },
            "faithfulness.model_review_conflict",
        ),
    ],
)
def test_incomplete_uncertain_vetoed_or_conflicting_model_evidence_fails(
    model_review: object,
    expected_code: str,
) -> None:
    result = _evaluate(model_review=model_review)

    assert result["status"] == "failed"
    model_layer = result["layers"]["model_review"]
    assert model_layer["status"] == "failed"
    assert model_layer["diagnostics"][0]["code"] == expected_code


def test_model_faithful_review_cannot_override_deterministic_failure() -> None:
    result = _evaluate(
        model_review={
            "status": "faithful",
            "back_translated_intent": INTENT,
            "diagnostics": [],
        },
        semantic_diagnostics=[
            {
                "code": "structured_intent.direction_mismatch",
                "message": "Generated query changed direction.",
            }
        ],
    )

    assert result["status"] == "failed"
    assert result["layers"]["semantic"]["status"] == "failed"
    assert result["layers"]["model_review"]["status"] == "passed"
