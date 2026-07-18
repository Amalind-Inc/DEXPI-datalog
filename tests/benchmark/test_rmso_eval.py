"""Behavior tests for the preregistered RMSO evaluation-slice lock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets, load_episode_budgets
from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    SOURCE_CONCLUSION_VERDICTS,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.dataset import load_question_manifest
from pydexpi_datalog.benchmark.rmso_eval import (
    RMSOEvalLockError,
    materialize_preregistered_rmso_manifest,
)
from pydexpi_datalog.benchmark.runner import ScriptedArm, run_benchmark


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "testdata" / "benchmark" / "rmso_eval_lock.json"
REDESIGNED_LOCK_PATH = (
    REPO_ROOT / "testdata" / "benchmark" / "rmso_eval_lock_v2.json"
)
EXPECTED_IDS = [
    "ha-e03-pump-p4713-retrieval",
    "hq-nozzle-piping-attachment-small",
    "hq-nozzle-piping-attachment-large",
    "hq-valve-monitoring-reachability-small",
    "hq-valve-monitoring-reachability-large",
    "hq-equipment-pump-connectivity-small",
    "hq-equipment-pump-connectivity-large",
    "hq-permission-defeasible-control-small",
    "hq-permission-defeasible-control-large",
]


def relocate_lock_references(lock: dict[str, object]) -> None:
    protocol = lock["protocol"]
    assert isinstance(protocol, dict)
    protocol["document"] = str(LOCK_PATH.parent / protocol["document"])
    sources = lock["sources"]
    assert isinstance(sources, list)
    for source in sources:
        assert isinstance(source, dict)
        source["path"] = str(LOCK_PATH.parent / source["path"])


def test_materializes_exact_certified_nine_entry_slice_without_copying_truth(
    tmp_path: Path,
) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert all("ground_truth" not in entry for entry in lock["entries"])

    manifest_path = materialize_preregistered_rmso_manifest(
        LOCK_PATH, tmp_path / "rmso_manifest.json"
    )

    dataset = load_question_manifest(manifest_path)
    assert [question.question_id for question in dataset.questions] == EXPECTED_IDS
    assert [question.ground_truth.verdict for question in dataset.questions] == [
        "violation_found",
        "violation_found",
        "violation_found",
        "no_violation",
        "violation_found",
        "no_violation",
        "no_violation",
        "unanswerable",
        "unanswerable",
    ]
    assert [len(question.ground_truth.witness_ids) for question in dataset.questions] == [
        1,
        4,
        3,
        0,
        8,
        0,
        0,
        0,
        0,
    ]
    assert load_episode_budgets(manifest_path) == EpisodeBudgets(
        max_turns=64,
        max_commands=128,
        max_output_tokens=8192,
        agent_timeout_sec=300.0,
        verifier_timeout_sec=60.0,
    )


def test_materializes_locked_redesigned_protocol_with_accounting_contract(
    tmp_path: Path,
) -> None:
    manifest_path = materialize_preregistered_rmso_manifest(
        REDESIGNED_LOCK_PATH, tmp_path / "rmso_manifest.json"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["rmso_lock"]["schema_version"] == 2
    assert (
        manifest["rmso_lock"]["design_revision"]
        == "graph-direct-vs-souffle-v2"
    )
    assert manifest["rmso_lock"]["protocol_bead"] == "pydexpi-datalog-1-rmso.1"
    assert manifest["rmso_lock"]["accounting_contract"] == {
        "provider_ledger": "required",
        "unknown_cost": "run_incomplete",
        "policy_violation": "run_incomplete",
    }
    assert [question["id"] for question in manifest["questions"]] == EXPECTED_IDS


def test_rejects_changed_source_manifest_before_materializing(tmp_path: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    source = LOCK_PATH.parent / lock["sources"][0]["path"]
    relocate_lock_references(lock)
    changed_source = tmp_path / source.name
    changed_source.write_bytes(source.read_bytes() + b"\n")
    lock["sources"][0]["path"] = changed_source.name
    changed_lock = tmp_path / "changed-lock.json"
    changed_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(RMSOEvalLockError, match="SHA-256"):
        materialize_preregistered_rmso_manifest(
            changed_lock, tmp_path / "manifest.json"
        )


def test_rejects_lock_without_product_owner_sme_certification(tmp_path: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    relocate_lock_references(lock)
    lock["certification"]["status"] = "pending"
    changed_lock = tmp_path / "uncertified-lock.json"
    changed_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(RMSOEvalLockError, match="SME certification"):
        materialize_preregistered_rmso_manifest(
            changed_lock, tmp_path / "manifest.json"
        )


def test_materialized_slice_runs_through_scripted_benchmark_plumbing(
    tmp_path: Path,
) -> None:
    manifest_path = materialize_preregistered_rmso_manifest(
        LOCK_PATH, tmp_path / "rmso_manifest.json"
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
        )
        for question in dataset.questions
    }

    report = run_benchmark(
        manifest_path=manifest_path,
        arm=ScriptedArm(arm_id="rmso-manifest-plumbing-dry-run", answers=answers),
        output_dir=tmp_path / "report",
    )

    assert report["totals"] == {"questions": 9, "passed": 9, "failed": 0}
    assert [episode["question_id"] for episode in report["episodes"]] == EXPECTED_IDS
