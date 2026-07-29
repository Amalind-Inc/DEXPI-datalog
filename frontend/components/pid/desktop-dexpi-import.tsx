"use client";

import { useState } from "react";
import { usePidGraph } from "@/components/pid/graph-context";
import { prepareReviewSession } from "@/lib/review-backend";

declare global {
  interface Window {
    portlogDesktop?: { selectDexpiSource(): Promise<{ path: string; filename: string; content: string } | null> };
  }
}

export function DesktopDexpiImport() {
  const { sessionId, applyPrepareResult, setGraphOpen } = usePidGraph();
  const [status, setStatus] = useState<string | null>(null);
  if (typeof window === "undefined" || !window.portlogDesktop) return null;
  return <button type="button" onClick={async () => {
    const source = await window.portlogDesktop?.selectDexpiSource();
    if (!source) return;
    setStatus("Preparing DEXPI review…");
    try { const result = await prepareReviewSession(sessionId, { filename: source.filename, content: source.content }); applyPrepareResult(result); setGraphOpen(true); setStatus(`Prepared ${source.filename}`); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Import failed"); }
  }}>Import DEXPI{status ? ` — ${status}` : ""}</button>;
}
