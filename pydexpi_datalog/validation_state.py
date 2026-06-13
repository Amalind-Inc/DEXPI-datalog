from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationStateResult:
    validation_states: list[dict[str, object]]
    diagnostics: list[dict[str, str]]


def derive_validation_state(
    *,
    raw_findings: list[dict[str, object]],
    suppressed_findings: list[dict[str, object]],
    suppression_records: list[dict[str, object]],
) -> ValidationStateResult:
    del raw_findings
    del suppression_records

    grouped_findings: dict[tuple[str, ...], list[dict[str, object]]] = {}
    for finding in suppressed_findings:
        key = tuple(finding["affected_object_ids"])
        grouped_findings.setdefault(key, []).append(finding)

    validation_states: list[dict[str, object]] = []
    for key, findings in grouped_findings.items():
        source_rule_ids = sorted({finding["rule_id"] for finding in findings})
        state = "conflicted" if len(source_rule_ids) > 1 else "needs_review"
        validation_states.append(
            {
                "affected_object_ids": list(key),
                "state": state,
                "source_rule_ids": source_rule_ids,
            }
        )

    return ValidationStateResult(validation_states=validation_states, diagnostics=[])
