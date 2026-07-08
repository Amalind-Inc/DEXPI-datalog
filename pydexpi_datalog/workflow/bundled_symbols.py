"""Bundled ISO-10628-styled symbols, keyed by raw DEXPI `ComponentClass`.

Canonical fallback source for symbol resolution (bead pydexpi-datalog-1-2ki.15):
when a plant item's own file-authored `ShapeCatalogue` has no entry for it
(tier-1, `schematic_scene.py`) or no source geometry exists at all (tier-2,
`pid_view.py`), this library supplies a bundled substitute keyed by the same
raw component class both tiers already carry (`ComponentClass` / graph-fact
`label`). Entries use the same primitive-shape vocabulary `_shape_primitives`
already produces from real file geometry (`polyline`/`circle`/`arc`/`polygon`
dicts), so no renderer-side change is needed to paint them.
"""
from __future__ import annotations

_STROKE = "#334155"


def _polyline(points: list[list[float]], *, width: float = 1.2) -> dict[str, object]:
    return {"kind": "polyline", "points": points, "stroke": _STROKE, "width": width, "dash": None}


def _circle(cx: float, cy: float, r: float, *, filled: bool = False, width: float = 1.4) -> dict[str, object]:
    return {"kind": "circle", "cx": cx, "cy": cy, "r": r, "filled": filled, "stroke": _STROKE, "width": width}


def _polygon(points: list[list[float]], *, filled: bool = False, width: float = 1.4) -> dict[str, object]:
    return {"kind": "polygon", "points": points, "filled": filled, "stroke": _STROKE, "width": width, "dash": None}


BUNDLED_SYMBOLS: dict[str, list[dict[str, object]]] = {
    "CentrifugalPump": [
        _circle(0, 0, 16),
        _polygon([[-6, -8], [-6, 8], [10, 0]], filled=True, width=1.0),
    ],
    "ReciprocatingPump": [
        _polygon([[-14, -10], [14, -10], [14, 10], [-14, 10]]),
        _polyline([[-8, -10], [-8, 10]], width=1.0),
        _polyline([[0, -10], [0, 10]], width=1.0),
        _polyline([[8, -10], [8, 10]], width=1.0),
    ],
    "PlateHeatExchanger": [
        _circle(0, 0, 18),
        _polyline([[-10, 0], [-5, 8], [0, -8], [5, 8], [10, 0]]),
    ],
    "TubularHeatExchanger": [
        _polygon([[-18, -8], [18, -8], [18, 8], [-18, 8]]),
        _polyline([[-18, 0], [18, 0]], width=1.0),
        _circle(-18, 0, 3, filled=True, width=1.0),
        _circle(18, 0, 3, filled=True, width=1.0),
    ],
    "Tank": [
        _polygon([[-12, -18], [12, -18], [12, 20], [-12, 20]]),
        _polyline([[-12, -18], [0, -24], [12, -18]]),
    ],
    "PressureVessel": [
        _polygon([[-10, -20], [10, -20], [10, 20], [-10, 20]]),
        _circle(0, -20, 10, width=1.0),
        _circle(0, 20, 10, width=1.0),
    ],
    "Vessel": [
        _polygon(
            [[-12, -18], [12, -18], [12, 16], [7, 22], [-7, 22], [-12, 16]],
        ),
    ],
    "ProcessColumn": [
        _polygon([[-10, -22], [10, -22], [10, 24], [-10, 24]]),
        _polyline([[-10, -10], [10, -10]], width=1.0),
        _polyline([[-10, 2], [10, 2]], width=1.0),
        _polyline([[-10, 14], [10, 14]], width=1.0),
    ],
    "TaggedColumnSection": [
        _polygon([[-10, -12], [10, -12], [10, 12], [-10, 12]]),
        _polyline([[-10, 0], [10, 0]], width=1.0),
    ],
}

GENERIC_PLACEHOLDER: list[dict[str, object]] = [
    _polygon([[-14, -10], [14, -10], [14, 10], [-14, 10]], width=1.2),
]
