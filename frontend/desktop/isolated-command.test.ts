import assert from "node:assert/strict";
import test from "node:test";

import {
  createInMemoryIsolatedCommandExecutor,
  toIsolatedCommandToolResult,
  type IsolatedCommandRequest,
} from "./isolated-command.ts";

function request(signal: AbortSignal): IsolatedCommandRequest {
  return {
    runId: "run-e06-001",
    inputBundle: {
      bundleId: "bundle-e06-001",
      digest: "sha256:bundle",
      files: [
        {
          relativePath: "review.json",
          bytes: new Uint8Array([1, 2, 3]),
          digest: "sha256:review",
        },
      ],
    },
    commandProfile: { id: "e06-review", version: "1" },
    limits: {
      maxDurationMs: 5_000,
      maxMemoryBytes: 128 * 1024 * 1024,
      maxCpuSeconds: 10,
      maxScratchBytes: 64 * 1024,
      maxOutputCount: 1,
      maxOutputBytes: 8 * 1024,
    },
    signal,
  };
}

test("isolated-command interface returns admitted result with host provenance", async () => {
  const executor = createInMemoryIsolatedCommandExecutor({
    backend: { id: "conformance", version: "1" },
    image: { id: "review-image", digest: "sha256:image" },
    policy: { id: "deny-all", digest: "sha256:policy" },
    artifact: { id: "artifact-e06-001", digest: "sha256:artifact", byteLength: 42 },
  });

  const result = await executor.runIsolatedCommand(request(new AbortController().signal));

  assert.equal(result.outcome, "admitted");
  assert.equal(result.exitCode, 0);
  assert.equal(result.diagnostic, "Isolated command completed.");
  assert.equal(result.provenance.runId, "run-e06-001");
  assert.deepEqual(result.provenance.backend, { id: "conformance", version: "1" });
  assert.deepEqual(result.provenance.image, {
    id: "review-image",
    digest: "sha256:image",
  });
  assert.deepEqual(result.provenance.policy, { id: "deny-all", digest: "sha256:policy" });
  assert.equal(result.provenance.commandProfile.id, "e06-review");
  assert.equal(result.provenance.outcome, "admitted");
  assert.deepEqual(result.provenance.artifact, {
    id: "artifact-e06-001",
    digest: "sha256:artifact",
    byteLength: 42,
  });
});

test("isolated-command interface turns an aborted request into a cancelled result", async () => {
  const controller = new AbortController();
  controller.abort();
  const executor = createInMemoryIsolatedCommandExecutor();

  const result = await executor.runIsolatedCommand(request(controller.signal));

  assert.equal(result.outcome, "cancelled");
  assert.match(result.diagnostic, /cancelled/i);
  assert.equal(result.provenance.outcome, "cancelled");
  assert.equal(result.provenance.artifact, undefined);
});

test("isolated-command interface bounds non-success diagnostics", async () => {
  const executor = createInMemoryIsolatedCommandExecutor({
    outcome: "rejected",
    diagnostic: "x".repeat(500),
  });

  const result = await executor.runIsolatedCommand(request(new AbortController().signal));

  assert.equal(result.outcome, "rejected");
  assert.equal(result.diagnostic.length, 240);
  assert.equal(result.provenance.artifact, undefined);
});

test("isolated-command tool results explain outcomes and preserve bounded provenance", async () => {
  const admitted = await createInMemoryIsolatedCommandExecutor({
    backend: { id: "conformance", version: "1" },
    image: { id: "review-image", digest: "sha256:image" },
    policy: { id: "deny-all", digest: "sha256:policy" },
    artifact: { id: "artifact-e06-001", digest: "sha256:artifact", byteLength: 42 },
  }).runIsolatedCommand(request(new AbortController().signal));
  const admittedToolResult = toIsolatedCommandToolResult(admitted);

  assert.equal(admittedToolResult.outcome, "admitted");
  assert.match(admittedToolResult.message, /admitted/i);
  assert.equal(admittedToolResult.remediation, undefined);
  assert.deepEqual(admittedToolResult.provenance.artifact, {
    id: "artifact-e06-001",
    digest: "sha256:artifact",
    byteLength: 42,
  });

  const rejected = await createInMemoryIsolatedCommandExecutor({
    outcome: "rejected",
  }).runIsolatedCommand(request(new AbortController().signal));
  const rejectedToolResult = toIsolatedCommandToolResult(rejected);

  assert.equal(rejectedToolResult.outcome, "rejected");
  assert.match(rejectedToolResult.message, /rejected/i);
  assert.match(rejectedToolResult.remediation ?? "", /approved profile/i);
  assert.equal(rejectedToolResult.provenance.artifact, undefined);

  const tainted = {
    ...admitted,
    rawTranscript: "guest output must not persist",
    provenance: {
      ...admitted.provenance,
      rawTranscript: "guest output must not persist",
      backend: { ...admitted.provenance.backend, rawTranscript: "guest output must not persist" },
    },
  } as unknown as typeof admitted;
  const taintedToolResult = toIsolatedCommandToolResult(tainted);
  assert.equal("rawTranscript" in taintedToolResult, false);
  assert.equal("rawTranscript" in taintedToolResult.provenance, false);
  assert.equal("rawTranscript" in taintedToolResult.provenance.backend, false);

  const rejectedWithArtifact = {
    ...rejected,
    provenance: {
      ...rejected.provenance,
      artifact: { id: "late", digest: "sha256:late", byteLength: 10 },
    },
  } as unknown as typeof rejected;
  assert.equal(toIsolatedCommandToolResult(rejectedWithArtifact).provenance.artifact, undefined);
});

test("isolated-command tool messages distinguish every terminal outcome", async () => {
  const outcomes = [
    "admitted",
    "rejected",
    "unavailable",
    "failed",
    "timed_out",
    "cancelled",
  ] as const;
  const toolResults = await Promise.all(
    outcomes.map(async (outcome) =>
      toIsolatedCommandToolResult(
        await createInMemoryIsolatedCommandExecutor({ outcome }).runIsolatedCommand(
          request(new AbortController().signal),
        ),
      ),
    ),
  );

  assert.equal(new Set(toolResults.map((result) => result.message)).size, outcomes.length);
  for (const result of toolResults) {
    assert.ok(result.message.length <= 240);
    if (result.outcome === "admitted") assert.equal(result.remediation, undefined);
    else assert.ok(result.remediation);
  }
});
