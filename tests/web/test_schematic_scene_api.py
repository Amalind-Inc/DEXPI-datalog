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
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from pydexpi_datalog.web.review_api import create_review_api_app
from pydexpi_datalog.workflow.bundled_symbols import BUNDLED_SYMBOLS

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


def _c01_with_positions_stripped(equipment_ids: list[str]) -> str:
    """C01, minus the `<Position>` child of the named real (catalogue-shaped)
    equipment -- everything else about the file, including the strict Proteus
    schema it otherwise satisfies, is untouched.
    """
    tree = ET.parse(C01_FIXTURE)
    root = tree.getroot()
    for equipment in root.iter("Equipment"):
        if equipment.attrib.get("ID") in equipment_ids:
            position = equipment.find("Position")
            if position is not None:
                equipment.remove(position)
    return ET.tostring(root, encoding="unicode")


def _c01_with_first_n_positions_stripped(n: int) -> str:
    """C01, minus the `<Position>` child of the first `n` document-order
    elements that carry a `ComponentName` and their own `Position` -- covers
    the gate's unpositioned_equipment ratio across every positionable item in
    the file (nozzles, valves, instruments, ..., not just top-level
    equipment), since that ratio is over the whole population, not just the
    five named equipment bodies.
    """
    tree = ET.parse(C01_FIXTURE)
    root = tree.getroot()
    catalogue = root.find("ShapeCatalogue")
    catalogue_elements = set(id(el) for el in catalogue.iter()) if catalogue is not None else set()
    stripped = 0
    for el in root.iter():
        if stripped >= n:
            break
        if id(el) in catalogue_elements or not el.attrib.get("ComponentName"):
            continue
        position = el.find("Position")
        if position is None:
            continue
        el.remove(position)
        stripped += 1
    assert stripped == n, f"only stripped {stripped} of the requested {n} positions"
    return ET.tostring(root, encoding="unicode")


class ShelfApiTests(unittest.TestCase):
    """Acceptance criteria for bead pydexpi-datalog-1-2ki.7: unplaced-equipment shelf."""

    def _prepare_content(self, client: TestClient, session_id: str, filename: str, content: str):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": filename, "content": content},
        )

    def test_under_threshold_share_stays_as_drawn_with_shelf_diagnostics(self) -> None:
        # 1 of C01's 5 real equipment unplaced (20%) is exactly at the gate's
        # threshold, so the file still passes and the item is shelved rather
        # than dropped -- everything else in C01 stays exactly as drawn.
        content = _c01_with_positions_stripped(["Tank-1"])
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "shelf-under", "shelf-under.xml", content)
            topology = client.get("/api/review/sessions/shelf-under/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            self.assertEqual(body["schematic_scene_kind"], "as-drawn")
            scene = body["schematic_scene"]
            self.assertIsNotNone(scene)

            shelved = [s for s in scene["symbols"] if s["shelved"]]
            self.assertEqual(len(shelved), 1)
            self.assertEqual(shelved[0]["shape"], "VESSEL_WITH_DISHED_HEADS_SHAPE")

            diagnostics = body["geometry_report"]["shelved_equipment"]
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]["raw_id"], "Tank-1")
            self.assertEqual(diagnostics[0]["reason"], "missing_position")

    def test_over_threshold_share_demotes_the_whole_file_to_auto_layout(self) -> None:
        # C01 has 62 positionable (ComponentName-bearing) items; stripping 13
        # of their Positions (21%) clears the gate's 20% unplaced-equipment
        # threshold -- the shelf is a per-item disclosure inside tier-1, not
        # an escape from the whole-file gate.
        content = _c01_with_first_n_positions_stripped(13)
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "shelf-over", "shelf-over.xml", content)
            topology = client.get("/api/review/sessions/shelf-over/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            self.assertEqual(body["schematic_scene_kind"], "auto-layout")
            self.assertIsNone(body["schematic_scene"])
            report = body["geometry_report"]
            self.assertFalse(report["passed"])
            self.assertIn("unpositioned_equipment", report["reasons"])
            self.assertEqual(len(report["shelved_equipment"]), 13)


def _c01_with_catalogue_entry_removed(component_name: str, *, mangle_class_on: str | None = None) -> str:
    """C01, minus the `ShapeCatalogue` definition for `component_name` -- any
    real equipment referencing it by `ComponentName` now misses the file's own
    catalogue, forcing the bundled/generic fallback chain (bead 2ki.15).
    Optionally also mangles a named element's `ComponentClass` to a value no
    bundled entry recognizes, to force the generic-placeholder branch.
    """
    tree = ET.parse(C01_FIXTURE)
    root = tree.getroot()
    catalogue = root.find("ShapeCatalogue")
    for shape in list(catalogue):
        if shape.attrib.get("ComponentName") == component_name:
            catalogue.remove(shape)
    if mangle_class_on is not None:
        for el in root.iter():
            if el.attrib.get("ID") == mangle_class_on:
                el.set("ComponentClass", "UnknownWidgetClass")
    return ET.tostring(root, encoding="unicode")


def _e06_with_class_mangled(equipment_id: str) -> str:
    tree = ET.parse(E06_FIXTURE)
    root = tree.getroot()
    for el in root.iter():
        if el.attrib.get("ID") == equipment_id:
            el.set("ComponentClass", "UnknownWidgetClass")
    return ET.tostring(root, encoding="unicode")


class BundledSymbolResolutionApiTests(unittest.TestCase):
    """Acceptance criteria for bead pydexpi-datalog-1-2ki.15: bundled symbol
    library coverage and the file -> bundled -> generic resolution order,
    asserted at the TestClient seam for both tiers."""

    def _prepare_content(self, client: TestClient, session_id: str, filename: str, content: str):
        return client.post(
            f"/api/review/sessions/{session_id}/prepare",
            json={"filename": filename, "content": content},
        )

    def test_tier1_catalogue_miss_falls_back_to_a_bundled_symbol_for_a_known_class(self) -> None:
        # Tank-1 keeps its Position but loses its own catalogue shape
        # definition; its ComponentClass ("Tank") is still bundled, so it must
        # still be placed (not dropped) using the bundled shape, no diagnostic.
        content = _c01_with_catalogue_entry_removed("VESSEL_WITH_DISHED_HEADS_SHAPE")
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "bundled-fallback", "bundled-fallback.xml", content)
            topology = client.get("/api/review/sessions/bundled-fallback/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            self.assertEqual(body["schematic_scene_kind"], "as-drawn")
            scene = body["schematic_scene"]
            self.assertIsNotNone(scene)

            bundled_symbols = [s for s in scene["symbols"] if s["shape"] == "__bundled__:Tank"]
            self.assertEqual(len(bundled_symbols), 1)
            self.assertFalse(bundled_symbols[0]["shelved"])
            self.assertIn("__bundled__:Tank", scene["catalogue"])

            report = body["geometry_report"]
            self.assertEqual(report["items_with_bundled_shape"], 1)
            self.assertEqual(report["generic_placeholders"], [])

    def test_tier1_unknown_component_class_falls_back_to_generic_with_a_typed_diagnostic(self) -> None:
        content = _c01_with_catalogue_entry_removed(
            "VESSEL_WITH_DISHED_HEADS_SHAPE", mangle_class_on="Tank-1"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "generic-fallback", "generic-fallback.xml", content)
            topology = client.get("/api/review/sessions/generic-fallback/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            scene = body["schematic_scene"]
            self.assertIsNotNone(scene)

            generic_symbols = [s for s in scene["symbols"] if s["shape"] == "__generic__"]
            self.assertEqual(len(generic_symbols), 1)
            self.assertFalse(generic_symbols[0]["shelved"])

            diagnostics = body["geometry_report"]["generic_placeholders"]
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]["raw_id"], "Tank-1")
            self.assertEqual(diagnostics[0]["class_name"], "UnknownWidgetClass")
            self.assertEqual(diagnostics[0]["reason"], "unknown_component_class")

    def test_tier2_units_resolve_to_bundled_symbols_across_a_no_geometry_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "tier2-e06", "e06.xml", E06_FIXTURE.read_text(encoding="utf-8"))
            topology = client.get("/api/review/sessions/tier2-e06/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            units = body["pid_view"]["units"]
            self.assertGreater(len(units), 0)
            for unit in units:
                self.assertNotEqual(unit["symbol_key"], "generic")
            self.assertEqual(body["pid_view"]["symbol_report"]["generic_placeholders"], [])

    def test_tier2_unknown_component_class_resolves_to_generic_with_a_typed_diagnostic(self) -> None:
        content = _e06_with_class_mangled("CentrifugalPump-1")
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_review_api_app(artifact_root=Path(tmp_dir) / "sessions")
            client = TestClient(app)
            self._prepare_content(client, "tier2-generic", "e06-mangled.xml", content)
            topology = client.get("/api/review/sessions/tier2-generic/topology")
            self.assertEqual(topology.status_code, 200)
            body = topology.json()
            units = {u["label"]: u for u in body["pid_view"]["units"]}
            self.assertEqual(units["P-4713"]["symbol_key"], "generic")

            diagnostics = body["pid_view"]["symbol_report"]["generic_placeholders"]
            self.assertEqual(len(diagnostics), 1)
            # pydexpi maps an unrecognized ComponentClass to its own generic
            # model class rather than passing the mangled string through.
            self.assertNotIn(diagnostics[0]["class_name"], BUNDLED_SYMBOLS)
            self.assertEqual(diagnostics[0]["reason"], "unknown_component_class")


if __name__ == "__main__":
    unittest.main()
