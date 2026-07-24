"""Exhaustive outgoing-edge cardinality census (bead 3qo.9.16)."""

from __future__ import annotations

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import RetrievalBudgets, TopologyTools

E06_QUESTION = (
    "Does every piping network segment have exactly one sourceItem reference?"
)

# Finite drawing: one segment with exactly one outgoing sourceItem reference.
E06_TOPOLOGY = {
    "source_id": "drawing-e06",
    "nodes": [
        {
            "id": "segment-1",
            "label": "PipingNetworkSegment",
            "class_name": "PipingNetworkSegment",
            "display_name": "PipingNetworkSegment-1",
            "category": "piping",
        },
        {
            "id": "nozzle-1",
            "label": "Nozzle",
            "class_name": "Nozzle",
            "display_name": "N-1",
            "category": "equipment",
        },
        {
            "id": "pump-1",
            "label": "CentrifugalPump",
            "class_name": "CentrifugalPump",
            "display_name": "P-101",
            "category": "equipment",
        },
    ],
    "edges": [
        {
            "id": "edge-source-item",
            "source_id": "segment-1",
            "target_id": "nozzle-1",
            "relationship": "sourceItem",
            "edge_family": "reference",
        }
    ],
    "evidence_map": {
        "segment-1": {"source_graph_node_id": "segment-1"},
        "nozzle-1": {"source_graph_node_id": "nozzle-1"},
        "pump-1": {"source_graph_node_id": "pump-1"},
    },
}


def _tools(**kwargs) -> TopologyTools:
    return TopologyTools(
        topology_view=E06_TOPOLOGY,
        session_id="census-e06",
        **kwargs,
    )


def test_census_outgoing_edge_cardinality_reports_complete_no_violators() -> None:
    tools = _tools()
    tools.begin_request(E06_QUESTION)
    result = tools.execute(
        "census_outgoing_edge_cardinality",
        {
            "source_node_label": "PipingNetworkSegment",
            "edge_label": "reference",
            "attr_name": "sourceItem",
            "expected_count": 1,
        },
    )
    assert result["status"] == "answered"
    assert result["coverage"]["complete"] is True
    assert result["truncated"] is False
    assert result["expected_count"] == 1
    assert result["source_count"] == 1
    assert result["violators"] == []
    assert result["rows"][0]["evidence_id"] == "segment-1"
    assert result["rows"][0]["count"] == 1


def test_rule_evaluation_offers_census_tool() -> None:
    offered: list[set[str]] = []

    class Capture:
        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            names = {
                str(item.get("function", {}).get("name", ""))
                for item in tools
                if isinstance(item, dict)
            }
            offered.append(names)
            return ToolCall(
                tool_name="census_outgoing_edge_cardinality",
                tool_input={
                    "source_node_label": "PipingNetworkSegment",
                    "edge_label": "reference",
                    "attr_name": "sourceItem",
                    "expected_count": 1,
                },
                tool_call_id="census-1",
            )

    try:
        run_grounded_qa_turn(
            question=E06_QUESTION,
            topology_tools=_tools(),
            provider=Capture(),
            max_rounds=1,
        )
    except RuntimeError:
        pass
    assert offered
    assert "census_outgoing_edge_cardinality" in offered[0]
    assert "propose_temporary_datalog" in offered[0]
    assert "find_equipment" not in offered[0]


def test_complete_census_grounds_universal_cardinality_without_propose() -> None:
    class CensusThenAnswer:
        def __init__(self) -> None:
            self.calls = 0

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.calls += 1
            if self.calls == 1:
                return ToolCall(
                    tool_name="census_outgoing_edge_cardinality",
                    tool_input={
                        "source_node_label": "PipingNetworkSegment",
                        "edge_label": "reference",
                        "attr_name": "sourceItem",
                        "expected_count": 1,
                    },
                    tool_call_id="census-1",
                )
            return FinalAnswer(
                answer_text="no_violation",
                evidence_references=["segment-1"],
                grounding_posture="source_grounded",
            )

    result = run_grounded_qa_turn(
        question=E06_QUESTION,
        topology_tools=_tools(),
        provider=CensusThenAnswer(),
        max_rounds=4,
    )
    assert result.source_grounded is True
    assert "could not" not in result.answer_text.lower()
    assert any(
        entry.get("tool_name") == "census_outgoing_edge_cardinality"
        for entry in result.tool_call_trace
    )
    assert not any(
        entry.get("tool_name") == "propose_temporary_datalog"
        for entry in result.tool_call_trace
    )


def test_truncated_census_does_not_satisfy_universal_claim() -> None:
    class TruncatedCensusThenAnswer:
        def __init__(self) -> None:
            self.calls = 0

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.calls += 1
            if self.calls == 1:
                return ToolCall(
                    tool_name="census_outgoing_edge_cardinality",
                    tool_input={
                        "source_node_label": "PipingNetworkSegment",
                        "edge_label": "reference",
                        "attr_name": "sourceItem",
                        "expected_count": 1,
                    },
                    tool_call_id="census-trunc",
                )
            return FinalAnswer(
                answer_text="no_violation",
                evidence_references=["segment-1"],
                grounding_posture="source_grounded",
            )

    # Force truncation via a zero evidence-object budget.
    tools = _tools(retrieval_budgets=RetrievalBudgets(max_evidence_objects=0))
    result = run_grounded_qa_turn(
        question=E06_QUESTION,
        topology_tools=tools,
        provider=TruncatedCensusThenAnswer(),
        max_rounds=3,
    )
    assert "could not ground" in result.answer_text.lower() or any(
        (entry.get("tool_result") or {}).get("code") == "evidence.insufficient_for_claim"
        for entry in result.tool_call_trace
    )
    census = next(
        entry
        for entry in result.tool_call_trace
        if entry.get("tool_name") == "census_outgoing_edge_cardinality"
    )
    assert (census.get("tool_result") or {}).get("coverage", {}).get("complete") is False
