from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .cache_execution import (
    load_or_build_canonical_engineering_ir,
    serialize_ir_result,
)
from .execution_lock import acquire_run_context_lock
from .manifest import (
    Diagnostic,
    Manifest,
    best_effort_output_context,
    load_manifest_file,
    validate_manifest,
)


def run_dry_run(manifest_path: Path) -> int:
    raw_manifest, parse_diagnostics = load_manifest_file(manifest_path)
    artifact_dir, run_id = best_effort_output_context(raw_manifest, manifest_path)

    manifest, validation_diagnostics = validate_manifest(raw_manifest)
    diagnostics = [*parse_diagnostics, *validation_diagnostics]

    if manifest is not None and manifest.execution_mode != "dry-run":
        diagnostics.append(
            Diagnostic(
                code="manifest.execution_mode_mismatch",
                severity="error",
                message="dry-run command requires execution.mode to be 'dry-run'.",
                path="execution.mode",
            )
        )

    summary: dict[str, object] | None = None
    canonical_ir: dict[str, object] | None = None
    cache: dict[str, str] | None = None
    run_lock = None
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

    try:
        if manifest is not None and not has_error_diagnostics(diagnostics):
            summary, source_diagnostics = summarize_source(manifest)
            diagnostics.extend(source_diagnostics)
            if not has_error_diagnostics(diagnostics):
                cache_result = load_or_build_canonical_engineering_ir(manifest)
                canonical_ir = serialize_ir_result(cache_result.ir_result)
                cache = {
                    "status": cache_result.cache_status,
                    "cache_key": cache_result.cache_key,
                    "cache_path": str(cache_result.cache_path.resolve()),
                }

        artifact = build_artifact(
            manifest_path=manifest_path,
            manifest=manifest,
            diagnostics=diagnostics,
            summary=summary,
            canonical_ir=canonical_ir,
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


def summarize_source(manifest: Manifest) -> tuple[dict[str, object] | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    source_path = manifest.dexpi_xml
    if not source_path.exists():
        diagnostics.append(
            Diagnostic(
                code="source.missing_file",
                severity="error",
                message=f"DEXPI source file does not exist: {source_path}",
                path="input.dexpi_xml",
            )
        )
        return None, diagnostics

    try:
        tree = ET.parse(source_path)
    except ET.ParseError as exc:
        diagnostics.append(
            Diagnostic(
                code="source.invalid_xml",
                severity="error",
                message=f"DEXPI source file is not well-formed XML: {exc}",
                path="input.dexpi_xml",
            )
        )
        return None, diagnostics

    root = tree.getroot()
    elements = list(root.iter())
    tags = [strip_namespace(elem.tag) for elem in elements]
    tag_counts = Counter(tags)
    object_ids = sorted(
        elem.attrib["id"] for elem in elements if "id" in elem.attrib and elem.attrib["id"]
    )

    diagnostics.append(
        Diagnostic(
            code="source.loaded",
            severity="info",
            message=f"Loaded XML root <{strip_namespace(root.tag)}> successfully.",
            path="input.dexpi_xml",
        )
    )

    summary = {
        "root_tag": strip_namespace(root.tag),
        "element_count": len(tags),
        "top_level_children": len(list(root)),
        "unique_tag_count": len(tag_counts),
        "elements_with_id_count": len(object_ids),
        "object_ids": object_ids,
        "tag_counts": dict(sorted(tag_counts.items())),
    }
    return summary, diagnostics


def strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def build_artifact(
    manifest_path: Path,
    manifest: Manifest | None,
    diagnostics: list[Diagnostic],
    summary: dict[str, object] | None,
    canonical_ir: dict[str, object] | None,
    cache: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "artifact_type": "dry_run_summary",
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
        "structural_summary": summary,
        "canonical_engineering_ir": canonical_ir,
        "findings": [],
        "patch_proposals": [],
    }


def persist_artifact(
    artifact_dir: Path, run_id: str, artifact: dict[str, object], manifest_path: Path
) -> None:
    run_dir = artifact_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "dry_run_summary.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")

    manifest_copy = run_dir / manifest_path.name
    if manifest_path.exists():
        manifest_copy.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")


def render_console_report(artifact: dict[str, object]) -> str:
    lines = ["Dry-Run Summary"]
    run = artifact["run"]
    lines.append(f"Status: {run['status']}")
    if run["run_id"]:
        lines.append(f"Run ID: {run['run_id']}")

    summary = artifact["structural_summary"]
    if summary:
        lines.append("")
        lines.append("Structural Summary")
        lines.append(f"Root tag: {summary['root_tag']}")
        lines.append(f"Element count: {summary['element_count']}")
        lines.append(f"Top-level children: {summary['top_level_children']}")
        lines.append(f"Unique tag count: {summary['unique_tag_count']}")

    diagnostics = artifact["diagnostics"]
    lines.append("")
    lines.append("Diagnostics")
    if diagnostics:
        for diagnostic in diagnostics:
            lines.append(
                f"[{diagnostic['severity']}] {diagnostic['code']} "
                f"{diagnostic['path']}: {diagnostic['message']}"
            )
    else:
        lines.append("None")

    return "\n".join(lines)
