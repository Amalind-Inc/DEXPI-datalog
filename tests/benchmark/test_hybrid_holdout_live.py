"""Opt-in live hybrid holdout smoke (bead 3qo.9.10).

Requires OPENROUTER_API_KEY. Default model is deepseek-v4-flash; override with
HYBRID_HOLDOUT_MODEL=deepseek-pro.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.hybrid_holdout import (
    create_hybrid_holdout_live_arm,
    run_hybrid_holdout,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "testdata" / "benchmark" / "hybrid_holdout_lock.json"


pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="live hybrid holdout requires OPENROUTER_API_KEY",
)


def test_live_hybrid_holdout_flash_emits_gate_report(tmp_path: Path) -> None:
    model_key = os.environ.get("HYBRID_HOLDOUT_MODEL", "deepseek-flash")
    arm = create_hybrid_holdout_live_arm(model_key)
    output_dir = (
        REPO_ROOT
        / "artifacts"
        / "benchmark"
        / "hybrid-holdout-live"
        / model_key
    )
    report = run_hybrid_holdout(
        lock_path=LOCK_PATH,
        arm=arm,
        output_dir=output_dir,
    )

    assert report["metrics"]["questions"] == 10
    assert "grounded_credit" in report["metrics"]
    assert "cost_per_grounded_credit" in report["metrics"]
    assert report["gate"]["production_generalization_claim_allowed"] is False
    assert (output_dir / "hybrid_holdout_report.json").is_file()
