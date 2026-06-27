import type { EvidenceHighlight } from "./grounded-qa-answer.ts";

export const DIRECTION_REVIEW_PREFIX = "pydexpi:direction-review:";

export type DirectionReviewConversationTurn = {
  question: string;
  answer_text: string;
  evidence_references: string[];
};

export type DirectionReviewState = {
  question: string;
  reviewKey: string;
  proposedDirection: string;
  directionBasis: string;
  basisExplanation: string;
  evidenceHighlight: EvidenceHighlight;
  conversation: DirectionReviewConversationTurn[];
  raw: Record<string, unknown>;
};

export function serializeDirectionReview(state: DirectionReviewState): string {
  return `${DIRECTION_REVIEW_PREFIX}${JSON.stringify(state)}`;
}

export function parseDirectionReviewMessage(text: string): DirectionReviewState | null {
  if (!text.startsWith(DIRECTION_REVIEW_PREFIX)) return null;
  try {
    const parsed = JSON.parse(text.slice(DIRECTION_REVIEW_PREFIX.length));
    if (!isRecord(parsed)) return null;
    if (typeof parsed.question !== "string") return null;
    if (typeof parsed.reviewKey !== "string") return null;
    if (typeof parsed.proposedDirection !== "string") return null;
    if (typeof parsed.directionBasis !== "string") return null;
    const highlight = isRecord(parsed.evidenceHighlight) ? parsed.evidenceHighlight : {};
    return {
      question: parsed.question,
      reviewKey: parsed.reviewKey,
      proposedDirection: parsed.proposedDirection,
      directionBasis: parsed.directionBasis,
      basisExplanation: typeof parsed.basisExplanation === "string" ? parsed.basisExplanation : "",
      evidenceHighlight: {
        source_scope_ids: Array.isArray(highlight.source_scope_ids)
          ? (highlight.source_scope_ids as string[])
          : [],
        matched_object_ids: Array.isArray(highlight.matched_object_ids)
          ? (highlight.matched_object_ids as string[])
          : [],
        paths: Array.isArray(highlight.paths)
          ? (highlight.paths as EvidenceHighlight["paths"])
          : [],
      },
      conversation: Array.isArray(parsed.conversation)
        ? (parsed.conversation as DirectionReviewConversationTurn[])
        : [],
      raw: isRecord(parsed.raw) ? parsed.raw : {},
    };
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
