import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { GONDOLIN_REVIEW_CANDIDATE_PROFILE } from "./gondolin-qemu.ts";
import { createPortLogPiAgent } from "./pi-turn-adapter.ts";

function admittedResult() {
  return {
    outcome: "admitted" as const,
    diagnostic: "Review candidate admitted.",
    provenance: {
      runId: "bash-call-1",
      backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
      image: { id: "alpine-base", digest: "builtin:alpine-base" },
      policy: { id: "qemu-hvf-deny-all", digest: "builtin:qemu-hvf-deny-all" },
      commandProfile: GONDOLIN_REVIEW_CANDIDATE_PROFILE,
      startedAt: "2026-08-06T00:00:00.000Z",
      completedAt: "2026-08-06T00:00:00.001Z",
      durationMs: 1,
      outcome: "admitted" as const,
      artifact: { id: "result.json", digest: "sha256:result", byteLength: 77 },
    },
    exitCode: 0,
    candidate: {
      schemaVersion: 1 as const,
      status: "ok" as const,
      message: "review bundle inspected",
    },
  };
}

async function createAgent(
  runIsolatedCommand: Parameters<typeof createPortLogPiAgent>[0]["runIsolatedCommand"],
) {
  const agentDir = await mkdtemp(path.join(os.tmpdir(), "portlog-pi-bash-"));
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
  const review = await createPortLogPiAgent({
    agentDir,
    cwd: agentDir,
    provider: "portlog-test",
    model: "review-model",
    signal: new AbortController().signal,
    runIsolatedCommand,
  });
  return { agentDir, review };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function toolText(result: { content: Array<{ type: string; text?: string }> }) {
  const content = result.content.find((item) => item.type === "text");
  assert.ok(content?.text);
  const parsed = JSON.parse(content.text);
  assert.ok(isRecord(parsed));
  return parsed;
}

function schemaPropertyNames(schema: unknown): string[] {
  assert.ok(schema !== null && typeof schema === "object" && "properties" in schema);
  const properties = schema.properties;
  assert.ok(properties !== null && typeof properties === "object");
  return Object.keys(properties);
}

test("bash registers only with the isolated bridge and rejects an unknown profile before execution", async () => {
  let calls = 0;
  const { agentDir, review } = await createAgent(async () => {
    calls += 1;
    return admittedResult();
  });
  try {
    assert.deepEqual(
      review.session.agent.state.tools.map((tool) => tool.name),
      ["portlog_isolated_command", "bash"],
    );
    const bash = review.session.agent.state.tools.find((tool) => tool.name === "bash");
    assert.ok(bash);
    assert.deepEqual(schemaPropertyNames(bash.parameters), ["profileId"]);

    const result = await bash.execute("bash-unknown", { profileId: "not-an-approved-profile" });
    const value = toolText(result);
    assert.equal(calls, 0);
    assert.equal(value.outcome, "rejected");
    assert.equal(value.route, "unavailable");
    assert.equal(value.authority, "ordinary");
    assert.deepEqual(value.profile, GONDOLIN_REVIEW_CANDIDATE_PROFILE);
  } finally {
    await review.dispose();
    await rm(agentDir, { recursive: true, force: true });
  }
});

test("bash invokes the existing isolated bridge exactly once for the immutable review profile", async () => {
  let calls = 0;
  let callbackSignal: AbortSignal | undefined;
  let callbackProfileId: string | undefined;
  const { agentDir, review } = await createAgent(async ({ profileId }, signal) => {
    calls += 1;
    callbackProfileId = profileId;
    callbackSignal = signal;
    return admittedResult();
  });
  try {
    const bash = review.session.agent.state.tools.find((tool) => tool.name === "bash");
    assert.ok(bash);
    const updates: unknown[] = [];
    const result = await bash.execute(
      "bash-approved",
      { profileId: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id },
      undefined,
      (update) => updates.push(update),
    );
    const value = toolText(result);

    assert.equal(calls, 1);
    assert.equal(callbackProfileId, GONDOLIN_REVIEW_CANDIDATE_PROFILE.id);
    assert.ok(callbackSignal instanceof AbortSignal);
    assert.equal(value.outcome, "admitted");
    assert.equal(value.route, "gondolin");
    assert.equal(value.authority, "ordinary");
    assert.deepEqual(value.profile, GONDOLIN_REVIEW_CANDIDATE_PROFILE);
    assert.equal(value.output_truncated, false);
    assert.equal(updates.length, 1);
    assert.match(JSON.stringify(updates[0]), /gondolin_started/);
  } finally {
    await review.dispose();
    await rm(agentDir, { recursive: true, force: true });
  }
});
test("bash rejects command-shaped parameters before any isolated execution", async () => {
  let calls = 0;
  const { agentDir, review } = await createAgent(async () => {
    calls += 1;
    return admittedResult();
  });
  try {
    const bash = review.session.agent.state.tools.find((tool) => tool.name === "bash");
    assert.ok(bash);
    const result = await bash.execute("bash-command-shaped", {
      profileId: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id,
      command: "cat /review/input/review.json",
    });
    const value = toolText(result);
    assert.equal(calls, 0);
    assert.equal(value.outcome, "rejected");
    assert.equal(value.route, "unavailable");
  } finally {
    await review.dispose();
    await rm(agentDir, { recursive: true, force: true });
  }
});

test("bash reports isolated failures without a host fallback", async () => {
  let calls = 0;
  const { agentDir, review } = await createAgent(async () => {
    calls += 1;
    throw new Error("guest initialization failed");
  });
  try {
    const bash = review.session.agent.state.tools.find((tool) => tool.name === "bash");
    assert.ok(bash);
    const result = await bash.execute("bash-failure", {
      profileId: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id,
    });
    const value = toolText(result);
    assert.equal(calls, 1);
    assert.equal(value.outcome, "failed");
    assert.equal(value.route, "gondolin");
    assert.equal(value.authority, "ordinary");
  } finally {
    await review.dispose();
    await rm(agentDir, { recursive: true, force: true });
  }
});
