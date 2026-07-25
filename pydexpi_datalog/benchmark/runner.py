"""One-command benchmark runner: manifest -> arm episodes -> report artifact.

``run_benchmark`` is the spine every benchmark arm plugs into.  An arm
implements exactly one thing — ``answer(question, drawing_ref) ->
StructuredAnswer`` — and the runner owns loading, timing, grading, and the
persisted per-episode report.  Scripted arms make the whole path testable
with zero live LLM calls.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydexpi_datalog.benchmark.contract import (
    POSTURES,
    TRAP_EXPECTED_POSTURES,
    VERDICTS,
    GroundTruth,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.dataset import (
    SLICE_TRAP,
    BenchmarkQuestion,
    load_question_manifest,
)
from pydexpi_datalog.benchmark.grader import Grade, grade
from pydexpi_datalog.benchmark.trap_rubric import (
    ScriptedTrapJudge,
    TrapJudge,
    load_scripted_trap_judgments,
)

# Version 5: answers carry their submitted claim-to-support graph.
BENCHMARK_REPORT_SCHEMA_VERSION = 5
BENCHMARK_REPORT_FILENAME = "benchmark_report.json"


@runtime_checkable
class ArmAdapter(Protocol):
    """The only contract a benchmark arm implements.

    ``arm_id`` names the arm in reports; ``answer`` maps one question plus
    its drawing reference (a ``graph_facts.json`` path or a drawing bundle
    directory) to a :class:`StructuredAnswer`.
    """

    @property
    def arm_id(self) -> str: ...

    def answer(
        self, *, question: BenchmarkQuestion, drawing_ref: Path
    ) -> StructuredAnswer: ...


@dataclass(frozen=True)
class ScriptedArm:
    """Deterministic arm: pre-committed answers keyed by question ID.

    The OSS default for tests and dry runs; it performs no model calls and
    fails fast on any question it has no script for.
    """

    arm_id: str
    answers: Mapping[str, StructuredAnswer]

    def answer(
        self, *, question: BenchmarkQuestion, drawing_ref: Path
    ) -> StructuredAnswer:
        try:
            return self.answers[question.question_id]
        except KeyError:
            raise KeyError(
                f"Scripted arm {self.arm_id!r} has no answer for question "
                f"{question.question_id!r}."
            ) from None


def run_benchmark(
    *,
    manifest_path: Path,
    arm: ArmAdapter,
    output_dir: Path,
    trap_judge: TrapJudge | None = None,
    episode_workers: int = 1,
) -> dict[str, object]:
    """Run every manifest question through one arm and persist the report.

    The report artifact (``benchmark_report.json``) carries per-episode
    grade, usage (tokens/cost as reported by the arm), wall time, and the
    full transcript.  It is written only after every episode completes, so
    a failing arm never leaves a partial artifact behind.
    """
    dataset = load_question_manifest(manifest_path)
    trap_questions = [
        question for question in dataset.questions if question.slice == SLICE_TRAP
    ]
    if trap_questions and trap_judge is None:
        raise ValueError(
            "A trap_judge is required when the benchmark manifest contains "
            "trap-slice questions."
        )

    def execute(question: BenchmarkQuestion) -> dict[str, object]:
        return _run_episode(
            question=question,
            arm=arm,
            trap_judge=trap_judge,
        )

    if episode_workers == 1:
        episodes = [execute(question) for question in dataset.questions]
    else:
        with ThreadPoolExecutor(max_workers=episode_workers) as executor:
            episodes = list(executor.map(execute, dataset.questions))

    gating_episodes = [episode for episode in episodes if episode["gating"]]
    informational_episodes = [episode for episode in episodes if not episode["gating"]]

    report: dict[str, object] = {
        "schema_version": BENCHMARK_REPORT_SCHEMA_VERSION,
        "manifest_path": str(manifest_path.resolve()),
        "arm_id": arm.arm_id,
        "trap_judge_id": trap_judge.judge_id if trap_judge is not None else None,
        # The headline aggregate is deliberately gating-only. Trap scores
        # cannot influence it even when every trap passes or fails.
        "totals": _episode_totals(gating_episodes),
        "informational_totals": _episode_totals(informational_episodes),
        "human_spot_check": {
            "instructions": (
                "Review each flagged trap episode answer.answer_text against its "
                "refusal basis and redirect target; use the transcript only for "
                "audit, and record disagreements without changing the score."
            ),
            "question_ids": [
                question.question_id
                for question in trap_questions
                if question.trap_rubric is not None
                and question.trap_rubric.human_spot_check
            ],
        },
        "episodes": episodes,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / BENCHMARK_REPORT_FILENAME
    staging_path = output_dir / f".{BENCHMARK_REPORT_FILENAME}.tmp"
    staging_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    staging_path.replace(artifact_path)
    return report


def _episode_totals(episodes: list[dict[str, object]]) -> dict[str, int]:
    passed = sum(
        bool(episode["grade"]["passed"])  # type: ignore[index]
        for episode in episodes
    )
    return {
        "questions": len(episodes),
        "passed": passed,
        "failed": len(episodes) - passed,
    }


def _run_episode(
    *,
    question: BenchmarkQuestion,
    arm: ArmAdapter,
    trap_judge: TrapJudge | None,
) -> dict[str, object]:
    graph_facts = _load_graph_facts(question.drawing_ref)

    started = time.perf_counter()
    answer = arm.answer(question=question, drawing_ref=question.drawing_ref)
    wall_time_seconds = time.perf_counter() - started

    trap_judgment = (
        trap_judge.judge(
            question=question,
            answer=answer,
            rubric=question.trap_rubric,
        )
        if question.trap_rubric is not None and trap_judge is not None
        else None
    )

    episode_grade = grade(
        answer=answer,
        ground_truth=question.ground_truth,
        graph_facts=graph_facts,
        trap_rubric=question.trap_rubric,
        trap_judgment=trap_judgment,
    )
    return {
        "question_id": question.question_id,
        "question": question.question,
        "slice": question.slice,
        "category": question.category,
        "size_bucket": question.size_bucket,
        "drawing_ref": str(question.drawing_ref),
        "gating": question.slice != SLICE_TRAP,
        "human_spot_check_required": bool(
            question.trap_rubric and question.trap_rubric.human_spot_check
        ),
        "answer": {
            "verdict": answer.verdict,
            "witness_ids": list(answer.witness_ids),
            "posture": answer.posture,
            "answer_text": answer.answer_text,
            "support": answer.support,
        },
        "expected": _ground_truth_payload(question.ground_truth),
        "trap_rubric": (
            {
                "expected_posture": question.trap_rubric.expected_posture,
                "refusal_basis": question.trap_rubric.refusal_basis,
                "redirect_target": question.trap_rubric.redirect_target,
            }
            if question.trap_rubric is not None
            else None
        ),
        "grade": _grade_payload(episode_grade),
        "wall_time_seconds": wall_time_seconds,
        "tokens": _tokens_payload(answer.usage),
        "cost_usd": answer.usage.get("cost_usd"),
        "usage": dict(answer.usage),
        "transcript": [dict(message) for message in answer.transcript],
    }


def _tokens_payload(usage: Mapping[str, object]) -> dict[str, object]:
    """Explicit per-episode token accounting from arm-reported usage."""
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total = input_tokens + output_tokens
    else:
        total = usage.get("total_tokens")
    return {"input": input_tokens, "output": output_tokens, "total": total}


def _ground_truth_payload(ground_truth: GroundTruth) -> dict[str, object]:
    return {
        "verdict": ground_truth.verdict,
        "witness_ids": list(ground_truth.witness_ids),
    }


def _grade_payload(episode_grade: Grade) -> dict[str, object]:
    return {
        "passed": episode_grade.passed,
        "verdict_match": episode_grade.verdict_match,
        "witness_match": episode_grade.witness_match,
        "posture_consistent": episode_grade.posture_consistent,
        "witness_precision": episode_grade.witness_precision,
        "witness_recall": episode_grade.witness_recall,
        "witness_f1": episode_grade.witness_f1,
        "grounded_answer_credit": episode_grade.grounded_answer_credit,
        "missing_witness_ids": list(episode_grade.missing_witness_ids),
        "extra_witness_ids": list(episode_grade.extra_witness_ids),
        "unknown_witness_ids": list(episode_grade.unknown_witness_ids),
        "trap_rubric_passed": episode_grade.trap_rubric_passed,
        "grounded_refusal": episode_grade.grounded_refusal,
        "graceful_redirect": episode_grade.graceful_redirect,
        "judge_rationale": episode_grade.judge_rationale,
    }


def _load_graph_facts(drawing_ref: Path) -> dict[str, object]:
    graph_facts_path = (
        drawing_ref / "graph_facts.json" if drawing_ref.is_dir() else drawing_ref
    )
    return json.loads(graph_facts_path.read_text(encoding="utf-8"))


def load_scripted_answers(path: Path) -> dict[str, StructuredAnswer]:
    """Load a scripted-answers JSON file: question ID -> StructuredAnswer."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Scripted answers at {path} must be a JSON object.")
    answers: dict[str, StructuredAnswer] = {}
    for question_id, raw_answer in raw.items():
        context = f"Scripted answer for {question_id!r}"
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("Scripted answer question IDs must be non-empty strings.")
        if not isinstance(raw_answer, dict):
            raise ValueError(f"{context} must be a JSON object.")
        verdict = raw_answer.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError(f"{context} has invalid verdict {verdict!r}.")
        witness_ids = raw_answer.get("witness_ids", [])
        if not isinstance(witness_ids, list) or not all(
            isinstance(witness_id, str) for witness_id in witness_ids
        ):
            raise ValueError(f"{context}.witness_ids must be a list of strings.")
        posture = raw_answer.get("posture", "unspecified")
        if posture not in POSTURES:
            raise ValueError(f"{context} has invalid posture {posture!r}.")
        answer_text = raw_answer.get("answer_text", "")
        if not isinstance(answer_text, str):
            raise ValueError(f"{context}.answer_text must be a string.")
        if posture in TRAP_EXPECTED_POSTURES and not answer_text.strip():
            raise ValueError(
                f"{context}.answer_text must be non-empty for posture {posture!r}."
            )
        transcript = raw_answer.get("transcript", [])
        if not isinstance(transcript, list) or not all(
            isinstance(message, dict) for message in transcript
        ):
            raise ValueError(f"{context}.transcript must be a list of objects.")
        usage = raw_answer.get("usage", {})
        if not isinstance(usage, dict):
            raise ValueError(f"{context}.usage must be an object.")
        support = raw_answer.get("support", {})
        if not isinstance(support, dict):
            raise ValueError(f"{context}.support must be an object.")
        answers[question_id] = StructuredAnswer(
            verdict=verdict,
            witness_ids=tuple(witness_ids),
            posture=posture,
            answer_text=answer_text,
            transcript=tuple(transcript),
            usage=dict(usage),
            support=dict(support),
        )
    return answers


def _scripted_trap_judge(
    *,
    trap_question_ids: set[str],
    judgments_path: Path | None,
) -> TrapJudge | None:
    if judgments_path is None:
        if not trap_question_ids:
            return None
        raise ValueError(
            "Trap questions require --scripted-trap-judgments before any "
            "benchmark episodes can run."
        )
    judgments = load_scripted_trap_judgments(judgments_path)
    if not trap_question_ids:
        return None
    missing = sorted(trap_question_ids - judgments.keys())
    if missing:
        raise ValueError(
            "Scripted trap judgments are missing question IDs: " + ", ".join(missing)
        )
    return ScriptedTrapJudge(judgments)


def run_scripted_benchmark(
    *,
    manifest_path: Path,
    scripted_answers_path: Path,
    arm_id: str,
    output_dir: Path,
    scripted_trap_judgments_path: Path | None = None,
) -> int:
    """CLI entry: validate all scripted inputs, then run one report."""
    dataset = load_question_manifest(manifest_path)
    answers = load_scripted_answers(scripted_answers_path)
    question_ids = {question.question_id for question in dataset.questions}
    missing_answers = sorted(question_ids - answers.keys())
    if missing_answers:
        raise ValueError(
            "Scripted answers are missing question IDs: " + ", ".join(missing_answers)
        )
    trap_judge = _scripted_trap_judge(
        trap_question_ids={
            question.question_id
            for question in dataset.questions
            if question.slice == SLICE_TRAP
        },
        judgments_path=scripted_trap_judgments_path,
    )
    arm = ScriptedArm(arm_id=arm_id, answers=answers)
    report = run_benchmark(
        manifest_path=manifest_path,
        arm=arm,
        output_dir=output_dir,
        trap_judge=trap_judge,
    )
    totals = report["totals"]
    print(f"Benchmark report: {output_dir / BENCHMARK_REPORT_FILENAME}")
    print(
        f"Arm: {report['arm_id']} | questions: {totals['questions']} | "  # type: ignore[index]
        f"passed: {totals['passed']} | failed: {totals['failed']}"  # type: ignore[index]
    )
    return 0
