import assert from "node:assert/strict";
import test from "node:test";
import { deriveTurnSteps } from "./turn-steps.ts";

test("deriveTurnSteps: immediate answer with no pause -- retrieval + evidence-answer only", () => {
  const turn = {
    events: [
      { type: "tool-progress", data: { status: "started" } },
      { type: "text", data: { text: "Answer." } },
      { type: "evidence", data: { evidence_references: ["node-p101"] } },
      { type: "completion", data: { status: "completed" } },
    ],
  };
  const reduced = { kind: "answered" as const, evidenceReferences: ["node-p101"] };

  const steps = deriveTurnSteps(turn, reduced);

  assert.deepEqual(
    steps.map((s) => s.id),
    ["retrieval", "evidence-answer"],
  );
  assert.equal(steps[0].status, "done");
  assert.equal(steps[0].detail?.kind, "retrieval");
  assert.equal((steps[0].detail as { resumed: boolean }).resumed, false);
  assert.equal(steps[1].status, "done");
  assert.deepEqual((steps[1].detail as { evidenceReferences: string[] }).evidenceReferences, [
    "node-p101",
  ]);
});

test("deriveTurnSteps: datalog-confirmation pause -- retrieval + blocked validation, no answer step", () => {
  const turn = {
    events: [
      { type: "tool-progress", data: { status: "started" } },
      { type: "review-required", data: { review: { datalog_confirmation: {} } } },
    ],
  };
  const reduced = {
    kind: "review-required" as const,
    review: { datalog_confirmation: {} },
  };

  const steps = deriveTurnSteps(turn, reduced);

  assert.deepEqual(
    steps.map((s) => s.id),
    ["retrieval", "validation"],
  );
  assert.equal(steps[1].status, "blocked");
  assert.equal(steps[1].detail?.kind, "datalog-confirmation");
});

test("deriveTurnSteps: direction-review pause -- validation detail kind is direction-review", () => {
  const turn = {
    events: [
      { type: "tool-progress", data: { status: "started" } },
      { type: "review-required", data: { review: { direction_review: {} } } },
    ],
  };
  const reduced = {
    kind: "review-required" as const,
    review: { direction_review: {} },
  };

  const steps = deriveTurnSteps(turn, reduced);

  assert.equal(steps[1].detail?.kind, "direction-review");
});

test("deriveTurnSteps: resumed second message -- retrieval marked resumed, no validation step", () => {
  const turn = {
    events: [
      { type: "tool-progress", data: { status: "started" } },
      { type: "review-required", data: { review: { direction_review: {} } } },
      { type: "tool-progress", data: { status: "resumed" } },
      { type: "text", data: { text: "Confirmed downstream." } },
      { type: "completion", data: { status: "completed" } },
    ],
  };
  const reduced = { kind: "answered" as const, evidenceReferences: [] };

  const steps = deriveTurnSteps(turn, reduced);

  assert.deepEqual(
    steps.map((s) => s.id),
    ["retrieval", "evidence-answer"],
  );
  assert.equal((steps[0].detail as { resumed: boolean }).resumed, true);
  assert.equal(steps[0].label, "Retrieval (resumed)");
});

test("deriveTurnSteps: canceled turn has no steps", () => {
  const turn = { events: [{ type: "tool-progress", data: { status: "started" } }] };
  const steps = deriveTurnSteps(turn, { kind: "canceled" as const });
  assert.deepEqual(steps, []);
});

test("deriveTurnSteps: failed turn has no steps", () => {
  const turn = { events: [{ type: "tool-progress", data: { status: "started" } }] };
  const steps = deriveTurnSteps(turn, { kind: "failed" as const, message: "boom" });
  assert.deepEqual(steps, []);
});

test("deriveTurnSteps: in-progress turn shows a single pending retrieval row (bead 2ki.12)", () => {
  const turn = { events: [{ type: "tool-progress", data: { status: "started" } }] };
  const steps = deriveTurnSteps(turn, { kind: "in-progress" as const });
  assert.deepEqual(steps, [{ id: "retrieval", label: "Retrieval", status: "pending" }]);
});
