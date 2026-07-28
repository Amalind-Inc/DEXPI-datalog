import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";
import type { PidView, SchematicScene } from "@/components/pid/types";
import { autoLayoutCatalogue } from "@/components/pid/auto-layout-catalogue";

const elk = new ELK();
const NODE_SIZE = 64;
const PSEUDO_SIZE = 20;
const MARGIN = 40;

// Tier-2 auto-layout schematic (bead pydexpi-datalog-1-2ki.5): exact source
// connectivity from `pidView`, positions computed by ELK's layered algorithm
// with orthogonal edge routing (ADR 0005's tolerated client-side exception --
// the decision to auto-layout is made backend-side, this only computes
// where things land). Source positions are never available here by
// construction: the backend only reaches this path when it withheld them.
export async function buildAutoLayoutScene(pidView: PidView): Promise<SchematicScene> {
  const unitIds = new Set(pidView.units.map((unit) => unit.id));
  const pseudoIds = new Set<string>();
  const endpoint = (id: string | null): string | null => {
    if (id == null) return null;
    if (!unitIds.has(id)) pseudoIds.add(id);
    return id;
  };

  const edges = pidView.lines
    .map((line) => {
      const source = endpoint(line.sourceUnit);
      const target = endpoint(line.targetUnit);
      if (source == null || target == null || source === target) return null;
      return { id: line.id, sources: [source], targets: [target], lineLabel: line.label || line.id };
    })
    .filter((edge): edge is { id: string; sources: string[]; targets: string[]; lineLabel: string } => edge !== null);

  const graph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": "70",
      "elk.spacing.nodeNode": "50",
    },
    children: [
      ...pidView.units.map((unit) => ({ id: unit.id, width: NODE_SIZE, height: NODE_SIZE })),
      ...[...pseudoIds].map((id) => ({ id, width: PSEUDO_SIZE, height: PSEUDO_SIZE })),
    ],
    edges: edges.map(({ id, sources, targets }): ElkExtendedEdge => ({ id, sources, targets })),
  };

  const laidOut = await elk.layout(graph);
  const nodeCenters = new Map<string, { x: number; y: number }>();
  for (const child of laidOut.children ?? []) {
    nodeCenters.set(child.id, {
      x: (child.x ?? 0) + (child.width ?? NODE_SIZE) / 2,
      y: (child.y ?? 0) + (child.height ?? NODE_SIZE) / 2,
    });
  }

  const unitById = new Map(pidView.units.map((unit) => [unit.id, unit]));
  const scene: SchematicScene = {
    units: "mm",
    extent: { x0: 0, y0: 0, x1: (laidOut.width ?? 400) + MARGIN, y1: (laidOut.height ?? 300) + MARGIN },
    catalogue: autoLayoutCatalogue,
    symbols: [],
    polylines: [],
    polygons: [],
    texts: [{ kind: "text", x: 8, y: (laidOut.height ?? 300) + MARGIN - 4, angle: 0, string: "AUTO-LAYOUT", height: 8, font: "sans-serif", just: "LeftBottom" }],
  };

  for (const unit of pidView.units) {
    const center = nodeCenters.get(unit.id);
    if (!center) continue;
    const shape = autoLayoutCatalogue[unit.symbolKey] ? unit.symbolKey : "generic";
    scene.symbols.push({
      id: unit.id,
      topologyId: unit.id,
      className: unit.className,
      shape,
      tx: center.x,
      ty: center.y,
      angle: 0,
      mirror: false,
      sx: 1,
      sy: 1,
      shelved: false,
    });
    scene.texts.push({
      kind: "text",
      x: center.x,
      y: center.y - NODE_SIZE / 2 - 6,
      angle: 0,
      string: unit.label || unitById.get(unit.id)?.label || unit.id,
      height: 7,
      font: "sans-serif",
      just: "center",
    });
  }

  for (const laidOutEdge of laidOut.edges ?? []) {
    const source = edges.find((edge) => edge.id === laidOutEdge.id);
    if (!source) continue;
    for (const section of laidOutEdge.sections ?? []) {
      const points: [number, number][] = [
        [section.startPoint.x, section.startPoint.y],
        ...((section.bendPoints ?? []).map((point) => [point.x, point.y] as [number, number])),
        [section.endPoint.x, section.endPoint.y],
      ];
      scene.polylines.push({
        id: source.id,
        topologyId: source.id,
        kind: "pipe",
        points,
        stroke: "#334155",
        width: 1.4,
        // Dashed = the standing "inferred routing" cue (renderer spike
        // section 5): positions here are computed, not drawn.
        dash: "6 3",
        inferred: true,
      });
    }
  }

  return scene;
}
