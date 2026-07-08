import type { TurnStep } from "./turn-steps.ts";

export const IN_PROGRESS_TURN_PREFIX = "pydexpi:in-progress-turn:";

export type InProgressTurnState = {
  steps: TurnStep[];
};

export function serializeInProgressTurn(state: InProgressTurnState): string {
  return `${IN_PROGRESS_TURN_PREFIX}${JSON.stringify(state)}`;
}

export function parseInProgressTurnMessage(text: string): InProgressTurnState | null {
  if (!text.startsWith(IN_PROGRESS_TURN_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(IN_PROGRESS_TURN_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (!Array.isArray(parsed.steps)) return null;
    return { steps: parsed.steps as TurnStep[] };
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
