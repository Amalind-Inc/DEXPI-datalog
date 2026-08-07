import assert from "node:assert/strict";
import { mkdtemp, readFile, symlink, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  createPortLogWorkspaceEditTool,
  createPortLogWorkspaceWriteTool,
  createWorkspaceSnapshotStore,
  recordWorkspaceReadSnapshot,
} from "./pi-workspace-mutation.ts";
import { createPortLogWorkspaceReadTool } from "./pi-workspace-read.ts";

async function withWorkspace(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(join(tmpdir(), "portlog-mutation-"));
  await run(root);
}

function textResult(result: unknown): Record<string, unknown> {
  assert.ok(result && typeof result === "object");
  const content = (result as { content?: unknown }).content;
  assert.ok(Array.isArray(content));
  const textPart = content.find(
    (part) =>
      part &&
      typeof part === "object" &&
      (part as { type?: unknown }).type === "text" &&
      typeof (part as { text?: unknown }).text === "string",
  ) as { text: string } | undefined;
  assert.ok(textPart);
  return JSON.parse(textPart.text) as Record<string, unknown>;
}

test("write creates a revision for a new file", async () => {
  await withWorkspace(async (root) => {
    const snapshots = createWorkspaceSnapshotStore();
    const write = createPortLogWorkspaceWriteTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots,
    });
    const result = textResult(
      await write.execute("1", { path: "notes/hello.txt", content: "hello\n" }),
    );
    assert.equal(result.outcome, "admitted");
    assert.match(String(result.source_revision), /^sha256:[0-9a-f]{64}$/);
    assert.equal(await readFile(join(root, "notes/hello.txt"), "utf8"), "hello\n");
  });
});

test("existing-file edit requires a current snapshot and creates a revision", async () => {
  await withWorkspace(async (root) => {
    const path = join(root, "file.txt");
    await writeFile(path, "alpha\n");
    const snapshots = createWorkspaceSnapshotStore();
    const read = createPortLogWorkspaceReadTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots,
    });
    await read.execute("1", { path: "file.txt" });
    const edit = createPortLogWorkspaceEditTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots,
    });
    const result = textResult(
      await edit.execute("2", {
        path: "file.txt",
        edits: [{ oldText: "alpha", newText: "beta" }],
      }),
    );
    assert.equal(result.outcome, "admitted");
    assert.equal(await readFile(path, "utf8"), "beta\n");
    assert.match(String(result.source_revision), /^sha256:[0-9a-f]{64}$/);
  });
});

test("missing snapshot conflicts without mutation", async () => {
  await withWorkspace(async (root) => {
    const path = join(root, "file.txt");
    await writeFile(path, "alpha\n");
    const edit = createPortLogWorkspaceEditTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots: createWorkspaceSnapshotStore(),
    });
    const result = textResult(
      await edit.execute("1", {
        path: "file.txt",
        edits: [{ oldText: "alpha", newText: "beta" }],
      }),
    );
    assert.equal(result.outcome, "conflict");
    assert.equal(await readFile(path, "utf8"), "alpha\n");
  });
});

test("stale snapshot conflicts without mutation", async () => {
  await withWorkspace(async (root) => {
    const path = join(root, "file.txt");
    await writeFile(path, "alpha\n");
    const snapshots = createWorkspaceSnapshotStore();
    await recordWorkspaceReadSnapshot(snapshots, {
      workspaceRoot: root,
      relativePath: "file.txt",
      content: "alpha\n",
    });
    await writeFile(path, "changed\n");
    const edit = createPortLogWorkspaceEditTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots,
    });
    const result = textResult(
      await edit.execute("1", {
        path: "file.txt",
        edits: [{ oldText: "alpha", newText: "beta" }],
      }),
    );
    assert.equal(result.outcome, "conflict");
    assert.equal(await readFile(path, "utf8"), "changed\n");
  });
});

test("protected and ignored paths are unavailable", async () => {
  await withWorkspace(async (root) => {
    const { mkdir } = await import("node:fs/promises");
    await writeFile(join(root, ".env"), "SECRET=1\n");
    await writeFile(join(root, ".portlogignore"), "ignored/**\n");
    const ignoredDir = join(root, "ignored");
    await mkdir(ignoredDir, { recursive: true });
    await writeFile(join(ignoredDir, "x.txt"), "nope\n");
    const write = createPortLogWorkspaceWriteTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
    });
    const protectedResult = textResult(
      await write.execute("1", { path: ".env", content: "SECRET=2\n" }),
    );
    assert.equal(protectedResult.outcome, "conflict");
    const ignoredResult = textResult(
      await write.execute("2", { path: "ignored/x.txt", content: "changed\n" }),
    );
    assert.equal(ignoredResult.outcome, "conflict");
    assert.equal(await readFile(join(root, ".env"), "utf8"), "SECRET=1\n");
    assert.equal(await readFile(join(ignoredDir, "x.txt"), "utf8"), "nope\n");
  });
});

test("symlink targets are denied", async () => {
  await withWorkspace(async (root) => {
    const real = join(root, "real.txt");
    await writeFile(real, "alpha\n");
    await symlink(real, join(root, "link.txt"));
    const write = createPortLogWorkspaceWriteTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
    });
    const result = textResult(await write.execute("1", { path: "link.txt", content: "beta\n" }));
    assert.equal(result.outcome, "conflict");
    assert.equal(await readFile(real, "utf8"), "alpha\n");
  });
});

test("ambiguous edits do not mutate", async () => {
  await withWorkspace(async (root) => {
    const path = join(root, "file.txt");
    await writeFile(path, "alpha alpha\n");
    const snapshots = createWorkspaceSnapshotStore();
    await recordWorkspaceReadSnapshot(snapshots, {
      workspaceRoot: root,
      relativePath: "file.txt",
      content: "alpha alpha\n",
    });
    const edit = createPortLogWorkspaceEditTool({
      workspaceRoot: root,
      signal: new AbortController().signal,
      snapshots,
    });
    const result = textResult(
      await edit.execute("1", {
        path: "file.txt",
        edits: [{ oldText: "alpha", newText: "beta" }],
      }),
    );
    assert.equal(result.outcome, "conflict");
    assert.equal(await readFile(path, "utf8"), "alpha alpha\n");
  });
});

test("cancelled write returns cancelled", async () => {
  await withWorkspace(async (root) => {
    const controller = new AbortController();
    controller.abort();
    const write = createPortLogWorkspaceWriteTool({
      workspaceRoot: root,
      signal: controller.signal,
    });
    const result = textResult(await write.execute("1", { path: "file.txt", content: "hello\n" }));
    assert.equal(result.outcome, "cancelled");
  });
});
