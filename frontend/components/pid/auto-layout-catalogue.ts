import type { SchematicPrimitive } from "@/components/pid/types";

const STROKE = "#334155";

// Bundled symbol library for the auto-layout schematic view (bead
// pydexpi-datalog-1-2ki.15): ISO-10628-styled schematic primitives keyed by
// the same raw DEXPI `ComponentClass` the backend resolves against
// (`pydexpi_datalog/workflow/bundled_symbols.py`) -- one entry per class
// actually appearing in the supported fixture corpus, plus a "generic"
// fallback for anything the backend could not resolve either.
export const autoLayoutCatalogue: Record<string, SchematicPrimitive[]> = {
  CentrifugalPump: [
    { kind: "circle", cx: 0, cy: 0, r: 16, filled: false, stroke: STROKE, width: 1.4, dash: null },
    {
      kind: "polygon",
      points: [
        [-6, -8],
        [-6, 8],
        [10, 0],
      ],
      filled: true,
      stroke: STROKE,
      width: 1,
      dash: null,
    },
  ],
  ReciprocatingPump: [
    {
      kind: "polygon",
      points: [
        [-14, -10],
        [14, -10],
        [14, 10],
        [-14, 10],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-8, -10],
        [-8, 10],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [0, -10],
        [0, 10],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [8, -10],
        [8, 10],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
  ],
  PlateHeatExchanger: [
    { kind: "circle", cx: 0, cy: 0, r: 18, filled: false, stroke: STROKE, width: 1.4, dash: null },
    {
      kind: "polyline",
      points: [
        [-10, 0],
        [-5, 8],
        [0, -8],
        [5, 8],
        [10, 0],
      ],
      stroke: STROKE,
      width: 1.2,
      dash: null,
    },
  ],
  TubularHeatExchanger: [
    {
      kind: "polygon",
      points: [
        [-18, -8],
        [18, -8],
        [18, 8],
        [-18, 8],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-18, 0],
        [18, 0],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
    { kind: "circle", cx: -18, cy: 0, r: 3, filled: true, stroke: STROKE, width: 1, dash: null },
    { kind: "circle", cx: 18, cy: 0, r: 3, filled: true, stroke: STROKE, width: 1, dash: null },
  ],
  Tank: [
    {
      kind: "polygon",
      points: [
        [-12, -18],
        [12, -18],
        [12, 20],
        [-12, 20],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-12, -18],
        [0, -24],
        [12, -18],
      ],
      stroke: STROKE,
      width: 1.2,
      dash: null,
    },
  ],
  PressureVessel: [
    {
      kind: "polygon",
      points: [
        [-10, -20],
        [10, -20],
        [10, 20],
        [-10, 20],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    { kind: "circle", cx: 0, cy: -20, r: 10, filled: false, stroke: STROKE, width: 1, dash: null },
    { kind: "circle", cx: 0, cy: 20, r: 10, filled: false, stroke: STROKE, width: 1, dash: null },
  ],
  Vessel: [
    {
      kind: "polygon",
      points: [
        [-12, -18],
        [12, -18],
        [12, 16],
        [7, 22],
        [-7, 22],
        [-12, 16],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
  ],
  ProcessColumn: [
    {
      kind: "polygon",
      points: [
        [-10, -22],
        [10, -22],
        [10, 24],
        [-10, 24],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-10, -10],
        [10, -10],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-10, 2],
        [10, 2],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-10, 14],
        [10, 14],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
  ],
  TaggedColumnSection: [
    {
      kind: "polygon",
      points: [
        [-10, -12],
        [10, -12],
        [10, 12],
        [-10, 12],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    {
      kind: "polyline",
      points: [
        [-10, 0],
        [10, 0],
      ],
      stroke: STROKE,
      width: 1,
      dash: null,
    },
  ],
  generic: [
    {
      kind: "polygon",
      points: [
        [-14, -10],
        [14, -10],
        [14, 10],
        [-14, 10],
      ],
      filled: false,
      stroke: STROKE,
      width: 1.2,
      dash: null,
    },
  ],
};

export const autoLayoutNozzleSymbol: SchematicPrimitive[] = [
  { kind: "circle", cx: 0, cy: 0, r: 4, filled: true, stroke: STROKE, width: 0.8, dash: null },
];
