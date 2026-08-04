import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  CAPABILITY_CASES,
  evaluateCapabilityCase,
  extractPortLogRecord,
  runCapabilityMatrix,
  writeCapabilityReport,
  type CapabilityRecord,
} from "./portlog-capability-eval.ts";
function record(
  posture: string,
  status: string,
  tools: string[],
  extra: Record<string, unknown> = {},
): CapabilityRecord {
  return {
    posture,
    status,
    evidenceIds: posture === "inspect" ? ["node-H-1009"] : [],
    deterministicChecks:
      posture === "verify" ? [{ run_status: "completed", outcome: "satisfied" }] : [],
    events: tools.map((tool, index) => ({
      type: "tool_request",
      sequence: index + 1,
      tool,
      arguments: {},
    })),
    ...extra,
  };
}

test("inspect evidence capability passes without a VM", () => {
  const capability = CAPABILITY_CASES.find((item) => item.id === "inspect-evidence");
  assert.ok(capability);
  const result = evaluateCapabilityCase(
    capability,
    record("inspect", "completed", ["portlog_evidence"]),
  );

  assert.equal(result.passed, true);
  assert.equal(result.vmRequired, false);
  assert.deepEqual(result.toolNames, ["portlog_evidence"]);
  assert.deepEqual(result.diagnostics, []);
});

test("inspect capability fails when an isolated tool appears", () => {
  const capability = CAPABILITY_CASES.find((item) => item.id === "inspect-evidence");
  assert.ok(capability);
  const result = evaluateCapabilityCase(
    capability,
    record("inspect", "completed", ["portlog_evidence", "portlog_isolated_command"]),
  );

  assert.equal(result.passed, false);
  assert.ok(result.diagnostics.some((diagnostic) => diagnostic.code === "forbidden_tool"));
});

test("verify capability passes with a completed deterministic check", () => {
  const capability = CAPABILITY_CASES.find((item) => item.id === "verify-deterministic");
  assert.ok(capability);
  const result = evaluateCapabilityCase(
    capability,
    record("verify", "completed", ["portlog_rule_check"]),
  );

  assert.equal(result.passed, true);
  assert.equal(result.vmRequired, false);
});

test("cancelled review capability records VM use without requiring an artifact", () => {
  const capability = CAPABILITY_CASES.find((item) => item.id === "review-cancelled");
  assert.ok(capability);
  const result = evaluateCapabilityCase(
    capability,
    record(
      "review",
      "cancelled",
      ["portlog_evidence", "portlog_rule_check", "portlog_isolated_command"],
      {
        events: [
          { type: "tool_request", tool: "portlog_isolated_command" },
          {
            type: "tool_result",
            tool: "portlog_isolated_command",
            result: {
              provenance: {
                runId: "run-cancelled",
                backend: { id: "gondolin-qemu-hvf", version: "0.10.0" },
                outcome: "cancelled",
              },
            },
          },
        ],
      },
    ),
  );

  assert.equal(result.passed, true);
  assert.equal(result.vmRequired, true);
});

test("extracts the final PortLog record and writes an atomic capability report", async () => {
  const parsed = extractPortLogRecord(
    `TURN COMPLETED\nFINAL PORTLOG RECORD\n${JSON.stringify({ status: "completed" })}`,
  );
  assert.deepEqual(parsed, { status: "completed" });

  const root = await mkdtemp(join(tmpdir(), "portlog-capability-eval-"));
  const outputPath = join(root, "report.json");
  try {
    await writeCapabilityReport(outputPath, {
      schemaVersion: 1,
      cases: [],
      results: [],
      summary: { passed: 0, failed: 0 },
    });
    assert.deepEqual(JSON.parse(await readFile(outputPath, "utf8")), {
      schemaVersion: 1,
      cases: [],
      results: [],
      summary: { passed: 0, failed: 0 },
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("runs a selected case and persists its raw record with classification", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-capability-matrix-"));
  const outputPath = join(root, "matrix.json");
  let seenArgs: string[] = [];
  try {
    const report = await runCapabilityMatrix({
      project: join(root, "project"),
      provider: "openrouter",
      model: "test-model",
      caseIds: ["inspect-evidence"],
      outputPath,
      executeReview: async (args) => {
        seenArgs = args;
        const captured = record("inspect", "completed", ["portlog_evidence"]);
        return {
          exitCode: 0,
          signal: null,
          stdout: `FINAL PORTLOG RECORD\n${JSON.stringify(captured)}`,
          stderr: "",
        };
      },
    });

    assert.deepEqual(report.summary, { passed: 1, failed: 0 });
    assert.ok(seenArgs.includes("--posture"));
    assert.ok(seenArgs.includes("inspect"));
    assert.equal(report.results[0]?.record?.status, "completed");
    assert.equal(JSON.parse(await readFile(outputPath, "utf8")).summary.passed, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
