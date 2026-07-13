from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from networkx.readwrite import json_graph

import pydexpi_datalog


REPO_ROOT = Path(__file__).resolve().parents[2]
E03_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E03 Pump With Nozzles"
    / "E03V01-VER.EX01.xml"
)
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class DrawingBundleTests(unittest.TestCase):
    @unittest.skipUnless(
        E03_FIXTURE.is_file(),
        "TrainingTestCases is an external fixture corpus and is not checked in",
    )
    def test_bundle_contains_source_facts_networkx_export_and_agent_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "bundles"
            fixture_id = "e03-pump"

            pydexpi_datalog.export_drawing_bundle(
                dexpi_xml_path=E03_FIXTURE,
                fixture_id=fixture_id,
                output_dir=output_dir,
            )

            bundle_dir = output_dir / fixture_id
            source_path = bundle_dir / "drawing.xml"
            facts_path = bundle_dir / "graph_facts.json"
            networkx_path = bundle_dir / "graph.json"
            readme_path = bundle_dir / "README.md"

            self.assertEqual(source_path.read_bytes(), E03_FIXTURE.read_bytes())
            self.assertTrue(facts_path.is_file())
            self.assertTrue(networkx_path.is_file())
            self.assertTrue(readme_path.is_file())

            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            self.assertEqual(facts["source_path"], "drawing.xml")
            self.assertEqual(
                facts["graph"],
                {
                    "node_count": len(facts["facts"]["nodes"]),
                    "edge_count": len(facts["facts"]["edges"]),
                },
            )

            graph = json_graph.node_link_graph(
                json.loads(networkx_path.read_text(encoding="utf-8")),
                directed=True,
                multigraph=True,
            )
            self.assertEqual(
                set(graph.nodes),
                {node["node_id"] for node in facts["facts"]["nodes"]},
            )
            self.assertEqual(
                {
                    (source, target, key)
                    for source, target, key in graph.edges(keys=True)
                },
                {
                    (edge["source_id"], edge["target_id"], edge["edge_key"])
                    for edge in facts["facts"]["edges"]
                },
            )

            readme = readme_path.read_text(encoding="utf-8")
            for expected_term in (
                "drawing.xml",
                "graph_facts.json",
                "graph.json",
                "node_id",
                "source_id",
                "target_id",
                "edge_key",
            ):
                self.assertIn(expected_term, readme)

    @unittest.skipUnless(
        E06_FIXTURE.is_file(),
        "TrainingTestCases is an external fixture corpus and is not checked in",
    )
    def test_bundle_builds_from_the_e06_pump_heat_exchanger_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = pydexpi_datalog.export_drawing_bundle(
                dexpi_xml_path=E06_FIXTURE,
                fixture_id="e06-pump-hex",
                output_dir=Path(tmp_dir),
            )

            self.assertEqual(
                bundle["graph"],
                {"node_count": 18, "edge_count": 21},
            )
            self.assertEqual(
                bundle["files"]["drawing"].read_bytes(),
                E06_FIXTURE.read_bytes(),
            )

    def test_bundle_rejects_missing_drawing_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "bundles"
            missing_source = Path(tmp_dir) / "missing.xml"

            with self.assertRaisesRegex(
                FileNotFoundError, "DEXPI drawing does not exist"
            ):
                pydexpi_datalog.export_drawing_bundle(
                    dexpi_xml_path=missing_source,
                    fixture_id="missing",
                    output_dir=output_dir,
                )

            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
