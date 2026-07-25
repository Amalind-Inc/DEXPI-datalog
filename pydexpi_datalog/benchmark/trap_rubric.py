"""Qualitative judge seam for informational trap-slice grading.

The live matrix may put an LLM judge behind :class:`TrapJudge`; behavior tests
use :class:`ScriptedTrapJudge` so CI never makes model calls.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydexpi_datalog.benchmark.contract import (
    StructuredAnswer,
    TrapJudgment,
    TrapRubric,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.llm.model_access import ModelProvider


@runtime_checkable
class TrapJudge(Protocol):
    """Assess refusal grounding and redirect quality for one trap answer."""

    @property
    def judge_id(self) -> str: ...

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        rubric: TrapRubric,
    ) -> TrapJudgment: ...


@dataclass(frozen=True)
class ModelTrapJudge:
    """Provider-backed qualitative judge used by live benchmark runs."""

    provider: ModelProvider

    @property
    def judge_id(self) -> str:
        return f"llm-trap-judge:{self.provider.provider}:{self.provider.model}"

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        rubric: TrapRubric,
    ) -> TrapJudgment:
        payload = {
            "question": question.question,
            "answer_text": answer.answer_text,
            "rubric": {
                "expected_posture": rubric.expected_posture,
                "refusal_basis": rubric.refusal_basis,
                "redirect_target": rubric.redirect_target,
            },
        }
        prompt = "\n".join(
            [
                "Judge this benchmark trap response on exactly two axes.",
                "grounded_refusal is true only when the response identifies the "
                "relevant limitation or ambiguity without inventing source facts.",
                "graceful_redirect is true only when it offers the rubric's useful "
                "next step, not merely a bare refusal.",
                "Return exactly one JSON object with boolean grounded_refusal, "
                "boolean graceful_redirect, and a non-empty rationale string.",
                json.dumps(payload, indent=2, sort_keys=True),
            ]
        )
        raw = self.provider.complete(
            request=prompt,
            context={
                "task": "benchmark_trap_judge",
                "question_id": question.question_id,
            },
        )
        return _parse_judgment(raw)


def _parse_judgment(raw: object) -> TrapJudgment:
    malformed = TrapJudgment(
        grounded_refusal=False,
        graceful_redirect=False,
        rationale="Malformed or refused trap-judge output; no rubric credit.",
    )
    if not isinstance(raw, str):
        return malformed
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return malformed
    if not isinstance(payload, dict) or set(payload) != {
        "grounded_refusal",
        "graceful_redirect",
        "rationale",
    }:
        return malformed
    grounded_refusal = payload["grounded_refusal"]
    graceful_redirect = payload["graceful_redirect"]
    rationale = payload["rationale"]
    if (
        not isinstance(grounded_refusal, bool)
        or not isinstance(graceful_redirect, bool)
        or not isinstance(rationale, str)
        or not rationale.strip()
    ):
        return malformed
    return TrapJudgment(
        grounded_refusal=grounded_refusal,
        graceful_redirect=graceful_redirect,
        rationale=rationale,
    )


@dataclass(frozen=True)
class ScriptedTrapJudge:
    """Deterministic trap judge keyed by question ID; no model calls."""

    judgments: Mapping[str, TrapJudgment]
    judge_id: str = "scripted-trap-judge"

    def judge(
        self,
        *,
        question: BenchmarkQuestion,
        answer: StructuredAnswer,
        rubric: TrapRubric,
    ) -> TrapJudgment:
        try:
            return self.judgments[question.question_id]
        except KeyError:
            raise KeyError(
                f"Scripted trap judge {self.judge_id!r} has no judgment for "
                f"question {question.question_id!r}."
            ) from None


def load_scripted_trap_judgments(path: Path) -> dict[str, TrapJudgment]:
    """Load deterministic question-ID judgments for the scripted CLI path."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Scripted trap judgments at {path} must be a JSON object.")
    judgments: dict[str, TrapJudgment] = {}
    for question_id, payload in raw.items():
        if not isinstance(question_id, str) or not isinstance(payload, dict):
            raise ValueError(
                "Each scripted trap judgment must map a question ID to an object."
            )
        judgment = _parse_judgment(json.dumps(payload))
        if judgment.rationale.startswith("Malformed or refused"):
            raise ValueError(
                f"Scripted trap judgment for {question_id!r} must contain exactly "
                "boolean grounded_refusal, boolean graceful_redirect, and a "
                "non-empty rationale string."
            )
        judgments[question_id] = judgment
    return judgments
