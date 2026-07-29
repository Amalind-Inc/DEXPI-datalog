"use client";

import { useEffect, useState } from "react";
import { usePidGraph } from "@/components/pid/graph-context";
import type { PrepareResult } from "@/components/pid/types";

type OpenRouterState = {
  provider: "openrouter";
  model: "deepseek/deepseek-v4-flash";
  credentialSource: "environment";
  configured: boolean;
};

declare global {
  interface Window {
    portlogDesktop?: {
      selectDexpiSource(): Promise<{ path: string; filename: string; content: string } | null>;
      persistImportedProject(payload: { sourcePath: string; sourceContent: string; sessionId: string; filename: string; status: string; artifacts?: Record<string, string> }): Promise<unknown>;
      loadCurrentProject(): Promise<unknown>;
      openRouterStatus(): Promise<OpenRouterState>;
      checkOpenRouter(): Promise<unknown>;
    };
  }
}

export function DesktopDexpiImport() {
  const { sessionId, beginDocumentImport, applyPrepareResult, setGraphOpen } = usePidGraph();
  const [status, setStatus] = useState<string | null>(null);
  const [openRouter, setOpenRouter] = useState<OpenRouterState | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !window.portlogDesktop) return;
    let cancelled = false;
    window.portlogDesktop.openRouterStatus().then((state) => {
      if (!cancelled) setOpenRouter(state);
    }).catch(() => {
      if (!cancelled) setOpenRouter(null);
    });
    return () => { cancelled = true; };
  }, []);

  if (typeof window === "undefined" || !window.portlogDesktop) return null;
  const openRouterText = openRouter?.configured
    ? "OpenRouter / deepseek/deepseek-v4-flash / Configured"
    : "OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.";
  return (
    <div>
      <p data-testid="desktop-openrouter-status">{openRouterText}</p>
      <button type="button" onClick={async () => {
        const source = await window.portlogDesktop?.selectDexpiSource();
        if (!source) return;
        beginDocumentImport();
        setStatus("Preparing DEXPI review…");
        try {
          const response = await fetch(`/api/review/sessions/${sessionId}/prepare`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ filename: source.filename, content: source.content }) });
          if (!response.ok) throw new Error(`Import failed (${response.status})`);
          const result = await response.json() as PrepareResult;
          await window.portlogDesktop?.persistImportedProject({ sourcePath: source.path, sourceContent: source.content, sessionId, filename: source.filename, status: result.status, artifacts: { topology: `backend:${sessionId}/topology` } });
          applyPrepareResult(result); setGraphOpen(true); setStatus(`Prepared ${source.filename}`);
        }
        catch (error) { setStatus(error instanceof Error ? error.message : "Import failed"); }
      }}>Import DEXPI{status ? ` — ${status}` : ""}</button>
    </div>
  );
}
