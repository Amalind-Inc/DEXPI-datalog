// Pure mapping from a backend-owned schematic scene (ADR 0004/0005) to the
// SVG geometry a React component paints. No geometry semantics live here --
// positions, rotations, and text angles are taken from the scene verbatim.
import type {
  GeometryReport,
  SchematicPrimitive,
  SchematicScene,
  SchematicSceneKind,
  SchematicSymbol,
} from "@/components/pid/types.ts";

export type ViewBox = { x: number; y: number; width: number; height: number };

const FALLBACK_VIEW_BOX: ViewBox = { x: 0, y: 0, width: 1, height: 1 };

/** World-space bounding box padded 3%, falling back to the file's own drawing extent. */
export function sceneViewBox(scene: SchematicScene): ViewBox {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const polyline of scene.polylines) {
    for (const [x, y] of polyline.points) {
      xs.push(x);
      ys.push(y);
    }
  }
  for (const polygon of scene.polygons) {
    for (const [x, y] of polygon.points) {
      xs.push(x);
      ys.push(y);
    }
  }
  for (const symbol of scene.symbols) {
    xs.push(symbol.tx);
    ys.push(symbol.ty);
  }
  for (const text of scene.texts) {
    xs.push(text.x);
    ys.push(text.y);
  }
  if (xs.length === 0 || ys.length === 0) {
    if (scene.extent) {
      const { x0, y0, x1, y1 } = scene.extent;
      return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    }
    return FALLBACK_VIEW_BOX;
  }
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const pad = 0.03 * Math.max(maxX - minX, maxY - minY, 1);
  return {
    x: minX - pad,
    y: minY - pad,
    width: maxX - minX + 2 * pad,
    height: maxY - minY + 2 * pad,
  };
}

/** SVG rotates clockwise; Proteus angles are CCW in Y-up space -- negate for the Y-flipped world group. */
export function svgRotationDegrees(proteusAngleDegrees: number): number {
  return -proteusAngleDegrees;
}

export function symbolTransform(symbol: SchematicSymbol): string {
  let transform = `translate(${symbol.tx} ${symbol.ty}) rotate(${symbol.angle})`;
  if (symbol.mirror) transform += " scale(1,-1)";
  if (symbol.sx !== 1 || symbol.sy !== 1) transform += ` scale(${symbol.sx} ${symbol.sy})`;
  return transform;
}

export function textAnchor(justification: string): "start" | "middle" | "end" {
  const value = justification.toLowerCase();
  if (value.startsWith("left")) return "start";
  if (value.startsWith("right")) return "end";
  return "middle";
}

/** Distinct catalogue shape names actually referenced by placed symbols, so callers only render used <defs>. */
export function catalogueShapesUsed(scene: SchematicScene): [string, SchematicPrimitive[]][] {
  const seen = new Set<string>();
  const used: [string, SchematicPrimitive[]][] = [];
  for (const symbol of scene.symbols) {
    if (seen.has(symbol.shape)) continue;
    seen.add(symbol.shape);
    const primitives = scene.catalogue[symbol.shape];
    if (primitives) used.push([symbol.shape, primitives]);
  }
  return used;
}

/** Bounding box of the shelved-symbol row (bead 2ki.7), padded for the backdrop rect, or null when nothing is shelved. */
export function shelfRegionBounds(scene: SchematicScene): ViewBox | null {
  const shelved = scene.symbols.filter((symbol) => symbol.shelved);
  if (shelved.length === 0) return null;
  const xs = shelved.map((s) => s.tx);
  const ys = shelved.map((s) => s.ty);
  const pad = 8;
  const minX = Math.min(...xs) - pad;
  const maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad;
  const maxY = Math.max(...ys) + pad;
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

export type SchematicTier = "as-drawn" | "partially-inferred" | "auto-layout";

// Single source of the three-way tier vocabulary (bead 2ki.8) -- the
// renderer badge and the geometry health card both call this so they can
// never disagree about what tier a prepared file landed on.
export function describeSchematicTier(
  kind: SchematicSceneKind,
  report: GeometryReport | null,
): { tier: SchematicTier; label: string } {
  if (kind !== "as-drawn" || !report) {
    return { tier: "auto-layout", label: "Auto-layout — positions inferred, not as drawn" };
  }
  const demoted = report.routedPipeRuns.length > 0 || report.shelvedEquipment.length > 0;
  return demoted
    ? {
        tier: "partially-inferred",
        label: "Partially inferred — some positions or routing are backend-computed",
      }
    : { tier: "as-drawn", label: "As drawn — positions and routing match the source" };
}

/** Local-space (pre-transform) bounding radius of a catalogue shape's primitives, padded for a forgiving click target. */
function catalogueShapeRadius(primitives: SchematicPrimitive[]): number {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const primitive of primitives) {
    switch (primitive.kind) {
      case "circle":
      case "arc":
        xs.push(primitive.cx - primitive.r, primitive.cx + primitive.r);
        ys.push(primitive.cy - primitive.r, primitive.cy + primitive.r);
        break;
      case "polyline":
      case "polygon":
        for (const [x, y] of primitive.points) {
          xs.push(x);
          ys.push(y);
        }
        break;
      default:
        break;
    }
  }
  if (xs.length === 0 || ys.length === 0) return 3;
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  // Modest padding, not maximal: on a dense schematic an overly generous
  // hit-circle starts overlapping a neighboring symbol's and stealing its
  // clicks, so this stays a small forgiving margin rather than a big one.
  return Math.max(width, height, 4) / 2 + 0.5;
}

/** Invisible hit-circle radius (local, pre-transform space) for a symbol's shape -- a forgiving margin around the shape's painted geometry, not a maximal one (see comment above). */
export function symbolHitRadius(
  catalogue: Record<string, SchematicPrimitive[]>,
  shape: string,
): number {
  const primitives = catalogue[shape];
  return primitives ? catalogueShapeRadius(primitives) : 3;
}

/** Every hit-testable scene object: id (== topologyId when resolved) paired with its topologyId for selection. */
export function hitTestableObjects(
  scene: SchematicScene,
): { id: string; topologyId: string | null }[] {
  const symbols = scene.symbols.map((s) => ({ id: s.id, topologyId: s.topologyId }));
  const polylines = scene.polylines
    .filter((p) => p.kind !== "frame" && p.kind !== "leader")
    .map((p) => ({ id: p.id, topologyId: p.topologyId }));
  return [...symbols, ...polylines];
}
