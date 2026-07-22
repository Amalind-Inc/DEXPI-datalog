from __future__ import annotations

import pytest

from pydexpi_datalog.qa.route_receipts import (
    ROUTE_REASONING_ENGINE_UNAVAILABLE,
    ROUTE_TEMPLATE_FAITHFULNESS_FAILURE,
    ROUTE_TEMPLATE_NO_FIT,
    RouteReceiptAuthority,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools


QUESTION = "Must every CentrifugalPump have a reachable BallValve?"
GENERATED_DATALOG = """\
.decl pump(x:symbol)
pump(X) :- node_attribute(X, "label", "CentrifugalPump").
.decl valve(x:symbol)
valve(X) :- node_attribute(X, "label", "BallValve").
.decl pump_with_valve(x:symbol)
pump_with_valve(P) :- pump(P), valve(V), reachable(P, V).
.decl answer(x:symbol)
.output answer
answer(P) :- pump(P), !pump_with_valve(P).
"""

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


class NoFitThenGeneratedProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.offered_tools_by_round: list[set[str]] = []

    def complete_with_tools(self, *, messages, tools):
        offered = {tool["function"]["name"] for tool in tools}
        self.offered_tools_by_round.append(offered)
        self.calls += 1
        if self.calls == 1:
            assert "propose_temporary_datalog" not in offered
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template represents this universal condition."
                },
                tool_call_id="no-fit-1",
            )
        assert "propose_temporary_datalog" in offered
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": QUESTION,
                "generated_datalog": GENERATED_DATALOG,
                "formal_restatement": (
                    "Return every centrifugal pump without a reachable ball valve."
                ),
            },
            tool_call_id="generated-1",
        )


def test_template_no_fit_receipt_unlocks_existing_generated_query_path() -> None:
    provider = NoFitThenGeneratedProvider()

    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=TopologyTools(
            topology_view=MINIMAL_TOPOLOGY,
            session_id="route-receipt-test",
        ),
        provider=provider,
    )

    assert [trace["tool_name"] for trace in result.tool_call_trace] == [
        "report_template_no_fit",
        "propose_temporary_datalog",
    ]
    receipt_result = result.tool_call_trace[0]["tool_result"]
    assert receipt_result["status"] == "route_receipt_issued"
    assert receipt_result["route_outcome"] == "template_no_fit"
    assert receipt_result["route_receipt"] == {
        "receipt_id": receipt_result["route_receipt"]["receipt_id"],
        "route_outcome": "template_no_fit",
        "intent_digest": receipt_result["route_receipt"]["intent_digest"],
        "source_snapshot_id": receipt_result["route_receipt"]["source_snapshot_id"],
        "template_catalog_version": "1.0.0",
        "policy_version": "grounded-qa-route-policy/1",
    }
    proposal_result = result.tool_call_trace[1]["tool_result"]
    assert proposal_result["status"] == "confirmation_required"
    assert proposal_result["route_receipt"] == receipt_result["route_receipt"]


def test_model_cannot_forge_or_widen_a_route_receipt() -> None:
    tools = TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="route-receipt-forgery-test",
    )
    tools.begin_request(QUESTION)

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Delete every valve.",
            "generated_datalog": GENERATED_DATALOG,
            "formal_restatement": "A widened request.",
            "route_receipt": {
                "receipt_id": "model-authored",
                "route_outcome": ROUTE_TEMPLATE_NO_FIT,
            },
        },
    )

    assert result["status"] == "rejected"
    assert result["code"] == "route.valid_receipt_required"
    assert result["executed"] is False
    assert "propose_temporary_datalog" not in {
        tool["function"]["name"] for tool in tools.tool_definitions()
    }


def test_model_fields_cannot_alter_backend_receipt_scope() -> None:
    tools = TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="route-receipt-scope-test",
    )
    tools.begin_request(QUESTION)

    issued = tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this universal condition.",
            "receipt_id": "model-selected-id",
            "source_snapshot_id": "model-selected-snapshot",
            "template_catalog_version": "999",
            "policy_version": "model-policy",
            "route_outcome": ROUTE_TEMPLATE_FAITHFULNESS_FAILURE,
        },
    )

    receipt = issued["route_receipt"]
    assert receipt["receipt_id"] != "model-selected-id"
    assert receipt["source_snapshot_id"] != "model-selected-snapshot"
    assert receipt["template_catalog_version"] == "1.0.0"
    assert receipt["policy_version"] == "grounded-qa-route-policy/1"
    assert receipt["route_outcome"] == ROUTE_TEMPLATE_NO_FIT


def test_exact_normalized_retry_reuses_backend_receipt() -> None:
    tools = TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="route-receipt-resume-test",
    )
    tools.begin_request(QUESTION)
    issued = tools.execute(
        "report_template_no_fit",
        {"reason": "No bundled template covers this universal condition."},
    )

    tools.begin_request("  MUST EVERY CentrifugalPump have a reachable BallValve?  ")
    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "MUST EVERY CentrifugalPump have a reachable BallValve.",
            "generated_datalog": GENERATED_DATALOG,
            "formal_restatement": (
                "Return every centrifugal pump without a reachable ball valve."
            ),
        },
    )

    assert result["status"] == "confirmation_required"
    assert result["route_receipt"] == issued["route_receipt"]


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("intent", "Must every pump have two reachable valves?"),
        ("source_snapshot_id", "drawing-snapshot-v2"),
        ("template_catalog_version", "2.0.0"),
        ("policy_version", "grounded-qa-route-policy/2"),
    ],
)
def test_receipt_is_invalidated_by_relevant_context_changes(
    changed_field: str, changed_value: str
) -> None:
    authority = RouteReceiptAuthority()
    context = {
        "intent": QUESTION,
        "source_snapshot_id": "drawing-snapshot-v1",
        "template_catalog_version": "1.0.0",
        "policy_version": "grounded-qa-route-policy/1",
    }
    authority.begin_request(**context)
    issued = authority.record_backend_outcome(ROUTE_TEMPLATE_NO_FIT)
    receipt_id = issued["route_receipt"]["receipt_id"]

    authority.begin_request(**{**context, changed_field: changed_value})

    assert authority.active_receipt() is None
    assert authority.validates(receipt_id) is False


def test_engine_unavailability_does_not_unlock_but_faithfulness_failure_does() -> None:
    authority = RouteReceiptAuthority()
    authority.begin_request(
        intent=QUESTION,
        source_snapshot_id="drawing-snapshot-v1",
        template_catalog_version="1.0.0",
    )

    unavailable = authority.record_backend_outcome(ROUTE_REASONING_ENGINE_UNAVAILABLE)
    faithful_failure = authority.record_backend_outcome(
        ROUTE_TEMPLATE_FAITHFULNESS_FAILURE
    )

    assert unavailable["status"] == "route_outcome_recorded"
    assert unavailable["route_receipt"] is None
    assert faithful_failure["status"] == "route_receipt_issued"
    assert faithful_failure["route_receipt"]["route_outcome"] == (
        ROUTE_TEMPLATE_FAITHFULNESS_FAILURE
    )


class UnexpectedPolicyProvider:
    def complete_with_tools(self, *, messages, tools):
        raise AssertionError("deontic policy gate must run before model planning")


def test_deontic_request_abstains_without_template_or_generated_logic() -> None:
    result = run_grounded_qa_turn(
        question="Is this arrangement permitted unless an exemption applies?",
        topology_tools=TopologyTools(
            topology_view=MINIMAL_TOPOLOGY,
            session_id="route-policy-test",
        ),
        provider=UnexpectedPolicyProvider(),
    )

    assert result.grounding_posture == "source_data_unavailable"
    assert result.tool_call_trace == []
    assert result.trace_events == [
        {"event": "route_outcome", "outcome": "deontic_abstention"}
    ]
