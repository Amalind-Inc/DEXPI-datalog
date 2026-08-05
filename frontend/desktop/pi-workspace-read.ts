import { constants } from "node:fs";
import { open, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

import type { AgentTool } from "@earendil-works/pi-agent-core";
import { Type } from "typebox";

const MAX_READ_BYTES = 12_000;

export function createPortLogWorkspaceReadTool(options: {
  workspaceRoot: string;
  signal: AbortSignal;
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
      const authorizedPath = await authorizePath(options.workspaceRoot, requestedPath);
      const result = await readBoundedUtf8(authorizedPath, options.signal, signal);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              source: "Pi workspace read",
              authority: "ordinary",
              limitations: ["workspace context only", "not PortLog evidence", "bounded output"],
              path: relative(await realpath(options.workspaceRoot), authorizedPath),
              content: result.text,
              truncated: result.truncated,
            }),
          },
        ],
        details: {
          source: "Pi workspace read",
          authority: "ordinary",
          path: relative(await realpath(options.workspaceRoot), authorizedPath),
          truncated: result.truncated,
        },
      };
    },
  };
}

async function authorizePath(workspaceRoot: string, requestedPath: string): Promise<string> {
  const root = await realpath(workspaceRoot);
  const lexicalTarget = resolve(root, requestedPath);
  if (!isWithin(root, lexicalTarget))
    throw new Error("Read blocked: path escapes the authorized workspace.");
  const target = await realpath(lexicalTarget).catch((error) => {
    throw new Error(
      `Read failed for ${requestedPath}: ${error instanceof Error ? error.message : String(error)}`,
    );
  });
  if (!isWithin(root, target))
    throw new Error("Read blocked: resolved target escapes the authorized workspace.");
  const relativePath = relative(root, target);
  if (isProtectedPath(relativePath))
    throw new Error("Read blocked: credential-like and protected paths are not available.");
  return target;
}

async function readBoundedUtf8(
  path: string,
  sessionSignal: AbortSignal,
  toolSignal?: AbortSignal,
): Promise<{ text: string; truncated: boolean }> {
  if (sessionSignal.aborted || toolSignal?.aborted) throw abortError();
  const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const buffer = Buffer.alloc(MAX_READ_BYTES + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
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
  if (isProtectedPath(path))
    throw new Error("Read blocked: credential-like and protected paths are not available.");
  return path;
}

function isWithin(root: string, candidate: string): boolean {
  const suffix = relative(root, candidate);
  return (
    suffix === "" ||
    (suffix !== ".." &&
      !suffix.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) &&
      !isAbsolute(suffix))
  );
}

function isProtectedPath(path: string): boolean {
  return /(^|[\\/])(?:\.env(?:\..*)?|\.git|\.ssh|credentials?|secrets?|id_rsa|.*\.(?:pem|key))(?:[\\/]|$)/i.test(
    path,
  );
}

function abortError(): DOMException {
  return new DOMException("Inspection cancelled", "AbortError");
}
