"""Acceptance contract for bead pydexpi-datalog-1-2ki.4: C01 rendered as drawn.

Session preparation must emit a backend-owned schematic scene for
geometry-bearing sources, with object identities shared with the rest of the
topology view so a schematic object and its topology counterpart are the same
selectable identity.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from pydexpi_datalog.web.review_api import create_review_api_app

REPO_ROOT = Path(__file__).resolve().parents[2]
C01_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "C01 DEXPI Reference P&ID"
    / "C01V04-VER.EX01.xml"
)
E06_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)
C03_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "C03 Piping (Equinor)"
    / "C03V04-VER.EX02.xml"
)


class SchematicSceneApiTests(unittest.TestCase):
    def _prepare(self, client: TestClient, session_id: str, fixture: Path):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": fixture.name, "content": fixture.read_text(encoding="utf-8")},
        )

    def test_prepare_response_includes_c01_schematic_scene_as_drawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            response = self._prepare(client, "c01-schematic", C01_FIXTURE)
            self.assertEqual(response.status_code, 200)
            scene = response.json()["topology_view"]["schematic_scene"]
            self.assertIsNotNone(scene)
            self.assertGreater(len(scene["symbols"]), 10)
            self.assertGreater(len(scene["polylines"]), 0)
            self.assertGreater(len(scene["catalogue"]), 0)
            self.assertIsNotNone(scene["extent"])
            # File-shape symbols resolved first: every placed symbol's shape
            # name resolves against this file's own catalogue.
            shapes_used = {s["shape"] for s in scene["symbols"]}
            self.assertTrue(shapes_used.issubset(scene["catalogue"].keys()))

    def test_schematic_scene_object_identities_match_topology_graph_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare(client, "c01-identity", C01_FIXTURE)
            topology = client.get("/api/review/sessions/c01-identity/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            scene = body["schematic_scene"]
            self.assertIsNotNone(scene)
            graph_object_ids = {obj["id"] for obj in body["graph_objects"]}
            # Every scene symbol resolved to a topology id (id == topology_id
            # when resolved) must be clickable as the same graph object -- the
            # frontend reuses this identity for selection and "show connections".
            resolved_symbols = [s for s in scene["symbols"] if s["topology_id"] is not None]
            self.assertGreater(len(resolved_symbols), 0)
            for symbol in resolved_symbols:
                self.assertEqual(symbol["id"], symbol["topology_id"])
                self.assertIn(symbol["topology_id"], graph_object_ids)

    def test_schematic_scene_is_none_for_geometry_poor_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare(client, "e06-no-geometry", E06_FIXTURE)
            topology = client.get("/api/review/sessions/e06-no-geometry/topology")
            self.assertEqual(topology.status_code, 200)
            self.assertIsNone(topology.json()["schematic_scene"])


class GeometrySanityGateApiTests(unittest.TestCase):
    """Acceptance criteria for bead pydexpi-datalog-1-2ki.5: honest degradation."""

    def _prepare(self, client: TestClient, session_id: str, fixture: Path):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": fixture.name, "content": fixture.read_text(encoding="utf-8")},
        )

    def test_c01_passes_the_gate_and_is_disclosed_as_drawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare(client, "c01-gate-pass", C01_FIXTURE)
            topology = client.get("/api/review/sessions/c01-gate-pass/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            self.assertEqual(body["schematic_scene_kind"], "as-drawn")
            self.assertIsNotNone(body["schematic_scene"])
            report = body["geometry_report"]
            self.assertTrue(report["passed"])
            self.assertEqual(report["reasons"], [])

    def test_e06_fails_the_gate_and_degrades_to_auto_layout_with_typed_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare(client, "e06-gate-fail", E06_FIXTURE)
            topology = client.get("/api/review/sessions/e06-gate-fail/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            self.assertEqual(body["schematic_scene_kind"], "auto-layout")
            # Positions from source are never mixed with invented positions:
            # a gate failure drops the scene entirely rather than partially
            # disclosing it as drawn.
            self.assertIsNone(body["schematic_scene"])
            report = body["geometry_report"]
            self.assertFalse(report["passed"])
            self.assertGreater(len(report["reasons"]), 0)
            for reason in report["reasons"]:
                self.assertIn(
                    reason,
                    {"no_geometry_source", "degenerate_extent", "low_pipe_coverage", "unpositioned_equipment"},
                )
            # The E-series fixture still carries exact source connectivity
            # for the auto-layout view to lay out (bead AC).
            self.assertGreater(len(body["pid_view"]["units"]), 0)


class RoutedPipeApiTests(unittest.TestCase):
    """Acceptance criteria for bead pydexpi-datalog-1-2ki.6: per-pipe demotion."""

    def _prepare(self, client: TestClient, session_id: str, fixture: Path):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": fixture.name, "content": fixture.read_text(encoding="utf-8")},
        )

    def test_c03_stays_as_drawn_with_routed_runs_disclosed_as_typed_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare(client, "c03-routed", C03_FIXTURE)
            topology = client.get("/api/review/sessions/c03-routed/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            # Two of C03's five segments carry no CenterLine, but the drawing
            # as a whole still comfortably passes the gate -- this is a
            # per-pipe fallback, not a whole-scene degradation.
            self.assertEqual(body["schematic_scene_kind"], "as-drawn")
            scene = body["schematic_scene"]
            self.assertIsNotNone(scene)

            routed = [p for p in scene["polylines"] if p.get("inferred")]
            drawn = [p for p in scene["polylines"] if p["kind"] == "pipe" and not p.get("inferred")]
            self.assertEqual(len(routed), 2)
            self.assertGreater(len(drawn), 0)
            for polyline in routed:
                # Real endpoints, not a re-layout: exactly two points.
                self.assertEqual(len(polyline["points"]), 2)

            diagnostics = body["geometry_report"]["routed_pipe_runs"]
            self.assertEqual(len(diagnostics), 2)
            for diagnostic in diagnostics:
                self.assertEqual(diagnostic["reason"], "missing_centerline")


if __name__ == "__main__":
    unittest.main()
