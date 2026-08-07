import assert from "node:assert/strict";
import { link, mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createPortLogWorkspaceReadTool } from "./pi-workspace-read.ts";

async function executeRead(workspaceRoot: string, path: string) {
  const tool = createPortLogWorkspaceReadTool({
    workspaceRoot,
    signal: new AbortController().signal,
  });
  return tool.execute("read-call", { path }, new AbortController().signal);
}

test("workspace read returns bounded ordinary context from an admitted file", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-workspace-read-"));
  try {
    await writeFile(join(workspaceRoot, "source.txt"), "ordinary source");
    const result = await executeRead(workspaceRoot, "source.txt");
    const content = result.content.find((item) => item.type === "text");
    assert.ok(content?.type === "text");
    const value = JSON.parse(content.text);
    assert.equal(value.authority, "ordinary");
    assert.equal(value.path, "source.txt");
    assert.equal(value.content, "ordinary source");
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("workspace read applies protected paths and PortLog ignore policy consistently", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-workspace-policy-"));
  try {
    await mkdir(join(workspaceRoot, "ignored"));
    await writeFile(join(workspaceRoot, ".env"), "SECRET=1");
    await writeFile(join(workspaceRoot, ".environment"), "SECRET=2");
    await writeFile(join(workspaceRoot, "credential-cache.json"), "SECRET=3");
    await writeFile(join(workspaceRoot, "id_ed25519"), "SECRET=4");
    await writeFile(join(workspaceRoot, ".portlogignore"), "ignored/**\n");
    await writeFile(join(workspaceRoot, "ignored", "private.txt"), "private");

    await assert.rejects(executeRead(workspaceRoot, ".env"), /protected paths are unavailable/i);
    for (const protectedPath of [".environment", "credential-cache.json", "id_ed25519"]) {
      await assert.rejects(
        executeRead(workspaceRoot, protectedPath),
        /protected paths are unavailable/i,
      );
    }
    await assert.rejects(
      executeRead(workspaceRoot, "ignored/private.txt"),
      /ignored, and protected paths are unavailable/i,
    );
    const ignoreResult = await executeRead(workspaceRoot, ".portlogignore");
    assert.match(JSON.stringify(ignoreResult), /ignored\/\*\*/);
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("workspace read rejects symlink components and unsupported ignore negation", async () => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-workspace-symlink-"));
  try {
    await writeFile(join(workspaceRoot, "source.txt"), "ordinary source");
    await symlink("source.txt", join(workspaceRoot, "linked.txt"));
    await assert.rejects(executeRead(workspaceRoot, "linked.txt"), /symbolic link/i);

    await writeFile(join(workspaceRoot, ".portlogignore"), "!source.txt\n");
    await assert.rejects(executeRead(workspaceRoot, "source.txt"), /unsupported syntax/i);
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("workspace read rejects hard-linked files and hard-linked ignore policy", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-workspace-hardlink-"));
  const workspaceRoot = join(root, "workspace");
  try {
    await mkdir(workspaceRoot);
    const outside = join(root, "outside-secret.txt");
    await writeFile(outside, "outside secret");
    await link(outside, join(workspaceRoot, "innocent.txt"));
    await assert.rejects(executeRead(workspaceRoot, "innocent.txt"), /single-link regular files/i);

    await link(outside, join(workspaceRoot, ".portlogignore"));
    await writeFile(join(workspaceRoot, "source.txt"), "ordinary");
    await assert.rejects(
      executeRead(workspaceRoot, "source.txt"),
      /ignore policy must be a single-link regular file/i,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
