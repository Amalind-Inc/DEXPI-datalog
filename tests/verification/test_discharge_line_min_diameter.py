from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.semantics.derive_graph_semantics import load_graph_topology_idb
from pydexpi_datalog.semantics.souffle_runner import run_souffle_program
from pydexpi_datalog.verification.bundled_rule_pack import (
    bundled_rule_packs,
    evaluate_bundled_rule,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
PACK_ID = "demo-process-safety"
RULE_ID = "discharge_line_min_diameter"
DIAMETER_ATTR = "nominalDiameterNumericalValueRepresentation"


def _graph() -> dict[str, object]:
    return json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))


def _diameter_attribute_maps(graph_facts: dict[str, object]) -> list[dict[str, object]]:
    return [
        node["attributes"]
        for node in graph_facts["facts"]["nodes"]
        if DIAMETER_ATTR in node["attributes"]
    ]


def _replace_diameter(graph_facts: dict[str, object], value: str) -> None:
    attributes = _diameter_attribute_maps(graph_facts)
    assert attributes
    for attrs in attributes:
        attrs[DIAMETER_ATTR] = value


def _remove_diameter(graph_facts: dict[str, object]) -> None:
    attributes = _diameter_attribute_maps(graph_facts)
    assert attributes
    for attrs in attributes:
        attrs.pop(DIAMETER_ATTR)


def _evaluate(graph_facts: dict[str, object]) -> dict[str, object]:
    return evaluate_bundled_rule(
        graph_facts,
        pack_id=PACK_ID,
        rule_id=RULE_ID,
    )


def _assert_numeric_diameter_evidence(
    result: dict[str, object], *, expected_dn: int
) -> None:
    evidence = result["evidence"]

    assert evidence["derived_graph_semantics"] == {
        "numeric_predicate": "node_numeric_attribute",
        "engine": "souffle",
    }
    assert evidence["threshold"]["attr_name"] == DIAMETER_ATTR
    assert evidence["threshold"]["min_diameter_dn"] == 25
    assert evidence["scope_completeness"]["complete"] is True
    assert evidence["scope_completeness"]["basis"] == "numeric_attribute_read"

    readings = evidence["diameter_readings"]
    assert readings
    assert evidence["matched_objects"] == readings
    assert [reading["nominal_diameter_dn"] for reading in readings] == [expected_dn]
    assert readings[0]["class"] == "PipingNetworkSystem"


def _assert_source_data_unavailable(result: dict[str, object]) -> None:
    evidence = result["evidence"]

    assert result["outcome"] == "indeterminate"
    assert result["legacy_result_type"] == "source_data_unavailable"
    assert evidence["limitation"]["code"] == "source_data_unavailable"
    assert evidence["scope_completeness"]["complete"] is False
    assert evidence["scope_completeness"]["basis"] == "source_data_unavailable"
    assert evidence["diameter_readings"] == []
    assert evidence["matched_objects"] == []
    assert evidence["derived_graph_semantics"] == {
        "numeric_predicate": "node_numeric_attribute",
        "engine": "souffle",
    }


def test_node_numeric_attribute_casts_only_integer_strings_to_number_facts() -> None:
    program = f"""
.decl node(id:symbol)
.decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)
.decl graph_edge(source:symbol, target:symbol, edge_key:symbol)
.decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol, attr_name:symbol, attr_value:symbol)

node("integer-node").
node("negative-node").
node("float-node").
node("text-node").
node_attribute("integer-node", "{DIAMETER_ATTR}", "80").
node_attribute("negative-node", "{DIAMETER_ATTR}", "-5").
node_attribute("float-node", "{DIAMETER_ATTR}", "4712.02").
node_attribute("text-node", "{DIAMETER_ATTR}", "abc").
{load_graph_topology_idb()}
.output node_attribute
.output node_numeric_attribute
"""

    relations = run_souffle_program(program)

    assert set(relations["node_attribute"]) == {
        ("integer-node", DIAMETER_ATTR, "80"),
        ("negative-node", DIAMETER_ATTR, "-5"),
        ("float-node", DIAMETER_ATTR, "4712.02"),
        ("text-node", DIAMETER_ATTR, "abc"),
    }
    assert set(relations["node_numeric_attribute"]) == {
        ("integer-node", DIAMETER_ATTR, "80"),
        ("negative-node", DIAMETER_ATTR, "-5"),
    }


def test_discharge_line_min_diameter_is_satisfied_for_real_e06_dn_80() -> None:
    result = _evaluate(_graph())

    assert result["outcome"] == "satisfied"
    assert result["legacy_result_type"] == "pass"
    assert "DN 80" in result["message"]
    _assert_numeric_diameter_evidence(result, expected_dn=80)


def test_discharge_line_min_diameter_is_violated_below_dn_25() -> None:
    graph_facts = _graph()
    _replace_diameter(graph_facts, "15")

    result = _evaluate(graph_facts)

    assert result["outcome"] == "violated"
    assert result["legacy_result_type"] == "hard_violation"
    assert "DN 15" in result["message"]
    _assert_numeric_diameter_evidence(result, expected_dn=15)


def test_missing_discharge_line_diameter_is_source_data_unavailable() -> None:
    graph_facts = _graph()
    _remove_diameter(graph_facts)

    result = _evaluate(graph_facts)

    assert "DN 25" in result["message"]
    _assert_source_data_unavailable(result)


def test_float_only_discharge_line_diameter_is_not_a_numeric_value() -> None:
    graph_facts = _graph()
    _replace_diameter(graph_facts, "80.5")

    result = _evaluate(graph_facts)

    assert "80.5" not in result["message"]
    _assert_source_data_unavailable(result)


def test_unreviewed_inferred_direction_gates_discharge_line_diameter_rule() -> None:
    result = evaluate_bundled_rule(
        _graph(),
        pack_id=PACK_ID,
        rule_id=RULE_ID,
        direction_basis="inferred",
        direction_review_status=None,
    )

    assert result["outcome"] == "indeterminate"
    assert result["evidence"]["direction"] == {
        "basis": "inferred",
        "review_status": None,
        "formal_use_allowed": False,
    }
    assert result["evidence"]["limitation"]["code"] == "direction.review_required"


def test_demo_pack_declares_discharge_line_min_diameter_contract() -> None:
    demo = next(
        pack
        for pack in bundled_rule_packs()
        if pack["pack_id"] == PACK_ID
    )

    assert [rule["rule_id"] for rule in demo["rules"]] == [
        "pump_discharge_check_valve",
        "discharge_line_min_diameter",
    ]
    rule = demo["rules"][1]
    executable_logic = rule["executable_logic"]

    assert executable_logic["language"] == "souffle_datalog"
    assert executable_logic["inspectable"] is True
    assert executable_logic["content"]
    assert "node_numeric_attribute" in executable_logic["content"]
