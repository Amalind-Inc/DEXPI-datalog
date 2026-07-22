from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools


REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTION_ID = "hq-equipment-pump-connectivity-small"
GRAPH_FACTS_PATH = (
    REPO_ROOT
    / "testdata"
    / "graph_contract"
    / "corpus"
    / "e06-pump-heatexchanger-nozzles-connected-with-pns-e06v01-ver-ex01"
    / "graph_facts.json"
)
MANIFEST_PATH = REPO_ROOT / "testdata" / "benchmark" / "harder_questions_manifest.json"
VALID_BINDINGS = {
    "source_classes": ["CentrifugalPump", "ReciprocatingPump"],
    "target_classes": [
        "PlateHeatExchanger",
        "TubularHeatExchanger",
        "Tank",
        "ProcessColumn",
    ],
    "scope": "piping",
    "direction": "undirected",
    "quantifier": "every",
    "negated": True,
}


class EquipmentPumpTemplateProvider:
    def __init__(
        self, question: str, bindings: dict[str, object] | None = None
    ) -> None:
        self._question = question
        self._bindings = bindings or VALID_BINDINGS
        self.calls = 0
        self.offered_tool_names: list[str] = []

    def complete_with_tools(self, *, messages, tools):
        self.offered_tool_names = [tool["function"]["name"] for tool in tools]
        self.calls += 1
        if self.calls == 1:
            return ToolCall(
                tool_name="execute_bundled_query_template",
                tool_input={
                    "request": self._question,
                    "template_id": "equipment_without_pump_path",
                    "bindings": self._bindings,
                },
                tool_call_id="template-call-1",
            )
        return FinalAnswer(answer_text="No major process equipment lacks a pump path.")


def _question() -> str:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    question = next(item for item in manifest["questions"] if item["id"] == QUESTION_ID)
    return str(question["question"])


def _prepared_tools(
    graph_facts: dict[str, object] | None = None,
) -> TopologyTools:
    graph_facts = graph_facts or json.loads(
        GRAPH_FACTS_PATH.read_text(encoding="utf-8")
    )
    nodes = []
    evidence_map = {}
    for fact in graph_facts["facts"]["nodes"]:
        node_id = str(fact["node_id"])
        attributes = fact["attributes"]
        label = str(attributes.get("label", ""))
        nodes.append(
            {
                "id": node_id,
                "source_graph_node_id": node_id,
                "label": label,
                "class_name": label,
                "display_name": str(attributes.get("tagName") or label or node_id),
                "category": "equipment"
                if label
                in {
                    "CentrifugalPump",
                    "ReciprocatingPump",
                    "PlateHeatExchanger",
                    "TubularHeatExchanger",
                    "Tank",
                    "ProcessColumn",
                }
                else "structural",
            }
        )
        evidence_map[node_id] = {"source_graph_node_id": node_id}
    edges = [
        {
            "id": str(fact["edge_key"]),
            "source_id": str(fact["source_id"]),
            "target_id": str(fact["target_id"]),
            "relationship": str(fact["attributes"].get("attr_name", "")),
            "source_graph_edge": fact,
        }
        for fact in graph_facts["facts"]["edges"]
    ]
    return TopologyTools(
        topology_view={
            "source_id": str(graph_facts["fixture_id"]),
            "nodes": nodes,
            "edges": edges,
            "evidence_map": evidence_map,
        },
        graph_facts=graph_facts,
        session_id="trusted-template-test",
    )


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_equipment_pump_template_executes_automatically_through_public_runner() -> None:
    question = _question()
    provider = EquipmentPumpTemplateProvider(question)

    result = run_grounded_qa_turn(
        question=question,
        topology_tools=_prepared_tools(),
        provider=provider,
    )

    assert "execute_bundled_query_template" in provider.offered_tool_names
    assert result.deterministic_verdict == "no_violation"
    assert result.witnesses == []
    assert result.route_artifact == {
        "route": "bundled_template",
        "template_id": "equipment_without_pump_path",
        "template_version": "1.0.0",
        "bindings": {
            "source_classes": ["CentrifugalPump", "ReciprocatingPump"],
            "target_classes": [
                "PlateHeatExchanger",
                "TubularHeatExchanger",
                "Tank",
                "ProcessColumn",
            ],
            "scope": "piping",
            "direction": "undirected",
            "quantifier": "every",
            "negated": True,
        },
        "validation": {"status": "accepted", "diagnostics": []},
    }
    assert [event["event"] for event in result.trace_events] == [
        "template_proposed",
        "template_validated",
        "template_executed",
        "result_observed",
    ]
    template_result = result.tool_call_trace[0]["tool_result"]
    assert template_result["executed"] is True
    assert template_result["confirmation"] == {"required": False}
    assert template_result["generated_datalog"] == {"requested": False}
    assert all(
        trace["tool_name"] != "propose_temporary_datalog"
        for trace in result.tool_call_trace
    )


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_equipment_pump_template_returns_disconnected_equipment_witness() -> None:
    graph_facts = json.loads(GRAPH_FACTS_PATH.read_text(encoding="utf-8"))
    graph_facts["facts"]["nodes"].append(
        {
            "fact_type": "node",
            "node_id": "disconnected-equipment",
            "attributes": {"label": "Tank", "tagName": "T-999"},
        }
    )
    question = _question()

    result = run_grounded_qa_turn(
        question=question,
        topology_tools=_prepared_tools(graph_facts),
        provider=EquipmentPumpTemplateProvider(question),
    )

    assert result.deterministic_verdict == "violation_found"
    assert result.witnesses == ["disconnected-equipment"]
    assert result.trace_events[-1] == {
        "event": "result_observed",
        "verdict": "violation_found",
        "witness_count": 1,
    }


@pytest.mark.parametrize(
    (("field", "invalid_value")),
    [
        ("source_classes", VALID_BINDINGS["target_classes"]),
        ("target_classes", ["Tank"]),
        ("scope", "any"),
        ("direction", "directed"),
        ("quantifier", "any"),
        ("negated", False),
    ],
)
def test_template_rejects_semantic_binding_changes_without_execution(
    field: str, invalid_value: object
) -> None:
    bindings = {**VALID_BINDINGS, field: invalid_value}

    result = _prepared_tools().execute(
        "execute_bundled_query_template",
        {
            "request": _question(),
            "template_id": "equipment_without_pump_path",
            "bindings": bindings,
        },
    )

    assert result["status"] == "rejected"
    assert result["executed"] is False
    assert result["confirmation"] == {"required": False}
    assert result["generated_datalog"] == {"requested": False}
    assert [event["event"] for event in result["trace_events"]] == [
        "template_proposed",
        "template_validated",
    ]
