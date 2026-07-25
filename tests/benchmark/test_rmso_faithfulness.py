from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.rmso_faithfulness import (
    FaithfulnessSuiteError,
    evaluate_faithfulness_program,
    load_faithfulness_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = REPO_ROOT / "testdata" / "benchmark" / "rmso_faithfulness_probes.json"


def test_loads_three_pairs_and_oracle_verifies_six_frozen_mutations() -> None:
    suite = load_faithfulness_suite(PROBES)

    assert [family.family_id for family in suite.families] == [
        "nozzle_piping_attachment",
        "valve_monitoring_reachability",
        "equipment_pump_connectivity",
    ]
    assert [len(family.cases) for family in suite.families] == [4, 4, 4]
    assert sum(
        case.is_counterfactual
        for family in suite.families
        for case in family.cases
    ) == 6


def test_rejects_counterfactual_expected_set_not_reproduced_by_oracle(
    tmp_path: Path,
) -> None:
    raw = json.loads(PROBES.read_text(encoding="utf-8"))
    raw["source"]["path"] = str(PROBES.parent / raw["source"]["path"])
    raw["families"][0]["probes"][0]["expected"]["witness_ids"] = []
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(FaithfulnessSuiteError, match="oracle mismatch"):
        load_faithfulness_suite(changed)


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_one_unchanged_program_passes_pair_and_counterfactual_replays() -> None:
    family = load_faithfulness_suite(PROBES).families[0]
    program = """\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
.decl nozzle(x:symbol)
nozzle(X) :- node_attribute(X, "label", "Nozzle").
.decl attached(x:symbol)
attached(X) :- graph_edge(S, X, K),
  graph_edge_attribute(S, X, K, "label", "reference"),
  graph_edge_attribute(S, X, K, "attr_name", "sourceItem").
attached(X) :- graph_edge(S, X, K),
  graph_edge_attribute(S, X, K, "label", "reference"),
  graph_edge_attribute(S, X, K, "attr_name", "targetItem").
attached(X) :- graph_edge(S, X, K),
  graph_edge_attribute(S, X, K, "label", "reference"),
  graph_edge_attribute(S, X, K, "attr_name", "sourceNode").
attached(X) :- graph_edge(S, X, K),
  graph_edge_attribute(S, X, K, "label", "reference"),
  graph_edge_attribute(S, X, K, "attr_name", "targetNode").
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- nozzle(X), !attached(X).
"""

    report = evaluate_faithfulness_program(program, family)

    assert report.passed is True
    assert all(case.passed for case in report.cases)


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
@pytest.mark.parametrize(
    "rule",
    (
        "result_witness(X) :- node(X), X != X.",
        "result_witness(X) :- node(X).",
    ),
)
def test_counterfactual_gate_rejects_vacuous_programs(rule: str) -> None:
    family = load_faithfulness_suite(PROBES).families[0]
    program = f"""\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
.decl result_witness(id:symbol)
.output result_witness
{rule}
"""

    report = evaluate_faithfulness_program(program, family)

    assert report.passed is False
    assert any(not case.passed for case in report.cases)
