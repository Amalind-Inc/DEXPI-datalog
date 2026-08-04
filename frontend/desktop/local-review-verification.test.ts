import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { persistLocalProject } from "./local-project-manifest.cjs";
import { runLocalReviewInspection } from "./local-review-inspection.ts";

async function makeProject() {
  const root = await mkdtemp(join(tmpdir(), "portlog-local-verify-"));
  const projectDirectory = join(root, "project");
  const sourcePath = join(root, "C01.xml");
  await writeFile(sourcePath, "<PlantModel />");
  await persistLocalProject({
    projectDirectory,
    sourcePath,
    sourceContent: "<PlantModel />",
    sessionId: "c01",
    filename: "C01.xml",
    status: "ready",
  });
  return { root, projectDirectory };
}

async function runVerifyResult(question: string, requestedEntityId: string) {
  const { root, projectDirectory } = await makeProject();
  try {
    return await runLocalReviewInspection({
      projectDirectory,
      turnId: `verify-${requestedEntityId}`,
      posture: "verify",
      question,
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [] }),
      createTurn: async ({ emit }) => ({
        prompt: async () => {
          emit({ type: "assistant_text_delta", text: "The model thinks this is satisfied." });
          emit({
            type: "tool_result",
            callId: "check-1",
            tool: "portlog_rule_check",
            result: {
              deterministic_result: {
                check_id: "pump_discharge_check_valve",
                check_version: "1",
                run_status: "completed",
                outcome: "violated",
                reason_code: "no_check_valve_on_complete_segment",
                scope: {
                  class: "CentrifugalPump",
                  pump_id: "pump-1",
                  requested_entity_id: requestedEntityId,
                },
                evidence: { ordered_topology_ids: [requestedEntityId, "N-1"] },
              },
            },
          });
        },
        abort: async () => {},
        dispose: async () => {},
      }),
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("Verify fails closed when no PortLog deterministic result is returned", async () => {
  const { root, projectDirectory } = await makeProject();
  try {
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "verify-missing-result",
      posture: "verify",
      question: "Does P-101 have a check valve on its first discharge segment?",
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [] }),
      createTurn: async ({ emit }) => ({
        prompt: async () => emit({ type: "assistant_text_delta", text: "It is satisfied." }),
        abort: async () => {},
        dispose: async () => {},
      }),
    });
    assert.equal(record.posture, "verify");
    assert.equal(record.status, "completed");
    assert.deepEqual(record.deterministicChecks, []);
    assert.match(record.finalText, /did not complete/i);
    assert.doesNotMatch(record.finalText, /It is satisfied/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Verify restates the PortLog outcome instead of trusting model verdict prose", async () => {
  const { root, projectDirectory } = await makeProject();
  try {
    const record = await runLocalReviewInspection({
      projectDirectory,
      turnId: "verify-owned-result",
      posture: "verify",
      question: "Does P-4713 have a check valve on its first discharge segment?",
      model: { provider: "test", id: "test" },
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [] }),
      createTurn: async ({ emit }) => ({
        prompt: async () => {
          emit({
            type: "assistant_text_delta",
            text: "The model thinks this is satisfied.",
          });
          emit({
            type: "tool_result",
            callId: "check-1",
            tool: "portlog_rule_check",
            result: {
              deterministic_result: {
                check_id: "pump_discharge_check_valve",
                check_version: "1",
                run_status: "completed",
                outcome: "violated",
                reason_code: "no_check_valve_on_complete_segment",
                scope: {
                  class: "CentrifugalPump",
                  pump_id: "pump-1",
                  requested_entity_id: "P-4713",
                },
                evidence: { ordered_topology_ids: ["P-4713", "N-1"] },
              },
            },
          });
        },
        abort: async () => {},
        dispose: async () => {},
      }),
    });
    assert.equal(record.status, "completed");
    assert.equal(record.deterministicChecks[0].outcome, "violated");
    assert.match(record.finalText, /violated/i);
    assert.doesNotMatch(record.finalText, /model thinks this is satisfied/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Verify rejects universal questions instead of reusing a single pump result", async () => {
  const record = await runVerifyResult(
    "Must every connected object satisfy the temporary topology rule?",
    "P-4713",
  );
  assert.match(record.finalText, /does not answer this question/i);
  assert.doesNotMatch(record.finalText, /PortLog deterministic check/i);
  assert.doesNotMatch(record.finalText, /\bviolated\b/i);
});

test("Verify rejects a deterministic pump result for non-pump equipment", async () => {
  const record = await runVerifyResult(
    "Does heat exchanger H-1009 have a downstream check valve?",
    "P-4713",
  );
  assert.match(record.finalText, /does not answer this question/i);
  assert.doesNotMatch(record.finalText, /P-4713.*violated/i);
});

test("Verify rejects a deterministic result whose scope differs from the question", async () => {
  const record = await runVerifyResult(
    "Does P-999 have a check valve on its first discharge segment?",
    "P-4713",
  );
  assert.match(record.finalText, /does not answer this question/i);
  assert.doesNotMatch(record.finalText, /PortLog deterministic check/i);
});
