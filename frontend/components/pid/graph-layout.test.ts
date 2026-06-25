import assert from "node:assert/strict";
import test from "node:test";
import { layoutGraphNodes } from "./graph-layout.ts";
import type { PidGraph } from "./types.ts";

test("layoutGraphNodes gives backend topology nodes distinct visible positions", () => {
  const graph: PidGraph = {
    nodes: Array.from({ length: 6 }, (_, index) => ({
      id: `node-${index}`,
      label: `N-${index}`,
      kind: "Equipment",
      description: "Backend topology node",
      status: "normal",
    })),
    edges: [],
  };

  const positions = layoutGraphNodes(graph);
  const uniqueCoordinates = new Set(
    Object.values(positions).map((position) => `${position.x},${position.y}`),
  );

  assert.equal(Object.keys(positions).length, 6);
  assert.equal(uniqueCoordinates.size, 6);
  for (const position of Object.values(positions)) {
    assert.ok(position.x >= 0 && position.x <= 430);
    assert.ok(position.y >= 0 && position.y <= 290);
  }
});
