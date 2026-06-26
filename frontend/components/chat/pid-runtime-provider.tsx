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

const HISTORY_KEY = "pydexpi.pidQa.threadHistory.v2";

export function PidAssistantProviders({ children }: { children: ReactNode }) {
  return (
    <PidGraphProvider>
      <PidRuntimeProvider>{children}</PidRuntimeProvider>
    </PidGraphProvider>
  );
}

function PidRuntimeProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(() => `pid-${crypto.randomUUID()}`);
  const { applyPrepareResult, selectedNode, selectedNodeId, setHighlightedNodeIds } = usePidGraph();
  const graphContextRef = useRef({ selectedNode, selectedNodeId });

  useEffect(() => {
    graphContextRef.current = { selectedNode, selectedNodeId };
  }, [selectedNode, selectedNodeId]);

  const modelAdapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        const graphContext = graphContextRef.current;
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: messages.map(toBackendMessage),
            sessionId,
            selectedNode: graphContext.selectedNode,
            selectedNodeId: graphContext.selectedNodeId,
          }),
          signal: abortSignal,
        });
        if (!response.ok) {
          throw new Error(`Chat request failed: ${response.status}`);
        }
        const data = (await response.json()) as {
          message: string;
          highlightedNodeIds?: string[];
        };
        if (data.highlightedNodeIds) {
          setHighlightedNodeIds(data.highlightedNodeIds);
        }
        return { content: [{ type: "text", text: data.message }] };
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

  const history = useMemo<ThreadHistoryAdapter>(() => createLocalHistory(), []);

  const runtime = useLocalRuntime(modelAdapter, {
    adapters: {
      attachments,
      history,
    },
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}

function createLocalHistory(): ThreadHistoryAdapter {
  return {
    async load() {
      if (typeof window === "undefined") return { messages: [] };
      const raw = window.localStorage.getItem(HISTORY_KEY);
      if (!raw) return { messages: [] };
      return JSON.parse(raw) as {
        messages: { parentId: string | null; message: ThreadMessage }[];
      };
    },
    async append(item) {
      if (typeof window === "undefined") return;
      const raw = window.localStorage.getItem(HISTORY_KEY);
      const history = raw
        ? (JSON.parse(raw) as {
            messages: { parentId: string | null; message: ThreadMessage }[];
          })
        : { messages: [] };
      history.messages.push(item);
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
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

function readFileText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(file);
  });
}
