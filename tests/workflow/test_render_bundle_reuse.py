from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydexpi_datalog.workflow.artifact_store import LocalArtifactStore
from pydexpi_datalog.workflow.review_session import ReviewSessionService, session_artifact_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


class RenderBundleReuseTests(unittest.TestCase):
    def test_second_preparation_of_identical_source_skips_export_and_scene_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = LocalArtifactStore(Path(tmp_dir) / "artifacts")
            service = ReviewSessionService(store=store)
            with (
                patch(
                    "pydexpi_datalog.workflow.review_session.export_graph_facts_artifact_timed",
                    wraps=__import__(
                        "pydexpi_datalog.workflow.review_session", fromlist=["export_graph_facts_artifact_timed"]
                    ).export_graph_facts_artifact_timed,
                ) as export,
                patch(
                    "pydexpi_datalog.workflow.review_session.build_topology_view_model",
                    wraps=__import__(
                        "pydexpi_datalog.workflow.review_session", fromlist=["build_topology_view_model"]
                    ).build_topology_view_model,
                ) as build,
            ):
                first = service.start_preparation(dexpi_xml_path=E06_FIXTURE, session_id="first")
                second = service.start_preparation(dexpi_xml_path=E06_FIXTURE, session_id="second")

            self.assertEqual(first["readiness"]["state"], "ready")
            self.assertEqual(second["readiness"]["state"], "ready")
            # Cache reuse is allowed only if the new review retains the graph
            # facts and deterministic programs needed by later grounded turns.
            for key in session_artifact_keys("second").values():
                self.assertTrue(store.exists(key), key)
            self.assertEqual(export.call_count, 1)
            self.assertEqual(build.call_count, 1)


if __name__ == "__main__":
    unittest.main()
