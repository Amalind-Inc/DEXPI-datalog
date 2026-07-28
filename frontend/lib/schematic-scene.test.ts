import assert from "node:assert/strict";
import test from "node:test";
import {
  catalogueShapesUsed,
  hitTestableObjects,
  sceneViewBox,
  svgRotationDegrees,
  symbolTransform,
  textAnchor,
} from "./schematic-scene.ts";
import type { SchematicScene } from "@/components/pid/types.ts";

function scene(overrides: Partial<SchematicScene> = {}): SchematicScene {
  return {
    units: "mm",
    extent: null,
    catalogue: {},
    symbols: [],
    polylines: [],
    polygons: [],
    texts: [],
    ...overrides,
  };
}

test("sceneViewBox pads the drawn content bounding box by 3%", () => {
  const box = sceneViewBox(
    scene({
      polylines: [
        {
          id: "p1",
          topologyId: null,
          kind: "pipe",
          points: [
            [0, 0],
            [100, 50],
          ],
          stroke: "#000",
          width: 0.3,
          dash: null,
          inferred: false,
        },
      ],
    }),
  );
  assert.ok(box.x < 0);
  assert.ok(box.y < 0);
  assert.ok(box.width > 100);
  assert.ok(box.height > 50);
});

test("sceneViewBox falls back to the drawing extent when nothing is drawn", () => {
  const box = sceneViewBox(scene({ extent: { x0: 0, y0: 0, x1: 420, y1: 297 } }));
  assert.deepEqual(box, { x: 0, y: 0, width: 420, height: 297 });
});

test("sceneViewBox falls back to a unit box when there is no content and no extent", () => {
  const box = sceneViewBox(scene());
  assert.deepEqual(box, { x: 0, y: 0, width: 1, height: 1 });
});

test("svgRotationDegrees negates the Proteus CCW angle for the flipped world group", () => {
  assert.equal(svgRotationDegrees(90), -90);
  assert.equal(svgRotationDegrees(-45), 45);
});

test("symbolTransform composes translate, rotate, mirror, and scale in file order", () => {
  const transform = symbolTransform({
    id: "s1",
    topologyId: null,
    className: "",
    shape: "PUMP_SHAPE",
    tx: 10,
    ty: 20,
    angle: 90,
    mirror: true,
    sx: 0.8,
    sy: 0.4,
    shelved: false,
  });
  assert.equal(transform, "translate(10 20) rotate(90) scale(1,-1) scale(0.8 0.4)");
});

test("symbolTransform omits scale when the symbol is unscaled", () => {
  const transform = symbolTransform({
    id: "s1",
    topologyId: null,
    className: "",
    shape: "PUMP_SHAPE",
    tx: 0,
    ty: 0,
    angle: 0,
    mirror: false,
    sx: 1,
    sy: 1,
    shelved: false,
  });
  assert.equal(transform, "translate(0 0) rotate(0)");
});

test("textAnchor maps Proteus justification to SVG text-anchor", () => {
  assert.equal(textAnchor("LeftBottom"), "start");
  assert.equal(textAnchor("RightTop"), "end");
  assert.equal(textAnchor("CenterCenter"), "middle");
});

test("catalogueShapesUsed returns only shapes referenced by placed symbols, deduped", () => {
  const s = scene({
    catalogue: {
      PUMP_SHAPE: [{ kind: "polyline", points: [[0, 0]], stroke: "#000", width: 0.3, dash: null }],
      UNUSED_SHAPE: [],
    },
    symbols: [
      { id: "a", topologyId: null, className: "", shape: "PUMP_SHAPE", tx: 0, ty: 0, angle: 0, mirror: false, sx: 1, sy: 1, shelved: false },
      { id: "b", topologyId: null, className: "", shape: "PUMP_SHAPE", tx: 5, ty: 5, angle: 0, mirror: false, sx: 1, sy: 1, shelved: false },
    ],
  });
  const used = catalogueShapesUsed(s);
  assert.equal(used.length, 1);
  assert.equal(used[0][0], "PUMP_SHAPE");
});

test("hitTestableObjects includes symbols and pipe/signal lines but not frame or leader polylines", () => {
  const s = scene({
    symbols: [{ id: "sym-1", topologyId: "topo-1", className: "", shape: "X", tx: 0, ty: 0, angle: 0, mirror: false, sx: 1, sy: 1, shelved: false }],
    polylines: [
      { id: "line-1", topologyId: "topo-2", kind: "pipe", points: [], stroke: "#000", width: 0.3, dash: null, inferred: false },
      { id: "sheet", topologyId: null, kind: "frame", points: [], stroke: "#000", width: 0.3, dash: null, inferred: false },
      { id: "leader", topologyId: null, kind: "leader", points: [], stroke: "#000", width: 0.3, dash: null, inferred: false },
    ],
  });
  const ids = hitTestableObjects(s).map((o) => o.id);
  assert.deepEqual(ids, ["sym-1", "line-1"]);
});
