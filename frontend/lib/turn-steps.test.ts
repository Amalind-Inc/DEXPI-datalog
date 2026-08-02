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

test("deriveTurnSteps: renders governed execution trace before deterministic evidence", () => {
  const turn = {
    session_id: "session-1",
    turn_id: "turn-1",
    events: [
      { type: "tool-progress", data: { status: "started" } },
      {
        type: "execution-trace",
        data: {
          schema_version: 1,
          event_id: "route-1",
          kind: "grounded_qa.routing.template_proposed",
          category: "routing",
          status: "completed",
          summary: "Routed to template equipment_without_pump_path.",
          occurrence_count: 1,
          evidence_references: [],
          detail: {
            display: "artifact",
            artifact: {
              kind: "execution_trace_detail",
              path: "turns/turn-1.trace/route-1.json",
              media_type: "application/json",
            },
          },
        },
      },
      {
        type: "execution-trace",
        data: {
          schema_version: 1,
          event_id: "evidence-1",
          kind: "grounded_qa.evidence.result_observed",
          category: "evidence",
          status: "completed",
          summary: "Observed deterministic result: violation_found with 1 witness(es).",
          occurrence_count: 1,
          evidence_references: ["tank-t101"],
          detail: {
            display: "artifact",
            artifact: {
              kind: "execution_trace_detail",
              path: "turns/turn-1.trace/evidence-1.json",
              media_type: "application/json",
            },
          },
        },
      },
    ],
  };

  const steps = deriveTurnSteps(turn, {
    kind: "answered" as const,
    evidenceReferences: ["tank-t101"],
  });

  assert.deepEqual(
    steps.map((step) => step.id),
    ["retrieval", "trace:route-1", "trace:evidence-1", "evidence-answer"],
  );
  assert.equal(steps[1].label, "Routed to template equipment_without_pump_path.");
  assert.deepEqual(steps[2].detail, {
    kind: "execution-trace",
    traceKind: "grounded_qa.evidence.result_observed",
    occurrenceCount: 1,
    evidenceReferences: ["tank-t101"],
    artifactPath: "turns/turn-1.trace/evidence-1.json",
    artifactUrl: "/api/review/sessions/session-1/turns/turn-1/trace/evidence-1",
  });
});

test("deriveTurnSteps: preserves governed trace lifecycle statuses", () => {
  const statuses = ["blocked", "canceled", "failed", "running"] as const;
  const turn = {
    events: statuses.map((status, index) => ({
      type: "execution-trace",
      data: {
        schema_version: 1,
        event_id: `event-${index}`,
        kind: `vendor.widget.${status}`,
        status,
        summary: `Widget activity ${status}.`,
        occurrence_count: 1,
        evidence_references: [],
      },
    })),
  };

  const steps = deriveTurnSteps(turn, {
    kind: "answered" as const,
    evidenceReferences: [],
  });

  assert.deepEqual(
    steps.slice(0, 4).map((step) => step.status),
    ["blocked", "canceled", "failed", "pending"],
  );
});

test("deriveTurnSteps: standard retrieval names tools and detailed data stays sanitized", () => {
  const turn = {
    events: [
      { type: "tool-progress", data: { status: "started" } },
      {
        type: "tool-progress",
        data: {
          status: "round",
          round: 1,
          max_rounds: 2,
          tool_name: "get_reachable_equipment",
          tool_input: {
            equipment_id: "pump-1",
            api_key: "must-not-render",
          },
        },
      },
      {
        type: "evidence",
        data: { evidence_references: ["connection-n1"] },
      },
    ],
  };

  const steps = deriveTurnSteps(turn, {
    kind: "answered" as const,
    evidenceReferences: ["connection-n1"],
  });

  assert.equal(steps[0].label, "Retrieval — get_reachable_equipment");
  assert.deepEqual(steps[0].detail, {
    kind: "retrieval",
    resumed: false,
    toolNames: ["get_reachable_equipment"],
    rounds: [
      {
        round: 1,
        maxRounds: 2,
        toolName: "get_reachable_equipment",
        toolInput: { equipment_id: "pump-1" },
      },
    ],
    outputReferences: ["connection-n1"],
  });
});
