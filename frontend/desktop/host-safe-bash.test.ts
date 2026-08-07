import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { promisify } from "node:util";

import type { BashOutputUpdate } from "./bash-capability.ts";
import { runHostSafeBash } from "./host-safe-bash.ts";

const execFileAsync = promisify(execFile);

test("host-safe executor runs pwd without a shell and emits output updates", async () => {
  const cwd = await mkdtemp(path.join(os.tmpdir(), "portlog-host-safe-"));
  const updates: BashOutputUpdate[] = [];
  try {
    const result = await runHostSafeBash(
      { command: "pwd", cwd, workspaceRoot: cwd, timeoutMs: 1_000, pty: false, env: {} },
      new AbortController().signal,
      (update) => updates.push(update),
    );

    assert.equal(result.outcome, "admitted");
    assert.equal(result.exitCode, 0);
    assert.equal(path.basename(result.stdout.trim()), path.basename(cwd));
    assert.equal(result.stderr, "");
    assert.ok(updates.length >= 1);
    assert.equal(result.stdoutBytes, Buffer.byteLength(result.stdout));
    assert.equal(result.stderrBytes, 0);
    assert.equal(result.stdoutTruncated, false);
    assert.equal(result.stderrTruncated, false);
    assert.deepEqual(
      updates.map((update) => update.sequence),
      updates.map((_update, index) => index + 1),
    );
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});

test("host-safe executor rejects a cwd symlink that leaves its workspace", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "portlog-host-safe-symlink-"));
  const workspaceRoot = path.join(root, "workspace");
  const outside = path.join(root, "outside");
  try {
    await mkdir(workspaceRoot);
    await mkdir(outside);
    await symlink(outside, path.join(workspaceRoot, "linked"));
    const result = await runHostSafeBash(
      {
        command: "pwd",
        cwd: path.join(workspaceRoot, "linked"),
        workspaceRoot,
        timeoutMs: 1_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );
    assert.equal(result.outcome, "unavailable");
    assert.equal(result.stdout, "");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("host-safe git status fails closed when workspace has no repo", async () => {
  const outer = await mkdtemp(path.join(os.tmpdir(), "portlog-host-safe-git-outer-"));
  const workspaceRoot = path.join(outer, "workspace");
  try {
    await mkdir(workspaceRoot);
    // Outer temp dirs can sit under a host checkout; the ceiling must still
    // prevent discovering that enclosing repository.
    const result = await runHostSafeBash(
      {
        command: "git status --short",
        cwd: workspaceRoot,
        workspaceRoot,
        timeoutMs: 1_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );
    assert.equal(result.outcome, "failed");
    assert.equal(result.exitCode, 128);
    assert.match(result.stderr, /not a git repository/i);
    assert.equal(result.stdout, "");
  } finally {
    await rm(outer, { recursive: true, force: true });
  }
});

test("host-safe git status uses an in-workspace repo and ignores enclosing repos", async () => {
  const outer = await mkdtemp(path.join(os.tmpdir(), "portlog-host-safe-git-nested-"));
  const workspaceRoot = path.join(outer, "workspace");
  try {
    await mkdir(workspaceRoot);
    await execFileAsync("git", ["init"], { cwd: workspaceRoot });
    await execFileAsync("git", ["config", "user.email", "portlog@example.com"], {
      cwd: workspaceRoot,
    });
    await execFileAsync("git", ["config", "user.name", "PortLog"], { cwd: workspaceRoot });
    await writeFile(path.join(workspaceRoot, "note.txt"), "hello\n", "utf8");
    const result = await runHostSafeBash(
      {
        command: "git status --short",
        cwd: workspaceRoot,
        workspaceRoot,
        timeoutMs: 1_000,
        pty: false,
        env: {},
      },
      new AbortController().signal,
    );
    assert.equal(result.outcome, "admitted");
    assert.equal(result.exitCode, 0);
    assert.match(result.stdout, /note\.txt/);
  } finally {
    await rm(outer, { recursive: true, force: true });
  }
});
