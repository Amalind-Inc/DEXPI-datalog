"""The topology panel and search must present engineer-facing identifiers.

Boundary: prepare the real E06 source and read the panel + find_equipment, then
assert objects carry tags/lines/qualified nozzle names rather than opaque ids or
bare class names ("PipingNode").
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.web.chainlit_review_flow import ChainlitReviewFlow


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class TopologyPanelLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.flow = ChainlitReviewFlow(store=LocalArtifactStore(Path(self.tmp) / "sessions"))
        self.session_id = "label-session"
        self.flow.prepare_upload(dexpi_xml_path=E06_FIXTURE, session_id=self.session_id)

    def _panel_node_labels(self) -> list[str]:
        panel = self.flow.topology_panel_state(session_id=self.session_id)
        return [
            obj["label"] for obj in panel["graph_objects"] if obj["kind"] == "node"
        ]

    def test_panel_shows_equipment_tags_and_line_numbers(self) -> None:
        labels = self._panel_node_labels()
        self.assertIn("P-4713", labels)
        self.assertIn("H-1009", labels)
        self.assertIn("Line 47132", labels)

    def test_panel_qualifies_nozzles_by_their_equipment(self) -> None:
        labels = self._panel_node_labels()
        # Both the pump and the exchanger have an N-1; each is disambiguated.
        self.assertIn("P-4713 / N-1", labels)
        self.assertIn("H-1009 / N-1", labels)

    def test_panel_does_not_show_bare_opaque_ids_for_tagged_equipment(self) -> None:
        labels = self._panel_node_labels()
        # No tagged-equipment label should be a raw node-<hash> id.
        self.assertFalse(any(label.startswith("node-") for label in labels))

    def test_panel_objects_carry_category_and_description(self) -> None:
        panel = self.flow.topology_panel_state(session_id=self.session_id)
        pump = next(o for o in panel["graph_objects"] if o.get("label") == "P-4713")
        self.assertEqual(pump["category"], "equipment")
        self.assertIn("pump", pump["description"].lower())

    def test_search_lists_process_equipment_before_connection_nodes(self) -> None:
        topology = self.flow._topology_for_session(self.session_id)
        tools = TopologyTools(topology_view=topology, session_id=self.session_id)
        matches = tools.execute("find_equipment", {"pattern": ""})["matches"]
        categories = [m["category"] for m in matches]
        first_connection = next(
            (i for i, c in enumerate(categories) if c == "connection"), len(categories)
        )
        last_equipment = max(
            (i for i, c in enumerate(categories) if c == "equipment"), default=-1
        )
        self.assertLess(last_equipment, first_connection)


if __name__ == "__main__":
    unittest.main()
