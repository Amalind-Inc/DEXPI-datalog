"use client";

import {
  AssistantRuntimeProvider,
  type Attachment,
  type AttachmentAdapter,
  type ChatModelAdapter,
  type CompleteAttachment,
  type PendingAttachment,
  type ThreadHistoryAdapter,
  type ThreadMessage,
  useLocalRuntime,
} from "@assistant-ui/react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { PidGraphProvider, usePidGraph } from "@/components/pid/graph-context";
import type { PrepareResult } from "@/components/pid/types";
import {
  cancelTurn,
  computeTurnId,
  getTurn,
  sha256Hex,
  startTurn,
  TurnRequestError,
  turnToMessage,
  type TurnState,
} from "@/lib/turn-client";
import { parseGroundedQAAnswerMessage } from "@/lib/grounded-qa-answer";

const HISTORY_KEY = "pydexpi.pidQa.threadHistory.v2";
const SESSION_KEY = "pydexpi.pidQa.sessionId.v1";
const ACTIVE_TURN_KEY_PREFIX = "pydexpi.pidQa.activeTurn.v1.";

type ActiveTurnRecord = {
  sessionId: string;
  requestId: string;
  turnId: string;
  question: string;
};

type StoredHistory = {
  messages: { parentId: string | null; message: ThreadMessage }[];
};

export function PidAssistantProviders({ children }: { children: ReactNode }) {
  return (
    <PidGraphProvider>
      <PidRuntimeProvider>{children}</PidRuntimeProvider>
    </PidGraphProvider>
  );
}

function PidRuntimeProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(readOrCreateSessionId);
  const { applyPrepareResult, selectedNode, selectedNodeId, setHighlightedNodeIds } = usePidGraph();
  const graphContextRef = useRef({ selectedNode, selectedNodeId });

  useEffect(() => {
    graphContextRef.current = { selectedNode, selectedNodeId };
  }, [selectedNode, selectedNodeId]);

  const modelAdapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        const backendMessages = messages.map(toBackendMessage);
        const question = lastUserText(backendMessages);
        const conversation = buildTurnConversation(backendMessages);
        // selectedNode is null when the stored id is not in the current graph
        // (e.g. the "pump-101" sample default before upload).  Use the
        // resolved object so a stale id never reaches the backend scope.
        const selectedNodeId = graphContextRef.current.selectedNode?.id ?? undefined;
        // Stable request id: identical double-sends map to the same turn
        // (backend dedupes); a different history prefix or scope selection
        // yields a fresh turn.
        const requestId = (
          await sha256Hex(`${sessionId}\n${selectedNodeId ?? ""}\n${JSON.stringify(backendMessages)}`)
        ).slice(0, 32);
        const turnId = await computeTurnId(sessionId, requestId);

        // Persist before the POST so a mid-flight refresh can recover the
        // turn via getTurn() on the next load(). Cleared in history.append().
        writeActiveTurn({ sessionId, requestId, turnId, question });

        // The backend executes turns synchronously inside the POST; the
        // abort signal can only fire while that request is in flight. Do NOT
        // pass the signal to fetch — the turn keeps executing server-side
        // regardless, so an aborted fetch would only lose the response. On
        // abort, cancel the backend turn and surface its terminal state.
        let turn: TurnState;
        if (abortSignal.aborted) {
          turn = await cancelTurn(sessionId, turnId);
        } else {
          const startPromise = startTurn(sessionId, {
            question,
            requestId,
            conversation,
            selectedNodeId,
          });
          // Swallow the eventual start result if cancellation wins the race:
          // the cancel response carries the turn's terminal state.
          const { promise: abortPromise, resolve: abortResolve } =
            Promise.withResolvers<"aborted">();
          const onAbort = () => abortResolve("aborted");
          abortSignal.addEventListener("abort", onAbort, { once: true });
          try {
            const raced = await Promise.race([startPromise, abortPromise]);
            if (raced === "aborted") {
              turn = await cancelTurnWithRetry(sessionId, turnId, startPromise);
            } else {
              turn = raced;
            }
          } finally {
            abortSignal.removeEventListener("abort", onAbort);
          }
        }

        const result = turnToMessage(turn);
        if (result.status === "failed") {
          clearActiveTurn(sessionId);
          throw new Error(result.message);
        }
        if (result.highlightedNodeIds.length > 0) {
          setHighlightedNodeIds(result.highlightedNodeIds);
        }
        return { content: [{ type: "text", text: result.message }] };
      },
    }),
    [sessionId, setHighlightedNodeIds],
  );

  const attachments = useMemo<AttachmentAdapter>(
    () => ({
      accept: ".xml,text/xml,application/xml",
      async add({ file }) {
        if (!file.name.toLowerCase().endsWith(".xml")) {
          throw new Error("Only plant XML files are supported.");
        }
        const content = await readFileText(file);
        const response = await fetch(`/api/review/sessions/${sessionId}/prepare`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, content }),
        });
        if (!response.ok) {
          throw new Error(`XML prepare failed: ${response.status}`);
        }
        const result = (await response.json()) as PrepareResult;
        applyPrepareResult(result);
        return {
          id: crypto.randomUUID(),
          type: "document",
          name: file.name,
          contentType: file.type || "application/xml",
          file,
          status: { type: "requires-action", reason: "composer-send" },
        } satisfies PendingAttachment;
      },
      async send(attachment) {
        return {
          ...attachment,
          status: { type: "complete" },
          content: [
            {
              type: "text",
              text: `[Plant XML uploaded: ${attachment.name}]`,
            },
          ],
        } satisfies CompleteAttachment;
      },
      async remove(_attachment: Attachment) {
        return undefined;
      },
    }),
    [applyPrepareResult, sessionId],
  );

  const history = useMemo<ThreadHistoryAdapter>(() => createLocalHistory(sessionId), [sessionId]);

  const runtime = useLocalRuntime(modelAdapter, {
    adapters: {
      attachments,
      history,
    },
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}

/**
 * Cancel a turn whose start POST is still in flight. The cancel can 404 when
 * the abort outruns turn creation on the backend, so retry while the start
 * request is pending; if the start settles first (the turn completed before
 * any cancel landed), its response is the authoritative terminal state.
 */
async function cancelTurnWithRetry(
  sessionId: string,
  turnId: string,
  startPromise: Promise<TurnState>,
): Promise<TurnState> {
  // Once cancellation is requested the start result must never win the race
  // silently — but if the turn reached a terminal state before a cancel
  // landed, that state is what the user observes.
  startPromise.catch(() => {});
  let startSettled = false;
  const settledStart = startPromise.then(
    (turn) => {
      startSettled = true;
      return turn;
    },
    () => {
      startSettled = true;
      return null;
    },
  );
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      return await cancelTurn(sessionId, turnId);
    } catch {
      // Turn not created yet (404) or transient failure: wait, then retry
      // unless the start request itself has already settled.
    }
    if (startSettled) {
      const settled = await settledStart;
      if (settled !== null) return settled;
      // Start failed and cancel keeps failing: give the cancel one last shot
      // below, then surface the error.
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 250);
    await promise;
  }
  return cancelTurn(sessionId, turnId);
}

function readOrCreateSessionId(): string {
  if (typeof window === "undefined") return `pid-${crypto.randomUUID()}`;
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = `pid-${crypto.randomUUID()}`;
  window.localStorage.setItem(SESSION_KEY, created);
  return created;
}

function activeTurnKey(sessionId: string): string {
  return `${ACTIVE_TURN_KEY_PREFIX}${sessionId}`;
}

function writeActiveTurn(record: ActiveTurnRecord): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(activeTurnKey(record.sessionId), JSON.stringify(record));
}

function readActiveTurn(sessionId: string): ActiveTurnRecord | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(activeTurnKey(sessionId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ActiveTurnRecord>;
    if (
      typeof parsed.sessionId === "string" &&
      typeof parsed.requestId === "string" &&
      typeof parsed.turnId === "string" &&
      typeof parsed.question === "string"
    ) {
      return parsed as ActiveTurnRecord;
    }
  } catch {
    // fall through to clear
  }
  window.localStorage.removeItem(activeTurnKey(sessionId));
  return null;
}

function clearActiveTurn(sessionId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(activeTurnKey(sessionId));
}

function readStoredHistory(): StoredHistory {
  const raw = window.localStorage.getItem(HISTORY_KEY);
  if (!raw) return { messages: [] };
  return JSON.parse(raw) as StoredHistory;
}

/**
 * localStorage-backed thread history with active-turn recovery.
 *
 * The active-turn record written by run() is only cleared once the assistant
 * message has actually been persisted here (append) — so a refresh at any
 * point between POST and persistence is recoverable: load() fetches the turn
 * from the backend (it executes synchronously, so by reconnect time it is
 * resolved or paused) and appends the missing assistant message.
 */
function createLocalHistory(sessionId: string): ThreadHistoryAdapter {
  return {
    async load() {
      if (typeof window === "undefined") return { messages: [] };
      const history = readStoredHistory();
      const active = readActiveTurn(sessionId);
      if (!active) return history;

      const recoveredId = `recovered-turn-${active.turnId}`;
      const alreadyPresent = history.messages.some((item) => item.message.id === recoveredId);
      if (alreadyPresent) {
        clearActiveTurn(sessionId);
        return history;
      }

      // The backend keeps executing the turn even though the refresh killed
      // the POST. Poll until it leaves "active"; if it is still running after
      // the budget, keep the record so a later load can pick it up.
      let turn: TurnState | null = null;
      for (let attempt = 0; attempt < 30; attempt += 1) {
        try {
          turn = await getTurn(active.sessionId, active.turnId);
        } catch (error) {
          // 404 is definitive: the turn never reached the backend — drop the
          // record; the user's message is in history and can be resent. Any
          // other failure (network, 5xx) may be transient: keep the record
          // so a later load can still recover the turn.
          if (error instanceof TurnRequestError && error.status === 404) {
            clearActiveTurn(sessionId);
          }
          return history;
        }
        if (turn.status !== "active") break;
        const { promise, resolve } = Promise.withResolvers<void>();
        setTimeout(resolve, 1000);
        await promise;
      }
      if (turn === null || turn.status === "active") return history;

      const result = turnToMessage(turn);
      const parentId =
        history.messages.length > 0
          ? history.messages[history.messages.length - 1].message.id
          : null;
      const recovered: ThreadMessage = {
        id: recoveredId,
        createdAt: new Date(),
        role: "assistant",
        content: [{ type: "text", text: result.message }],
        status: { type: "complete", reason: "stop" },
        metadata: {
          unstable_state: null,
          unstable_annotations: [],
          unstable_data: [],
          steps: [],
          custom: {},
        },
      };
      history.messages.push({ parentId, message: recovered });
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
      clearActiveTurn(sessionId);
      return history;
    },
    async append(item) {
      if (typeof window === "undefined") return;
      const history = readStoredHistory();
      history.messages.push(item);
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
      // The turn's outcome is now durably in history; the active-turn record
      // has served its recovery purpose. Only one turn is in flight at a
      // time, so any persisted assistant message resolves the pending record.
      if (item.message.role === "assistant") {
        clearActiveTurn(sessionId);
      }
    },
  };
}

function toBackendMessage(message: ThreadMessage) {
  return {
    role: message.role,
    content: message.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .filter(Boolean)
      .join("\n"),
  };
}

function lastUserText(messages: Array<{ role: string; content: string }>): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") return messages[index].content;
  }
  return "";
}

/**
 * Pair each prior assistant QA answer with the user question preceding it —
 * the same conversation shape the backend QA harness consumes (see
 * buildQAConversation in review-backend.ts, which handles the legacy path).
 */
function buildTurnConversation(
  messages: Array<{ role: string; content: string }>,
): Array<{ question: string; answer_text: string; evidence_references: string[] }> {
  const turns: Array<{ question: string; answer_text: string; evidence_references: string[] }> =
    [];
  for (let index = 0; index < messages.length - 1; index += 1) {
    const message = messages[index];
    if (message.role !== "assistant") continue;
    const parsed = parseGroundedQAAnswerMessage(message.content);
    if (!parsed) continue;
    let question = "";
    for (let back = index - 1; back >= 0; back -= 1) {
      if (messages[back].role === "user") {
        question = messages[back].content;
        break;
      }
    }
    turns.push({
      question,
      answer_text: parsed.answerText,
      evidence_references: parsed.evidenceReferences,
    });
  }
  return turns;
}

function readFileText(file: File) {
  const { promise, resolve, reject } = Promise.withResolvers<string>();
  const reader = new FileReader();
  reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
  reader.addEventListener("error", () => reject(reader.error));
  reader.readAsText(file);
  return promise;
}
