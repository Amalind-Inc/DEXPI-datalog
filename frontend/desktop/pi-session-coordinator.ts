import { createRequire } from "node:module";
import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, realpath, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { NodeExecutionEnv } from "@earendil-works/pi-agent-core/node";
import { createPortLogPiAgent, type GovernedPiReviewTurnOptions } from "./pi-turn-adapter.ts";
import { createPortLogCapabilityRegistry } from "./portlog-capability-registry.ts";

type PiSessionMetadata = {
  id: string;
  createdAt: string;
  cwd: string;
  path: string;
  metadata?: Record<string, unknown>;
};

type PiSession = {
  getMetadata(): Promise<PiSessionMetadata>;
  appendMessage(message: AgentMessage): Promise<string>;
  appendCustomEntry(customType: string, data?: unknown): Promise<string>;
  getEntries(): Promise<unknown[]>;
};

type PiSessionRepo = {
  create(options: {
    id: string;
    cwd: string;
    metadata?: Record<string, unknown>;
  }): Promise<PiSession>;
  open(metadata: PiSessionMetadata): Promise<PiSession>;
  list(options?: { cwd?: string }): Promise<PiSessionMetadata[]>;
};

type PiSessionInternals = {
  JsonlSessionRepo: new (options: { fs: NodeExecutionEnv; sessionsRoot: string }) => PiSessionRepo;
};

const PI_AGENT_CORE_VERSION = "0.80.6";
const PORTLOG_SESSION_METADATA_VERSION = 1;
const require = createRequire(import.meta.url);
let internalsPromise: Promise<PiSessionInternals> | undefined;

export interface PortLogSessionIdentity {
  readonly workspaceRoot: string;
  readonly projectId: string;
  readonly sourceDigest: string;
  readonly policy: {
    readonly id: string;
    readonly version: string;
    readonly digest: string;
  };
  readonly toolProfile: {
    readonly id: string;
    readonly version: string;
    readonly digest: string;
  };
}

export interface PortLogPiSessionOptions {
  readonly sessionRoot: string;
  readonly sessionId: string;
  readonly identity: PortLogSessionIdentity;
}
export type PortLogPiTurnOptions = Omit<
  GovernedPiReviewTurnOptions,
  "workspaceRoot" | "initialMessages" | "sessionId" | "capabilityRegistry"
> & {
  onEvent?: (event: unknown) => void;
};

export interface PortLogPiTurn {
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): Promise<void>;
}

export type PortLogSessionErrorCode =
  | "incompatible_runtime"
  | "identity_mismatch"
  | "not_found"
  | "session_exists"
  | "writer_conflict"
  | "writer_lost";

export class PortLogSessionError extends Error {
  readonly code: PortLogSessionErrorCode;

  constructor(code: PortLogSessionErrorCode, message: string) {
    super(message);
    this.name = "PortLogSessionError";
    this.code = code;
  }
}

type WriterFence = {
  readonly lockPath: string;
  readonly token: string;
  readonly epoch: number;
};

export class PortLogPiSessionCoordinator {
  private readonly session: PiSession;
  private readonly metadata: PiSessionMetadata;
  private readonly identityValue: PortLogSessionIdentity;
  private readonly fence: WriterFence;

  private constructor(
    session: PiSession,
    metadata: PiSessionMetadata,
    identityValue: PortLogSessionIdentity,
    fence: WriterFence,
  ) {
    this.session = session;
    this.metadata = metadata;
    this.identityValue = identityValue;
    this.fence = fence;
  }
  static async create(options: PortLogPiSessionOptions): Promise<PortLogPiSessionCoordinator> {
    const identity = await canonicalizeIdentity(options.identity);
    const repo = await createRepo(identity.workspaceRoot, options.sessionRoot);
    const fence = await acquireWriterFence(options.sessionRoot, options.sessionId);
    try {
      const existing = (await repo.list({ cwd: identity.workspaceRoot })).find(
        (candidate) => candidate.id === options.sessionId,
      );
      if (existing) {
        throw new PortLogSessionError(
          "session_exists",
          `Pi session ${options.sessionId} already exists; reopen it instead of creating a second transcript.`,
        );
      }
      const session = await repo.create({
        id: options.sessionId,
        cwd: identity.workspaceRoot,
        metadata: {
          portlog: {
            schemaVersion: PORTLOG_SESSION_METADATA_VERSION,
            identity,
          },
        },
      });
      const metadata = await session.getMetadata();
      return new PortLogPiSessionCoordinator(session, metadata, identity, fence);
    } catch (error) {
      await releaseWriterFence(fence);
      throw error;
    }
  }

  static async open(options: PortLogPiSessionOptions): Promise<PortLogPiSessionCoordinator> {
    const identity = await canonicalizeIdentity(options.identity);
    const repo = await createRepo(identity.workspaceRoot, options.sessionRoot);
    const metadata = (await repo.list({ cwd: identity.workspaceRoot })).find(
      (candidate) => candidate.id === options.sessionId,
    );
    if (!metadata) {
      throw new PortLogSessionError(
        "not_found",
        `Pi session ${options.sessionId} was not found for workspace ${identity.workspaceRoot}.`,
      );
    }
    validatePersistedIdentity(metadata, identity);
    const fence = await acquireWriterFence(options.sessionRoot, options.sessionId);
    try {
      const session = await repo.open(metadata);
      return new PortLogPiSessionCoordinator(session, metadata, identity, fence);
    } catch (error) {
      await releaseWriterFence(fence);
      throw error;
    }
  }

  get sessionId(): string {
    return this.metadata.id;
  }

  get sessionPath(): string {
    return this.metadata.path;
  }

  get identity(): PortLogSessionIdentity {
    return this.identityValue;
  }

  async appendMessage(message: AgentMessage): Promise<string> {
    await assertWriterFence(this.fence);
    return this.session.appendMessage(message);
  }

  async appendCustomEntry(customType: string, data?: unknown): Promise<string> {
    await assertWriterFence(this.fence);
    return this.session.appendCustomEntry(customType, data);
  }
  async getEntries(): Promise<unknown[]> {
    await assertWriterFence(this.fence);
    return this.session.getEntries();
  }

  async getContextMessages(): Promise<AgentMessage[]> {
    const entries = await this.getEntries();
    return entries.filter(isMessageEntry).map((entry) => entry.message);
  }

  async appendMessages(messages: readonly AgentMessage[]): Promise<void> {
    for (const message of messages) await this.appendMessage(message);
  }
  async createPiTurn(options: PortLogPiTurnOptions): Promise<PortLogPiTurn> {
    await assertWriterFence(this.fence);
    const initialMessages = await this.getContextMessages();
    const { onEvent, ...agentOptions } = options;
    const capabilityRegistry = options.getRuleCheck
      ? createPortLogCapabilityRegistry({
          getRuleCheck: options.getRuleCheck,
        })
      : undefined;
    const review = await createPortLogPiAgent({
      ...agentOptions,
      capabilityRegistry,
      workspaceRoot: this.identityValue.workspaceRoot,
      initialMessages,
      sessionId: this.sessionId,
    });
    let persistedMessageCount = initialMessages.length;
    let persistence = Promise.resolve();
    const persistMessages = (messages: readonly AgentMessage[]): Promise<void> => {
      persistence = persistence.then(async () => {
        if (messages.length < persistedMessageCount)
          throw new Error("Pi transcript moved backwards; refusing to append duplicate history.");
        await this.appendMessages(messages.slice(persistedMessageCount));
        persistedMessageCount = messages.length;
      });
      return persistence;
    };
    const unsubscribe = review.subscribe(async (event) => {
      if (event.type === "agent_end") await persistMessages(event.messages);
      onEvent?.(event);
    });
    return {
      prompt: async (text) => {
        await assertWriterFence(this.fence);
        try {
          await review.prompt(text);
          await persistence;
        } catch (error) {
          await persistMessages(review.agent.state.messages);
          throw error;
        }
      },
      abort: review.abort,
      dispose: async () => {
        await persistMessages(review.agent.state.messages);
        unsubscribe();
        await review.dispose();
      },
    };
  }

  async close(): Promise<void> {
    await releaseWriterFence(this.fence);
  }
}

async function createRepo(workspaceRoot: string, sessionRoot: string): Promise<PiSessionRepo> {
  const { JsonlSessionRepo } = await loadPiSessionInternals();
  return new JsonlSessionRepo({
    fs: new NodeExecutionEnv({ cwd: workspaceRoot }),
    sessionsRoot: sessionRoot,
  });
}

async function loadPiSessionInternals(): Promise<PiSessionInternals> {
  internalsPromise ??= (async () => {
    let packageJsonPath: string;
    try {
      packageJsonPath = require.resolve("@earendil-works/pi-agent-core/package.json");
    } catch (error) {
      throw new PortLogSessionError(
        "incompatible_runtime",
        `Pi session runtime is unavailable: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    const packageRoot = dirname(packageJsonPath);
    let packageJson: { version?: unknown };
    try {
      packageJson = JSON.parse(await readFile(packageJsonPath, "utf8")) as { version?: unknown };
    } catch (error) {
      throw new PortLogSessionError(
        "incompatible_runtime",
        `Pi session runtime metadata could not be read: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (packageJson.version !== PI_AGENT_CORE_VERSION) {
      throw new PortLogSessionError(
        "incompatible_runtime",
        `Unsupported Pi session runtime version ${String(packageJson.version)}; expected ${PI_AGENT_CORE_VERSION}.`,
      );
    }
    try {
      const modulePath = pathToFileURL(
        join(packageRoot, "dist", "harness", "session", "jsonl-repo.js"),
      ).href;
      const module = (await import(modulePath)) as Partial<PiSessionInternals>;
      if (typeof module.JsonlSessionRepo !== "function")
        throw new Error("JsonlSessionRepo export is missing");
      return { JsonlSessionRepo: module.JsonlSessionRepo } as PiSessionInternals;
    } catch (error) {
      throw new PortLogSessionError(
        "incompatible_runtime",
        `Pi native JSONL session support could not be loaded: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  })();
  return internalsPromise;
}

async function canonicalizeIdentity(
  identity: PortLogSessionIdentity,
): Promise<PortLogSessionIdentity> {
  if (!identity.projectId || !/^sha256:[0-9a-f]{64}$/.test(identity.sourceDigest))
    throw new PortLogSessionError(
      "identity_mismatch",
      "Project identity and a validated sha256 source digest are required.",
    );
  const workspaceRoot = await realpath(identity.workspaceRoot).catch((error) => {
    throw new PortLogSessionError(
      "identity_mismatch",
      `Workspace identity could not be canonicalized: ${error instanceof Error ? error.message : String(error)}`,
    );
  });
  return { ...identity, workspaceRoot };
}

function validatePersistedIdentity(
  metadata: PiSessionMetadata,
  expected: PortLogSessionIdentity,
): void {
  const persisted = isRecord(metadata.metadata?.portlog) ? metadata.metadata.portlog : undefined;
  const persistedIdentity =
    persisted && isRecord(persisted.identity) ? persisted.identity : undefined;
  if (
    !persisted ||
    !persistedIdentity ||
    persisted.schemaVersion !== PORTLOG_SESSION_METADATA_VERSION
  ) {
    throw new PortLogSessionError(
      "identity_mismatch",
      "The Pi session has no compatible PortLog identity metadata; explicit migration is required.",
    );
  }
  const actual = normalizeIdentity(persistedIdentity);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new PortLogSessionError(
      "identity_mismatch",
      "The Pi session workspace, project, source, policy, or tool-profile identity does not match.",
    );
  }
}

function normalizeIdentity(value: Record<string, unknown>): PortLogSessionIdentity {
  const policy = isRecord(value.policy) ? value.policy : {};
  const toolProfile = isRecord(value.toolProfile) ? value.toolProfile : {};
  return {
    workspaceRoot: typeof value.workspaceRoot === "string" ? value.workspaceRoot : "",
    projectId: typeof value.projectId === "string" ? value.projectId : "",
    sourceDigest: typeof value.sourceDigest === "string" ? value.sourceDigest : "",
    policy: {
      id: typeof policy.id === "string" ? policy.id : "",
      version: typeof policy.version === "string" ? policy.version : "",
      digest: typeof policy.digest === "string" ? policy.digest : "",
    },
    toolProfile: {
      id: typeof toolProfile.id === "string" ? toolProfile.id : "",
      version: typeof toolProfile.version === "string" ? toolProfile.version : "",
      digest: typeof toolProfile.digest === "string" ? toolProfile.digest : "",
    },
  };
}

async function acquireWriterFence(sessionRoot: string, sessionId: string): Promise<WriterFence> {
  const lockRoot = join(sessionRoot, ".portlog-writer-fences");
  await mkdir(lockRoot, { recursive: true });
  const lockPath = join(lockRoot, `${sessionId}.lock`);
  const epochPath = join(lockRoot, `${sessionId}.epoch`);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const token = cryptoRandomUuid();
    try {
      const handle = await open(lockPath, "wx", 0o600);
      const previousEpoch = await readEpoch(epochPath);
      const epoch = previousEpoch + 1;
      await writeFile(epochPath, `${epoch}\n`, { mode: 0o600 });
      await handle.writeFile(`${JSON.stringify({ pid: process.pid, token, epoch })}\n`);
      await handle.close();
      return { lockPath, token, epoch };
    } catch (error) {
      if (isAlreadyExists(error) && (await removeDeadWriter(lockPath))) continue;
      throw new PortLogSessionError(
        "writer_conflict",
        `Pi session writer is already owned: ${sessionId}.`,
      );
    }
  }
  throw new PortLogSessionError(
    "writer_conflict",
    `Pi session writer could not be acquired: ${sessionId}.`,
  );
}

async function assertWriterFence(fence: WriterFence): Promise<void> {
  let current: { token?: unknown; epoch?: unknown };
  try {
    current = JSON.parse(await readFile(fence.lockPath, "utf8")) as {
      token?: unknown;
      epoch?: unknown;
    };
  } catch {
    throw new PortLogSessionError(
      "writer_lost",
      "The Pi session writer fence is no longer present.",
    );
  }
  if (current.token !== fence.token || current.epoch !== fence.epoch)
    throw new PortLogSessionError(
      "writer_lost",
      "The Pi session writer fence is owned by another coordinator.",
    );
}

async function releaseWriterFence(fence: WriterFence): Promise<void> {
  try {
    await assertWriterFence(fence);
    await unlink(fence.lockPath);
  } catch (error) {
    if (error instanceof PortLogSessionError && error.code === "writer_lost") return;
    throw error;
  }
}

async function removeDeadWriter(lockPath: string): Promise<boolean> {
  try {
    const lock = JSON.parse(await readFile(lockPath, "utf8")) as { pid?: unknown };
    if (typeof lock.pid !== "number" || processAlive(lock.pid)) return false;
    await unlink(lockPath);
    return true;
  } catch {
    return false;
  }
}

function processAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

function readEpoch(path: string): Promise<number> {
  return readFile(path, "utf8")
    .then((value) => Number.parseInt(value.trim(), 10) || 0)
    .catch(() => 0);
}

function cryptoRandomUuid(): string {
  return randomUUID();
}

function isMessageEntry(value: unknown): value is { type: "message"; message: AgentMessage } {
  return isRecord(value) && value.type === "message" && value.message !== undefined;
}
function isAlreadyExists(error: unknown): boolean {
  return isRecord(error) && error.code === "EEXIST";
}

function isRecord(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
