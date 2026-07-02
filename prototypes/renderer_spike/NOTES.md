# Renderer spike findings (bead pydexpi-datalog-1-2ki.2)

Throwaway spike. The **decisions below** are the deliverable; the code is
reference-only and dies with this directory.

Run: `python3 prototypes/renderer_spike/spike.py` (tier-1),
`node prototypes/renderer_spike/elk/layout.mjs` (tier-2 sample).
View: `out/compare.html?f=C01|C02|C03` (mine vs vendor reference SVG).

## 1. Verdict: source-geometry rendering works

C01 (DEXPI 1.3 reference P&ID) renders **recognizably as the reference
drawing** from file geometry alone: equipment symbols from the file's shape
catalogue, as-drawn positions, orthogonal pipe runs, instrument bubbles,
signal dashes, labels, drawing border and title block. C02 (BASF column) and
C03 (Equinor piping) also match their vendor references.

## 2. Proteus geometry model (what production must implement)

- **Catalogue**: `ShapeCatalogue/*` entries keyed by `ComponentName`; each is a
  list of primitives in local coords. Instances reference the catalogue via
  their own `ComponentName` attribute.
- **Primitives**: `PolyLine` (Coordinate*), `Circle` (Radius, optional
  `Filled="Solid"`), `TrimmedCurve` (arc: inner Circle + Start/EndAngle),
  `Shape` (**polygon** with direct Coordinate children + optional Filled —
  never a nested group), `Text` (String/Height/Justification/Font +
  **`TextAngle`**: explicit CCW rotation *additive* to the Position/Reference
  angle — vertical pipe-run labels rely on it; C01 has 13, C02 has 15.
  `Font` names the face — all fixtures say Calibri; emit it, don't hardcode).
- **Placement**: `Position/Location` = translate, `Position/Reference` = local
  +X direction (rotation = atan2(ry, rx)), `Position/Axis` Z<0 = mirror,
  instance-level `Scale` (nozzles use 0.8x0.4). Y axis is **up**: flip once at
  render, un-flip text.
- **Pipes**: `PipingNetworkSegment/CenterLine` polylines (world coords).
  Signal/instrument lines: `CenterLine` under instrumentation parents, styled
  dashed via `Presentation/LineType`.
- **Labels**: a `Label` may itself reference a catalogue shape via
  `ComponentName` + `Position` (e.g. C03's ESD funnel) and carries Text /
  PolyLine / Shape children in **absolute world coords** (no transform
  inheritance).
- **Style**: per-element `Presentation` (RGB 0..1, LineWeight in file units,
  LineType → dash). File colors are normative (C01 draws equipment maroon);
  the vendor viewer recolors, we should not.
- **Sheet**: `Drawing/Extent` exists in every geometry export; C01 also draws
  border+title block as world PolyLine/Text, C03 as a `Drawing/Symbol`.
- **Units**: `PlantInformation@Units` — C01 is mm, C02/C03 are **m**. All
  coordinates, stroke widths, and font sizes are in file units; normalize
  before cross-file thresholds, render per-file in native units.
- Geometry presence is **per-exporter, not per-DEXPI-version**: 1.2 HEX
  exports carry 50-shape catalogues; 1.2 VER exports of the same plants carry
  zero geometry.

## 3. Proposed scene schema (validated end-to-end)

```jsonc
{
  "units": "mm",
  "extent": {"x0": 0, "y0": 0, "x1": 420, "y1": 297},   // Drawing/Extent
  "catalogue": {"CENTRIFUGAL_PUMP_SHAPE": [/* primitives */]},
  "symbols":  [{"id": "P4711", "class": "CentrifugalPump", "shape": "...",
                "tx": 0, "ty": 0, "angle": 0, "mirror": false, "sx": 1, "sy": 1}],
  "polylines": [{"id": "seg-1", "kind": "pipe|signal|leader|frame",
                 "points": [[x, y]], "stroke": "#...", "width": 0.3,
                 "dash": null, "inferred": false}],
  "polygons":  [{"points": [[x, y]], "filled": true}],
  "texts":     [{"x": 0, "y": 0, "angle": 0, "string": "...", "height": 3,
                 "just": "CenterCenter"}],
  "report":    {/* typed geometry diagnostics, existing pattern */}
}
```

Frontend paints this verbatim (`<use>` per symbol, one flipped world group);
hit-testing via `data-id` on `<use>`/polylines. Highlighting = class toggle,
same as the Cytoscape path today.

## 4. Geometry sanity gate — calibrated thresholds

Survey of all 150 fixture exports (see spike output) is cleanly bimodal:

| metric | real drawings (C01–C04, I-SAG) | pedagogical (E/I/P VER+HEX) |
|---|---|---|
| normalized extent | ≥ 130 × 50 mm | 0, or degenerate (1e-15 on one axis) |
| pipe centerline coverage | 60–100% | 0% (or no segments) |
| unpositioned equipment | 0% | 100% |

Proposed gate (all three required for tier-1 as-drawn):
- **extent**: both dimensions of normalized content bbox ≥ 10 mm
- **pipe coverage**: ≥ 50% of segments carry a CenterLine (segments > 0;
  vacuously true when the plant has no segments)
- **unpositioned equipment share**: ≤ 20% (per PRD, equipment placement is
  all-or-nothing within the frame; unpositioned → shelf only in tier-1)

Margins are wide on both sides (closest real file: C03 at 60% coverage;
closest degenerate: I03V01-HEX at 50% coverage but 1e-15 extent), so
threshold choice is not sensitive. Per-element demotion still applies inside
tier-1: C02 (78%) and C03 (60%) get inferred-routing cues for their
centerline-less segments.

## 5. Auto-layout engine: **elkjs** (client-side)

- `elkjs` layered algorithm + `ORTHOGONAL` edge routing produces a readable
  left-to-right process flow for the compressed `pid_view` (sample:
  `out/c01-elk.svg`, `out/e06-elk.svg` — E06 proves the geometry-free path).
- dagre (already bundled via cytoscape) has no orthogonal edge routing —
  disqualifying for P&ID pipes. Python-side alternatives (grandalf, igraph)
  also lack it, so **layout computes client-side per ADR 0005's carve-out**;
  the *decision* to auto-layout (gate result) and its disclosure remain
  backend-owned in the geometry report.
- Line endpoints outside the unit set (off-page connectors, unfolded junction
  nodes) need explicit pseudo-nodes to keep connectivity complete — in
  production these become connector glyphs, not dropped edges.

## 6. Oddities log

- C02/C03 declare `Units="m"`; everything scales, including LineWeight
  (0.0003 m) and text Height. Normalize only for gate metrics.
- C02: 2/9 segments lack centerlines (78%); C03: 2/5 (60%) → the standing
  inferred-pipe-routing fixtures for production tests.
- C02V01-VER.EX01 (1.2) carries zero geometry while C02V01-HEX.EX02 (1.2)
  carries a 38-shape catalogue — same plant, different exporter.
- P01V01-ING.EX01: pipes drawn, equipment unpositioned (100%) → tier-2 by the
  unpositioned gate, exercising the "frame must not lie" rule.
- C03's filled ball valve is `Circle Filled="Solid"`; ESD funnel is a Label
  referencing `ACTUATING_SYSTEM_LABEL_SHAPE`. Both now render.
- 1.2 HEX symbol IDs collide across files (`TaggedPlantItemShape-1`) — scene
  ids must be namespaced per export in production.
