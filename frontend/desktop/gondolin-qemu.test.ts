import assert from "node:assert/strict";
import { access, constants } from "node:fs/promises";
import test from "node:test";

import {
  GONDOLIN_QEMU_PROFILE,
  GONDOLIN_REVIEW_CANDIDATE_PROFILE,
  createGondolinQemuExecutor,
} from "./gondolin-qemu.ts";
import type { IsolatedCommandRequest } from "./isolated-command.ts";

const qemuPath = process.env.PORTLOG_QEMU_PATH ?? "/opt/homebrew/bin/qemu-system-aarch64";
let qemuPrerequisite: string | undefined;
try {
  await access(qemuPath, constants.X_OK);
} catch {
  qemuPrerequisite = `QEMU/HVF prerequisite unavailable at ${qemuPath}`;
}
const hostPrerequisite =
  qemuPrerequisite ??
  (process.platform === "darwin" && process.arch === "arm64"
    ? undefined
    : "Gondolin QEMU/HVF requires an arm64 macOS host");

const request: IsolatedCommandRequest = {
  runId: "qemu-e06-001",
  inputBundle: {
    bundleId: "empty-dev-bundle",
    digest: "sha256:empty-dev-bundle",
    files: [],
  },
  commandProfile: GONDOLIN_QEMU_PROFILE,
  limits: {
    maxDurationMs: 60_000,
    maxMemoryBytes: 2 * 1024 * 1024 * 1024,
    maxCpuSeconds: 30,
    maxScratchBytes: 0,
    maxOutputCount: 0,
    maxOutputBytes: 0,
  },
  signal: new AbortController().signal,
};

const candidateRequest: IsolatedCommandRequest = {
  ...request,
  runId: "qemu-e06-candidate-001",
  inputBundle: {
    bundleId: "review-bundle-001",
    digest: "sha256:review-bundle",
    files: [
      {
        relativePath: "review.json",
        bytes: new TextEncoder().encode('{"review":"bounded"}'),
        digest: "sha256:review",
      },
    ],
  },
  commandProfile: GONDOLIN_REVIEW_CANDIDATE_PROFILE,
  limits: {
    ...request.limits,
    maxOutputBytes: 1_024,
  },
};

test(
  "Gondolin QEMU/HVF executes the approved native-child profile and closes the guest",
  { skip: hostPrerequisite },
  async () => {
    const executor = createGondolinQemuExecutor({ qemuPath });
    const result = await executor.runIsolatedCommand(request);

    assert.equal(result.outcome, "admitted");
    assert.equal(result.exitCode, 0);
    assert.equal(result.diagnostic, "Native guest child completed.");
    assert.equal(result.provenance.backend.id, "gondolin-qemu-hvf");
    assert.equal(result.provenance.backend.version, "0.10.0");
  },
);

test(
  "failed Gondolin command returns a bounded failure after closing the guest",
  { skip: hostPrerequisite },
  async () => {
    let closed = false;
    const executor = createGondolinQemuExecutor({
      qemuPath,
      createVm: async () => ({
        exec: async () => ({ exitCode: 17, stdout: "" }),
        close: async () => {
          closed = true;
        },
      }),
    });

    const result = await executor.runIsolatedCommand(request);

    assert.equal(result.outcome, "failed");
    assert.equal(result.exitCode, 17);
    assert.equal(result.diagnostic, "Native guest command failed with exit code 17.");
    assert.equal(closed, true);
  },
);

test(
  "Gondolin startup failure returns unavailable without a host fallback",
  { skip: hostPrerequisite },
  async () => {
    const executor = createGondolinQemuExecutor({
      qemuPath,
      createVm: async () => {
        throw new Error("guest startup failed");
      },
    });

    const result = await executor.runIsolatedCommand(request);

    assert.equal(result.outcome, "unavailable");
    assert.equal(result.diagnostic, "Gondolin QEMU/HVF could not start.");
  },
);

test(
  "Gondolin admits one valid bounded result candidate after read-only review input",
  { skip: hostPrerequisite },
  async () => {
    const executor = createGondolinQemuExecutor({ qemuPath });
    const result = await executor.runIsolatedCommand(candidateRequest);

    assert.equal(result.outcome, "admitted");
    assert.deepEqual(result.candidate, {
      schemaVersion: 1,
      status: "ok",
      message: "review bundle inspected",
    });
    assert.equal(result.provenance.artifact?.id, "result.json");
    assert.equal(result.provenance.artifact?.byteLength, 69);
    assert.equal(
      new TextDecoder().decode(candidateRequest.inputBundle.files[0].bytes),
      '{"review":"bounded"}',
    );
  },
);

test(
  "Gondolin rejects malformed result candidates through the same executor interface",
  { skip: hostPrerequisite },
  async () => {
    const executor = createGondolinQemuExecutor({
      qemuPath,
      createVm: async (vmOptions) => {
        const scratch = vmOptions.vfs?.mounts?.["/review/scratch"];
        if (!scratch?.writeFile) throw new Error("scratch mount is unavailable");
        await scratch.writeFile("/result.json", Buffer.from('{"schemaVersion":1}'));
        return {
          exec: async () => ({ exitCode: 0, stdout: "" }),
          close: async () => {},
        };
      },
    });

    const result = await executor.runIsolatedCommand(candidateRequest);

    assert.equal(result.outcome, "rejected");
    assert.match(result.diagnostic, /schema|candidate/i);
    assert.equal(result.provenance.artifact, undefined);
  },
);
