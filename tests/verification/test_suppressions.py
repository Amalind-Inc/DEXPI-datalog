from __future__ import annotations

import unittest

from pydexpi_datalog.verification.suppressions import apply_suppressions


class SuppressionTests(unittest.TestCase):
    def raw_finding(self) -> dict[str, object]:
        return {
            "rule_id": "equipment-tag-present",
            "severity": "informational",
            "affected_object_ids": ["P-101"],
            "evidence_trail": {
                "primary_rule": "equipment-tag-present",
                "supporting_facts": [
                    {
                        "predicate": "has_tag",
                        "object_id": "P-101",
                        "normalized_tag": "P-101",
                    }
                ],
            },
        }

    def matching_waiver(self) -> dict[str, object]:
        return {
            "waiver_id": "WVR-001",
            "rule_id": "equipment-tag-present",
            "affected_object_id": "P-101",
            "rationale": "Reviewed and accepted for this run.",
        }

    def test_matching_waiver_suppresses_finding_while_preserving_raw_record(self) -> None:
        raw_finding = self.raw_finding()
        waiver = self.matching_waiver()

        suppression_result = apply_suppressions([raw_finding], [waiver])

        self.assertEqual(suppression_result.diagnostics, [])
        self.assertEqual(suppression_result.raw_findings, [raw_finding])
        self.assertEqual(suppression_result.suppressed_findings, [])
        self.assertEqual(
            suppression_result.suppression_records,
            [
                {
                    "waiver_id": "WVR-001",
                    "rule_id": "equipment-tag-present",
                    "affected_object_ids": ["P-101"],
                    "rationale": "Reviewed and accepted for this run.",
                }
            ],
        )

    def test_suppression_does_not_mutate_raw_finding_record(self) -> None:
        raw_finding = self.raw_finding()
        original_snapshot = self.raw_finding()
        waiver = self.matching_waiver()

        suppression_result = apply_suppressions([raw_finding], [waiver])

        self.assertEqual(raw_finding, original_snapshot)
        self.assertEqual(suppression_result.raw_findings[0], original_snapshot)

if __name__ == "__main__":
    unittest.main()
