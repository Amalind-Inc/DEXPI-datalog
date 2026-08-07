import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { isAbsolute } from "node:path";

import type { AgentTool } from "@earendil-works/pi-agent-core";
import { Type } from "typebox";

import {
  recordWorkspaceReadSnapshot,
  type WorkspaceSnapshotStore,
} from "./pi-workspace-mutation.ts";
import {
  assertNoWorkspaceSymlinkComponents,
  loadPortLogWorkspacePathPolicy,
} from "./workspace-path-policy.ts";

const MAX_READ_BYTES = 12_000;

export function createPortLogWorkspaceReadTool(options: {
  workspaceRoot: string;
  signal: AbortSignal;
  snapshots?: WorkspaceSnapshotStore;
}): AgentTool {
  return {
    name: "read",
    label: "Pi workspace read",
    description:
      "Read a bounded UTF-8 file under the authorized workspace. This is ordinary context, not PortLog evidence.",
    parameters: Type.Object({ path: Type.String() }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      if (options.signal.aborted || signal?.aborted) throw abortError();
      const requestedPath = readPath(params);
      if (isAbsolute(requestedPath))
        throw new Error("Read blocked: absolute paths are not allowed.");
      const authorized = await authorizePath(options.workspaceRoot, requestedPath);
      const result = await readBoundedUtf8(authorized.path, options.signal, signal);
      if (!result.truncated && options.snapshots) {
        await recordWorkspaceReadSnapshot(options.snapshots, {
          workspaceRoot: options.workspaceRoot,
          relativePath: authorized.relativePath,
          content: result.text,
        });
      }
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              source: "Pi workspace read",
              authority: "ordinary",
              limitations: ["workspace context only", "not PortLog evidence", "bounded output"],
              path: authorized.relativePath,
              content: result.text,
              truncated: result.truncated,
            }),
          },
        ],
        details: {
          source: "Pi workspace read",
          authority: "ordinary",
          path: authorized.relativePath,
          truncated: result.truncated,
        },
      };
    },
  };
}

async function authorizePath(
  workspaceRoot: string,
  requestedPath: string,
): Promise<{ path: string; relativePath: string }> {
  const identity = await assertNoWorkspaceSymlinkComponents(workspaceRoot, requestedPath);
  const policy = await loadPortLogWorkspacePathPolicy(identity.root);
  if (!policy.evaluate(identity.relativePath, "file").include)
    throw new Error("Read blocked: credential-like, ignored, and protected paths are unavailable.");
  return { path: identity.path, relativePath: identity.relativePath };
}

async function readBoundedUtf8(
  path: string,
  sessionSignal: AbortSignal,
  toolSignal?: AbortSignal,
): Promise<{ text: string; truncated: boolean }> {
  if (sessionSignal.aborted || toolSignal?.aborted) throw abortError();
  const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.nlink !== 1)
      throw new Error("Read blocked: only single-link regular files are available.");
    const buffer = Buffer.alloc(MAX_READ_BYTES + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    const after = await handle.stat();
    if (
      after.dev !== before.dev ||
      after.ino !== before.ino ||
      after.size !== before.size ||
      after.mtimeMs !== before.mtimeMs ||
      after.nlink !== 1
    )
      throw new Error("Read blocked: the file changed while it was read.");
    if (sessionSignal.aborted || toolSignal?.aborted) throw abortError();
    const truncated = bytesRead > MAX_READ_BYTES;
    let end = Math.min(bytesRead, MAX_READ_BYTES);
    while (end > 0 && end < bytesRead && (buffer[end] & 0xc0) === 0x80) end -= 1;
    return { text: buffer.subarray(0, end).toString("utf8"), truncated };
  } finally {
    await handle.close();
  }
}

function readPath(params: unknown): string {
  if (
    params === null ||
    typeof params !== "object" ||
    typeof (params as { path?: unknown }).path !== "string"
  )
    throw new Error("Invalid read arguments.");
  const path = (params as { path: string }).path.trim();
  if (!path) throw new Error("Invalid read path.");
  return path;
}

function abortError(): DOMException {
  return new DOMException("Inspection cancelled", "AbortError");
}
