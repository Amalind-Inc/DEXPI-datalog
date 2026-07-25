from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .manifest import Manifest, default_artifact_dir


@dataclass(frozen=True)
class RunContextLock:
    context_key: str
    lock_path: Path

    def release(self) -> None:
        self.lock_path.unlink(missing_ok=True)


def build_run_context_key(manifest: Manifest) -> str:
    payload = {
        "dexpi_xml": str(manifest.dexpi_xml.resolve()),
        "rule_pack_name": manifest.rule_pack_name,
        "rule_pack_version": manifest.rule_pack_version,
        "rule_pack_lifecycle_state": manifest.rule_pack_lifecycle_state,
        "execution_mode": manifest.execution_mode,
        "run_id": manifest.run_id,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def acquire_run_context_lock(manifest: Manifest) -> RunContextLock | None:
    context_key = build_run_context_key(manifest)
    lock_path = default_artifact_dir() / "locks" / f"{context_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            handle.write(f"{manifest.run_id}\n")
    except FileExistsError:
        return None
    return RunContextLock(context_key=context_key, lock_path=lock_path)
