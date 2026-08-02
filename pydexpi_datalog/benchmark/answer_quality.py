"""Qualitative judging for ordinary grounded benchmark answers.

The deterministic benchmark grade remains authoritative.  This module scores
only the natural-language answer and is intentionally injectable so offline
CI uses :class:`ScriptedAnswerQualityJudge` rather than making model calls.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydexpi_datalog.benchmark.contract import StructuredAnswer
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.llm.model_access import ModelProvider

ANSWER_QUALITY_RUBRIC_VERSION = "answer-quality-v2"
GROUNDING_REQUIRED = "required"
GROUNDING_HELPFUL = "helpful"
GROUNDING_NOT_NEEDED = "not_needed"
GROUNDING_EXPECTATIONS = (
    GROUNDING_REQUIRED,
    GROUNDING_HELPFUL,
    GROUNDING_NOT_NEEDED,
)


@dataclass(frozen=True)
class AnswerQualityJudgment:
    """A qualitative result that cannot override deterministic correctness."""

    answered_question: bool
    faithful_to_evidence: bool
    engineering_language: bool
    scope_honest: bool
    provenance_clear: bool
    grounding_expectation: str
    grounding_fit: bool
    useful_next_step: bool
    overall_score: int
    rationale: str

    def to_payload(self) -> dict[str, object]:
        return {
            "answered_question": self.answered_question,
            "faithful_to_evidence": self.faithful_to_evidence,
            "engineering_language": self.engineering_language,
            "scope_honest": self.scope_honest,
            "provenance_clear": self.provenance_clear,
            "grounding_expectation": self.grounding_expectation,
            "grounding_fit": self.grounding_fit,
            "useful_next_step": self.useful_next_step,
            "overall_score": self.overall_score,
            "rationale": self.rationale,
        }


@runtime_checkable
class AnswerQualityJudge(Protocol):
    """Assess natural-language quality without deciding answer correctness."""

    @property
    def judge_id(self) -> str: ...

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        graph_facts: dict[str, object],
    ) -> AnswerQualityJudgment: ...


@dataclass(frozen=True)
class ModelAnswerQualityJudge:
    """Provider-backed qualitative judge used by live evaluation runs."""

    provider: ModelProvider

    @property
    def judge_id(self) -> str:
        return (
            f"llm-answer-quality-judge:{self.provider.provider}:{self.provider.model}"
        )

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        graph_facts: dict[str, object],
    ) -> AnswerQualityJudgment:
        payload = {
            "question": question.question,
            "answer": {
                "text": answer.answer_text,
                "verdict": answer.verdict,
                "posture": answer.posture,
                "witness_ids": list(answer.witness_ids),
                "support": answer.support,
            },
            "expected_deterministic_result": {
                "verdict": question.ground_truth.verdict,
                "witness_ids": list(question.ground_truth.witness_ids),
            },
            "source_evidence": _evidence_summary(
                graph_facts=graph_facts,
                witness_ids=(
                    *question.ground_truth.witness_ids,
                    *answer.witness_ids,
                ),
            ),
        }
        prompt = "\n".join(
            [
                "Judge the natural-language quality of this engineering answer as a "
                "wastewater-treatment and oil-refinery process SME.",
                "Do not require formal logic syntax. If the answer includes a rule, "
                "query, or agent plan, judge whether its condition, scope, result, and "
                "limitations are explained in plain process-engineering language.",
                "Do not replace or override deterministic verdict or witness checks.",
                "answered_question: directly addresses the user's request.",
                "faithful_to_evidence: source claims match supplied evidence when the "
                "question requires source grounding; absence of citation is not a failure "
                "when grounding is not needed.",
                "engineering_language: uses clear, domain-appropriate wording without "
                "requiring specialist logic terminology.",
                "scope_honest: distinguishes source observation, engineering inference, "
                "and recommendation without overclaiming.",
                "provenance_clear: makes the support traceable when grounding is required; "
                "does not add irrelevant IDs or proof when grounding is not needed.",
                "grounding_expectation: choose required, helpful, or not_needed based on "
                "what the question asks, not on a blanket citation rule.",
                "grounding_fit: the answer uses the appropriate amount of source support; "
                "a not_needed answer stays direct instead of adding a proof dump.",
                "useful_next_step: offers a useful clarification or follow-up when one is "
                "needed.",
                "Rationale must briefly explain what the answer claimed and why its "
                "evidence level was or was not appropriate. Do not reveal private "
                "chain-of-thought.",
                "Return exactly one JSON object with seven booleans, grounding_expectation "
                "as one allowed string, overall_score as an integer from 1 to 5, and a "
                "non-empty rationale string.",
                json.dumps(payload, indent=2, sort_keys=True),
            ]
        )
        raw = self.provider.complete(
            request=prompt,
            context={
                "task": "benchmark_answer_quality_judge",
                "question_id": question.question_id,
                "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
            },
        )
        return _parse_judgment(raw)


@dataclass(frozen=True)
class ScriptedAnswerQualityJudge:
    """Deterministic answer-quality judge keyed by question ID."""

    judgments: Mapping[str, AnswerQualityJudgment]
    judge_id: str = "scripted-answer-quality-judge"

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        graph_facts: dict[str, object],
    ) -> AnswerQualityJudgment:
        del answer, graph_facts
        try:
            return self.judgments[question.question_id]
        except KeyError:
            raise KeyError(
                f"Scripted answer-quality judge {self.judge_id!r} has no judgment for "
                f"question {question.question_id!r}."
            ) from None


def _parse_judgment(raw: object) -> AnswerQualityJudgment:
    malformed = AnswerQualityJudgment(
        answered_question=False,
        faithful_to_evidence=False,
        engineering_language=False,
        scope_honest=False,
        provenance_clear=False,
        grounding_expectation=GROUNDING_REQUIRED,
        grounding_fit=False,
        useful_next_step=False,
        overall_score=1,
        rationale="Malformed or refused answer-quality output; no qualitative credit.",
    )
    if not isinstance(raw, str):
        return malformed
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return malformed
    boolean_fields = {
        "answered_question",
        "faithful_to_evidence",
        "engineering_language",
        "scope_honest",
        "provenance_clear",
        "grounding_fit",
        "useful_next_step",
    }
    fields = {
        *boolean_fields,
        "grounding_expectation",
        "overall_score",
        "rationale",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        return malformed
    booleans = [payload[name] for name in boolean_fields]
    grounding_expectation = payload["grounding_expectation"]
    score = payload["overall_score"]
    rationale = payload["rationale"]
    if (
        not all(isinstance(value, bool) for value in booleans)
        or not isinstance(grounding_expectation, str)
        or grounding_expectation not in GROUNDING_EXPECTATIONS
        or not isinstance(score, int)
        or isinstance(score, bool)
        or score not in range(1, 6)
        or not isinstance(rationale, str)
        or not rationale.strip()
    ):
        return malformed
    return AnswerQualityJudgment(
        answered_question=payload["answered_question"],
        faithful_to_evidence=payload["faithful_to_evidence"],
        engineering_language=payload["engineering_language"],
        scope_honest=payload["scope_honest"],
        provenance_clear=payload["provenance_clear"],
        grounding_expectation=grounding_expectation,
        grounding_fit=payload["grounding_fit"],
        useful_next_step=payload["useful_next_step"],
        overall_score=score,
        rationale=rationale,
    )


def _evidence_summary(
    *, graph_facts: Mapping[str, object], witness_ids: tuple[str, ...]
) -> list[dict[str, object]]:
    facts = graph_facts.get("facts", graph_facts)
    if not isinstance(facts, Mapping):
        return []
    nodes = facts.get("nodes", [])
    if not isinstance(nodes, list):
        return []
    wanted = set(witness_ids)
    summary: list[dict[str, object]] = []
    for node in nodes:
        if not isinstance(node, Mapping) or str(node.get("node_id", "")) not in wanted:
            continue
        attributes = node.get("attributes", {})
        attributes = attributes if isinstance(attributes, Mapping) else {}
        source_label = (
            attributes.get("proteusId")
            or attributes.get("tag_name")
            or attributes.get("display_name")
            or node.get("proteusId")
            or node.get("tag_name")
            or node.get("display_name")
            or node.get("label")
            or attributes.get("label")
            or node.get("node_id", "")
        )
        object_kind = attributes.get("label") or node.get("label") or "unknown"
        summary.append(
            {
                "source_label": str(source_label),
                "object_kind": str(object_kind),
            }
        )
    return summary
