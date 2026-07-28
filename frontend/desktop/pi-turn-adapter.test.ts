import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
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
  try {
    const review = await createGovernedPiReviewTurn({
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
        return { artifactId, evidence: [{ kind: "drawing-highlight", id: "hl-101" }] };
      },
    });

    assert.deepEqual(
      review.session.agent.state.tools.map((tool) => tool.name),
      ["portlog_evidence"],
    );
    await review.prompt("Check the claimed connection.");
    assert.equal(evidenceCalls, 1);
    assert.equal(requestCount, 2);
  } finally {
    server.close();
    await rm(agentDir, { recursive: true, force: true });
  }
});
