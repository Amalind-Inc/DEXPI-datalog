import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createGovernedPiReviewTurn } from "./pi-turn-adapter.ts";

const toolCall = {
  id: "call_evidence_1",
  type: "function",
  function: {
    name: "portlog_evidence",
    arguments: JSON.stringify({ artifactId: "drawing-1", claim: "P-101 is connected to V-201" }),
  },
};

function sse(response: http.ServerResponse, payload: object) {
  response.write(`data: ${JSON.stringify(payload)}\n\n`);
}

test("governed Pi turn exposes only PortLog tools and carries cancellation to evidence lookup", async () => {
  let requestCount = 0;
  const server = http.createServer((request, response) => {
    assert.equal(request.url, "/v1/chat/completions");
    requestCount += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });

    if (requestCount === 1) {
      sse(response, {
        id: "chatcmpl-1",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: { role: "assistant", tool_calls: [toolCall] },
            finish_reason: "tool_calls",
          },
        ],
      });
    } else {
      sse(response, {
        id: "chatcmpl-2",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: { role: "assistant", content: "Evidence is attached to the reviewed artifact." },
            finish_reason: "stop",
          },
        ],
      });
    }
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-pi-agent-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "portlog-test": {
          baseUrl: `http://127.0.0.1:${address.port}/v1`,
          api: "openai-completions",
          apiKey: "test-key",
          models: [{ id: "review-model", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );

  const abortController = new AbortController();
  let evidenceCalls = 0;
  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: abortController.signal,
      getEvidence: async ({ artifactId, claim, signal }) => {
        evidenceCalls += 1;
        assert.equal(artifactId, "drawing-1");
        assert.equal(claim, "P-101 is connected to V-201");
        assert.equal(signal, abortController.signal);
        abortController.abort();
        assert.equal(signal?.aborted, true);
        return { artifactId, evidence: [{ kind: "drawing-highlight", id: "hl-101" }] };
      },
    });

    assert.deepEqual(
      review.session.agent.state.tools.map((tool) => tool.name),
      ["portlog_evidence"],
    );
    assert.match(
      review.session.agent.state.tools[0].description,
      /artifactId must be exactly 'topology'/,
    );
    await review.prompt("Check the claimed connection.");
    assert.equal(evidenceCalls, 1);
    assert.ok(requestCount <= 2, "cancellation bounds any continuation already being scheduled");
    assert.equal(abortController.signal.aborted, true);
    assert.doesNotMatch(JSON.stringify(review.agent.state.messages), /Evidence is attached/);
  } finally {
    await review?.dispose();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(agentDir, { recursive: true, force: true });
  }
});
test("optional isolated command tool supports one model-tool-model continuation", async () => {
  let requestCount = 0;
  let isolatedCalls = 0;
  const server = http.createServer((_request, response) => {
    requestCount += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (requestCount === 1) {
      sse(response, {
        id: "isolated-tool-request",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "isolated-call-1",
                  type: "function",
                  function: {
                    name: "portlog_isolated_command",
                    arguments: JSON.stringify({ profileId: "native-child-echo" }),
                  },
                },
              ],
            },
            finish_reason: "tool_calls",
          },
        ],
      });
    } else {
      sse(response, {
        id: "isolated-answer",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "The approved native child completed.",
            },
            finish_reason: "stop",
          },
        ],
      });
    }
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-isolated-agent-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "portlog-test": {
          baseUrl: `http://127.0.0.1:${address.port}/v1`,
          api: "openai-completions",
          apiKey: "test-key",
          models: [{ id: "review-model", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );

  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: new AbortController().signal,
      runIsolatedCommand: async ({ profileId }, signal) => {
        isolatedCalls += 1;
        assert.equal(profileId, "native-child-echo");
        assert.equal(signal.aborted, false);
        return {
          outcome: "admitted" as const,
          diagnostic: "Native guest child completed.",
          provenance: {
            runId: "isolated-call-1",
            backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
            image: { id: "alpine-base", digest: "builtin:alpine-base" },
            policy: { id: "qemu-hvf-deny-all", digest: "builtin:qemu-hvf-deny-all" },
            commandProfile: { id: profileId, version: "1" },
            startedAt: "2026-08-03T00:00:00.000Z",
            completedAt: "2026-08-03T00:00:00.001Z",
            durationMs: 1,
            outcome: "admitted" as const,
          },
          exitCode: 0,
        };
      },
    });
    assert.deepEqual(
      review.session.agent.state.tools.map((tool) => tool.name),
      ["portlog_isolated_command"],
    );
    await review.prompt("Run the approved native child.");
    assert.equal(isolatedCalls, 1);
    assert.equal(requestCount, 2);
    assert.match(JSON.stringify(review.agent.state.messages), /Native guest child completed/);
    assert.match(JSON.stringify(review.agent.state.messages), /approved native child completed/);
  } finally {
    await review?.dispose();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(agentDir, { recursive: true, force: true });
  }
});
test("isolated command cancellation reaches the callback and ignores late completion", async () => {
  const controller = new AbortController();
  const started = Promise.withResolvers<AbortSignal>();
  const release = Promise.withResolvers<void>();
  let requestCount = 0;
  const server = http.createServer((_request, response) => {
    requestCount += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    sse(response, {
      id: "isolated-cancel-request",
      object: "chat.completion.chunk",
      choices: [
        {
          index: 0,
          delta: {
            role: "assistant",
            tool_calls: [
              {
                id: "isolated-cancel-call",
                type: "function",
                function: {
                  name: "portlog_isolated_command",
                  arguments: JSON.stringify({ profileId: "native-child-hold" }),
                },
              },
            ],
          },
          finish_reason: "tool_calls",
        },
      ],
    });
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-isolated-cancel-agent-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "portlog-test": {
          baseUrl: `http://127.0.0.1:${address.port}/v1`,
          api: "openai-completions",
          apiKey: "test-key",
          models: [{ id: "review-model", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );

  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: controller.signal,
      runIsolatedCommand: async (_request, signal) => {
        started.resolve(signal);
        await release.promise;
        return {
          outcome: "admitted" as const,
          diagnostic: "Late native child completion.",
          provenance: {
            runId: "isolated-cancel-call",
            backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
            image: { id: "alpine-base", digest: "builtin:alpine-base" },
            policy: { id: "qemu-hvf-deny-all", digest: "builtin:qemu-hvf-deny-all" },
            commandProfile: { id: "native-child-hold", version: "1" },
            startedAt: "2026-08-03T00:00:00.000Z",
            completedAt: "2026-08-03T00:00:01.000Z",
            durationMs: 1_000,
            outcome: "admitted" as const,
          },
          exitCode: 0,
        };
      },
    });

    const promptPromise = review.prompt("Run the held native child.");
    const callbackSignal = await started.promise;
    controller.abort();
    assert.equal(callbackSignal.aborted, true);
    release.resolve();
    await promptPromise;
    assert.equal(requestCount, 1);
    assert.doesNotMatch(
      JSON.stringify(review.agent.state.messages),
      /Late native child completion/,
    );
  } finally {
    release.resolve();
    await review?.dispose();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(agentDir, { recursive: true, force: true });
  }
});

test("general desktop turns expose no P&ID tools without an evidence bridge", async () => {
  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-general-agent-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "portlog-test": {
          baseUrl: "http://127.0.0.1:1/v1",
          api: "openai-completions",
          apiKey: "test-key",
          models: [{ id: "review-model", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );
  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: new AbortController().signal,
    });
    assert.deepEqual(
      review.session.agent.state.tools.map((tool) => tool.name),
      [],
    );
  } finally {
    await review?.dispose();
    await rm(agentDir, { recursive: true, force: true });
  }
});

test("desktop pins only the exact direct Pi core runtime pair", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  assert.equal(packageJson.dependencies["@earendil-works/pi-agent-core"], "0.80.6");
  assert.equal(packageJson.dependencies["@earendil-works/pi-ai"], "0.80.6");
  assert.equal(packageJson.dependencies["@earendil-works/pi-coding-agent"], undefined);
  assert.equal(packageJson.devDependencies["@earendil-works/pi-coding-agent"], undefined);
  const lockfile = JSON.parse(
    await readFile(new URL("../package-lock.json", import.meta.url), "utf8"),
  );
  assert.equal(lockfile.packages["node_modules/@earendil-works/pi-agent-core"].version, "0.80.6");
  assert.equal(lockfile.packages["node_modules/@earendil-works/pi-ai"].version, "0.80.6");
});

test("Codex runtime uses the pinned Codex Responses transport and backend", async () => {
  let requestPath = "";
  const server = http.createServer((_request, response) => {
    requestPath = _request.url ?? "";
    response.writeHead(200, { "content-type": "text/event-stream" });
    sse(response, { type: "response.created", response: { id: "resp-1" } });
    sse(response, {
      type: "response.output_item.added",
      output_index: 0,
      item: { type: "message", id: "msg-1", role: "assistant", content: [] },
    });
    sse(response, { type: "response.output_text.delta", output_index: 0, delta: "Codex response" });
    sse(response, {
      type: "response.output_item.done",
      output_index: 0,
      item: {
        type: "message",
        id: "msg-1",
        role: "assistant",
        content: [{ type: "output_text", text: "Codex response" }],
      },
    });
    sse(response, {
      type: "response.completed",
      response: {
        id: "resp-1",
        status: "completed",
        usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3 },
      },
    });
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-codex-agent-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "openai-codex": {
          baseUrl: `http://127.0.0.1:${address.port}/backend-api`,
          api: "openai-codex-responses",
          models: [{ id: "gpt-5.4", reasoning: true, input: ["text"] }],
        },
      },
    }),
  );
  const accountToken = [
    "header",
    Buffer.from(
      JSON.stringify({ "https://api.openai.com/auth": { chatgpt_account_id: "acct-test" } }),
    ).toString("base64url"),
    "signature",
  ].join(".");
  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "openai-codex",
      model: "gpt-5.4",
      signal: new AbortController().signal,
      apiKey: accountToken,
      getEvidence: async () => ({ citations: [] }),
    });
    assert.equal(review.agent.state.model.api, "openai-codex-responses");
    assert.equal(review.agent.state.model.baseUrl, `http://127.0.0.1:${address.port}/backend-api`);
    await review.prompt("Say hello.");
    assert.equal(requestPath, "/backend-api/codex/responses");
  } finally {
    await review?.dispose();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(agentDir, { recursive: true, force: true });
  }
});
