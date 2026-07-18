from __future__ import annotations

from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets
from pydexpi_datalog.benchmark.rmso_live import (
    create_rmso_live_arms,
    run_rmso_live,
)
from pydexpi_datalog.benchmark.souffle_arm import build_rmso_souffle_harbor_task


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
    assert [arm.artifact_root for arm in arms] == [
        tmp_path / "run" / "arm-a" / "harbor",
        tmp_path / "run" / "arm-b" / "harbor",
    ]
    assert arms[1].task_builder is build_rmso_souffle_harbor_task


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
