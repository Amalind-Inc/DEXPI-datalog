from __future__ import annotations

import unittest

from pydexpi_datalog.validation_state import derive_validation_state


class ValidationStateTests(unittest.TestCase):
    def tagged_equipment_finding(self) -> dict[str, object]:
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

    def test_unresolved_remaining_findings_yield_needs_review_state(self) -> None:
        raw_finding = self.tagged_equipment_finding()

        result = derive_validation_state(
            raw_findings=[raw_finding],
            suppressed_findings=[raw_finding],
            suppression_records=[],
        )

        self.assertEqual(result.diagnostics, [])
        self.assertEqual(
            result.validation_states,
            [
                {
                    "affected_object_ids": ["P-101"],
                    "state": "needs_review",
                    "source_rule_ids": ["equipment-tag-present"],
                }
            ],
        )

    def test_conflicting_findings_yield_conflicted_state(self) -> None:
        first_finding = self.tagged_equipment_finding()
        second_finding = {
            "rule_id": "equipment-tag-missing",
            "severity": "hard violation",
            "affected_object_ids": ["P-101"],
            "evidence_trail": {
                "primary_rule": "equipment-tag-missing",
                "supporting_facts": [
                    {
                        "predicate": "missing_tag",
                        "object_id": "P-101",
                    }
                ],
            },
        }

        result = derive_validation_state(
            raw_findings=[first_finding, second_finding],
            suppressed_findings=[first_finding, second_finding],
            suppression_records=[],
        )

        self.assertEqual(result.diagnostics, [])
        self.assertEqual(
            result.validation_states,
            [
                {
                    "affected_object_ids": ["P-101"],
                    "state": "conflicted",
                    "source_rule_ids": [
                        "equipment-tag-missing",
                        "equipment-tag-present",
                    ],
                }
            ],
        )

    def test_validation_state_output_is_artifact_ready(self) -> None:
        raw_finding = self.tagged_equipment_finding()

        result = derive_validation_state(
            raw_findings=[raw_finding],
            suppressed_findings=[raw_finding],
            suppression_records=[],
        )

        self.assertEqual(
            result.validation_states,
            [
                {
                    "affected_object_ids": ["P-101"],
                    "state": "needs_review",
                    "source_rule_ids": ["equipment-tag-present"],
                }
            ],
        )
        self.assertEqual(
            {
                "validation_state": result.validation_states,
                "diagnostics": result.diagnostics,
            },
            {
                "validation_state": [
                    {
                        "affected_object_ids": ["P-101"],
                        "state": "needs_review",
                        "source_rule_ids": ["equipment-tag-present"],
                    }
                ],
                "diagnostics": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
