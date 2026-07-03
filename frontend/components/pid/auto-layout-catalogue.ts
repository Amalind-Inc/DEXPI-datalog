import type { SchematicPrimitive } from "@/components/pid/types";
import { symbolKeyFor, type SymbolKey } from "@/components/pid/pid-symbols";

const STROKE = "#334155";

// Starter bundled symbol library for the auto-layout schematic view (bead
// pydexpi-datalog-1-2ki.5): plain schematic primitives, not file geometry,
// keyed the same way as the existing Cytoscape symbol set (`symbolKeyFor`)
// so equipment classification stays in one place.
export const autoLayoutCatalogue: Record<SymbolKey, SchematicPrimitive[]> = {
  pump: [
    { kind: "circle", cx: 0, cy: 0, r: 16, filled: false, stroke: STROKE, width: 1.4, dash: null },
    { kind: "polygon", points: [[-6, -8], [-6, 8], [10, 0]], filled: true, stroke: STROKE, width: 1, dash: null },
  ],
  exchanger: [
    { kind: "circle", cx: 0, cy: 0, r: 18, filled: false, stroke: STROKE, width: 1.4, dash: null },
    {
      kind: "polyline",
      points: [[-10, 0], [-5, 8], [0, -8], [5, 8], [10, 0]],
      stroke: STROKE,
      width: 1.2,
      dash: null,
    },
  ],
  vessel: [
    {
      kind: "polygon",
      points: [[-12, -18], [12, -18], [12, 16], [7, 22], [-7, 22], [-12, 16]],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
  ],
  column: [
    {
      kind: "polygon",
      points: [[-10, -20], [10, -20], [10, 22], [-10, 22]],
      filled: false,
      stroke: STROKE,
      width: 1.4,
      dash: null,
    },
    { kind: "polyline", points: [[-10, -8], [10, -8]], stroke: STROKE, width: 1, dash: null },
    { kind: "polyline", points: [[-10, 4], [10, 4]], stroke: STROKE, width: 1, dash: null },
  ],
  valve: [
    { kind: "polygon", points: [[-8, -10], [-8, 10], [8, 0]], filled: false, stroke: STROKE, width: 1.4, dash: null },
    { kind: "polygon", points: [[8, -10], [8, 10], [-8, 0]], filled: false, stroke: STROKE, width: 1.4, dash: null },
  ],
  instrument: [
    { kind: "circle", cx: 0, cy: 0, r: 12, filled: false, stroke: STROKE, width: 1.2, dash: null },
  ],
  generic: [
    {
      kind: "polygon",
      points: [[-14, -10], [14, -10], [14, 10], [-14, 10]],
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

export function autoLayoutSymbolKeyFor(category: string, className: string): SymbolKey {
  return symbolKeyFor(category, className);
}
