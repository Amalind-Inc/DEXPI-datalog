import test from "node:test";
import assert from "node:assert/strict";
import { autoLayoutCatalogue } from "./auto-layout-catalogue.ts";

// The corpus classes bundled_symbols.py covers (bead pydexpi-datalog-1-2ki.15) --
// kept in sync manually since one lives in Python and the other in TS.
const CORPUS_CLASSES = [
  "CentrifugalPump",
  "ReciprocatingPump",
  "PlateHeatExchanger",
  "TubularHeatExchanger",
  "Tank",
  "PressureVessel",
  "Vessel",
  "ProcessColumn",
  "TaggedColumnSection",
];

test("autoLayoutCatalogue covers every corpus component class plus a generic fallback", () => {
  for (const className of CORPUS_CLASSES) {
    assert.ok(autoLayoutCatalogue[className], `missing bundled symbol for ${className}`);
    assert.ok(autoLayoutCatalogue[className].length > 0);
  }
  assert.ok(autoLayoutCatalogue.generic);
});
