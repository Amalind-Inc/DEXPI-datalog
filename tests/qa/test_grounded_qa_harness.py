"""
Behavioral contract tests for the grounded QA harness.

Boundary: run_grounded_qa_turn() public function + TopologyTools.execute()
These tests do not inspect message lists, tool call counts, or internal state.
They assert what a caller observes: answer text, evidence references, witnesses.
"""
import json
import pytest

from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_GENERAL_KNOWLEDGE,
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


# ---------------------------------------------------------------------------
# Minimal topology fixture
# ---------------------------------------------------------------------------

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
        {"id": EDGE_PUMP_NOZZLE, "source_id": PUMP_ID, "target_id": NOZZLE_ID, "relationship": "has_nozzle"},
        {"id": EDGE_NOZZLE_SEGMENT, "source_id": NOZZLE_ID, "target_id": SEGMENT_ID, "relationship": "connected_to"},
        {"id": EDGE_SEGMENT_VALVE, "source_id": SEGMENT_ID, "target_id": VALVE_ID, "relationship": "connected_to"},
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
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": "Check whether every pump has a reachable valve.",
                    "resolved_identity_ids": [PUMP_ID],
                },
                tool_call_id="escalate-datalog",
            )
        return FinalAnswer(answer_text="This needs confirmed generated logic.")


class ImmediateConversationProvider:
    def complete_with_tools(self, *, messages, tools):
        return FinalAnswer(answer_text="Happy to help.")


class UnexpectedProviderCall:
    def complete_with_tools(self, *, messages, tools):
        raise AssertionError("source mutation requests should be denied before model use")


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


def test_universal_claim_from_sampled_path_escalates_to_confirmed_logic():
    result = run_grounded_qa_turn(
        question="Do all pumps have a reachable valve?",
        topology_tools=make_tools(),
        provider=SampledPathThenDatalogProvider(),
    )

    assert result.answer_text == "This needs confirmed generated logic."
    tool_names = [trace["tool_name"] for trace in result.tool_call_trace]
    assert "__evidence_sufficiency__" in tool_names
    assert "propose_temporary_datalog" in tool_names


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
    rejected = next(t for t in result.tool_call_trace if t["tool_name"] == "nonexistent_tool")
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
    assert VALVE_ID in result.evidence_references or NOZZLE_ID in result.evidence_references


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
                if message.get("role") == "assistant" and "grounded_evidence_ids" in message:
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
                if message.get("role") == "assistant" and "grounded_evidence_ids" in message:
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

    offered = {evidence_id for grounded in seen_grounded_ids for evidence_id in grounded}
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
                if message.get("role") == "assistant" and "grounded_evidence_ids" in message:
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

    offered = {evidence_id for grounded in seen_grounded_ids for evidence_id in grounded}
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
                if message.get("role") == "user" and "Earlier in this conversation" in str(
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
