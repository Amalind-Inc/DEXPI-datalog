from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .xml_normalization import (
    LegacyXmlNormalizationResult,
    LegacyXmlObject,
    build_legacy_xml_normalization,
)
from ..workflow.manifest import Manifest, default_artifact_dir


@dataclass(frozen=True)
class CacheBackedNormalizationResult:
    normalization_result: LegacyXmlNormalizationResult
    cache_status: str
    cache_key: str
    cache_path: Path


def load_or_build_legacy_xml_normalization(
    manifest: Manifest,
) -> CacheBackedNormalizationResult:
    source_bytes = manifest.dexpi_xml.read_bytes()
    cache_key = hashlib.sha256(source_bytes).hexdigest()
    cache_path = default_artifact_dir() / "cache" / f"{cache_key}.json"

    if cache_path.exists():
        cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return CacheBackedNormalizationResult(
            normalization_result=deserialize_normalization_result(cached_payload),
            cache_status="hit",
            cache_key=cache_key,
            cache_path=cache_path,
        )

    normalization_result = build_legacy_xml_normalization(manifest.dexpi_xml)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            serialize_normalization_result(normalization_result),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return CacheBackedNormalizationResult(
        normalization_result=normalization_result,
        cache_status="miss",
        cache_key=cache_key,
        cache_path=cache_path,
    )


def serialize_normalization_result(
    normalization_result: LegacyXmlNormalizationResult,
) -> dict[str, object]:
    return {
        "normalized_objects": [
            {
                "object_id": obj.object_id,
                "normalized_tag": obj.normalized_tag,
                "source_attributes": obj.source_attributes,
                "diagnostics": obj.diagnostics,
            }
            for obj in normalization_result.normalized_objects
        ],
        "raw_tag_variants": normalization_result.raw_tag_variants,
        "diagnostics": normalization_result.diagnostics,
    }


def deserialize_normalization_result(
    payload: dict[str, object],
) -> LegacyXmlNormalizationResult:
    object_payloads = payload.get("normalized_objects", payload.get("canonical_objects", []))
    normalized_objects = [
        LegacyXmlObject(
            object_id=item["object_id"],
            normalized_tag=item.get("normalized_tag", item.get("canonical_tag", "")),
            source_attributes=item["source_attributes"],
            diagnostics=normalize_legacy_diagnostics(item["diagnostics"]),
        )
        for item in object_payloads
    ]
    return LegacyXmlNormalizationResult(
        normalized_objects=normalized_objects,
        raw_tag_variants=payload["raw_tag_variants"],
        diagnostics=normalize_legacy_diagnostics(payload["diagnostics"]),
    )


def normalize_legacy_diagnostics(
    diagnostics: list[dict[str, str]],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for diagnostic in diagnostics:
        item = dict(diagnostic)
        if item.get("code") == "normalizer.ambiguous_canonical_tag":
            item["code"] = "normalizer.ambiguous_normalized_tag"
            item["message"] = item["message"].replace(
                "Canonical tag", "Normalized tag"
            )
        normalized.append(item)
    return normalized
