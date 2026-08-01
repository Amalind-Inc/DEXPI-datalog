"use client";

import { useEffect, useState } from "react";
import { usePidGraph } from "@/components/pid/graph-context";
import type { PrepareResult } from "@/components/pid/types";
import { SESSION_KEY } from "@/lib/session-id";
import {
  DESKTOP_CHAT_PROVIDER_KEY,
  type ClaudeAuthState,
  type CodexAuthState,
} from "@/lib/desktop-auth-types";

type OpenRouterState = {
  provider: "openrouter";
  model: "deepseek/deepseek-v4-flash";
  credentialSource: "environment";
  configured: boolean;
};
type InspectionEvent = {
  sequence: number;
  type: string;
  text?: string;
  tool?: string;
  callId?: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
};
type InspectionRecord = {
  turnId: string;
  posture: "inspect" | "verify";
  question: string;
  status: "active" | "completed" | "cancelled" | "failed";
  finalText: string;
  evidenceIds: string[];
  deterministicChecks?: Record<string, unknown>[];
  events: InspectionEvent[];
  error?: string;
};
type InspectionMessage = {
  kind: "event";
  turnId: string;
  event: InspectionEvent;
};
type LocalProject = {
  projectId?: string;
  source?: { filename?: string };
  turns?: InspectionRecord[];
  error?: string;
};

declare global {
  interface Window {
    portlogDesktop?: {
      selectDexpiSource(): Promise<{
        path: string;
        filename: string;
        content: string;
      } | null>;
      persistImportedProject(payload: {
        sourcePath: string;
        sourceContent: string;
        sessionId: string;
        filename: string;
        status: string;
        artifacts?: Record<string, string>;
      }): Promise<unknown>;
      loadCurrentProject(): Promise<LocalProject>;
      openRouterStatus(): Promise<OpenRouterState>;
      claudeAuthStatus(): Promise<ClaudeAuthState>;
      claudeLogin(): Promise<ClaudeAuthState>;
      claudeCancelLogin(): Promise<ClaudeAuthState>;
      claudeLogout(): Promise<ClaudeAuthState>;
      codexAuthStatus(): Promise<CodexAuthState>;
      codexLogin(method?: "browser" | "device_code"): Promise<CodexAuthState>;
      codexCancelLogin(): Promise<CodexAuthState>;
      codexLogout(): Promise<CodexAuthState>;
      checkOpenRouter(): Promise<unknown>;
      runLocalInspection(payload: {
        sessionId: string;
        turnId: string;
        question: string;
        posture?: "inspect" | "verify";
        provider?: "openrouter" | "anthropic" | "openai-codex";
      }): Promise<InspectionRecord>;
      cancelLocalInspection(turnId: string): Promise<{ cancelled: boolean }>;
      onInspectionEvent(listener: (message: InspectionMessage) => void): () => void;
    };
  }
}

export function DesktopDexpiImport() {
  const {
    sessionId,
    loadedFileName,
    beginDocumentImport,
    applyPrepareResult,
    setGraphOpen,
    setHighlightedNodeIds,
    setSelectedNodeId,
  } = usePidGraph();
  const [status, setStatus] = useState<string | null>(null);
  const [projectSessionId, setProjectSessionId] = useState<string | null>(null);
  const [openRouter, setOpenRouter] = useState<OpenRouterState | null>(null);
  const [claude, setClaude] = useState<ClaudeAuthState | null>(null);
  const [codex, setCodex] = useState<CodexAuthState | null>(null);
  const [question, setQuestion] = useState("What equipment and connections are around P4711?");
  const [posture, setPosture] = useState<"inspect" | "verify">("inspect");
  const [turns, setTurns] = useState<InspectionRecord[]>([]);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<InspectionEvent[]>([]);

  useEffect(() => {
    const desktop = typeof window === "undefined" ? undefined : window.portlogDesktop;
    if (!desktop) return;
    let cancelled = false;
    void Promise.all([
      desktop.openRouterStatus(),
      desktop.claudeAuthStatus(),
      desktop.codexAuthStatus(),
      desktop.loadCurrentProject(),
    ])
      .then(([provider, claudeStatus, codexStatus, project]) => {
        if (cancelled) return;
        setOpenRouter(provider);
        setClaude(claudeStatus);
        setCodex(codexStatus);
        setTurns(Array.isArray(project.turns) ? project.turns : []);
        setProjectSessionId(project.projectId ?? null);
        if (project.projectId) {
          window.localStorage.setItem(SESSION_KEY, project.projectId);
          void fetch(`/api/review/sessions/${encodeURIComponent(project.projectId)}/restore`)
            .then(async (response) =>
              response.ok ? ((await response.json()) as PrepareResult) : null,
            )
            .then((restored) => {
              if (restored && !cancelled)
                applyPrepareResult({
                  ...restored,
                  filename: project.source?.filename ?? restored.filename,
                });
            });
        }
      })
      .catch(() => {
        if (!cancelled) setOpenRouter(null);
      });
    const unsubscribe = desktop.onInspectionEvent((message) => {
      setLiveEvents((current) =>
        message.turnId === activeTurnId ? [...current, message.event] : current,
      );
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [activeTurnId]);

  if (typeof window === "undefined" || !window.portlogDesktop) return null;
  const openRouterText = openRouter?.configured
    ? "OpenRouter / deepseek/deepseek-v4-flash / Configured"
    : "OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.";
  const claudeConnected = claude?.state === "logged_in";
  const codexConnected = codex?.state === "logged_in";
  const canInspect = claudeConnected || codexConnected || Boolean(openRouter?.configured);

  const startCodexLogin = (method: "browser" | "device_code") => {
    const desktop = window.portlogDesktop;
    if (!desktop) return;
    setCodex((current) => ({
      provider: "openai-codex",
      recoverable: true,
      ...current,
      state: "opening_browser",
      loginMethod: method,
    }));
    const poll = window.setInterval(() => {
      void desktop
        .codexAuthStatus()
        .then(setCodex)
        .catch(() => undefined);
    }, 100);
    void desktop
      .codexLogin(method)
      .then((next) => {
        setCodex(next);
        if (next.state === "logged_in") selectDesktopChatProvider("openai-codex");
      })
      .catch((error) => setStatus(error instanceof Error ? error.message : "Codex login failed."))
      .finally(() => window.clearInterval(poll));
  };

  const runInspection = async (retry?: InspectionRecord) => {
    const trimmed = (retry?.question ?? question).trim();
    const selectedPosture = retry?.posture ?? posture;
    if (!trimmed || !loadedFileName || !canInspect) return;
    const turnId = retry?.turnId ?? crypto.randomUUID();
    setActiveTurnId(turnId);
    setLiveEvents([]);
    setStatus("Inspecting prepared review…");
    const selectedProvider = readSelectedDesktopProvider();
    try {
      const record = await window.portlogDesktop!.runLocalInspection({
        sessionId: projectSessionId ?? sessionId,
        turnId,
        question: trimmed,
        posture: selectedPosture,
        provider:
          selectedProvider === "openai-codex" && codexConnected
            ? selectedProvider
            : selectedProvider === "anthropic" && claudeConnected
              ? selectedProvider
              : openRouter?.configured
                ? "openrouter"
                : codexConnected
                  ? "openai-codex"
                  : claudeConnected
                    ? "anthropic"
                    : "openrouter",
      });
      setTurns((current) => [...current.filter((turn) => turn.turnId !== record.turnId), record]);
      setStatus(
        record.status === "completed"
          ? "Inspection complete"
          : record.status === "cancelled"
            ? "Inspection cancelled"
            : (record.error ?? "Inspection failed"),
      );
      if (record.evidenceIds.length) {
        setHighlightedNodeIds(record.evidenceIds);
        setSelectedNodeId(record.evidenceIds[0]);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Inspection failed");
    } finally {
      setActiveTurnId(null);
    }
  };

  return (
    <div className="space-y-3">
      <section aria-label="Claude account" className="border p-2 space-y-2">
        <p data-testid="desktop-claude-auth-status">
          Claude: {claude?.state === "logged_in" ? "Connected" : (claude?.state ?? "Checking")}
        </p>
        <p className="text-sm">
          A Claude Pro or Max subscription does not include PortLog usage; provider charges and
          eligibility are determined by Claude.
        </p>
        {claudeConnected ? (
          <button
            type="button"
            onClick={() => void window.portlogDesktop?.claudeLogout().then(setClaude)}
          >
            Log out
          </button>
        ) : (
          <button
            type="button"
            onClick={() =>
              void window.portlogDesktop
                ?.claudeLogin()
                .then((next) => {
                  setClaude(next);
                  if (next.state === "logged_in") selectDesktopChatProvider("anthropic");
                })
                .catch((error) =>
                  setStatus(error instanceof Error ? error.message : "Claude login failed."),
                )
            }
            disabled={
              claude?.state === "opening_browser" || claude?.state === "waiting_for_authorization"
            }
          >
            {claude?.state === "opening_browser" || claude?.state === "waiting_for_authorization"
              ? "Waiting for Claude authorization…"
              : "Log in with Claude"}
          </button>
        )}
        {claude?.state === "opening_browser" || claude?.state === "waiting_for_authorization" ? (
          <button
            type="button"
            onClick={() => void window.portlogDesktop?.claudeCancelLogin().then(setClaude)}
          >
            Cancel login
          </button>
        ) : null}
        {claude?.error ? <p role="alert">{claude.error}</p> : null}
      </section>
      <section aria-label="OpenAI Codex account" className="border p-2 space-y-2">
        <p data-testid="desktop-codex-auth-status">
          OpenAI Codex: {codex?.state === "logged_in" ? "Connected" : (codex?.state ?? "Checking")}
        </p>
        <p className="text-sm">
          Codex subscription access is separate from PortLog API-key usage; OpenAI determines
          eligibility and billing.
        </p>
        {codexConnected ? (
          <button
            type="button"
            onClick={() => void window.portlogDesktop?.codexLogout().then(setCodex)}
          >
            Log out of Codex
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => startCodexLogin("browser")}
              disabled={
                codex?.state === "opening_browser" || codex?.state === "waiting_for_authorization"
              }
            >
              {codex?.state === "opening_browser" || codex?.state === "waiting_for_authorization"
                ? "Waiting for Codex authorization…"
                : "Log in with Codex"}
            </button>
            <button
              type="button"
              onClick={() => startCodexLogin("device_code")}
              disabled={
                codex?.state === "opening_browser" || codex?.state === "waiting_for_authorization"
              }
            >
              Use device code
            </button>
          </div>
        )}
        {codex?.state === "opening_browser" || codex?.state === "waiting_for_authorization" ? (
          <button
            type="button"
            onClick={() => void window.portlogDesktop?.codexCancelLogin().then(setCodex)}
          >
            Cancel Codex login
          </button>
        ) : null}
        {codex?.deviceCode ? (
          <p role="status">
            Enter <strong>{codex.deviceCode.userCode}</strong> at {codex.deviceCode.verificationUri}
            .
          </p>
        ) : null}
        {codex?.error ? <p role="alert">{codex.error}</p> : null}
      </section>
      <p data-testid="desktop-openrouter-status">{openRouterText}</p>
      <button
        type="button"
        onClick={async () => {
          const source = await window.portlogDesktop?.selectDexpiSource();
          if (!source) return;
          beginDocumentImport();
          setStatus("Preparing DEXPI review…");
          try {
            const response = await fetch(`/api/review/sessions/${sessionId}/prepare`, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                filename: source.filename,
                content: source.content,
              }),
            });
            if (!response.ok) throw new Error(`Import failed (${response.status})`);
            const result = (await response.json()) as PrepareResult;
            await window.portlogDesktop?.persistImportedProject({
              sourcePath: source.path,
              sourceContent: source.content,
              sessionId,
              filename: source.filename,
              status: result.status,
              artifacts: { topology: `backend:${sessionId}/topology` },
            });
            setProjectSessionId(sessionId);
            applyPrepareResult(result);
            setGraphOpen(true);
            setTurns([]);
            setStatus(`Prepared ${source.filename}`);
          } catch (error) {
            setStatus(error instanceof Error ? error.message : "Import failed");
          }
        }}
      >
        Import DEXPI{status ? ` — ${status}` : ""}
      </button>

      {loadedFileName ? (
        <section aria-label="Local evidence inspection" className="space-y-2">
          <label className="block text-sm" htmlFor="desktop-inspection-question">
            Ask about this prepared P&amp;ID
          </label>
          <div className="flex gap-2">
            <input
              id="desktop-inspection-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={Boolean(activeTurnId)}
              className="min-w-0 flex-1 border px-2 py-1"
            />
            <select
              aria-label="Review posture"
              value={posture}
              onChange={(event) => setPosture(event.target.value as "inspect" | "verify")}
              disabled={Boolean(activeTurnId)}
            >
              <option value="inspect">Inspect</option>
              <option value="verify">Verify</option>
            </select>
            <button
              type="button"
              onClick={() => void runInspection()}
              disabled={Boolean(activeTurnId) || !canInspect}
            >
              Inspect
            </button>
            {activeTurnId ? (
              <button
                type="button"
                onClick={() => void window.portlogDesktop?.cancelLocalInspection(activeTurnId)}
              >
                Cancel
              </button>
            ) : null}
          </div>
          {activeTurnId ? (
            <InspectionTimeline
              events={liveEvents}
              onSelectEvidence={(ids) => {
                setHighlightedNodeIds(ids);
                setSelectedNodeId(ids[0] ?? null);
              }}
            />
          ) : null}
          {[...turns].reverse().map((turn) => (
            <article key={turn.turnId} data-testid="desktop-inspection-turn" className="border p-2">
              <p>
                <strong>{turn.posture === "verify" ? "Verify" : "Inspect"}</strong> · {turn.status}
              </p>
              <p>{turn.question}</p>
              {turn.deterministicChecks?.map((check, index) => (
                <section
                  key={`${turn.turnId}-check-${index}`}
                  aria-label="Deterministic verification result"
                  data-testid="deterministic-check-result"
                  className="border p-2"
                >
                  <p>
                    <strong>Deterministic result</strong> ·{" "}
                    {String(check.check_id ?? "unknown check")}
                  </p>
                  <p>
                    Status: {String(check.run_status ?? "unknown")} · Outcome:{" "}
                    {String(check.outcome ?? "No outcome")}
                  </p>
                  {check.reason_code ? <p>Reason: {String(check.reason_code)}</p> : null}
                  <details>
                    <summary>Rule and evidence trace</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          required_facts: check.required_facts,
                          evidence: check.evidence,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </section>
              ))}
              {turn.finalText ? (
                <section aria-label="Model interpretation">
                  <p>
                    <strong>Model interpretation</strong>
                  </p>
                  <p>{turn.finalText}</p>
                </section>
              ) : null}
              {turn.error ? <p role="alert">{turn.error}</p> : null}
              <InspectionTimeline
                events={turn.events}
                onSelectEvidence={(ids) => {
                  setHighlightedNodeIds(ids);
                  setSelectedNodeId(ids[0] ?? null);
                }}
              />
              {turn.status === "failed" || turn.status === "active" ? (
                <button
                  type="button"
                  onClick={() => {
                    setQuestion(turn.question);
                    setPosture(turn.posture);
                    void runInspection(turn);
                  }}
                >
                  Retry
                </button>
              ) : null}
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}

function readSelectedDesktopProvider(): "anthropic" | "openai-codex" | null {
  const value = window.localStorage.getItem(DESKTOP_CHAT_PROVIDER_KEY);
  return value === "anthropic" || value === "openai-codex" ? value : null;
}

function selectDesktopChatProvider(provider: "anthropic" | "openai-codex") {
  window.localStorage.setItem(DESKTOP_CHAT_PROVIDER_KEY, provider);
}

function InspectionTimeline({
  events,
  onSelectEvidence,
}: {
  events: InspectionEvent[];
  onSelectEvidence(ids: string[]): void;
}) {
  const streamedText = events
    .filter((event) => event.type === "assistant_text_delta")
    .map((event) => event.text ?? "")
    .join("");
  return (
    <div>
      {streamedText ? <p aria-live="polite">{streamedText}</p> : null}
      <ol aria-label="Inspection activity">
        {events
          .filter((event) => event.type !== "assistant_text_delta")
          .map((event) => {
            const evidence = readEvidenceIds(event.result);
            const hasDetails = event.arguments !== undefined || event.result !== undefined;
            const label = `${event.type.replaceAll("_", " ")}${event.tool ? ` · ${event.tool}` : ""}`;
            return (
              <li key={`${event.sequence}-${event.type}`}>
                {hasDetails ? (
                  <details>
                    <summary>{label}</summary>
                    <pre>{JSON.stringify(event.arguments ?? event.result, null, 2)}</pre>
                  </details>
                ) : (
                  <span>{label}</span>
                )}
                {evidence.length ? (
                  <button type="button" onClick={() => onSelectEvidence(evidence)}>
                    Select evidence ({evidence.length})
                  </button>
                ) : null}
              </li>
            );
          })}
      </ol>
    </div>
  );
}

function readEvidenceIds(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(readEvidenceIds);
  if (!value || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const direct = [
    record.citations,
    record.evidenceIds,
    record.evidence_ids,
    record.ordered_topology_ids,
  ]
    .flatMap((candidate) => (Array.isArray(candidate) ? candidate : []))
    .filter((candidate): candidate is string => typeof candidate === "string");
  return Array.from(new Set([...direct, ...Object.values(record).flatMap(readEvidenceIds)]));
}
