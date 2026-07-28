import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { startLocalReviewRuntime } from "./local-review-runtime.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const python = resolve(repoRoot, ".venv/bin/python");

test("supervises the real local PortLog review API through readiness and clean shutdown", async () => {
  const artifactRoot = await mkdtemp(`${tmpdir()}/portlog-desktop-sidecar-`);
  const runtime = await startLocalReviewRuntime({
    command: python,
    args: ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "0"],
    workingDirectory: repoRoot,
    environment: {
      HARBORFIELD_DEPLOYMENT_PROFILE: "local",
      HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifactRoot,
      PYTHONPATH: repoRoot,
    },
    endpointFromStdout: (line) => {
      const match = /Uvicorn running on (http:\/\/\S+)/.exec(line);
      return match?.[1] ?? null;
    },
    healthPath: "/api/review/sessions",
  });

  try {
    const response = await fetch(`${runtime.endpoint}/api/review/sessions`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { sessions: [] });
  } finally {
    await runtime.stop();
    await rm(artifactRoot, { force: true, recursive: true });
  }
});
