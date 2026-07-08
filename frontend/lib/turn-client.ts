import { serializeGroundedQAAnswer } from "./grounded-qa-answer.ts";
import { serializeDirectionReview } from "./direction-review.ts";
import {
  serializeDatalogConfirmation,
  serializeGroundedLogicAnswer,
} from "./datalog-confirmation.ts";
import { deriveTurnSteps } from "./turn-steps.ts";

export type TurnEvent = { sequence: number; type: string; data: Record<string, unknown> };
export type TurnState = {
  turn_id: string;
  session_id: string;
  status: string;
  events: TurnEvent[];
  result?: Record<string, unknown>;
  question: string;
  request_id: string;
};
export type ReducedTurn =
  | {
      kind: "answered";
      text: string;
      highlightedNodeIds: string[];
      conversationState: unknown[];
      evidenceReferences: string[];
      evidenceHighlight: unknown;
      raw: Record<string, unknown>;
    }
  | { kind: "review-required"; review: Record<string, unknown> }
  | { kind: "canceled" }
  | { kind: "failed"; message: string }
  | { kind: "in-progress" };

type TurnClientOptions = {
  baseUrl?: string;
  fetcher?: typeof fetch;
};

export function reduceTurn(turn: TurnState): ReducedTurn {
  let text = "";
  let evidenceReferences: string[] = [];
  let evidenceHighlight: unknown = {};
  let reviewRequired: Record<string, unknown> | null = null;
  let canceled = false;
  let failureMessage: string | null = null;
  // Seed from the terminal status contract; the completion event corroborates it.
  let completed = turn.status === "completed";

  for (const event of turn.events) {
    if (event.type === "text" && typeof event.data.text === "string") {
      text += event.data.text;
    }
    if (event.type === "evidence") {
      evidenceReferences = readStringArray(event.data.evidence_references);
      evidenceHighlight = event.data.evidence_highlight ?? {};
    }
    if (event.type === "review-required") {
      reviewRequired = isRecord(event.data.review) ? event.data.review : {};
    }
    if (event.type === "cancellation") {
      canceled = true;
    }
    if (event.type === "failure") {
      failureMessage = typeof event.data.message === "string" ? event.data.message : "Turn failed";
    }
    if (event.type === "completion") {
      completed = true;
    }
  }

  // Terminal states win over an earlier review-required event. A resumed turn
  // keeps its original review-required event in the log, then appends the
  // completion after the reviewer decides — the completion must win so the turn
  // renders its grounded answer, not a second (stale) review card.
  if (canceled) return { kind: "canceled" };
  if (failureMessage !== null) return { kind: "failed", message: failureMessage };
  if (reviewRequired !== null && !completed) {
    return { kind: "review-required", review: reviewRequired };
  }
  // A still-active turn with no terminal event yet (bead 2ki.12): the turn
  // is mid-execution, not answered -- fall through to "answered" only once
  // the backend has actually produced a result.
  if (turn.status === "active" && !completed) {
    return { kind: "in-progress" };
  }

  const raw = turn.result ?? {};
  return {
    kind: "answered",
    text,
    highlightedNodeIds: readEvidenceHighlightIds(evidenceHighlight),
    conversationState: Array.isArray(raw.conversation_state) ? raw.conversation_state : [],
    evidenceReferences,
    evidenceHighlight,
    raw,
  };
}

export async function startTurn(
  sessionId: string,
  body: { question: string; requestId: string; conversation?: unknown; selectedNodeId?: string },
  options: TurnClientOptions = {},
): Promise<TurnState> {
  return postTurnJson(
    turnUrl(options.baseUrl, sessionId),
    {
      question: body.question,
      request_id: body.requestId,
      conversation: body.conversation,
      selected_node_id: body.selectedNodeId,
    },
    options.fetcher,
  );
}

/** SHA-256 hex digest via Web Crypto (browser and Node compatible). */
export async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Compute the deterministic turn_id the backend derives in
 * TurnLifecycleStore (sha256(`${sessionId}\n${requestId}`).hexdigest()[:20]).
 * Lets the client know the turn_id up front — before startTurn() resolves —
 * so an active turn can be persisted and recovered via getTurn() if the page
 * is refreshed while the request is still in flight.
 */
export async function computeTurnId(sessionId: string, requestId: string): Promise<string> {
  return (await sha256Hex(`${sessionId}\n${requestId}`)).slice(0, 20);
}

export async function getTurn(
  sessionId: string,
  turnId: string,
  options: TurnClientOptions = {},
): Promise<TurnState> {
  return fetchTurnJson(turnUrl(options.baseUrl, sessionId, turnId), options.fetcher);
}

export async function cancelTurn(
  sessionId: string,
  turnId: string,
  options: TurnClientOptions = {},
): Promise<TurnState> {
  return postTurnJson(turnUrl(options.baseUrl, sessionId, turnId, "cancel"), {}, options.fetcher);
}

export async function resumeDirectionReview(
  sessionId: string,
  turnId: string,
  body:
    | { decision: string; reviewKey: string }
    | { directionReviews: Array<{ decision: string; reviewKey: string }> },
  options: TurnClientOptions = {},
): Promise<TurnState> {
  const payload = "directionReviews" in body
    ? {
        direction_reviews: body.directionReviews.map((item) => ({
          decision: item.decision,
          review_key: item.reviewKey,
        })),
      }
    : { decision: body.decision, review_key: body.reviewKey };
  return postTurnJson(
    turnUrl(options.baseUrl, sessionId, turnId, "direction-review"),
    payload,
    options.fetcher,
  );
}

export async function resumeDatalogReview(
  sessionId: string,
  turnId: string,
  body: { decision: string; proposalResult: unknown },
  options: TurnClientOptions = {},
): Promise<TurnState> {
  return postTurnJson(
    turnUrl(options.baseUrl, sessionId, turnId, "datalog-review"),
    { decision: body.decision, proposal_result: body.proposalResult },
    options.fetcher,
  );
}

async function postTurnJson(
  url: string,
  body: object,
  fetcher: typeof fetch = fetch,
): Promise<TurnState> {
  const response = await fetcher(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readTurnResponse(response);
}

async function fetchTurnJson(url: string, fetcher: typeof fetch = fetch): Promise<TurnState> {
  const response = await fetcher(url);
  return readTurnResponse(response);
}

/** Turn API failure carrying the HTTP status so callers can tell a
 * definitive "turn not found" (404) from transient backend errors. */
export class TurnRequestError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Turn request failed with status ${status}`);
    this.status = status;
  }
}

async function readTurnResponse(response: Response): Promise<TurnState> {
  if (!response.ok) {
    throw new TurnRequestError(response.status);
  }
  return (await response.json()) as TurnState;
}

function turnUrl(baseUrl = "", sessionId: string, turnId?: string, action?: string) {
  const parts = [
    "api",
    "review",
    "sessions",
    sessionId,
    "turns",
    ...(turnId ? [turnId] : []),
    ...(action ? [action] : []),
  ];
  return `${baseUrl}${pathFromParts(parts)}`;
}

function pathFromParts(parts: string[]) {
  return `/${parts.map(encodeURIComponent).join("/")}`;
}

function readEvidenceHighlightIds(value: unknown) {
  if (!isRecord(value)) return [];
  return Array.from(
    new Set([
      ...readStringArray(value.source_scope_ids),
      ...readStringArray(value.matched_object_ids),
      ...readPathIds(value.paths),
    ]),
  );
}

function readPathIds(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((path) => {
    if (!isRecord(path)) return [];
    return [...readStringArray(path.node_ids), ...readStringArray(path.edge_ids)];
  });
}

function readStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

// ---------------------------------------------------------------------------
// Shared message helper — used by both the runtime provider and review cards.
// Routes are pure TurnState proxies; this is the single place that converts a
// reduced turn into the assistant-ui message shape. The turn_id/session_id
// are embedded into the review dict so cards can resume the exact turn that
// paused, without a separate prop-drilling chain.
// ---------------------------------------------------------------------------

export type TurnMessage = {
  status: string;
  message: string;
  highlightedNodeIds: string[];
};

/** Merge turn identity into a review dict so a card can resume the right turn. */
function withTurnIdentity(review: Record<string, unknown>, turn: TurnState): Record<string, unknown> {
  return { ...review, __turn_id: turn.turn_id, __session_id: turn.session_id };
}

/** Read the {turnId, sessionId} embedded by withTurnIdentity (undefined if absent). */
export function readTurnIdentity(raw: Record<string, unknown>): {
  turnId: string | undefined;
  sessionId: string | undefined;
} {
  return {
    turnId: typeof raw.__turn_id === "string" ? raw.__turn_id : undefined,
    sessionId: typeof raw.__session_id === "string" ? raw.__session_id : undefined,
  };
}

function readEvidenceHighlight(value: unknown) {
  if (!isRecord(value)) return { source_scope_ids: [], matched_object_ids: [], paths: [] };
  return {
    source_scope_ids: readStringArray(value.source_scope_ids),
    matched_object_ids: readStringArray(value.matched_object_ids),
    paths: Array.isArray(value.paths)
      ? value.paths.filter(isRecord).map((p) => ({
          id: typeof p.id === "string" ? p.id : "",
          node_ids: readStringArray(p.node_ids),
          edge_ids: readStringArray(p.edge_ids),
        }))
      : [],
  };
}

/** Convert a completed turn into the assistant-ui message shape, dispatching
 * on the reduced kind. Review-required turns are tagged with turn identity so
 * DirectionReviewCard/DatalogConfirmationCard can resume via the turn-scoped
 * endpoints rather than the legacy session-scoped ones. */
export function turnToMessage(turn: TurnState): TurnMessage {
  const reduced = reduceTurn(turn);
  const steps = deriveTurnSteps(turn, reduced);

  if (reduced.kind === "in-progress") {
    // turnToMessage is only ever meant to be called on a resolved turn; the
    // in-progress placeholder is built directly from deriveTurnSteps by the
    // streaming poll loop (pid-runtime-provider.tsx), not through here.
    return { status: "active", message: "", highlightedNodeIds: [] };
  }
  if (reduced.kind === "canceled") {
    return { status: "canceled", message: "The turn was canceled.", highlightedNodeIds: [] };
  }
  if (reduced.kind === "failed") {
    return { status: "failed", message: reduced.message, highlightedNodeIds: [] };
  }
  if (reduced.kind === "review-required") {
    const review = reduced.review;
    if (review.status === "needs_direction_review") {
      const directionReview = isRecord(review.direction_review) ? review.direction_review : {};
      const rawItems = Array.isArray(review.direction_reviews)
        ? review.direction_reviews.filter(isRecord)
        : [directionReview];
      const items = rawItems.map((item) => ({
        reviewKey: typeof item.review_key === "string" ? item.review_key : "",
        objectId: typeof item.object_id === "string" ? item.object_id : "",
        proposedDirection:
          typeof item.proposed_direction === "string" ? item.proposed_direction : "",
        directionBasis: typeof item.direction_basis === "string" ? item.direction_basis : "",
        basisExplanation:
          typeof item.basis_explanation === "string" ? item.basis_explanation : "",
        evidenceHighlight: readEvidenceHighlight(item.evidence_highlight),
        raw: item,
      }));
      const highlight = readEvidenceHighlight(directionReview.evidence_highlight);
      return {
        status: "needs_direction_review",
        message: serializeDirectionReview({
          question: typeof review.question === "string" ? review.question : turn.question,
          reviewKey: typeof directionReview.review_key === "string" ? directionReview.review_key : "",
          proposedDirection:
            typeof directionReview.proposed_direction === "string"
              ? directionReview.proposed_direction
              : "",
          directionBasis:
            typeof directionReview.direction_basis === "string" ? directionReview.direction_basis : "",
          basisExplanation:
            typeof directionReview.basis_explanation === "string"
              ? directionReview.basis_explanation
              : "",
          evidenceHighlight: highlight,
          conversation: [],
          raw: withTurnIdentity(review, turn),
          items,
          steps,
        }),
        highlightedNodeIds: readEvidenceHighlightIds(review.direction_reviews ?? directionReview.evidence_highlight),
      };
    }
    const confirmation = isRecord(review.datalog_confirmation) ? review.datalog_confirmation : {};
    const proposal = isRecord(confirmation.proposal) ? confirmation.proposal : {};
    const validation = isRecord(confirmation.validation) ? confirmation.validation : {};
    return {
      status: "needs_datalog_confirmation",
      message: serializeDatalogConfirmation({
        plainLanguageMeaning:
          typeof confirmation.plain_language_meaning === "string"
            ? confirmation.plain_language_meaning
            : typeof proposal.formal_restatement === "string"
              ? proposal.formal_restatement
              : "Review generated Datalog before execution.",
        generatedDatalog:
          typeof confirmation.generated_datalog === "string"
            ? confirmation.generated_datalog
            : typeof proposal.generated_datalog === "string"
              ? proposal.generated_datalog
              : "",
        validationStatus:
          typeof validation.status === "string" ? validation.status : "pending_safety_validation",
        allowedActions: readStringArray(confirmation.allowed_actions),
        raw: withTurnIdentity({ confirmation_kind: "temporary_datalog", ...review }, turn),
        steps,
      }),
      highlightedNodeIds: [],
    };
  }

  // Rule-pack executions (e.g. the bundled pump discharge check) render as
  // grounded logic answers with inspectable raw evidence, not QA answers.
  const resultArtifact = isRecord(reduced.raw.result_artifact) ? reduced.raw.result_artifact : {};
  if (resultArtifact.kind === "rule_pack_result") {
    const pack = isRecord(reduced.raw.pack) ? reduced.raw.pack : {};
    const summary = isRecord(reduced.raw.summary) ? reduced.raw.summary : {};
    const summaryText = typeof summary.text === "string" ? summary.text : reduced.text;
    const trustNotice = typeof pack.trust_notice === "string" ? pack.trust_notice : "";
    const evidence = isRecord(reduced.raw.evidence) ? reduced.raw.evidence : {};
    return {
      status: "answered",
      message: serializeGroundedLogicAnswer({
        summary: [summaryText, trustNotice].filter(Boolean).join(" "),
        rawEvidence: evidence,
        highlightedNodeIds: reduced.highlightedNodeIds,
        raw: reduced.raw,
        steps,
      }),
      highlightedNodeIds: reduced.highlightedNodeIds,
    };
  }

  return {
    status: "answered",
    message: serializeGroundedQAAnswer({
      answerText: reduced.text,
      evidenceReferences: reduced.evidenceReferences,
      interpretedObjectIds: readStringArray(reduced.raw.interpreted_object_ids),
      evidenceHighlight: readEvidenceHighlight(reduced.evidenceHighlight),
      raw: reduced.raw,
      steps,
    }),
    highlightedNodeIds: reduced.highlightedNodeIds,
  };
}
