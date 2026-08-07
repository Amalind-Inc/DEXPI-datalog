import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { VMOptions, VirtualProvider } from "@earendil-works/gondolin";

import { createGondolinBashRunner } from "./gondolin-bash.ts";

import { loadLocalProject, persistLocalProject } from "./local-project-manifest.cjs";
import { runLocalReviewInspection } from "./local-review-inspection.ts";
import {
  PortLogPiSessionCoordinator,
  type PortLogSessionIdentity,
} from "./pi-session-coordinator.ts";

function sse(response: http.ServerResponse, payload: object) {
  response.write(`data: ${JSON.stringify(payload)}\n\n`);
}
async function createSession(
  workspaceRoot: string,
  sessionId: string,
  sourceDigest: string,
  attachmentRoot?: string,
): Promise<PortLogPiSessionCoordinator> {
  const identity: PortLogSessionIdentity = {
    workspaceRoot,
    projectId: sessionId,
    sourceDigest,
    policy: { id: "portlog-host-policy", version: "1", digest: "sha256:portlog-host-policy-v1" },
    toolProfile: { id: "pi-portlog-v1", version: "1", digest: "sha256:pi-portlog-v1" },
  };
  return PortLogPiSessionCoordinator.create({
    sessionRoot: join(workspaceRoot, ".portlog", "sessions"),
    sessionId,
    identity,
    ...(attachmentRoot === undefined ? {} : { attachmentRoot }),
  });
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

  let session: PortLogPiSessionCoordinator | undefined;
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01",
      filename: "C01V04-VER.EX01.xml",
      status: "ready",
    });
    const project = await loadLocalProject(projectDirectory);
    session = await createSession(projectDirectory, project.projectId, project.source.digest);
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "real-pi-turn",
      question: "What equipment and connections are around P-101?",
      model: { provider: "portlog-test", id: "review-model" },
      session,
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
    await session?.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});

test("provider failures persist an actionable failed turn instead of an empty success", async () => {
  const server = http.createServer((_request, response) => {
    response.writeHead(401, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { message: "invalid api key" } }));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const root = await mkdtemp(join(tmpdir(), "portlog-provider-error-"));
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

  let session: PortLogPiSessionCoordinator | undefined;
  try {
    session = await createSession(root, "provider-error-turn", `sha256:${"0".repeat(64)}`);
    const record = await runLocalReviewInspection({
      turnId: "provider-error-turn",
      question: "What equipment is around P-101?",
      model: { provider: "portlog-test", id: "review-model" },
      signal: new AbortController().signal,
      agentDir: root,
      cwd: root,
      session,
    });
    assert.equal(record.status, "failed");
    assert.match(record.error ?? "", /invalid api key/i);
    assert.equal(record.finalText, "");
    assert.deepEqual(
      record.events.map((event) => event.type),
      ["turn_started", "turn_failed"],
    );
  } finally {
    await session?.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});

test("controlled Verify journey keeps the Soufflé outcome separate from model prose", async () => {
  let modelRequests = 0;
  const server = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (modelRequests === 1) {
      sse(response, {
        id: "verify-tool",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "check-1",
                  type: "function",
                  function: {
                    name: "portlog_rule_check",
                    arguments: JSON.stringify({
                      checkId: "pump_discharge_check_valve",
                      scopeEntityId: "P-101",
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
        id: "verify-answer",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "The model thinks the check is satisfied.",
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
  const root = await mkdtemp(join(tmpdir(), "portlog-local-verify-pi-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
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
  let session: PortLogPiSessionCoordinator | undefined;
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "verify-c01",
      filename: "C01.xml",
      status: "ready",
    });
    const project = await loadLocalProject(projectDirectory);
    session = await createSession(projectDirectory, project.projectId, project.source.digest);
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "verify-pi-turn",
      posture: "verify",
      question: "Does pump P-101 have a check valve on its first discharge segment?",
      model: { provider: "portlog-test", id: "review-model" },
      session,
      signal: new AbortController().signal,
      agentDir: root,
      cwd: root,
      getEvidence: async () => ({ citations: [] }),
      getRuleCheck: async ({ checkId, scopeEntityId }) => ({
        deterministic_result: {
          check_id: checkId,
          check_version: 1,
          rule: { pack_id: "demo-process-safety", pack_version: 1 },
          run_status: "completed",
          outcome: "violated",
          reason_code: "no_check_valve_on_complete_segment",
          evidence: {
            ordered_topology_ids: [scopeEntityId, "N-1"],
            scope_completeness: { complete: true, basis: "terminal_boundary_reached" },
          },
          coverage: {
            requested_entity_id: scopeEntityId,
            evaluated_entity_id: "pump-1",
            required_facts: ["discharge path"],
            missing_facts: [],
            complete: true,
          },
          scope: {
            class: "CentrifugalPump",
            pump_id: "pump-1",
            requested_entity_id: scopeEntityId,
          },
          engine: { name: "souffle", status: "completed" },
          document_preparation_digest: "sha256:verify-pi-test",
          source_attestation: {
            revision: "sha256:verify-pi-test",
            kind: "prepared-review-source",
            authority: "governed-check-engine",
          },
        },
      }),
    });
    assert.equal(modelRequests, 2);
    assert.equal(record.posture, "verify");
    assert.equal(record.deterministicChecks[0].outcome, "violated");
    assert.match(record.finalText, /PortLog deterministic check.*violated/);
    assert.doesNotMatch(record.finalText, /model thinks the check is satisfied/i);
    assert.deepEqual(
      record.events.filter((event) => event.type.startsWith("tool_")).map((event) => event.type),
      ["tool_request", "tool_result"],
    );
  } finally {
    await session?.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});

test("model-issued Bash runs once through Gondolin and persists bounded ordinary metadata", async () => {
  let modelRequests = 0;
  const server = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (modelRequests === 1) {
      sse(response, {
        id: "bash-tool",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "bash-call-1",
                  type: "function",
                  function: {
                    name: "bash",
                    arguments: JSON.stringify({
                      command: "printf guest-output && printf changed > generated.txt",
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
        id: "bash-answer",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "The isolated command completed.",
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

  const root = await mkdtemp(join(tmpdir(), "portlog-bash-session-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
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

  let session: PortLogPiSessionCoordinator | undefined;
  let guestCalls = 0;
  let hostCalls = 0;
  let guestClosed = false;
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "bash-project",
      filename: "C01.xml",
      status: "ready",
    });
    const project = await loadLocalProject(projectDirectory);
    session = await createSession(
      projectDirectory,
      project.projectId,
      project.source.digest,
      join(root, "attachments"),
    );
    const runGondolinBash = createGondolinBashRunner({
      workspaceRoot: projectDirectory,
      qemuPath: "/absolute/qemu-system-aarch64",
      policyDigest: "sha256:portlog-host-policy-v1",
      createVm: async (vmOptions: VMOptions) => {
        const provider = vmOptions.vfs?.mounts?.["/workspace"] as VirtualProvider | undefined;
        assert.ok(provider?.writeFile);
        return {
          exec(command) {
            guestCalls += 1;
            assert.deepEqual(command, [
              "/bin/sh",
              "-c",
              "printf guest-output && printf changed > generated.txt",
            ]);
            const completion = (async () => {
              await provider.writeFile!("/generated.txt", Buffer.from("changed"));
              return { exitCode: 0, stdout: "", stderr: "" };
            })();
            return {
              then: completion.then.bind(completion),
              async *output() {
                yield {
                  stream: "stdout" as const,
                  data: Buffer.from("guest-output"),
                  text: "guest-output",
                };
              },
            };
          },
          async close() {
            guestClosed = true;
          },
        };
      },
    });

    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "bash-pi-turn",
      posture: "review",
      question: "Inspect the source and create a scratch summary.",
      model: { provider: "portlog-test", id: "review-model" },
      session,
      signal: new AbortController().signal,
      agentDir: root,
      cwd: projectDirectory,
      runHostSafeBash: async () => {
        hostCalls += 1;
        throw new Error("Host fallback must not run.");
      },
      runGondolinBash,
    });

    assert.equal(modelRequests, 2);
    assert.equal(guestCalls, 1);
    assert.equal(hostCalls, 0);
    assert.equal(guestClosed, true);
    assert.equal(record.status, "completed");
    assert.match(record.finalText, /isolated command completed/i);
    assert.deepEqual(
      record.events.filter((event) => event.type.startsWith("tool_")).map((event) => event.type),
      ["tool_request", "tool_update", "tool_result"],
    );
    const liveUpdate = record.events.find((event) => event.type === "tool_update");
    assert.ok(liveUpdate && "result" in liveUpdate);
    assert.match(JSON.stringify(liveUpdate.result), /guest-output/);
    assert.match(JSON.stringify(liveUpdate.result), /"stream_sequence":1/);
    const recordText = JSON.stringify(record);
    assert.match(recordText, /gondolin-qemu-hvf/);
    assert.match(recordText, /generated\.txt/);
    assert.match(recordText, /"authority":"ordinary"/);

    const credentials = await session.issueClientCredentials({
      clientId: "bash-observer",
      role: "observer",
    });
    const observer = await session.attachClient(credentials);
    const history = await observer.resync({ nextEntryIndex: 0 });
    const persistedTranscript = JSON.stringify(history.entries);
    assert.match(persistedTranscript, /gondolin-qemu-hvf/);
    assert.match(persistedTranscript, /generated\.txt/);

    const persistedProject = await loadLocalProject(projectDirectory);
    const persistedTurn = persistedProject.turns.find(
      (turn: { turnId?: string }) => turn.turnId === "bash-pi-turn",
    );
    assert.ok(persistedTurn);
    assert.match(JSON.stringify(persistedTurn), /gondolin-qemu-hvf/);
  } finally {
    await session?.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(root, { recursive: true, force: true });
  }
});
