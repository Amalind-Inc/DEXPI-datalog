import type { TurnStep } from "./turn-steps.ts";

export const QA_ANSWER_PREFIX = "pydexpi:qa-answer:";

export type EvidencePath = {
  id: string;
  node_ids: string[];
  edge_ids: string[];
};

export type EvidenceHighlight = {
  source_scope_ids: string[];
  matched_object_ids: string[];
  paths: EvidencePath[];
};

export type GroundedQAAnswerState = {
  answerText: string;
  evidenceReferences: string[];
  interpretedObjectIds: string[];
  evidenceHighlight: EvidenceHighlight;
  raw: Record<string, unknown>;
  steps?: TurnStep[];
};

export function serializeGroundedQAAnswer(state: GroundedQAAnswerState): string {
  return `${QA_ANSWER_PREFIX}${JSON.stringify(state)}`;
}

export function parseGroundedQAAnswerMessage(text: string): GroundedQAAnswerState | null {
  if (!text.startsWith(QA_ANSWER_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(QA_ANSWER_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.answerText !== "string") return null;
    if (!Array.isArray(parsed.evidenceReferences)) return null;
    if (!parsed.evidenceReferences.every((r: unknown) => typeof r === "string")) return null;
    const highlight = parsed.evidenceHighlight;
    if (!isRecord(highlight)) return null;
    return {
      answerText: parsed.answerText,
      evidenceReferences: parsed.evidenceReferences,
      interpretedObjectIds: Array.isArray(parsed.interpretedObjectIds)
        ? (parsed.interpretedObjectIds as string[]).filter(
            (r): r is string => typeof r === "string",
          )
        : [],
      evidenceHighlight: {
        source_scope_ids: Array.isArray(highlight.source_scope_ids)
          ? (highlight.source_scope_ids as string[])
          : [],
        matched_object_ids: Array.isArray(highlight.matched_object_ids)
          ? (highlight.matched_object_ids as string[])
          : [],
        paths: Array.isArray(highlight.paths) ? (highlight.paths as EvidencePath[]) : [],
      },
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
