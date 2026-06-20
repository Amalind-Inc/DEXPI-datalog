from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class PersistedArtifactSetResult:
    artifact_ids: dict[str, str]
    artifact_paths: dict[str, Path]


def persist_artifact_set(
    *,
    artifact_dir: Path,
    run_id: str,
    artifact_name: str,
    artifact_type: str,
    artifact: dict[str, object],
    manifest_path: Path,
    failure: dict[str, object] | None = None,
) -> PersistedArtifactSetResult:
    run_dir = artifact_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_copy = run_dir / manifest_path.name
    if manifest_path.exists():
        manifest_copy.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")

    artifact_path = run_dir / artifact_name
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")

    artifact_ids = {
        "manifest": f"{run_id}:manifest",
        artifact_type: f"{run_id}:{artifact_type}",
    }
    artifacts = [
        {
            "artifact_id": artifact_ids["manifest"],
            "artifact_type": "manifest_copy",
            "path": str(manifest_copy.resolve()),
        },
        {
            "artifact_id": artifact_ids[artifact_type],
            "artifact_type": artifact_type,
            "path": str(artifact_path.resolve()),
        },
    ]
    artifact_set_path = run_dir / "artifact_set.json"
    artifact_set_failure = None
    if failure is not None:
        artifact_set_failure = dict(failure)
        artifact_set_failure["artifact_id"] = artifact_ids[artifact_type]

    artifact_set_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "artifact_ids": artifact_ids,
                "artifacts": artifacts,
                "failure": artifact_set_failure,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return PersistedArtifactSetResult(
        artifact_ids=artifact_ids,
        artifact_paths={
            "manifest": manifest_copy,
            artifact_type: artifact_path,
            "artifact_set": artifact_set_path,
        },
    )
