import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, rename, rm, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative } from "node:path";

import type { AgentTool } from "@earendil-works/pi-agent-core";
import { Type } from "typebox";

import {
  assertNoWorkspaceSymlinkComponents,
  assertWritableWorkspacePath,
  loadPortLogWorkspacePathPolicy,
  type PortLogWorkspacePathPolicy,
} from "./workspace-path-policy.ts";

const MAX_MUTATION_BYTES = 256 * 1024;
const MAX_EDIT_COUNT = 32;
const MAX_DIFF_CHARS = 4_000;

export type WorkspaceFileSnapshot = {
  readonly relativePath: string;
  readonly digest: string;
  readonly bytes: Buffer;
  readonly size: number;
  readonly mtimeMs: number;
  readonly nlink: number;
  readonly dev: number;
  readonly ino: number;
  readonly mode: number;
};

export type WorkspaceRevisionEvent = {
  readonly path: string;
  readonly sourceRevision: string;
  readonly previousRevision?: string;
  readonly operation: "write" | "edit";
};

export type WorkspaceSnapshotStore = {
  get(relativePath: string): WorkspaceFileSnapshot | undefined;
  set(snapshot: WorkspaceFileSnapshot): void;
  delete(relativePath: string): void;
};

export function createWorkspaceSnapshotStore(): WorkspaceSnapshotStore {
  const entries = new Map<string, WorkspaceFileSnapshot>();
  return {
    get(relativePath) {
      return entries.get(relativePath);
    },
    set(snapshot) {
      entries.set(snapshot.relativePath, snapshot);
    },
    delete(relativePath) {
      entries.delete(relativePath);
    },
  };
}

export function digestWorkspaceBytes(bytes: Buffer): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

export async function recordWorkspaceReadSnapshot(
  store: WorkspaceSnapshotStore,
  options: {
    workspaceRoot: string;
    relativePath: string;
    content: string;
  },
): Promise<WorkspaceFileSnapshot | undefined> {
  const identity = await assertNoWorkspaceSymlinkComponents(
    options.workspaceRoot,
    options.relativePath,
  );
  const handle = await open(identity.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const status = await handle.stat();
    if (!status.isFile() || status.nlink !== 1) return undefined;
    const bytes = Buffer.from(options.content, "utf8");
    if (bytes.byteLength !== status.size) return undefined;
    const snapshot: WorkspaceFileSnapshot = {
      relativePath: identity.relativePath,
      digest: digestWorkspaceBytes(bytes),
      bytes,
      size: Number(status.size),
      mtimeMs: status.mtimeMs,
      nlink: Number(status.nlink),
      dev: Number(status.dev),
      ino: Number(status.ino),
      mode: Number(status.mode),
    };
    store.set(snapshot);
    return snapshot;
  } finally {
    await handle.close();
  }
}

export function createPortLogWorkspaceWriteTool(options: {
  workspaceRoot: string;
  signal: AbortSignal;
  snapshots?: WorkspaceSnapshotStore;
  onRevision?: (event: WorkspaceRevisionEvent) => void | Promise<void>;
}): AgentTool {
  const snapshots = options.snapshots ?? createWorkspaceSnapshotStore();
  return {
    name: "write",
    label: "Pi workspace write",
    description:
      "Write UTF-8 content to a workspace-relative path under PortLog policy. Existing files require a current read snapshot. Successful writes create a new ordinary source revision.",
    parameters: Type.Object(
      {
        path: Type.String({ minLength: 1, maxLength: 1_000 }),
        content: Type.String({ maxLength: MAX_MUTATION_BYTES }),
      },
      { additionalProperties: false },
    ),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      if (options.signal.aborted || signal?.aborted)
        return mutationResponse("cancelled", "Write was cancelled.");
      const request = parseWriteParams(params);
      if (!request)
        return mutationResponse("rejected", "Write request failed parameter validation.");
      try {
        const result = await mutateWorkspaceFile({
          workspaceRoot: options.workspaceRoot,
          relativePath: request.path,
          snapshots,
          sessionSignal: options.signal,
          toolSignal: signal,
          operation: "write",
          apply: () => request.content,
        });
        if (result.outcome === "admitted") {
          await options.onRevision?.({
            path: result.path,
            sourceRevision: result.source_revision!,
            previousRevision: result.previous_revision,
            operation: "write",
          });
        }
        return mutationResponse(result.outcome, result.diagnostic, result);
      } catch (error) {
        if (error instanceof MutationConflictError)
          return mutationResponse("conflict", error.message, {
            path: request.path,
            authority: "ordinary",
          });
        if (isAbortError(error) || options.signal.aborted || signal?.aborted)
          return mutationResponse("cancelled", "Write was cancelled.");
        return mutationResponse(
          "failed",
          error instanceof Error ? error.message : "Write failed before a result was available.",
        );
      }
    },
  };
}

export function createPortLogWorkspaceEditTool(options: {
  workspaceRoot: string;
  signal: AbortSignal;
  snapshots?: WorkspaceSnapshotStore;
  onRevision?: (event: WorkspaceRevisionEvent) => void | Promise<void>;
}): AgentTool {
  const snapshots = options.snapshots ?? createWorkspaceSnapshotStore();
  return {
    name: "edit",
    label: "Pi workspace edit",
    description:
      "Apply unique non-overlapping text replacements to a workspace file under PortLog policy. Existing files require a current read snapshot. Conflicts produce no mutation.",
    parameters: Type.Object(
      {
        path: Type.String({ minLength: 1, maxLength: 1_000 }),
        edits: Type.Array(
          Type.Object(
            {
              oldText: Type.String({ minLength: 1, maxLength: MAX_MUTATION_BYTES }),
              newText: Type.String({ maxLength: MAX_MUTATION_BYTES }),
            },
            { additionalProperties: false },
          ),
          { minItems: 1, maxItems: MAX_EDIT_COUNT },
        ),
      },
      { additionalProperties: false },
    ),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      if (options.signal.aborted || signal?.aborted)
        return mutationResponse("cancelled", "Edit was cancelled.");
      const request = parseEditParams(params);
      if (!request)
        return mutationResponse("rejected", "Edit request failed parameter validation.");
      try {
        const result = await mutateWorkspaceFile({
          workspaceRoot: options.workspaceRoot,
          relativePath: request.path,
          snapshots,
          sessionSignal: options.signal,
          toolSignal: signal,
          operation: "edit",
          requireExisting: true,
          apply: (current) => applyUniqueEdits(current, request.edits),
        });
        if (result.outcome === "admitted") {
          await options.onRevision?.({
            path: result.path,
            sourceRevision: result.source_revision!,
            previousRevision: result.previous_revision,
            operation: "edit",
          });
        }
        return mutationResponse(result.outcome, result.diagnostic, result);
      } catch (error) {
        if (error instanceof MutationConflictError)
          return mutationResponse("conflict", error.message, {
            path: request.path,
            authority: "ordinary",
          });
        if (isAbortError(error) || options.signal.aborted || signal?.aborted)
          return mutationResponse("cancelled", "Edit was cancelled.");
        return mutationResponse(
          "failed",
          error instanceof Error ? error.message : "Edit failed before a result was available.",
        );
      }
    },
  };
}

type MutationOutcome = "admitted" | "rejected" | "conflict" | "failed" | "cancelled";

type MutationResult = {
  outcome: MutationOutcome;
  diagnostic: string;
  path: string;
  authority: "ordinary";
  source_revision?: string;
  previous_revision?: string;
  diff?: string;
  truncated?: boolean;
};

class MutationConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MutationConflictError";
  }
}

async function mutateWorkspaceFile(options: {
  workspaceRoot: string;
  relativePath: string;
  snapshots: WorkspaceSnapshotStore;
  sessionSignal: AbortSignal;
  toolSignal?: AbortSignal;
  operation: "write" | "edit";
  requireExisting?: boolean;
  apply: (current: string) => string;
}): Promise<MutationResult> {
  assertNotAborted(options.sessionSignal, options.toolSignal);
  if (isAbsolute(options.relativePath))
    throw new MutationConflictError("Absolute paths are not allowed.");

  let identity: Awaited<ReturnType<typeof assertNoWorkspaceSymlinkComponents>>;
  try {
    identity = await assertWritableWorkspacePath(options.workspaceRoot, options.relativePath);
  } catch (error) {
    throw new MutationConflictError(
      error instanceof Error ? error.message : "Workspace path is not authorized for mutation.",
    );
  }
  const policy = await loadPortLogWorkspacePathPolicy(identity.root);
  denyProtectedPath(policy, identity.relativePath);

  let existing:
    | {
        handle: Awaited<ReturnType<typeof open>>;
        status: Awaited<ReturnType<Awaited<ReturnType<typeof open>>["stat"]>>;
        bytes: Buffer;
        digest: string;
      }
    | undefined;
  try {
    existing = await openExistingFile(identity.path);
  } catch (error) {
    if (!(isNodeError(error) && error.code === "ENOENT")) throw error;
    if (options.requireExisting)
      throw new MutationConflictError("Edit requires an existing workspace file.");
  }

  try {
    assertNotAborted(options.sessionSignal, options.toolSignal);
    const snapshot = options.snapshots.get(identity.relativePath);
    if (existing) {
      if (!snapshot)
        throw new MutationConflictError(
          "Existing-file mutations require a current read snapshot for this path.",
        );
      if (!snapshotMatches(snapshot, existing.status, existing.digest))
        throw new MutationConflictError(
          "The file changed since the last authorized snapshot; no mutation was applied.",
        );
    } else if (snapshot) {
      throw new MutationConflictError(
        "A snapshot exists for a missing path; no mutation was applied.",
      );
    }

    const currentText = existing ? existing.bytes.toString("utf8") : "";
    const nextText = options.apply(currentText);
    const nextBytes = Buffer.from(nextText, "utf8");
    if (nextBytes.byteLength > MAX_MUTATION_BYTES)
      throw new MutationConflictError("Mutation exceeds the bounded workspace file size.");

    await ensureParentDirectory(identity.root, identity.path);
    assertNotAborted(options.sessionSignal, options.toolSignal);
    await writeAtomically(
      identity.path,
      nextBytes,
      existing ? Number(existing.status.mode) : undefined,
    );

    const after = await open(identity.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    try {
      const status = await after.stat();
      if (!status.isFile() || status.nlink !== 1)
        throw new Error("Mutation verification failed: result is not a single-link regular file.");
      if (status.size !== nextBytes.byteLength)
        throw new Error("Mutation verification failed: size mismatch after write.");
      const sourceRevision = digestWorkspaceBytes(nextBytes);
      options.snapshots.set({
        relativePath: identity.relativePath,
        digest: sourceRevision,
        bytes: nextBytes,
        size: Number(status.size),
        mtimeMs: status.mtimeMs,
        nlink: Number(status.nlink),
        dev: Number(status.dev),
        ino: Number(status.ino),
        mode: Number(status.mode),
      });
      const diff = boundDiff(currentText, nextText);
      return {
        outcome: "admitted",
        diagnostic:
          options.operation === "write"
            ? "Workspace write created a new ordinary source revision."
            : "Workspace edit created a new ordinary source revision.",
        path: identity.relativePath,
        authority: "ordinary",
        source_revision: sourceRevision,
        previous_revision: existing?.digest,
        diff: diff.value,
        truncated: diff.truncated,
      };
    } finally {
      await after.close();
    }
  } finally {
    await existing?.handle.close();
  }
}

function applyUniqueEdits(
  content: string,
  edits: Array<{ oldText: string; newText: string }>,
): string {
  type Replacement = { start: number; end: number; newText: string };
  const replacements: Replacement[] = [];
  for (const edit of edits) {
    const first = content.indexOf(edit.oldText);
    if (first === -1)
      throw new MutationConflictError(
        "Edit oldText was not found in the current snapshot; no mutation was applied.",
      );
    const second = content.indexOf(edit.oldText, first + 1);
    if (second !== -1)
      throw new MutationConflictError(
        "Edit oldText matched more than once; no mutation was applied.",
      );
    replacements.push({
      start: first,
      end: first + edit.oldText.length,
      newText: edit.newText,
    });
  }
  replacements.sort((left, right) => left.start - right.start);
  for (let index = 1; index < replacements.length; index += 1) {
    const previous = replacements[index - 1]!;
    const current = replacements[index]!;
    if (current.start < previous.end)
      throw new MutationConflictError("Edit ranges overlap; no mutation was applied.");
  }
  let cursor = 0;
  let result = "";
  for (const replacement of replacements) {
    result += content.slice(cursor, replacement.start);
    result += replacement.newText;
    cursor = replacement.end;
  }
  result += content.slice(cursor);
  return result;
}

async function openExistingFile(path: string): Promise<{
  handle: Awaited<ReturnType<typeof open>>;
  status: Awaited<ReturnType<Awaited<ReturnType<typeof open>>["stat"]>>;
  bytes: Buffer;
  digest: string;
}> {
  const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.nlink !== 1)
      throw new MutationConflictError("Only single-link regular files may be mutated.");
    if (before.size > MAX_MUTATION_BYTES)
      throw new MutationConflictError("Existing file exceeds the bounded workspace file size.");
    const bytes = await handle.readFile();
    const after = await handle.stat();
    if (
      bytes.byteLength !== before.size ||
      after.size !== before.size ||
      after.dev !== before.dev ||
      after.ino !== before.ino ||
      after.mtimeMs !== before.mtimeMs ||
      after.nlink !== 1
    )
      throw new MutationConflictError(
        "The file changed while it was inspected; no mutation was applied.",
      );
    return {
      handle,
      status: after,
      bytes,
      digest: digestWorkspaceBytes(bytes),
    };
  } catch (error) {
    await handle.close();
    throw error;
  }
}

function snapshotMatches(
  snapshot: WorkspaceFileSnapshot,
  status: {
    size: number | bigint;
    mtimeMs: number | bigint;
    nlink: number | bigint;
    dev: number | bigint;
    ino: number | bigint;
  },
  digest: string,
): boolean {
  return (
    snapshot.digest === digest &&
    Number(status.size) === snapshot.size &&
    Number(status.mtimeMs) === snapshot.mtimeMs &&
    Number(status.nlink) === snapshot.nlink &&
    Number(status.dev) === snapshot.dev &&
    Number(status.ino) === snapshot.ino
  );
}

async function ensureParentDirectory(workspaceRoot: string, filePath: string): Promise<void> {
  const parent = dirname(filePath);
  if (parent === workspaceRoot || parent === ".") return;
  const relativeParent = relative(workspaceRoot, parent).split("\\").join("/");
  if (!relativeParent || relativeParent.startsWith("..") || isAbsolute(relativeParent))
    throw new MutationConflictError("Parent directory escapes the authorized workspace.");
  let current = workspaceRoot;
  for (const segment of relativeParent.split("/")) {
    current = join(current, segment);
    try {
      const handle = await open(current, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
      try {
        const status = await handle.stat();
        if (status.isSymbolicLink() || !status.isDirectory())
          throw new MutationConflictError("Parent path is not a safe workspace directory.");
      } finally {
        await handle.close();
      }
    } catch (error) {
      if (!(isNodeError(error) && error.code === "ENOENT")) {
        throw error instanceof MutationConflictError
          ? error
          : new MutationConflictError(
              error instanceof Error ? error.message : "Parent directory is not authorized.",
            );
      }
      await mkdir(current, { recursive: false });
    }
  }
}

async function writeAtomically(
  targetPath: string,
  bytes: Buffer,
  mode: number | undefined,
): Promise<void> {
  const temporaryPath = join(dirname(targetPath), `.portlog-write-${randomUUID()}.tmp`);
  try {
    await writeFile(temporaryPath, bytes, mode === undefined ? undefined : { mode });
    await rename(temporaryPath, targetPath);
  } catch (error) {
    await rm(temporaryPath, { force: true });
    throw error;
  }
}

function denyProtectedPath(policy: PortLogWorkspacePathPolicy, relativePath: string): void {
  const decision = policy.evaluate(relativePath, "file");
  if (!decision.include)
    throw new MutationConflictError(
      "Credential-like, ignored, and protected paths are unavailable for mutation.",
    );
}

function parseWriteParams(value: unknown): { path: string; content: string } | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => key !== "path" && key !== "content")) return undefined;
  if (typeof record.path !== "string" || typeof record.content !== "string") return undefined;
  const path = record.path.trim();
  if (!path || Buffer.byteLength(record.content, "utf8") > MAX_MUTATION_BYTES) return undefined;
  return { path, content: record.content };
}

function parseEditParams(
  value: unknown,
): { path: string; edits: Array<{ oldText: string; newText: string }> } | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => key !== "path" && key !== "edits")) return undefined;
  if (typeof record.path !== "string" || !Array.isArray(record.edits) || record.edits.length === 0)
    return undefined;
  if (record.edits.length > MAX_EDIT_COUNT) return undefined;
  const path = record.path.trim();
  if (!path) return undefined;
  const edits: Array<{ oldText: string; newText: string }> = [];
  for (const item of record.edits) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return undefined;
    const edit = item as Record<string, unknown>;
    if (Object.keys(edit).some((key) => key !== "oldText" && key !== "newText")) return undefined;
    if (typeof edit.oldText !== "string" || typeof edit.newText !== "string") return undefined;
    if (!edit.oldText || Buffer.byteLength(edit.oldText, "utf8") > MAX_MUTATION_BYTES)
      return undefined;
    if (Buffer.byteLength(edit.newText, "utf8") > MAX_MUTATION_BYTES) return undefined;
    edits.push({ oldText: edit.oldText, newText: edit.newText });
  }
  return { path, edits };
}

function mutationResponse(
  outcome: MutationOutcome,
  diagnostic: string,
  result?: Partial<MutationResult>,
): {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, never>;
} {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          schemaVersion: 1,
          outcome,
          authority: "ordinary",
          diagnostic: diagnostic.slice(0, 240),
          path: result?.path,
          source_revision: result?.source_revision,
          previous_revision: result?.previous_revision,
          diff: result?.diff,
          truncated: result?.truncated === true,
          limitations: [
            "ordinary workspace mutation",
            "not PortLog evidence",
            "requires current snapshot for existing files",
          ],
        }),
      },
    ],
    details: {},
  };
}

function boundDiff(before: string, after: string): { value: string; truncated: boolean } {
  const value = [
    "--- previous",
    before.split("\n").slice(0, 80).join("\n"),
    "+++ next",
    after.split("\n").slice(0, 80).join("\n"),
  ].join("\n");
  return value.length > MAX_DIFF_CHARS
    ? { value: value.slice(0, MAX_DIFF_CHARS), truncated: true }
    : { value, truncated: false };
}

function assertNotAborted(...signals: Array<AbortSignal | undefined>): void {
  if (signals.some((signal) => signal?.aborted)) throw abortError();
}

function abortError(): DOMException {
  return new DOMException("Inspection cancelled", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
