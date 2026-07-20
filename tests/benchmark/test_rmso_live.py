from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pydexpi_datalog.benchmark import GroundTruth
from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets, EpisodeResult
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.rmso_live import (
    apply_episode_cost_accounting,
    create_rmso_live_arms,
    finalize_rmso_accounting,
    run_rmso_live,
    validate_redesigned_live_manifest,
)
from pydexpi_datalog.benchmark.rmso_kira import (
    CHECKPOINT_FIELD,
    CHECKPOINT_VALUE,
    _accepted_checkpoint,
)
from pydexpi_datalog.benchmark.rmso_eval import (
    materialize_preregistered_rmso_manifest,
)
from pydexpi_datalog.benchmark.souffle_arm import build_rmso_souffle_harbor_task


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_BUNDLE = (
    REPO_ROOT
    / "testdata"
    / "graph_contract"
    / "corpus"
    / "e06-pump-heatexchanger-nozzles-connected-with-pns-e06v01-ver-ex01"
)
LOCK_PATH = REPO_ROOT / "testdata" / "benchmark" / "rmso_eval_lock.json"
REDESIGNED_LOCK_PATH = (
    REPO_ROOT / "testdata" / "benchmark" / "rmso_eval_lock_v2.json"
)


def test_creates_exact_two_locked_deepseek_arms_with_one_gateway(
    tmp_path: Path,
) -> None:
    gateway = object()
    arms = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=gateway,  # type: ignore[arg-type]
    )

    assert [arm.arm_id for arm in arms] == [
        "a-agentic:deepseek",
        "c-souffle:deepseek",
    ]
    assert all(arm.runner.request_gateway is gateway for arm in arms)
    assert [arm.runner.accounting_arm_id for arm in arms] == [
        "a-agentic:deepseek",
        "c-souffle:deepseek",
    ]
    assert [arm.artifact_root for arm in arms] == [
        tmp_path / "run" / "arm-a" / "harbor",
        tmp_path / "run" / "arm-c" / "harbor",
    ]
    assert arms[1].task_builder is build_rmso_souffle_harbor_task


def test_rmso_arm_a_receives_graph_facts_and_compact_index_not_raw_xml(
    tmp_path: Path,
) -> None:
    arm_a, _ = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )
    question = BenchmarkQuestion(
        question_id="graph-direct-q1",
        question="Find every unattached nozzle.",
        slice="hand_authored",
        drawing_ref=E06_BUNDLE,
        ground_truth=GroundTruth(verdict="violation_found", witness_ids=()),
    )

    task_dir = arm_a.task_builder(
        question=question,
        drawing_ref=E06_BUNDLE,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(),
    )

    environment = task_dir / "environment"
    assert (environment / "graph_facts.json").is_file()
    assert (environment / "graph_inspection.json").is_file()
    assert (environment / "run_analysis.py").is_file()
    assert not (environment / "drawing.xml").exists()
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "/input/graph_facts.json" in instruction
    assert "/input/graph_inspection.json" in instruction
    assert "standard-library Python" in instruction
    assert "python3 /input/run_analysis.py /workspace/analysis.py" in instruction
    assert "souffle" not in instruction.lower()


def test_rmso_arm_a_helper_replays_analysis_and_writes_provisional_answer(
    tmp_path: Path,
) -> None:
    arm_a, _ = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )
    question = BenchmarkQuestion(
        question_id="graph-direct-helper-q1",
        question="Find one graph node.",
        slice="hand_authored",
        drawing_ref=E06_BUNDLE,
        ground_truth=GroundTruth(verdict="violation_found", witness_ids=()),
    )
    task_dir = arm_a.task_builder(
        question=question,
        drawing_ref=E06_BUNDLE,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(),
    )
    environment = task_dir / "environment"
    witness = json.loads(
        (environment / "graph_inspection.json").read_text(encoding="utf-8")
    )["nodes"][0]["id"]
    analysis = tmp_path / "analysis.py"
    analysis.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'verdict': 'violation_found', 'witness_ids': [{witness!r}]}}))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(environment / "run_analysis.py"), str(analysis)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    replay_line, receipt_line = completed.stdout.splitlines()
    assert json.loads(replay_line)["witness_ids"] == [witness]
    assert json.loads(receipt_line) == {"ok": True, CHECKPOINT_FIELD: CHECKPOINT_VALUE}
    assert json.loads((tmp_path / "analysis_replay.json").read_text()) == {
        "verdict": "violation_found",
        "witness_ids": [witness],
    }
    checkpoint = json.loads((tmp_path / "structured_answer.json").read_text())
    assert checkpoint["verdict"] == "violation_found"
    assert checkpoint["witness_ids"] == [witness]
    assert checkpoint["support"]["steps"][1]["kind"] == "python_execution"

    analysis.write_text("raise RuntimeError('later revision failed')\n", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(environment / "run_analysis.py"), str(analysis)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode != 0
    assert json.loads((tmp_path / "structured_answer.json").read_text()) == checkpoint


def test_rmso_arm_a_helper_emits_wrap_proof_checkpoint_receipt(
    tmp_path: Path,
) -> None:
    """The Arm A helper's mechanical receipt must survive a fixed-width pane
    even when the witness listing wraps."""
    arm_a, _ = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )
    question = BenchmarkQuestion(
        question_id="graph-direct-receipt-q1",
        question="Find every graph node.",
        slice="hand_authored",
        drawing_ref=E06_BUNDLE,
        ground_truth=GroundTruth(verdict="violation_found", witness_ids=()),
    )
    task_dir = arm_a.task_builder(
        question=question,
        drawing_ref=E06_BUNDLE,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(),
    )
    environment = task_dir / "environment"
    witnesses = [
        node["id"]
        for node in json.loads(
            (environment / "graph_inspection.json").read_text(encoding="utf-8")
        )["nodes"]
    ]
    assert sum(len(witness) + 4 for witness in witnesses) > 80, (
        "fixture must supply enough witness IDs to force terminal wrapping"
    )
    analysis = tmp_path / "analysis.py"
    analysis.write_text(
        "import json\n"
        f"print(json.dumps({{'verdict': 'violation_found', 'witness_ids': {witnesses!r}}}))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(environment / "run_analysis.py"), str(analysis)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    replay_line, receipt_line = completed.stdout.splitlines()
    assert json.loads(replay_line)["witness_ids"] == witnesses
    assert json.loads(receipt_line) == {"ok": True, CHECKPOINT_FIELD: CHECKPOINT_VALUE}
    # The mechanical receipt must never wrap at ordinary terminal widths.
    assert len(receipt_line) <= 60

    # Hard-fold every physical line like a fixed-width terminal pane; the
    # checkpoint parser must still find the receipt.
    pane_width = 80
    assert any(len(line) > pane_width for line in completed.stdout.splitlines())
    wrapped = "\n".join(
        line[start : start + pane_width]
        for line in completed.stdout.splitlines()
        for start in range(0, max(len(line), 1), pane_width)
    )
    assert _accepted_checkpoint(wrapped)


def test_rmso_arm_a_uses_checkpoint_adapter_with_analysis_preflight(
    tmp_path: Path,
) -> None:
    """Arm A must get the same checkpoint auto-completion lifecycle as Arm C."""
    budgets = EpisodeBudgets(agent_timeout_sec=300.0)
    arm_a, _ = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=budgets,
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )

    assert arm_a.runner.agent_import_path == "rmso_kira:CheckpointTerminusKira"
    assert str(REPO_ROOT / "pydexpi_datalog" / "benchmark") in arm_a.runner.environ[
        "PYTHONPATH"
    ].split(os.pathsep)
    assert arm_a.runner.agent_kwargs == {
        "checkpoint_cutoff_sec": 240.0,
        "checkpoint_preflight_command": (
            "python3 /input/run_analysis.py /workspace/analysis.py"
        ),
    }


def test_rmso_arm_a_replays_graph_analysis_and_credits_graph_trace(
    tmp_path: Path,
) -> None:
    graph = json.loads((E06_BUNDLE / "graph_facts.json").read_text())
    witness = graph["facts"]["nodes"][0]["node_id"]
    replay = {"verdict": "violation_found", "witness_ids": [witness]}
    answer = {
        **replay,
        "posture": "source_grounded",
        "support": {
            "steps": [
                {
                    "id": "scope",
                    "kind": "graph_scope",
                    "node_count": len(graph["facts"]["nodes"]),
                    "edge_count": len(graph["facts"]["edges"]),
                    "dependencies": [],
                },
                {
                    "id": "execution",
                    "kind": "python_execution",
                    "artifact": "analysis.py",
                    "input": "graph_facts.json",
                    "output": "analysis_replay.json",
                    **replay,
                    "dependencies": ["scope"],
                },
            ],
            "claims": [
                {"claim": "verdict", "step_ids": ["execution"]},
                {"claim": f"witness:{witness}", "step_ids": ["execution"]},
            ],
        },
    }

    class ScriptedRunner:
        def run(self, *, task_dir, jobs_dir, budgets):
            return EpisodeResult(
                structured_answer_text=json.dumps(answer),
                reward=1.0,
                analysis_script="import json; print(json.dumps({}))",
                analysis_replay_text=json.dumps(replay),
            )

    arm_a, _ = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )
    arm_a = replace(arm_a, runner=ScriptedRunner())
    question = BenchmarkQuestion(
        question_id="graph-direct-q1",
        question="Find the first graph node.",
        slice="hand_authored",
        drawing_ref=E06_BUNDLE,
        ground_truth=GroundTruth(
            verdict="violation_found", witness_ids=(str(witness),)
        ),
    )

    result = arm_a.answer(question=question, drawing_ref=E06_BUNDLE)

    assert result.verdict == "violation_found"
    assert result.witness_ids == (witness,)
    assert result.usage["audit_trace"]["trace_safe"] is True


def test_rmso_arms_receive_identical_answer_neutral_graph_index(
    tmp_path: Path,
) -> None:
    arm_a, arm_c = create_rmso_live_arms(
        kira_dir=tmp_path / "kira",
        output_dir=tmp_path / "run",
        budgets=EpisodeBudgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
        request_gateway=object(),  # type: ignore[arg-type]
    )
    question = BenchmarkQuestion(
        question_id="graph-index-q1",
        question="Inspect the graph.",
        slice="hand_authored",
        drawing_ref=E06_BUNDLE,
        ground_truth=GroundTruth(verdict="no_violation", witness_ids=()),
    )
    tasks = [
        arm.task_builder(
            question=question,
            drawing_ref=E06_BUNDLE,
            output_dir=tmp_path / f"tasks-{index}",
            budgets=EpisodeBudgets(),
        )
        for index, arm in enumerate((arm_a, arm_c))
    ]

    indexes = [
        (task / "environment" / "graph_inspection.json").read_bytes()
        for task in tasks
    ]
    assert indexes[0] == indexes[1]
    index = json.loads(indexes[0])
    graph = json.loads((E06_BUNDLE / "graph_facts.json").read_text())
    assert index["node_count"] == len(graph["facts"]["nodes"])
    assert index["edge_count"] == len(graph["facts"]["edges"])
    assert {node["id"] for node in index["nodes"]} == {
        node["node_id"] for node in graph["facts"]["nodes"]
    }


def test_refuses_to_replace_any_existing_live_run_artifact(tmp_path: Path) -> None:
    kira_dir = tmp_path / "kira"
    kira_dir.mkdir()
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    (output_dir / "partial-paid-response.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing replacement run"):
        run_rmso_live(
            lock_path=tmp_path / "unused-lock.json",
            output_dir=output_dir,
            kira_dir=kira_dir,
            environ={"OPENROUTER_API_KEY": "test-key"},
        )


def test_provider_ledger_populates_episode_and_arm_costs() -> None:
    class Ledger:
        def episode_accounting(self, *, arm_id, question_id):
            assert arm_id == "a-agentic:deepseek"
            return {
                "q1": {
                    "accounting_complete": True,
                    "call_numbers": [1, 2],
                    "cost_usd": 0.003,
                    "known_cost_usd": 0.003,
                    "policy_violation_call_numbers": [],
                },
                "q2": {
                    "accounting_complete": False,
                    "call_numbers": [3],
                    "cost_usd": None,
                    "known_cost_usd": 0.0,
                    "policy_violation_call_numbers": [],
                },
            }[question_id]

    report = {
        "arm_id": "a-agentic:deepseek",
        "episodes": [
            {"question_id": "q1", "usage": {}, "cost_usd": None},
            {"question_id": "q2", "usage": {}, "cost_usd": None},
        ],
    }

    accounting = apply_episode_cost_accounting(report, Ledger())  # type: ignore[arg-type]

    assert report["episodes"][0]["cost_usd"] == 0.003
    assert report["episodes"][1]["cost_usd"] is None
    assert report["episodes"][0]["usage"]["provider_accounting"][  # type: ignore[index]
        "call_numbers"
    ] == [1, 2]
    assert accounting == {
        "accounting_complete": False,
        "cost_usd": None,
        "episodes": 2,
        "episodes_with_complete_accounting": 1,
        "known_cost_usd": 0.003,
        "policy_violation_call_numbers": [],
    }
    assert report["provider_accounting"] == accounting


@pytest.mark.parametrize(
    ("snapshot", "expected_reasons"),
    [
        (
            {
                "actual_spend_usd": 0.2,
                "active_reservations_usd": 0.0,
                "accounting_complete": False,
                "attribution_complete": True,
                "unattributed_attempts": 0,
                "unknown_cost_calls": [7],
                "policy_violations": [],
            },
            ["unknown_provider_cost"],
        ),
        (
            {
                "actual_spend_usd": 0.2,
                "active_reservations_usd": 0.0,
                "accounting_complete": True,
                "attribution_complete": True,
                "unattributed_attempts": 0,
                "unknown_cost_calls": [],
                "policy_violations": [
                    {"call_number": 8, "reason": "output ceiling"}
                ],
            },
            ["provider_policy_violation"],
        ),
        (
            {
                "actual_spend_usd": 0.0,
                "active_reservations_usd": 0.0,
                "accounting_complete": True,
                "attribution_complete": False,
                "unattributed_attempts": 1,
                "unknown_cost_calls": [],
                "policy_violations": [],
            },
            ["missing_call_attribution"],
        ),
        (
            {
                "actual_spend_usd": 9.9,
                "active_reservations_usd": 0.0,
                "accounting_complete": True,
                "attribution_complete": True,
                "unattributed_attempts": 0,
                "spend_cap_complete": False,
                "spend_cap_blocked_attempts": 1,
                "unknown_cost_calls": [],
                "policy_violations": [],
            },
            ["spend_cap_exhausted"],
        ),
    ],
)
def test_run_summary_is_formally_incomplete_for_accounting_or_policy_failure(
    snapshot: dict[str, object], expected_reasons: list[str]
) -> None:
    class Gateway:
        def accounting_snapshot(self):
            return snapshot

    summary = {"status": "running"}

    finalize_rmso_accounting(summary, Gateway())  # type: ignore[arg-type]

    assert summary["status"] == "invalid"
    assert summary["formal_status"] == "INCOMPLETE"
    assert summary["invalid_reasons"] == expected_reasons
    assert summary["actual_spend_usd"] == snapshot["actual_spend_usd"]


def test_live_executor_persists_provider_ledger_costs_and_complete_status(
    tmp_path: Path, monkeypatch
) -> None:
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            pass

    class Gateway:
        def __init__(self, **kwargs):
            self.actual_spend = 0.02

        def episode_accounting(self, *, arm_id, question_id):
            return {
                "accounting_complete": True,
                "call_numbers": [1],
                "cost_usd": 0.01,
                "known_cost_usd": 0.01,
                "policy_violation_call_numbers": [],
            }

        def accounting_snapshot(self):
            return {
                "actual_spend_usd": 0.02,
                "active_reservations_usd": 0.0,
                "accounting_complete": True,
                "attribution_complete": True,
                "unattributed_attempts": 0,
                "unknown_cost_calls": [],
                "policy_violations": [],
            }

    def scripted_run(*, manifest_path, arm, output_dir, episode_workers):
        return {
            "arm_id": arm.arm_id,
            "totals": {"questions": 1, "passed": 1, "failed": 0},
            "episodes": [
                {"question_id": "q1", "usage": {}, "cost_usd": None}
            ],
        }

    monkeypatch.setattr("pydexpi_datalog.benchmark.rmso_live.httpx.Client", Client)
    monkeypatch.setattr(
        "pydexpi_datalog.benchmark.rmso_live.LockedOpenRouterGateway", Gateway
    )
    monkeypatch.setattr(
        "pydexpi_datalog.benchmark.rmso_live.run_benchmark", scripted_run
    )
    kira_dir = tmp_path / "kira"
    kira_dir.mkdir()
    output_dir = tmp_path / "run"

    summary = run_rmso_live(
        lock_path=REDESIGNED_LOCK_PATH,
        output_dir=output_dir,
        kira_dir=kira_dir,
        environ={"OPENROUTER_API_KEY": "test-key"},
    )

    assert summary["status"] == "complete"
    assert summary["formal_status"] == "COMPLETE"
    assert summary["actual_spend_usd"] == 0.02
    for label in ("arm-a", "arm-c"):
        report = json.loads(
            (output_dir / label / "benchmark_report.json").read_text()
        )
        assert report["episodes"][0]["cost_usd"] == 0.01
        assert report["provider_accounting"]["cost_usd"] == 0.01


def test_paid_live_boundary_rejects_obsolete_raw_xml_protocol_lock(
    tmp_path: Path,
) -> None:
    old_manifest = materialize_preregistered_rmso_manifest(
        LOCK_PATH, tmp_path / "old-manifest.json"
    )
    new_manifest = materialize_preregistered_rmso_manifest(
        REDESIGNED_LOCK_PATH, tmp_path / "new-manifest.json"
    )

    with pytest.raises(ValueError, match="graph-direct-vs-souffle-v2"):
        validate_redesigned_live_manifest(old_manifest)
    validate_redesigned_live_manifest(new_manifest)


def test_interrupted_live_summary_retains_accounting_invalid_reasons(
    tmp_path: Path, monkeypatch
) -> None:
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            pass

    class Gateway:
        def __init__(self, **kwargs):
            pass

        def accounting_snapshot(self):
            return {
                "actual_spend_usd": 0.001,
                "active_reservations_usd": 0.0,
                "accounting_complete": True,
                "attribution_complete": True,
                "unattributed_attempts": 0,
                "spend_cap_complete": True,
                "spend_cap_blocked_attempts": 0,
                "unknown_cost_calls": [],
                "policy_violations": [
                    {"call_number": 1, "reason": "provider metadata"}
                ],
            }

    def interrupt(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("pydexpi_datalog.benchmark.rmso_live.httpx.Client", Client)
    monkeypatch.setattr(
        "pydexpi_datalog.benchmark.rmso_live.LockedOpenRouterGateway", Gateway
    )
    monkeypatch.setattr("pydexpi_datalog.benchmark.rmso_live.run_benchmark", interrupt)
    kira_dir = tmp_path / "kira"
    kira_dir.mkdir()
    output_dir = tmp_path / "run"

    with pytest.raises(KeyboardInterrupt):
        run_rmso_live(
            lock_path=REDESIGNED_LOCK_PATH,
            output_dir=output_dir,
            kira_dir=kira_dir,
            environ={"OPENROUTER_API_KEY": "test-key"},
        )

    summary = json.loads((output_dir / "rmso_live_summary.json").read_text())
    assert summary["formal_status"] == "INCOMPLETE"
    assert summary["invalid_reasons"] == [
        "provider_policy_violation",
        "execution_failure",
    ]
