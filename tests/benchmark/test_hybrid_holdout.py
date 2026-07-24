"""Behavior tests for the hybrid product holdout (bead 3qo.9.10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    SOURCE_CONCLUSION_VERDICTS,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.dataset import load_question_manifest
from pydexpi_datalog.benchmark.hybrid_holdout import (
    FROZEN_V3_DEVELOPMENT_IDS,
    HYBRID_HOLDOUT_REQUIRED_CASE_TAGS,
    HybridHoldoutError,
    build_hybrid_holdout_report,
    materialize_hybrid_holdout_manifest,
    run_hybrid_holdout,
)
from pydexpi_datalog.benchmark.runner import ScriptedArm


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "testdata" / "benchmark" / "hybrid_holdout_lock.json"

EXPECTED_IDS = [
    "ha-e04-exchanger-h1009-retrieval",
    "ha-c01-centrifugal-pumps-retrieval",
    "ha-e05-nozzles-retrieval",
    "ha-e12-chambers-retrieval",
    "ha-e06-segment-source-compliance",
    "ha-i03-piping-systems-retrieval",
    "hq-instrumentation-actuation-closure-small",
    "hq-instrumentation-actuation-closure-large",
    "ha-e03-pump-nozzles-compliance",
    "ha-i04-function-ownership-compliance",
]


def test_holdout_lock_is_unseen_relative_to_frozen_v3_matrix() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in lock["entries"]]
    assert ids == EXPECTED_IDS
    assert set(ids).isdisjoint(FROZEN_V3_DEVELOPMENT_IDS)
    assert set(lock["excluded_development_matrix_ids"]) == FROZEN_V3_DEVELOPMENT_IDS


def test_materializes_certified_holdout_with_required_case_tags(tmp_path: Path) -> None:
    manifest_path = materialize_hybrid_holdout_manifest(
        LOCK_PATH, tmp_path / "hybrid_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = load_question_manifest(manifest_path)

    assert [q.question_id for q in dataset.questions] == EXPECTED_IDS
    assert manifest["hybrid_holdout_lock"]["protocol_bead"] == "pydexpi-datalog-1-3qo.9.10"
    assert manifest["hybrid_holdout_lock"]["certification"]["status"] == (
        "product_owner_sme_approved"
    )
    covered = {
        tag
        for entry in manifest["hybrid_holdout_lock"]["entries"]
        for tag in entry["case_tags"]
    }
    assert HYBRID_HOLDOUT_REQUIRED_CASE_TAGS <= covered


def test_rejects_lock_that_reuses_development_matrix_id(tmp_path: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock["entries"][0]["id"] = "ha-e03-pump-p4713-retrieval"
    lock["entries"][0]["source"] = "hand_authored"
    bad = tmp_path / "bad-lock.json"
    # Rewrite source paths absolute so relocate isn't needed after path rewrite
    for source in lock["sources"]:
        source["path"] = str(LOCK_PATH.parent / source["path"])
    protocol = lock["protocol"]
    protocol["document"] = str(LOCK_PATH.parent / protocol["document"])
    bad.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(HybridHoldoutError, match="development matrix"):
        materialize_hybrid_holdout_manifest(bad, tmp_path / "manifest.json")


def test_scripted_holdout_report_is_fail_closed_without_generalization_claim(
    tmp_path: Path,
) -> None:
    """Perfect scripted grades still require the gate; claim stays false until
    the locked credit threshold and artifact contract pass together."""
    manifest_path = materialize_hybrid_holdout_manifest(
        LOCK_PATH, tmp_path / "hybrid_manifest.json"
    )
    dataset = load_question_manifest(manifest_path)
    answers = {
        question.question_id: StructuredAnswer(
            verdict=question.ground_truth.verdict,
            witness_ids=question.ground_truth.witness_ids,
            posture=(
                POSTURE_SOURCE_GROUNDED
                if question.ground_truth.verdict in SOURCE_CONCLUSION_VERDICTS
                else POSTURE_SOURCE_DATA_UNAVAILABLE
            ),
            usage={"cost_usd": 0.01, "prompt_tokens": 10, "completion_tokens": 5},
        )
        for question in dataset.questions
    }

    report = run_hybrid_holdout(
        lock_path=LOCK_PATH,
        arm=ScriptedArm(arm_id="hybrid-holdout-scripted", answers=answers),
        output_dir=tmp_path / "report",
        manifest_output_path=manifest_path,
    )

    metrics = report["metrics"]
    assert metrics["grounded_credit"] == 10
    assert metrics["questions"] == 10
    assert metrics["grounded_credit_rate"] == 1.0
    assert metrics["cost_per_grounded_credit"] == pytest.approx(0.01)
    assert metrics["template_coverage_excluding_policy_abstentions"] is not None
    assert report["gate"]["passed"] is True
    assert report["gate"]["production_generalization_claim_allowed"] is False
    assert "deontic_abstention" in report["gate"]["deferred_case_tags"]


def test_gate_fails_when_grounded_credit_below_threshold(tmp_path: Path) -> None:
    manifest_path = materialize_hybrid_holdout_manifest(
        LOCK_PATH, tmp_path / "hybrid_manifest.json"
    )
    dataset = load_question_manifest(manifest_path)
    answers = {
        question.question_id: StructuredAnswer(
            verdict="unanswerable",
            witness_ids=(),
            posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
            usage={"cost_usd": 0.0},
        )
        for question in dataset.questions
    }
    benchmark_report = {
        "arm_id": "failing",
        "episodes": [
            {
                "question_id": q.question_id,
                "gating": True,
                "grade": {"passed": False, "grounded_answer_credit": 0.0},
                "answer": {"verdict": "unanswerable"},
                "usage": {"cost_usd": 0.0},
                "cost_usd": 0.0,
                "wall_time_seconds": 0.1,
                "transcript": [],
            }
            for q in dataset.questions
        ],
        "totals": {"questions": 10, "passed": 0, "failed": 10},
    }
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    holdout_report = build_hybrid_holdout_report(
        lock=lock,
        manifest_path=manifest_path,
        benchmark_report=benchmark_report,
    )
    assert holdout_report["gate"]["passed"] is False
    assert holdout_report["gate"]["production_generalization_claim_allowed"] is False
