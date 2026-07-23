"""
Behavioral contract tests for steering an active grounded-QA run.

Boundary: run_grounded_qa_turn() public function + TopologyTools.execute().
These tests assert what a caller observes when a human steers a run with
Answer Now / Stop or optional answer constraints -- never internal state,
message lists, or private helpers (bead pydexpi-datalog-1-3qo.9.8).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    STEER_ANSWER_NOW,
    STEER_STOP,
    FinalAnswer,
    RunConstraints,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

PUMP_ID = "node-pump-p101"
NOZZLE_ID = "node-nozzle-n1"
SEGMENT_ID = "node-segment-s1"
VALVE_ID = "node-valve-v102"

EDGE_PUMP_NOZZLE = "edge-pump-nozzle"
EDGE_NOZZLE_SEGMENT = "edge-nozzle-segment"
EDGE_SEGMENT_VALVE = "edge-segment-valve"

MINIMAL_TOPOLOGY: dict = {
    "nodes": [
        {"id": PUMP_ID, "label": "Pump", "tag_name": "P-101"},
        {"id": NOZZLE_ID, "label": "Nozzle", "tag_name": "N-1"},
        {"id": SEGMENT_ID, "label": "PipingSegment", "tag_name": "S-1"},
        {"id": VALVE_ID, "label": "Valve", "tag_name": "V-102"},
    ],
    "edges": [
        {
            "id": EDGE_PUMP_NOZZLE,
            "source_id": PUMP_ID,
            "target_id": NOZZLE_ID,
            "relationship": "has_nozzle",
        },
        {
            "id": EDGE_NOZZLE_SEGMENT,
            "source_id": NOZZLE_ID,
            "target_id": SEGMENT_ID,
            "relationship": "connected_to",
        },
        {
            "id": EDGE_SEGMENT_VALVE,
            "source_id": SEGMENT_ID,
            "target_id": VALVE_ID,
            "relationship": "connected_to",
        },
    ],
    "evidence_map": {
        PUMP_ID: {"id": PUMP_ID},
        NOZZLE_ID: {"id": NOZZLE_ID},
        SEGMENT_ID: {"id": SEGMENT_ID},
        VALVE_ID: {"id": VALVE_ID},
        EDGE_PUMP_NOZZLE: {"id": EDGE_PUMP_NOZZLE},
        EDGE_NOZZLE_SEGMENT: {"id": EDGE_NOZZLE_SEGMENT},
        EDGE_SEGMENT_VALVE: {"id": EDGE_SEGMENT_VALVE},
    },
}


def _make_tools() -> TopologyTools:
    return TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="steer-session")


class RecordingProvider:
    """Returns a scripted response per step and counts how many times the
    model was consulted, so a test can prove an interrupt stopped exploration
    before the next model call."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):
        index = self.calls
        self.calls += 1
        if index < len(self._responses):
            return self._responses[index]
        return FinalAnswer(answer_text="Model-authored answer that must not appear.")


def _steer_after(polls: int, directive: str) -> Callable[[], str | None]:
    """A steering poll that yields ``directive`` only from the given poll index
    onward. Polls happen once at the top of each round, so ``polls=1`` lets the
    first round run and interrupts at the second."""
    state = {"count": 0}

    def _poll() -> str | None:
        current = state["count"]
        state["count"] += 1
        return directive if current >= polls else None

    return _poll


def _reachable_call() -> ToolCall:
    return ToolCall(
        tool_name="get_reachable_equipment",
        tool_input={"equipment_id": PUMP_ID},
        tool_call_id="reach-1",
    )


def test_answer_now_without_verdict_reports_facts_and_blocker_without_guessing() -> (
    None
):
    provider = RecordingProvider(
        [
            _reachable_call(),
            # would explore further, but Answer Now must interrupt first
            ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "V-102"},
                tool_call_id="find-later",
            ),
        ]
    )

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        steering=_steer_after(1, STEER_ANSWER_NOW),
    )

    # Interrupted after exactly one model round: the second exploratory tool
    # was never launched.
    assert provider.calls == 1
    assert [t["tool_name"] for t in result.tool_call_trace] == [
        "get_reachable_equipment"
    ]
    assert result.steering_outcome == STEER_ANSWER_NOW
    # No validated verdict exists, so the answer must not fabricate a conclusion.
    assert result.deterministic_verdict is None
    assert result.source_grounded is False
    assert result.grounding_posture == POSTURE_SOURCE_DATA_UNAVAILABLE
    assert result.disclosure is not None
    # Established facts gathered so far are still reported as evidence.
    assert VALVE_ID in result.evidence_references
    lowered = result.answer_text.lower()
    assert "no validated verdict" in lowered or "no validated conclusion" in lowered


def test_answer_now_does_not_launch_additional_exploratory_tools() -> None:
    provider = RecordingProvider(
        [
            _reachable_call(),
            _reachable_call(),
            _reachable_call(),
        ]
    )

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        steering=_steer_after(1, STEER_ANSWER_NOW),
    )

    # Exactly one tool executed; no further exploration was launched.
    assert provider.calls == 1
    assert len(result.tool_call_trace) == 1
    assert result.steering_outcome == STEER_ANSWER_NOW


def test_answer_now_before_any_evidence_states_blocker_and_consults_no_model() -> None:
    provider = RecordingProvider([_reachable_call()])

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        steering=_steer_after(0, STEER_ANSWER_NOW),
    )

    # Interrupt precedes the first model call: nothing was explored.
    assert provider.calls == 0
    assert result.tool_call_trace == []
    assert result.steering_outcome == STEER_ANSWER_NOW
    assert result.source_grounded is False
    assert result.evidence_references == []
    assert result.deterministic_verdict is None


def test_stop_interrupts_the_run_and_preserves_the_completed_trace() -> None:
    provider = RecordingProvider(
        [
            _reachable_call(),
            ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "V-102"},
                tool_call_id="find-2",
            ),
            _reachable_call(),
        ]
    )

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        steering=_steer_after(2, STEER_STOP),
    )

    # Two rounds ran and were preserved; the third was never launched.
    assert provider.calls == 2
    assert [t["tool_name"] for t in result.tool_call_trace] == [
        "get_reachable_equipment",
        "find_equipment",
    ]
    assert result.steering_outcome == STEER_STOP
    # Stop never fabricates a grounded conclusion.
    assert result.source_grounded is False


def test_unsteered_run_is_unaffected_by_the_steering_parameter() -> None:
    provider = RecordingProvider(
        [
            _reachable_call(),
            FinalAnswer(
                answer_text="Pump P-101 reaches valve V-102.",
                evidence_references=[VALVE_ID],
            ),
        ]
    )

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        steering=lambda: None,
    )

    assert result.steering_outcome is None
    assert result.answer_text == "Pump P-101 reaches valve V-102."
    assert VALVE_ID in result.evidence_references


def test_answer_constraints_lower_the_turn_cap_and_synthesize_at_the_limit() -> None:
    provider = RecordingProvider([_reachable_call() for _ in range(10)])

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        max_rounds=8,
        constraints=RunConstraints(max_rounds=2),
    )

    # The user turn cap (2) binds below the operational ceiling (8).
    assert provider.calls == 2
    assert result.steering_outcome == "turn_limit"
    assert result.source_grounded is False


def test_answer_constraints_cannot_raise_the_operational_turn_ceiling() -> None:
    provider = RecordingProvider([_reachable_call() for _ in range(50)])

    # A user request for more turns than the operational ceiling is clamped to
    # the ceiling: the model is consulted at most `max_rounds` times, and the
    # operational exhaustion keeps its existing behavior (not a user turn_limit).
    with pytest.raises(RuntimeError):
        run_grounded_qa_turn(
            question="What is connected downstream of P-101?",
            topology_tools=_make_tools(),
            provider=provider,
            max_rounds=3,
            constraints=RunConstraints(max_rounds=50),
        )

    assert provider.calls == 3


def test_duration_constraint_ends_the_run_cleanly() -> None:
    provider = RecordingProvider([_reachable_call() for _ in range(10)])
    # Clock: start=0, first poll=0 (under limit), second poll=100 (over limit).
    ticks = iter([0.0, 0.0, 100.0])
    last = {"value": 100.0}

    def _clock() -> float:
        try:
            last["value"] = next(ticks)
        except StopIteration:
            pass
        return last["value"]

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        constraints=RunConstraints(max_duration_seconds=10.0),
        clock=_clock,
    )

    assert provider.calls == 1
    assert result.steering_outcome == "duration_limit"
    assert result.source_grounded is False


def test_provider_cost_constraint_ends_the_run_cleanly() -> None:
    provider = RecordingProvider([_reachable_call() for _ in range(10)])
    costs = iter([0.0, 10.0])
    last = {"value": 10.0}

    def _cost() -> float:
        try:
            last["value"] = next(costs)
        except StopIteration:
            pass
        return last["value"]

    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=_make_tools(),
        provider=provider,
        constraints=RunConstraints(max_provider_cost=5.0),
        provider_cost=_cost,
    )

    assert provider.calls == 1
    assert result.steering_outcome == "cost_limit"
    assert result.source_grounded is False


def test_capability_narrowing_refuses_a_disallowed_tool_at_the_backend() -> None:
    provider = RecordingProvider(
        [
            # The model tries a tool the user constrained away, then a permitted
            # one. The blocked tool must never execute; the permitted one runs.
            _reachable_call(),
            ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "V-102"},
                tool_call_id="find-allowed",
            ),
            FinalAnswer(
                answer_text="Valve V-102 is present.",
                evidence_references=[VALVE_ID],
            ),
        ]
    )

    result = run_grounded_qa_turn(
        question="Which equipment exists?",
        topology_tools=_make_tools(),
        provider=provider,
        constraints=RunConstraints(allowed_capabilities=frozenset({"find_equipment"})),
    )

    blocked = [
        t for t in result.tool_call_trace if t["tool_name"] == "get_reachable_equipment"
    ]
    assert blocked, "the disallowed tool call should be recorded as blocked"
    assert blocked[0]["tool_result"]["status"] == "capability_unavailable"
    # It was refused, not executed: no reachability payload was produced.
    assert "reachable" not in blocked[0]["tool_result"]
    executed = [t for t in result.tool_call_trace if t["tool_name"] == "find_equipment"]
    assert executed
    assert executed[0]["tool_result"].get("status") != "capability_unavailable"
    assert "matches" in executed[0]["tool_result"]


def test_capability_narrowing_cannot_grant_a_backend_unknown_tool() -> None:
    provider = RecordingProvider(
        [
            ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "V-102"},
                tool_call_id="find-1",
            ),
            FinalAnswer(answer_text="done", evidence_references=[VALVE_ID]),
        ]
    )

    # Requesting a capability the backend never exposed intersects to nothing:
    # narrowing can only remove real tools, never add a fabricated one.
    result = run_grounded_qa_turn(
        question="Which equipment exists?",
        topology_tools=_make_tools(),
        provider=provider,
        constraints=RunConstraints(
            allowed_capabilities=frozenset({"delete_source_graph"})
        ),
    )

    # Even a normally-authorized read-only tool is now blocked; no fabricated
    # capability was granted.
    statuses = {
        t["tool_name"]: t["tool_result"].get("status")
        for t in result.tool_call_trace
        if isinstance(t.get("tool_result"), dict)
    }
    assert statuses.get("find_equipment") == "capability_unavailable"
