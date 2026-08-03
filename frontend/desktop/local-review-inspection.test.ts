import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { toIsolatedCommandToolResult } from "./isolated-command.ts";
import { loadLocalProject, persistLocalProject } from "./local-project-manifest.cjs";
import { runLocalDesktopChat, runLocalReviewInspection } from "./local-review-inspection.ts";

test("a governed Inspect turn is reconstructed from the durable PortLog project record", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-inspection-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01V04-VER.EX01.xml");
  await writeFile(sourcePath, "<PlantModel />");

  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01-review",
      filename: "C01V04-VER.EX01.xml",
      status: "ready",
      artifacts: { topology: "backend:c01-review/topology" },
    });

    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "turn-p101",
      question: "What equipment and connections are around P-101?",
      model: { provider: "portlog-test", id: "review-model" },
      signal: new AbortController().signal,
      createTurn: async ({ emit, getEvidence }) => ({
        prompt: async () => {
          emit({ type: "assistant_text_delta", text: "I will inspect P-101. " });
          emit({
            type: "tool_request",
            callId: "call-1",
            tool: "portlog_evidence",
            arguments: { artifactId: "topology", claim: "equipment and connections around P-101" },
          });
          const evidence = await getEvidence!({
            artifactId: "topology",
            claim: "equipment and connections around P-101",
          });
          emit({
            type: "tool_result",
            callId: "call-1",
            tool: "portlog_evidence",
            result: evidence,
          });
          emit({ type: "assistant_text_delta", text: "P-101 connects to V-201 [entity:P-101]." });
        },
        abort: async () => {},
        dispose: async () => {},
      }),
      getEvidence: async () => ({
        citations: ["entity:P-101", "entity:V-201"],
        sourceScopeIds: ["P-101", "V-201"],
        diagnostics: [],
      }),
    });

    assert.equal(record.posture, "inspect");
    assert.equal(record.status, "completed");
    assert.deepEqual(record.evidenceIds, ["entity:P-101", "entity:V-201"]);
    assert.doesNotMatch(record.finalText, /\b(satisfied|violated)\b/i);

    const reopened = await loadLocalProject(projectDirectory);
    assert.equal(reopened.schemaVersion, 2);
    assert.deepEqual(reopened.turns, [record]);
    assert.deepEqual(
      reopened.turns[0].events.map((event: { type: string }) => event.type),
      [
        "turn_started",
        "assistant_text_delta",
        "tool_request",
        "tool_result",
        "assistant_text_delta",
        "turn_completed",
      ],
    );
    assert.equal(
      reopened.turns[0].finalText,
      "I will inspect P-101. P-101 connects to V-201 [entity:P-101].",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("review posture asks Pi to run the governed E06 tool sequence", async () => {
  let promptText = "";
  const record = await runLocalReviewInspection({
    turnId: "review-posture-turn",
    question: "Review the E06 pump discharge path.",
    posture: "review",
    model: { provider: "test", id: "test" },
    signal: new AbortController().signal,
    createTurn: async ({ emit }) => ({
      prompt: async (prompt) => {
        promptText = prompt;
        emit({ type: "assistant_text_delta", text: "Review complete." });
      },
      abort: async () => {},
      dispose: async () => {},
    }),
  });

  assert.equal(record.status, "completed");
  assert.match(promptText, /portlog_evidence/);
  assert.match(promptText, /portlog_rule_check/);
  assert.match(promptText, /portlog_isolated_command/);
  assert.ok(promptText.indexOf("portlog_evidence") < promptText.indexOf("portlog_rule_check"));
  assert.ok(
    promptText.indexOf("portlog_rule_check") < promptText.indexOf("portlog_isolated_command"),
  );
});
test("optional isolated command results use the existing PortLog event path", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-isolated-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  const controller = new AbortController();
  const isolatedResult = {
    outcome: "admitted" as const,
    diagnostic: "Native guest child completed.",
    provenance: {
      runId: "isolated-turn",
      backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
      image: { id: "alpine-base", digest: "builtin:alpine-base" },
      policy: { id: "qemu-hvf-deny-all", digest: "builtin:qemu-hvf-deny-all" },
      commandProfile: { id: "native-child-echo", version: "1" },
      startedAt: "2026-08-03T00:00:00.000Z",
      completedAt: "2026-08-03T00:00:00.001Z",
      durationMs: 1,
      outcome: "admitted" as const,
    },
    exitCode: 0,
  };
  const isolatedToolResult = toIsolatedCommandToolResult(isolatedResult);
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "isolated-session",
      filename: "C01.xml",
      status: "ready",
    });
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "isolated-turn",
      question: "Run the approved native child.",
      posture: "chat",
      model: { provider: "test", id: "test" },
      signal: controller.signal,
      runIsolatedCommand: async ({ profileId }, signal) => {
        assert.equal(profileId, "native-child-echo");
        assert.equal(signal, controller.signal);
        return isolatedResult;
      },
      createTurn: async ({ emit, runIsolatedCommand }) => ({
        prompt: async () => {
          emit({ type: "assistant_text_delta", text: "I will run the approved child. " });
          emit({
            type: "tool_request",
            callId: "isolated-call",
            tool: "portlog_isolated_command",
            arguments: { profileId: "native-child-echo" },
          });
          await runIsolatedCommand!({ profileId: "native-child-echo" }, controller.signal);
          emit({
            type: "tool_result",
            callId: "isolated-call",
            tool: "portlog_isolated_command",
            result: isolatedToolResult,
          });
          emit({ type: "assistant_text_delta", text: "The approved child completed." });
        },
        abort: async () => {},
        dispose: async () => {},
      }),
    });

    assert.equal(record.status, "completed");
    assert.equal(record.finalText, "I will run the approved child. The approved child completed.");
    assert.deepEqual(
      record.events.map((event) => event.type),
      [
        "turn_started",
        "assistant_text_delta",
        "tool_request",
        "tool_result",
        "assistant_text_delta",
        "turn_completed",
      ],
    );
    const toolResult = record.events.find((event) => event.type === "tool_result");
    assert.ok(toolResult && "result" in toolResult);
    assert.deepEqual(toolResult.result, isolatedToolResult);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("non-success isolated outcomes persist remediation without an admitted artifact", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-isolated-rejected-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  const rejectedResult = {
    outcome: "rejected" as const,
    diagnostic: "The requested command profile is not approved.",
    provenance: {
      runId: "rejected-turn",
      backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
      image: { id: "alpine-base", digest: "builtin:alpine-base" },
      policy: { id: "qemu-hvf-deny-all", digest: "builtin:qemu-hvf-deny-all" },
      commandProfile: { id: "unapproved-profile", version: "1" },
      startedAt: "2026-08-03T00:00:00.000Z",
      completedAt: "2026-08-03T00:00:00.001Z",
      durationMs: 1,
      outcome: "rejected" as const,
    },
  };
  const rejectedToolResult = toIsolatedCommandToolResult(rejectedResult);

  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "isolated-rejected-session",
      filename: "C01.xml",
      status: "ready",
    });
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "rejected-turn",
      question: "Run the unapproved command profile.",
      posture: "chat",
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      runIsolatedCommand: async ({ profileId }) => {
        assert.equal(profileId, "unapproved-profile");
        return rejectedResult;
      },
      createTurn: async ({ emit, runIsolatedCommand }) => ({
        prompt: async () => {
          emit({
            type: "tool_request",
            callId: "rejected-call",
            tool: "portlog_isolated_command",
            arguments: { profileId: "unapproved-profile" },
          });
          const result = await runIsolatedCommand!(
            { profileId: "unapproved-profile" },
            new AbortController().signal,
          );
          emit({
            type: "tool_result",
            callId: "rejected-call",
            tool: "portlog_isolated_command",
            result: toIsolatedCommandToolResult(result),
          });
          emit({ type: "assistant_text_delta", text: "The command was not admitted." });
        },
        abort: async () => {},
        dispose: async () => {},
      }),
    });

    assert.equal(record.status, "completed");
    const toolResult = record.events.find((event) => event.type === "tool_result");
    assert.ok(toolResult && "result" in toolResult);
    assert.deepEqual(toolResult.result, rejectedToolResult);
    assert.match(JSON.stringify(toolResult.result), /approved profile/i);
    assert.equal(
      (toolResult.result as { provenance: { artifact?: unknown } }).provenance.artifact,
      undefined,
    );
    assert.deepEqual((await loadLocalProject(projectDirectory)).turns, [record]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("a general desktop chat turn works without a project manifest or evidence bridge", async () => {
  let promptText = "";
  const record = await runLocalDesktopChat({
    turnId: "chat-without-pid",
    question: "Hello without an uploaded P&ID.",
    model: { provider: "openai-codex", id: "gpt-5.4" },
    signal: new AbortController().signal,
    createTurn: async ({ emit, getEvidence }) => {
      assert.equal(getEvidence, undefined);
      return {
        prompt: async (text) => {
          promptText = text;
          emit({ type: "assistant_text_delta", text: "Hello from desktop chat." });
        },
        abort: async () => {},
        dispose: async () => {},
      };
    },
  });
  assert.equal(record.status, "completed");
  assert.equal(record.finalText, "Hello from desktop chat.");
  assert.match(promptText, /general conversation/i);
});

test("cancellation stops active work and persists one honest terminal record", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-cancel-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  const controller = new AbortController();
  let abortCalls = 0;
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01",
      filename: "C01.xml",
      status: "ready",
    });
    const resultPromise = runLocalReviewInspection({
      projectDirectory,
      turnId: "cancelled-turn",
      question: "Inspect P-101",
      model: { provider: "test", id: "test" },
      signal: controller.signal,
      getEvidence: async () => ({}),
      createTurn: async () => {
        let settle!: () => void;
        const stopped = new Promise<void>((resolve) => {
          settle = resolve;
        });
        return {
          prompt: () => stopped,
          abort: async () => {
            abortCalls += 1;
            settle();
          },
          dispose: async () => {},
        };
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    controller.abort();
    const record = await resultPromise;
    assert.equal(record.status, "cancelled");
    assert.equal(abortCalls, 1);
    assert.equal(record.events.at(-1)?.type, "turn_cancelled");
    assert.deepEqual((await loadLocalProject(projectDirectory)).turns, [record]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("a failed partial turn remains inspectable and retry replaces rather than duplicates authority", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-retry-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01",
      filename: "C01.xml",
      status: "ready",
    });
    const common = {
      projectDirectory,
      turnId: "retryable-turn",
      question: "Inspect P-101",
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      getEvidence: async () => ({}),
    };
    const failed = await runLocalReviewInspection({
      ...common,
      createTurn: async ({ emit }) => ({
        prompt: async () => {
          emit({ type: "assistant_text_delta", text: "Partial" });
          throw new Error("model stream disconnected");
        },
        abort: async () => {},
        dispose: async () => {},
      }),
    });
    assert.equal(failed.status, "failed");
    assert.equal(failed.finalText, "Partial");
    assert.match(failed.error ?? "", /disconnected/);

    const retried = await runLocalReviewInspection({
      ...common,
      signal: new AbortController().signal,
      createTurn: async ({ emit }) => ({
        prompt: async () =>
          emit({ type: "assistant_text_delta", text: "Grounded answer [entity:P-101]" }),
        abort: async () => {},
        dispose: async () => {},
      }),
    });
    assert.equal(retried.status, "completed");
    const reopened = await loadLocalProject(projectDirectory);
    assert.equal(reopened.turns.length, 1);
    assert.equal(reopened.turns[0].status, "completed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Inspect states explicit insufficiency when the model supplies no governed evidence", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-insufficient-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  try {
    await persistLocalProject({
      projectDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "c01",
      filename: "C01.xml",
      status: "ready",
    });
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "insufficient",
      question: "What is the design pressure?",
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [], diagnostics: [] }),
      createTurn: async ({ emit }) => ({
        prompt: async () =>
          emit({ type: "assistant_text_delta", text: "The design pressure is probably 10 bar." }),
        abort: async () => {},
        dispose: async () => {},
      }),
    });
    assert.equal(record.status, "completed");
    assert.match(record.finalText, /evidence is insufficient/i);
    assert.doesNotMatch(record.finalText, /10 bar/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
