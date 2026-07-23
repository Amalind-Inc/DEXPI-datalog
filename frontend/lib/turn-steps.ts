// Synthesizes an ordered "step" view of a turn from the coarse backend event
// log (bead pydexpi-datalog-1-2ki.11). Presentation-only: the backend event
// stream has no per-tool-call granularity (just tool-progress/text/evidence/
// review-required/terminal events), so steps are derived from what's
// actually there -- no fabricated timing or fake sub-steps.

export type TurnStepId = "retrieval" | "validation" | "evidence-answer" | `trace:${string}`;
export type TurnStepStatus = "done" | "blocked" | "canceled" | "failed" | "pending";

export type TurnStepDetail =
  | { kind: "retrieval"; resumed: boolean }
  | { kind: "retrieval-progress"; round: number; maxRounds: number; toolName: string | null }
  | { kind: "datalog-confirmation" }
  | { kind: "direction-review" }
  | { kind: "evidence"; evidenceReferences: string[] }
  | {
      kind: "execution-trace";
      traceKind: string;
      occurrenceCount: number;
      evidenceReferences: string[];
      artifactPath: string | null;
      artifactUrl: string | null;
    };

export type TurnStep = {
  id: TurnStepId;
  label: string;
  status: TurnStepStatus;
  detail?: TurnStepDetail;
};

type TurnEventLike = { type: string; data: Record<string, unknown> };
type TurnLike = {
  events: TurnEventLike[];
  session_id?: string;
  turn_id?: string;
};

// Minimal shape of ReducedTurn (from turn-client.ts) needed here -- kept
// local to avoid a circular import (turn-client.ts imports this module).
type ReducedTurnLike =
  | { kind: "answered"; evidenceReferences: string[] }
  | { kind: "review-required"; review: Record<string, unknown> }
  | { kind: "canceled" }
  | { kind: "failed"; message: string }
  | { kind: "in-progress" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function deriveTurnSteps(turn: TurnLike, reduced: ReducedTurnLike): TurnStep[] {
  if (reduced.kind === "canceled" || reduced.kind === "failed") {
    // Canceled/failed turns render as plain text, not a stepped card --
    // matches today's behavior (turnToMessage's early-return branches).
    return [];
  }

  if (reduced.kind === "in-progress") {
    // The turn is still executing server-side (bead 2ki.12). The backend now
    // persists a live "tool-progress"/"round" event per tool-calling round
    // (pydexpi_datalog/web/turn_lifecycle.py's append_progress) as it runs, so
    // a still-active turn can report real round/tool progress instead of a
    // single static pending row -- falls back to that generic row only if no
    // round has landed yet (e.g. the very first poll tick).
    const roundEvents = turn.events.filter(
      (event) => event.type === "tool-progress" && event.data.status === "round",
    );
    if (roundEvents.length > 0) {
      const last = roundEvents[roundEvents.length - 1];
      const round = typeof last.data.round === "number" ? last.data.round : 0;
      const maxRounds = typeof last.data.max_rounds === "number" ? last.data.max_rounds : 0;
      const toolName = typeof last.data.tool_name === "string" ? last.data.tool_name : null;
      return [
        {
          id: "retrieval",
          label: `Retrieval — round ${round} of ${maxRounds}`,
          status: "pending",
          detail: { kind: "retrieval-progress", round, maxRounds, toolName },
        },
      ];
    }
    return [{ id: "retrieval", label: "Retrieval", status: "pending" }];
  }

  const steps: TurnStep[] = [];

  const toolProgressEvents = turn.events.filter((event) => event.type === "tool-progress");
  if (toolProgressEvents.length > 0) {
    // The events array accumulates across a pause/resume, so a resumed
    // message's own turnToMessage() call sees BOTH the original "started"
    // and the later "resumed" marker -- the last one wins.
    const last = toolProgressEvents[toolProgressEvents.length - 1];
    steps.push({
      id: "retrieval",
      label: last.data.status === "resumed" ? "Retrieval (resumed)" : "Retrieval",
      status: "done",
      detail: { kind: "retrieval", resumed: last.data.status === "resumed" },
    });
  }

  for (const event of turn.events) {
    const trace = readExecutionTrace(event);
    if (trace === null) continue;
    steps.push({
      id: `trace:${trace.eventId}`,
      label: trace.summary,
      status: traceStepStatus(trace.status),
      detail: {
        kind: "execution-trace",
        traceKind: trace.traceKind,
        occurrenceCount: trace.occurrenceCount,
        evidenceReferences: trace.evidenceReferences,
        artifactPath: trace.artifactPath,
        artifactUrl:
          turn.session_id && turn.turn_id
            ? `/api/review/sessions/${encodeURIComponent(turn.session_id)}/turns/${encodeURIComponent(turn.turn_id)}/trace/${encodeURIComponent(trace.eventId)}`
            : null,
      },
    });
  }

  if (reduced.kind === "review-required") {
    const isDirectionReview = isRecord(reduced.review.direction_review);
    steps.push({
      id: "validation",
      label: "Validation",
      status: "blocked",
      detail: { kind: isDirectionReview ? "direction-review" : "datalog-confirmation" },
    });
  }

  if (reduced.kind === "answered") {
    steps.push({
      id: "evidence-answer",
      label: "Evidence & answer",
      status: "done",
      detail: { kind: "evidence", evidenceReferences: reduced.evidenceReferences },
    });
  }

  return steps;
}

function readExecutionTrace(event: TurnEventLike): {
  eventId: string;
  traceKind: string;
  status: string;
  summary: string;
  occurrenceCount: number;
  evidenceReferences: string[];
  artifactPath: string | null;
} | null {
  if (event.type !== "execution-trace" || event.data.schema_version !== 1) return null;
  const eventId = typeof event.data.event_id === "string" ? event.data.event_id : "";
  const traceKind = typeof event.data.kind === "string" ? event.data.kind : "";
  const summary = typeof event.data.summary === "string" ? event.data.summary.slice(0, 160) : "";
  if (!eventId || !traceKind.includes(".") || !summary) return null;
  const occurrenceCount =
    typeof event.data.occurrence_count === "number" && event.data.occurrence_count > 0
      ? event.data.occurrence_count
      : 1;
  const evidenceReferences = Array.isArray(event.data.evidence_references)
    ? event.data.evidence_references
        .filter((item): item is string => typeof item === "string")
        .slice(0, 25)
    : [];
  const detail = isRecord(event.data.detail) ? event.data.detail : {};
  const artifact = isRecord(detail.artifact) ? detail.artifact : {};
  const rawArtifactPath = typeof artifact.path === "string" ? artifact.path : "";
  const artifactPath =
    rawArtifactPath &&
    !rawArtifactPath.startsWith("/") &&
    !rawArtifactPath.split("/").includes("..")
      ? rawArtifactPath
      : null;
  return {
    eventId,
    traceKind,
    status: typeof event.data.status === "string" ? event.data.status : "completed",
    summary,
    occurrenceCount,
    evidenceReferences,
    artifactPath,
  };
}

function traceStepStatus(status: string): TurnStepStatus {
  switch (status) {
    case "blocked":
      return "blocked";
    case "canceled":
      return "canceled";
    case "failed":
      return "failed";
    case "pending":
    case "running":
      return "pending";
    default:
      return "done";
  }
}
