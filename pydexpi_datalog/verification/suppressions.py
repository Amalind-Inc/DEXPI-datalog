from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuppressionResult:
    raw_findings: list[dict[str, object]]
    suppressed_findings: list[dict[str, object]]
    suppression_records: list[dict[str, object]]
    diagnostics: list[dict[str, str]]


def apply_suppressions(
    findings: list[dict[str, object]],
    waivers: list[dict[str, object]],
) -> SuppressionResult:
    raw_findings = list(findings)
    remaining_findings: list[dict[str, object]] = []
    suppression_records: list[dict[str, object]] = []

    for finding in findings:
        matched_waiver = match_waiver(finding, waivers)
        if matched_waiver is None:
            remaining_findings.append(finding)
            continue

        suppression_records.append(
            {
                "waiver_id": matched_waiver["waiver_id"],
                "rule_id": finding["rule_id"],
                "affected_object_ids": finding["affected_object_ids"],
                "rationale": matched_waiver["rationale"],
            }
        )

    return SuppressionResult(
        raw_findings=raw_findings,
        suppressed_findings=remaining_findings,
        suppression_records=suppression_records,
        diagnostics=[],
    )


def match_waiver(
    finding: dict[str, object], waivers: list[dict[str, object]]
) -> dict[str, object] | None:
    for waiver in waivers:
        if waiver.get("rule_id") != finding["rule_id"]:
            continue
        if waiver.get("affected_object_id") not in finding["affected_object_ids"]:
            continue
        return waiver
    return None
