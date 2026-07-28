import assert from "node:assert/strict";
import test from "node:test";
import {
  cancelTurn,
  computeTurnId,
  readTurnIdentity,
  reduceTurn,
  resumeDirectionReview,
  startTurn,
  turnToMessage,
  type TurnState,
} from "./turn-client.ts";
import { parseDirectionReviewMessage } from "./direction-review.ts";
import { parseDatalogConfirmationMessage } from "./datalog-confirmation.ts";

function mockTurn(overrides: Partial<TurnState> = {}): TurnState {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    status: "completed",
    events: [],
    question: "What changed?",
    request_id: "request-1",
    ...overrides,
  };
}

test("reduceTurn returns answered with text and evidence from turn events", () => {
  const evidenceHighlight = {
    source_scope_ids: ["node-p101"],
    matched_object_ids: ["node-v102", "node-p101"],
    paths: [{ node_ids: ["node-x"], edge_ids: ["edge-y"] }],
  };
  const turn = mockTurn({
    events: [
      { sequence: 1, type: "tool-progress", data: { status: "started" } },
      { sequence: 2, type: "text", data: { text: "Pump " } },
      { sequence: 3, type: "text", data: { text: "answered." } },
      {
        sequence: 4,
        type: "evidence",
        data: {
          evidence_references: ["ref-1"],
          evidence_highlight: evidenceHighlight,
        },
      },
      { sequence: 5, type: "completion", data: { status: "completed" } },
    ],
    result: { conversation_state: [{ role: "assistant", text: "Pump answered." }] },
  });

  const reduced = reduceTurn(turn);

  assert.equal(reduced.kind, "answered");
  assert.equal(reduced.text, "Pump answered.");
  assert.deepEqual(reduced.highlightedNodeIds, ["node-p101", "node-v102", "node-x", "edge-y"]);
  assert.deepEqual(reduced.conversationState, [{ role: "assistant", text: "Pump answered." }]);
  assert.deepEqual(reduced.evidenceReferences, ["ref-1"]);
  assert.deepEqual(reduced.evidenceHighlight, evidenceHighlight);
});

test("reduceTurn returns review-required when review-required event present", () => {
  const review = { review_key: "direction", status: "pending" };
  const turn = mockTurn({
    status: "paused",
    events: [{ sequence: 1, type: "review-required", data: { review } }],
  });

  const reduced = reduceTurn(turn);

  assert.equal(reduced.kind, "review-required");
  assert.deepEqual(reduced.review, review);
});

test("reduceTurn returns canceled for cancellation event", () => {
  const turn = mockTurn({
    events: [{ sequence: 1, type: "cancellation", data: { reason: "user" } }],
  });

  assert.deepEqual(reduceTurn(turn), { kind: "canceled" });
});

test("reduceTurn returns failed for failure event", () => {
  const turn = mockTurn({
    events: [{ sequence: 1, type: "failure", data: { message: "backend failed" } }],
  });

  assert.deepEqual(reduceTurn(turn), { kind: "failed", message: "backend failed" });
});

test("reduceTurn returns in-progress for an active turn with no terminal event yet (bead 2ki.12)", () => {
  const turn = mockTurn({
    status: "active",
    events: [{ sequence: 1, type: "tool-progress", data: { status: "started" } }],
  });

  assert.deepEqual(reduceTurn(turn), { kind: "in-progress" });
});

test("startTurn POSTs to correct path with request_id and returns TurnState", async () => {
  const returned = mockTurn();
  const calls: Array<{ path: string; method: string | undefined; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      path: new URL(String(url)).pathname,
      method: init?.method,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json(returned);
  };

  const result = await startTurn(
    "session-1",
    { question: "What changed?", requestId: "request-1", conversation: [{ role: "user" }] },
    { baseUrl: "http://frontend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(result, returned);
  assert.deepEqual(calls, [
    {
      path: "/api/review/sessions/session-1/turns",
      method: "POST",
      body: {
        question: "What changed?",
        request_id: "request-1",
        conversation: [{ role: "user" }],
      },
    },
  ]);
});

test("startTurn attaches the browser's active BYOK provider to the turn body", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const fetcher = async (_url: string | URL | Request, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
    return Response.json(mockTurn());
  };

  await startTurn(
    "session-1",
    { question: "What changed?", requestId: "request-1" },
    {
      baseUrl: "http://frontend.test",
      fetcher: fetcher as typeof fetch,
      providerSettings: { provider: "openai", model: "gpt-4.1", credential: "sk-user-key" },
    },
  );

  assert.deepEqual(bodies[0].provider_settings, {
    provider: "openai",
    model: "gpt-4.1",
    credential: "sk-user-key",
  });
});

test("startTurn omits provider_settings entirely when the browser has no key", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const fetcher = async (_url: string | URL | Request, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
    return Response.json(mockTurn());
  };

  await startTurn(
    "session-1",
    { question: "What changed?", requestId: "request-1" },
    { baseUrl: "http://frontend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
  );

  assert.equal("provider_settings" in bodies[0], false);
});

test("cancelTurn POSTs to cancel path", async () => {
  const returned = mockTurn({ status: "canceled" });
  const calls: Array<{ path: string; method: string | undefined }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ path: new URL(String(url)).pathname, method: init?.method });
    return Response.json(returned);
  };

  const result = await cancelTurn("session-1", "turn-1", {
    baseUrl: "http://frontend.test",
    fetcher: fetcher as typeof fetch,
  });

  assert.deepEqual(result, returned);
  assert.deepEqual(calls, [
    { path: "/api/review/sessions/session-1/turns/turn-1/cancel", method: "POST" },
  ]);
});

test("resumeDirectionReview POSTs decision and review_key", async () => {
  const returned = mockTurn();
  const calls: Array<{ path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      path: new URL(String(url)).pathname,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json(returned);
  };

  const result = await resumeDirectionReview(
    "session-1",
    "turn-1",
    { decision: "accept", reviewKey: "review-1" },
    { baseUrl: "http://frontend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(result, returned);
  assert.deepEqual(calls, [
    {
      path: "/api/review/sessions/session-1/turns/turn-1/direction-review",
      body: { decision: "accept", review_key: "review-1" },
    },
  ]);
});

test("resumeDirectionReview POSTs a batch of independent direction-review decisions", async () => {
  const returned = mockTurn();
  const calls: Array<{ path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      path: new URL(String(url)).pathname,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json(returned);
  };

  const result = await resumeDirectionReview(
    "session-1",
    "turn-1",
    {
      directionReviews: [
        { reviewKey: "review-a", decision: "confirm" },
        { reviewKey: "review-b", decision: "unknown" },
      ],
    },
    { baseUrl: "http://frontend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(result, returned);
  assert.deepEqual(calls, [
    {
      path: "/api/review/sessions/session-1/turns/turn-1/direction-review",
      body: {
        direction_reviews: [
          { review_key: "review-a", decision: "confirm" },
          { review_key: "review-b", decision: "unknown" },
        ],
      },
    },
  ]);
});

test("reduceTurn pulls conversationState from turn.result not events", () => {
  const conversationState = [{ role: "assistant", content: "stored state" }];
  const turn = mockTurn({
    events: [],
    result: { conversation_state: conversationState },
  });

  const reduced = reduceTurn(turn);

  assert.equal(reduced.kind, "answered");
  assert.deepEqual(reduced.conversationState, conversationState);
});

test("reduceTurn returns canceled when cancellation event follows review-required", () => {
  // A paused turn that was subsequently canceled has both a review-required event
  // and a later cancellation event. The terminal cancellation must win.
  const turn = mockTurn({
    status: "canceled",
    events: [
      { sequence: 0, type: "tool-progress", data: { status: "started" } },
      {
        sequence: 1,
        type: "review-required",
        data: { review: { status: "needs_direction_review" } },
      },
      { sequence: 2, type: "cancellation", data: { message: "Canceled by user." } },
    ],
  });
  const reduced = reduceTurn(turn);
  assert.equal(reduced.kind, "canceled");
});

test("reduceTurn returns failed when failure event follows review-required", () => {
  const turn = mockTurn({
    status: "failed",
    events: [
      { sequence: 0, type: "tool-progress", data: { status: "started" } },
      {
        sequence: 1,
        type: "review-required",
        data: { review: { status: "needs_direction_review" } },
      },
      { sequence: 2, type: "failure", data: { message: "Backend error." } },
    ],
  });
  const reduced = reduceTurn(turn);
  assert.equal(reduced.kind, "failed");
  assert.equal("message" in reduced && reduced.message, "Backend error.");
});

test("turnToMessage tags a direction-review-required turn with turn identity for resume", () => {
  const turn = mockTurn({
    turn_id: "turn-abc",
    session_id: "session-xyz",
    status: "paused",
    events: [
      { sequence: 0, type: "tool-progress", data: { status: "started" } },
      {
        sequence: 1,
        type: "review-required",
        data: {
          review: {
            status: "needs_direction_review",
            question: "What is downstream of the pump?",
            direction_review: {
              review_key: "review-key-1",
              proposed_direction: "downstream",
              direction_basis: "inferred",
              basis_explanation: "The path traverses composition edges.",
              evidence_highlight: {
                source_scope_ids: [],
                matched_object_ids: ["node-p101"],
                paths: [],
              },
            },
          },
        },
      },
    ],
  });

  const converted = turnToMessage(turn);

  assert.equal(converted.status, "needs_direction_review");
  const parsed = parseDirectionReviewMessage(converted.message);
  assert.ok(parsed !== null, "message must parse as a direction review");
  assert.equal(parsed?.reviewKey, "review-key-1");
  assert.equal(parsed?.proposedDirection, "downstream");
  const identity = readTurnIdentity(parsed!.raw);
  assert.equal(identity.turnId, "turn-abc");
  assert.equal(identity.sessionId, "session-xyz");
});

test("turnToMessage preserves batched direction-review items", () => {
  const turn = mockTurn({
    turn_id: "turn-batch",
    session_id: "session-xyz",
    status: "paused",
    events: [
      {
        sequence: 1,
        type: "review-required",
        data: {
          review: {
            status: "needs_direction_review",
            question: "Do all pumps have downstream valves?",
            direction_reviews: [
              {
                review_key: "review-a",
                object_id: "pump-a",
                proposed_direction: "downstream",
                direction_basis: "inferred",
                basis_explanation: "First inferred path.",
                evidence_highlight: {
                  source_scope_ids: [],
                  matched_object_ids: ["pump-a"],
                  paths: [],
                },
              },
              {
                review_key: "review-b",
                object_id: "pump-b",
                proposed_direction: "downstream",
                direction_basis: "inferred",
                basis_explanation: "Second inferred path.",
                evidence_highlight: {
                  source_scope_ids: [],
                  matched_object_ids: ["pump-b"],
                  paths: [],
                },
              },
            ],
            direction_review: {
              review_key: "review-a",
              object_id: "pump-a",
              proposed_direction: "downstream",
              direction_basis: "inferred",
              basis_explanation: "First inferred path.",
              evidence_highlight: {
                source_scope_ids: [],
                matched_object_ids: ["pump-a"],
                paths: [],
              },
            },
          },
        },
      },
    ],
  });

  const converted = turnToMessage(turn);
  const parsed = parseDirectionReviewMessage(converted.message);

  assert.equal(converted.status, "needs_direction_review");
  assert.equal(parsed?.items.length, 2);
  assert.deepEqual(
    parsed?.items.map((item) => item.reviewKey),
    ["review-a", "review-b"],
  );
  assert.deepEqual(
    parsed?.items.map((item) => item.objectId),
    ["pump-a", "pump-b"],
  );
});

test("turnToMessage tags a datalog-confirmation-required turn with turn identity for resume", () => {
  const turn = mockTurn({
    turn_id: "turn-def",
    session_id: "session-xyz",
    status: "paused",
    events: [
      {
        sequence: 0,
        type: "review-required",
        data: {
          review: {
            status: "needs_datalog_confirmation",
            datalog_confirmation: {
              plain_language_meaning: "Find pumps with no discharge check valve.",
              generated_datalog: "result(X) :- pump(X), not has_check_valve(X).",
              validation: { status: "valid" },
              allowed_actions: ["run", "cancel"],
            },
          },
        },
      },
    ],
  });

  const converted = turnToMessage(turn);

  assert.equal(converted.status, "needs_datalog_confirmation");
  const parsed = parseDatalogConfirmationMessage(converted.message);
  assert.ok(parsed !== null, "message must parse as a datalog confirmation");
  assert.equal(parsed?.generatedDatalog, "result(X) :- pump(X), not has_check_valve(X).");
  const identity = readTurnIdentity(parsed!.raw);
  assert.equal(identity.turnId, "turn-def");
  assert.equal(identity.sessionId, "session-xyz");
});

test("turnToMessage returns canceled/failed status without a turn-scoped identity", () => {
  const canceledTurn = mockTurn({
    events: [{ sequence: 0, type: "cancellation", data: { message: "Canceled by user." } }],
  });
  assert.equal(turnToMessage(canceledTurn).status, "canceled");

  const failedTurn = mockTurn({
    events: [{ sequence: 0, type: "failure", data: { message: "Backend error." } }],
  });
  const failedMessage = turnToMessage(failedTurn);
  assert.equal(failedMessage.status, "failed");
  assert.equal(failedMessage.message, "Backend error.");
});

test("computeTurnId matches the backend TurnLifecycleStore formula", async () => {
  // Reference value computed with Python:
  // hashlib.sha256(b"cross-check-session\ncross-check-request").hexdigest()[:20]
  const turnId = await computeTurnId("cross-check-session", "cross-check-request");
  assert.equal(turnId, "6bfc7fb7461891122bfe");
});

test("turnToMessage renders rule-pack results as grounded logic answers", () => {
  const turn = mockTurn({
    events: [
      {
        sequence: 1,
        type: "evidence",
        data: {
          evidence_references: [],
          evidence_highlight: {
            source_scope_ids: [],
            matched_object_ids: ["node-p101"],
            paths: [],
          },
        },
      },
      { sequence: 2, type: "completion", data: { status: "completed" } },
    ],
    result: {
      status: "answered",
      rule_id: "pump_discharge_check_valve",
      pack: { pack_id: "demo-process-safety", trust_notice: "Demonstration content only." },
      outcome: "violated",
      summary: { text: "pump_discharge_check_valve: violated." },
      result_artifact: { kind: "rule_pack_result", path: "/tmp/result.json" },
      evidence: { display: "expandable", items: [{ id: "node-p101" }] },
      evidence_highlight: {
        source_scope_ids: [],
        matched_object_ids: ["node-p101"],
        paths: [],
      },
    },
  });

  const message = turnToMessage(turn);

  assert.equal(message.status, "answered");
  assert.ok(message.message.startsWith("pydexpi:logic-answer:"));
  const parsed = JSON.parse(message.message.slice("pydexpi:logic-answer:".length));
  assert.equal(parsed.summary, "pump_discharge_check_valve: violated. Demonstration content only.");
  assert.deepEqual(parsed.highlightedNodeIds, ["node-p101"]);
  assert.deepEqual(parsed.rawEvidence.items, [{ id: "node-p101" }]);
  assert.deepEqual(message.highlightedNodeIds, ["node-p101"]);
});

test("reduceTurn: completion after a resumed review-required wins over the stale review card", () => {
  // A paused turn keeps its review-required event; resume appends the answer +
  // completion to the SAME turn. The completion must win so the turn renders a
  // grounded answer, not a second review card.
  const turn = mockTurn({
    status: "completed",
    events: [
      { sequence: 0, type: "tool-progress", data: { status: "started" } },
      { sequence: 1, type: "review-required", data: { review: { review_key: "direction" } } },
      { sequence: 2, type: "tool-progress", data: { status: "resumed" } },
      { sequence: 3, type: "text", data: { text: "Confirmed downstream flow direction." } },
      { sequence: 4, type: "completion", data: { status: "completed" } },
    ],
    result: { answer_text: "Confirmed downstream flow direction." },
  });

  const reduced = reduceTurn(turn);
  assert.equal(reduced.kind, "answered");
  assert.equal(reduced.text, "Confirmed downstream flow direction.");
});

test("reduceTurn: cancellation still wins over review-required and completion", () => {
  const turn = mockTurn({
    status: "canceled",
    events: [
      { sequence: 0, type: "review-required", data: { review: { review_key: "direction" } } },
      { sequence: 1, type: "cancellation", data: { message: "canceled" } },
    ],
  });
  assert.equal(reduceTurn(turn).kind, "canceled");
});

test("turnToMessage: interpreted_object_ids array is preserved (not dropped as a record)", () => {
  const turn = mockTurn({
    status: "completed",
    events: [
      { sequence: 0, type: "text", data: { text: "Ambiguous; 3 candidates." } },
      { sequence: 1, type: "completion", data: { status: "completed" } },
    ],
    result: {
      answer_text: "Ambiguous; 3 candidates.",
      interpreted_object_ids: ["node-a", "node-b", "node-c"],
    },
  });

  const message = turnToMessage(turn);
  assert.equal(message.status, "answered");
  // The serialized QA answer must carry all three interpreted object ids so the
  // UI renders three interpretation chips.
  assert.ok(message.message.includes("node-a"));
  assert.ok(message.message.includes("node-b"));
  assert.ok(message.message.includes("node-c"));
});
