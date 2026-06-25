import type { PidGraph } from "./types.ts";

export type GraphPosition = { x: number; y: number };

const samplePositions: Record<string, GraphPosition> = {
  "pump-101": { x: 68, y: 120 },
  "valve-102": { x: 220, y: 96 },
  "flow-transmitter-101": { x: 350, y: 164 },
  "line-101": { x: 248, y: 208 },
};

export function layoutGraphNodes(graph: PidGraph): Record<string, GraphPosition> {
  if (graph.nodes.every((node) => samplePositions[node.id])) {
    return Object.fromEntries(
      graph.nodes.map((node) => [node.id, samplePositions[node.id]]),
    );
  }

  const positions: Record<string, GraphPosition> = {};
  const columns = Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length)));
  const rows = Math.max(1, Math.ceil(graph.nodes.length / columns));
  const xStep = columns === 1 ? 0 : 320 / (columns - 1);
  const yStep = rows === 1 ? 0 : 190 / (rows - 1);

  graph.nodes.forEach((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    positions[node.id] = {
      x: Math.round(55 + column * xStep),
      y: Math.round(50 + row * yStep),
    };
  });

  return positions;
}
