import assert from "node:assert/strict";
import test from "node:test";

import { aggregateUniversalRule, buildRuleDerivation } from "./local-ask-execution.ts";
import {
  createClarificationAskRecord,
  createDeterministicAskRecord,
} from "./local-review-inspection.ts";

test("builds a deterministic derivation for one pump", () => {
  const derivation = buildRuleDerivation({
    claim: "Does pump P-4713 have a downstream check valve?",
    ruleId: "pump_discharge_check_valve",
    scopeEntityIds: ["P-4713"],
    checks: [
      {
        scopeEntityId: "P-4713",
        result: {
          deterministic_result: {
            check_id: "pump_discharge_check_valve",
            run_status: "completed",
            outcome: "violated",
            reason_code: "no_check_valve_on_complete_segment",
            evidence: { ordered_topology_ids: ["P-4713", "N-1"] },
          },
        },
      },
    ],
  });

  assert.equal(derivation.outcome, "violated");
  assert.deepEqual(derivation.counterexamples, ["P-4713"]);
  assert.deepEqual(derivation.evaluations[0]?.evidenceIds, ["P-4713", "N-1"]);
  assert.match(derivation.summary, /P-4713/);
});

test("proves a universal rule only when every member passes", () => {
  const derivation = aggregateUniversalRule({
    claim: "Do all centrifugal pumps have a downstream check valve?",
    ruleId: "pump_discharge_check_valve",
    domain: "centrifugal_pumps",
    scopeEntityIds: ["P-101", "P-4713"],
    checks: [
      { scopeEntityId: "P-101", result: result("satisfied") },
      { scopeEntityId: "P-4713", result: result("satisfied") },
    ],
  });

  assert.equal(derivation.outcome, "satisfied");
  assert.equal(derivation.domainComplete, true);
  assert.equal(derivation.evaluations.length, 2);
});

test("disproves a universal rule with a counterexample", () => {
  const derivation = aggregateUniversalRule({
    claim: "Do all centrifugal pumps have a downstream check valve?",
    ruleId: "pump_discharge_check_valve",
    domain: "centrifugal_pumps",
    scopeEntityIds: ["P-101", "P-4713"],
    checks: [
      { scopeEntityId: "P-101", result: result("satisfied") },
      { scopeEntityId: "P-4713", result: result("violated") },
    ],
  });

  assert.equal(derivation.outcome, "violated");
  assert.deepEqual(derivation.counterexamples, ["P-4713"]);
});

test("returns indeterminate when a universal member is unknown", () => {
  const derivation = aggregateUniversalRule({
    claim: "Do all centrifugal pumps have a downstream check valve?",
    ruleId: "pump_discharge_check_valve",
    domain: "centrifugal_pumps",
    scopeEntityIds: ["P-101", "P-4713"],
    checks: [{ scopeEntityId: "P-101", result: result("satisfied") }],
  });

  assert.equal(derivation.outcome, "indeterminate");
  assert.deepEqual(derivation.unknowns, ["P-4713"]);
});

test("does not silently pass an empty universal domain", () => {
  const derivation = aggregateUniversalRule({
    claim: "Do all centrifugal pumps have a downstream check valve?",
    ruleId: "pump_discharge_check_valve",
    domain: "centrifugal_pumps",
    scopeEntityIds: [],
    checks: [],
  });

  assert.equal(derivation.outcome, "indeterminate");
  assert.equal(derivation.emptyDomain, true);
  assert.match(derivation.summary, /no centrifugal pumps/i);
});

test("creates a completed clarification record without pretending to run a tool", () => {
  const record = createClarificationAskRecord({
    turnId: "ask-clarification",
    question: "Must every connected object satisfy the rule?",
    prompt: "I need a precise scope.",
    choices: [
      {
        id: "all-centrifugal-pumps",
        label: "All centrifugal pumps",
        question: "Do all centrifugal pumps have a downstream check valve?",
      },
    ],
    now: () => new Date("2026-08-04T00:00:00.000Z"),
  });

  assert.equal(record.status, "completed");
  assert.equal(record.route, "clarification");
  assert.deepEqual(
    record.clarification?.choices.map((choice) => choice.id),
    ["all-centrifugal-pumps"],
  );
  assert.deepEqual(
    record.events.map((event) => event.type),
    ["turn_started", "turn_completed"],
  );
});

test("creates a completed deterministic Ask record with derivation before interpretation", () => {
  const record = createDeterministicAskRecord({
    turnId: "ask-record",
    question: "Does pump P-4713 have a downstream check valve?",
    route: "rule",
    ruleId: "pump_discharge_check_valve",
    scopeEntityIds: ["P-4713"],
    checks: [{ scopeEntityId: "P-4713", result: result("violated") }],
  });

  assert.equal(record.status, "completed");
  assert.equal(record.route, "rule");
  assert.equal(record.derivation?.outcome, "violated");
  assert.match(record.finalText, /violated/i);
  assert.deepEqual(
    record.events.map((event) => event.type),
    ["turn_started", "tool_request", "tool_result", "turn_completed"],
  );
});

function result(outcome: "satisfied" | "violated") {
  return {
    deterministic_result: {
      check_id: "pump_discharge_check_valve",
      run_status: "completed",
      outcome,
    },
  };
}
