from __future__ import annotations

import json
from pathlib import Path

from .cache_execution import load_or_build_canonical_engineering_ir
from .execution_lock import acquire_run_context_lock
from .manifest import (
    Diagnostic,
    Manifest,
    best_effort_output_context,
    load_manifest_file,
    validate_manifest,
)
from .rule_evaluation import evaluate_rule_pack


def run_review_only(manifest_path: Path) -> int:
    raw_manifest, parse_diagnostics = load_manifest_file(manifest_path)
    artifact_dir, run_id = best_effort_output_context(raw_manifest, manifest_path)

    manifest, validation_diagnostics = validate_manifest(raw_manifest)
    diagnostics = [*parse_diagnostics, *validation_diagnostics]

    if manifest is not None and manifest.execution_mode != "review-only":
        diagnostics.append(
            Diagnostic(
                code="manifest.execution_mode_mismatch",
                severity="error",
                message="review-only command requires execution.mode to be 'review-only'.",
                path="execution.mode",
            )
        )
    if manifest is not None and manifest.rule_pack_path is None:
        diagnostics.append(
            Diagnostic(
                code="manifest.rule_pack_path_required",
                severity="error",
                message="review-only command requires rule_pack.path.",
                path="rule_pack.path",
            )
        )

    findings: list[dict[str, object]] = []
    cache: dict[str, str] | None = None
    run_lock = None
    try:
        if manifest is not None and not has_error_diagnostics(diagnostics):
            run_lock = acquire_run_context_lock(manifest)
            if run_lock is None:
                diagnostics.append(
                    Diagnostic(
                        code="run_context.locked",
                        severity="error",
                        message="Another run is already active for this full run context.",
                        path="run",
                    )
                )

        if manifest is not None and not has_error_diagnostics(diagnostics):
            cache_result = load_or_build_canonical_engineering_ir(manifest)
            cache = {
                "status": cache_result.cache_status,
                "cache_key": cache_result.cache_key,
                "cache_path": str(cache_result.cache_path.resolve()),
            }
            evaluation_result = evaluate_rule_pack(
                manifest.rule_pack_path, cache_result.ir_result
            )
            findings = evaluation_result.findings
            diagnostics.extend(
                Diagnostic(**diagnostic) for diagnostic in evaluation_result.diagnostics
            )

        artifact = build_artifact(
            manifest_path=manifest_path,
            manifest=manifest,
            diagnostics=diagnostics,
            findings=findings,
            cache=cache,
        )
        persist_artifact(artifact_dir, run_id, artifact, manifest_path)
        print(render_console_report(artifact))
    finally:
        if run_lock is not None:
            run_lock.release()

    has_errors = any(item["severity"] == "error" for item in artifact["diagnostics"])
    return 1 if has_errors else 0


def has_error_diagnostics(diagnostics: list[Diagnostic]) -> bool:
    return any(diagnostic.severity == "error" for diagnostic in diagnostics)


def build_artifact(
    manifest_path: Path,
    manifest: Manifest | None,
    diagnostics: list[Diagnostic],
    findings: list[dict[str, object]],
    cache: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "artifact_type": "review_only",
        "run": {
            "manifest_path": str(manifest_path.resolve()),
            "run_id": manifest.run_id if manifest else None,
            "execution_mode": manifest.execution_mode if manifest else None,
            "status": "failed"
            if any(diag.severity == "error" for diag in diagnostics)
            else "ok",
        },
        "diagnostics": [diag.to_dict() for diag in diagnostics],
        "cache": cache,
        "findings": findings,
        "patch_proposals": [],
    }


def persist_artifact(
    artifact_dir: Path, run_id: str, artifact: dict[str, object], manifest_path: Path
) -> None:
    run_dir = artifact_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "review_only.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")

    manifest_copy = run_dir / manifest_path.name
    if manifest_path.exists():
        manifest_copy.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")


def render_console_report(artifact: dict[str, object]) -> str:
    lines = ["Review-Only Report"]
    run = artifact["run"]
    lines.append(f"Status: {run['status']}")
    if run["run_id"]:
        lines.append(f"Run ID: {run['run_id']}")
    lines.append("")
    findings = artifact["findings"]
    lines.append(f"Findings: {len(findings)}")
    for finding in findings:
        affected_object_ids = finding["affected_object_ids"]
        affected_object = affected_object_ids[0] if affected_object_ids else "-"
        lines.append(
            f"[{finding['severity']}] {finding['rule_id']} {affected_object}"
        )
    return "\n".join(lines)
