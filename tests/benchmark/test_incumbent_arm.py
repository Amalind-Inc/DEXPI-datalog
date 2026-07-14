"""Behavior tests for Arm B: the incumbent grounded-QA pipeline adapter.

The incumbent is driven at its existing public boundary (``run_grounded_qa_turn``
+ ``TopologyTools``), its generated-Datalog confirmation gate stays and is
auto-confirmed as part of the episode, and the pipeline outcome maps to a
:class:`StructuredAnswer` so the incumbent is graded on the same terms as the
challengers.  Scripted QA providers only: zero live LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.benchmark import (
    POSTURE_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
    run_benchmark,
    ScriptedTrapJudge,
    TrapJudgment,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.incumbent_arm import (
    DEGRADED_VERDICT,
    IncumbentArm,
    create_incumbent_arm,
)
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_OUT_OF_SCOPE as HARNESS_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE as HARNESS_SOURCE_DATA_UNAVAILABLE,
    FinalAnswer,
    ToolCall,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.workflow.review_session import build_topology_view_model

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)


# --------------------------------------------------------------------------
# Scripted QA providers (no live calls)
# --------------------------------------------------------------------------


class ImmediateFinalAnswerProvider:
    """Returns one fixed FinalAnswer; must be consulted exactly once."""

    def __init__(self, final: FinalAnswer) -> None:
        self._final = final
        self.calls = 0
        self.usage = {
            "input_tokens": 80,
            "output_tokens": 10,
            "total_tokens": 90,
            "cost_usd": 0.003,
        }

    def complete_with_tools(self, *, messages, tools):
        self.calls += 1
        return self._final


class ProposeDatalogProvider:
    """Proposes a temporary Datalog query once, then must never be consulted
    again: after a confirmation_required result the harness ends the turn and
    the adapter auto-confirms without re-authoring through the model."""

    def __init__(
        self, *, generated_datalog: str, formal_restatement: str, request: str
    ) -> None:
        self._generated_datalog = generated_datalog
        self._formal_restatement = formal_restatement
        self._request = request
        self.calls = 0

    def complete_with_tools(self, *, messages, tools):
        self.calls += 1
        assert self.calls == 1, "model consulted after the confirmation gate"
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": self._request,
                "generated_datalog": self._generated_datalog,
                "formal_restatement": self._formal_restatement,
            },
            tool_call_id="scripted-propose",
        )


class InfiniteToolCallProvider:
    """Never authors a final answer: drives the harness past its round cap."""

    def complete_with_tools(self, *, messages, tools):
        return ToolCall(
            tool_name="find_equipment",
            tool_input={"pattern": ""},
            tool_call_id="scripted-loop",
        )


# --------------------------------------------------------------------------
# Probes: compute expectations through the same public tools the adapter uses
# --------------------------------------------------------------------------


def _tools_and_view() -> tuple[TopologyTools, dict]:
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    source_id = graph_facts.get("source_id")
    topology_view = build_topology_view_model(
        graph_facts=graph_facts,
        session_id="probe",
        source_id=source_id if isinstance(source_id, str) else None,
    )
    tools = TopologyTools(
        topology_view=topology_view,
        graph_facts=graph_facts,
        session_id="probe",
    )
    return tools, topology_view


def _raw_of(stable_id: str, topology_view: dict) -> str:
    entry = topology_view["evidence_map"][stable_id]
    return str(entry["canonical_fact"]["node_id"])


def _anchor_with_reachables() -> tuple[str, list[str]]:
    """Find a raw node id whose reachability is non-empty, and return that
    anchor plus the expected matched raw node ids (sorted).

    The temporary Datalog EDB is built from the raw graph facts, so anchors
    are raw ``node_id``s; the engine's evidence items come back in stable-ID
    space and are translated back to raw for grading.
    """
    tools, view = _tools_and_view()
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    raw_ids = [str(node["node_id"]) for node in graph_facts["facts"]["nodes"]]
    for raw_id in raw_ids:
        datalog = (
            ".decl answer(x:symbol)\n.output answer\n"
            f'answer(x) :- reachable("{raw_id}", x).'
        )
        proposal = tools.execute(
            "propose_temporary_datalog",
            {
                "request": "reachability probe",
                "generated_datalog": datalog,
                "formal_restatement": "Return reachable objects.",
            },
        )
        if proposal.get("status") != "confirmation_required":
            continue
        execution = tools.execute_confirmed_temporary_datalog(proposal)
        items = execution.get("evidence", {}).get("items", [])
        if execution.get("status") == "answered" and items:
            matched_raw = sorted(_raw_of(str(item["id"]), view) for item in items)
            return raw_id, matched_raw
    raise AssertionError("no reachable anchor found in E06 fixture")


def _question(text: str, *, slice_name: str = "hand_authored") -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="q",
        question=text,
        slice=slice_name,
        drawing_ref=E06_GRAPH_FACTS,
        ground_truth=GroundTruth(verdict=VERDICT_UNANSWERABLE),
    )


def _arm(provider) -> IncumbentArm:
    return IncumbentArm(provider_factory=lambda: provider)


# --------------------------------------------------------------------------
# Non-gated mapping: refusal / non-source postures -> unanswerable
# --------------------------------------------------------------------------


def test_source_data_unavailable_answer_maps_to_unanswerable() -> None:
    provider = ImmediateFinalAnswerProvider(
        FinalAnswer(
            answer_text="The drawing does not record an approval date.",
            grounding_posture=HARNESS_SOURCE_DATA_UNAVAILABLE,
        )
    )
    answer = _arm(provider).answer(
        question=_question("When was this drawing approved?", slice_name="trap"),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.posture == POSTURE_SOURCE_DATA_UNAVAILABLE
    assert answer.witness_ids == ()
    assert provider.calls == 1
    assert answer.usage == provider.usage


def test_out_of_scope_answer_maps_to_unanswerable() -> None:
    provider = ImmediateFinalAnswerProvider(
        FinalAnswer(
            answer_text="That is outside this drawing.",
            grounding_posture=HARNESS_OUT_OF_SCOPE,
        )
    )
    answer = _arm(provider).answer(
        question=_question("What is the capital of France?", slice_name="trap"),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.posture == POSTURE_OUT_OF_SCOPE


def test_general_knowledge_answer_maps_to_unanswerable() -> None:
    from pydexpi_datalog.benchmark import POSTURE_GENERAL_KNOWLEDGE
    from pydexpi_datalog.qa.grounded_qa_harness import (
        POSTURE_GENERAL_KNOWLEDGE as HARNESS_GENERAL_KNOWLEDGE,
    )

    provider = ImmediateFinalAnswerProvider(
        FinalAnswer(
            answer_text="Flow direction is generally read from arrows and specs.",
            grounding_posture=HARNESS_GENERAL_KNOWLEDGE,
        )
    )
    answer = _arm(provider).answer(
        question=_question(
            "Explain in general how process flow direction is determined.",
            slice_name="trap",
        ),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert provider.calls == 1
    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.posture == POSTURE_GENERAL_KNOWLEDGE
    assert answer.witness_ids == ()


# --------------------------------------------------------------------------
# Confirmation gate: auto-confirmed, cost surfaces in the transcript
# --------------------------------------------------------------------------


def test_confirmed_datalog_with_matches_maps_to_violation_found() -> None:
    anchor, expected_raw = _anchor_with_reachables()
    provider = ProposeDatalogProvider(
        request="Which objects are reachable, as a rule?",
        generated_datalog=(
            ".decl answer(x:symbol)\n.output answer\n"
            f'answer(x) :- reachable("{anchor}", x).'
        ),
        formal_restatement="Return objects reachable from the anchor.",
    )
    answer = _arm(provider).answer(
        question=_question("Is any object reachable in violation of the rule?"),
        drawing_ref=E06_GRAPH_FACTS,
    )

    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert answer.posture == POSTURE_SOURCE_GROUNDED
    assert sorted(answer.witness_ids) == expected_raw
    # Witnesses live in the raw node_id space of the canonical base fact
    # layer - validated against graph_facts directly, independent of the
    # evidence-map translation used to compute the expectation.
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    known_raw = {str(node["node_id"]) for node in graph_facts["facts"]["nodes"]}
    assert set(answer.witness_ids) <= known_raw
    # The model proposed once and was never consulted again after the gate.
    assert provider.calls == 1
    # The confirmation gate's cost is on the transcript: the proposal and its
    # executed result both appear.
    tool_names = [
        str(message.get("tool_name", ""))
        for message in answer.transcript
        if message.get("role") == "tool"
    ]
    assert "propose_temporary_datalog" in tool_names
    assert "execute_confirmed_temporary_datalog" in tool_names


def test_confirmed_datalog_without_matches_maps_to_no_violation() -> None:
    provider = ProposeDatalogProvider(
        request="Any violations reachable from a non-existent anchor?",
        generated_datalog=(
            ".decl answer(x:symbol)\n.output answer\n"
            'answer(x) :- reachable("node-does-not-exist", x).'
        ),
        formal_restatement="Return objects reachable from a missing anchor.",
    )
    answer = _arm(provider).answer(
        question=_question("Is any object in violation of the rule?"),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert answer.verdict == VERDICT_NO_VIOLATION
    assert answer.posture == POSTURE_SOURCE_GROUNDED
    assert answer.witness_ids == ()


def test_failed_gate_execution_maps_to_unanswerable() -> None:
    # Wrong reachable arity passes static validation but fails at the engine.
    provider = ProposeDatalogProvider(
        request="Use reachable with the wrong arity",
        generated_datalog=(
            ".decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable(x)."
        ),
        formal_restatement="Return reachable objects.",
    )
    answer = _arm(provider).answer(
        question=_question("Is any object in violation of the rule?"),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.posture == POSTURE_SOURCE_DATA_UNAVAILABLE


# --------------------------------------------------------------------------
# Failure: the harness runs out of rounds -> never-creditable, never crashes
# --------------------------------------------------------------------------


def test_harness_round_exhaustion_degrades_not_crashes() -> None:
    answer = _arm(InfiniteToolCallProvider()).answer(
        question=_question("loop forever"),
        drawing_ref=E06_GRAPH_FACTS,
    )
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.posture == POSTURE_UNSPECIFIED
    assert answer.witness_ids == ()


# --------------------------------------------------------------------------
# arm_id and live model selection through the existing provider layer
# --------------------------------------------------------------------------


def test_arm_id_names_the_incumbent_and_model() -> None:
    arm = IncumbentArm(
        provider_factory=lambda: ImmediateFinalAnswerProvider(
            FinalAnswer(answer_text="x")
        ),
        provider_name="openrouter",
        model_name="openai/gpt-5.4",
    )
    assert arm.arm_id == "b-incumbent:openrouter:openai/gpt-5.4"


def test_create_incumbent_arm_requires_credential() -> None:
    try:
        create_incumbent_arm("gpt", environ={})
    except ValueError as error:
        assert "OPENROUTER_API_KEY" in str(error)
    else:  # pragma: no cover - explicit failure
        raise AssertionError("missing credential must fail fast")


def test_create_incumbent_arm_rejects_unknown_model_key() -> None:
    try:
        create_incumbent_arm("bogus", environ={"OPENROUTER_API_KEY": "x"})
    except ValueError as error:
        assert "bogus" in str(error)
    else:  # pragma: no cover - explicit failure
        raise AssertionError("unknown model key must fail fast")


def test_create_incumbent_arm_selects_all_three_models() -> None:
    for key in ("sonnet", "gpt", "deepseek"):
        arm = create_incumbent_arm(key, environ={"OPENROUTER_API_KEY": "x"})
        assert arm.arm_id.startswith("b-incumbent:openrouter:")


# --------------------------------------------------------------------------
# End to end through the runner: incumbent graded on the same terms
# --------------------------------------------------------------------------


class TrapOrRuleProvider:
    """One provider that branches on the question: traps refuse, rule
    questions escalate to the confirmation-gated Datalog capability."""

    def __init__(self, *, anchor: str) -> None:
        self._anchor = anchor
        self._proposed = False

    def complete_with_tools(self, *, messages, tools):
        question = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                question = str(message.get("content", ""))
                break
        if "approved" in question.lower():
            return FinalAnswer(
                answer_text="No approval metadata is recorded.",
                grounding_posture=HARNESS_SOURCE_DATA_UNAVAILABLE,
            )
        self._proposed = True
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": question,
                "generated_datalog": (
                    ".decl answer(x:symbol)\n.output answer\n"
                    f'answer(x) :- reachable("{self._anchor}", x).'
                ),
                "formal_restatement": "Return reachable objects.",
            },
            tool_call_id="scripted-propose",
        )


def test_run_benchmark_grades_incumbent_end_to_end(tmp_path: Path) -> None:
    anchor, expected_raw = _anchor_with_reachables()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [
                    {
                        "id": "e06-trap",
                        "question": "When was this drawing approved?",
                        "slice": "trap",
                        "drawing": str(E06_GRAPH_FACTS),
                        "ground_truth": {"verdict": "unanswerable"},
                        "trap_rubric": {
                            "expected_posture": "source_data_unavailable",
                            "refusal_basis": "Approval history is absent.",
                            "redirect_target": "Offer source-grounded checks.",
                        },
                    },
                    {
                        "id": "e06-rule",
                        "question": "Is any object reachable in violation?",
                        "slice": "hand_authored",
                        "category": "compliance_universal",
                        "drawing": str(E06_GRAPH_FACTS),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": expected_raw,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    arm = IncumbentArm(
        provider_factory=lambda: TrapOrRuleProvider(anchor=anchor),
        provider_name="scripted",
        model_name="scripted",
    )
    report = run_benchmark(
        manifest_path=manifest,
        arm=arm,
        output_dir=tmp_path / "out",
        trap_judge=ScriptedTrapJudge(
            {
                "e06-trap": TrapJudgment(
                    grounded_refusal=True,
                    graceful_redirect=True,
                    rationale="Names the missing approval data and redirects.",
                )
            }
        ),
    )
    grades = {
        episode["question_id"]: episode["grade"]["passed"]
        for episode in report["episodes"]
    }
    assert grades == {"e06-trap": True, "e06-rule": True}
