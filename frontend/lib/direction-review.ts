import type { EvidenceHighlight } from "./grounded-qa-answer.ts";
import type { TurnStep } from "./turn-steps.ts";

export const DIRECTION_REVIEW_PREFIX = "pydexpi:direction-review:";

export type DirectionReviewConversationTurn = {
  question: string;
  answer_text: string;
  evidence_references: string[];
};

export type DirectionReviewItem = {
  reviewKey: string;
  objectId: string;
  proposedDirection: string;
  directionBasis: string;
  basisExplanation: string;
  evidenceHighlight: EvidenceHighlight;
  raw: Record<string, unknown>;
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
  items: DirectionReviewItem[];
  steps?: TurnStep[];
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
    const highlight = readEvidenceHighlight(parsed.evidenceHighlight);
    const rawItems = Array.isArray(parsed.items) ? parsed.items.filter(isRecord) : [];
    const fallbackItem: DirectionReviewItem = {
      reviewKey: parsed.reviewKey,
      objectId: "",
      proposedDirection: parsed.proposedDirection,
      directionBasis: parsed.directionBasis,
      basisExplanation: typeof parsed.basisExplanation === "string" ? parsed.basisExplanation : "",
      evidenceHighlight: highlight,
      raw: {},
    };
    const items = rawItems.map(readDirectionReviewItem).filter((item): item is DirectionReviewItem => item !== null);
    return {
      question: parsed.question,
      reviewKey: parsed.reviewKey,
      proposedDirection: parsed.proposedDirection,
      directionBasis: parsed.directionBasis,
      basisExplanation: typeof parsed.basisExplanation === "string" ? parsed.basisExplanation : "",
      evidenceHighlight: highlight,
      conversation: Array.isArray(parsed.conversation)
        ? (parsed.conversation as DirectionReviewConversationTurn[])
        : [],
      raw: isRecord(parsed.raw) ? parsed.raw : {},
      items: items.length > 0 ? items : [fallbackItem],
      steps: Array.isArray(parsed.steps) ? (parsed.steps as TurnStep[]) : [],
    };
  } catch {
    return null;
  }
}

function readDirectionReviewItem(raw: Record<string, unknown>): DirectionReviewItem | null {
  const reviewKey = typeof raw.reviewKey === "string" ? raw.reviewKey : "";
  const proposedDirection = typeof raw.proposedDirection === "string" ? raw.proposedDirection : "";
  const directionBasis = typeof raw.directionBasis === "string" ? raw.directionBasis : "";
  if (!reviewKey || !proposedDirection || !directionBasis) return null;
  return {
    reviewKey,
    objectId: typeof raw.objectId === "string" ? raw.objectId : "",
    proposedDirection,
    directionBasis,
    basisExplanation: typeof raw.basisExplanation === "string" ? raw.basisExplanation : "",
    evidenceHighlight: readEvidenceHighlight(raw.evidenceHighlight),
    raw: isRecord(raw.raw) ? raw.raw : {},
  };
}

function readEvidenceHighlight(value: unknown): EvidenceHighlight {
  const highlight = isRecord(value) ? value : {};
  return {
    source_scope_ids: Array.isArray(highlight.source_scope_ids)
      ? (highlight.source_scope_ids as string[])
      : [],
    matched_object_ids: Array.isArray(highlight.matched_object_ids)
      ? (highlight.matched_object_ids as string[])
      : [],
    paths: Array.isArray(highlight.paths) ? (highlight.paths as EvidenceHighlight["paths"]) : [],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
