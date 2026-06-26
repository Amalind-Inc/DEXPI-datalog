import assert from "node:assert/strict";
import test from "node:test";
import { answerChatWithReviewBackend, prepareReviewSession } from "./review-backend.ts";

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

test("answerChatWithReviewBackend returns confirmation state without executing generated Datalog", async () => {
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
        refinement: { refined_prompt: body.prompt },
      });
    }
    if (parsedUrl.pathname.endsWith("/logic-requests/confirm")) {
      return Response.json({
        status: "confirmation_ready",
        session_id: "session-1",
        restatement: {
          kind: "datalog_grounded_restatement",
          text: "Return downstream reachable process objects.",
        },
        generated_logic: {
          kind: "generated_datalog",
          language: "souffle_datalog",
          content: '.decl answer(x:symbol)\n.output answer\nanswer("P-101").',
        },
        validation: { status: "pending_safety_validation" },
        allowed_actions: ["run", "revise", "cancel"],
      });
    }
    if (parsedUrl.pathname.endsWith("/logic-requests/execute")) {
      return Response.json({
        status: "answered",
        summary: { text: "Deterministic execution produced 2 evidence items." },
        evidence_highlight: {
          source_scope_ids: ["node-p101"],
          matched_object_ids: ["node-v102"],
          paths: [{ id: "path-1", node_ids: ["node-p101", "node-v102"], edge_ids: ["edge-p-v"] }],
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
      "POST /api/review/sessions/session-1/logic-requests/confirm",
    ],
  );
  assert.deepEqual(calls[0].body, { source_scope_ids: ["node-p101"] });
  assert.deepEqual(calls[1].body, {
    provider: "openrouter",
    model: "openrouter/owl-alpha",
    credential: "sk-hidden",
  });
  assert.equal(result.status, "confirmation_ready");
  assert.match(result.message, /Datalog confirmation ready/);
  assert.equal(
    result.confirmation?.plainLanguageMeaning,
    "Return downstream reachable process objects.",
  );
  assert.equal(
    result.confirmation?.generatedDatalog,
    '.decl answer(x:symbol)\n.output answer\nanswer("P-101").',
  );
  assert.deepEqual(result.confirmation?.allowedActions, ["run", "revise", "cancel"]);
  assert.equal(JSON.stringify(result).includes("sk-hidden"), false);
  assert.deepEqual(result.highlightedNodeIds, []);
});

test("answerChatWithReviewBackend keeps Datalog prompts in confirmation state when backend is unavailable", async () => {
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

  assert.equal(result.status, "confirmation_ready");
  assert.match(result.message, /Datalog confirmation ready/);
  assert.doesNotMatch(result.message, /I am grounding this QA answer/);
  assert.equal(
    result.confirmation?.plainLanguageMeaning,
    "Review a generated Datalog query for the requested topology reasoning before execution.",
  );
});
