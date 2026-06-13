from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class CanonicalObject:
    object_id: str
    canonical_tag: str
    source_attributes: dict[str, str]
    diagnostics: list[dict[str, str]]


@dataclass(frozen=True)
class CanonicalEngineeringIRResult:
    canonical_objects: list[CanonicalObject]
    raw_tag_variants: dict[str, list[str]]
    diagnostics: list[dict[str, str]]


def build_canonical_engineering_ir(source_path: Path) -> CanonicalEngineeringIRResult:
    tree = ET.parse(source_path)
    root = tree.getroot()

    canonical_objects: list[CanonicalObject] = []
    raw_tag_variants: dict[str, list[str]] = {}
    diagnostics: list[dict[str, str]] = []
    for element in root.iter():
        object_id = element.attrib.get("id")
        if not object_id:
            continue

        canonical_tag = element.attrib.get("tag", object_id)
        raw_variants = collect_raw_tag_variants(element)
        object_diagnostics = build_ambiguity_diagnostics(
            object_id=object_id,
            canonical_tag=canonical_tag,
            raw_variants=raw_variants,
        )
        canonical_objects.append(
            CanonicalObject(
                object_id=object_id,
                canonical_tag=canonical_tag,
                source_attributes=dict(element.attrib),
                diagnostics=object_diagnostics,
            )
        )
        raw_tag_variants[canonical_tag] = raw_variants
        diagnostics.extend(object_diagnostics)

    canonical_objects.sort(key=lambda item: item.object_id)
    return CanonicalEngineeringIRResult(
        canonical_objects=canonical_objects,
        raw_tag_variants=raw_tag_variants,
        diagnostics=diagnostics,
    )


def collect_raw_tag_variants(element: ET.Element) -> list[str]:
    raw_variants: list[str] = []
    for key, value in element.attrib.items():
        if not key.startswith("tag") or not value:
            continue
        if value not in raw_variants:
            raw_variants.append(value)
    return raw_variants


def build_ambiguity_diagnostics(
    *, object_id: str, canonical_tag: str, raw_variants: list[str]
) -> list[dict[str, str]]:
    canonical_normalized = normalize_tag(canonical_tag)
    diagnostics: list[dict[str, str]] = []

    for raw_variant in raw_variants:
        if raw_variant == canonical_tag:
            continue
        if normalize_tag(raw_variant) != canonical_normalized:
            continue
        diagnostics.append(
            {
                "code": "normalizer.ambiguous_canonical_tag",
                "severity": "warning",
                "message": (
                    f"Canonical tag '{canonical_tag}' for object '{object_id}' has "
                    f"an ambiguous raw variant '{raw_variant}'."
                ),
                "path": object_id,
            }
        )
        break

    return diagnostics


def normalize_tag(value: str) -> str:
    return "".join(char for char in value if char.isalnum()).upper()
