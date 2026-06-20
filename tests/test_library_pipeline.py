from __future__ import annotations

import json
from pathlib import Path
import unittest

import pydexpi_datalog


REPO_ROOT = Path(__file__).resolve().parents[1]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)


class LibraryPipelineTests(unittest.TestCase):
    def load_e06_graph_facts(self) -> dict[str, object]:
        return json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))

    def test_public_library_derives_graph_semantics_from_base_facts(self) -> None:
        graph_facts = self.load_e06_graph_facts()

        datalog = pydexpi_datalog.derive_graph_semantics_datalog(graph_facts)

        self.assertIn(".decl node(id:symbol)", datalog)
        self.assertIn(".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)", datalog)
        self.assertIn(".decl reachable(source:symbol, target:symbol)", datalog)
        self.assertIn("candidate_topology_edge(source, target, attr_name) :-", datalog)

    def test_public_library_evaluates_rule_against_graph_facts(self) -> None:
        graph_facts = self.load_e06_graph_facts()

        result = pydexpi_datalog.evaluate_rule(
            graph_facts,
            rule_id="pump_discharge_check_valve",
        )

        self.assertEqual(result["rule_id"], "pump_discharge_check_valve")
        self.assertIn(result["result_type"], {"pass", "hard_violation"})
        self.assertIn("evidence", result)

    def test_public_library_exports_graph_mirrored_base_fact_artifact(self) -> None:
        class FakeGraph:
            def nodes(self, data: bool = False) -> list[tuple[str, dict[str, str]]]:
                if not data:
                    raise AssertionError("node attributes must be requested")
                return [("P-101", {"label": "CentrifugalPump", "tagName": "P-101"})]

            def edges(
                self, keys: bool = False, data: bool = False
            ) -> list[tuple[str, str, int, dict[str, str]]]:
                if not keys or not data:
                    raise AssertionError("edge keys and attributes must be requested")
                return [("P-101", "N-1", 0, {"label": "composition", "attr_name": "nozzles"})]

        graph_facts = pydexpi_datalog.build_base_fact_artifact(
            dexpi_xml_path=Path("plant.xml"),
            fixture_id="library-example",
            pydexpi_full_graph=FakeGraph(),
        )

        self.assertEqual(graph_facts["fixture_id"], "library-example")
        self.assertEqual(graph_facts["graph"], {"node_count": 1, "edge_count": 1})
        self.assertEqual(graph_facts["facts"]["nodes"][0]["node_id"], "P-101")


if __name__ == "__main__":
    unittest.main()
