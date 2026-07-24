"""Rule outcome convention: fences evaluate without per-rule Python adapters."""

from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.verification.bundled_rule_pack import evaluate_bundled_rule
from pydexpi_datalog.verification.souffle_rule_pack import evaluate_rule_fence


REPO_ROOT = Path(__file__).resolve().parents[2]

# Minimal fence that only speaks the rule outcome convention — no custom
# Python interpreter may be registered for this rule_id.
PUMP_PRESENT_FENCE = """
.decl pump(id:symbol)
pump(id) :- node_label(id, "CentrifugalPump").

.decl rule_result(subject_id:symbol, result_type:symbol)
rule_result(id, "pass") :- pump(id).

.decl rule_message(subject_id:symbol, message:symbol)
rule_message(id, "A centrifugal pump is present in the prepared graph.") :- pump(id).

.decl rule_subject_attr(subject_id:symbol, attr:symbol, value:symbol)
rule_subject_attr(id, "pump_id", id) :- pump(id).
rule_subject_attr(id, "discharge_nozzle_id", "n/a") :- pump(id).

.decl rule_engine_attr(subject_id:symbol, key:symbol, value:symbol)
rule_engine_attr(id, "engine", "souffle") :- pump(id).

.output rule_result
.output rule_message
.output rule_subject_attr
.output rule_engine_attr
"""


def _graph(relative_path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def test_convention_fence_evaluates_without_per_rule_adapter() -> None:
    result = evaluate_rule_fence(
        _graph("testdata/verifier_suite/inputs/pass_c01_local_segment_graph.json"),
        rule_id="pump_present_convention",
        fence=PUMP_PRESENT_FENCE,
    )

    assert result["result_type"] == "pass"
    assert result["rule_id"] == "pump_present_convention"
    assert "centrifugal pump" in str(result["message"]).lower()
    assert result["evidence"]["derived_graph_semantics"]["engine"] == "souffle"
    assert result["subject"]["pump_id"]


def test_bundled_demo_rules_use_generic_fence_path() -> None:
    """Demo rules must not require a per-rule_id adapter map entry."""
    result = evaluate_bundled_rule(
        _graph("testdata/verifier_suite/inputs/pass_c01_local_segment_graph.json"),
        pack_id="demo-process-safety",
        rule_id="pump_discharge_check_valve",
    )
    assert result["outcome"] == "satisfied"
    assert result["evidence"]["derived_graph_semantics"]["engine"] == "souffle"
