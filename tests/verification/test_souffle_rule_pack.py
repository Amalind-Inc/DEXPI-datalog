from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydexpi_datalog.verification.bundled_rule_pack import (
    bundled_rule_packs,
    evaluate_bundled_rule,
)
from pydexpi_datalog.verification.souffle_rule_pack import (
    evaluate_pump_discharge_rule,
)
from pydexpi_datalog.verification.verify_suite import evaluate_graph_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]

FIXTURE_PATHS = [
    "testdata/verifier_suite/inputs/pass_c01_local_segment_graph.json",
    "testdata/verifier_suite/inputs/pass_e06_added_check_valve_graph.json",
    "testdata/verifier_suite/inputs/hard_violation_c01_no_check_valve_graph.json",
    "testdata/verifier_suite/inputs/bounded_failure_off_page_c01_graph.json",
    "testdata/graph_contract/e03-pump/graph_facts.json",
]


def _graph(relative_path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS)
def test_souffle_evaluation_matches_python_traversal_contract(
    fixture_path: str,
) -> None:
    graph_facts = _graph(fixture_path)

    legacy = evaluate_graph_fixture(graph_facts, rule_id="pump_discharge_check_valve")
    souffle = evaluate_pump_discharge_rule(
        graph_facts, rule_id="pump_discharge_check_valve"
    )

    engine = souffle["evidence"]["derived_graph_semantics"].pop("engine")
    assert engine == "souffle"
    assert souffle == legacy


def test_bundled_rule_evaluation_reports_souffle_engine() -> None:
    result = evaluate_bundled_rule(
        _graph("testdata/verifier_suite/inputs/pass_c01_local_segment_graph.json"),
        pack_id="demo-process-safety",
        rule_id="pump_discharge_check_valve",
    )

    assert result["outcome"] == "satisfied"
    assert result["evidence"]["derived_graph_semantics"]["engine"] == "souffle"


def test_pack_metadata_declares_real_souffle_datalog() -> None:
    demo = next(
        pack
        for pack in bundled_rule_packs()
        if pack["pack_id"] == "demo-process-safety"
    )
    rule = demo["rules"][0]

    assert rule["executable_logic"]["language"] == "souffle_datalog"
    # The inspectable content is the actual executed Datalog program, not prose.
    assert ".decl" in rule["executable_logic"]["content"]
    assert "matched_required_component" in rule["executable_logic"]["content"]
    assert rule["executable_logic"]["inspectable"] is True
