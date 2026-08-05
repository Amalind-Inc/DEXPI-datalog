import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import test from "node:test";

import { createPortLogToolProfile, PORTLOG_HOST_POLICY } from "./capability-routing.ts";
import { loadLocalProject, persistLocalProject } from "./local-project-manifest.cjs";
import { PortLogPiSessionCoordinator } from "./pi-session-coordinator.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const commandPath = join(repoRoot, "frontend/desktop/portlog-review.ts");

function sse(response: http.ServerResponse, payload: object) {
  response.write(`data: ${JSON.stringify(payload)}\n\n`);
}

async function runCommand(args: string[], environment: Partial<NodeJS.ProcessEnv>) {
  const child = spawn(process.execPath, ["--experimental-strip-types", commandPath, ...args], {
    cwd: repoRoot,
    env: { ...process.env, ...environment },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += String(chunk);
  });
  child.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  const [code] = (await once(child, "exit")) as [number | null, NodeJS.Signals | null];
  return { code, stdout, stderr };
}

test("terminal review prints bounded PortLog events and persists the completed record", async () => {
  let modelRequests = 0;
  const modelServer = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (modelRequests === 1) {
      sse(response, {
        id: "read-turn",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "read-call",
                  type: "function",
                  function: {
                    name: "read",
                    arguments: JSON.stringify({ path: "C01.xml" }),
                  },
                },
              ],
            },
            finish_reason: "tool_calls",
          },
        ],
      });
    } else if (modelRequests === 2) {
      sse(response, {
        id: "tool-turn",
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
              ],
            },
            finish_reason: "tool_calls",
          },
        ],
      });
    } else {
      sse(response, {
        id: "answer-turn",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "P-101 is present in the prepared topology.",
            },
            finish_reason: "stop",
          },
        ],
      });
    }
    response.end("data: [DONE]\n\n");
  });
  modelServer.listen(0, "127.0.0.1");
  await once(modelServer, "listening");
  const modelAddress = modelServer.address();
  assert.ok(modelAddress && typeof modelAddress !== "string");

  const sidecarServer = http.createServer((request, response) => {
    if (request.url === "/openapi.json") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("{}");
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        topology_view: {
          nodes: [{ id: "P-101", kind: "CentrifugalPump" }],
          edges: [],
        },
      }),
    );
  });
  sidecarServer.listen(0, "127.0.0.1");
  await once(sidecarServer, "listening");
  const sidecarAddress = sidecarServer.address();
  assert.ok(sidecarAddress && typeof sidecarAddress !== "string");

  const root = await mkdtemp(join(repoRoot, ".tmp-portlog-review-test-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: "<PlantModel />",
    sessionId: "terminal-review-session",
    filename: "C01.xml",
    status: "ready",
  });
  await writeFile(join(projectDirectory, "C01.xml"), "<PlantModel />");

  try {
    const result = await runCommand(
      [
        "--project",
        projectDirectory,
        "--provider",
        "openrouter",
        "--model",
        "review-model",
        "--posture",
        "inspect",
        "--question",
        "What equipment is around P-101?",
      ],
      {
        PORTLOG_RUNTIME_API_KEY: "test-key",
        PORTLOG_RUNTIME_BASE_URL: `http://127.0.0.1:${modelAddress.port}/v1`,
        PORTLOG_REVIEW_SIDECAR_ENDPOINT: `http://127.0.0.1:${sidecarAddress.port}`,
      },
    );
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /TOOL REQUEST read/);
    assert.match(result.stdout, /TOOL RESULT read/);
    assert.match(result.stdout, /TOOL REQUEST portlog_evidence/);
    assert.match(result.stdout, /TOOL RESULT portlog_evidence/);
    assert.match(result.stdout, /FINAL PORTLOG RECORD/);
    assert.match(result.stdout, /"status": "completed"/);
    assert.match(result.stdout, /P-101 is present/);
    assert.equal(modelRequests, 3);

    const project = await loadLocalProject(projectDirectory);
    assert.equal(project.turns.length, 1);
    assert.equal(project.turns[0].status, "completed");
    assert.deepEqual(project.turns[0].evidenceIds, ["P-101"]);
    const session = await PortLogPiSessionCoordinator.open({
      sessionRoot: join(projectDirectory, ".portlog", "sessions"),
      sessionId: project.projectId,
      identity: {
        workspaceRoot: projectDirectory,
        projectId: project.projectId,
        sourceDigest: project.source.digest,
        policy: PORTLOG_HOST_POLICY,
        toolProfile: createPortLogToolProfile({
          hostEvidence: true,
          hostRules: true,
          isolatedExecution: true,
        }),
      },
    });
    try {
      const entries = await session.getEntries();
      const messages = entries.filter((entry) => (entry as { type?: string }).type === "message");
      const nativeMessages = JSON.stringify(messages);
      assert.match(nativeMessages, /P-101 is present/);
      assert.match(nativeMessages, /Pi workspace read/);
      assert.match(nativeMessages, /authority.*ordinary/);
      assert.match(nativeMessages, /portlog_evidence/);
      assert.ok(
        entries.some(
          (entry) => (entry as { customType?: string }).customType === "portlog_turn_started",
        ),
      );
      assert.ok(
        entries.some(
          (entry) => (entry as { customType?: string }).customType === "portlog_turn_terminal",
        ),
      );
    } finally {
      await session.close();
    }
  } finally {
    modelServer.closeAllConnections();
    sidecarServer.closeAllConnections();
    await Promise.all([
      new Promise<void>((resolveClose) => modelServer.close(() => resolveClose())),
      new Promise<void>((resolveClose) => sidecarServer.close(() => resolveClose())),
    ]);
    await rm(root, { recursive: true, force: true });
  }
});

test("terminal review completes the governed E06 evidence-check-isolation journey", async () => {
  let modelRequests = 0;
  const modelServer = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    const toolCalls = [
      {
        id: "e06-evidence",
        name: "portlog_evidence",
        arguments: {
          artifactId: "topology",
          claim: "E06 pump discharge path around P-101",
        },
      },
      {
        id: "e06-check",
        name: "portlog_rule_check",
        arguments: {
          checkId: "pump_discharge_check_valve",
          scopeEntityId: "P-101",
        },
      },
      {
        id: "e06-isolated",
        name: "portlog_isolated_command",
        arguments: { profileId: "review-bundle-candidate" },
      },
    ];
    if (modelRequests <= toolCalls.length) {
      const tool = toolCalls[modelRequests - 1];
      sse(response, {
        id: tool.id,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: tool.id,
                  type: "function",
                  function: {
                    name: tool.name,
                    arguments: JSON.stringify(tool.arguments),
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
        id: "e06-answer",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content:
                "E06 review completed with cited topology, a deterministic check, and an admitted isolated candidate.",
            },
            finish_reason: "stop",
          },
        ],
      });
    }
    response.end("data: [DONE]\n\n");
  });
  modelServer.listen(0, "127.0.0.1");
  await once(modelServer, "listening");
  const modelAddress = modelServer.address();
  assert.ok(modelAddress && typeof modelAddress !== "string");

  const sidecarServer = http.createServer((request, response) => {
    if (request.url === "/openapi.json") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("{}");
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify(
        request.url?.endsWith("/governed-checks")
          ? {
              deterministic_result: {
                schema_version: 1,
                check_id: "pump_discharge_check_valve",
                check_version: 1,
                rule: { pack_id: "demo-process-safety", pack_version: 1 },
                scope: {
                  requested_entity_id: "P-101",
                  evaluated_entity_id: "P-101",
                  pump_id: "P-101",
                  class: "CentrifugalPump",
                },
                required_facts: ["discharge path"],
                run_status: "completed",
                outcome: "satisfied",
                evidence: {
                  scope_completeness: { complete: true, basis: "terminal_boundary_reached" },
                  ordered_entity_ids: ["P-101", "E06-V-101"],
                },
                coverage: {
                  requested_entity_id: "P-101",
                  evaluated_entity_id: "P-101",
                  required_facts: ["discharge path"],
                  missing_facts: [],
                  complete: true,
                },
                engine: { name: "souffle", status: "completed" },
                document_preparation_digest: "sha256:portlog-review-e06",
                source_attestation: {
                  revision: "sha256:portlog-review-e06",
                  kind: "prepared-review-source",
                  authority: "governed-check-engine",
                },
              },
            }
          : {
              topology_view: {
                nodes: [
                  { id: "P-101", kind: "CentrifugalPump" },
                  { id: "E06-V-101", kind: "Valve" },
                ],
                edges: [{ source: "P-101", target: "E06-V-101", kind: "discharge" }],
              },
            },
      ),
    );
  });
  sidecarServer.listen(0, "127.0.0.1");
  await once(sidecarServer, "listening");
  const sidecarAddress = sidecarServer.address();
  assert.ok(sidecarAddress && typeof sidecarAddress !== "string");

  const root = await mkdtemp(join(repoRoot, ".tmp-portlog-review-e06-test-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "E06.xml");
  await writeFile(sourcePath, '<PlantModel id="E06" />');
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: '<PlantModel id="E06" />',
    sessionId: "terminal-e06-session",
    filename: "E06.xml",
    status: "ready",
  });

  try {
    const result = await runCommand(
      [
        "--project",
        projectDirectory,
        "--provider",
        "openrouter",
        "--model",
        "review-model",
        "--posture",
        "review",
        "--question",
        "Review the E06 pump discharge path.",
      ],
      {
        PORTLOG_RUNTIME_API_KEY: "test-key",
        PORTLOG_RUNTIME_BASE_URL: `http://127.0.0.1:${modelAddress.port}/v1`,
        PORTLOG_REVIEW_SIDECAR_ENDPOINT: `http://127.0.0.1:${sidecarAddress.port}`,
        PORTLOG_QEMU_PATH: "/opt/homebrew/bin/qemu-system-aarch64",
      },
    );
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /TOOL REQUEST portlog_evidence/);
    assert.match(result.stdout, /TOOL REQUEST portlog_rule_check/);
    assert.match(result.stdout, /TOOL REQUEST portlog_isolated_command/);
    assert.match(result.stdout, /FINAL PORTLOG RECORD/);
    assert.match(result.stdout, /"posture": "review"/);
    assert.match(result.stdout, /"outcome": "admitted"/);
    assert.match(result.stdout, /E06 review completed/);
    assert.equal(modelRequests, 4);

    const project = await loadLocalProject(projectDirectory);
    assert.equal(project.turns.length, 1);
    assert.equal(project.turns[0].status, "completed");
    assert.equal(project.turns[0].posture, "review");
    assert.deepEqual(project.turns[0].evidenceIds, ["P-101", "E06-V-101"]);
    assert.equal(project.turns[0].deterministicChecks[0].outcome, "satisfied");
    assert.equal(
      project.turns[0].events.find(
        (event: { type: string; tool?: string; arguments?: { profileId?: string } }) =>
          event.type === "tool_request" && event.tool === "portlog_isolated_command",
      )?.arguments?.profileId,
      "review-bundle-candidate",
    );
  } finally {
    modelServer.closeAllConnections();
    sidecarServer.closeAllConnections();
    await Promise.all([
      new Promise<void>((resolveClose) => modelServer.close(() => resolveClose())),
      new Promise<void>((resolveClose) => sidecarServer.close(() => resolveClose())),
    ]);
    await rm(root, { recursive: true, force: true });
  }
});
test("terminal review can reopen the same prepared session for verify posture", async () => {
  let modelRequests = 0;
  const modelServer = http.createServer((_request, response) => {
    modelRequests += 1;
    response.writeHead(200, { "content-type": "text/event-stream" });
    if (modelRequests === 1) {
      sse(response, {
        id: "review-evidence-call",
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              tool_calls: [
                {
                  id: "review-evidence-call",
                  type: "function",
                  function: {
                    name: "portlog_evidence",
                    arguments: JSON.stringify({
                      artifactId: "topology",
                      claim: "P-4713 pump",
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
        id: `answer-${modelRequests}`,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: {
              role: "assistant",
              content: "The prepared session remains available for this posture.",
            },
            finish_reason: "stop",
          },
        ],
      });
    }
    response.end("data: [DONE]\n\n");
  });
  modelServer.listen(0, "127.0.0.1");
  await once(modelServer, "listening");
  const modelAddress = modelServer.address();
  assert.ok(modelAddress && typeof modelAddress !== "string");

  const sidecarServer = http.createServer((request, response) => {
    if (request.url === "/openapi.json") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("{}");
      return;
    }
    if (request.url?.endsWith("/topology")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          topology_view: {
            nodes: [{ id: "P-4713", kind: "CentrifugalPump" }],
            edges: [],
          },
        }),
      );
      return;
    }
    response.writeHead(404);
    response.end();
  });
  sidecarServer.listen(0, "127.0.0.1");
  await once(sidecarServer, "listening");
  const sidecarAddress = sidecarServer.address();
  assert.ok(sidecarAddress && typeof sidecarAddress !== "string");

  const root = await mkdtemp(join(repoRoot, ".tmp-portlog-review-posture-test-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  const qemuPath = join(root, "qemu-system-aarch64");
  await writeFile(sourcePath, "<PlantModel />");
  await writeFile(qemuPath, "#!/bin/sh\nexit 0\n");
  await chmod(qemuPath, 0o755);
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: "<PlantModel />",
    sessionId: "terminal-posture-session",
    filename: "C01.xml",
    status: "ready",
  });

  const commandOptions = [
    "--project",
    projectDirectory,
    "--provider",
    "openrouter",
    "--model",
    "review-model",
    "--question",
    "Review the E06 pump discharge path.",
  ];
  const environment = {
    PORTLOG_RUNTIME_API_KEY: "test-key",
    PORTLOG_RUNTIME_BASE_URL: `http://127.0.0.1:${modelAddress.port}/v1`,
    PORTLOG_REVIEW_SIDECAR_ENDPOINT: `http://127.0.0.1:${sidecarAddress.port}`,
    PORTLOG_QEMU_PATH: qemuPath,
  };

  try {
    const review = await runCommand(
      [...commandOptions.slice(0, 6), "--posture", "review", ...commandOptions.slice(6)],
      environment,
    );
    assert.equal(review.code, 0, review.stderr);
    assert.match(review.stdout, /"posture": "review"/);
    assert.match(review.stdout, /TOOL REQUEST portlog_evidence/);

    const verify = await runCommand(
      [...commandOptions.slice(0, 6), "--posture", "verify", ...commandOptions.slice(6)],
      environment,
    );
    assert.equal(verify.code, 0, verify.stderr);
    assert.match(verify.stdout, /"posture": "verify"/);
    assert.match(verify.stdout, /prepared session remains available/);
    assert.equal(modelRequests, 3);
  } finally {
    modelServer.closeAllConnections();
    sidecarServer.closeAllConnections();
    await Promise.all([
      new Promise<void>((resolveClose) => modelServer.close(() => resolveClose())),
      new Promise<void>((resolveClose) => sidecarServer.close(() => resolveClose())),
    ]);
    await rm(root, { recursive: true, force: true });
  }
});

test("terminal review reports a missing provider credential before starting work", async () => {
  const root = await mkdtemp(join(repoRoot, ".tmp-portlog-review-config-test-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: "<PlantModel />",
    sessionId: "terminal-config-session",
    filename: "C01.xml",
    status: "ready",
  });

  try {
    const result = await runCommand(
      [
        "--project",
        projectDirectory,
        "--provider",
        "openrouter",
        "--model",
        "review-model",
        "--posture",
        "inspect",
        "--question",
        "What equipment is around P-101?",
      ],
      {
        PORTLOG_RUNTIME_API_KEY: "",
        PORTLOG_OPENROUTER_API_KEY: "",
      },
    );
    assert.notEqual(result.code, 0);
    assert.match(result.stderr, /provider credential.*PORTLOG_RUNTIME_API_KEY/i);
    assert.doesNotMatch(result.stdout, /TURN STARTED/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("terminal review reports missing QEMU/HVF before starting a review posture", async () => {
  const root = await mkdtemp(join(repoRoot, ".tmp-portlog-review-qemu-config-test-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: "<PlantModel />",
    sessionId: "terminal-qemu-config-session",
    filename: "C01.xml",
    status: "ready",
  });

  try {
    const result = await runCommand(
      [
        "--project",
        projectDirectory,
        "--provider",
        "openrouter",
        "--model",
        "review-model",
        "--posture",
        "review",
        "--question",
        "Review the E06 pump discharge path.",
      ],
      {
        PORTLOG_RUNTIME_API_KEY: "test-key",
        PORTLOG_QEMU_PATH: join(root, "missing-qemu"),
      },
    );
    assert.notEqual(result.code, 0);
    assert.match(result.stderr, /QEMU\/HVF runtime is unavailable/i);
    assert.doesNotMatch(result.stdout, /TURN STARTED/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
