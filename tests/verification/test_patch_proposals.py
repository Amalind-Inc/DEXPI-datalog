from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydexpi_datalog._legacy.xml_normalization import build_legacy_xml_normalization
from pydexpi_datalog.verification.patch_proposals import generate_patch_proposals
from pydexpi_datalog.verification.rule_evaluation import evaluate_rule_pack


def write_rule_pack(rule_pack_path: Path) -> None:
    rule_pack_path.write_text(
        (
            "{"
            "\"rules\": ["
            "{"
            "\"rule_id\": \"equipment-tag-present\","
            "\"severity\": \"informational\","
            "\"conditions\": {"
            "\"all\": ["
            "{"
            "\"predicate\": \"has_tag\","
            "\"args\": {\"object_ref\": \"trigger\"}"
            "}"
            "]"
            "}"
            "}"
            "]"
            "}"
        ),
        encoding="utf-8",
    )


class PatchProposalTests(unittest.TestCase):
    def build_supported_patch_result(self) -> object:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            write_rule_pack(rule_pack_path)

            normalization_result = build_legacy_xml_normalization(source_path)
            evaluation_result = evaluate_rule_pack(rule_pack_path, normalization_result)
            return generate_patch_proposals(
                evaluation_result.findings, normalization_result
            )

    def test_generates_one_concrete_atomic_patch_proposal_for_supported_finding(
        self,
    ) -> None:
        patch_result = self.build_supported_patch_result()

        self.assertEqual(patch_result.diagnostics, [])
        self.assertEqual(
            patch_result.patch_proposals,
            [
                {
                    "finding_rule_id": "equipment-tag-present",
                    "affected_object_ids": ["P-101"],
                    "action": "modify_object",
                    "target_object_id": "P-101",
                    "changes": {
                        "review_status": "confirmed-tagged-equipment",
                    },
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
            ],
        )

    def test_patch_proposal_action_is_additive_or_modifying_not_deleting(self) -> None:
        patch_result = self.build_supported_patch_result()

        self.assertEqual(len(patch_result.patch_proposals), 1)
        self.assertIn(
            patch_result.patch_proposals[0]["action"],
            {"add_object", "add_connection", "modify_object", "modify_connection"},
        )
        self.assertNotEqual(
            patch_result.patch_proposals[0]["action"], "delete_object"
        )
        self.assertNotEqual(
            patch_result.patch_proposals[0]["action"], "delete_connection"
        )

    def test_ambiguous_case_emits_no_placeholder_patch_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                "<PlantModel><Equipment id='P-101' tag='P-101' /></PlantModel>",
                encoding="utf-8",
            )

            normalization_result = build_legacy_xml_normalization(source_path)
            ambiguous_finding = {
                "rule_id": "ambiguous-equipment-finding",
                "severity": "soft advisory",
                "affected_object_ids": ["P-101", "P-102"],
                "evidence_trail": {
                    "primary_rule": "ambiguous-equipment-finding",
                    "supporting_facts": [
                        {
                            "predicate": "has_tag",
                            "object_id": "P-101",
                            "normalized_tag": "P-101",
                        }
                    ],
                },
            }

            patch_result = generate_patch_proposals(
                [ambiguous_finding], normalization_result
            )

            self.assertEqual(patch_result.diagnostics, [])
            self.assertEqual(patch_result.patch_proposals, [])


if __name__ == "__main__":
    unittest.main()
