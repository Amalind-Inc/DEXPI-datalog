from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
E03_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E03 Pump With Nozzles"
    / "E03V01-VER.EX01.xml"
)
GOLDEN_FACTS_DIR = REPO_ROOT / "testdata" / "graph_contract"
GOLDEN_MANIFEST_PATH = GOLDEN_FACTS_DIR / "manifest.json"
CORPUS_SUMMARY_PATH = GOLDEN_FACTS_DIR / "corpus" / "corpus_summary.json"
DEXPI_13_FIXTURE_ROOT = (
    REPO_ROOT / "TrainingTestCases" / "dexpi 1.3" / "example pids"
)


class ExportFactsCliTests(unittest.TestCase):
    def run_export_facts(
        self, fixture_path: Path, fixture_id: str, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "export-facts",
                str(fixture_path),
                "--fixture-id",
                fixture_id,
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def run_export_corpus(
        self, fixture_root: Path, output_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pydexpi_datalog",
                "export-corpus",
                str(fixture_root),
                "--output-dir",
                str(output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_export_facts_persists_graph_mirrored_base_facts_for_real_pump_fixture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "exported-facts"
            fixture_id = "e03-pump"
            artifact_path = output_dir / fixture_id / "graph_facts.json"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_export_facts(E03_FIXTURE, fixture_id, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(artifact_path.exists())

            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["fixture_id"], fixture_id)
            self.assertEqual(artifact["source_path"], str(E03_FIXTURE.resolve()))
            self.assertTrue(artifact["facts"]["nodes"])
            self.assertTrue(artifact["facts"]["edges"])

    def test_export_corpus_persists_parse_coverage_summary_for_dexpi_13_fixtures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "corpus-export"
            summary_path = output_dir / "corpus_summary.json"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_export_corpus(DEXPI_13_FIXTURE_ROOT, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(summary_path.exists())

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            xml_fixture_count = len(sorted(DEXPI_13_FIXTURE_ROOT.glob("**/*.xml")))
            self.assertEqual(summary["fixture_root"], str(DEXPI_13_FIXTURE_ROOT.resolve()))
            self.assertEqual(summary["totals"]["discovered"], xml_fixture_count)
            self.assertEqual(
                summary["totals"]["discovered"],
                summary["totals"]["parsed"]
                + summary["totals"]["failed"]
                + summary["totals"]["excluded"],
            )
            self.assertEqual(summary["excluded_fixtures"], [])

            fixtures_by_path = {
                fixture["relative_path"]: fixture for fixture in summary["fixtures"]
            }
            e03_summary = fixtures_by_path[
                "E03 Pump With Nozzles/E03V01-VER.EX01.xml"
            ]
            self.assertEqual(e03_summary["status"], "parsed")
            self.assertEqual(e03_summary["node_count"], 5)
            self.assertEqual(e03_summary["edge_count"], 4)

            artifact_path = output_dir / e03_summary["artifact_path"]
            self.assertTrue(artifact_path.exists(), artifact_path)

            attribute_coverage = summary["attribute_coverage"]
            self.assertIn(
                "nominalDiameterNumericalValueRepresentation",
                attribute_coverage["node_attribute_keys"],
            )
            self.assertIn("chamber", attribute_coverage["edge_attr_names"])
            self.assertEqual(attribute_coverage["base_fact_collections"], ["edges", "nodes"])
            self.assertNotIn("pump", attribute_coverage["base_fact_collections"])

    def test_export_facts_records_pinned_pydexpi_version_in_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "exported-facts"
            fixture_id = "e03-pump-versioned"
            artifact_path = output_dir / fixture_id / "graph_facts.json"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_export_facts(E03_FIXTURE, fixture_id, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["provenance"]["extractor_version"],
                "1.2.0",
            )

    def test_export_facts_preserves_selected_e03_graph_structure_one_to_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "exported-facts"
            fixture_id = "e03-pump-structure"
            artifact_path = output_dir / fixture_id / "graph_facts.json"
            self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

            result = self.run_export_facts(E03_FIXTURE, fixture_id, output_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

            pump_nodes = [
                node
                for node in artifact["facts"]["nodes"]
                if node["attributes"].get("label") == "CentrifugalPump"
            ]
            self.assertEqual(len(pump_nodes), 1)

            pump_node = pump_nodes[0]
            self.assertEqual(
                pump_node["attributes"].get("proteusId"),
                "CentrifugalPump-1",
            )
            self.assertEqual(
                pump_node["attributes"].get("tagName"),
                "P-4713",
            )

            nozzle_edges = [
                edge
                for edge in artifact["facts"]["edges"]
                if edge["source_id"] == pump_node["node_id"]
                and edge["attributes"].get("label") == "composition"
                and edge["attributes"].get("attr_name") == "nozzles"
            ]
            self.assertEqual(len(nozzle_edges), 1)

    def test_repo_persists_golden_fact_outputs_for_multiple_real_pump_fixtures(self) -> None:
        fixture_ids = ["e03-pump", "e06-pump-hex", "c01-reference-pid"]

        for fixture_id in fixture_ids:
            with self.subTest(fixture_id=fixture_id):
                artifact_path = GOLDEN_FACTS_DIR / fixture_id / "graph_facts.json"
                self.assertTrue(artifact_path.exists(), artifact_path)

                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                self.assertEqual(artifact["fixture_id"], fixture_id)
                self.assertTrue(artifact["facts"]["nodes"])
                self.assertTrue(artifact["facts"]["edges"])

    def test_repo_persists_fixture_manifest_with_expected_graph_sizes(self) -> None:
        self.assertTrue(GOLDEN_MANIFEST_PATH.exists(), GOLDEN_MANIFEST_PATH)

        manifest = json.loads(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["extractor"],
            {
                "name": "pyDEXPI",
                "version": "1.2.0",
                "git_commit": "83e5a11c4af3635ad12290a4dbe310480eb6d7a3",
                "git_remote": "https://github.com/process-intelligence-research/pyDEXPI.git",
            },
        )
        self.assertEqual(
            manifest["fixtures"],
            [
                {
                    "fixture_id": "e03-pump",
                    "node_count": 5,
                    "edge_count": 4,
                },
                {
                    "fixture_id": "e06-pump-hex",
                    "node_count": 18,
                    "edge_count": 21,
                },
                {
                    "fixture_id": "c01-reference-pid",
                    "node_count": 214,
                    "edge_count": 376,
                },
            ],
        )

    def test_repo_persists_dexpi_13_corpus_coverage_summary(self) -> None:
        self.assertTrue(CORPUS_SUMMARY_PATH.exists(), CORPUS_SUMMARY_PATH)

        summary = json.loads(CORPUS_SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            summary["fixture_root"],
            "TrainingTestCases/dexpi 1.3/example pids",
        )
        self.assertEqual(
            summary["totals"],
            {
                "discovered": 35,
                "parsed": 35,
                "failed": 0,
                "excluded": 0,
            },
        )
        self.assertEqual(summary["excluded_fixtures"], [])
        self.assertIn(
            "nominalDiameterNumericalValueRepresentation",
            summary["attribute_coverage"]["node_attribute_keys"],
        )
        self.assertIn("chamber", summary["attribute_coverage"]["edge_attr_names"])
        self.assertEqual(
            summary["attribute_coverage"]["base_fact_collections"],
            ["edges", "nodes"],
        )


if __name__ == "__main__":
    unittest.main()
