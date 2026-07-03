"""Geometry sanity gate (bead pydexpi-datalog-1-2ki.5).

Decides whether a schematic scene's source geometry is trustworthy enough to
present as drawn (ADR 0004), or must degrade to an auto-layout schematic
view. Thresholds are calibrated against the full 150-fixture survey in the
renderer spike (prototypes/renderer_spike/NOTES.md section 4): real drawings
and pedagogical (geometry-free) fixtures are cleanly bimodal on every metric,
so the exact threshold choice is not sensitive.

The gate outcome is computed here, backend-side, and is the sole authority
for whether a scene is disclosed as "as drawn" -- even when auto-layout
position computation itself later executes client-side (ADR 0005's tolerated
exception), the decision to auto-layout is made in this module.
"""
from __future__ import annotations

_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}

_MIN_EXTENT_MM = 10.0
_MIN_PIPE_COVERAGE = 0.5
_MAX_UNPOSITIONED_SHARE = 0.20


def evaluate_geometry_gate(scene: dict[str, object] | None) -> dict[str, object]:
    """Evaluate the sanity gate against a raw scene (see `build_schematic_scene_report`).

    `scene` may be None when the source carries no DEXPI geometry export at
    all, which trivially fails every metric.
    """
    if scene is None:
        return {
            "passed": False,
            "extent": {"passed": False, "width_mm": 0.0, "height_mm": 0.0},
            "pipe_coverage": {
                "passed": True,
                "ratio": None,
                "segments": 0,
                "segments_with_centerline": 0,
            },
            "unpositioned_equipment": {
                "passed": True,
                "ratio": None,
                "total": 0,
                "missing": 0,
            },
            "reasons": ["no_geometry_source"],
        }

    factor = _UNIT_TO_MM.get(str(scene.get("units", "mm")), 1.0)
    extent = scene.get("extent")
    if isinstance(extent, dict):
        width_mm = abs(float(extent["x1"]) - float(extent["x0"])) * factor
        height_mm = abs(float(extent["y1"]) - float(extent["y0"])) * factor
    else:
        width_mm = height_mm = 0.0
    extent_passed = width_mm >= _MIN_EXTENT_MM and height_mm >= _MIN_EXTENT_MM

    report = scene.get("report", {})
    assert isinstance(report, dict)
    segments = int(report.get("segments", 0))
    segments_with_centerline = int(report.get("segments_with_centerline", 0))
    if segments == 0:
        coverage_ratio = None
        coverage_passed = True  # vacuously true: nothing to route
    else:
        coverage_ratio = segments_with_centerline / segments
        coverage_passed = coverage_ratio >= _MIN_PIPE_COVERAGE

    items_with_shape = int(report.get("items_with_shape", 0))
    items_missing_position = int(report.get("items_missing_position", 0))
    total_positionable = items_with_shape + items_missing_position
    if total_positionable == 0:
        unpositioned_ratio = None
        unpositioned_passed = True  # vacuously true: no equipment to place
    else:
        unpositioned_ratio = items_missing_position / total_positionable
        unpositioned_passed = unpositioned_ratio <= _MAX_UNPOSITIONED_SHARE

    reasons = []
    if not extent_passed:
        reasons.append("degenerate_extent")
    if not coverage_passed:
        reasons.append("low_pipe_coverage")
    if not unpositioned_passed:
        reasons.append("unpositioned_equipment")

    return {
        "passed": extent_passed and coverage_passed and unpositioned_passed,
        "extent": {"passed": extent_passed, "width_mm": width_mm, "height_mm": height_mm},
        "pipe_coverage": {
            "passed": coverage_passed,
            "ratio": coverage_ratio,
            "segments": segments,
            "segments_with_centerline": segments_with_centerline,
        },
        "unpositioned_equipment": {
            "passed": unpositioned_passed,
            "ratio": unpositioned_ratio,
            "total": total_positionable,
            "missing": items_missing_position,
        },
        "reasons": reasons,
    }
