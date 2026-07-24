"""Rule-evaluation branch: specialist tool surface + escalate (bead 3qo.9.15)."""

from __future__ import annotations

from pydexpi_datalog.qa.grounded_qa_harness import (
    FinalAnswer,
    ToolCall,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

RULE_QUESTION = (
    "Does every piping network segment have exactly one sourceItem reference?"
)
LOOKUP_QUESTION = "Where is pump P-101?"

MINIMAL_TOPOLOGY = {
    "source_id": "drawing-v1",
    "nodes": [
        {
            "id": "pump-1",
            "label": "CentrifugalPump",
            "class_name": "CentrifugalPump",
            "display_name": "P-101",
            "category": "equipment",
        }
    ],
    "edges": [],
    "evidence_map": {"pump-1": {"source_graph_node_id": "pump-1"}},
}


def _tools() -> TopologyTools:
    return TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="rule-eval-branch",
    )


def _tool_names(tools: list[dict[str, object]]) -> set[str]:
    names: set[str] = set()
    for definition in tools:
        function = definition.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
    return names


def test_rule_evaluation_offers_logic_tools_not_topology_retrieval() -> None:
    """Specialist branch: rule questions must not see find/reach as options."""

    class CaptureOffer:
        def __init__(self) -> None:
            self.offers: list[set[str]] = []
            self.choices: list[str] = []

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.offers.append(_tool_names(tools))
            self.choices.append(tool_choice)
            return ToolCall(
                tool_name="report_template_no_fit",
                tool_input={
                    "reason": "No bundled template for segment sourceItem cardinality.",
                    "structured_intent": {
                        "source_classes": ["PipingNetworkSegment"],
                        "target_classes": ["TopologyObject"],
                        "source_role": "equipment",
                        "target_role": "referenced_object",
                        "graph_scope": "piping_only",
                        "direction": "undirected",
                        "quantifier": "all",
                        "negated": False,
                        "output_obligations": ["violating_source_ids"],
                    },
                },
                tool_call_id="no-fit-1",
            )

    provider = CaptureOffer()
    try:
        run_grounded_qa_turn(
            question=RULE_QUESTION,
            topology_tools=_tools(),
            provider=provider,
            max_rounds=1,
        )
    except RuntimeError:
        pass
    assert provider.offers
    first = provider.offers[0]
    assert "propose_temporary_datalog" in first
    assert "execute_bundled_query_template" in first
    assert "report_template_no_fit" in first
    assert "find_equipment" not in first
    assert "get_reachable_equipment" not in first


def test_rule_evaluation_first_turn_requires_tool_then_resets() -> None:
    """Per-turn tool_choice: force once, then reset to auto (OpenAI pattern)."""

    class TwoToolsThenStop:
        def __init__(self) -> None:
            self.choices: list[str] = []
            self.calls = 0

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.calls += 1
            self.choices.append(tool_choice)
            if self.calls == 1:
                return ToolCall(
                    tool_name="report_template_no_fit",
                    tool_input={
                        "reason": "No template fit.",
                        "structured_intent": {
                            "source_classes": ["PipingNetworkSegment"],
                            "target_classes": ["TopologyObject"],
                            "source_role": "equipment",
                            "target_role": "referenced_object",
                            "graph_scope": "piping_only",
                            "direction": "undirected",
                            "quantifier": "all",
                            "negated": False,
                            "output_obligations": ["violating_source_ids"],
                        },
                    },
                    tool_call_id="no-fit-1",
                )
            return FinalAnswer(
                answer_text="Need a generated program next.",
                grounding_posture="source_data_unavailable",
            )

    provider = TwoToolsThenStop()
    run_grounded_qa_turn(
        question=RULE_QUESTION,
        topology_tools=_tools(),
        provider=provider,
        max_rounds=3,
    )
    assert provider.choices[0] == "required"
    assert provider.choices[1] == "auto"


def test_object_lookup_still_offers_find_equipment() -> None:
    class CaptureOffer:
        def __init__(self) -> None:
            self.offers: list[set[str]] = []

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.offers.append(_tool_names(tools))
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": "P-101"},
                tool_call_id="find-1",
            )

    provider = CaptureOffer()
    try:
        run_grounded_qa_turn(
            question=LOOKUP_QUESTION,
            topology_tools=_tools(),
            provider=provider,
            max_rounds=1,
        )
    except RuntimeError:
        pass
    assert provider.offers
    assert "find_equipment" in provider.offers[0]


def test_two_retrievals_without_logic_attempt_forces_required_next() -> None:
    """Soft budget: after two topology retrievals on a rule path, force a tool."""

    class RetrievalThrashThenLogic:
        def __init__(self) -> None:
            self.choices: list[str] = []
            self.calls = 0
            self.offers: list[set[str]] = []

        def complete_with_tools(self, *, messages, tools, tool_choice: str = "auto"):
            self.calls += 1
            self.choices.append(tool_choice)
            self.offers.append(_tool_names(tools))
            if self.calls <= 2:
                # Model ignores the specialist offer and asks for retrieval anyway.
                return ToolCall(
                    tool_name="find_equipment",
                    tool_input={"pattern": "segment"},
                    tool_call_id=f"find-{self.calls}",
                )
            if self.calls == 3:
                assert tool_choice == "required"
                assert "find_equipment" not in self.offers[-1]
                return ToolCall(
                    tool_name="report_template_no_fit",
                    tool_input={
                        "reason": "Escalating after retrieval thrash.",
                        "structured_intent": {
                            "source_classes": ["PipingNetworkSegment"],
                            "target_classes": ["TopologyObject"],
                            "source_role": "equipment",
                            "target_role": "referenced_object",
                            "graph_scope": "piping_only",
                            "direction": "undirected",
                            "quantifier": "all",
                            "negated": False,
                            "output_obligations": ["violating_source_ids"],
                        },
                    },
                    tool_call_id="no-fit-after-escalate",
                )
            return FinalAnswer(
                answer_text="Stopping after escalate path was exercised.",
                grounding_posture="source_data_unavailable",
            )

    provider = RetrievalThrashThenLogic()
    result = run_grounded_qa_turn(
        question=RULE_QUESTION,
        topology_tools=_tools(),
        provider=provider,
        max_rounds=4,
    )
    assert provider.calls >= 3
    assert provider.choices[0] == "required"
    assert provider.choices[1] == "auto"
    assert provider.choices[2] == "required"
    find_attempts = [
        entry
        for entry in result.tool_call_trace
        if entry.get("tool_name") == "find_equipment"
    ]
    assert len(find_attempts) >= 2
