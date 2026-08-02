"""Behavior tests for the qualitative answer-quality judge seam."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pydexpi_datalog.benchmark.answer_quality import (
    AnswerQualityJudgment,
    ModelAnswerQualityJudge,
    ScriptedAnswerQualityJudge,
)
from pydexpi_datalog.benchmark.contract import GroundTruth, StructuredAnswer
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.runner import ScriptedArm, run_benchmark
from pydexpi_datalog.llm.byok_provider import build_system_prompt, create_byok_provider
from pydexpi_datalog.llm.model_access import FakeModelProvider


def _question(question_text: str = "Which pump is represented?") -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="quality-1",
        question=question_text,
        slice="hand_authored",
        drawing_ref=Path("graph_facts.json"),
        ground_truth=GroundTruth(
            verdict="violation_found",
            witness_ids=("pump-1",),
        ),
    )


def _answer() -> StructuredAnswer:
    return StructuredAnswer(
        verdict="violation_found",
        witness_ids=("pump-1",),
        posture="source_grounded",
        answer_text="The represented pump is P-101.",
        support={"basis": "source label P-101"},
        transcript=(
            {"role": "system", "content": "Do not expose this private message."},
        ),
    )


def _facts() -> dict[str, object]:
    return {
        "facts": {
            "nodes": [
                {
                    "node_id": "pump-1",
                    "fact_type": "node",
                    "attributes": {"label": "CentrifugalPump", "proteusId": "P-101"},
                }
            ],
            "edges": [],
        }
    }


def test_judge_tasks_use_an_agent_literate_sme_system_prompt() -> None:
    for task in ("benchmark_answer_quality_judge", "benchmark_trap_judge"):
        prompt = build_system_prompt({"task": task})

        assert "wastewater" in prompt
        assert "oil refinery" in prompt
        assert "Pi" in prompt
        assert "OMP" in prompt
        assert "Codex" in prompt
        assert "Claude Code" in prompt
        assert "Datalog query generator" not in prompt


def test_model_answer_quality_judge_parses_rubric_and_excludes_transcript() -> None:
    provider = FakeModelProvider(
        json.dumps(
            {
                "answered_question": True,
                "faithful_to_evidence": True,
                "engineering_language": True,
                "scope_honest": True,
                "provenance_clear": True,
                "grounding_expectation": "required",
                "grounding_fit": True,
                "useful_next_step": False,
                "overall_score": 4,
                "rationale": "The answer identifies the pump and cites its source label.",
            }
        )
    )
    judge = ModelAnswerQualityJudge(provider=provider)

    result = judge.judge(question=_question(), answer=_answer(), graph_facts=_facts())

    assert result.grounding_expectation == "required"
    assert result.grounding_fit is True
    assert result.overall_score == 4
    assert result.faithful_to_evidence is True
    assert judge.judge_id == "llm-answer-quality-judge:fake:fake-model"
    request = provider.requests[0]["request"]
    assert "source label P-101" in request
    assert "Which pump is represented?" in request
    assert "The represented pump is P-101." in request
    assert "Do not expose this private message" not in request
    assert provider.requests[0]["context"]["task"] == "benchmark_answer_quality_judge"


def test_model_answer_quality_judge_accepts_nested_provider_schema() -> None:
    provider = FakeModelProvider(
        json.dumps(
            {
                "answer": {
                    "answered_question": True,
                    "faithful_to_evidence": True,
                    "engineering_language": True,
                    "scope_honest": True,
                    "provenance_clear": True,
                    "grounding_expectation": "required",
                    "grounding_fit": True,
                    "useful_next_step": False,
                },
                "overall_score": 5,
                "rationale": "The answer is clear, grounded, and useful.",
            }
        )
    )

    result = ModelAnswerQualityJudge(provider=provider).judge(
        question=_question(), answer=_answer(), graph_facts=_facts()
    )

    assert result.overall_score == 5
    assert result.answered_question is True
    assert result.grounding_expectation == "required"
    assert result.rationale == "The answer is clear, grounded, and useful."

def test_model_answer_quality_judge_accepts_answer_only_nested_schema() -> None:
    provider = FakeModelProvider(
        json.dumps(
            {
                "answer": {
                    "answered_question": True,
                    "faithful_to_evidence": True,
                    "engineering_language": True,
                    "scope_honest": True,
                    "provenance_clear": True,
                    "grounding_expectation": "required",
                    "grounding_fit": True,
                    "useful_next_step": False,
                    "overall_score": 4,
                    "rationale": "The answer is concise and source-grounded.",
                }
            }
        )
    )

    result = ModelAnswerQualityJudge(provider=provider).judge(
        question=_question(), answer=_answer(), graph_facts=_facts()
    )

    assert result.overall_score == 4
    assert result.grounding_fit is True
    assert result.rationale == "The answer is concise and source-grounded."



def test_sme_judge_allows_direct_answers_when_grounding_is_not_needed() -> None:
    provider = FakeModelProvider(
        json.dumps(
            {
                "answered_question": True,
                "faithful_to_evidence": True,
                "engineering_language": True,
                "scope_honest": True,
                "provenance_clear": True,
                "grounding_expectation": "not_needed",
                "grounding_fit": True,
                "useful_next_step": False,
                "overall_score": 5,
                "rationale": (
                    "The operator-facing recommendation is direct and does not "
                    "need a source proof block."
                ),
            }
        )
    )
    answer = StructuredAnswer(
        verdict="unanswerable",
        posture="general_knowledge",
        answer_text="Keep equalization capacity available before peak inflow.",
    )

    result = ModelAnswerQualityJudge(provider=provider).judge(
        question=_question(
            "What is a practical operator consideration for peak inflow?"
        ),
        answer=answer,
        graph_facts=_facts(),
    )

    assert result.grounding_expectation == "not_needed"
    assert result.grounding_fit is True
    assert "proof dump" in provider.requests[0]["request"]


def test_openrouter_judge_requests_zero_temperature() -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {},
            }

    provider = create_byok_provider(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        credential="test-key",
        base_url="https://openrouter.test/api/v1",
    )
    with patch("httpx.post", return_value=Response()) as post:
        provider.complete(
            request="{}",
            context={"task": "benchmark_answer_quality_judge"},
        )

    assert post.call_args.kwargs["json"]["temperature"] == 0


def test_malformed_answer_quality_judgment_receives_no_qualitative_credit() -> None:
    judge = ModelAnswerQualityJudge(provider=FakeModelProvider("not-json"))

    result = judge.judge(question=_question(), answer=_answer(), graph_facts=_facts())

    assert result.overall_score == 1
    assert result.answered_question is False
    assert "malformed" in result.rationale.lower()


def test_runner_keeps_deterministic_grade_separate_from_quality_judgment(
    tmp_path: Path,
) -> None:
    graph_path = tmp_path / "graph_facts.json"
    graph_path.write_text(json.dumps(_facts()), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [
                    {
                        "id": "quality-1",
                        "question": "Which pump is represented?",
                        "slice": "hand_authored",
                        "category": "retrieval_local",
                        "drawing": str(graph_path),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": ["pump-1"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    quality = AnswerQualityJudgment(
        answered_question=True,
        faithful_to_evidence=True,
        engineering_language=True,
        scope_honest=True,
        provenance_clear=True,
        grounding_expectation="required",
        grounding_fit=True,
        useful_next_step=False,
        overall_score=4,
        rationale="Clear and grounded.",
    )

    report = run_benchmark(
        manifest_path=manifest_path,
        arm=ScriptedArm(arm_id="scripted", answers={"quality-1": _answer()}),
        output_dir=tmp_path / "report",
        answer_quality_judge=ScriptedAnswerQualityJudge({"quality-1": quality}),
    )

    episode = report["episodes"][0]
    assert episode["grade"]["passed"] is True
    assert episode["answer_quality"]["judgment"]["overall_score"] == 4
    assert episode["answer_quality"]["rubric_version"] == "answer-quality-v2"
    assert episode["answer_quality"]["judgment"]["grounding_fit"] is True
    assert episode["answer_quality"]["deterministic_grade_passed"] is True
    assert report["answer_quality_judge_id"] == "scripted-answer-quality-judge"
