"""Authoring scaffold on temporary-Datalog proposal reject (bead imdi)."""

from __future__ import annotations

import shutil

import pytest

from pydexpi_datalog.qa.grounded_qa_harness import (
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

QUESTION = "Must every CentrifugalPump have a reachable BallValve?"
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

# Intentionally invalid: missing decls/output, invents predicates, no intent guard.
BAD_PROGRAM = """\
answer(P) :- compCount(P, N), N < 1.
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

requires_souffle = pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)


def _tools() -> TopologyTools:
    return TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="authoring-scaffold",
    )


def test_proposal_reject_includes_authoring_scaffold_with_approved_predicates() -> None:
    tools = _tools()
    tools.begin_request(QUESTION)
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this universal condition.",
            "structured_intent": STRUCTURED_INTENT,
        },
    )

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": QUESTION,
            "generated_datalog": BAD_PROGRAM,
            "formal_restatement": "Broken proposal.",
            "faithfulness_review": FAITHFULNESS_REVIEW,
        },
    )

    assert result["status"] == "rejected"
    assert result["code"] == "tool.proposal_rejected"
    scaffold = result["authoring_scaffold"]
    assert isinstance(scaffold, dict)
    assert "answer" in scaffold["approved_predicates"]
    assert "node_attribute" in scaffold["approved_predicates"]
    assert "compCount" not in scaffold["approved_predicates"]
    skeleton = scaffold["program_skeleton"]
    assert ".decl answer(x:symbol)" in skeleton
    assert ".output answer" in skeleton
    assert "query_intent_contract(" in skeleton
    assert "answer(" in skeleton
    assert scaffold["instructions"]
    assert isinstance(scaffold["diagnostic_codes"], list)
    assert scaffold["diagnostic_codes"]


@requires_souffle
def test_harness_caps_propose_rejects_and_surfaces_scaffold_in_trace() -> None:
    """Repeated bad proposes must fail closed instead of thrashing for 20 turns."""

    class AlwaysBadPropose:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_results_seen: list[dict[str, object]] = []

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            del tool_choice
            self.calls += 1
            for message in messages:
                if message.get("role") != "tool":
                    continue
                content = message.get("content")
                if isinstance(content, str) and "authoring_scaffold" in content:
                    import json

                    try:
                        self.tool_results_seen.append(json.loads(content))
                    except json.JSONDecodeError:
                        pass
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": QUESTION,
                    "generated_datalog": BAD_PROGRAM,
                    "formal_restatement": "Broken proposal.",
                    "faithfulness_review": FAITHFULNESS_REVIEW,
                },
                tool_call_id=f"bad-{self.calls}",
            )

    provider = AlwaysBadPropose()
    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=_tools(),
        provider=provider,
    )

    propose_traces = [
        entry
        for entry in result.tool_call_trace
        if entry.get("tool_name") == "propose_temporary_datalog"
    ]
    assert 1 <= len(propose_traces) <= 3
    assert provider.calls <= 3
    assert "faithful generated program" in result.answer_text.lower()
    first = propose_traces[0]["tool_result"]
    assert "authoring_scaffold" in first
    assert provider.tool_results_seen
    assert "authoring_scaffold" in provider.tool_results_seen[0]
