from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .canonical_ir import (
    CanonicalEngineeringIRResult,
    CanonicalObject,
    build_canonical_engineering_ir,
)
from .manifest import Manifest, default_artifact_dir


@dataclass(frozen=True)
class CacheBackedIRResult:
    ir_result: CanonicalEngineeringIRResult
    cache_status: str
    cache_key: str
    cache_path: Path


def load_or_build_canonical_engineering_ir(
    manifest: Manifest,
) -> CacheBackedIRResult:
    source_bytes = manifest.dexpi_xml.read_bytes()
    cache_key = hashlib.sha256(source_bytes).hexdigest()
    cache_path = default_artifact_dir() / "cache" / f"{cache_key}.json"

    if cache_path.exists():
        cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return CacheBackedIRResult(
            ir_result=deserialize_ir_result(cached_payload),
            cache_status="hit",
            cache_key=cache_key,
            cache_path=cache_path,
        )

    ir_result = build_canonical_engineering_ir(manifest.dexpi_xml)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(serialize_ir_result(ir_result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return CacheBackedIRResult(
        ir_result=ir_result,
        cache_status="miss",
        cache_key=cache_key,
        cache_path=cache_path,
    )


def serialize_ir_result(
    ir_result: CanonicalEngineeringIRResult,
) -> dict[str, object]:
    return {
        "canonical_objects": [
            {
                "object_id": obj.object_id,
                "canonical_tag": obj.canonical_tag,
                "source_attributes": obj.source_attributes,
                "diagnostics": obj.diagnostics,
            }
            for obj in ir_result.canonical_objects
        ],
        "raw_tag_variants": ir_result.raw_tag_variants,
        "diagnostics": ir_result.diagnostics,
    }


def deserialize_ir_result(payload: dict[str, object]) -> CanonicalEngineeringIRResult:
    canonical_objects = [
        CanonicalObject(
            object_id=item["object_id"],
            canonical_tag=item["canonical_tag"],
            source_attributes=item["source_attributes"],
            diagnostics=item["diagnostics"],
        )
        for item in payload["canonical_objects"]
    ]
    return CanonicalEngineeringIRResult(
        canonical_objects=canonical_objects,
        raw_tag_variants=payload["raw_tag_variants"],
        diagnostics=payload["diagnostics"],
    )
