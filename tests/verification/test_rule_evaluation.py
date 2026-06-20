from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydexpi_datalog._legacy.xml_normalization import build_legacy_xml_normalization
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


class RuleEvaluationTests(unittest.TestCase):
    def test_loads_valid_rule_pack_with_core_predicates(self) -> None:
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
            result = evaluate_rule_pack(rule_pack_path, normalization_result)

            self.assertEqual(result.diagnostics, [])
            self.assertEqual(result.findings[0]["rule_id"], "equipment-tag-present")

    def test_emits_one_raw_finding_for_matching_rule(self) -> None:
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
            result = evaluate_rule_pack(rule_pack_path, normalization_result)

            self.assertEqual(result.diagnostics, [])
            self.assertEqual(len(result.findings), 1)
            self.assertEqual(result.findings[0]["rule_id"], "equipment-tag-present")
            self.assertEqual(result.findings[0]["severity"], "informational")

    def test_finding_is_scoped_to_affected_object_ids_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' />"
                    "<Equipment id='P-102' />"
                    "<Line id='L-1' tag='L-1' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )
            rule_pack_path = tmp_path / "rule_pack.json"
            write_rule_pack(rule_pack_path)

            normalization_result = build_legacy_xml_normalization(source_path)
            result = evaluate_rule_pack(rule_pack_path, normalization_result)

            self.assertEqual(
                [finding["affected_object_ids"] for finding in result.findings],
                [["L-1"], ["P-101"], ["P-102"]],
            )

    def test_finding_includes_rule_hit_and_supporting_facts(self) -> None:
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
            result = evaluate_rule_pack(rule_pack_path, normalization_result)

            finding = result.findings[0]
            self.assertEqual(
                finding["evidence_trail"],
                {
                    "primary_rule": "equipment-tag-present",
                    "supporting_facts": [
                        {
                            "predicate": "has_tag",
                            "object_id": "P-101",
                            "normalized_tag": "P-101",
                        }
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
