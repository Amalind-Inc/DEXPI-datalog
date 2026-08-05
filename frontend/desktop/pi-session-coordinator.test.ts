import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PortLogPiSessionCoordinator,
  PortLogSessionError,
  type PortLogSessionIdentity,
} from "./pi-session-coordinator.ts";

function identity(
  workspaceRoot: string,
  sourceDigest = `sha256:${"1".repeat(64)}`,
): PortLogSessionIdentity {
  return {
    workspaceRoot,
    projectId: "project-1",
    sourceDigest,
    policy: { id: "desktop-review", version: "1", digest: "sha256:policy-1" },
    toolProfile: { id: "pi-read-evidence", version: "1", digest: "sha256:tools-1" },
  };
}

async function makeRoot(): Promise<string> {
  const root = join(
    tmpdir(),
    `portlog-pi-session-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  await mkdir(join(root, "workspace"), { recursive: true });
  return root;
}

test("native Pi JSONL is canonical across coordinator close and reopen", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const sessionRoot = join(root, "sessions");
  const options = { sessionRoot, sessionId: "session-1", identity: identity(workspaceRoot) };
  try {
    const created = await PortLogPiSessionCoordinator.create(options);
    await created.appendMessage({
      role: "user",
      content: [{ type: "text", text: "Read the operator notes." }],
      timestamp: Date.now(),
    });
    await created.appendCustomEntry("portlog_turn_started", { turnId: "turn-1" });
    const sessionPath = created.sessionPath;
    await created.close();

    const reopened = await PortLogPiSessionCoordinator.open(options);
    const entries = await reopened.getEntries();
    assert.equal(reopened.sessionPath, sessionPath);
    assert.equal(
      entries.filter((entry) => (entry as { type?: string }).type === "message").length,
      1,
    );
    const customEntry = entries.find((entry) => (entry as { type?: string }).type === "custom") as
      | { customType?: string }
      | undefined;
    assert.equal(customEntry?.customType, "portlog_turn_started");
    await reopened.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("reopen rejects a changed project, source, policy, or tool identity", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const sessionRoot = join(root, "sessions");
  const options = { sessionRoot, sessionId: "session-identity", identity: identity(workspaceRoot) };
  try {
    const created = await PortLogPiSessionCoordinator.create(options);
    await created.close();
    const otherWorkspaceRoot = join(root, "other-workspace");
    await mkdir(otherWorkspaceRoot, { recursive: true });
    const base = identity(workspaceRoot);
    const variants: Array<[string, PortLogSessionIdentity]> = [
      ["workspace", { ...base, workspaceRoot: otherWorkspaceRoot }],
      ["project", { ...base, projectId: "project-2" }],
      ["source", { ...base, sourceDigest: `sha256:${"2".repeat(64)}` }],
      ["invalid source", { ...base, sourceDigest: "sha256:unknown" }],
      ["policy", { ...base, policy: { ...base.policy, digest: "sha256:policy-2" } }],
      ["tool profile", { ...base, toolProfile: { ...base.toolProfile, version: "2" } }],
    ];
    for (const [label, changedIdentity] of variants) {
      await assert.rejects(
        PortLogPiSessionCoordinator.open({ ...options, identity: changedIdentity }),
        (error: unknown) =>
          error instanceof PortLogSessionError &&
          (error.code === "identity_mismatch" ||
            (label === "workspace" && error.code === "not_found")),
        `${label} identity must fail closed`,
      );
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("a live writer is fenced and a stale dead-PID writer can be recovered", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const sessionRoot = join(root, "sessions");
  const options = { sessionRoot, sessionId: "session-fence", identity: identity(workspaceRoot) };
  try {
    const first = await PortLogPiSessionCoordinator.create(options);
    await assert.rejects(
      PortLogPiSessionCoordinator.open(options),
      (error: unknown) => error instanceof PortLogSessionError && error.code === "writer_conflict",
    );
    await first.close();

    const lockRoot = join(sessionRoot, ".portlog-writer-fences");
    const lockPath = join(lockRoot, `${options.sessionId}.lock`);
    await writeFile(lockPath, JSON.stringify({ pid: 999999, token: "stale", epoch: 1 }));
    const recovered = await PortLogPiSessionCoordinator.open(options);
    await recovered.appendCustomEntry("portlog_recovered", { ok: true });
    await recovered.close();

    const epoch = Number.parseInt(
      await readFile(join(lockRoot, `${options.sessionId}.epoch`), "utf8"),
      10,
    );
    assert.ok(epoch >= 2);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("appending after close fails instead of bypassing the writer fence", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    sessionId: "session-closed",
    identity: identity(workspaceRoot),
  };
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    await coordinator.close();
    await assert.rejects(
      coordinator.appendCustomEntry("should_not_write"),
      (error: unknown) => error instanceof PortLogSessionError && error.code === "writer_lost",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
