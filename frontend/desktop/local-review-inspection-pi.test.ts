import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadLocalProject, persistLocalProject } from "./local-project-manifest.cjs";
import { runLocalReviewInspection } from "./local-review-inspection.ts";

function sse(response: http.ServerResponse, payload: object) {
  response.write(`data: ${JSON.stringify(payload)}\n\n`);
}

test("controlled Pi model-tool-model journey becomes a reconstructable PortLog Inspect trace", async () => {
  let modelRequests = 0;
  let activeEvidence = 0;
  let maxActiveEvidence = 0;
  const evidenceOrder: string[] = [];
  const server = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (modelRequests === 1) {
      sse(response, {
        id: "one",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "call-1",
                  type: "function",
                  function: {
                    name: "portlog_evidence",
                    arguments: JSON.stringify({
                      artifactId: "topology",
                      claim: "equipment around P-101",
                    }),
                  },
                },
                {
                  id: "call-2",
                  type: "function",
                  function: {
                    name: "portlog_evidence",
                    arguments: JSON.stringify({
                      artifactId: "topology",
                      claim: "connections around V-201",
                    }),
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
        id: "two",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "P-101 connects to V-201 [entity:P-101] [entity:V-201].",
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

  const root = await mkdtemp(join(tmpdir(), "portlog-local-pi-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01V04-VER.EX01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  await writeFile(
    join(root, "models.json"),
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

  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01",
      filename: "C01V04-VER.EX01.xml",
      status: "ready",
    });
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "real-pi-turn",
      question: "What equipment and connections are around P-101?",
      model: { provider: "portlog-test", id: "review-model" },
      signal: new AbortController().signal,
      agentDir: root,
      cwd: root,
      getEvidence: async ({ artifactId, claim }) => {
        activeEvidence += 1;
        maxActiveEvidence = Math.max(maxActiveEvidence, activeEvidence);
        evidenceOrder.push(claim);
        await new Promise((resolve) => setTimeout(resolve, 5));
        activeEvidence -= 1;
        return {
          artifactId,
          claim,
          citations: ["entity:P-101", "entity:V-201"],
          sourceScopeIds: ["P-101", "V-201"],
          diagnostics: [],
        };
      },
    });
    assert.equal(modelRequests, 2);
    assert.equal(maxActiveEvidence, 1);
    assert.deepEqual(evidenceOrder, ["equipment around P-101", "connections around V-201"]);
    assert.equal(record.status, "completed");
    assert.match(record.finalText, /P-101 connects to V-201/);
    assert.deepEqual(record.evidenceIds, ["entity:P-101", "entity:V-201"]);
    assert.deepEqual(
      record.events.filter((event) => event.type.startsWith("tool_")).map((event) => event.type),
      ["tool_request", "tool_result", "tool_request", "tool_result"],
    );
    assert.deepEqual((await loadLocalProject(projectDirectory)).turns, [record]);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});
