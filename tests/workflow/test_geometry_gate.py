"""Behavioral contracts for the geometry sanity gate (bead pydexpi-datalog-1-2ki.5).

Thresholds are calibrated in prototypes/renderer_spike/NOTES.md section 4:
degenerate extent (<10mm either dimension), pipe coverage (<50% of segments
carry a centerline), and unpositioned equipment (>20% of positionable items
lack a Position) each independently fail the gate.
"""
from __future__ import annotations

import unittest

from pydexpi_datalog.workflow.geometry_gate import evaluate_geometry_gate


def _scene(*, extent, units="mm", segments=0, segments_with_centerline=0, items_with_shape=0, items_missing_position=0):
    return {
        "units": units,
        "extent": extent,
        "report": {
            "items_with_shape": items_with_shape,
            "items_missing_shape": 0,
            "items_missing_position": items_missing_position,
            "segments": segments,
            "segments_with_centerline": segments_with_centerline,
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


if __name__ == "__main__":
    unittest.main()
