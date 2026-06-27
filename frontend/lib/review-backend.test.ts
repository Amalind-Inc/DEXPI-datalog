import assert from "node:assert/strict";
import test from "node:test";
import {
  answerChatWithReviewBackend,
  executeConfirmedDatalog,
  prepareReviewSession,
  submitDirectionReview,
} from "./review-backend.ts";
import { QA_ANSWER_PREFIX, parseGroundedQAAnswerMessage } from "./grounded-qa-answer.ts";
import { DIRECTION_REVIEW_PREFIX, parseDirectionReviewMessage } from "./direction-review.ts";

test("prepareReviewSession adapts backend topology_view into graph state", async () => {
  const calls: string[] = [];
  const fetcher = async (url: string | URL | Request) => {
    calls.push(String(url));
    return Response.json({
      status: "ready",
      topology_view: {
        nodes: [
          { id: "node-p101", tag_name: "P-101", label: "Pump object" },
          { id: "node-v102", tag_name: "V-102", label: "Valve object" },
        ],
        edges: [
          {
            id: "edge-p-v",
            source_id: "node-p101",
            target_id: "node-v102",
            relationship: "connected_to",
          },
        ],
      },
      visible_source_scope: { ids: ["node-p101"] },
    });
  };

  const result = await prepareReviewSession(
    "session-1",
    { filename: "plant.xml", content: "<PlantModel />" },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(calls, ["http://backend.test/api/review/sessions/session-1/prepare"]);
  assert.equal(result.filename, "plant.xml");
  assert.equal(result.graph.nodes[0].id, "node-p101");
  assert.equal(result.graph.nodes[0].label, "P-101");
  assert.equal(result.graph.edges[0].source, "node-p101");
  assert.deepEqual(result.sourceScopeIds, ["node-p101"]);
});

test("answerChatWithReviewBackend routes topology question through QA harness and returns grounded answer", async () => {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({
      method: init?.method ?? "GET",
      path: parsedUrl.pathname,
      body,
    });

    if (parsedUrl.pathname.endsWith("/source-scope")) {
      return Response.json({ visible_source_scope: { ids: body.source_scope_ids } });
    }
    if (parsedUrl.pathname.endsWith("/provider-settings")) {
      return Response.json({
        provider: body.provider,
        model: body.model,
        configured: true,
      });
    }
    if (parsedUrl.pathname.endsWith("/logic-requests/improve")) {
      return Response.json({
        status: "refinement_ready",
        route: { kind: "topology_logic" },
        refinement: { refined_prompt: body.prompt },
      });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "answered",
        session_id: "session-1",
        answer_text: "From P-101, V-102 is reachable via a piping segment.",
        evidence_references: ["node-p101", "node-v102"],
        evidence_highlight: {
          source_scope_ids: [],
          matched_object_ids: ["node-p101", "node-v102"],
          paths: [
            {
              id: "node-v102",
              node_ids: ["node-p101", "node-nozzle", "node-segment", "node-v102"],
              edge_ids: ["edge-1", "edge-2", "edge-3"],
            },
          ],
        },
      });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      selectedNode: {
        id: "node-p101",
        label: "P-101",
        kind: "Pump",
        description: "Pump",
      },
      messages: [
        {
          role: "user",
          content: "What downstream process objects are reachable?",
        },
      ],
    },
    {
      baseUrl: "http://backend.test",
      fetcher: fetcher as typeof fetch,
      providerSettings: {
        provider: "openrouter",
        model: "openrouter/owl-alpha",
        credential: "sk-hidden",
      },
    },
  );

  assert.deepEqual(
    calls.map((call) => `${call.method} ${call.path}`),
    [
      "PUT /api/review/sessions/session-1/source-scope",
      "PUT /api/review/sessions/session-1/provider-settings",
      "POST /api/review/sessions/session-1/logic-requests/improve",
      "POST /api/review/sessions/session-1/qa-turns",
    ],
  );
  assert.deepEqual(calls[0].body, { source_scope_ids: ["node-p101"] });
  assert.deepEqual(calls[1].body, {
    provider: "openrouter",
    model: "openrouter/owl-alpha",
    credential: "sk-hidden",
  });
  assert.deepEqual(calls[3].body, { question: "What downstream process objects are reachable?" });
  assert.equal(result.status, "answered");
  assert.match(result.message, /^pydexpi:qa-answer:/);
  const parsed = parseGroundedQAAnswerMessage(result.message);
  assert.ok(parsed !== null, "message must parse as a grounded QA answer");
  assert.equal(parsed?.answerText, "From P-101, V-102 is reachable via a piping segment.");
  assert.deepEqual(parsed?.evidenceReferences, ["node-p101", "node-v102"]);
  assert.ok(
    parsed?.evidenceHighlight.paths.length > 0,
    "evidence highlight must include witness paths",
  );
  assert.equal(JSON.stringify(result).includes("sk-hidden"), false);
  assert.ok(
    result.highlightedNodeIds.includes("node-p101") ||
      result.highlightedNodeIds.includes("node-v102"),
  );
});

test("answerChatWithReviewBackend forwards prior QA evidence as conversation state for follow-ups", async () => {
  let qaBody: { question?: string; conversation?: unknown } | null = null;
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (parsedUrl.pathname.endsWith("/source-scope")) {
      return Response.json({ visible_source_scope: { ids: [] } });
    }
    if (parsedUrl.pathname.endsWith("/logic-requests/improve")) {
      return Response.json({
        status: "refinement_ready",
        route: { kind: "topology_logic" },
        refinement: { refined_prompt: body.prompt },
      });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      qaBody = body;
      return Response.json({
        status: "answered",
        session_id: "session-1",
        answer_text: "Continuing with N-1: 2 reachable objects.",
        evidence_references: ["node-n1", "node-seg"],
        interpreted_object_ids: ["node-n1"],
        evidence_highlight: { source_scope_ids: [], matched_object_ids: ["node-n1"], paths: [] },
      });
    }
    return new Response("not found", { status: 404 });
  };

  // A prior assistant QA answer is present in history; the new user message is a follow-up.
  const priorAnswer = serializeGroundedQAAnswerForTest();
  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      selectedNode: null,
      messages: [
        { role: "user", content: "What is reachable from the nozzle?" },
        { role: "assistant", content: priorAnswer },
        { role: "user", content: "What is reachable from those?" },
      ],
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
  );

  assert.equal(result.status, "answered");
  const captured = qaBody as { question?: string; conversation?: unknown } | null;
  assert.ok(captured !== null);
  assert.equal(captured?.question, "What is reachable from those?");
  assert.ok(Array.isArray(captured?.conversation), "conversation must be forwarded");
  const conversation = captured?.conversation as Array<Record<string, unknown>>;
  assert.equal(conversation.length, 1);
  assert.equal(conversation[0].question, "What is reachable from the nozzle?");
  assert.deepEqual(conversation[0].evidence_references, ["node-prior-1", "node-prior-2"]);

  const parsed = parseGroundedQAAnswerMessage(result.message);
  assert.deepEqual(parsed?.interpretedObjectIds, ["node-n1"]);
});

function serializeGroundedQAAnswerForTest(): string {
  return (
    QA_ANSWER_PREFIX +
    JSON.stringify({
      answerText: "From the nozzle, 2 objects are reachable.",
      evidenceReferences: ["node-prior-1", "node-prior-2"],
      interpretedObjectIds: ["node-prior-1"],
      evidenceHighlight: { source_scope_ids: [], matched_object_ids: ["node-prior-1"], paths: [] },
      raw: {},
    })
  );
}

test("answerChatWithReviewBackend surfaces a direction review when flow direction is inferred", async () => {
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (parsedUrl.pathname.endsWith("/logic-requests/improve")) {
      return Response.json({
        status: "refinement_ready",
        route: { kind: "topology_logic" },
        refinement: { refined_prompt: body.prompt },
      });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "needs_direction_review",
        session_id: "session-1",
        question: body.question,
        direction_review: {
          review_key: "direction-abc123",
          proposed_direction: "downstream",
          direction_basis: "inferred",
          review_status: "pending",
          evaluation_boundary: "directed_reachable:downstream",
          basis_explanation: "Flow direction along this witness is inferred.",
          witness: { node_ids: ["node-a", "node-b"], edge_ids: ["edge-1"] },
          evidence_highlight: {
            source_scope_ids: [],
            matched_object_ids: ["node-b"],
            paths: [{ id: "node-b", node_ids: ["node-a", "node-b"], edge_ids: ["edge-1"] }],
          },
          actions: ["confirm", "reverse", "unknown"],
        },
        answer_text: "Please review the inferred flow direction.",
      });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      selectedNode: null,
      messages: [{ role: "user", content: "What is downstream of the piping?" }],
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
  );

  assert.equal(result.status, "needs_direction_review");
  assert.match(result.message, new RegExp("^" + DIRECTION_REVIEW_PREFIX));
  const review = parseDirectionReviewMessage(result.message);
  assert.ok(review !== null);
  assert.equal(review?.proposedDirection, "downstream");
  assert.equal(review?.directionBasis, "inferred");
  assert.equal(review?.reviewKey, "direction-abc123");
  assert.deepEqual(result.highlightedNodeIds.sort(), ["edge-1", "node-a", "node-b"]);
});

test("submitDirectionReview resumes the original question and returns a grounded answer", async () => {
  const calls: Array<{ path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path: parsedUrl.pathname, body });
    return Response.json({
      status: "answered",
      session_id: "session-1",
      answer_text: "Confirmed downstream flow direction. 2 objects reachable.",
      evidence_references: ["node-a", "node-b"],
      interpreted_object_ids: ["node-a"],
      direction: {
        proposed_direction: "downstream",
        effective_direction: "downstream",
        review_status: "confirmed",
      },
      evidence_highlight: {
        source_scope_ids: [],
        matched_object_ids: ["node-a", "node-b"],
        paths: [{ id: "node-b", node_ids: ["node-a", "node-b"], edge_ids: ["edge-1"] }],
      },
    });
  };

  const result = await submitDirectionReview(
    "session-1",
    {
      question: "What is downstream of the piping?",
      decision: "confirm",
      reviewKey: "direction-abc123",
      conversation: [],
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
  );

  assert.equal(calls[0].path, "/api/review/sessions/session-1/direction-reviews");
  assert.deepEqual(calls[0].body, {
    question: "What is downstream of the piping?",
    decision: "confirm",
    review_key: "direction-abc123",
  });
  assert.equal(result.status, "answered");
  assert.match(result.message, new RegExp("^" + QA_ANSWER_PREFIX));
  const parsed = parseGroundedQAAnswerMessage(result.message);
  assert.match(parsed?.answerText ?? "", /Confirmed downstream flow direction/);
});

test("answerChatWithReviewBackend returns an error message when backend is unavailable for Datalog prompts", async () => {
  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      selectedNode: {
        id: "node-p101",
        label: "P-101",
        kind: "Pump",
        description: "Pump",
      },
      messages: [
        {
          role: "user",
          content: "What downstream process objects are reachable from P-101?",
        },
      ],
    },
    {
      baseUrl: "",
      providerSettings: null,
    },
  );

  assert.equal(result.status, undefined);
  assert.doesNotMatch(result.message, /I am grounding this QA answer/);
  assert.match(result.message, /Unable to reach the review backend/);
  assert.equal(result.confirmation, undefined);
});

test("executeConfirmedDatalog proxies confirmed query execution and returns grounded answer envelope", async () => {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    calls.push({
      method: init?.method ?? "GET",
      path: parsedUrl.pathname,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json({
      status: "answered",
      summary: { text: "Deterministic execution produced 1 evidence item." },
      evidence: {
        display: "expandable",
        items: [{ id: "node-p101", label: "P-101" }],
      },
      evidence_highlight: {
        source_scope_ids: ["node-p101"],
        matched_object_ids: ["node-p101"],
        paths: [],
      },
    });
  };

  const result = await executeConfirmedDatalog(
    "session-1",
    { status: "confirmation_ready" },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(
    calls.map((call) => `${call.method} ${call.path}`),
    ["POST /api/review/sessions/session-1/logic-requests/execute"],
  );
  assert.deepEqual(calls[0].body, {
    confirmation: { status: "confirmation_ready" },
  });
  assert.equal(result.status, "answered");
  assert.match(result.message, /^pydexpi:logic-answer:/);
  assert.deepEqual(result.highlightedNodeIds, ["node-p101"]);
});

test("executeConfirmedDatalog fails instead of fabricating local evidence when backend execution is unavailable", async () => {
  const fetcher = async () => new Response("unavailable", { status: 503 });

  await assert.rejects(
    () =>
      executeConfirmedDatalog(
        "session-1",
        { status: "confirmation_ready" },
        { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
      ),
    /Python review backend did not execute the confirmed Datalog query/,
  );
});

test("executeConfirmedDatalog rejects backend execution diagnostics instead of rendering an answer", async () => {
  const fetcher = async () =>
    Response.json({
      status: "execution_failed",
      summary: {
        text: "Generated Datalog answered unknown topology object(s): deterministic-evidence",
      },
      evidence: {
        display: "expandable",
        items: [],
      },
      diagnostics: [
        {
          code: "generated_datalog.answer_unresolved",
          message: "Generated Datalog answered unknown topology object(s): deterministic-evidence",
        },
      ],
    });

  await assert.rejects(
    () =>
      executeConfirmedDatalog(
        "session-1",
        { status: "confirmation_ready" },
        { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
      ),
    /Generated Datalog answered unknown topology object/,
  );
});
