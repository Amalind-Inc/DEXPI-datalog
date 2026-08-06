import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { runHostSafeBash } from "./host-safe-bash.ts";

test("host-safe executor runs pwd without a shell and emits output updates", async () => {
  const cwd = await mkdtemp(path.join(os.tmpdir(), "portlog-host-safe-"));
  const updates: Array<{ stdout: string; stderr: string }> = [];
  try {
    const result = await runHostSafeBash(
      { command: "pwd", cwd, timeoutMs: 1_000, pty: false, env: {} },
      new AbortController().signal,
      (update) => updates.push(update),
    );

    assert.equal(result.outcome, "admitted");
    assert.equal(result.exitCode, 0);
    assert.equal(path.basename(result.stdout.trim()), path.basename(cwd));
    assert.equal(result.stderr, "");
    assert.ok(updates.length >= 1);
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});
