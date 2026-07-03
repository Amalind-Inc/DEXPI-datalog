"""Behavioral contracts for building a tier-1 schematic scene from Proteus geometry.

A geometry-bearing DEXPI/Proteus export carries a shape catalogue, as-drawn
positions, and drawn centerlines. This module must reproduce that drawing
faithfully (ADR 0004) as a backend-owned scene (ADR 0005), keyed to the same
stable topology ids the rest of the review workflow uses so a schematic
object and its topology counterpart are the same identity.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydexpi_datalog.workflow.schematic_scene import build_schematic_scene

REPO_ROOT = Path(__file__).resolve().parents[2]
C01_FIXTURE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "C01 DEXPI Reference P&ID"
    / "C01V04-VER.EX01.xml"
)

_MINIMAL_PROTEUS = """<?xml version="1.0" encoding="UTF-8"?>
<PlantModel>
  <PlantInformation Units="mm"/>
  <ShapeCatalogue>
    <PlantItemShape ComponentName="PUMP_SHAPE" ComponentClass="CentrifugalPump">
      <PolyLine>
        <Presentation R="0.2" G="0.2" B="0.2" LineWeight="0.25" LineType="0"/>
        <Coordinate X="0" Y="0"/>
        <Coordinate X="10" Y="0"/>
      </PolyLine>
    </PlantItemShape>
  </ShapeCatalogue>
  <Drawing>
    <Extent>
      <Min X="0" Y="0"/>
      <Max X="420" Y="297"/>
    </Extent>
    <PolyLine>
      <Presentation R="0.6" G="0.6" B="0.6" LineWeight="0.5" LineType="0"/>
      <Coordinate X="0" Y="0"/>
      <Coordinate X="420" Y="0"/>
      <Coordinate X="420" Y="297"/>
      <Coordinate X="0" Y="297"/>
      <Coordinate X="0" Y="0"/>
    </PolyLine>
  </Drawing>
  <Equipment ComponentClass="CentrifugalPump" ComponentName="PUMP_SHAPE" ID="Equipment-1">
    <Position>
      <Location X="50" Y="60"/>
      <Reference X="1" Y="0"/>
      <Axis X="0" Y="0" Z="1"/>
    </Position>
  </Equipment>
  <PipingNetworkSystem ID="System-1">
    <PipingNetworkSegment ID="Segment-1">
      <CenterLine>
        <Presentation R="0" G="0" B="0" LineWeight="0.3" LineType="0"/>
        <Coordinate X="50" Y="60"/>
        <Coordinate X="120" Y="60"/>
      </CenterLine>
      <Text String="Line 1001" Height="3" TextAngle="90" Font="Calibri">
        <Position>
          <Location X="85" Y="60"/>
          <Reference X="1" Y="0"/>
        </Position>
      </Text>
    </PipingNetworkSegment>
  </PipingNetworkSystem>
</PlantModel>
"""

_NO_GEOMETRY_PROTEUS = """<?xml version="1.0" encoding="UTF-8"?>
<PlantModel>
  <PlantInformation Units="mm"/>
  <Equipment ComponentClass="CentrifugalPump" ID="Equipment-1"/>
</PlantModel>
"""


def _write(tmp_dir: Path, content: str) -> Path:
    path = tmp_dir / "source.xml"
    path.write_text(content, encoding="utf-8")
    return path


class BuildSchematicSceneTests(unittest.TestCase):
    def test_returns_none_when_source_carries_no_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _NO_GEOMETRY_PROTEUS)
            scene = build_schematic_scene(
                dexpi_xml_path=path, proteus_id_to_topology_id={}, namespace="ns"
            )
        self.assertIsNone(scene)

    def test_symbol_placed_as_drawn_and_linked_to_topology_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _MINIMAL_PROTEUS)
            scene = build_schematic_scene(
                dexpi_xml_path=path,
                proteus_id_to_topology_id={"Equipment-1": "topo-pump"},
                namespace="ns",
            )
        assert scene is not None
        self.assertEqual(scene["units"], "mm")
        self.assertEqual(scene["extent"], {"x0": 0.0, "y0": 0.0, "x1": 420.0, "y1": 297.0})
        self.assertIn("PUMP_SHAPE", scene["catalogue"])
        [symbol] = scene["symbols"]
        self.assertEqual(symbol["id"], "topo-pump")
        self.assertEqual(symbol["topology_id"], "topo-pump")
        self.assertEqual((symbol["tx"], symbol["ty"]), (50.0, 60.0))
        self.assertEqual(symbol["shape"], "PUMP_SHAPE")

    def test_pipe_centerline_uses_segment_topology_id_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _MINIMAL_PROTEUS)
            scene = build_schematic_scene(
                dexpi_xml_path=path,
                proteus_id_to_topology_id={"Segment-1": "topo-seg"},
                namespace="ns",
            )
        assert scene is not None
        [line] = [p for p in scene["polylines"] if p["kind"] == "pipe"]
        self.assertEqual(line["id"], "topo-seg")
        self.assertEqual(line["points"], [[50.0, 60.0], [120.0, 60.0]])

    def test_unmapped_element_falls_back_to_namespaced_id_not_raw_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _MINIMAL_PROTEUS)
            # No topology id map at all: nothing should collide on the raw
            # Proteus id, which can repeat across exports (1.2 HEX oddity).
            scene = build_schematic_scene(
                dexpi_xml_path=path, proteus_id_to_topology_id={}, namespace="src-abc"
            )
        assert scene is not None
        [symbol] = scene["symbols"]
        self.assertEqual(symbol["id"], "src-abc:Equipment-1")
        self.assertIsNone(symbol["topology_id"])

    def test_text_angle_is_explicit_and_additive_not_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _MINIMAL_PROTEUS)
            scene = build_schematic_scene(
                dexpi_xml_path=path, proteus_id_to_topology_id={}, namespace="ns"
            )
        assert scene is not None
        [text] = scene["texts"]
        self.assertEqual(text["string"], "Line 1001")
        # Position/Reference angle (0) + explicit TextAngle (90).
        self.assertEqual(text["angle"], 90.0)
        self.assertEqual(text["font"], "Calibri")

    def test_drawing_frame_is_a_frame_polyline_with_no_topology_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), _MINIMAL_PROTEUS)
            scene = build_schematic_scene(
                dexpi_xml_path=path, proteus_id_to_topology_id={}, namespace="ns"
            )
        assert scene is not None
        [frame] = [p for p in scene["polylines"] if p["kind"] == "frame"]
        self.assertIsNone(frame["topology_id"])
        self.assertEqual(len(frame["points"]), 5)


class BuildSchematicSceneC01Tests(unittest.TestCase):
    """Acceptance criteria for bead pydexpi-datalog-1-2ki.4: C01 as drawn."""

    def test_c01_renders_with_file_shape_symbols_and_as_drawn_placement(self) -> None:
        scene = build_schematic_scene(
            dexpi_xml_path=C01_FIXTURE,
            proteus_id_to_topology_id={},
            namespace="c01",
        )
        assert scene is not None
        self.assertGreater(len(scene["symbols"]), 10)
        self.assertGreater(len(scene["polylines"]), 0)
        self.assertGreater(len(scene["catalogue"]), 0)
        self.assertEqual(scene["units"], "mm")
        self.assertIsNotNone(scene["extent"])
        # Every symbol resolves against the file's own catalogue (file-shape
        # symbols resolved first, per the symbol resolution order).
        shapes_used = {s["shape"] for s in scene["symbols"]}
        self.assertTrue(shapes_used.issubset(scene["catalogue"].keys()))


if __name__ == "__main__":
    unittest.main()
