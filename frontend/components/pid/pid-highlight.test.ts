import test from "node:test";
import assert from "node:assert/strict";
import { highlightSets } from "./pid-highlight.ts";
import type { PidView } from "./types.ts";

const view: PidView = {
  units: [
    { id: "u_pump", label: "P-4713", className: "Centrifugal Pump", category: "equipment", description: "", ports: [{ id: "nz1", label: "N-1" }] },
    { id: "u_hx", label: "H-1009", className: "Plate Heat Exchanger", category: "equipment", description: "", ports: [{ id: "nz2", label: "N-2" }] },
  ],
  lines: [
    {
      id: "line_seg",
      label: "Line 47132",
      sourceUnit: "u_pump",
      targetUnit: "u_hx",
      sourcePort: "nz1",
      targetPort: "nz2",
      memberTopologyIds: ["line_seg", "nz1", "nz2", "pn1", "pn2", "sys"],
    },
  ],
  hiddenTopologyIds: ["root"],
};

test("a cited equipment id lights up that unit", () => {
  const { units, lines } = highlightSets(view, ["u_pump"]);
  assert.ok(units.has("u_pump"));
  assert.ok(!units.has("u_hx"));
  assert.equal(lines.size, 0);
});

test("a cited nozzle (port) lights up its parent unit", () => {
  const { units } = highlightSets(view, ["nz2"]);
  assert.ok(units.has("u_hx"));
});

test("citing any collapsed member of a line lights up that line", () => {
  // The chat cites internal witness ids (segment + piping nodes), never the
  // synthetic line id directly — the line must still light up.
  const { lines } = highlightSets(view, ["pn1", "sys"]);
  assert.ok(lines.has("line_seg"));
});

test("unrelated ids highlight nothing", () => {
  const { units, lines } = highlightSets(view, ["something-else"]);
  assert.equal(units.size, 0);
  assert.equal(lines.size, 0);
});
