import assert from "node:assert/strict";
import test from "node:test";
import {
  answerChatWithReviewBackend,
  executeConfirmedDatalog,
  getTurnFromBackend,
  getTurnTraceDetailFromBackend,
  prepareReviewSession,
  startTurnOnBackend,
  submitDirectionReview,
  submitTemporaryDatalogReview,
} from "./review-backend.ts";
import { QA_ANSWER_PREFIX, parseGroundedQAAnswerMessage } from "./grounded-qa-answer.ts";
import { DIRECTION_REVIEW_PREFIX, parseDirectionReviewMessage } from "./direction-review.ts";
import {
  DATALOG_CONFIRMATION_PREFIX,
  parseDatalogConfirmationMessage,
} from "./datalog-confirmation.ts";

test("explicit bundled pump check command runs trusted-pack endpoint without confirmation", async () => {
  const calls: Array<{ path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path, body });
    return Response.json({
      status: "answered",
      rule_id: "pump_discharge_check_valve",
      outcome: "violated",
      confirmation: { required: false },
      pack: {
        pack_id: "demo-process-safety",
        authoritative: false,
        trust_notice: "Demonstration content only; not authoritative.",
      },
      summary: { text: "pump_discharge_check_valve: violated." },
      evidence: { items: [{ id: "node-p101" }] },
      evidence_highlight: {
        source_scope_ids: [],
        matched_object_ids: ["node-p101"],
        paths: [],
      },
    });
  };

  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      messages: [{ role: "user", content: "Run the bundled pump discharge check." }],
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(calls, [
    {
      path: "/api/review/sessions/session-1/rule-pack-results",
      body: {
        pack_id: "demo-process-safety",
        rule_id: "pump_discharge_check_valve",
      },
    },
  ]);
  assert.equal(result.status, "answered");
  assert.match(result.message, /violated/);
  assert.match(result.message, /not authoritative/i);
  assert.deepEqual(result.highlightedNodeIds, ["node-p101"]);
});

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
        model: "anthropic/claude-sonnet-4",
        credential: "sk-hidden",
      },
    },
  );

  // With a tool-calling model configured, chat goes straight to the agentic QA
  // harness — no keyword-router (improve) round-trip.
  assert.deepEqual(
    calls.map((call) => `${call.method} ${call.path}`),
    [
      "PUT /api/review/sessions/session-1/source-scope",
      "PUT /api/review/sessions/session-1/provider-settings",
      "POST /api/review/sessions/session-1/qa-turns",
    ],
  );
  assert.deepEqual(calls[0].body, { source_scope_ids: ["node-p101"] });
  assert.deepEqual(calls[1].body, {
    provider: "openrouter",
    model: "anthropic/claude-sonnet-4",
    credential: "sk-hidden",
  });
  assert.deepEqual(calls[2].body, { question: "What downstream process objects are reachable?" });
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

test("answerChatWithReviewBackend sends open conversation to the harness instead of rejecting it", async () => {
  const paths: string[] = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    paths.push(parsedUrl.pathname);
    if (parsedUrl.pathname.endsWith("/provider-settings")) {
      return Response.json({ provider: "openrouter", model: "m", configured: true });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "answered",
        session_id: "session-1",
        answer_text: "Sure — ask me anything about the loaded P&ID and I'll dig in.",
        evidence_references: [],
        evidence_highlight: { source_scope_ids: [], matched_object_ids: [], paths: [] },
      });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      selectedNode: null,
      messages: [{ role: "user", content: "bro i need help" }],
    },
    {
      baseUrl: "http://backend.test",
      fetcher: fetcher as typeof fetch,
      providerSettings: { provider: "openrouter", model: "m", credential: "sk-x" },
    },
  );

  // A non-topology message must not hit the keyword router or be rejected.
  assert.ok(!paths.some((p) => p.endsWith("/logic-requests/improve")));
  assert.ok(paths.some((p) => p.endsWith("/qa-turns")));
  assert.equal(result.status, "answered");
  const parsed = parseGroundedQAAnswerMessage(result.message);
  assert.match(parsed?.answerText ?? "", /ask me anything/);
});

test("answerChatWithReviewBackend forwards prior QA evidence as conversation state for follow-ups", async () => {
  let qaBody: { question?: string; conversation?: unknown } | null = null;
  const paths: string[] = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    paths.push(parsedUrl.pathname);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (parsedUrl.pathname.endsWith("/source-scope")) {
      return Response.json({ visible_source_scope: { ids: [] } });
    }
    if (parsedUrl.pathname.endsWith("/logic-requests/improve")) {
      return Response.json({
        status: "needs_clarification",
        diagnostics: [
          {
            code: "logic_request.needs_clarification",
            message:
              "The request is too vague to route safely. Clarify the object, relationship, and expected condition.",
          },
        ],
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
        { role: "user", content: "What does that mean?" },
      ],
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
  );

  assert.equal(result.status, "answered");
  const captured = qaBody as { question?: string; conversation?: unknown } | null;
  assert.ok(captured !== null);
  assert.equal(captured?.question, "What does that mean?");
  assert.equal(
    paths.some((path) => path.endsWith("/logic-requests/improve")),
    false,
    "a grounded follow-up must not be preempted by the legacy logic-request router",
  );
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

test("answerChatWithReviewBackend returns confirmation for rule-shaped Datalog prompts", async () => {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method: init?.method ?? "GET", path: parsedUrl.pathname, body });
    if (parsedUrl.pathname.endsWith("/logic-requests/improve")) {
      return Response.json({
        status: "refinement_ready",
        route: { kind: "topology_logic" },
        refinement: {
          refined_prompt: "Must every connected object satisfy the temporary topology rule?",
          scope: { kind: "whole_pid" },
          source_scope_ids: [],
        },
      });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "needs_datalog_confirmation",
        session_id: "session-1",
        question: "Must every connected object satisfy the temporary topology rule?",
        datalog_confirmation: {
          review_status: "pending",
          allowed_actions: ["run", "cancel"],
          plain_language_meaning: "Return objects that satisfy the temporary topology rule.",
          generated_datalog: '.decl answer(x:symbol)\n.output answer\nanswer("node-p101").',
          validation: { status: "safe_to_confirm" },
          proposal_result: { executed: false },
        },
      });
    }
    return new Response("unexpected", { status: 500 });
  };

  const result = await answerChatWithReviewBackend(
    {
      sessionId: "session-1",
      messages: [
        {
          role: "user",
          content: "Must every connected object satisfy the temporary topology rule?",
        },
      ],
    },
    {
      baseUrl: "http://backend.test",
      fetcher: fetcher as typeof fetch,
      providerSettings: null,
    },
  );

  assert.equal(result.status, "confirmation_ready");
  assert.match(result.message, new RegExp(`^${DATALOG_CONFIRMATION_PREFIX}`));
  const confirmation = parseDatalogConfirmationMessage(result.message);
  assert.ok(confirmation);
  assert.equal(confirmation.validationStatus, "safe_to_confirm");
  assert.equal(
    confirmation.plainLanguageMeaning,
    "Return objects that satisfy the temporary topology rule.",
  );
  assert.deepEqual(
    calls.map((call) => `${call.method} ${call.path}`),
    [
      "POST /api/review/sessions/session-1/logic-requests/improve",
      "POST /api/review/sessions/session-1/qa-turns",
    ],
  );
});

test("submitTemporaryDatalogReview confirms native proposal through backend endpoint", async () => {
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
      answer_text: "Return objects matching the temporary topology rule.",
      evidence: {
        display: "expandable",
        items: [{ id: "node-p101", label: "P-101" }],
      },
      evidence_highlight: {
        source_scope_ids: [],
        matched_object_ids: ["node-p101"],
        paths: [],
      },
    });
  };

  const result = await submitTemporaryDatalogReview(
    "session-1",
    {
      question: "Must every connected object satisfy the temporary topology rule?",
      decision: "confirm",
      proposalResult: { proposal: { proposal_id: "abc" } },
    },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
  );

  assert.deepEqual(calls, [
    {
      method: "POST",
      path: "/api/review/sessions/session-1/temporary-datalog-reviews",
      body: {
        question: "Must every connected object satisfy the temporary topology rule?",
        decision: "confirm",
        proposal_result: { proposal: { proposal_id: "abc" } },
      },
    },
  ]);
  assert.equal(result.status, "answered");
  assert.match(result.message, /^pydexpi:logic-answer:/);
  assert.deepEqual(result.highlightedNodeIds, ["node-p101"]);
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

test("OLLAMA_MODEL env routes provider-settings PUT to ollama with base_url", async () => {
  const prev = {
    OLLAMA_MODEL: process.env.OLLAMA_MODEL,
    OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY,
  };
  process.env.OLLAMA_MODEL = "ornith:35b";
  delete process.env.OPENROUTER_API_KEY;

  const calls: Array<{ body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (init?.method === "PUT" && parsedUrl.pathname.endsWith("/provider-settings")) {
      calls.push({ body });
      return Response.json({ provider: body.provider, model: body.model, configured: true });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "answered",
        answer_text: "ok",
        evidence_references: [],
        evidence_highlight: { source_scope_ids: [], matched_object_ids: [], paths: [] },
      });
    }
    return Response.json({});
  };

  try {
    await answerChatWithReviewBackend(
      {
        sessionId: "session-1",
        messages: [{ role: "user", content: "What is connected to the pump?" }],
      },
      { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
    );

    assert.equal(calls.length, 1);
    const sent = calls[0].body as Record<string, unknown>;
    assert.equal(sent.provider, "ollama");
    assert.equal(sent.model, "ornith:35b");
    assert.equal(sent.credential, "");
    assert.equal(sent.base_url, "http://localhost:11434/v1");
  } finally {
    if (prev.OLLAMA_MODEL === undefined) delete process.env.OLLAMA_MODEL;
    else process.env.OLLAMA_MODEL = prev.OLLAMA_MODEL;
    if (prev.OPENROUTER_API_KEY === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = prev.OPENROUTER_API_KEY;
  }
});

test("OLLAMA_MODEL takes precedence over OPENROUTER_API_KEY in env routing", async () => {
  const prev = {
    OLLAMA_MODEL: process.env.OLLAMA_MODEL,
    OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY,
  };
  process.env.OLLAMA_MODEL = "ornith:35b";
  process.env.OPENROUTER_API_KEY = "sk-or-fake";

  const calls: Array<{ body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const parsedUrl = new URL(String(url));
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (init?.method === "PUT" && parsedUrl.pathname.endsWith("/provider-settings")) {
      calls.push({ body });
      return Response.json({ provider: body.provider, model: body.model, configured: true });
    }
    if (parsedUrl.pathname.endsWith("/qa-turns")) {
      return Response.json({
        status: "answered",
        answer_text: "ok",
        evidence_references: [],
        evidence_highlight: { source_scope_ids: [], matched_object_ids: [], paths: [] },
      });
    }
    return Response.json({});
  };

  try {
    await answerChatWithReviewBackend(
      {
        sessionId: "session-1",
        messages: [{ role: "user", content: "What is connected to the pump?" }],
      },
      { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch },
    );

    assert.equal(calls.length, 1);
    const sent = calls[0].body as Record<string, unknown>;
    assert.equal(sent.provider, "ollama", "ollama must win over openrouter when OLLAMA_MODEL set");
    assert.notEqual(sent.provider, "openrouter");
  } finally {
    if (prev.OLLAMA_MODEL === undefined) delete process.env.OLLAMA_MODEL;
    else process.env.OLLAMA_MODEL = prev.OLLAMA_MODEL;
    if (prev.OPENROUTER_API_KEY === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = prev.OPENROUTER_API_KEY;
  }
});

test("startTurnOnBackend applies source scope and provider settings before starting the turn", async () => {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    calls.push({
      method: init?.method ?? "GET",
      path,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json({ turn_id: "turn-1", status: "completed", events: [] });
  };

  const turn = await startTurnOnBackend(
    "session-1",
    {
      question: "What is downstream of the pump?",
      request_id: "req-1",
      conversation: [],
      selected_node_id: "node-p101",
    },
    {
      baseUrl: "http://backend.test",
      fetcher: fetcher as typeof fetch,
      // Non-test credential: provider-settings PUT fires.
      providerSettings: { provider: "ollama", model: "llama3", credential: "ollama-local" },
    },
  );

  assert.deepEqual(
    calls.map((call) => [call.method, call.path]),
    [
      ["PUT", "/api/review/sessions/session-1/source-scope"],
      ["PUT", "/api/review/sessions/session-1/provider-settings"],
      ["POST", "/api/review/sessions/session-1/turns"],
    ],
  );
  assert.deepEqual(calls[0].body, { source_scope_ids: ["node-p101"] });
  assert.deepEqual(calls[1].body, {
    provider: "ollama",
    model: "llama3",
    credential: "ollama-local",
  });
  // selected_node_id is frontend routing state, never part of the turn body.
  assert.deepEqual(calls[2].body, {
    question: "What is downstream of the pump?",
    request_id: "req-1",
    conversation: [],
  });
  assert.equal(turn.turn_id, "turn-1");
});

test("startTurnOnBackend skips provider-settings PUT for test sentinel credentials", async () => {
  const paths: string[] = [];
  const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
    paths.push(`${init?.method ?? "GET"} ${new URL(String(url)).pathname}`);
    return Response.json({ turn_id: "turn-1", status: "completed", events: [] });
  };

  await startTurnOnBackend(
    "session-1",
    { question: "q", request_id: "req-1" },
    {
      baseUrl: "http://backend.test",
      fetcher: fetcher as typeof fetch,
      providerSettings: { provider: "openai", model: "gpt-4.1", credential: "sk-test-sentinel" },
    },
  );

  // provider-settings PUT must be absent; only the turn POST fires.
  assert.deepEqual(paths, ["POST /api/review/sessions/session-1/turns"]);
});

test("startTurnOnBackend scope failure throws (caller must resolve real node ids)", async () => {
  const fetcher = async (url: string | URL | Request) => {
    if (String(url).endsWith("/source-scope")) return new Response("bad node", { status: 400 });
    return Response.json({ turn_id: "turn-1", status: "completed", events: [] });
  };

  await assert.rejects(
    startTurnOnBackend(
      "session-1",
      { question: "q", request_id: "req-1", selected_node_id: "invalid-node" },
      { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
    ),
    /source-scope update failed/,
  );
});

test("startTurnOnBackend skips source-scope PUT without a selected node", async () => {
  const paths: string[] = [];
  const fetcher = async (url: string | URL | Request) => {
    paths.push(new URL(String(url)).pathname);
    return Response.json({ turn_id: "turn-1", status: "completed", events: [] });
  };

  await startTurnOnBackend(
    "session-1",
    { question: "q", request_id: "req-1" },
    { baseUrl: "http://backend.test", fetcher: fetcher as typeof fetch, providerSettings: null },
  );

  assert.deepEqual(paths, ["/api/review/sessions/session-1/turns"]);
});

test("getTurnFromBackend preserves the backend HTTP status for failures", async () => {
  const notFound = await getTurnFromBackend("session-1", "missing-turn", {
    baseUrl: "http://backend.test",
    fetcher: (async () => new Response("nope", { status: 404 })) as typeof fetch,
  });
  assert.deepEqual(notFound, { turn: null, status: 404 });

  const backendDown = await getTurnFromBackend("session-1", "turn-1", {
    baseUrl: "http://backend.test",
    fetcher: (async () => new Response("boom", { status: 500 })) as typeof fetch,
  });
  assert.deepEqual(backendDown, { turn: null, status: 500 });

  const ok = await getTurnFromBackend("session-1", "turn-1", {
    baseUrl: "http://backend.test",
    fetcher: (async () =>
      Response.json({ turn_id: "turn-1", status: "completed" })) as typeof fetch,
  });
  assert.equal(ok.status, 200);
  assert.deepEqual(ok.turn, { turn_id: "turn-1", status: "completed" });
});

test("getTurnTraceDetailFromBackend proxies bounded artifacts and statuses", async () => {
  const paths: string[] = [];
  const ok = await getTurnTraceDetailFromBackend("session one", "turn/one", "event one", {
    baseUrl: "http://backend.test",
    fetcher: (async (url: string | URL | Request) => {
      paths.push(new URL(String(url)).pathname);
      return Response.json({ kind: "grounded_qa.execution.template" });
    }) as typeof fetch,
  });
  assert.deepEqual(paths, [
    "/api/review/sessions/session%20one/turns/turn%2Fone/trace/event%20one",
  ]);
  assert.deepEqual(ok, {
    detail: { kind: "grounded_qa.execution.template" },
    status: 200,
  });

  const notFound = await getTurnTraceDetailFromBackend("session-1", "turn-1", "missing-event", {
    baseUrl: "http://backend.test",
    fetcher: (async () => new Response("nope", { status: 404 })) as typeof fetch,
  });
  assert.deepEqual(notFound, { detail: null, status: 404 });
});
