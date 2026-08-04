import assert from "node:assert/strict";
import test from "node:test";

import { routeCapabilities } from "./capability-routing.ts";

const getEvidence = async () => ({ citations: ["node-pump"] });
const getRuleCheck = async () => ({ deterministic_result: { outcome: "violated" } });
const runIsolatedCommand = async () => ({
  outcome: "admitted" as const,
  diagnostic: "candidate admitted",
  provenance: {
    runId: "routing-test",
    backend: { id: "test", version: "1" },
    image: { id: "image", digest: "sha256:image" },
    policy: { id: "deny-all", digest: "sha256:policy" },
    commandProfile: { id: "native-analysis", version: "1" },
    startedAt: "2026-08-04T00:00:00.000Z",
    completedAt: "2026-08-04T00:00:00.001Z",
    durationMs: 1,
    outcome: "admitted" as const,
  },
  exitCode: 0,
});

function route(mode: "inspection" | "chat", posture?: "inspect" | "verify" | "review" | "chat") {
  return routeCapabilities({
    mode,
    posture,
    getEvidence,
    getRuleCheck,
    runIsolatedCommand,
  });
}

test("prepared inspect and verify routes keep analysis on the host", () => {
  for (const posture of ["inspect", "verify"] as const) {
    const result = route("inspection", posture);
    assert.equal(result.prepared, true);
    assert.equal(result.hostEvidence, true);
    assert.equal(result.hostRules, true);
    assert.equal(result.isolatedExecution, false);
    assert.equal(result.getEvidence, getEvidence);
    assert.equal(result.getRuleCheck, getRuleCheck);
    assert.equal(result.runIsolatedCommand, undefined);
  }
});

test("review routing exposes the approved isolated capability without moving host bridges", () => {
  const result = route("inspection", "review");

  assert.equal(result.prepared, true);
  assert.equal(result.hostEvidence, true);
  assert.equal(result.hostRules, true);
  assert.equal(result.isolatedExecution, true);
  assert.equal(result.getEvidence, getEvidence);
  assert.equal(result.getRuleCheck, getRuleCheck);
  assert.equal(result.runIsolatedCommand, runIsolatedCommand);
});

test("review routing stays host-only when no isolated executor is available", () => {
  const result = routeCapabilities({
    mode: "inspection",
    posture: "review",
    getEvidence,
    getRuleCheck,
  });

  assert.equal(result.prepared, true);
  assert.equal(result.hostEvidence, true);
  assert.equal(result.hostRules, true);
  assert.equal(result.isolatedExecution, false);
  assert.equal(result.runIsolatedCommand, undefined);
});

test("general chat exposes no prepared-project or VM capability", () => {
  const result = route("chat", "chat");

  assert.equal(result.prepared, false);
  assert.equal(result.hostEvidence, false);
  assert.equal(result.hostRules, false);
  assert.equal(result.isolatedExecution, false);
  assert.equal(result.getEvidence, undefined);
  assert.equal(result.getRuleCheck, undefined);
  assert.equal(result.runIsolatedCommand, undefined);
});
