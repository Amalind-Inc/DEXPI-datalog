from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class LegacyXmlObject:
    object_id: str
    normalized_tag: str
    source_attributes: dict[str, str]
    diagnostics: list[dict[str, str]]


@dataclass(frozen=True)
class LegacyXmlNormalizationResult:
    normalized_objects: list[LegacyXmlObject]
    raw_tag_variants: dict[str, list[str]]
    diagnostics: list[dict[str, str]]


def build_legacy_xml_normalization(source_path: Path) -> LegacyXmlNormalizationResult:
    tree = ET.parse(source_path)
    root = tree.getroot()

    normalized_objects: list[LegacyXmlObject] = []
    raw_tag_variants: dict[str, list[str]] = {}
    diagnostics: list[dict[str, str]] = []
    for element in root.iter():
        object_id = element.attrib.get("id")
        if not object_id:
            continue

        normalized_tag = element.attrib.get("tag", object_id)
        raw_variants = collect_raw_tag_variants(element)
        object_diagnostics = build_ambiguity_diagnostics(
            object_id=object_id,
            normalized_tag=normalized_tag,
            raw_variants=raw_variants,
        )
        normalized_objects.append(
            LegacyXmlObject(
                object_id=object_id,
                normalized_tag=normalized_tag,
                source_attributes=dict(element.attrib),
                diagnostics=object_diagnostics,
            )
        )
        raw_tag_variants[normalized_tag] = raw_variants
        diagnostics.extend(object_diagnostics)

    normalized_objects.sort(key=lambda item: item.object_id)
    return LegacyXmlNormalizationResult(
        normalized_objects=normalized_objects,
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
    *, object_id: str, normalized_tag: str, raw_variants: list[str]
) -> list[dict[str, str]]:
    normalized_key = normalize_tag(normalized_tag)
    diagnostics: list[dict[str, str]] = []

    for raw_variant in raw_variants:
        if raw_variant == normalized_tag:
            continue
        if normalize_tag(raw_variant) != normalized_key:
            continue
        diagnostics.append(
            {
                "code": "normalizer.ambiguous_normalized_tag",
                "severity": "warning",
                "message": (
                    f"Normalized tag '{normalized_tag}' for object '{object_id}' has "
                    f"an ambiguous raw variant '{raw_variant}'."
                ),
                "path": object_id,
            }
        )
        break

    return diagnostics


def normalize_tag(value: str) -> str:
    return "".join(char for char in value if char.isalnum()).upper()
