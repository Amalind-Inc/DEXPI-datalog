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
    RMSO_REDESIGNED_REVISION,
    RMSO_TEMPLATE_REVISION,
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
from pydexpi_datalog.benchmark.template_arm_task import create_template_arm


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_PRICE_PER_MILLION = 0.098
COMPLETION_PRICE_PER_MILLION = 0.196
RESERVED_INPUT_TOKENS = 1_000_000
SUMMARY_FILENAME = "rmso_live_summary.json"


def apply_episode_cost_accounting(
    report: dict[str, object], gateway: LockedOpenRouterGateway
) -> dict[str, object]:
    """Attach provider-ledger costs to one arm report."""
    arm_id = report.get("arm_id")
    episodes = report.get("episodes")
    if not isinstance(arm_id, str) or not isinstance(episodes, list):
        raise ValueError("Benchmark report lacks an arm_id or episodes list.")
    complete_count = 0
    known_cost = 0.0
    policy_calls: list[int] = []
    for episode in episodes:
        if not isinstance(episode, dict) or not isinstance(
            episode.get("question_id"), str
        ):
            raise ValueError("Benchmark report contains an invalid episode.")
        accounting = gateway.episode_accounting(
            arm_id=arm_id,
            question_id=episode["question_id"],
        )
        usage = episode.get("usage")
        if not isinstance(usage, dict):
            usage = {}
            episode["usage"] = usage
        usage["provider_accounting"] = accounting
        episode["cost_usd"] = accounting["cost_usd"]
        known_cost += float(accounting["known_cost_usd"])
        if accounting["accounting_complete"]:
            complete_count += 1
        policy_calls.extend(accounting["policy_violation_call_numbers"])
    complete = complete_count == len(episodes)
    arm_accounting: dict[str, object] = {
        "accounting_complete": complete,
        "cost_usd": known_cost if complete else None,
        "episodes": len(episodes),
        "episodes_with_complete_accounting": complete_count,
        "known_cost_usd": known_cost,
        "policy_violation_call_numbers": sorted(policy_calls),
    }
    report["provider_accounting"] = arm_accounting
    return arm_accounting


def finalize_rmso_accounting(
    summary: dict[str, object], gateway: LockedOpenRouterGateway
) -> None:
    """Set the formal run status from the provider accounting ledger."""
    snapshot = gateway.accounting_snapshot()
    reasons = []
    if not snapshot["accounting_complete"]:
        reasons.append("unknown_provider_cost")
    if not snapshot["attribution_complete"]:
        reasons.append("missing_call_attribution")
    if snapshot.get("spend_cap_complete") is False:
        reasons.append("spend_cap_exhausted")
    if snapshot["policy_violations"]:
        reasons.append("provider_policy_violation")
    if snapshot["active_reservations_usd"] != 0:
        reasons.append("unsettled_provider_reservation")
    summary.update(
        {
            "status": "invalid" if reasons else "complete",
            "formal_status": "INCOMPLETE" if reasons else "COMPLETE",
            "actual_spend_usd": snapshot["actual_spend_usd"],
            "provider_accounting": snapshot,
            "invalid_reasons": reasons,
        }
    )


def validate_redesigned_live_manifest(manifest_path: Path) -> str:
    """Reject obsolete RMSO locks at the paid live-run boundary.

    Returns the locked design revision so the executor can select the
    matching arm matrix.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = manifest.get("rmso_lock") if isinstance(manifest, dict) else None
    revision = lock.get("design_revision") if isinstance(lock, dict) else None
    if revision not in (RMSO_REDESIGNED_REVISION, RMSO_TEMPLATE_REVISION):
        raise ValueError(
            "Paid RMSO runs require design revision "
            f"{RMSO_REDESIGNED_REVISION} or {RMSO_TEMPLATE_REVISION}."
        )
    if lock.get("accounting_contract") != {
        "provider_ledger": "required",
        "unknown_cost": "run_incomplete",
        "policy_violation": "run_incomplete",
    }:
        raise ValueError("Paid RMSO runs require the fail-closed accounting contract.")
    return revision


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
    arm_c = create_souffle_arm(
        "deepseek",
        kira_dir=kira_dir,
        budgets=budgets,
        environ=environ,
        request_gateway=request_gateway,
    )
    arm_a = replace(
        arm_a,
        runner=replace(arm_a.runner, accounting_arm_id=arm_a.arm_id),
    )
    arm_c = replace(
        arm_c,
        runner=replace(arm_c.runner, accounting_arm_id=arm_c.arm_id),
    )
    return (
        replace(arm_a, artifact_root=output_dir / "arm-a" / "harbor"),
        replace(arm_c, artifact_root=output_dir / "arm-c" / "harbor"),
    )


def create_rmso_template_live_arms(
    *,
    kira_dir: Path,
    output_dir: Path,
    budgets: EpisodeBudgets,
    environ: Mapping[str, str],
    request_gateway: LockedOpenRouterGateway,
) -> tuple[AgenticArm, AgenticArm]:
    """Construct the locked v3 matrix arms: C-classic (fixed) and Arm T."""
    arm_c = create_souffle_arm(
        "deepseek",
        kira_dir=kira_dir,
        budgets=budgets,
        environ=environ,
        request_gateway=request_gateway,
    )
    arm_t = create_template_arm(
        "deepseek",
        kira_dir=kira_dir,
        budgets=budgets,
        environ=environ,
        request_gateway=request_gateway,
    )
    arm_c = replace(
        arm_c,
        runner=replace(arm_c.runner, accounting_arm_id=arm_c.arm_id),
    )
    arm_t = replace(
        arm_t,
        runner=replace(arm_t.runner, accounting_arm_id=arm_t.arm_id),
    )
    return (
        replace(arm_c, artifact_root=output_dir / "arm-c" / "harbor"),
        replace(arm_t, artifact_root=output_dir / "arm-t" / "harbor"),
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
    revision = validate_redesigned_live_manifest(manifest)
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
        "design_revision": revision,
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
        if revision == RMSO_TEMPLATE_REVISION:
            labels = ("arm-c", "arm-t")
            arms = create_rmso_template_live_arms(
                kira_dir=kira_dir,
                output_dir=output_dir,
                budgets=budgets,
                environ=env,
                request_gateway=gateway,
            )
        else:
            labels = ("arm-a", "arm-c")
            arms = create_rmso_live_arms(
                kira_dir=kira_dir,
                output_dir=output_dir,
                budgets=budgets,
                environ=env,
                request_gateway=gateway,
            )
        try:
            reports = []
            for label, arm in zip(labels, arms, strict=True):
                report_dir = output_dir / label
                report = run_benchmark(
                    manifest_path=manifest,
                    arm=arm,
                    output_dir=report_dir,
                    episode_workers=1,
                )
                arm_accounting = apply_episode_cost_accounting(report, gateway)
                report_path = report_dir / "benchmark_report.json"
                _write_json(report_path, report)
                reports.append(
                    {
                        "label": label,
                        "arm_id": report["arm_id"],
                        "report": str(report_path),
                        "totals": report["totals"],
                        "provider_accounting": arm_accounting,
                    }
                )
            summary.update(
                {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "reports": reports,
                }
            )
            finalize_rmso_accounting(summary, gateway)
        except BaseException as error:
            finalize_rmso_accounting(summary, gateway)
            invalid_reasons = list(summary["invalid_reasons"])
            invalid_reasons.append("execution_failure")
            summary.update(
                {
                    "status": "failed",
                    "formal_status": "INCOMPLETE",
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "invalid_reasons": invalid_reasons,
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
    return 0 if summary.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
