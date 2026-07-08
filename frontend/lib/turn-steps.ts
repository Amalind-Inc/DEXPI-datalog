// Synthesizes an ordered "step" view of a turn from the coarse backend event
// log (bead pydexpi-datalog-1-2ki.11). Presentation-only: the backend event
// stream has no per-tool-call granularity (just tool-progress/text/evidence/
// review-required/terminal events), so steps are derived from what's
// actually there -- no fabricated timing or fake sub-steps.

export type TurnStepId = "retrieval" | "validation" | "evidence-answer";
export type TurnStepStatus = "done" | "blocked" | "canceled" | "failed" | "pending";

export type TurnStepDetail =
  | { kind: "retrieval"; resumed: boolean }
  | { kind: "retrieval-progress"; round: number; maxRounds: number; toolName: string | null }
  | { kind: "datalog-confirmation" }
  | { kind: "direction-review" }
  | { kind: "evidence"; evidenceReferences: string[] };

export type TurnStep = {
  id: TurnStepId;
  label: string;
  status: TurnStepStatus;
  detail?: TurnStepDetail;
};

type TurnEventLike = { type: string; data: Record<string, unknown> };
type TurnLike = { events: TurnEventLike[] };

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
