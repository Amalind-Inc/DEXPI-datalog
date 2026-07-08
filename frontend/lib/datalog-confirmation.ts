import type { TurnStep } from "./turn-steps.ts";

export const DATALOG_CONFIRMATION_PREFIX = "pydexpi:datalog-confirmation:";
export const LOGIC_ANSWER_PREFIX = "pydexpi:logic-answer:";

export type DatalogConfirmationState = {
  plainLanguageMeaning: string;
  generatedDatalog: string;
  validationStatus: string;
  allowedActions: string[];
  raw: Record<string, unknown>;
  steps?: TurnStep[];
};

export type GroundedLogicAnswerState = {
  summary: string;
  rawEvidence: Record<string, unknown>;
  highlightedNodeIds: string[];
  raw: Record<string, unknown>;
  steps?: TurnStep[];
};

export function serializeDatalogConfirmation(state: DatalogConfirmationState) {
  return `${DATALOG_CONFIRMATION_PREFIX}${JSON.stringify(state)}`;
}

export function serializeGroundedLogicAnswer(state: GroundedLogicAnswerState) {
  return `${LOGIC_ANSWER_PREFIX}${JSON.stringify(state)}`;
}

export function parseDatalogConfirmationMessage(text: string): DatalogConfirmationState | null {
  if (!text.startsWith(DATALOG_CONFIRMATION_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(DATALOG_CONFIRMATION_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.plainLanguageMeaning !== "string") return null;
    if (typeof parsed.generatedDatalog !== "string") return null;
    if (typeof parsed.validationStatus !== "string") return null;
    if (!Array.isArray(parsed.allowedActions)) return null;
    if (!parsed.allowedActions.every((action) => typeof action === "string")) {
      return null;
    }
    return {
      plainLanguageMeaning: parsed.plainLanguageMeaning,
      generatedDatalog: parsed.generatedDatalog,
      validationStatus: parsed.validationStatus,
      allowedActions: parsed.allowedActions,
      raw: isRecord(parsed.raw) ? parsed.raw : {},
      steps: Array.isArray(parsed.steps) ? (parsed.steps as TurnStep[]) : [],
    };
  } catch {
    return null;
  }
}

export function parseGroundedLogicAnswerMessage(text: string): GroundedLogicAnswerState | null {
  if (!text.startsWith(LOGIC_ANSWER_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(LOGIC_ANSWER_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.summary !== "string") return null;
    if (!isRecord(parsed.rawEvidence)) return null;
    if (!Array.isArray(parsed.highlightedNodeIds)) return null;
    if (!parsed.highlightedNodeIds.every((id) => typeof id === "string")) {
      return null;
    }
    return {
      summary: parsed.summary,
      rawEvidence: parsed.rawEvidence,
      highlightedNodeIds: parsed.highlightedNodeIds,
      raw: isRecord(parsed.raw) ? parsed.raw : {},
      steps: Array.isArray(parsed.steps) ? (parsed.steps as TurnStep[]) : [],
    };
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
