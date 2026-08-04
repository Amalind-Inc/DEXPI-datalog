import assert from "node:assert/strict";
import test from "node:test";

import { enumerateCentrifugalPumpScopes, routeLocalAsk } from "./local-ask-routing.ts";

test("routes ordinary topology questions to evidence lookup", () => {
  assert.deepEqual(routeLocalAsk("What equipment is connected to P-4713?"), {
    kind: "evidence",
    posture: "inspect",
  });
});

test("routes a named pump rule question without deciding its truth", () => {
  assert.deepEqual(routeLocalAsk("Does pump P-4713 have a downstream check valve?"), {
    kind: "rule",
    posture: "verify",
    checkId: "pump_discharge_check_valve",
    scopeEntityId: "P-4713",
  });
});

test("routes compact pump tags to the supported deterministic rule", () => {
  assert.deepEqual(routeLocalAsk("Does pump P4711 have a downstream check valve?"), {
    kind: "rule",
    posture: "verify",
    checkId: "pump_discharge_check_valve",
    scopeEntityId: "P4711",
  });
});

test("clarifies an ambiguous any-pump rule question", () => {
  const route = routeLocalAsk("Does any pump have a downstream check valve?");
  assert.equal(route.kind, "clarification");
});
test("routes an all-pumps question to a universal rule plan", () => {
  assert.deepEqual(routeLocalAsk("Do all centrifugal pumps have a downstream check valve?"), {
    kind: "universal_rule",
    posture: "verify",
    checkId: "pump_discharge_check_valve",
    domain: "centrifugal_pumps",
  });
});

test("clarifies a universal connected-object question with useful choices", () => {
  const route = routeLocalAsk("Must every connected object satisfy the rule?");
  assert.equal(route.kind, "clarification");
  if (route.kind !== "clarification") return;
  assert.match(route.prompt, /scope/i);
  assert.deepEqual(
    route.choices.map((choice) => choice.id),
    ["all-centrifugal-pumps", "connected-objects", "applicable-equipment"],
  );
});

test("clarifies a non-pump rule question instead of routing the pump rule", () => {
  const route = routeLocalAsk("Does heat exchanger H-1009 have a downstream check valve?");
  assert.equal(route.kind, "clarification");
  if (route.kind !== "clarification") return;
  assert.match(route.prompt, /pump discharge rule/i);
});

test("enumerates only centrifugal pump scopes from prepared topology nodes", () => {
  assert.deepEqual(
    enumerateCentrifugalPumpScopes({
      topology_view: {
        nodes: [
          { id: "node-p101", tag_name: "P-101", class_name: "CentrifugalPump" },
          { id: "node-h1009", tag_name: "H-1009", class_name: "PlateHeatExchanger" },
          { id: "node-p4713", tag_name: "P-4713", class_name: "CentrifugalPump" },
        ],
      },
    }),
    ["P-101", "P-4713"],
  );
});
