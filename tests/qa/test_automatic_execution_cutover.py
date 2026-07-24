"""Cut over automatic read-only execution and retire confirmation (3qo.9.9).

Seams: ``run_grounded_qa_turn`` / ``TopologyTools``, capability manifest.
"""

from __future__ import annotations

import shutil

import pytest

from pydexpi_datalog.qa.capability_manifest import (
    PERMISSION_ALLOWED_READ_ONLY,
    default_grounded_qa_manifest,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_SOURCE_GROUNDED,
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import (
    AutomaticExecutionUnavailableError,
    TemporaryDatalogValidatorBundle,
    TopologyTools,
)

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


class GeneratedFallbackProvider:
    def __init__(self) -> None:
        self.calls = 0

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
        return FinalAnswer(
            answer_text="Every centrifugal pump has a reachable ball valve.",
            grounding_posture=POSTURE_SOURCE_GROUNDED,
        )


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_released_default_executes_generated_query_without_confirmation() -> None:
    """Released TopologyTools has no migration guard and never pauses for
    read-only generated-query confirmation."""
    tools = TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="cutover-default-auto",
    )
    provider = GeneratedFallbackProvider()

    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=tools,
        provider=provider,
    )

    proposal_trace = next(
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    )
    executed = proposal_trace["tool_result"]

    assert executed["status"] == "answered"
    assert executed["executed"] is True
    assert executed["execution_mode"] == "automatic"
    assert executed["confirmation"] == {"required": False}
    assert "proposal" not in executed
    assert "confirmation" not in result.answer_text.lower()
    assert provider.calls == 3


def test_released_manifest_treats_temporary_datalog_as_allowed_read_only() -> None:
    proposal = default_grounded_qa_manifest().require("propose_temporary_datalog")

    assert proposal.permission_class == PERMISSION_ALLOWED_READ_ONLY
    assert "confirmation" not in " ".join(proposal.limitations).lower()
    assert "automatic" in " ".join(proposal.limitations).lower() or (
        "validated" in " ".join(proposal.limitations).lower()
    )


def test_automatic_mode_refuses_when_mandatory_validator_unavailable() -> None:
    with pytest.raises(AutomaticExecutionUnavailableError) as raised:
        TopologyTools(
            topology_view=MINIMAL_TOPOLOGY,
            session_id="cutover-missing-validator",
            validators=TemporaryDatalogValidatorBundle(
                mechanical_safety=TemporaryDatalogValidatorBundle.production().mechanical_safety,
                counterfactual_probes=TemporaryDatalogValidatorBundle.production().counterfactual_probes,
                layered_faithfulness_gate=None,
            ),
        )

    assert "layered_faithfulness_gate" in str(raised.value)
    assert "confirmation" not in str(raised.value).lower()
