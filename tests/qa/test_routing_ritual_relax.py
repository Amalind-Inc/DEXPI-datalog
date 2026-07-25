"""Behavioral contracts for relaxed generated-Datalog routing (bead 2669).

Propose must be a free choice (always offered except deontic policy), and the
session question — not a paraphrased model `request` — authorizes the receipt.
"""

from __future__ import annotations

import shutil

import pytest

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools

QUESTION = "Must every CentrifugalPump have a reachable BallValve?"
PARAPHRASED_REQUEST = (
    "Check what attributes exist on the CentrifugalPump node (P-101)."
)
GENERATED_DATALOG = """\
.decl pump(x:symbol)
pump(X) :- node_attribute(X, "label", "CentrifugalPump").
.decl valve(x:symbol)
valve(X) :- node_attribute(X, "label", "BallValve").
.decl pump_with_valve(x:symbol)
pump_with_valve(P) :- pump(P), valve(V), piping_connected(P, V).
.decl answer(x:symbol)
.output answer
answer(P) :- pump(P), !pump_with_valve(P).
"""
STRUCTURED_INTENT = {
    "source_classes": ["CentrifugalPump"],
    "target_classes": ["BallValve"],
    "source_role": "equipment",
    "target_role": "reachable_object",
    "graph_scope": "piping_only",
    "direction": "undirected",
    "quantifier": "all",
    "negated": True,
    "output_obligations": ["violating_source_ids"],
}
FAITHFULNESS_REVIEW = {
    "status": "faithful",
    "back_translated_intent": STRUCTURED_INTENT,
    "diagnostics": [],
}

MINIMAL_TOPOLOGY = {
    "source_id": "drawing-v1",
    "nodes": [
        {
            "id": "pump-1",
            "label": "CentrifugalPump",
            "class_name": "CentrifugalPump",
            "display_name": "P-101",
            "category": "equipment",
        },
        {
            "id": "valve-1",
            "label": "BallValve",
            "class_name": "BallValve",
            "display_name": "V-101",
            "category": "equipment",
        },
    ],
    "edges": [
        {
            "id": "edge-1",
            "source_id": "pump-1",
            "target_id": "valve-1",
            "relationship": "connections",
        }
    ],
    "evidence_map": {
        "pump-1": {"source_graph_node_id": "pump-1"},
        "valve-1": {"source_graph_node_id": "valve-1"},
    },
}

requires_souffle = pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)


def _tools() -> TopologyTools:
    return TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="routing-ritual-relax",
    )


def test_propose_temporary_datalog_is_offered_before_any_receipt() -> None:
    tools = _tools()
    tools.begin_request(QUESTION)
    names = {tool["function"]["name"] for tool in tools.tool_definitions()}
    assert "propose_temporary_datalog" in names
    assert "report_template_no_fit" in names


@requires_souffle
def test_paraphrased_propose_request_still_executes_after_no_fit() -> None:
    """Live DeepSeek failure mode: no-fit OK, propose used a rewritten request."""

    class NoFitThenParaphrasedPropose:
        def __init__(self) -> None:
            self.calls = 0

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            del tool_choice
            self.calls += 1
            offered = {tool["function"]["name"] for tool in tools}
            assert "propose_temporary_datalog" in offered
            if self.calls == 1:
                return ToolCall(
                    tool_name="report_template_no_fit",
                    tool_input={
                        "reason": "No bundled template covers this universal condition.",
                        "structured_intent": STRUCTURED_INTENT,
                    },
                    tool_call_id="no-fit-1",
                )
            if self.calls == 2:
                return ToolCall(
                    tool_name="propose_temporary_datalog",
                    tool_input={
                        "request": PARAPHRASED_REQUEST,
                        "generated_datalog": encode_structured_intent_program(
                            GENERATED_DATALOG,
                            STRUCTURED_INTENT,
                        ),
                        "formal_restatement": (
                            "Return every centrifugal pump without a reachable "
                            "ball valve."
                        ),
                        "faithfulness_review": FAITHFULNESS_REVIEW,
                    },
                    tool_call_id="generated-paraphrased",
                )
            return FinalAnswer(answer_text="Automatic generated logic completed.")

    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=_tools(),
        provider=NoFitThenParaphrasedPropose(),
    )
    propose = next(
        entry
        for entry in result.tool_call_trace
        if entry.get("tool_name") == "propose_temporary_datalog"
    )
    propose_result = propose["tool_result"]
    assert propose_result["status"] == "answered"
    assert propose_result.get("executed") is True
    assert propose_result.get("code") != "route.valid_receipt_required"


@requires_souffle
def test_direct_propose_without_prior_no_fit_executes_when_intent_supplied() -> None:
    """Agent may choose generated Datalog without a template no-fit ceremony."""

    class DirectPropose:
        def __init__(self) -> None:
            self.calls = 0

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            del tool_choice
            self.calls += 1
            if self.calls == 1:
                return ToolCall(
                    tool_name="propose_temporary_datalog",
                    tool_input={
                        "request": PARAPHRASED_REQUEST,
                        "generated_datalog": encode_structured_intent_program(
                            GENERATED_DATALOG,
                            STRUCTURED_INTENT,
                        ),
                        "formal_restatement": (
                            "Return every centrifugal pump without a reachable "
                            "ball valve."
                        ),
                        "faithfulness_review": FAITHFULNESS_REVIEW,
                    },
                    tool_call_id="direct-generated",
                )
            return FinalAnswer(answer_text="Automatic generated logic completed.")

    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=_tools(),
        provider=DirectPropose(),
    )
    assert [entry.get("tool_name") for entry in result.tool_call_trace] == [
        "propose_temporary_datalog"
    ]
    propose_result = result.tool_call_trace[0]["tool_result"]
    assert propose_result["status"] == "answered"
    assert propose_result.get("executed") is True
