"""Behavioral contracts for hybrid harness grounding (bead 1g7l).

Holdout SME retrieval prompts must accept find_equipment evidence, and bare
FinalAnswer thrash must fail closed instead of burning the full turn budget.
"""

from __future__ import annotations

from pydexpi_datalog.qa.grounded_qa_harness import (
    DEFAULT_MAX_ROUNDS,
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

PUMP_ID = "node-pump-p101"
NOZZLE_ID = "node-nozzle-n1"

MINIMAL_TOPOLOGY: dict = {
    "nodes": [
        {"id": PUMP_ID, "label": "Pump", "tag_name": "P-101"},
        {"id": NOZZLE_ID, "label": "Nozzle", "tag_name": "N-1"},
        {
            "id": "node-exchanger-h1009",
            "label": "PlateHeatExchanger",
            "tag_name": "H-1009",
        },
    ],
    "edges": [],
    "evidence_map": {
        PUMP_ID: {"id": PUMP_ID},
        NOZZLE_ID: {"id": NOZZLE_ID},
        "node-exchanger-h1009": {"id": "node-exchanger-h1009"},
    },
}

HOLDOUT_E04_RETRIEVAL = (
    "Does this drawing contain the plate heat exchanger tagged H-1009? "
    "If matches exist, answer violation_found and return every matching object "
    "as a witness; otherwise answer no_violation with no witnesses."
)

HOLDOUT_E05_RETRIEVAL = (
    "Does this drawing contain any nozzles? If matches exist, answer "
    "violation_found and return every matching object as a witness; otherwise "
    "answer no_violation with no witnesses."
)

COMPLIANCE_OWNERSHIP = (
    "Does every nozzle have exactly one incoming composition/nozzles "
    "ownership relationship?"
)


def _tools() -> TopologyTools:
    return TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="grounding-fix")


class _FindThenAnswer:
    """One find_equipment call, then a grounded FinalAnswer."""

    def __init__(self, *, pattern: str, evidence_id: str) -> None:
        self._pattern = pattern
        self._evidence_id = evidence_id
        self.calls = 0
        self.tool_choices: list[str] = []

    def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
        self.calls += 1
        self.tool_choices.append(tool_choice)
        if self.calls == 1:
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": self._pattern},
                tool_call_id="find-1",
            )
        return FinalAnswer(
            answer_text="violation_found",
            evidence_references=[self._evidence_id],
            grounding_posture="source_grounded",
        )


def test_holdout_tagged_retrieval_accepts_find_equipment_evidence() -> None:
    """SME grading vocabulary must not force a Datalog/template-only path."""
    provider = _FindThenAnswer(pattern="H-1009", evidence_id="node-exchanger-h1009")
    result = run_grounded_qa_turn(
        question=HOLDOUT_E04_RETRIEVAL,
        topology_tools=_tools(),
        provider=provider,
    )
    assert "could not ground" not in result.answer_text.lower()
    assert result.source_grounded is True
    assert "node-exchanger-h1009" in result.evidence_references
    assert provider.calls == 2
    assert any(
        entry.get("tool_name") == "find_equipment"
        for entry in result.tool_call_trace
    )


def test_holdout_existential_any_retrieval_accepts_find_equipment_evidence() -> None:
    provider = _FindThenAnswer(pattern="nozzle", evidence_id=NOZZLE_ID)
    result = run_grounded_qa_turn(
        question=HOLDOUT_E05_RETRIEVAL,
        topology_tools=_tools(),
        provider=provider,
    )
    assert "could not ground" not in result.answer_text.lower()
    assert result.source_grounded is True
    assert NOZZLE_ID in result.evidence_references
    assert provider.calls == 2


def test_real_compliance_quantifier_still_requires_rule_result_path() -> None:
    """Ownership/compliance questions must keep rule_result sufficiency."""

    class FindOnlyThenAnswer(_FindThenAnswer):
        pass

    provider = FindOnlyThenAnswer(pattern="pump", evidence_id=PUMP_ID)
    result = run_grounded_qa_turn(
        question=COMPLIANCE_OWNERSHIP,
        topology_tools=_tools(),
        provider=provider,
        max_rounds=4,
    )
    assert "could not ground" in result.answer_text.lower()
    sufficiency = [
        entry
        for entry in result.tool_call_trace
        if entry.get("tool_name") == "__evidence_sufficiency__"
    ]
    assert sufficiency
    assert any(
        (entry.get("tool_result") or {}).get("evidence_need") == "rule_result"
        for entry in sufficiency
    )


class _BareFinalAnswerForever:
    """Always answers in prose with no tool calls (live DeepSeek thrash shape)."""

    def __init__(self) -> None:
        self.calls = 0
        self.tool_choices: list[str] = []

    def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
        self.calls += 1
        self.tool_choices.append(tool_choice)
        return FinalAnswer(answer_text=f"Prose answer without tools #{self.calls}")


def test_bare_final_answer_thrash_fails_closed_before_full_budget() -> None:
    """Insufficient bare FinalAnswers must not burn the full operational budget."""
    provider = _BareFinalAnswerForever()
    result = run_grounded_qa_turn(
        question=HOLDOUT_E04_RETRIEVAL,
        topology_tools=_tools(),
        provider=provider,
    )
    assert provider.calls < DEFAULT_MAX_ROUNDS
    assert provider.calls <= 4
    assert "could not ground" in result.answer_text.lower()
    assert "required" in provider.tool_choices
    assert any(
        entry.get("tool_name") == "__evidence_sufficiency__"
        for entry in result.tool_call_trace
    )


def test_after_insufficient_answer_next_round_requires_a_tool() -> None:
    """After one insufficient FinalAnswer, the harness forces tool_choice=required."""

    class FirstProseThenFind(_BareFinalAnswerForever):
        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.calls += 1
            self.tool_choices.append(tool_choice)
            if self.calls == 1:
                return FinalAnswer(answer_text="Guessing without tools.")
            if self.calls == 2:
                assert tool_choice == "required"
                return ToolCall(
                    tool_name="find_equipment",
                    tool_input={"pattern": "H-1009"},
                    tool_call_id="forced-find",
                )
            return FinalAnswer(
                answer_text="violation_found",
                evidence_references=["node-exchanger-h1009"],
                grounding_posture="source_grounded",
            )

    provider = FirstProseThenFind()
    result = run_grounded_qa_turn(
        question=HOLDOUT_E04_RETRIEVAL,
        topology_tools=_tools(),
        provider=provider,
    )
    assert provider.tool_choices[0] == "auto"
    assert provider.tool_choices[1] == "required"
    assert result.source_grounded is True
    assert "node-exchanger-h1009" in result.evidence_references
