import { createRequire } from "node:module";
import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { chmod, mkdir, open, readFile, realpath, unlink, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
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
  readonly attachmentRoot?: string;
}

export type PortLogSessionOptions = PortLogPiSessionOptions;

export type PortLogClientRole = "observer" | "writer";
export type PortLogCanonicalCursor = { readonly nextEntryIndex: number };

export type PortLogObserverCredentials = {
  readonly sessionId: string;
  readonly clientId: string;
  readonly role: "observer";
  readonly canApprove: boolean;
  readonly token: string;
};

export type PortLogWriterCredentials = {
  readonly sessionId: string;
  readonly clientId: string;
  readonly role: "writer";
  readonly canApprove: false;
  readonly token: string;
};

export type PortLogClientCredentials =
  | PortLogObserverCredentials
  | PortLogWriterCredentials;

export type PortLogObserverAttachment = {
  readonly clientId: string;
  readonly role: "observer";
  readonly canApprove: boolean;
  resync(cursor?: PortLogCanonicalCursor): Promise<{
    entries: readonly unknown[];
    cursor: PortLogCanonicalCursor;
  }>;
  submitApproval(input: {
    approvalRequestId: string;
    decision: "approve" | "deny";
  }): Promise<{ entryId: string }>;
  close(): Promise<void>;
};

export type PortLogWriterAttachment = {
  readonly clientId: string;
  readonly role: "writer";
  readonly canApprove: false;
  resync(cursor?: PortLogCanonicalCursor): Promise<{
    entries: readonly unknown[];
    cursor: PortLogCanonicalCursor;
  }>;
  enqueuePrompt(text: string): Promise<string>;
  close(): Promise<void>;
};

export type PortLogPiClientAttachment =
  | PortLogObserverAttachment
  | PortLogWriterAttachment;

export type PortLogApprovalRequestOptions = {
  readonly action: string;
  readonly target: string;
  readonly policyDigest: string;
  readonly expiresAt: number | string;
  readonly approverClientId: string;
};

export type PortLogApprovalRequest = {
  readonly approvalRequestId: string;
  readonly bindingDigest: string;
};
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
  | "writer_lost"
  | "attachment_unavailable"
  | "attachment_invalid"
  | "attachment_revoked"
  | "invalid_cursor"
  | "queue_invalid"
  | "approval_invalid";

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
  private readonly attachmentRoot?: string;
  private mutationTail: Promise<void> = Promise.resolve();

  private constructor(
    session: PiSession,
    metadata: PiSessionMetadata,
    identityValue: PortLogSessionIdentity,
    fence: WriterFence,
    attachmentRoot?: string,
  ) {
    this.session = session;
    this.metadata = metadata;
    this.identityValue = identityValue;
    this.fence = fence;
    this.attachmentRoot = attachmentRoot;
  }
  static async create(options: PortLogPiSessionOptions): Promise<PortLogPiSessionCoordinator> {
    const identity = await canonicalizeIdentity(options.identity);
    const attachmentRoot = await canonicalizeAttachmentRoot(
      options.attachmentRoot,
      identity.workspaceRoot,
    );
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
      return new PortLogPiSessionCoordinator(session, metadata, identity, fence, attachmentRoot);
    } catch (error) {
      await releaseWriterFence(fence);
      throw error;
    }
  }

  static async open(options: PortLogPiSessionOptions): Promise<PortLogPiSessionCoordinator> {
    const identity = await canonicalizeIdentity(options.identity);
    const attachmentRoot = await canonicalizeAttachmentRoot(
      options.attachmentRoot,
      identity.workspaceRoot,
    );
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
      return new PortLogPiSessionCoordinator(session, metadata, identity, fence, attachmentRoot);
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
  async issueClientCredentials(
    options: { clientId: string; role: "observer"; canApprove?: boolean },
  ): Promise<PortLogObserverCredentials>;
  async issueClientCredentials(
    options: { clientId: string; role: "writer"; canApprove?: false },
  ): Promise<PortLogWriterCredentials>;
  async issueClientCredentials(options: {
    clientId: string;
    role: PortLogClientRole;
    canApprove?: boolean;
  }): Promise<PortLogClientCredentials> {
    await assertWriterFence(this.fence);
    const attachmentRoot = this.requireAttachmentRoot();
    assertBoundedText(options.clientId, "client ID");
    const canApprove = options.role === "observer" && options.canApprove === true;
    const token = randomBytes(32).toString("base64url");
    const credentials = {
      sessionId: this.sessionId,
      clientId: options.clientId,
      role: options.role,
      canApprove,
      token,
    } as PortLogClientCredentials;
    const path = credentialPath(attachmentRoot, this.sessionId, options.clientId);
    const handle = await open(path, "wx", 0o600).catch((error) => {
      if (isAlreadyExists(error))
        throw new PortLogSessionError(
          "attachment_invalid",
          `Client credentials already exist: ${options.clientId}.`,
        );
      throw error;
    });
    try {
      await handle.writeFile(
        `${JSON.stringify({
          sessionId: this.sessionId,
          clientId: options.clientId,
          role: options.role,
          canApprove,
          tokenDigest: digestToken(token),
        })}\n`,
      );
    } finally {
      await handle.close();
    }
    return credentials;
  }

  async attachClient(credentials: PortLogObserverCredentials): Promise<PortLogObserverAttachment>;
  async attachClient(credentials: PortLogWriterCredentials): Promise<PortLogWriterAttachment>;
  async attachClient(credentials: PortLogClientCredentials): Promise<PortLogPiClientAttachment> {
    await this.validateClientCredentials(credentials);
    let closed = false;
    const authenticate = async () => {
      if (closed)
        throw new PortLogSessionError("attachment_invalid", "The client attachment is closed.");
      await this.validateClientCredentials(credentials);
    };
    const base = {
      clientId: credentials.clientId,
      role: credentials.role,
      canApprove: credentials.canApprove,
      resync: async (cursor?: PortLogCanonicalCursor) => {
        await authenticate();
        return this.resyncEntries(cursor);
      },
      close: async () => {
        closed = true;
      },
    };
    if (credentials.role === "writer") {
      return {
        ...base,
        role: "writer",
        canApprove: false,
        enqueuePrompt: async (text: string) => {
          await authenticate();
          return this.enqueueQueuedPrompt(credentials, text);
        },
      };
    }
    return {
      ...base,
      role: "observer",
      submitApproval: async (input) => {
        await authenticate();
        if (!credentials.canApprove)
          throw new PortLogSessionError(
            "approval_invalid",
            "This observer is not authorized to approve actions.",
          );
        return this.decideApproval(credentials, input.approvalRequestId, input.decision);
      },
    };
  }

  async revokeClient(clientId: string): Promise<void> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      assertBoundedText(clientId, "client ID");
      const path = credentialPath(this.requireAttachmentRoot(), this.sessionId, clientId);
      try {
        await unlink(path);
      } catch (error) {
        if (!isNotFound(error)) throw error;
      }
    });
  }

  async admitQueuedPrompt(queueId: string, turnId: string): Promise<{ entryId: string }> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      assertBoundedText(queueId, "queue ID");
      assertBoundedText(turnId, "turn ID");
      const state = readQueueState(await this.session.getEntries(), queueId);
      if (!state)
        throw new PortLogSessionError("queue_invalid", `Queued prompt is not pending: ${queueId}.`);
      if (state.status === "admitted")
        throw new PortLogSessionError("queue_invalid", `Queued prompt is not pending: ${queueId}.`);
      if (state.status === "admission_started") {
        if (turnId !== state.turnId)
          throw new PortLogSessionError("queue_invalid", `Queued prompt turn does not match: ${queueId}.`);
        const message = makeQueuedUserMessage(
          state.text,
          state.messageTimestamp,
          state.admissionId,
          state.turnId,
        );
        if (queuedMessageDigest(message) !== state.messageDigest)
          throw new PortLogSessionError("queue_invalid", `Queued prompt admission is corrupt: ${queueId}.`);
        await this.session.appendMessage(message);
        return { entryId: state.entryId };
      }
      if (state.status !== "queued")
        throw new PortLogSessionError("queue_invalid", `Queued prompt admission is corrupt: ${queueId}.`);
      const admissionId = randomUUID();
      const message = makeQueuedUserMessage(state.text, Date.now(), admissionId, turnId);
      const entryId = await this.session.appendCustomEntry("portlog.queue.admitted.v1", {
        queueId,
        turnId,
        admissionId,
        text: state.text,
        messageTimestamp: message.timestamp,
        messageDigest: queuedMessageDigest(message),
        admittedAt: new Date().toISOString(),
      });
      await this.session.appendMessage(message);
      return { entryId };
    });
  }

  async requestApproval(options: PortLogApprovalRequestOptions): Promise<PortLogApprovalRequest> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      assertBoundedText(options.action, "approval action");
      assertBoundedText(options.target, "approval target");
      assertBoundedText(options.approverClientId, "approver client ID");
      if (options.policyDigest !== this.identityValue.policy.digest)
        throw new PortLogSessionError(
          "approval_invalid",
          "Approval policy does not match the current session policy.",
        );
      const expiresAt = normalizeExpiry(options.expiresAt);
      const client = await this.readClientCredential(options.approverClientId);
      if (!client || client.role !== "observer" || client.canApprove !== true)
        throw new PortLogSessionError(
          "approval_invalid",
          "Approval approver is not an authorized observer.",
        );
      const approvalRequestId = randomUUID();
      const bindingDigest = approvalBindingDigest({
        approvalRequestId,
        action: options.action,
        target: options.target,
        workspaceRoot: this.identityValue.workspaceRoot,
        policyDigest: options.policyDigest,
        expiresAt,
        approverClientId: options.approverClientId,
      });
      await this.session.appendCustomEntry("portlog.approval.requested.v1", {
        approvalRequestId,
        action: options.action,
        target: options.target,
        workspaceRoot: this.identityValue.workspaceRoot,
        policyDigest: options.policyDigest,
        expiresAt,
        approverClientId: options.approverClientId,
        bindingDigest,
        requestedAt: new Date().toISOString(),
      });
      return { approvalRequestId, bindingDigest };
    });
  }

  async consumeApproval(
    approvalRequestId: string,
    execution: {
      action: string;
      target: string;
      policyDigest: string;
      toolCallId: string;
    },
  ): Promise<{ approvalRequestId: string; bindingDigest: string }> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      const entries = await this.session.getEntries();
      const state = readApprovalState(entries, approvalRequestId);
      if (!state || state.invalid || state.decision !== "approve" || state.consumed)
        throw new PortLogSessionError("approval_invalid", "Approval is not approved or was already consumed.");
      validateApprovalExecution(this.identityValue, state.request, execution);
      await this.session.appendCustomEntry("portlog.approval.consumed.v1", {
        approvalRequestId,
        bindingDigest: state.request.bindingDigest,
        toolCallId: execution.toolCallId,
        consumedAt: new Date().toISOString(),
      });
      return { approvalRequestId, bindingDigest: state.request.bindingDigest };
    });
  }

  private async withMutation<T>(operation: () => Promise<T>): Promise<T> {
    const previous = this.mutationTail;
    let release!: () => void;
    this.mutationTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await operation();
    } finally {
      release();
    }
  }

  private requireAttachmentRoot(): string {
    if (!this.attachmentRoot)
      throw new PortLogSessionError(
        "attachment_unavailable",
        "Client attachments require an external attachment root.",
      );
    return this.attachmentRoot;
  }

  private async readClientCredential(clientId: string): Promise<StoredClientCredential | undefined> {
    const path = credentialPath(this.requireAttachmentRoot(), this.sessionId, clientId);
    try {
      return JSON.parse(await readFile(path, "utf8")) as StoredClientCredential;
    } catch (error) {
      if (isNotFound(error)) return undefined;
      throw new PortLogSessionError(
        "attachment_invalid",
        `Client credential metadata could not be read: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  private async validateClientCredentials(credentials: PortLogClientCredentials): Promise<void> {
    await assertWriterFence(this.fence);
    if (credentials.sessionId !== this.sessionId)
      throw new PortLogSessionError("attachment_invalid", "Client credentials belong to another session.");
    const stored = await this.readClientCredential(credentials.clientId);
    if (
      !stored ||
      stored.sessionId !== credentials.sessionId ||
      stored.clientId !== credentials.clientId ||
      stored.role !== credentials.role ||
      stored.canApprove !== credentials.canApprove
    )
      throw new PortLogSessionError("attachment_revoked", "Client credentials are revoked or invalid.");
    const expected = Buffer.from(stored.tokenDigest, "hex");
    const actual = Buffer.from(digestToken(credentials.token), "hex");
    if (expected.length !== actual.length || !timingSafeEqual(expected, actual))
      throw new PortLogSessionError("attachment_revoked", "Client credentials are revoked or invalid.");
  }

  private async resyncEntries(
    cursor?: PortLogCanonicalCursor,
  ): Promise<{ entries: readonly unknown[]; cursor: PortLogCanonicalCursor }> {
    const entries = await this.getEntries();
    let nextEntryIndex = 0;
    if (cursor !== undefined) {
      if (!isRecord(cursor) || !Number.isInteger(cursor.nextEntryIndex))
        throw new PortLogSessionError("invalid_cursor", "Canonical event cursor is malformed.");
      nextEntryIndex = cursor.nextEntryIndex;
    }
    if (nextEntryIndex < 0 || nextEntryIndex > entries.length)
      throw new PortLogSessionError("invalid_cursor", "Canonical event cursor is outside the session history.");
    return {
      entries: entries.slice(nextEntryIndex),
      cursor: { nextEntryIndex: entries.length },
    };
  }

  private async enqueueQueuedPrompt(
    credentials: PortLogClientCredentials,
    text: string,
  ): Promise<string> {
    return this.withMutation(async () => {
      await this.validateClientCredentials(credentials);
      assertBoundedText(text, "queued prompt");
      const queueId = randomUUID();
      await this.session.appendCustomEntry("portlog.queue.enqueued.v1", {
        queueId,
        clientId: credentials.clientId,
        text,
        createdAt: new Date().toISOString(),
      });
      return queueId;
    });
  }

  private async decideApproval(
    credentials: PortLogClientCredentials,
    approvalRequestId: string,
    decision: "approve" | "deny",
  ): Promise<{ entryId: string }> {
    return this.withMutation(async () => {
      await this.validateClientCredentials(credentials);
      if (decision !== "approve" && decision !== "deny")
        throw new PortLogSessionError("approval_invalid", "Approval decision is invalid.");
      const state = readApprovalState(await this.session.getEntries(), approvalRequestId);
      if (!state || state.invalid || state.decision !== undefined || state.consumed)
        throw new PortLogSessionError("approval_invalid", "Approval is missing, decided, or consumed.");
      if (state.request.approverClientId !== credentials.clientId)
        throw new PortLogSessionError("approval_invalid", "Client is not the authorized approver.");
      validateApprovalRequest(this.identityValue, state.request);
      const entryId = await this.session.appendCustomEntry("portlog.approval.decided.v1", {
        approvalRequestId,
        decision,
        clientId: credentials.clientId,
        bindingDigest: state.request.bindingDigest,
        timestamp: Date.now(),
      });
      return { entryId };
    });
  }

  async appendMessage(message: AgentMessage): Promise<string> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      return this.session.appendMessage(message);
    });
  }

  async appendCustomEntry(customType: string, data?: unknown): Promise<string> {
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      return this.session.appendCustomEntry(customType, data);
    });
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
    return this.withMutation(async () => {
      await assertWriterFence(this.fence);
      for (const message of messages) await this.session.appendMessage(message);
    });
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
      if (event.type === "agent_end") await persistMessages(review.agent.state.messages);
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
    await this.mutationTail;
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

type StoredClientCredential = {
  readonly sessionId: string;
  readonly clientId: string;
  readonly role: PortLogClientRole;
  readonly canApprove: boolean;
  readonly tokenDigest: string;
};

type QueueState =
  | {
      readonly status: "queued";
      readonly text: string;
    }
  | {
      readonly status: "admission_started";
      readonly text: string;
      readonly turnId: string;
      readonly entryId: string;
      readonly admissionId: string;
      readonly messageTimestamp: number;
      readonly messageDigest: string;
    }
  | {
      readonly status: "admitted";
      readonly text: string;
      readonly entryId: string;
    }
  | {
      readonly status: "invalid";
      readonly text: string;
    };

type ApprovalBindingRecord = {
  readonly approvalRequestId: string;
  readonly action: string;
  readonly target: string;
  readonly workspaceRoot: string;
  readonly policyDigest: string;
  readonly expiresAt: string;
  readonly approverClientId: string;
  readonly bindingDigest: string;
};

type ApprovalState = {
  readonly request: ApprovalBindingRecord;
  readonly decision?: "approve" | "deny";
  readonly consumed: boolean;
  readonly invalid: boolean;
};

async function canonicalizeAttachmentRoot(
  attachmentRoot: string | undefined,
  workspaceRoot: string,
): Promise<string | undefined> {
  if (attachmentRoot === undefined) return undefined;
  const absolute = resolve(attachmentRoot);
  await mkdir(absolute, { recursive: true, mode: 0o700 });
  await chmod(absolute, 0o700);
  const canonical = await realpath(absolute);
  const relation = relative(workspaceRoot, canonical);
  if (relation === "" || (!relation.startsWith("..") && !isAbsolute(relation)))
    throw new PortLogSessionError(
      "identity_mismatch",
      "Attachment credentials must be stored outside the canonical workspace.",
    );
  return canonical;
}

function credentialPath(attachmentRoot: string, sessionId: string, clientId: string): string {
  const key = createHash("sha256").update(`${sessionId}\0${clientId}`).digest("hex");
  return join(attachmentRoot, `${key}.client.json`);
}

function digestToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function approvalBindingDigest(
  binding: Omit<ApprovalBindingRecord, "bindingDigest">,
): string {
  return createHash("sha256")
    .update(
      JSON.stringify({
        approvalRequestId: binding.approvalRequestId,
        action: binding.action,
        target: binding.target,
        workspaceRoot: binding.workspaceRoot,
        policyDigest: binding.policyDigest,
        expiresAt: binding.expiresAt,
        approverClientId: binding.approverClientId,
      }),
    )
    .digest("hex");
}

function normalizeExpiry(value: number | string): string {
  const date = typeof value === "number" ? new Date(value) : new Date(value);
  if (!Number.isFinite(date.getTime()))
    throw new PortLogSessionError("approval_invalid", "Approval expiry is invalid.");
  return date.toISOString();
}

function assertBoundedText(value: string, label: string): void {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 100_000)
    throw new PortLogSessionError("approval_invalid", `${label} must be bounded and non-empty.`);
}

function readCustomEntry(
  value: unknown,
): { customType: string; data: Record<string, unknown>; entryId?: string } | undefined {
  if (!isRecord(value) || value.type !== "custom" || typeof value.customType !== "string")
    return undefined;
  const data = isRecord(value.data) ? value.data : {};
  return {
    customType: value.customType,
    data,
    entryId: typeof value.id === "string" ? value.id : undefined,
  };
}
function makeQueuedUserMessage(
  text: string,
  timestamp: number,
  admissionId: string,
  turnId: string,
): AgentMessage {
  return {
    role: "user",
    content: [{ type: "text", text }],
    timestamp,
    portlogAdmission: { admissionId, turnId },
  } as unknown as AgentMessage;
}

function queuedMessageDigest(message: AgentMessage): string {
  return createHash("sha256").update(JSON.stringify(message)).digest("hex");
}

function queuedMessageIdentity(
  message: AgentMessage,
): { admissionId: string; turnId: string } | undefined {
  const record = message as unknown as Record<string, unknown>;
  if (!isRecord(record) || !isRecord(record.portlogAdmission)) return undefined;
  const { admissionId, turnId } = record.portlogAdmission;
  if (typeof admissionId !== "string" || typeof turnId !== "string") return undefined;
  return { admissionId, turnId };
}

function readQueueState(entries: readonly unknown[], queueId: string): QueueState | undefined {
  let state: QueueState | undefined;
  for (const entry of entries) {
    if (state?.status === "admission_started") {
      if (isMatchingQueuedMessage(entry, state)) {
        state = { status: "admitted", text: state.text, entryId: state.entryId };
      } else {
        state = { status: "invalid", text: state.text };
      }
      continue;
    }
    if (state?.status === "invalid") continue;
    const custom = readCustomEntry(entry);
    if (!custom || custom.data.queueId !== queueId) continue;
    if (custom.customType === "portlog.queue.enqueued.v1") {
      const text = custom.data.text;
      if (typeof text !== "string" || text.trim().length === 0) {
        state = { status: "invalid", text: "" };
      } else if (!state) {
        state = { status: "queued", text };
      } else {
        state = { status: "invalid", text };
      }
    } else if (custom.customType === "portlog.queue.admitted.v1") {
      const text = custom.data.text;
      const turnId = custom.data.turnId;
      const admissionId = custom.data.admissionId;
      const messageTimestamp = custom.data.messageTimestamp;
      const messageDigest = custom.data.messageDigest;
      if (
        state?.status !== "queued" ||
        typeof text !== "string" ||
        text !== state.text ||
        typeof turnId !== "string" ||
        turnId.length === 0 ||
        typeof admissionId !== "string" ||
        admissionId.length === 0 ||
        typeof messageTimestamp !== "number" ||
        !Number.isInteger(messageTimestamp) ||
        typeof messageDigest !== "string" ||
        messageDigest.length !== 64
      ) {
        state = { status: "invalid", text: typeof text === "string" ? text : state?.text ?? "" };
      } else {
        state = {
          status: "admission_started",
          text,
          turnId,
          entryId: custom.entryId ?? "",
          admissionId,
          messageTimestamp,
          messageDigest,
        };
      }
    }
  }
  return state;
}

function isMatchingQueuedMessage(
  value: unknown,
  state: Extract<QueueState, { status: "admission_started" }>,
): boolean {
  if (!isMessageEntry(value) || state.messageTimestamp !== value.message.timestamp) return false;
  const identity = queuedMessageIdentity(value.message);
  if (!identity || identity.admissionId !== state.admissionId || identity.turnId !== state.turnId)
    return false;
  return queuedMessageDigest(value.message) === state.messageDigest;
}

function readApprovalState(entries: readonly unknown[], approvalRequestId: string): ApprovalState | undefined {
  let request: ApprovalBindingRecord | undefined;
  let decision: "approve" | "deny" | undefined;
  let decisionBindingDigest: string | undefined;
  let decisionClientId: string | undefined;
  let consumed = false;
  let consumedBindingDigest: string | undefined;
  let invalid = false;
  for (const entry of entries) {
    const custom = readCustomEntry(entry);
    if (!custom || custom.data.approvalRequestId !== approvalRequestId) continue;
    if (custom.customType === "portlog.approval.requested.v1") {
      const data = custom.data;
      if (
        request ||
        typeof data.action !== "string" ||
        typeof data.target !== "string" ||
        typeof data.workspaceRoot !== "string" ||
        typeof data.policyDigest !== "string" ||
        typeof data.expiresAt !== "string" ||
        typeof data.approverClientId !== "string" ||
        typeof data.bindingDigest !== "string"
      ) {
        invalid = true;
      } else {
        request = data as unknown as ApprovalBindingRecord;
      }
    } else if (custom.customType === "portlog.approval.decided.v1") {
      if (
        !request ||
        decision !== undefined ||
        (custom.data.decision !== "approve" && custom.data.decision !== "deny") ||
        typeof custom.data.clientId !== "string" ||
        typeof custom.data.bindingDigest !== "string"
      ) {
        invalid = true;
      } else {
        decision = custom.data.decision;
        decisionClientId = custom.data.clientId;
        decisionBindingDigest = custom.data.bindingDigest;
      }
    } else if (custom.customType === "portlog.approval.consumed.v1") {
      if (
        !request ||
        decision !== "approve" ||
        consumed ||
        typeof custom.data.bindingDigest !== "string" ||
        typeof custom.data.toolCallId !== "string"
      ) {
        invalid = true;
      } else {
        consumed = true;
        consumedBindingDigest = custom.data.bindingDigest;
      }
    }
  }
  if (!request) return undefined;
  if (
    decision !== undefined &&
    (decisionBindingDigest !== request.bindingDigest ||
      decisionClientId !== request.approverClientId)
  )
    invalid = true;
  if (consumed && consumedBindingDigest !== request.bindingDigest) invalid = true;
  return { request, decision, consumed, invalid };
}

function validateApprovalRequest(
  identity: PortLogSessionIdentity,
  request: ApprovalBindingRecord,
): void {
  if (
    request.workspaceRoot !== identity.workspaceRoot ||
    request.policyDigest !== identity.policy.digest ||
    approvalBindingDigest(request) !== request.bindingDigest ||
    Date.parse(request.expiresAt) <= Date.now()
  )
    throw new PortLogSessionError(
      "approval_invalid",
      "Approval binding is stale, expired, or inconsistent with the session.",
    );
}

function validateApprovalExecution(
  identity: PortLogSessionIdentity,
  request: ApprovalBindingRecord,
  execution: { action: string; target: string; policyDigest: string; toolCallId: string },
): void {
  validateApprovalRequest(identity, request);
  if (
    execution.action !== request.action ||
    execution.target !== request.target ||
    execution.policyDigest !== request.policyDigest
  )
    throw new PortLogSessionError(
      "approval_invalid",
      "Execution does not match the exact approved action, target, and policy.",
    );
  assertBoundedText(execution.toolCallId, "tool call ID");
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
function isNotFound(error: unknown): boolean {
  return isRecord(error) && error.code === "ENOENT";
}

function isRecord(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
