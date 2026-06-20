from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydexpi_datalog.legacy_xml_normalization import build_legacy_xml_normalization


class LegacyXmlNormalizationTests(unittest.TestCase):
    def test_builds_normalized_objects_from_one_dexpi_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' componentClass='Pump' />"
                    "<Line id='L-1' tag='L-1' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )

            result = build_legacy_xml_normalization(source_path)

            self.assertEqual(result.diagnostics, [])
            self.assertEqual(
                [obj.object_id for obj in result.normalized_objects],
                ["L-1", "P-101"],
            )
            self.assertEqual(
                [obj.normalized_tag for obj in result.normalized_objects],
                ["L-1", "P-101"],
            )
            self.assertEqual(
                result.normalized_objects[1].source_attributes["componentClass"],
                "Pump",
            )

    def test_preserves_raw_tag_variants_for_each_normalized_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' tag_variant_1='P101' tag_variant_2='P-0101' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )

            result = build_legacy_xml_normalization(source_path)

            self.assertEqual(result.normalized_objects[0].normalized_tag, "P-101")
            self.assertEqual(
                result.raw_tag_variants["P-101"],
                ["P-101", "P101", "P-0101"],
            )

    def test_records_diagnostic_when_tag_normalization_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "plant.xml"
            source_path.write_text(
                (
                    "<PlantModel>"
                    "<Equipment id='P-101' tag='P-101' tag_variant_1='P101' />"
                    "</PlantModel>"
                ),
                encoding="utf-8",
            )

            result = build_legacy_xml_normalization(source_path)

            self.assertEqual(result.normalized_objects[0].normalized_tag, "P-101")
            self.assertEqual(len(result.diagnostics), 1)
            self.assertEqual(
                result.diagnostics[0]["code"],
                "normalizer.ambiguous_normalized_tag",
            )
            self.assertEqual(len(result.normalized_objects[0].diagnostics), 1)
            self.assertEqual(
                result.normalized_objects[0].diagnostics[0]["code"],
                "normalizer.ambiguous_normalized_tag",
            )


if __name__ == "__main__":
    unittest.main()
