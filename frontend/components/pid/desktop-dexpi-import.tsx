"use client";

import { useState } from "react";
import { usePidGraph } from "@/components/pid/graph-context";
import type { PrepareResult } from "@/components/pid/types";

declare global {
  interface Window {
    portlogDesktop?: { selectDexpiSource(): Promise<{ path: string; filename: string; content: string } | null>; persistImportedProject(payload: { sourcePath: string; sourceContent: string; sessionId: string; filename: string; status: string; artifacts?: Record<string, string> }): Promise<unknown>; loadCurrentProject(): Promise<unknown>; };
  }
}

export function DesktopDexpiImport() {
  const { sessionId, beginDocumentImport, applyPrepareResult, setGraphOpen } = usePidGraph();
  const [status, setStatus] = useState<string | null>(null);
  if (typeof window === "undefined" || !window.portlogDesktop) return null;
  return <button type="button" onClick={async () => {
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
  }}>Import DEXPI{status ? ` — ${status}` : ""}</button>;
}
