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
