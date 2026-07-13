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
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from pydexpi_datalog.benchmark.contract import GroundTruth, StructuredAnswer
from pydexpi_datalog.benchmark.dataset import (
    BenchmarkQuestion,
    load_question_manifest,
)
from pydexpi_datalog.benchmark.grader import Grade, grade

BENCHMARK_REPORT_SCHEMA_VERSION = 1
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
    *, manifest_path: Path, arm: ArmAdapter, output_dir: Path
) -> dict[str, object]:
    """Run every manifest question through one arm and persist the report.

    The report artifact (``benchmark_report.json``) carries per-episode
    grade, usage (tokens/cost as reported by the arm), wall time, and the
    full transcript.  It is written only after every episode completes, so
    a failing arm never leaves a partial artifact behind.
    """
    dataset = load_question_manifest(manifest_path)

    episodes: list[dict[str, object]] = []
    passed = 0
    for question in dataset.questions:
        episode = _run_episode(question=question, arm=arm)
        if episode["grade"]["passed"]:  # type: ignore[index]
            passed += 1
        episodes.append(episode)

    report: dict[str, object] = {
        "schema_version": BENCHMARK_REPORT_SCHEMA_VERSION,
        "manifest_path": str(manifest_path.resolve()),
        "arm_id": arm.arm_id,
        "totals": {
            "questions": len(episodes),
            "passed": passed,
            "failed": len(episodes) - passed,
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


def _run_episode(
    *, question: BenchmarkQuestion, arm: ArmAdapter
) -> dict[str, object]:
    graph_facts = _load_graph_facts(question.drawing_ref)

    started = time.perf_counter()
    answer = arm.answer(question=question, drawing_ref=question.drawing_ref)
    wall_time_seconds = time.perf_counter() - started

    episode_grade = grade(
        answer=answer,
        ground_truth=question.ground_truth,
        graph_facts=graph_facts,
    )
    return {
        "question_id": question.question_id,
        "question": question.question,
        "slice": question.slice,
        "drawing_ref": str(question.drawing_ref),
        "answer": {
            "verdict": answer.verdict,
            "witness_ids": list(answer.witness_ids),
            "posture": answer.posture,
        },
        "expected": _ground_truth_payload(question.ground_truth),
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
        "missing_witness_ids": list(episode_grade.missing_witness_ids),
        "extra_witness_ids": list(episode_grade.extra_witness_ids),
        "unknown_witness_ids": list(episode_grade.unknown_witness_ids),
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
        if not isinstance(raw_answer, dict) or not isinstance(
            raw_answer.get("verdict"), str
        ):
            raise ValueError(
                f"Scripted answer for {question_id!r} must be an object with a "
                "string verdict."
            )
        answers[question_id] = StructuredAnswer(
            verdict=raw_answer["verdict"],
            witness_ids=tuple(raw_answer.get("witness_ids", ())),
            posture=raw_answer.get("posture", "unspecified"),
            transcript=tuple(raw_answer.get("transcript", ())),
            usage=dict(raw_answer.get("usage", {})),
        )
    return answers


def run_scripted_benchmark(
    *,
    manifest_path: Path,
    scripted_answers_path: Path,
    arm_id: str,
    output_dir: Path,
) -> int:
    """CLI entry: one command from manifest + scripted answers to report."""
    arm = ScriptedArm(
        arm_id=arm_id,
        answers=load_scripted_answers(scripted_answers_path),
    )
    report = run_benchmark(
        manifest_path=manifest_path, arm=arm, output_dir=output_dir
    )
    totals = report["totals"]
    print(f"Benchmark report: {output_dir / BENCHMARK_REPORT_FILENAME}")
    print(
        f"Arm: {report['arm_id']} | questions: {totals['questions']} | "  # type: ignore[index]
        f"passed: {totals['passed']} | failed: {totals['failed']}"  # type: ignore[index]
    )
    return 0
