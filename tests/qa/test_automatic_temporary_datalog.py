"""Automatic execution of faithful generated Datalog (bead 3qo.9.9).

Behavior under test, through the public ``run_grounded_qa_turn`` /
``TopologyTools`` seams:

- A gate-passing temporary Datalog proposal executes immediately through real Souffle and
  the turn continues to a model-authored final answer -- no confirmation
  state is ever created.
- The executed tool result discloses the restatement, source scope, route,
  validation outcomes, collapsed inspectable Datalog, deterministic result,
  and evidence, and carries a minimal audit record.
- Generated logic stays temporary: nothing grants reusable-rule trust.
- Gate failures never execute.
"""

from __future__ import annotations

import shutil

import pytest

from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_SOURCE_GROUNDED,
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools

QUESTION = "Must every CentrifugalPump have a reachable BallValve?"
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


def make_tools() -> TopologyTools:
    return TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="automatic-datalog-test",
    )


class GeneratedFallbackProvider:
    """No-fit -> proposal -> (automatic mode) final grounded answer."""

    def __init__(self) -> None:
        self.calls = 0
        self.saw_executed_result = False

    def complete_with_tools(self, *, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template represents this universal condition.",
                    "structured_intent": STRUCTURED_INTENT,
                },
                tool_call_id="no-fit-1",
            )
        if self.calls == 2:
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": QUESTION,
                    "generated_datalog": encode_structured_intent_program(
                        GENERATED_DATALOG,
                        STRUCTURED_INTENT,
                    ),
                    "formal_restatement": (
                        "Return every centrifugal pump without a reachable ball valve."
                    ),
                    "faithfulness_review": FAITHFULNESS_REVIEW,
                },
                tool_call_id="generated-1",
            )
        self.saw_executed_result = any(
            message.get("role") == "tool"
            and '"executed": true' in message.get("content", "")
            for message in messages
        )
        return FinalAnswer(
            answer_text="Every centrifugal pump has a reachable ball valve.",
            grounding_posture=POSTURE_SOURCE_GROUNDED,
        )


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_gate_passing_proposal_executes_automatically() -> None:
    provider = GeneratedFallbackProvider()

    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=make_tools(),
        provider=provider,
    )

    proposal_trace = next(
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    )
    executed = proposal_trace["tool_result"]

    # Executed immediately, turn continued to the model's final answer.
    assert executed["status"] == "answered"
    assert executed["executed"] is True
    assert executed["execution_mode"] == "automatic"
    assert provider.calls == 3
    assert provider.saw_executed_result is True
    assert "confirmation" not in result.answer_text.lower()

    # No confirmation state anywhere in the executed result.
    assert executed["confirmation"] == {"required": False}
    assert "proposal" not in executed

    # Post-execution semantic disclosure.
    disclosure = executed["disclosure"]
    assert disclosure["restatement"] == (
        "Return every centrifugal pump without a reachable ball valve."
    )
    assert disclosure["source_scope"]["graph"] == "drawing-v1"
    assert disclosure["route"] == "generated_temporary_datalog"
    assert disclosure["validation"]["status"] == "safe_to_confirm"
    assert disclosure["counterfactual_validation"]["status"] in {
        "passed",
        "not_applicable",
    }
    assert disclosure["faithfulness_gate"]["status"] == "passed"
    assert disclosure["inspectable_datalog"]["display"] == "collapsed"
    assert "answer(P)" in disclosure["inspectable_datalog"]["generated_datalog"]
    assert disclosure["deterministic_result"]["matched_object_ids"] == []
    assert executed["evidence"]["display"] == "expandable"

    # Route artifact: route, program identity, gates, repair summary, latency.
    route_artifact = executed["route_artifact"]
    assert route_artifact["route"] == "generated_temporary_datalog"
    assert route_artifact["execution_mode"] == "automatic"
    assert route_artifact["engine"] == "souffle"
    assert len(route_artifact["program_id"]) == 64
    assert route_artifact["faithfulness_gate"]["status"] == "passed"
    assert route_artifact["repair_summary"]["gate_attempts"] == 1
    assert route_artifact["repair_summary"]["failed_gate_attempts"] == 0
    assert route_artifact["execution"]["latency_seconds"] >= 0.0

    # Temporary trust only: no reusable-rule promotion.
    assert route_artifact["trust"] == {
        "temporary": True,
        "reusable_rule_trust": False,
        "promotion": "separate_explicit_authoring_action",
    }

    # Minimal audit record travels with the result for durable persistence.
    audit = executed["audit_record"]
    assert audit["route"] == "generated_temporary_datalog"
    assert audit["program_id"] == route_artifact["program_id"]
    assert audit["decision"] == "automatic_execution"
    assert audit["executed"] is True
    assert audit["faithfulness_gate"]["status"] == "passed"

    # The harness surfaces the deterministic artifact and grounds the answer.
    assert result.route_artifact is not None
    assert result.route_artifact["route"] == "generated_temporary_datalog"
    assert result.grounding_posture == POSTURE_SOURCE_GROUNDED
    assert result.source_grounded is True
    assert result.disclosure is None


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_trace_events_disclose_the_automatic_generated_route() -> None:
    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=make_tools(),
        provider=GeneratedFallbackProvider(),
    )

    assert [event["event"] for event in result.trace_events] == [
        "generated_proposed",
        "generated_gates_passed",
        "generated_executed",
        "result_observed",
    ]


def test_gate_failure_never_executes_automatically() -> None:
    """Execution is authorized only after every mandatory gate passes."""
    tools = make_tools()
    tools.begin_request(QUESTION)
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template represents this universal condition.",
            "structured_intent": STRUCTURED_INTENT,
        },
    )

    vetoed = tools.execute(
        "propose_temporary_datalog",
        {
            "request": QUESTION,
            "generated_datalog": encode_structured_intent_program(
                GENERATED_DATALOG,
                STRUCTURED_INTENT,
            ),
            "formal_restatement": (
                "Return every centrifugal pump without a reachable ball valve."
            ),
            "faithfulness_review": {
                "status": "unfaithful",
                "back_translated_intent": STRUCTURED_INTENT,
                "diagnostics": [
                    {
                        "code": "model_review.mismatch",
                        "message": "Back-translation does not match the request.",
                    }
                ],
            },
        },
    )

    assert vetoed["status"] == "rejected"
    assert vetoed["executed"] is False
    assert "route_artifact" not in vetoed


def test_automatic_execution_requires_a_route_receipt() -> None:
    """Automatic execution never bypasses the backend receipt precondition."""
    tools = make_tools()
    tools.begin_request(QUESTION)

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": QUESTION,
            "generated_datalog": encode_structured_intent_program(
                GENERATED_DATALOG,
                STRUCTURED_INTENT,
            ),
            "formal_restatement": (
                "Return every centrifugal pump without a reachable ball valve."
            ),
            "faithfulness_review": FAITHFULNESS_REVIEW,
        },
    )

    assert result["status"] == "rejected"
    assert result["code"] == "route.valid_receipt_required"
    assert result["executed"] is False
