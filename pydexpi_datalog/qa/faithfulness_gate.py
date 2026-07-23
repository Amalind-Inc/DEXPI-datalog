"""Backend-owned composition of generated-query faithfulness evidence."""

from __future__ import annotations

from collections.abc import Mapping

from pydexpi_datalog.qa.structured_intent import compare_structured_intents


def evaluate_layered_faithfulness_gate(
    *,
    mechanical_validation: Mapping[str, object],
    requested_intent: Mapping[str, object] | None,
    encoded_intent: Mapping[str, object] | None,
    semantic_diagnostics: list[dict[str, object]],
    counterfactual_validation: Mapping[str, object] | None,
    model_review: object,
) -> dict[str, object]:
    """Require every deterministic layer while allowing model review only to veto."""
    mechanical = _mechanical_layer(mechanical_validation)
    semantic = _semantic_layer(
        requested_intent=requested_intent,
        encoded_intent=encoded_intent,
        diagnostics=semantic_diagnostics,
    )
    counterfactual = _counterfactual_layer(counterfactual_validation)
    model = _model_review_layer(requested_intent, model_review)
    layers = {
        "mechanical": mechanical,
        "semantic": semantic,
        "counterfactual": counterfactual,
        "model_review": model,
    }
    passed = all(
        layers[name]["status"] == "passed"
        for name in ("mechanical", "semantic", "counterfactual")
    ) and model["status"] in {"passed", "not_applicable"}
    diagnostics = [
        diagnostic for layer in layers.values() for diagnostic in _diagnostics(layer)
    ]
    return {
        "status": "passed" if passed else "failed",
        "layers": layers,
        "diagnostics": diagnostics,
    }


def _mechanical_layer(validation: Mapping[str, object]) -> dict[str, object]:
    passed = validation.get("status") == "safe_to_confirm"
    return {
        "status": "passed" if passed else "failed",
        "diagnostics": [] if passed else _diagnostics(validation),
    }


def _semantic_layer(
    *,
    requested_intent: Mapping[str, object] | None,
    encoded_intent: Mapping[str, object] | None,
    diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    passed = (
        requested_intent is not None and encoded_intent is not None and not diagnostics
    )
    if passed:
        return {"status": "passed", "diagnostics": []}
    layer_diagnostics = list(diagnostics)
    if not layer_diagnostics:
        layer_diagnostics = [
            {
                "code": "faithfulness.semantic_evidence_incomplete",
                "message": "Deterministic structured-intent evidence is incomplete.",
            }
        ]
    return {"status": "failed", "diagnostics": layer_diagnostics}


def _counterfactual_layer(
    validation: Mapping[str, object] | None,
) -> dict[str, object]:
    if validation is None:
        return {
            "status": "not_evaluated",
            "diagnostics": [
                {
                    "code": "faithfulness.counterfactual_not_evaluated",
                    "message": "Counterfactual replay was not evaluated.",
                }
            ],
        }
    outcome = validation.get("status")
    passed = outcome in {"passed", "not_applicable"}
    return {
        "status": "passed" if passed else "failed",
        "outcome": outcome,
        "diagnostics": [] if passed else _diagnostics(validation),
    }


def _model_review_layer(
    requested_intent: Mapping[str, object] | None, model_review: object
) -> dict[str, object]:
    if model_review is None:
        return {
            "status": "not_applicable",
            "outcome": None,
            "back_translated_intent": None,
            "model_diagnostics": [],
            "diagnostics": [],
        }
    if not isinstance(model_review, Mapping):
        return _failed_model_review(
            "faithfulness.model_review_incomplete",
            "When supplied, model review must be a structured back-translation.",
        )

    status = model_review.get("status")
    if status not in {"faithful", "unfaithful", "uncertain"}:
        return _failed_model_review(
            "faithfulness.model_review_incomplete",
            "Model review status must be faithful, unfaithful, or uncertain.",
        )
    raw_review_diagnostics = model_review.get("diagnostics")
    if not isinstance(raw_review_diagnostics, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_review_diagnostics
    ):
        return _failed_model_review(
            "faithfulness.model_review_incomplete",
            "Model review diagnostics must be a list of non-empty strings.",
            outcome=status,
        )
    review_diagnostics = [item.strip() for item in raw_review_diagnostics]
    back_translated = model_review.get("back_translated_intent")
    if requested_intent is None:
        return _failed_model_review(
            "faithfulness.model_review_incomplete",
            "Model review cannot be checked without backend-bound structured intent.",
        )
    normalized, comparison_diagnostics = compare_structured_intents(
        requested_intent, back_translated
    )
    if comparison_diagnostics or normalized is None:
        code = (
            "faithfulness.model_review_conflict"
            if status == "faithful"
            else "faithfulness.model_review_incomplete"
        )
        return {
            "status": "failed",
            "outcome": status,
            "back_translated_intent": normalized,
            "model_diagnostics": review_diagnostics,
            "diagnostics": [
                {
                    "code": code,
                    "message": (
                        "Model back-translation conflicts with the requested intent."
                        if status == "faithful"
                        else "Model back-translation is incomplete or invalid."
                    ),
                },
                *comparison_diagnostics,
            ],
        }
    if status == "faithful" and review_diagnostics:
        return _failed_model_review(
            "faithfulness.model_review_conflict",
            "Model review claims faithfulness but also reports blocking diagnostics.",
            outcome=status,
            back_translated_intent=normalized,
            model_diagnostics=review_diagnostics,
        )
    if status == "uncertain":
        return _failed_model_review(
            "faithfulness.model_review_uncertain",
            "Model back-translation reported uncertain faithfulness.",
            outcome=status,
            back_translated_intent=normalized,
            model_diagnostics=review_diagnostics,
        )
    if status == "unfaithful":
        return _failed_model_review(
            "faithfulness.model_review_veto",
            "Model back-translation vetoed this generated revision.",
            outcome=status,
            back_translated_intent=normalized,
            model_diagnostics=review_diagnostics,
        )
    return {
        "status": "passed",
        "outcome": status,
        "back_translated_intent": normalized,
        "model_diagnostics": review_diagnostics,
        "diagnostics": [],
    }


def _failed_model_review(
    code: str,
    message: str,
    *,
    outcome: object = None,
    back_translated_intent: object = None,
    model_diagnostics: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": "failed",
        "outcome": outcome,
        "back_translated_intent": back_translated_intent,
        "model_diagnostics": list(model_diagnostics or []),
        "diagnostics": [{"code": code, "message": message}],
    }


def _diagnostics(value: Mapping[str, object]) -> list[dict[str, object]]:
    raw = value.get("diagnostics")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]
