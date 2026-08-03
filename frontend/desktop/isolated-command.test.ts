import assert from "node:assert/strict";
import test from "node:test";

import {
  createInMemoryIsolatedCommandExecutor,
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
