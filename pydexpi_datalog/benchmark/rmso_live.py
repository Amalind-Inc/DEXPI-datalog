"""Fail-closed executor for the preregistered two-arm RMSO live matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

import httpx

from pydexpi_datalog.benchmark.agentic_arm import (
    AgenticArm,
    EpisodeBudgets,
    create_rmso_graph_direct_arm,
    load_episode_budgets,
)
from pydexpi_datalog.benchmark.rmso_eval import (
    materialize_preregistered_rmso_manifest,
)
from pydexpi_datalog.benchmark.rmso_openrouter_gateway import (
    LockedOpenRouterGateway,
)
from pydexpi_datalog.benchmark.rmso_openrouter_policy import (
    OpenRouterRequestPolicy,
)
from pydexpi_datalog.benchmark.runner import run_benchmark
from pydexpi_datalog.benchmark.souffle_arm import create_souffle_arm


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_PRICE_PER_MILLION = 0.098
COMPLETION_PRICE_PER_MILLION = 0.196
RESERVED_INPUT_TOKENS = 1_000_000
SUMMARY_FILENAME = "rmso_live_summary.json"


def create_rmso_live_arms(
    *,
    kira_dir: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
    environ: Mapping[str, str],
    request_gateway: LockedOpenRouterGateway,
) -> tuple[AgenticArm, AgenticArm]:
    """Construct exactly the two locked DeepSeek arms for this spike."""
    arm_a = create_rmso_graph_direct_arm(
        "deepseek",
        kira_dir=kira_dir,
        budgets=budgets,
        environ=environ,
        request_gateway=request_gateway,
    )
    arm_b = create_souffle_arm(
        "deepseek",
        kira_dir=kira_dir,
        budgets=budgets,
        environ=environ,
        request_gateway=request_gateway,
    )
    return (
        replace(arm_a, artifact_root=output_dir / "arm-a" / "harbor"),
        replace(arm_b, artifact_root=output_dir / "arm-b" / "harbor"),
    )


def run_rmso_live(
    *,
    lock_path: Path,
    output_dir: Path,
    kira_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run the one-shot two-arm matrix and preserve failures without retrying."""
    env = dict(os.environ if environ is None else environ)
    credential = env.get("OPENROUTER_API_KEY", "")
    if not credential:
        raise ValueError("OPENROUTER_API_KEY is required for the RMSO live run")
    if not kira_dir.is_dir():
        raise FileNotFoundError(f"Terminus KIRA checkout does not exist: {kira_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"RMSO live output must be fresh; refusing replacement run: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = materialize_preregistered_rmso_manifest(
        lock_path, output_dir / "inputs" / "rmso_manifest.json"
    )
    budgets = load_episode_budgets(manifest)
    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=PROMPT_PRICE_PER_MILLION,
        completion_price_per_million=COMPLETION_PRICE_PER_MILLION,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    summary: dict[str, object] = {
        "schema_version": 1,
        "status": "running",
        "started_at": started_at,
        "manifest": str(manifest),
        "model": "deepseek/deepseek-v4-flash",
        "episode_budgets": asdict(budgets),
        "spend_cap_usd": 10.0,
        "reports": [],
    }
    _write_json(output_dir / SUMMARY_FILENAME, summary)

    with httpx.Client(timeout=httpx.Timeout(360.0, connect=30.0)) as client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential=credential,
            artifact_dir=output_dir / "openrouter",
            reserved_input_tokens=RESERVED_INPUT_TOKENS,
            upstream_url=OPENROUTER_URL,
            http_client=client,
        )
        arms = create_rmso_live_arms(
            kira_dir=kira_dir,
            output_dir=output_dir,
            budgets=budgets,
            environ=env,
            request_gateway=gateway,
        )
        try:
            reports = []
            for label, arm in zip(("arm-a", "arm-b"), arms, strict=True):
                report_dir = output_dir / label
                report = run_benchmark(
                    manifest_path=manifest,
                    arm=arm,
                    output_dir=report_dir,
                    episode_workers=1,
                )
                reports.append(
                    {
                        "label": label,
                        "arm_id": report["arm_id"],
                        "report": str(report_dir / "benchmark_report.json"),
                        "totals": report["totals"],
                    }
                )
            summary.update(
                {
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "actual_spend_usd": gateway.actual_spend,
                    "reports": reports,
                }
            )
        except BaseException as error:
            summary.update(
                {
                    "status": "failed",
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "actual_spend_usd": gateway.actual_spend,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            _write_json(output_dir / SUMMARY_FILENAME, summary)
            raise
    _write_json(output_dir / SUMMARY_FILENAME, summary)
    return summary


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    staging.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kira-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_rmso_live(
        lock_path=args.lock,
        output_dir=args.output,
        kira_dir=args.kira_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
