import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadLocalProject, persistLocalProject } from "./local-project-manifest.cjs";
import { runLocalReviewInspection } from "./local-review-inspection.ts";

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
          const evidence = await getEvidence({
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
