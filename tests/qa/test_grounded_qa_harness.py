"""
Behavioral contract tests for the grounded QA harness.

Boundary: run_grounded_qa_turn() public function + TopologyTools.execute()
These tests do not inspect message lists, tool call counts, or internal state.
They assert what a caller observes: answer text, evidence references, witnesses.
"""

import re
import shutil

import pytest

from pydexpi_datalog.qa import counterfactual_probes
from pydexpi_datalog.qa.grounded_qa_harness import (
    DEFAULT_MAX_ROUNDS,
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_NEEDS_CLARIFICATION,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    POSTURE_UNSUPPORTED_SOURCE_CLAIM,
    ConversationTurn,
    FinalAnswer,
    QATurnResult,
    ScriptedQATurnProvider,
    ToolCall,
    compact_conversation,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools


def _rejection_feedback_from_messages(messages: list[dict[str, object]]) -> str | None:
    """Prefer the tool rejection payload; fall back to harness repair nudges."""
    for message in reversed(messages):
        role = message.get("role")
        content = str(message.get("content", ""))
        if role == "tool" and (
            '"status": "rejected"' in content or '"status":"rejected"' in content
        ):
            return content
    for message in reversed(messages):
        content = str(message.get("content", ""))
        if message.get("role") == "user" and content.startswith(
            "Temporary Datalog proposal rejected"
        ):
            return content
    return None


# ---------------------------------------------------------------------------
# Minimal topology fixture
# ---------------------------------------------------------------------------

PUMP_ID = "node-pump-p101"
NOZZLE_ID = "node-nozzle-n1"
SEGMENT_ID = "node-segment-s1"
VALVE_ID = "node-valve-v102"
LEGACY_TEMPORARY_INTENT = {
    "source_classes": ["TopologyObject"],
    "target_classes": ["TopologyObject"],
    "source_role": "resolved_source",
    "target_role": "reachable_result",
    "graph_scope": "all_topology",
    "direction": "directed",
    "quantifier": "any",
    "negated": False,
    "output_obligations": ["answer_ids"],
}


def _faithful_review(intent: dict[str, object]) -> dict[str, object]:
    return {
        "status": "faithful",
        "back_translated_intent": intent,
        "diagnostics": [],
    }


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


def make_tools(topology: dict = MINIMAL_TOPOLOGY) -> TopologyTools:
    return TopologyTools(topology_view=topology, session_id="test-session")


def make_graph_facts_backed_tools() -> TopologyTools:
    topology = {
        **MINIMAL_TOPOLOGY,
        "nodes": [
            {**node, "source_graph_node_id": node["id"]}
            for node in MINIMAL_TOPOLOGY["nodes"]
        ],
        "edges": [
            {
                **edge,
                "source_graph_edge": {
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "edge_key": edge["id"],
                },
            }
            for edge in MINIMAL_TOPOLOGY["edges"]
        ],
    }
    graph_facts = {
        "fixture_id": "minimal-topology-tools",
        "source_path": "minimal.xml",
        "graph": {"node_count": 4, "edge_count": 3},
        "facts": {
            "nodes": [
                {
                    "fact_type": "node",
                    "node_id": node["id"],
                    "attributes": {
                        "label": node["label"],
                        "tagName": node.get("tag_name", ""),
                    },
                }
                for node in MINIMAL_TOPOLOGY["nodes"]
            ],
            "edges": [
                {
                    "fact_type": "edge",
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "edge_key": edge["id"],
                    "attributes": {
                        "label": "reference",
                        "attr_name": "connections",
                    },
                }
                for edge in MINIMAL_TOPOLOGY["edges"]
            ],
        },
        "provenance": {"extractor": "test"},
    }
    return TopologyTools(
        topology_view=topology,
        session_id="test-session",
        graph_facts=graph_facts,
    )


class LookupOnlyThenWitnessProvider:
    def __init__(self) -> None:
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        step = self._step
        self._step += 1
        if step == 0:
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "P-101"},
                tool_call_id="find-only",
            )
        if step == 1:
            return FinalAnswer(
                answer_text="Pump P-101 is connected downstream.",
                evidence_references=[PUMP_ID],
            )
        if step == 2:
            return ToolCall(
                tool_name="get_reachable_equipment",
                tool_input={"equipment_id": PUMP_ID},
                tool_call_id="retrieve-witness",
            )
        return FinalAnswer(
            answer_text="Pump P-101 has a witnessed structural path.",
            evidence_references=[PUMP_ID, VALVE_ID],
        )


class SampledPathThenDatalogProvider:
    def __init__(self) -> None:
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        step = self._step
        self._step += 1
        if step == 0:
            return ToolCall(
                tool_name="get_reachable_equipment",
                tool_input={"equipment_id": PUMP_ID},
                tool_call_id="sample-one-path",
            )
        if step == 1:
            return FinalAnswer(
                answer_text="All pumps have reachable valves.",
                evidence_references=[PUMP_ID, VALVE_ID],
            )
        if step == 2:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No template covers this universal rule.",
                    "structured_intent": LEGACY_TEMPORARY_INTENT,
                },
                tool_call_id="sample-no-fit",
            )
        if step == 3:
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Do all pumps have a reachable valve?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n.output answer\n"
                            f'answer(x) :- reachable("{PUMP_ID}", x).'
                        ),
                        LEGACY_TEMPORARY_INTENT,
                    ),
                    "formal_restatement": "Return objects reachable from pump P-101.",
                    "faithfulness_review": _faithful_review(LEGACY_TEMPORARY_INTENT),
                    "resolved_identity_ids": [PUMP_ID],
                },
                tool_call_id="escalate-datalog",
            )
        return FinalAnswer(answer_text="Automatic generated logic completed.")


class ImmediateConversationProvider:
    def complete_with_tools(self, *, messages, tools):
        return FinalAnswer(answer_text="Happy to help.")


class UnexpectedProviderCall:
    def complete_with_tools(self, *, messages, tools):
        raise AssertionError(
            "source mutation requests should be denied before model use"
        )


def test_topology_relationship_answer_requires_structural_witness_before_acceptance():
    result = run_grounded_qa_turn(
        question="What is connected downstream of P-101?",
        topology_tools=make_tools(),
        provider=LookupOnlyThenWitnessProvider(),
    )

    assert result.answer_text == "Pump P-101 has a witnessed structural path."
    assert VALVE_ID in result.evidence_references
    sufficiency_events = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "__evidence_sufficiency__"
    ]
    assert sufficiency_events
    assert sufficiency_events[0]["tool_result"]["suggested_next_tools"] == [
        "get_reachable_equipment"
    ]


def test_universal_claim_from_sampled_path_escalates_to_automatic_logic():
    result = run_grounded_qa_turn(
        question="Do all pumps have a reachable valve?",
        topology_tools=make_tools(),
        provider=SampledPathThenDatalogProvider(),
    )

    assert result.answer_text == "Automatic generated logic completed."
    tool_names = [trace["tool_name"] for trace in result.tool_call_trace]
    assert "__evidence_sufficiency__" in tool_names
    assert "propose_temporary_datalog" in tool_names


class AnswerAfterProposalProvider:
    """Authors a final answer after observing automatic execution."""

    def __init__(self) -> None:
        self.calls_after_proposal = 0
        self._routed = False
        self._proposed = False

    def complete_with_tools(self, *, messages, tools):
        if not self._routed:
            self._routed = True
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No template covers this segment rule.",
                    "structured_intent": LEGACY_TEMPORARY_INTENT,
                },
                tool_call_id="proposal-no-fit",
            )
        if not self._proposed:
            self._proposed = True
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every segment reach a valve?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n.output answer\n"
                            f'answer(x) :- reachable("{SEGMENT_ID}", x).'
                        ),
                        LEGACY_TEMPORARY_INTENT,
                    ),
                    "formal_restatement": "Return objects reachable from segment S-1.",
                    "faithfulness_review": _faithful_review(LEGACY_TEMPORARY_INTENT),
                    "resolved_identity_ids": [SEGMENT_ID],
                },
                tool_call_id="proposal-shortcircuit",
            )
        self.calls_after_proposal += 1
        return FinalAnswer(answer_text="Model-authored answer after execution.")


def test_automatic_proposal_continues_to_model_answer():
    """An executed proposal is returned to the model before its final answer."""
    provider = AnswerAfterProposalProvider()
    result = run_grounded_qa_turn(
        question="Must every segment reach a valve?",
        topology_tools=make_tools(),
        provider=provider,
    )

    assert provider.calls_after_proposal == 1
    assert result.answer_text == "Model-authored answer after execution."
    proposal_traces = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposal_traces) == 1
    executed = proposal_traces[0]["tool_result"]
    assert executed["status"] == "answered"
    assert executed["executed"] is True
    assert executed["confirmation"] == {"required": False}


class RetryAfterRejectionProvider:
    """Mirrors the live 3cq follow-up: the first proposal omits `.output
    answer` (exactly what the BYOK model generated live). The harness must
    hand the rejection back to the model as tool feedback instead of pausing
    the turn, and the corrected re-proposal executes automatically."""

    def __init__(self) -> None:
        self.rejection_feedback: list[str] = []
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        if self._step == 0:
            self._step += 1
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No template covers this segment rule.",
                    "structured_intent": LEGACY_TEMPORARY_INTENT,
                },
                tool_call_id="retry-no-fit",
            )
        if self._step == 1:
            self._step += 1
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every segment reach a valve?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n"
                            f'answer(x) :- reachable("{SEGMENT_ID}", x).'
                        ),
                        LEGACY_TEMPORARY_INTENT,
                    ),
                    "formal_restatement": "Return objects reachable from segment S-1.",
                    "faithfulness_review": _faithful_review(LEGACY_TEMPORARY_INTENT),
                    "resolved_identity_ids": [SEGMENT_ID],
                },
                tool_call_id="proposal-invalid",
            )
        if self._step == 2:
            self._step += 1
            feedback = _rejection_feedback_from_messages(messages)
            if feedback is not None:
                self.rejection_feedback.append(feedback)
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every segment reach a valve?",
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n.output answer\n"
                            f'answer(x) :- reachable("{SEGMENT_ID}", x).'
                        ),
                        LEGACY_TEMPORARY_INTENT,
                    ),
                    "formal_restatement": "Return objects reachable from segment S-1.",
                    "faithfulness_review": _faithful_review(LEGACY_TEMPORARY_INTENT),
                    "resolved_identity_ids": [SEGMENT_ID],
                },
                tool_call_id="proposal-corrected",
            )
        return FinalAnswer(answer_text="Model-authored answer after automatic execution.")


def test_rejected_proposal_feeds_back_to_model_and_never_pauses():
    """An invalid temporary-Datalog proposal must not reach the user as a
    confirmation card (it can never execute). The rejection diagnostics go
    back to the model as an ordinary tool result so it can revise within the
    same turn; the corrected proposal executes automatically."""
    provider = RetryAfterRejectionProvider()
    result = run_grounded_qa_turn(
        question="Must every segment reach a valve?",
        topology_tools=make_tools(),
        provider=provider,
    )

    proposal_traces = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposal_traces) == 2
    assert proposal_traces[0]["tool_result"]["status"] == "rejected"
    invalid_gate = proposal_traces[0]["tool_result"]
    assert invalid_gate["counterfactual_validation"]["status"] == "not_applicable"
    assert (
        invalid_gate["faithfulness_gate"]["layers"]["counterfactual"]["status"]
        == "passed"
    )
    assert len(invalid_gate["faithfulness_gate_attempts"]) == 1
    assert proposal_traces[1]["tool_result"]["status"] == "answered"
    assert proposal_traces[1]["tool_result"]["executed"] is True
    assert (
        proposal_traces[1]["tool_result"]["validation"]["status"] == "safe_to_confirm"
    )
    # The model saw the rejection diagnostics and the authoring contract.
    assert provider.rejection_feedback
    assert "answer(x:symbol)" in provider.rejection_feedback[0]
    # The executed proposal is the corrected program, not the invalid one.
    assert ".output answer" in str(
        proposal_traces[1]["tool_result"]["disclosure"]["inspectable_datalog"][
            "generated_datalog"
        ]
    )


STRUCTURED_CONNECTIVITY_INTENT = {
    "source_classes": ["CentrifugalPump", "ReciprocatingPump"],
    "target_classes": ["BallValve"],
    "source_role": "equipment",
    "target_role": "reachable_object",
    "graph_scope": "piping_only",
    "direction": "undirected",
    "quantifier": "all",
    "negated": True,
    "output_obligations": ["violating_source_ids"],
}


def _faithful_structured_connectivity_program() -> str:
    return "\n".join(
        [
            ".decl source(x:symbol)",
            'source(X) :- node_attribute(X, "label", "CentrifugalPump").',
            'source(X) :- node_attribute(X, "label", "ReciprocatingPump").',
            ".decl target(x:symbol)",
            'target(X) :- node_attribute(X, "label", "BallValve").',
            ".decl has_target(x:symbol)",
            "has_target(Source) :- source(Source), target(Target), "
            "piping_connected(Source, Target).",
            ".decl answer(x:symbol)",
            ".output answer",
            "answer(Source) :- source(Source), !has_target(Source).",
        ]
    )


COUNTERFACTUAL_CONNECTIVITY_INTENT = {
    "source_classes": ["Tank"],
    "target_classes": ["CentrifugalPump"],
    "source_role": "process_equipment",
    "target_role": "pump",
    "graph_scope": "piping_only",
    "direction": "undirected",
    "quantifier": "all",
    "negated": True,
    "output_obligations": ["violating_source_ids"],
}


def _counterfactual_connectivity_program(*, faithful: bool) -> str:
    rules = [
        ".decl source(x:symbol)",
        'source(X) :- node_attribute(X, "label", "Tank").',
        ".decl pump(x:symbol)",
        'pump(X) :- node_attribute(X, "label", "CentrifugalPump").',
    ]
    rules.append(".decl has_pump(x:symbol)")
    if faithful:
        rules.append(
            "has_pump(Source) :- source(Source), pump(Target), "
            "piping_connected(Source, Target)."
        )
    else:
        rules.append(
            "has_pump(Source) :- source(Source), pump(Target), "
            "piping_connected(Source, Target), graph_edge(Source, Target, _)."
        )
    answer_rule = "answer(X) :- source(X), !has_pump(X)."
    rules.extend(
        [
            ".decl answer(x:symbol)",
            ".output answer",
            answer_rule,
        ]
    )
    return encode_structured_intent_program(
        "\n".join(rules),
        COUNTERFACTUAL_CONNECTIVITY_INTENT,
    )


class RepairCounterfactualProbeProvider:
    def __init__(self) -> None:
        self._step = 0
        self.rejection_feedback: list[str] = []

    def complete_with_tools(self, *, messages, tools):
        self._step += 1
        if self._step == 4:
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        if self._step == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this connectivity obligation.",
                    "structured_intent": COUNTERFACTUAL_CONNECTIVITY_INTENT,
                },
                tool_call_id="counterfactual-no-fit",
            )
        if self._step > 2:
            feedback = _rejection_feedback_from_messages(messages)
            if feedback is not None:
                self.rejection_feedback.append(feedback)
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": "Must every tank have a piping path to a centrifugal pump?",
                "generated_datalog": _counterfactual_connectivity_program(
                    faithful=self._step > 2
                ),
                "formal_restatement": (
                    "Return tanks without a piping path to a centrifugal pump."
                ),
                "faithfulness_review": _faithful_review(
                    COUNTERFACTUAL_CONNECTIVITY_INTENT
                ),
            },
            tool_call_id=(
                "counterfactual-vacuous"
                if self._step == 2
                else "counterfactual-corrected"
            ),
        )


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle not on PATH")
def test_counterfactual_failure_is_repaired_through_public_runner() -> None:
    provider = RepairCounterfactualProbeProvider()

    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=provider,
    )

    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposals) == 2
    failed, corrected = proposals
    assert failed["status"] == "rejected"
    assert failed["code"] == "faithfulness.counterfactual_failed"
    assert failed["counterfactual_validation"]["status"] == "failed"
    assert any(
        outcome["probe_id"].endswith(":multihop") and outcome["outcome"] == "failed"
        for outcome in failed["counterfactual_validation"]["probes"]
    )
    assert any(
        "faithfulness.counterfactual_failed" in feedback
        for feedback in provider.rejection_feedback
    )
    assert corrected["status"] == "answered"
    assert corrected["executed"] is True
    assert corrected["counterfactual_validation"]["status"] == "passed"
    assert corrected["route_artifact"]["repair_summary"] == {
        "gate_attempts": 2,
        "failed_gate_attempts": 1,
    }


class RepairLayeredFaithfulnessProvider:
    def __init__(self) -> None:
        self._step = 0
        self.rejection_feedback: list[str] = []

    def complete_with_tools(self, *, messages, tools):
        self._step += 1
        if self._step == 4:
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        if self._step == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this connectivity obligation.",
                    "structured_intent": COUNTERFACTUAL_CONNECTIVITY_INTENT,
                },
                tool_call_id="layered-no-fit",
            )
        if self._step > 2:
            feedback = _rejection_feedback_from_messages(messages)
            if feedback is not None:
                self.rejection_feedback.append(feedback)
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": "Must every tank have a piping path to a centrifugal pump?",
                "generated_datalog": _counterfactual_connectivity_program(
                    faithful=True
                ),
                "formal_restatement": (
                    "Return tanks without a piping path to a centrifugal pump."
                ),
                "faithfulness_review": {
                    "status": "uncertain" if self._step == 2 else "faithful",
                    "back_translated_intent": COUNTERFACTUAL_CONNECTIVITY_INTENT,
                    "diagnostics": (
                        [
                            "The model could not establish whether direction was preserved."
                        ]
                        if self._step == 2
                        else []
                    ),
                },
            },
            tool_call_id=(
                "layered-uncertain" if self._step == 2 else "layered-corrected"
            ),
        )


def test_model_back_translation_can_veto_but_not_authorize_public_runner(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    provider = RepairLayeredFaithfulnessProvider()

    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=provider,
    )
    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposals) == 2
    vetoed, corrected = proposals
    assert vetoed["status"] == "rejected"
    assert vetoed["code"] == "faithfulness.model_veto"
    assert vetoed["faithfulness_gate"]["status"] == "failed"
    assert vetoed["faithfulness_gate"]["layers"]["mechanical"]["status"] == "passed"
    assert vetoed["faithfulness_gate"]["layers"]["semantic"]["status"] == "passed"
    assert vetoed["faithfulness_gate"]["layers"]["counterfactual"]["status"] == "passed"
    assert vetoed["faithfulness_gate"]["layers"]["model_review"]["status"] == "failed"
    assert corrected["status"] == "answered"
    assert corrected["executed"] is True
    assert corrected["faithfulness_gate"]["status"] == "passed"
    assert corrected["route_artifact"]["repair_summary"] == {
        "gate_attempts": 2,
        "failed_gate_attempts": 1,
    }
    assert any(
        "faithfulness.model_veto" in item for item in provider.rejection_feedback
    )


class ExhaustedConflictingFaithfulnessProvider:
    def __init__(self) -> None:
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        self._step += 1
        if self._step == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this connectivity obligation.",
                    "structured_intent": COUNTERFACTUAL_CONNECTIVITY_INTENT,
                },
                tool_call_id="exhausted-no-fit",
            )
        if self._step == 4:
            return FinalAnswer(
                answer_text="Every tank has a compliant piping path.",
                evidence_references=[PUMP_ID],
                grounding_posture=POSTURE_SOURCE_GROUNDED,
            )
        if self._step > 4:
            raise AssertionError("provider consulted after failed gate ended the run")
        conflicting_intent = {
            **COUNTERFACTUAL_CONNECTIVITY_INTENT,
            "direction": "directed",
        }
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": "Must every tank have a piping path to a centrifugal pump?",
                "generated_datalog": _counterfactual_connectivity_program(
                    faithful=True
                ),
                "formal_restatement": (
                    "Return tanks without a piping path to a centrifugal pump."
                ),
                "faithfulness_review": {
                    "status": "faithful",
                    "back_translated_intent": conflicting_intent,
                    "diagnostics": [],
                },
            },
            tool_call_id=f"conflicting-revision-{self._step}",
        )


def test_exhausted_conflicting_gate_returns_missing_capability_not_verdict(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=ExhaustedConflictingFaithfulnessProvider(),
        max_rounds=3,
    )

    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposals) == 2
    assert all(proposal["status"] == "rejected" for proposal in proposals)
    assert all(
        proposal["faithfulness_gate"]["layers"]["model_review"]["diagnostics"][0][
            "code"
        ]
        == "faithfulness.model_review_conflict"
        for proposal in proposals
    )
    assert result.grounding_posture == POSTURE_SOURCE_DATA_UNAVAILABLE
    assert result.source_grounded is False
    assert result.deterministic_verdict is None
    assert result.witnesses == []
    assert "faithful generated program" in result.answer_text
    outcome = result.trace_events[-1]["outcome"]
    assert outcome["status"] == "missing_capability"
    assert outcome["code"] == "faithfulness.no_faithful_program"
    assert outcome["diagnostics"]


def test_final_answer_cannot_bypass_a_failed_faithfulness_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=ExhaustedConflictingFaithfulnessProvider(),
        max_rounds=5,
    )

    assert result.grounding_posture == POSTURE_SOURCE_DATA_UNAVAILABLE
    assert result.source_grounded is False
    assert result.deterministic_verdict is None
    assert result.evidence_references == []
    assert "Every tank has a compliant piping path." not in result.answer_text
    assert result.trace_events[-1]["outcome"]["code"] == (
        "faithfulness.no_faithful_program"
    )


class SingleRejectionThenRepairedAnswerProvider:
    """Mirrors the live bug: one faithfulness-gate rejection followed by a
    premature final answer, while round budget remains and no repair has
    been attempted yet. The harness must push the model to retry instead of
    immediately declaring faithfulness.no_faithful_program."""

    def __init__(self) -> None:
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        self._step += 1
        if self._step == 5:
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        if self._step == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this connectivity obligation.",
                    "structured_intent": COUNTERFACTUAL_CONNECTIVITY_INTENT,
                },
                tool_call_id="single-rejection-no-fit",
            )
        if self._step == 2:
            conflicting_intent = {
                **COUNTERFACTUAL_CONNECTIVITY_INTENT,
                "direction": "directed",
            }
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every tank have a piping path to a centrifugal pump?",
                    "generated_datalog": _counterfactual_connectivity_program(
                        faithful=True
                    ),
                    "formal_restatement": (
                        "Return tanks without a piping path to a centrifugal pump."
                    ),
                    "faithfulness_review": {
                        "status": "faithful",
                        "back_translated_intent": conflicting_intent,
                        "diagnostics": [],
                    },
                },
                tool_call_id="single-rejection-conflicting",
            )
        if self._step == 3:
            # The bug this guards against: giving up immediately after one
            # rejection instead of using the backend's repair guidance.
            return FinalAnswer(
                answer_text="Every tank has a compliant piping path.",
                evidence_references=[PUMP_ID],
                grounding_posture=POSTURE_SOURCE_GROUNDED,
            )
        if self._step == 4:
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Must every tank have a piping path to a centrifugal pump?",
                    "generated_datalog": _counterfactual_connectivity_program(
                        faithful=True
                    ),
                    "formal_restatement": (
                        "Return tanks without a piping path to a centrifugal pump."
                    ),
                    "faithfulness_review": _faithful_review(
                        COUNTERFACTUAL_CONNECTIVITY_INTENT
                    ),
                },
                tool_call_id="single-rejection-corrected",
            )
        raise AssertionError("provider consulted beyond the expected repair sequence")


def test_single_gate_rejection_forces_a_repair_attempt_before_giving_up(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    provider = SingleRejectionThenRepairedAnswerProvider()

    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=provider,
        max_rounds=6,
    )

    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert [proposal["status"] for proposal in proposals] == [
        "rejected",
        "answered",
    ]
    assert result.answer_text == "Automatic generated logic completed."


def test_single_gate_rejection_with_no_remaining_budget_still_gives_up(
    monkeypatch,
) -> None:
    """Forcing a repair attempt only applies when round budget remains --
    the harness must not loop forever waiting for a retry it cannot afford."""
    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    provider = SingleRejectionThenRepairedAnswerProvider()

    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=provider,
        max_rounds=3,
    )

    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert [proposal["status"] for proposal in proposals] == ["rejected"]
    assert result.trace_events[-1]["outcome"]["code"] == (
        "faithfulness.no_faithful_program"
    )


def _replay_counterfactual_program(
    program: str, **_limits: object
) -> dict[str, list[tuple[str, ...]]]:
    source_match = re.search(
        r'^node_attribute\("([^"]+)", "label", "Tank"\)\.$',
        program,
        re.MULTILINE,
    )
    target_match = re.search(
        r'^node_attribute\("([^"]+)", "label", "CentrifugalPump"\)\.$',
        program,
        re.MULTILINE,
    )
    assert source_match is not None and target_match is not None
    source_id, target_id = source_match.group(1), target_match.group(1)
    connected = bool(
        re.search(r'^graph_edge\("[^"]+", "[^"]+", ', program, re.MULTILINE)
    )
    edge_attrs = re.findall(
        r'^graph_edge_attribute\(.*"attr_name", "([^"]+)"\)\.$',
        program,
        re.MULTILINE,
    )
    qualifying_path = connected and any(
        attr_name
        in {
            "sourceItem",
            "targetItem",
            "sourceNode",
            "targetNode",
            "nodes",
            "segments",
            "connections",
            "items",
            "pipingNetworkSystems",
            "nozzles",
        }
        for attr_name in edge_attrs
    )
    narrowed_to_direct = "graph_edge(Source, Target, _)" in program
    direct_forward = f'graph_edge("{source_id}", "{target_id}",' in program
    has_pump = (
        qualifying_path and direct_forward if narrowed_to_direct else qualifying_path
    )
    answer = [] if has_pump else [(source_id,)]
    return {"answer": answer}


def test_counterfactual_repair_loop_does_not_depend_on_local_engine(
    monkeypatch,
) -> None:

    monkeypatch.setattr(
        counterfactual_probes,
        "run_souffle_program",
        _replay_counterfactual_program,
    )
    result = run_grounded_qa_turn(
        question="Must every tank have a piping path to a centrifugal pump?",
        topology_tools=make_tools(),
        provider=RepairCounterfactualProbeProvider(),
    )

    proposals = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert [proposal["status"] for proposal in proposals] == [
        "rejected",
        "answered",
    ]


class RepairStructuredIntentProvider:
    def __init__(self) -> None:
        self._step = 0
        self.rejection_feedback: list[str] = []

    def complete_with_tools(self, *, messages, tools):
        if any(
            message.get("role") == "tool"
            and '"status": "answered"' in str(message.get("content", ""))
            for message in messages
        ):
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        if self._step == 0:
            self._step += 1
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this valve obligation.",
                    "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
                },
                tool_call_id="structured-no-fit",
            )

        if self._step > 1:
            feedback = _rejection_feedback_from_messages(messages)
            if feedback is not None:
                self.rejection_feedback.append(feedback)
        self._step += 1
        if self._step == 2:
            encoded_intent = {
                **STRUCTURED_CONNECTIVITY_INTENT,
                "source_classes": ["BallValve"],
                "target_classes": ["CentrifugalPump", "ReciprocatingPump"],
                "source_role": "reachable_object",
                "target_role": "equipment",
            }
            program = (
                ".decl answer(x:symbol)\n.output answer\n"
                f'answer(x) :- reachable("{SEGMENT_ID}", x).'
            )
            call_id = "structured-reversed"
        else:
            encoded_intent = STRUCTURED_CONNECTIVITY_INTENT
            program = _faithful_structured_connectivity_program()
            call_id = "structured-corrected"
        program = encode_structured_intent_program(program, encoded_intent)
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": "Must every pump have a reachable ball valve?",
                "generated_datalog": program,
                "formal_restatement": "Return pumps without a reachable ball valve.",
                "resolved_identity_ids": [SEGMENT_ID],
                "faithfulness_review": _faithful_review(STRUCTURED_CONNECTIVITY_INTENT),
            },
            tool_call_id=call_id,
        )


def test_structured_intent_mismatch_is_repaired_through_public_runner() -> None:
    provider = RepairStructuredIntentProvider()

    result = run_grounded_qa_turn(
        question="Must every pump have a reachable ball valve?",
        topology_tools=make_tools(),
        provider=provider,
    )

    proposal_traces = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposal_traces) == 2
    assert proposal_traces[0]["tool_result"]["status"] == "rejected"
    rejected = proposal_traces[0]["tool_result"]
    assert rejected["status"] == "rejected"
    assert rejected["validation"]["status"] == "rejected"
    assert {diagnostic["field"] for diagnostic in rejected["diagnostics"]} >= {
        "source_classes",
        "target_classes",
        "source_role",
        "target_role",
    }
    assert all(
        "requested" in diagnostic and "encoded" in diagnostic
        for diagnostic in rejected["diagnostics"]
        if diagnostic["code"].startswith("structured_intent.")
    )
    assert any(
        "structured_intent.source_classes_mismatch" in feedback
        for feedback in provider.rejection_feedback
    )
    accepted = proposal_traces[-1]["tool_result"]
    assert accepted["status"] == "answered"
    assert accepted["executed"] is True
    assert accepted["validation"]["status"] == "safe_to_confirm"
    assert accepted["route_artifact"]["repair_summary"] == {
        "gate_attempts": 2,
        "failed_gate_attempts": 1,
    }


class ValidStructuredIntentProvider:
    def __init__(self) -> None:
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        if self._step >= 2:
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        self._step += 1
        if self._step == 1:
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template covers this valve obligation.",
                    "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
                },
                tool_call_id="valid-structured-no-fit",
            )
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": "Must every pump have a reachable ball valve?",
                "generated_datalog": encode_structured_intent_program(
                    _faithful_structured_connectivity_program(),
                    STRUCTURED_CONNECTIVITY_INTENT,
                ),
                "formal_restatement": "Return pumps without a reachable ball valve.",
                "faithfulness_review": _faithful_review(STRUCTURED_CONNECTIVITY_INTENT),
                "resolved_identity_ids": [SEGMENT_ID],
            },
            tool_call_id="valid-structured-proposal",
        )


def test_valid_structured_intent_executes_through_public_runner() -> None:
    result = run_grounded_qa_turn(
        question="Must every pump have a reachable ball valve?",
        topology_tools=make_tools(),
        provider=ValidStructuredIntentProvider(),
    )

    proposal = next(
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    )
    assert proposal["status"] == "answered"
    assert proposal["executed"] is True
    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert proposal["confirmation"] == {"required": False}


def test_model_metadata_cannot_substitute_for_program_intent_contract() -> None:
    tools = make_tools()
    tools.begin_request("Must every pump have a reachable ball valve?")
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this valve obligation.",
            "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
        },
    )

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Must every pump have a reachable ball valve?",
            "generated_datalog": (
                ".decl answer(x:symbol)\n.output answer\n"
                f'answer(x) :- reachable("{SEGMENT_ID}", x).'
            ),
            "formal_restatement": "Return pumps without a reachable ball valve.",
            "encoded_intent": STRUCTURED_CONNECTIVITY_INTENT,
        },
    )

    assert result["status"] == "rejected"
    assert result["diagnostics"][-1] == {
        "code": "structured_intent.program_contract_invalid",
        "field": "contract",
        "message": ("Generated query must declare exactly one query_intent_contract."),
    }


def test_program_contract_guard_in_comment_cannot_authorize_answer_rule() -> None:
    tools = make_tools()
    tools.begin_request("Must every pump have a reachable ball valve?")
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this valve obligation.",
            "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
        },
    )
    guarded = encode_structured_intent_program(
        (
            ".decl answer(x:symbol)\n.output answer\n"
            f'answer(x) :- reachable("{SEGMENT_ID}", x).'
        ),
        STRUCTURED_CONNECTIVITY_INTENT,
    )
    lines = guarded.splitlines()
    guard = lines[1][:-1]
    lines[-1] = lines[-1].replace(f"{guard},", "", 1) + f" // {guard}"

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Must every pump have a reachable ball valve?",
            "generated_datalog": "\n".join(lines),
            "formal_restatement": "Return pumps without a reachable ball valve.",
        },
    )

    assert result["status"] == "rejected"
    assert result["diagnostics"][-1]["field"] == "output_obligations"


def test_malformed_program_contract_returns_diagnostic_instead_of_raising() -> None:
    tools = make_tools()
    tools.begin_request("Must every pump have a reachable ball valve?")
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this valve obligation.",
            "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
        },
    )

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Must every pump have a reachable ball valve?",
            "generated_datalog": (
                ".decl query_intent_contract(payload:symbol)\n"
                'query_intent_contract("A").\n'
                ".decl answer(x:symbol)\n.output answer\n"
                'answer("node-segment-s1") :- query_intent_contract("A").'
            ),
            "formal_restatement": "Return pumps without a reachable ball valve.",
        },
    )

    assert result["status"] == "rejected"
    assert result["diagnostics"][-1]["field"] == "contract"


@pytest.mark.parametrize(
    ("field", "encoded_value"),
    [
        ("source_classes", ["CentrifugalPump"]),
        ("target_classes", ["GateValve"]),
        ("source_role", "reachable_object"),
        ("target_role", "equipment"),
        ("graph_scope", "instrumentation_inclusive"),
        ("direction", "directed"),
        ("quantifier", "any"),
        ("negated", False),
        ("output_obligations", ["matching_target_ids"]),
    ],
)
def test_every_structured_intent_obligation_is_mechanically_compared(
    field: str,
    encoded_value: object,
) -> None:
    tools = make_tools()
    tools.begin_request("Must every pump have a reachable ball valve?")
    route = tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this valve obligation.",
            "structured_intent": STRUCTURED_CONNECTIVITY_INTENT,
        },
    )
    assert route["status"] == "route_receipt_issued"

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Must every pump have a reachable ball valve?",
            "generated_datalog": encode_structured_intent_program(
                (
                    ".decl answer(x:symbol)\n.output answer\n"
                    f'answer(x) :- reachable("{SEGMENT_ID}", x).'
                ),
                {
                    **STRUCTURED_CONNECTIVITY_INTENT,
                    field: encoded_value,
                },
            ),
            "formal_restatement": "Return pumps without a reachable ball valve.",
            "resolved_identity_ids": [SEGMENT_ID],
        },
    )
    assert result["status"] == "rejected"
    semantic_diagnostics = [
        diagnostic
        for diagnostic in result["diagnostics"]
        if diagnostic["code"].startswith("structured_intent.")
    ]
    assert len(semantic_diagnostics) == 1
    assert semantic_diagnostics[0] == {
        "code": f"structured_intent.{field}_mismatch",
        "field": field,
        "requested": STRUCTURED_CONNECTIVITY_INTENT[field],
        "encoded": encoded_value,
        "message": (
            f"Generated query changed {field}: requested "
            f"{STRUCTURED_CONNECTIVITY_INTENT[field]!r}, encoded {encoded_value!r}."
        ),
    }


class ScriptedThenAnswerProvider(ScriptedQATurnProvider):
    def complete_with_tools(self, *, messages, tools):
        if any(
            message.get("role") == "tool"
            and '"status": "answered"' in str(message.get("content", ""))
            for message in messages
        ):
            return FinalAnswer(answer_text="Automatic generated logic completed.")
        return super().complete_with_tools(messages=messages, tools=tools)


def test_scripted_provider_escalates_rule_evaluation_to_automatic_datalog():
    """The OSS provider reaches automatic generated execution for rule-like
    questions instead of dead-ending in a retrieval-only answer."""
    result = run_grounded_qa_turn(
        question="Must every connected object satisfy the temporary topology rule?",
        topology_tools=make_tools(),
        provider=ScriptedThenAnswerProvider(),
    )

    proposal_traces = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "propose_temporary_datalog"
    ]
    assert len(proposal_traces) == 1
    tool_result = proposal_traces[0]["tool_result"]
    assert tool_result["status"] == "answered"
    assert tool_result["executed"] is True
    assert tool_result["disclosure"]["inspectable_datalog"]["generated_datalog"]
    assert tool_result["disclosure"]["restatement"]
    assert tool_result["validation"]["status"] == "safe_to_confirm"


def test_conversational_answer_does_not_require_evidence():
    result = run_grounded_qa_turn(
        question="hi, what can you help with?",
        topology_tools=make_tools(),
        provider=ImmediateConversationProvider(),
    )

    assert result.answer_text == "Happy to help."
    assert result.tool_call_trace == []


def test_source_mutation_request_is_denied_without_model_planning():
    result = run_grounded_qa_turn(
        question="Delete pump P-101 from the drawing.",
        topology_tools=make_tools(),
        provider=UnexpectedProviderCall(),
    )

    assert "cannot modify" in result.answer_text
    assert result.tool_call_trace[0]["tool_name"] == "mutate_source_graph"
    assert result.tool_call_trace[0]["tool_result"]["status"] == "rejected"


# ---------------------------------------------------------------------------
# Grounding-posture disclosure boundary (37x.22.21)
#
# The model declares each answer's grounding posture; the backend deterministically
# enforces that the posture is consistent with validated evidence and attaches an
# authoritative disclosure whenever an answer is not a validated source conclusion.
# The backend never classifies the question itself.
# ---------------------------------------------------------------------------


class SinglePostureProvider:
    """Returns one FinalAnswer with a declared posture and no tool calls."""

    def __init__(self, answer: FinalAnswer) -> None:
        self._answer = answer

    def complete_with_tools(self, *, messages, tools):
        return self._answer


class FindThenPostureProvider:
    """Satisfies the object-lookup evidence gate, then answers with a posture."""

    def __init__(self, answer: FinalAnswer, *, pattern: str = "P-101") -> None:
        self._answer = answer
        self._pattern = pattern
        self._step = 0

    def complete_with_tools(self, *, messages, tools):
        step = self._step
        self._step += 1
        if step == 0:
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": self._pattern},
                tool_call_id="posture-find",
            )
        return self._answer


def test_general_knowledge_answer_is_disclosed_as_not_from_source():
    result = run_grounded_qa_turn(
        question="Explain in general how process flow direction is determined.",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(
            FinalAnswer(
                answer_text="Flow direction generally follows pressure gradients.",
                grounding_posture=POSTURE_GENERAL_KNOWLEDGE,
            )
        ),
    )

    assert result.grounding_posture == POSTURE_GENERAL_KNOWLEDGE
    assert result.source_grounded is False
    assert result.disclosure is not None
    assert "not" in result.disclosure.lower()
    assert "loaded source" in result.disclosure.lower()
    assert result.evidence_references == []


def test_source_specific_calculation_with_missing_data_states_unavailable():
    result = run_grounded_qa_turn(
        question="Compute the operating Reynolds number for this line.",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(
            FinalAnswer(
                answer_text=(
                    "I cannot compute it: flow rate, fluid viscosity, and density "
                    "are not present in the loaded source."
                ),
                grounding_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
            )
        ),
    )

    assert result.grounding_posture == POSTURE_SOURCE_DATA_UNAVAILABLE
    assert result.source_grounded is False
    assert result.disclosure is not None
    assert "unavailable" in result.disclosure.lower()


def test_unrelated_question_is_redirected_without_backend_classifier():
    result = run_grounded_qa_turn(
        question="What is the capital of France?",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(
            FinalAnswer(
                answer_text=(
                    "That is unrelated to your P&ID. Ask me about the loaded source."
                ),
                grounding_posture=POSTURE_OUT_OF_SCOPE,
            )
        ),
    )

    # The redirect is model behavior: the backend planned no tool calls and ran no
    # deterministic intent classifier to detect off-topic input.
    assert result.tool_call_trace == []
    assert result.grounding_posture == POSTURE_OUT_OF_SCOPE
    assert result.source_grounded is False
    assert result.disclosure is not None


def test_ambiguous_question_can_request_clarification_without_source_claim():
    result = run_grounded_qa_turn(
        question="Is the line okay?",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(
            FinalAnswer(
                answer_text=(
                    "Which line and acceptance criterion should I check? "
                    "I can inspect connectivity and represented attributes."
                ),
                grounding_posture=POSTURE_NEEDS_CLARIFICATION,
            )
        ),
    )

    assert result.grounding_posture == POSTURE_NEEDS_CLARIFICATION
    assert result.source_grounded is False
    assert result.disclosure is not None
    assert "criterion" in result.disclosure.lower()


def test_source_grounded_answer_with_validated_evidence_has_no_disclosure():
    result = run_grounded_qa_turn(
        question="Find pump P-101 in the source.",
        topology_tools=make_tools(),
        provider=FindThenPostureProvider(
            FinalAnswer(
                answer_text="Pump P-101 is present in the loaded source.",
                evidence_references=[PUMP_ID],
                grounding_posture=POSTURE_SOURCE_GROUNDED,
            )
        ),
    )

    assert result.grounding_posture == POSTURE_SOURCE_GROUNDED
    assert result.source_grounded is True
    assert result.disclosure is None
    assert PUMP_ID in result.evidence_references


def test_declared_source_grounding_without_validated_evidence_is_downgraded():
    result = run_grounded_qa_turn(
        question="What is the capital of France?",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(
            FinalAnswer(
                answer_text="Pump P-101 feeds valve V-102.",
                evidence_references=["node-not-in-source"],
                grounding_posture=POSTURE_SOURCE_GROUNDED,
            )
        ),
    )

    assert result.grounding_posture == POSTURE_UNSUPPORTED_SOURCE_CLAIM
    assert result.source_grounded is False
    assert result.disclosure is not None
    assert result.evidence_references == []
    assert "node-not-in-source" in result.rejected_references


def test_unspecified_posture_preserves_legacy_grounding():
    grounded = run_grounded_qa_turn(
        question="Find pump P-101 in the source.",
        topology_tools=make_tools(),
        provider=FindThenPostureProvider(
            FinalAnswer(
                answer_text="Pump P-101 is present.",
                evidence_references=[PUMP_ID],
            )
        ),
    )
    assert grounded.grounding_posture == POSTURE_UNSPECIFIED
    assert grounded.source_grounded is True
    assert grounded.disclosure is None

    conversational = run_grounded_qa_turn(
        question="hi, what can you help with?",
        topology_tools=make_tools(),
        provider=SinglePostureProvider(FinalAnswer(answer_text="Happy to help.")),
    )
    assert conversational.grounding_posture == POSTURE_UNSPECIFIED
    assert conversational.source_grounded is False
    assert conversational.disclosure is None
    assert conversational.answer_text == "Happy to help."


# ---------------------------------------------------------------------------
# TopologyTools.find_equipment contracts
# ---------------------------------------------------------------------------


def test_find_equipment_empty_pattern_returns_all_nodes():
    """
    Behavior: empty pattern means "list all topology objects".
    Public interface: TopologyTools.execute("find_equipment", {"pattern": ""})
    """
    tools = make_tools()
    result = tools.execute("find_equipment", {"pattern": ""})
    assert result["count"] == 4
    ids = {m["evidence_id"] for m in result["matches"]}
    assert ids == {PUMP_ID, NOZZLE_ID, SEGMENT_ID, VALVE_ID}


def test_find_equipment_tag_pattern_filters_by_tag_name():
    """
    Behavior: pattern matched against tag_name (case-insensitive).
    """
    tools = make_tools()
    result = tools.execute("find_equipment", {"pattern": "P-101"})
    assert result["count"] == 1
    assert result["matches"][0]["evidence_id"] == PUMP_ID


def test_find_equipment_label_pattern_filters_by_node_class():
    """
    Behavior: pattern matched against label (node class) as fallback.
    """
    tools = make_tools()
    result = tools.execute("find_equipment", {"pattern": "valve"})
    assert result["count"] == 1
    assert result["matches"][0]["evidence_id"] == VALVE_ID


def test_find_equipment_no_match_returns_empty():
    tools = make_tools()
    result = tools.execute("find_equipment", {"pattern": "DOES-NOT-EXIST"})
    assert result["count"] == 0
    assert result["matches"] == []


def test_get_reachable_uses_graph_facts_for_raw_structural_witness():
    """
    Behavior: the model-facing topology tool still returns topology IDs for UI
    highlighting, while its witness is backed by canonical graph-fact node and
    edge identities.
    """
    tools = make_graph_facts_backed_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": PUMP_ID})

    valve_entry = next(r for r in result["reachable"] if r["evidence_id"] == VALVE_ID)
    witness = valve_entry["witness"]

    assert witness["node_ids"] == [PUMP_ID, NOZZLE_ID, SEGMENT_ID, VALVE_ID]
    assert witness["raw_node_ids"] == [PUMP_ID, NOZZLE_ID, SEGMENT_ID, VALVE_ID]
    assert [edge["edge_key"] for edge in witness["raw_edges"]] == [
        EDGE_PUMP_NOZZLE,
        EDGE_NOZZLE_SEGMENT,
        EDGE_SEGMENT_VALVE,
    ]


def test_find_equipment_match_includes_evidence_id_and_label():
    """
    Behavior: each match exposes evidence_id and a human-readable label.
    The label should prefer tag_name over label.
    """
    tools = make_tools()
    result = tools.execute("find_equipment", {"pattern": "P-101"})
    match = result["matches"][0]
    assert match["evidence_id"] == PUMP_ID
    assert "P-101" in match["label"]


# ---------------------------------------------------------------------------
# TopologyTools.get_reachable_equipment contracts
# ---------------------------------------------------------------------------


def test_get_reachable_includes_all_structural_nodes_in_path():
    """
    Behavior: reachable result includes intervening structural nodes (nozzle, segment),
    not just process-facing equipment. The witness is the complete ordered path.
    """
    tools = make_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": PUMP_ID})
    reachable_ids = {r["evidence_id"] for r in result["reachable"]}
    # All three downstream nodes must be reachable
    assert NOZZLE_ID in reachable_ids
    assert SEGMENT_ID in reachable_ids
    assert VALVE_ID in reachable_ids


def test_get_reachable_witness_is_ordered_structural_path():
    """
    Behavior: each reachable item carries an ordered witness with node_ids and edge_ids
    representing the full structural path from source to that node.
    The pump→valve path must pass through nozzle and segment.
    """
    tools = make_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": PUMP_ID})
    # Find the valve entry
    valve_entry = next(
        (r for r in result["reachable"] if r["evidence_id"] == VALVE_ID), None
    )
    assert valve_entry is not None, "Valve must be reachable from pump"
    witness = valve_entry["witness"]
    assert witness["node_ids"][0] == PUMP_ID
    assert NOZZLE_ID in witness["node_ids"]
    assert SEGMENT_ID in witness["node_ids"]
    assert witness["node_ids"][-1] == VALVE_ID
    # Edge IDs must be present and ordered
    assert EDGE_PUMP_NOZZLE in witness["edge_ids"]
    assert EDGE_NOZZLE_SEGMENT in witness["edge_ids"]
    assert EDGE_SEGMENT_VALVE in witness["edge_ids"]


def test_get_reachable_direction_status_is_inferred():
    """
    Behavior: all reachable items carry direction_status: "inferred" (undirected traversal).
    """
    tools = make_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": PUMP_ID})
    for item in result["reachable"]:
        assert item["direction_status"] == "inferred", (
            f"Expected direction_status='inferred' on {item['evidence_id']}"
        )


def test_get_reachable_from_unknown_id_returns_error():
    """
    Behavior: unknown equipment_id returns an error key, not a crash.
    """
    tools = make_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": "no-such-node"})
    assert "error" in result
    assert result["reachable"] == []


def test_get_reachable_is_undirected():
    """
    Behavior: traversal is undirected — reachable from valve includes pump.
    """
    tools = make_tools()
    result = tools.execute("get_reachable_equipment", {"equipment_id": VALVE_ID})
    reachable_ids = {r["evidence_id"] for r in result["reachable"]}
    assert PUMP_ID in reachable_ids


# ---------------------------------------------------------------------------
# run_grounded_qa_turn contracts (harness behavior)
# ---------------------------------------------------------------------------


def test_harness_returns_qa_turn_result_with_scripted_provider():
    """
    Behavior: harness with scripted provider produces a QATurnResult with
    answer_text and evidence_references populated from tool outputs.
    """
    tools = make_tools()
    provider = ScriptedQATurnProvider()
    result = run_grounded_qa_turn(
        question="What is reachable from P-101?",
        topology_tools=tools,
        provider=provider,
    )
    assert isinstance(result, QATurnResult)
    assert len(result.answer_text) > 0
    assert isinstance(result.evidence_references, list)


def test_harness_evidence_references_are_known_ids():
    """
    Behavior: all returned evidence_references are valid topology IDs (present in evidence_map).
    """
    tools = make_tools()
    provider = ScriptedQATurnProvider()
    result = run_grounded_qa_turn(
        question="What is reachable from the pump?",
        topology_tools=tools,
        provider=provider,
    )
    known = tools.known_evidence_ids()
    for ref in result.evidence_references:
        assert ref in known, f"evidence_reference {ref!r} is not a known topology ID"


def test_harness_propagates_tool_results_to_provider():
    """
    Behavior: provider receives tool results in subsequent messages so it can reference them.
    Verified by: ScriptedQATurnProvider uses tool results to pick equipment_id for step 2.
    If the harness didn't propagate results the scripted provider would error; if it gets
    here with evidence references the propagation worked.
    """
    tools = make_tools()
    provider = ScriptedQATurnProvider()
    result = run_grounded_qa_turn(
        question="What topology objects exist?",
        topology_tools=tools,
        provider=provider,
    )
    # The scripted provider's step-2 reads the find_equipment result to pick equipment_id;
    # step-3 reads get_reachable result. If propagation failed, evidence_references would be empty.
    assert len(result.evidence_references) > 0


def test_harness_includes_tool_call_trace():
    """
    Behavior: QATurnResult carries a trace of all tool calls executed during the turn.
    """
    tools = make_tools()
    provider = ScriptedQATurnProvider()
    result = run_grounded_qa_turn(
        question="What is connected to P-101?",
        topology_tools=tools,
        provider=provider,
    )
    assert len(result.tool_call_trace) >= 2
    tool_names = [t["tool_name"] for t in result.tool_call_trace]
    assert "find_equipment" in tool_names
    assert "get_reachable_equipment" in tool_names


def test_harness_raises_on_max_rounds_exceeded():
    """
    Behavior: harness raises RuntimeError if the provider never returns a FinalAnswer.
    """

    class InfiniteToolCallProvider:
        def complete_with_tools(self, *, messages, tools):
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": ""},
                tool_call_id="loop",
            )

    tools = make_tools()
    with pytest.raises(RuntimeError, match="exceeded"):
        run_grounded_qa_turn(
            question="loop forever",
            topology_tools=tools,
            provider=InfiniteToolCallProvider(),
            max_rounds=3,
        )


def test_default_max_rounds_is_20():
    """
    Behavior: the default round budget is 20, not the original 10 -- heavier
    reasoning models routed through BYOK/OpenRouter (e.g. large MoE models)
    were observed hitting the old cap on broad, open-ended questions well
    before exhausting useful tool calls.
    """
    assert DEFAULT_MAX_ROUNDS == 20


def test_on_round_is_reported_once_per_tool_call_not_before_a_first_round_final_answer():
    """
    Behavior: on_round fires with (round_number, max_rounds, tool_name,
    tool_input, reasoning) for each round that dispatches a tool call, so a
    caller can surface live progress -- including what the model is doing and
    why -- instead of a static "working" placeholder for a long-running turn.
    A round that answers immediately (no tool call at all) must not report
    progress -- there's nothing "in flight" to describe.
    """

    class TwoToolCallsThenAnswerProvider:
        def __init__(self):
            self.calls = 0

        def complete_with_tools(self, *, messages, tools):
            self.calls += 1
            if self.calls <= 2:
                return ToolCall(
                    tool_name="find_equipment",
                    tool_input={"pattern": "pump"},
                    tool_call_id=f"call-{self.calls}",
                    reasoning="Scanning for pump candidates."
                    if self.calls == 1
                    else None,
                )
            return FinalAnswer(answer_text="Found it.")

    reported: list[tuple[int, int, str | None, dict | None, str | None]] = []
    tools = make_tools()
    run_grounded_qa_turn(
        question="find the pump",
        topology_tools=tools,
        provider=TwoToolCallsThenAnswerProvider(),
        on_round=lambda round_number, max_rounds, tool_name, tool_input, reasoning: (
            reported.append(
                (round_number, max_rounds, tool_name, tool_input, reasoning)
            )
        ),
    )
    assert reported == [
        (
            1,
            DEFAULT_MAX_ROUNDS,
            "find_equipment",
            {"pattern": "pump"},
            "Scanning for pump candidates.",
        ),
        (2, DEFAULT_MAX_ROUNDS, "find_equipment", {"pattern": "pump"}, None),
    ]


def test_tool_call_trace_records_bounded_model_reasoning():
    """The audit trail carries the model's reasoning for each tool call --
    bounded, never fabricated (absent reasoning stays absent)."""

    class ReasonedProvider:
        def __init__(self):
            self.calls = 0

        def complete_with_tools(self, *, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return ToolCall(
                    tool_name="find_equipment",
                    tool_input={"pattern": "pump"},
                    tool_call_id="reasoned-1",
                    reasoning="x" * 10_000,
                )
            return FinalAnswer(answer_text="Found it.")

    result = run_grounded_qa_turn(
        question="find the pump",
        topology_tools=make_tools(),
        provider=ReasonedProvider(),
    )

    traced = [
        trace
        for trace in result.tool_call_trace
        if trace["tool_name"] == "find_equipment"
    ]
    assert traced
    recorded = traced[0]["reasoning"]
    assert isinstance(recorded, str)
    assert 0 < len(recorded) <= 2_000
    assert "reasoning" not in {
        key
        for trace in result.tool_call_trace
        if trace["tool_name"] != "find_equipment"
        for key in trace
    }


def test_harness_raises_on_unknown_tool_name_error():
    """
    Behavior: if provider returns an unknown tool_name, the harness executes it
    and gets an error result back — not a crash. The provider can then respond
    with a FinalAnswer. (Tool errors are propagated gracefully, not swallowed silently.)
    """

    class UnknownToolThenAnswerProvider:
        def __init__(self):
            self._step = 0

        def complete_with_tools(self, *, messages, tools):
            if self._step == 0:
                self._step += 1
                return ToolCall(
                    tool_name="nonexistent_tool",
                    tool_input={},
                    tool_call_id="bad-1",
                )
            return FinalAnswer(answer_text="done", evidence_references=[])

    tools = make_tools()
    result = run_grounded_qa_turn(
        question="call unknown tool",
        topology_tools=tools,
        provider=UnknownToolThenAnswerProvider(),
    )
    assert result.answer_text == "done"
    rejected = next(
        t for t in result.tool_call_trace if t["tool_name"] == "nonexistent_tool"
    )
    assert rejected["tool_result"]["status"] == "rejected"
    assert rejected["tool_result"]["code"] == "tool.unknown"


# ---------------------------------------------------------------------------
# 37x.22.17 — ambiguity, multi-candidate, follow-ups, prose rejection
# ---------------------------------------------------------------------------


def _multi_nozzle_topology(nozzle_count: int) -> dict:
    """Topology with one pump and several nozzles all connected to the pump."""
    nodes = [{"id": PUMP_ID, "label": "Pump", "tag_name": "P-101"}]
    edges = []
    evidence_map = {PUMP_ID: {"id": PUMP_ID}}
    for index in range(nozzle_count):
        node_id = f"node-nozzle-{index}"
        edge_id = f"edge-pump-nozzle-{index}"
        nodes.append({"id": node_id, "label": "Nozzle", "tag_name": f"N-{index}"})
        edges.append(
            {
                "id": edge_id,
                "source_id": PUMP_ID,
                "target_id": node_id,
                "relationship": "has_nozzle",
            }
        )
        evidence_map[node_id] = {"id": node_id}
        evidence_map[edge_id] = {"id": edge_id}
    return {"nodes": nodes, "edges": edges, "evidence_map": evidence_map}


def test_find_equipment_is_bounded_and_flags_truncation():
    """Ambiguous text yields bounded candidates with a truncation flag — no
    unbounded result and no mandatory selection step."""
    topology = _multi_nozzle_topology(TopologyTools.MAX_FIND_RESULTS + 5)
    tools = TopologyTools(topology_view=topology, session_id="s")
    result = tools.execute("find_equipment", {"pattern": "nozzle"})
    assert result["count"] == TopologyTools.MAX_FIND_RESULTS
    assert result["total_matches"] == TopologyTools.MAX_FIND_RESULTS + 5
    assert result["truncated"] is True


def test_ambiguous_text_produces_multiple_candidate_interpretation():
    """The model can answer for several plausible candidates and disclose which
    objects it interpreted the request to mean."""
    topology = _multi_nozzle_topology(3)
    tools = TopologyTools(topology_view=topology, session_id="s")
    result = run_grounded_qa_turn(
        question="What is connected to the nozzle?",
        topology_tools=tools,
        provider=ScriptedQATurnProvider(),
    )
    # Several nozzle candidates were interpreted (bounded by provider max).
    assert len(result.interpreted_object_ids) >= 2
    for interpreted in result.interpreted_object_ids:
        assert interpreted in tools.known_evidence_ids()
    # All interpreted candidates also appear as grounded evidence references.
    for interpreted in result.interpreted_object_ids:
        assert interpreted in result.evidence_references


def test_follow_up_reuses_prior_evidence_by_identity():
    """A follow-up that uses a pronoun resolves to the prior turn's evidence id."""
    tools = make_tools()
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump P-101 is here.",
            evidence_references=[PUMP_ID],
        )
    ]
    result = run_grounded_qa_turn(
        question="What is reachable from it?",
        topology_tools=tools,
        provider=ScriptedQATurnProvider(),
        conversation=conversation,
    )
    assert PUMP_ID in result.evidence_references
    assert PUMP_ID in result.interpreted_object_ids
    # The pump reaches the valve through nozzle and segment.
    assert (
        VALVE_ID in result.evidence_references
        or NOZZLE_ID in result.evidence_references
    )


def test_prior_prose_is_rejected_as_engineering_evidence():
    """Anything cited that is not a valid topology identity (e.g. prior prose)
    is rejected and never becomes evidence or interpretation."""

    class ProseCitingProvider:
        def __init__(self):
            self._step = 0

        def complete_with_tools(self, *, messages, tools):
            if self._step == 0:
                self._step += 1
                return ToolCall(
                    tool_name="get_reachable_equipment",
                    tool_input={"equipment_id": PUMP_ID},
                    tool_call_id="witness-before-citing-prose",
                )
            return FinalAnswer(
                answer_text="As I said earlier, the pump is connected.",
                evidence_references=[VALVE_ID, "the pump is connected"],
                interpreted_object_ids=[VALVE_ID, "as I said earlier"],
            )

    tools = make_tools()
    result = run_grounded_qa_turn(
        question="Is the valve connected?",
        topology_tools=tools,
        provider=ProseCitingProvider(),
    )
    assert result.evidence_references == [VALVE_ID]
    assert "the pump is connected" in result.rejected_references
    assert result.interpreted_object_ids == [VALVE_ID]


def test_conversation_state_cannot_smuggle_prose_through_prior_evidence():
    """Invalid prior evidence ids (prose masquerading as identities) are dropped
    before being offered back to the model for reuse."""

    seen_grounded_ids: list[list[str]] = []

    class InspectingProvider:
        def complete_with_tools(self, *, messages, tools):
            for message in messages:
                if (
                    message.get("role") == "assistant"
                    and "grounded_evidence_ids" in message
                ):
                    seen_grounded_ids.append(list(message["grounded_evidence_ids"]))
            return FinalAnswer(answer_text="ok", evidence_references=[])

    tools = make_tools()
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump is here.",
            evidence_references=[PUMP_ID, "prior prose not an id"],
        )
    ]
    run_grounded_qa_turn(
        question="Thanks",
        topology_tools=tools,
        provider=InspectingProvider(),
        conversation=conversation,
    )
    assert seen_grounded_ids == [[PUMP_ID]]


def test_compaction_folds_old_turns_but_preserves_evidence_identity():
    """Past a turn threshold, older prose is folded into a single summary turn,
    yet the evidence identities it established remain reusable by identity and
    the recent turns are kept verbatim."""
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump P-101 is right here in the loaded source.",
            evidence_references=[PUMP_ID],
        ),
        ConversationTurn(
            question="And the nozzle?",
            answer_text="Nozzle N-1 hangs off the pump body.",
            evidence_references=[NOZZLE_ID],
        ),
        ConversationTurn(
            question="What about the segment?",
            answer_text="Segment S-1 continues downstream.",
            evidence_references=[SEGMENT_ID],
        ),
    ]

    compacted = compact_conversation(conversation, max_turns=2)

    # The conversation was compacted below the caller-supplied window.
    assert len(compacted) == 2
    # The most recent turn is preserved verbatim.
    assert compacted[-1].question == "What about the segment?"
    assert compacted[-1].evidence_references == [SEGMENT_ID]
    # The folded turns collapse into a leading summary that keeps every prior
    # evidence identity so later follow-ups can still reuse them.
    summary = compacted[0]
    assert PUMP_ID in summary.evidence_references
    assert NOZZLE_ID in summary.evidence_references
    # Summary prose is context only; it carries the prior user decisions/questions
    # but is not any single verbatim prior answer that could masquerade as fact.
    assert "Where is the pump?" in summary.answer_text
    assert "And the nozzle?" in summary.answer_text


def test_compaction_preserves_follow_up_evidence_reuse_across_threshold():
    """A follow-up asked after the conversation crossed the compaction threshold
    still resolves against a prior-turn evidence identity that was folded into
    the summary."""
    seen_grounded_ids: list[list[str]] = []

    class InspectingProvider:
        def complete_with_tools(self, *, messages, tools):
            for message in messages:
                if (
                    message.get("role") == "assistant"
                    and "grounded_evidence_ids" in message
                ):
                    seen_grounded_ids.append(list(message["grounded_evidence_ids"]))
            return FinalAnswer(answer_text="ok", evidence_references=[])

    tools = make_tools()
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump is here.",
            evidence_references=[PUMP_ID],
        ),
        ConversationTurn(
            question="And the nozzle?",
            answer_text="Nozzle is there.",
            evidence_references=[NOZZLE_ID],
        ),
        ConversationTurn(
            question="And the segment?",
            answer_text="Segment continues.",
            evidence_references=[SEGMENT_ID],
        ),
    ]

    run_grounded_qa_turn(
        question="Thanks",
        topology_tools=tools,
        provider=InspectingProvider(),
        conversation=conversation,
        max_conversation_turns=2,
    )

    offered = {
        evidence_id for grounded in seen_grounded_ids for evidence_id in grounded
    }
    # The folded pump/nozzle identities remain offered to the model for reuse.
    assert PUMP_ID in offered
    assert NOZZLE_ID in offered
    assert SEGMENT_ID in offered


def test_compaction_drops_stale_evidence_but_keeps_valid_for_reuse():
    """After compaction, a folded evidence identity that is no longer valid in the
    current topology is dropped (the model must request fresh evidence), while a
    still-valid folded identity remains available for reuse."""
    seen_grounded_ids: list[list[str]] = []

    class InspectingProvider:
        def complete_with_tools(self, *, messages, tools):
            for message in messages:
                if (
                    message.get("role") == "assistant"
                    and "grounded_evidence_ids" in message
                ):
                    seen_grounded_ids.append(list(message["grounded_evidence_ids"]))
            return FinalAnswer(answer_text="ok", evidence_references=[])

    tools = make_tools()
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump is here.",
            evidence_references=[PUMP_ID, "node-removed-since"],
        ),
        ConversationTurn(
            question="And the nozzle?",
            answer_text="Nozzle is there.",
            evidence_references=[NOZZLE_ID],
        ),
        ConversationTurn(
            question="And the segment?",
            answer_text="Segment continues.",
            evidence_references=[SEGMENT_ID],
        ),
    ]

    run_grounded_qa_turn(
        question="Thanks",
        topology_tools=tools,
        provider=InspectingProvider(),
        conversation=conversation,
        max_conversation_turns=2,
    )

    offered = {
        evidence_id for grounded in seen_grounded_ids for evidence_id in grounded
    }
    # Valid identities survive compaction and remain reusable by identity.
    assert PUMP_ID in offered
    assert NOZZLE_ID in offered
    # The stale identity is dropped; it is never offered back for reuse.
    assert "node-removed-since" not in offered


def test_compaction_summary_prose_is_never_promoted_to_evidence():
    """A model that cites the compacted summary prose as an identity has that
    citation rejected; folded prose remains context and never becomes evidence."""

    class ProseCitingProvider:
        def complete_with_tools(self, *, messages, tools):
            summary_text = ""
            for message in messages:
                if message.get(
                    "role"
                ) == "user" and "Earlier in this conversation" in str(
                    message.get("content", "")
                ):
                    summary_text = str(message["content"])
            return FinalAnswer(
                answer_text="Reusing the summary.",
                evidence_references=[summary_text],
                interpreted_object_ids=[summary_text],
            )

    tools = make_tools()
    conversation = [
        ConversationTurn(
            question="Where is the pump?",
            answer_text="The pump is here.",
            evidence_references=[PUMP_ID],
        ),
        ConversationTurn(
            question="And the nozzle?",
            answer_text="Nozzle is there.",
            evidence_references=[NOZZLE_ID],
        ),
        ConversationTurn(
            question="And the segment?",
            answer_text="Segment continues.",
            evidence_references=[SEGMENT_ID],
        ),
    ]

    result = run_grounded_qa_turn(
        question="Summarize",
        topology_tools=tools,
        provider=ProseCitingProvider(),
        conversation=conversation,
        max_conversation_turns=2,
    )
    assert result.evidence_references == []
    assert result.interpreted_object_ids == []
