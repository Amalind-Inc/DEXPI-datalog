import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { access, mkdtemp, rm, writeFile } from "node:fs/promises";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createGovernedPiReviewTurn } from "./pi-turn-adapter.ts";

function sse(response: http.ServerResponse, payload: object) {
  response.write(`data: ${JSON.stringify(payload)}\n\n`);
}

test("injects the OpenRouter key as a runtime override without consulting Pi auth files", async () => {
  let authorization: string | undefined;
  const server = http.createServer((request, response) => {
    assert.equal(request.url, "/v1/chat/completions");
    authorization = request.headers.authorization;
    response.writeHead(200, { "content-type": "text/event-stream" });
    sse(response, {
      id: "chatcmpl-openrouter",
      object: "chat.completion.chunk",
      choices: [{ index: 0, delta: { role: "assistant", content: "ok" }, finish_reason: "stop" }],
    });
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-pi-openrouter-"));
  await writeFile(
    path.join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        openrouter: {
          baseUrl: `http://127.0.0.1:${address.port}/v1`,
          api: "openai-completions",
          models: [{ id: "deepseek/deepseek-v4-flash", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );

  let review: Awaited<ReturnType<typeof createGovernedPiReviewTurn>> | null = null;
  try {
    review = await createGovernedPiReviewTurn({
      agentDir,
      cwd: agentDir,
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
      apiKey: "sk-or-runtime-only",
      signal: new AbortController().signal,
      getEvidence: async () => ({}),
    });
    await review.prompt("Run the connection smoke.");
    await review.session.abort();
    await review.dispose();
    review = null;

    assert.equal(authorization, "Bearer sk-or-runtime-only");
    await assert.rejects(() => access(path.join(agentDir, "auth.json")), /ENOENT/);
    const source = await fs.readFile(new URL("./pi-turn-adapter.ts", import.meta.url), "utf8");
    assert.match(source, /credentials: new InMemoryCredentialStore\(\)/);
    assert.doesNotMatch(source, /authPath/);
  } finally {
    await review?.dispose();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(agentDir, { recursive: true, force: true });
  }
});

// Pi's runtime-key path leaves an internal provider handle open after the
// observable session is disposed. This file has no post-test cleanup work; exit
// the worker once the assertions above have completed so npm test can finish.
test.after(() => { process.exit(0); });
