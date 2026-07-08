"""Behavioral contracts for the geometry sanity gate (bead pydexpi-datalog-1-2ki.5).

Thresholds are calibrated in prototypes/renderer_spike/NOTES.md section 4:
degenerate extent (<10mm either dimension), pipe coverage (<50% of segments
carry a centerline), and unpositioned equipment (>20% of positionable items
lack a Position) each independently fail the gate.
"""
from __future__ import annotations

import unittest

from pydexpi_datalog.workflow.geometry_gate import evaluate_geometry_gate


def _scene(
    *,
    extent,
    units="mm",
    segments=0,
    segments_with_centerline=0,
    items_with_shape=0,
    items_missing_position=0,
    routed_pipe_runs=None,
    shelved_equipment=None,
):
    return {
        "units": units,
        "extent": extent,
        "report": {
            "items_with_shape": items_with_shape,
            "items_missing_shape": 0,
            "items_missing_position": items_missing_position,
            "segments": segments,
            "segments_with_centerline": segments_with_centerline,
            "routed_pipe_runs": routed_pipe_runs or [],
            "shelved_equipment": shelved_equipment or [],
        },
    }


class GeometryGateTests(unittest.TestCase):
    def test_none_scene_fails_with_no_geometry_source_reason(self) -> None:
        report = evaluate_geometry_gate(None)
        self.assertFalse(report["passed"])
        self.assertEqual(report["reasons"], ["no_geometry_source"])

    def test_healthy_drawing_passes_all_three_metrics(self) -> None:
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            segments=10,
            segments_with_centerline=8,
            items_with_shape=20,
            items_missing_position=0,
        )
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["passed"])
        self.assertEqual(report["reasons"], [])
        self.assertTrue(report["extent"]["passed"])
        self.assertTrue(report["pipe_coverage"]["passed"])
        self.assertTrue(report["unpositioned_equipment"]["passed"])

    def test_degenerate_extent_fails_extent_metric(self) -> None:
        scene = _scene(extent={"x0": 0, "y0": 0, "x1": 1e-15, "y1": 1e-15}, segments=0)
        report = evaluate_geometry_gate(scene)
        self.assertFalse(report["passed"])
        self.assertIn("degenerate_extent", report["reasons"])

    def test_missing_extent_fails_extent_metric(self) -> None:
        scene = _scene(extent=None)
        report = evaluate_geometry_gate(scene)
        self.assertFalse(report["extent"]["passed"])

    def test_low_pipe_coverage_fails_that_metric(self) -> None:
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            segments=10,
            segments_with_centerline=3,
            items_with_shape=5,
        )
        report = evaluate_geometry_gate(scene)
        self.assertFalse(report["passed"])
        self.assertIn("low_pipe_coverage", report["reasons"])
        self.assertEqual(report["pipe_coverage"]["ratio"], 0.3)

    def test_zero_segments_is_vacuously_true_for_coverage(self) -> None:
        scene = _scene(extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297}, segments=0)
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["pipe_coverage"]["passed"])
        self.assertIsNone(report["pipe_coverage"]["ratio"])

    def test_unpositioned_equipment_over_threshold_fails_that_metric(self) -> None:
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            items_with_shape=5,
            items_missing_position=5,
        )
        report = evaluate_geometry_gate(scene)
        self.assertFalse(report["passed"])
        self.assertIn("unpositioned_equipment", report["reasons"])
        self.assertEqual(report["unpositioned_equipment"]["ratio"], 0.5)

    def test_no_positionable_equipment_is_vacuously_true(self) -> None:
        scene = _scene(extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297})
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["unpositioned_equipment"]["passed"])
        self.assertIsNone(report["unpositioned_equipment"]["ratio"])

    def test_units_in_meters_normalized_before_extent_threshold(self) -> None:
        # 0.02 m x 0.02 m = 20mm x 20mm -- passes; a naive mm comparison would fail.
        scene = _scene(extent={"x0": 0, "y0": 0, "x1": 0.02, "y1": 0.02}, units="m")
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["extent"]["passed"])
        self.assertEqual(report["extent"]["width_mm"], 20.0)

    def test_none_scene_reports_no_routed_pipe_runs(self) -> None:
        report = evaluate_geometry_gate(None)
        self.assertEqual(report["routed_pipe_runs"], [])

    def test_none_scene_reports_no_shelved_equipment(self) -> None:
        report = evaluate_geometry_gate(None)
        self.assertEqual(report["shelved_equipment"], [])

    def test_shelved_equipment_passes_through_when_under_threshold(self) -> None:
        # One shelved item out of five positionable equipment (20% share) is
        # exactly at the threshold, still passing -- the shelf, not a gate
        # failure, is how a low unplaced share is disclosed.
        entries = [{"topology_id": "topo-valve", "raw_id": "Equipment-2", "reason": "missing_position"}]
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            items_with_shape=4,
            items_missing_position=1,
            shelved_equipment=entries,
        )
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["passed"])
        self.assertEqual(report["shelved_equipment"], entries)

    def test_shelved_equipment_over_threshold_still_demotes_the_gate(self) -> None:
        # Shelving is per-item disclosure, not an escape hatch from the
        # whole-file threshold: once unplaced share exceeds 20%, the file
        # still demotes to auto-layout.
        entries = [
            {"topology_id": "topo-1", "raw_id": "Equipment-1", "reason": "missing_position"},
            {"topology_id": "topo-2", "raw_id": "Equipment-2", "reason": "missing_position"},
        ]
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            items_with_shape=3,
            items_missing_position=2,
            shelved_equipment=entries,
        )
        report = evaluate_geometry_gate(scene)
        self.assertFalse(report["passed"])
        self.assertIn("unpositioned_equipment", report["reasons"])
        self.assertEqual(report["shelved_equipment"], entries)

    def test_routed_pipe_runs_pass_through_independent_of_gate_outcome(self) -> None:
        # Per-pipe demotion (bead 2ki.6) is orthogonal to the gate's pass/fail --
        # a healthy drawing can still carry a routed run, and the report
        # discloses it either way.
        runs = [{"topology_id": "topo-seg", "raw_id": "Segment-2", "reason": "missing_centerline"}]
        scene = _scene(
            extent={"x0": 0, "y0": 0, "x1": 420, "y1": 297},
            segments=10,
            segments_with_centerline=8,
            routed_pipe_runs=runs,
        )
        report = evaluate_geometry_gate(scene)
        self.assertTrue(report["passed"])
        self.assertEqual(report["routed_pipe_runs"], runs)


if __name__ == "__main__":
    unittest.main()
