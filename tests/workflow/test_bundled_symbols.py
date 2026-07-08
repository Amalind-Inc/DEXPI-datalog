"""Corpus-coverage contract for bead pydexpi-datalog-1-2ki.15.

Every equipment `ComponentClass` that appears anywhere in the supported
fixture corpus must resolve to a bundled symbol, not a generic placeholder,
whenever the source itself carries no shape for it.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydexpi_datalog.export.pipeline import export_graph_facts_artifact, fixture_id_from_path
from pydexpi_datalog.workflow.bundled_symbols import BUNDLED_SYMBOLS

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids"


class BundledSymbolCorpusCoverageTests(unittest.TestCase):
    def test_every_equipment_class_in_the_corpus_has_a_bundled_symbol(self) -> None:
        missing: set[str] = set()
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            for xml_path in sorted(FIXTURE_ROOT.glob("**/*.xml")):
                relative_path = xml_path.relative_to(FIXTURE_ROOT)
                fixture_id = fixture_id_from_path(relative_path)
                artifact = export_graph_facts_artifact(
                    dexpi_xml_path=xml_path,
                    fixture_id=fixture_id,
                    output_dir=output_dir,
                )
                for node in artifact["facts"]["nodes"]:
                    attrs = node["attributes"]
                    # Mirrors topology_naming._category: a tagged node is "equipment".
                    if not attrs.get("tagName"):
                        continue
                    class_name = str(attrs.get("label", ""))
                    if class_name and class_name not in BUNDLED_SYMBOLS:
                        missing.add(class_name)
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
