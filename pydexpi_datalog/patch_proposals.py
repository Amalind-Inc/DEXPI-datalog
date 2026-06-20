from __future__ import annotations

from dataclasses import dataclass

from .legacy_xml_normalization import LegacyXmlNormalizationResult


@dataclass(frozen=True)
class PatchProposalResult:
    patch_proposals: list[dict[str, object]]
    diagnostics: list[dict[str, str]]


def generate_patch_proposals(
    findings: list[dict[str, object]],
    normalization_result: LegacyXmlNormalizationResult,
) -> PatchProposalResult:
    proposals: list[dict[str, object]] = []
    object_ids = {obj.object_id for obj in normalization_result.normalized_objects}

    for finding in findings:
        affected_object_ids = finding["affected_object_ids"]
        if len(affected_object_ids) != 1:
            continue
        target_object_id = affected_object_ids[0]
        if target_object_id not in object_ids:
            continue

        proposals.append(
            {
                "finding_rule_id": finding["rule_id"],
                "affected_object_ids": affected_object_ids,
                "action": "modify_object",
                "target_object_id": target_object_id,
                "changes": {
                    "review_status": "confirmed-tagged-equipment",
                },
                "evidence_trail": finding["evidence_trail"],
            }
        )

    return PatchProposalResult(patch_proposals=proposals, diagnostics=[])
