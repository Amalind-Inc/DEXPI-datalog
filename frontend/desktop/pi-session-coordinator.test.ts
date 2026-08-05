import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
test("observer attachments resync canonical history without prompt or append access", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const attachmentRoot = join(root, "attachments");
  const options = {
    sessionRoot: join(root, "sessions"),
    attachmentRoot,
    sessionId: "session-attachments-observer",
    identity: identity(workspaceRoot),
  };
  assert.notEqual(attachmentRoot, workspaceRoot);
  assert.ok(!attachmentRoot.startsWith(`${workspaceRoot}/`));
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    const credentials = await coordinator.issueClientCredentials({
      clientId: "observer-1",
      role: "observer",
      canApprove: true,
    });
    assert.equal(credentials.sessionId, options.sessionId);
    assert.equal(credentials.clientId, "observer-1");
    assert.equal(credentials.role, "observer");
    assert.equal(credentials.canApprove, true);
    assert.ok(credentials.token.length >= 32);

    const observer = await coordinator.attachClient(credentials);
    await coordinator.appendCustomEntry("portlog.test.attachment.v1", {
      value: "observer",
    });
    const snapshot = await observer.resync({ nextEntryIndex: 0 });
    const customEntry = snapshot.entries.find(
      (entry) =>
        (entry as { type?: string; customType?: string }).type === "custom" &&
        (entry as { customType?: string }).customType === "portlog.test.attachment.v1",
    );
    assert.ok(customEntry);
    assert.equal("enqueuePrompt" in observer, false);
    assert.equal("appendCustomEntry" in observer, false);
    assert.equal(JSON.stringify(snapshot.entries).includes(credentials.token), false);
    await coordinator.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("writer queue is durable and admission is coordinator-owned", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    attachmentRoot: join(root, "attachments"),
    sessionId: "session-attachments-writer",
    identity: identity(workspaceRoot),
  };
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    const credentials = await coordinator.issueClientCredentials({
      clientId: "writer-1",
      role: "writer",
    });
    const writer = await coordinator.attachClient(credentials);
    const beforeQueue = await writer.resync({ nextEntryIndex: 0 });
    const queueId = await writer.enqueuePrompt("Read the operator notes.");
    const queued = await writer.resync(beforeQueue.cursor);
    const queuedEntry = queued.entries.find(
      (entry) =>
        (entry as { type?: string; customType?: string }).type === "custom" &&
        (entry as { customType?: string }).customType === "portlog.queue.enqueued.v1",
    ) as { data?: { queueId?: string } } | undefined;
    assert.ok(queuedEntry);
    assert.equal(queuedEntry.data?.queueId, queueId);
    assert.equal(
      queued.entries.filter(
        (entry) =>
          (entry as { type?: string; message?: { role?: string } }).type === "message" &&
          (entry as { message?: { role?: string } }).message?.role === "user",
      ).length,
      0,
    );

    const admissionResults = await Promise.allSettled([
      coordinator.admitQueuedPrompt(queueId, "turn-1"),
      coordinator.admitQueuedPrompt(queueId, "turn-1"),
    ]);
    assert.equal(admissionResults.filter((result) => result.status === "fulfilled").length, 1);
    assert.equal(admissionResults.filter((result) => result.status === "rejected").length, 1);
    const admitted = await writer.resync(queued.cursor);
    const admissionEntry = admitted.entries.find(
      (entry) =>
        (entry as { type?: string; customType?: string }).type === "custom" &&
        (entry as { customType?: string }).customType === "portlog.queue.admitted.v1",
    ) as {
      data?: { queueId?: string; turnId?: string; admissionId?: string };
    } | undefined;
    assert.ok(admissionEntry);
    assert.equal(admissionEntry.data?.queueId, queueId);
    assert.equal(admissionEntry.data?.turnId, "turn-1");
    assert.equal(
      admitted.entries.filter(
        (entry) =>
          (entry as { type?: string; message?: { role?: string } }).type === "message" &&
          (entry as { message?: { role?: string } }).message?.role === "user",
      ).length,
      1,
    );
    const admittedMessage = admitted.entries.find(
      (entry) =>
        (entry as { type?: string; message?: { role?: string } }).type === "message" &&
        (entry as { message?: { role?: string } }).message?.role === "user",
    ) as
      | { message?: { portlogAdmission?: { admissionId?: string; turnId?: string } } }
      | undefined;
    assert.equal(admittedMessage?.message?.portlogAdmission?.admissionId, admissionEntry.data?.admissionId);
    assert.equal(admittedMessage?.message?.portlogAdmission?.turnId, "turn-1");
    assert.equal(admitted.entries.length, 2);
    await coordinator.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("queue admission intents recover across reopen without duplicate prompts", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    attachmentRoot: join(root, "attachments"),
    sessionId: "session-queue-recovery",
    identity: identity(workspaceRoot),
  };
  const text = "Read the operator notes once.";
  const policyTimestamp = 1_700_000_000_000;
  const message = {
    role: "user" as const,
    content: [{ type: "text" as const, text }],
    timestamp: policyTimestamp,
    portlogAdmission: { admissionId: "admission-recovery-1", turnId: "turn-recovery-1" },
  };
  const messageDigest = createHash("sha256").update(JSON.stringify(message)).digest("hex");
  const secondMessage = {
    ...message,
    timestamp: policyTimestamp + 1,
    portlogAdmission: { admissionId: "admission-recovery-2", turnId: "turn-recovery-2" },
  };
  const secondMessageDigest = createHash("sha256")
    .update(JSON.stringify(secondMessage))
    .digest("hex");
  const wrongSecondMessage = {
    ...secondMessage,
    portlogAdmission: { admissionId: "wrong-admission", turnId: "turn-recovery-2" },
  };
  try {
    const created = await PortLogPiSessionCoordinator.create(options);
    const credentials = await created.issueClientCredentials({
      clientId: "queue-recovery-writer",
      role: "writer",
    });
    const writer = await created.attachClient(credentials);
    const firstQueueId = await writer.enqueuePrompt(text);
    const firstIntentId = await created.appendCustomEntry("portlog.queue.admitted.v1", {
      queueId: firstQueueId,
      turnId: "turn-recovery-1",
      admissionId: "admission-recovery-1",
      text,
      messageTimestamp: policyTimestamp,
      messageDigest,
      admittedAt: new Date().toISOString(),
    });
    await created.close();

    const recovered = await PortLogPiSessionCoordinator.open(options);
    assert.deepEqual(await recovered.admitQueuedPrompt(firstQueueId, "turn-recovery-1"), {
      entryId: firstIntentId,
    });
    const recoveredWriter = await recovered.attachClient(credentials);
    const secondQueueId = await recoveredWriter.enqueuePrompt(text);
    const secondIntentId = await recovered.appendCustomEntry("portlog.queue.admitted.v1", {
      queueId: secondQueueId,
      turnId: "turn-recovery-2",
      admissionId: "admission-recovery-2",
      text,
      messageTimestamp: policyTimestamp + 1,
      messageDigest: secondMessageDigest,
      admittedAt: new Date().toISOString(),
    });
    await recovered.appendMessage(wrongSecondMessage);
    await recovered.close();

    const reopened = await PortLogPiSessionCoordinator.open(options);
    await assert.rejects(
      reopened.admitQueuedPrompt(firstQueueId, "turn-recovery-1"),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    await assert.rejects(
      reopened.admitQueuedPrompt(secondQueueId, "turn-recovery-2"),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    const entries = await reopened.getEntries();
    assert.equal(
      entries.filter(
        (entry) =>
          (entry as { customType?: string }).customType === "portlog.queue.admitted.v1",
      ).length,
      2,
    );
    assert.equal(
      entries.filter(
        (entry) =>
          (entry as { type?: string; message?: { role?: string } }).type === "message" &&
          (entry as { message?: { role?: string } }).message?.role === "user",
      ).length,
      2,
    );
    assert.equal(secondIntentId.length > 0, true);
    await reopened.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("scoped approvals accept only authorized exact one-time decisions", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    attachmentRoot: join(root, "attachments"),
    sessionId: "session-attachments-approval",
    identity: identity(workspaceRoot),
  };
  const action = "read_file";
  const target = "workspace/README.md";
  const policyDigest = "sha256:policy-1";
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    const approverCredentials = await coordinator.issueClientCredentials({
      clientId: "approver-1",
      role: "observer",
      canApprove: true,
    });
    const nonApproverCredentials = await coordinator.issueClientCredentials({
      clientId: "observer-1",
      role: "observer",
      canApprove: false,
    });
    const wrongObserverCredentials = await coordinator.issueClientCredentials({
      clientId: "observer-2",
      role: "observer",
      canApprove: true,
    });
    const approver = await coordinator.attachClient(approverCredentials);
    const nonApprover = await coordinator.attachClient(nonApproverCredentials);
    const wrongObserver = await coordinator.attachClient(wrongObserverCredentials);
    const request = await coordinator.requestApproval({
      action,
      target,
      policyDigest,
      expiresAt: Date.now() + 60_000,
      approverClientId: approverCredentials.clientId,
    });

    await assert.rejects(
      nonApprover.submitApproval({
        approvalRequestId: request.approvalRequestId,
        decision: "approve",
      }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    await assert.rejects(
      wrongObserver.submitApproval({
        approvalRequestId: request.approvalRequestId,
        decision: "approve",
      }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    const decisionResults = await Promise.allSettled([
      approver.submitApproval({
        approvalRequestId: request.approvalRequestId,
        decision: "approve",
      }),
      approver.submitApproval({
        approvalRequestId: request.approvalRequestId,
        decision: "approve",
      }),
    ]);
    assert.equal(decisionResults.filter((result) => result.status === "fulfilled").length, 1);
    assert.equal(decisionResults.filter((result) => result.status === "rejected").length, 1);

    const history = await approver.resync({ nextEntryIndex: 0 });
    const approvalEntries = history.entries.filter(
      (entry) =>
        (entry as { type?: string; customType?: string }).type === "custom" &&
        (entry as { customType?: string }).customType?.startsWith("portlog.approval."),
    ) as Array<{
      customType?: string;
      data?: {
        approvalRequestId?: string;
        bindingDigest?: string;
      };
    }>;
    assert.equal(
      approvalEntries.filter((entry) => entry.customType === "portlog.approval.requested.v1").length,
      1,
    );
    assert.equal(
      approvalEntries.filter((entry) => entry.customType === "portlog.approval.decided.v1").length,
      1,
    );
    assert.ok(approvalEntries.length >= 2);
    for (const entry of approvalEntries) {
      assert.equal(JSON.stringify(entry).includes(approverCredentials.token), false);
      assert.equal(entry.data?.approvalRequestId, request.approvalRequestId);
      assert.equal(entry.data?.bindingDigest, request.bindingDigest);
    }

    await assert.rejects(
      coordinator.consumeApproval(request.approvalRequestId, {
        action: "write_file",
        target,
        policyDigest,
        toolCallId: "tool-1",
      }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    const consumptionResults = await Promise.allSettled([
      coordinator.consumeApproval(request.approvalRequestId, {
        action,
        target,
        policyDigest,
        toolCallId: "tool-1",
      }),
      coordinator.consumeApproval(request.approvalRequestId, {
        action,
        target,
        policyDigest,
        toolCallId: "tool-1",
      }),
    ]);
    assert.equal(consumptionResults.filter((result) => result.status === "fulfilled").length, 1);
    assert.equal(consumptionResults.filter((result) => result.status === "rejected").length, 1);
    const consumedHistory = await approver.resync(history.cursor);
    assert.equal(
      consumedHistory.entries.filter(
        (entry) =>
          (entry as { type?: string; customType?: string }).customType ===
          "portlog.approval.consumed.v1",
      ).length,
      1,
    );

    const expiredRequest = await coordinator.requestApproval({
      action,
      target,
      policyDigest,
      expiresAt: Date.now() - 1,
      approverClientId: approverCredentials.clientId,
    });
    await assert.rejects(
      approver.submitApproval({
        approvalRequestId: expiredRequest.approvalRequestId,
        decision: "approve",
      }),
      (error: unknown) => error instanceof PortLogSessionError,
    );

    await coordinator.revokeClient(approverCredentials.clientId);
    await assert.rejects(
      approver.resync({ nextEntryIndex: 0 }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    await coordinator.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("malformed approval lifecycle order is rejected before consumption", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    sessionId: "session-malformed-approval",
    identity: identity(workspaceRoot),
  };
  const approvalRequestId = "approval-out-of-order";
  const action = "read_file";
  const target = "workspace/README.md";
  const policyDigest = "sha256:policy-1";
  const expiresAt = new Date(Date.now() + 60_000).toISOString();
  const approverClientId = "approver-1";
  const bindingDigest = createHash("sha256")
    .update(
      JSON.stringify({
        approvalRequestId,
        action,
        target,
        workspaceRoot,
        policyDigest,
        expiresAt,
        approverClientId,
      }),
    )
    .digest("hex");
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    await coordinator.appendCustomEntry("portlog.approval.decided.v1", {
      approvalRequestId,
      decision: "approve",
      clientId: approverClientId,
      bindingDigest,
    });
    await coordinator.appendCustomEntry("portlog.approval.requested.v1", {
      approvalRequestId,
      action,
      target,
      workspaceRoot,
      policyDigest,
      expiresAt,
      approverClientId,
      bindingDigest,
    });
    await assert.rejects(
      coordinator.consumeApproval(approvalRequestId, {
        action,
        target,
        policyDigest,
        toolCallId: "tool-1",
      }),
      (error: unknown) =>
        error instanceof PortLogSessionError && error.code === "approval_invalid",
    );
    await coordinator.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("canonical cursors resynchronize gaps without duplication", async () => {
  const root = await makeRoot();
  const workspaceRoot = join(root, "workspace");
  const options = {
    sessionRoot: join(root, "sessions"),
    attachmentRoot: join(root, "attachments"),
    sessionId: "session-attachments-cursor",
    identity: identity(workspaceRoot),
  };
  try {
    const coordinator = await PortLogPiSessionCoordinator.create(options);
    const credentials = await coordinator.issueClientCredentials({
      clientId: "cursor-observer",
      role: "observer",
    });
    const observer = await coordinator.attachClient(credentials);
    const initial = await observer.resync({ nextEntryIndex: 0 });
    await coordinator.appendCustomEntry("portlog.cursor.first.v1", { ordinal: 1 });
    await coordinator.appendCustomEntry("portlog.cursor.second.v1", { ordinal: 2 });

    const suffix = await observer.resync(initial.cursor);
    assert.equal(suffix.entries.length, 2);
    assert.deepEqual(
      suffix.entries.map((entry) => (entry as { customType?: string }).customType),
      ["portlog.cursor.first.v1", "portlog.cursor.second.v1"],
    );
    assert.equal(
      suffix.cursor.nextEntryIndex,
      initial.cursor.nextEntryIndex + suffix.entries.length,
    );
    const empty = await observer.resync(suffix.cursor);
    assert.deepEqual(empty.entries, []);
    assert.deepEqual(empty.cursor, suffix.cursor);

    await assert.rejects(
      observer.resync({ nextEntryIndex: -1 }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    await assert.rejects(
      observer.resync({ nextEntryIndex: suffix.cursor.nextEntryIndex + 1 }),
      (error: unknown) => error instanceof PortLogSessionError,
    );
    await coordinator.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
