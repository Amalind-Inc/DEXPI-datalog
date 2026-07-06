from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.verification.bundled_rule_pack import (
    bundled_rule_packs,
    evaluate_bundled_rule,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "testdata" / "verifier_suite" / "inputs"


def _graph(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _graph_at(relative_path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def test_bundled_pack_declares_non_authoritative_rule_contract() -> None:
    packs = bundled_rule_packs()

    assert len(packs) >= 1
    demo = next(pack for pack in packs if pack["pack_id"] == "demo-process-safety")
    assert demo["authoritative"] is False
    assert "not" in str(demo["trust_notice"]).lower()
    assert [rule["rule_id"] for rule in demo["rules"]] == [
        "pump_discharge_check_valve",
        "discharge_line_min_diameter",
    ]
    rule = demo["rules"][0]
    assert rule["restatement"]["plain_language_meaning"]
    assert rule["executable_logic"]["inspectable"] is True


def test_pump_rule_satisfied_outcome_has_complete_witness() -> None:
    result = evaluate_bundled_rule(
        _graph("pass_c01_local_segment_graph.json"),
        pack_id="demo-process-safety",
        rule_id="pump_discharge_check_valve",
    )

    assert result["outcome"] == "satisfied"
    assert result["pack"]["authoritative"] is False
    assert result["evidence"]["traversed_objects"]
    assert result["evidence"]["traversed_edges"]
    assert result["evidence"]["matched_objects"]
    assert result["evidence"]["boundary"]["kind"] == "matched_required_component"


def test_absence_violation_proves_complete_bounded_scope() -> None:
    result = evaluate_bundled_rule(
        _graph("hard_violation_c01_no_check_valve_graph.json"),
        pack_id="demo-process-safety",
        rule_id="pump_discharge_check_valve",
    )

    assert result["outcome"] == "violated"
    assert result["evidence"]["matched_objects"] == []
    assert result["evidence"]["scope_completeness"] == {
        "complete": True,
        "basis": "terminal_boundary_reached",
        "boundary_kind": "terminal_object",
    }


def test_off_page_and_unresolved_scope_are_indeterminate() -> None:
    for fixture, expected_boundary in (
        ("bounded_failure_off_page_c01_graph.json", "off_page_connector"),
        ("../graph_contract/e03-pump/graph_facts.json", "unresolved_discharge_nozzle"),
    ):
        graph = (
            _graph_at(f"testdata/{fixture.removeprefix('../')}")
            if fixture.startswith("../")
            else _graph(fixture)
        )
        result = evaluate_bundled_rule(
            graph,
            pack_id="demo-process-safety",
            rule_id="pump_discharge_check_valve",
        )

        assert result["outcome"] == "indeterminate"
        assert result["evidence"]["boundary"]["kind"] == expected_boundary
        assert result["evidence"]["scope_completeness"]["complete"] is False


def test_unreviewed_inferred_direction_cannot_establish_formal_outcome() -> None:
    result = evaluate_bundled_rule(
        _graph("pass_c01_local_segment_graph.json"),
        pack_id="demo-process-safety",
        rule_id="pump_discharge_check_valve",
        direction_basis="inferred",
        direction_review_status="pending",
    )

    assert result["outcome"] == "indeterminate"
    assert result["evidence"]["direction"] == {
        "basis": "inferred",
        "review_status": "pending",
        "formal_use_allowed": False,
    }
    assert result["evidence"]["limitation"]["code"] == "direction.review_required"
