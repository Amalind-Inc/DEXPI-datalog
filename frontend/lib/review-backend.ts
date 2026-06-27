import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { samplePidGraph } from "../components/pid/sample-graph.ts";
import type { PidGraph, PidNode, PrepareResult } from "../components/pid/types.ts";
import {
  serializeGroundedLogicAnswer,
  serializeDatalogConfirmation,
  type DatalogConfirmationState,
} from "./datalog-confirmation.ts";
import {
  parseGroundedQAAnswerMessage,
  serializeGroundedQAAnswer,
  type EvidenceHighlight,
} from "./grounded-qa-answer.ts";
import { serializeDirectionReview } from "./direction-review.ts";

type QAConversationTurn = {
  question: string;
  answer_text: string;
  evidence_references: string[];
};

export type ChatRequest = {
  messages?: Array<{ role: string; content: string }>;
  sessionId?: string;
  selectedNode?: {
    id: string;
    label: string;
    kind: string;
    description: string;
  } | null;
};

export type ChatResult = {
  status?: "answered" | "confirmation_ready" | "confirmation_failed" | "needs_direction_review";
  message: string;
  highlightedNodeIds: string[];
  confirmation?: DatalogConfirmationState;
};

export type DirectionReviewResult = {
  status: "answered";
  message: string;
  highlightedNodeIds: string[];
};

export type ExecuteConfirmedDatalogResult = {
  status: "answered";
  message: string;
  highlightedNodeIds: string[];
};

export class BackendExecutionUnavailableError extends Error {
  constructor() {
    super(
      "Python review backend did not execute the confirmed Datalog query. Start the review API and try Run again.",
    );
    this.name = "BackendExecutionUnavailableError";
  }
}

export class GeneratedDatalogExecutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GeneratedDatalogExecutionError";
  }
}

type PrepareBody = {
  filename?: string;
  content?: string;
};

type BackendFetch = typeof fetch;
type BackendProviderSettings = {
  provider: "openrouter" | "openai" | "anthropic" | "gemini";
  model: string;
  credential: string;
};

export async function prepareReviewSession(
  sessionId: string,
  body: PrepareBody,
  options: BackendOptions = {},
): Promise<PrepareResult> {
  const proxied = await prepareWithPythonBackend(sessionId, body, options);
  if (proxied) return proxied;

  const graph = graphFromXml(body.content ?? "");
  return {
    status: "ready",
    filename: body.filename ?? "plant.xml",
    graph,
    sourceScopeIds: [graph.nodes[0]?.id ?? "pump-101"],
  };
}

export async function answerChatWithReviewBackend(
  body: ChatRequest,
  options: BackendOptions = {},
): Promise<ChatResult> {
  const prompt = body.messages?.at(-1)?.content ?? "";
  const selectedNode = body.selectedNode ?? null;
  const conversation = buildQAConversation(body.messages ?? []);
  const backendAnswer = await runBackendLogicRequest(
    body.sessionId,
    prompt,
    selectedNode?.id,
    conversation,
    options,
  );

  if (backendAnswer) return backendAnswer;

  if (body.sessionId && isDatalogReasoningPrompt(prompt)) {
    return {
      message:
        "Unable to reach the review backend. Make sure the API is running on port 8000 and send your message again.",
      highlightedNodeIds: [],
    };
  }

  const selectedText = selectedNode
    ? `${selectedNode.label} (${selectedNode.kind})`
    : "the currently selected topology scope";
  return {
    message:
      `I am grounding this QA answer in ${selectedText}. ` +
      `Upload a plant XML to replace the sample graph, then select nodes or paths ` +
      `to focus deterministic checks. For this request I would inspect source scope, ` +
      `derive the topology evidence, and return highlighted equipment/path evidence.`,
    highlightedNodeIds: inferHighlights(prompt, selectedNode?.id),
  };
}

export async function executeConfirmedDatalog(
  sessionId: string,
  confirmation: Record<string, unknown>,
  options: BackendOptions = {},
): Promise<ExecuteConfirmedDatalogResult> {
  const answer = await runBackendExecute(sessionId, confirmation, options);
  if (!answer) {
    throw new BackendExecutionUnavailableError();
  }
  const normalized = answer;
  if (normalized.status !== "answered") {
    throw new GeneratedDatalogExecutionError(readExecutionFailureMessage(normalized));
  }
  const highlightedNodeIds = readEvidenceHighlightIds(normalized.evidence_highlight);
  return {
    status: "answered",
    message: serializeGroundedLogicAnswer({
      summary: readAnswerText(normalized),
      rawEvidence: readRawEvidence(normalized),
      highlightedNodeIds,
      raw: normalized,
    }),
    highlightedNodeIds,
  };
}

async function prepareWithPythonBackend(
  sessionId: string,
  body: PrepareBody,
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<PrepareResult | null> {
  if (!baseUrl) return null;

  try {
    const response = await fetcher(`${baseUrl}/api/review/sessions/${sessionId}/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    return {
      status: readStatus(data),
      filename: body.filename ?? "plant.xml",
      graph: readTopology(data),
      sourceScopeIds: readVisibleSourceScopeIds(data.visible_source_scope),
    };
  } catch {
    return null;
  }
}

async function runBackendLogicRequest(
  sessionId: string | undefined,
  prompt: string,
  selectedNodeId: string | undefined,
  conversation: QAConversationTurn[],
  {
    baseUrl = backendBaseUrl(),
    fetcher = fetch,
    providerSettings = readProviderSettingsFromEnv(),
  }: BackendOptions = {},
): Promise<ChatResult | null> {
  if (!baseUrl || !sessionId || prompt.trim() === "") return null;

  try {
    if (selectedNodeId) {
      const scopeResponse = await fetcher(
        `${baseUrl}/api/review/sessions/${sessionId}/source-scope`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_scope_ids: [selectedNodeId] }),
        },
      );
      if (!scopeResponse.ok) return null;
    }

    if (providerSettings) {
      const providerResponse = await fetcher(
        `${baseUrl}/api/review/sessions/${sessionId}/provider-settings`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(providerSettings),
        },
      );
      if (!providerResponse.ok) return null;
    }

    if (conversation.length > 0) {
      return await answerWithGroundedQA(fetcher, baseUrl, sessionId, prompt, conversation);
    }

    const improvement = await postJson(fetcher, {
      url: `${baseUrl}/api/review/sessions/${sessionId}/logic-requests/improve`,
      body: { prompt },
    });
    if (!improvement) return null;

    if (improvement.status !== "refinement_ready") {
      return {
        message: readNonRefinementMessage(improvement),
        highlightedNodeIds: selectedNodeId ? [selectedNodeId] : [],
      };
    }

    const route = improvement.route;
    if (isRecord(route) && route.kind === "topology_logic") {
      return await answerWithGroundedQA(fetcher, baseUrl, sessionId, prompt, conversation);
    }

    const confirmation = await postJson(fetcher, {
      url: `${baseUrl}/api/review/sessions/${sessionId}/logic-requests/confirm`,
      body: { improvement },
    });
    if (!confirmation || confirmation.status !== "confirmation_ready") {
      return null;
    }

    if (confirmation.status !== "confirmation_ready") {
      return {
        status: "confirmation_failed",
        message: readConfirmationFailureMessage(confirmation),
        highlightedNodeIds: [],
      };
    }

    return confirmationReadyResult(confirmation);
  } catch {
    return null;
  }
}

async function answerWithGroundedQA(
  fetcher: BackendFetch,
  baseUrl: string,
  sessionId: string,
  question: string,
  conversation: QAConversationTurn[],
): Promise<ChatResult | null> {
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/qa-turns`,
    body: conversation.length > 0 ? { question, conversation } : { question },
  });
  if (!result) return null;

  if (result.status === "needs_direction_review") {
    return directionReviewResult(question, conversation, result);
  }

  const answerText = typeof result.answer_text === "string" ? result.answer_text : "";
  const evidenceReferences = readStringArray(result.evidence_references);
  const interpretedObjectIds = readStringArray(result.interpreted_object_ids);
  const highlightRaw = result.evidence_highlight;
  const highlight = readEvidenceHighlight(highlightRaw);
  const highlightedNodeIds = readEvidenceHighlightIds(highlightRaw);

  return {
    status: "answered",
    message: serializeGroundedQAAnswer({
      answerText,
      evidenceReferences,
      interpretedObjectIds,
      evidenceHighlight: highlight,
      raw: result,
    }),
    highlightedNodeIds,
  };
}

function directionReviewResult(
  question: string,
  conversation: QAConversationTurn[],
  result: Record<string, unknown>,
): ChatResult {
  const review = isRecord(result.direction_review) ? result.direction_review : {};
  const highlight = readEvidenceHighlight(review.evidence_highlight);
  return {
    status: "needs_direction_review",
    message: serializeDirectionReview({
      question,
      reviewKey: typeof review.review_key === "string" ? review.review_key : "",
      proposedDirection:
        typeof review.proposed_direction === "string" ? review.proposed_direction : "",
      directionBasis: typeof review.direction_basis === "string" ? review.direction_basis : "",
      basisExplanation:
        typeof review.basis_explanation === "string" ? review.basis_explanation : "",
      evidenceHighlight: highlight,
      conversation,
      raw: result,
    }),
    highlightedNodeIds: readEvidenceHighlightIds(review.evidence_highlight),
  };
}

export async function submitDirectionReview(
  sessionId: string,
  params: {
    question: string;
    decision: "confirm" | "reverse" | "unknown";
    reviewKey: string;
    conversation?: QAConversationTurn[];
  },
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<DirectionReviewResult> {
  const body: Record<string, unknown> = {
    question: params.question,
    decision: params.decision,
    review_key: params.reviewKey,
  };
  if (params.conversation && params.conversation.length > 0) {
    body.conversation = params.conversation;
  }
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/direction-reviews`,
    body,
  });
  if (!result) {
    throw new Error("The review backend did not resume the question after direction review.");
  }
  const answerText = typeof result.answer_text === "string" ? result.answer_text : "";
  const evidenceReferences = readStringArray(result.evidence_references);
  const interpretedObjectIds = readStringArray(result.interpreted_object_ids);
  const highlight = readEvidenceHighlight(result.evidence_highlight);
  return {
    status: "answered",
    message: serializeGroundedQAAnswer({
      answerText,
      evidenceReferences,
      interpretedObjectIds,
      evidenceHighlight: highlight,
      raw: result,
    }),
    highlightedNodeIds: readEvidenceHighlightIds(result.evidence_highlight),
  };
}

function buildQAConversation(
  messages: Array<{ role: string; content: string }>,
): QAConversationTurn[] {
  const turns: QAConversationTurn[] = [];
  // Pair each assistant QA answer with the user question that preceded it,
  // excluding the final (current) user message.
  for (let index = 0; index < messages.length - 1; index += 1) {
    const message = messages[index];
    if (message.role !== "assistant") continue;
    const parsed = parseGroundedQAAnswerMessage(message.content);
    if (!parsed) continue;
    let question = "";
    for (let back = index - 1; back >= 0; back -= 1) {
      if (messages[back].role === "user") {
        question = messages[back].content;
        break;
      }
    }
    turns.push({
      question,
      answer_text: parsed.answerText,
      evidence_references: parsed.evidenceReferences,
    });
  }
  return turns;
}

async function runBackendExecute(
  sessionId: string,
  confirmation: Record<string, unknown>,
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<Record<string, unknown> | null> {
  if (!baseUrl || !sessionId) return null;
  try {
    return await postJson(fetcher, {
      url: `${baseUrl}/api/review/sessions/${sessionId}/logic-requests/execute`,
      body: { confirmation },
    });
  } catch {
    return null;
  }
}

type BackendOptions = {
  baseUrl?: string;
  fetcher?: BackendFetch;
  providerSettings?: BackendProviderSettings | null;
};

async function postJson(
  fetcher: BackendFetch,
  { url, body }: { url: string; body: object },
): Promise<Record<string, unknown> | null> {
  const response = await fetcher(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) return null;
  return (await response.json()) as Record<string, unknown>;
}

function graphFromXml(content: string): PidGraph {
  const graph = structuredClone(samplePidGraph);
  const labels = Array.from(content.matchAll(/\b(P-\d+|V-\d+|FT-\d+)\b/gi)).map((match) =>
    match[1].toUpperCase(),
  );
  if (labels.length === 0) return graph;

  return {
    ...graph,
    nodes: graph.nodes.map((node) =>
      labels.includes(node.label) ? { ...node, status: "selected" } : node,
    ),
  };
}

function readStatus(data: Record<string, unknown>) {
  return data.status === "failed" ? "failed" : "ready";
}

function readTopology(data: Record<string, unknown>): PidGraph {
  const topology = (data.topology_view ?? data.topology ?? data) as {
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  };
  const nodes =
    topology.nodes?.map((node): PidNode => {
      const id = String(node.id ?? node.label ?? "node");
      const label = String(node.tag_name ?? node.label ?? id);
      return {
        id,
        label,
        kind: classifyNode(label),
        description: `Prepared topology object ${label}.`,
        status: "normal",
      };
    }) ?? samplePidGraph.nodes;
  const edges =
    topology.edges?.map((edge, index) => ({
      id: String(edge.id ?? `edge-${index}`),
      source: String(edge.source_id ?? edge.source ?? ""),
      target: String(edge.target_id ?? edge.target ?? ""),
      label: String(edge.relationship ?? edge.label ?? "connected to"),
    })) ?? samplePidGraph.edges;
  return { nodes, edges };
}

function readVisibleSourceScopeIds(value: unknown) {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }
  if (isRecord(value) && Array.isArray(value.ids)) {
    return value.ids.filter((item): item is string => typeof item === "string");
  }
  return [];
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

function readEvidenceHighlight(value: unknown): EvidenceHighlight {
  if (!isRecord(value)) {
    return { source_scope_ids: [], matched_object_ids: [], paths: [] };
  }
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

function readPathIds(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((path) => {
    if (!isRecord(path)) return [];
    return [...readStringArray(path.node_ids), ...readStringArray(path.edge_ids)];
  });
}

function confirmationReadyResult(confirmation: Record<string, unknown>): ChatResult {
  const state = readConfirmationState(confirmation);
  return {
    status: "confirmation_ready",
    message: serializeDatalogConfirmation(state),
    highlightedNodeIds: [],
    confirmation: state,
  };
}

function readConfirmationState(confirmation: Record<string, unknown>): DatalogConfirmationState {
  return {
    plainLanguageMeaning: readPlainLanguageMeaning(confirmation),
    generatedDatalog: readGeneratedDatalog(confirmation),
    validationStatus: readValidationStatus(confirmation),
    allowedActions: readAllowedActions(confirmation),
    raw: confirmation,
  };
}

function readPlainLanguageMeaning(confirmation: Record<string, unknown>) {
  const restatement = confirmation.restatement;
  if (isRecord(restatement) && typeof restatement.text === "string") {
    return restatement.text;
  }
  const request = confirmation.request;
  if (isRecord(request) && typeof request.prompt === "string") {
    return request.prompt;
  }
  return "Review generated Datalog before execution.";
}

function readGeneratedDatalog(confirmation: Record<string, unknown>) {
  const generatedLogic = confirmation.generated_logic;
  if (isRecord(generatedLogic) && typeof generatedLogic.content === "string") {
    return generatedLogic.content;
  }
  return "";
}

function readValidationStatus(confirmation: Record<string, unknown>) {
  const validation = confirmation.validation;
  if (isRecord(validation) && typeof validation.status === "string") {
    return validation.status;
  }
  return "pending_safety_validation";
}

function readAllowedActions(confirmation: Record<string, unknown>) {
  const actions = readStringArray(confirmation.allowed_actions);
  return actions.length > 0 ? actions : ["run", "revise", "cancel"];
}

function readConfirmationFailureMessage(confirmation: Record<string, unknown>) {
  const diagnostics = confirmation.diagnostics;
  if (Array.isArray(diagnostics) && isRecord(diagnostics[0])) {
    const message = diagnostics[0].message;
    if (typeof message === "string") return message;
  }
  return "The backend could not prepare a Datalog confirmation for this prompt.";
}

function readExecutionFailureMessage(answer: Record<string, unknown>) {
  const diagnostics = answer.diagnostics;
  if (Array.isArray(diagnostics) && isRecord(diagnostics[0])) {
    const message = diagnostics[0].message;
    if (typeof message === "string") return message;
  }
  const summary = answer.summary;
  if (isRecord(summary) && typeof summary.text === "string") {
    return summary.text;
  }
  return "The backend rejected the generated Datalog before execution.";
}

function isDatalogReasoningPrompt(prompt: string) {
  const normalized = prompt.toLowerCase();
  return ["downstream", "reachable", "connected", "source"].some((term) =>
    normalized.includes(term),
  );
}

function readStringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function readAnswerText(answer: Record<string, unknown>) {
  const summary = answer.summary;
  if (isRecord(summary) && typeof summary.text === "string") {
    return summary.text;
  }
  return "Deterministic execution completed, but the backend response did not include a summary.";
}

function readRawEvidence(answer: Record<string, unknown>): Record<string, unknown> {
  const evidence = answer.evidence;
  if (isRecord(evidence)) return evidence;
  return { items: [] };
}

function readNonRefinementMessage(improvement: Record<string, unknown>) {
  const diagnostics = improvement.diagnostics;
  if (Array.isArray(diagnostics) && isRecord(diagnostics[0])) {
    const message = diagnostics[0].message;
    if (typeof message === "string") return message;
  }
  const route = improvement.route;
  if (isRecord(route) && typeof route.kind === "string") {
    return `This request was routed as ${route.kind}; no deterministic topology refinement was created.`;
  }
  return "The backend did not create a reviewable topology refinement for this prompt.";
}

function classifyNode(label: string) {
  if (label.startsWith("P-")) return "Pump";
  if (label.startsWith("V-")) return "Valve";
  if (label.startsWith("FT-")) return "Instrument";
  if (label.startsWith("L-")) return "Line";
  return "Equipment";
}

function inferHighlights(prompt: string, fallbackId: string | undefined) {
  const normalized = prompt.toLowerCase();
  const highlights = new Set<string>();
  if (normalized.includes("p-101") || normalized.includes("pump")) {
    highlights.add("pump-101");
  }
  if (normalized.includes("v-102") || normalized.includes("valve")) {
    highlights.add("valve-102");
  }
  if (normalized.includes("ft-101") || normalized.includes("flow")) {
    highlights.add("flow-transmitter-101");
  }
  if (fallbackId) highlights.add(fallbackId);
  return Array.from(highlights);
}

function readProviderSettingsFromEnv(): BackendProviderSettings | null {
  const openrouterKey = readEnvValue("OPENROUTER_API_KEY");
  const openaiKey = readEnvValue("OPENAI_API_KEY");
  const anthropicKey = readEnvValue("ANTHROPIC_API_KEY");
  const geminiKey = readEnvValue("GEMINI_API_KEY");

  if (openrouterKey) {
    return {
      provider: "openrouter",
      model: readEnvValue("OPENROUTER_MODEL") ?? "openrouter/owl-alpha",
      credential: openrouterKey,
    };
  }
  if (openaiKey) {
    return {
      provider: "openai",
      model: readEnvValue("OPENAI_MODEL") ?? "gpt-4.1",
      credential: openaiKey,
    };
  }
  if (anthropicKey) {
    return {
      provider: "anthropic",
      model: readEnvValue("ANTHROPIC_MODEL") ?? "claude-sonnet-4",
      credential: anthropicKey,
    };
  }
  if (geminiKey) {
    return {
      provider: "gemini",
      model: readEnvValue("GEMINI_MODEL") ?? "gemini-2.5-pro",
      credential: geminiKey,
    };
  }
  return null;
}

function backendBaseUrl() {
  return readEnvValue("PYDEXPI_REVIEW_API_URL") ?? "http://127.0.0.1:8000";
}

function readEnvValue(key: string): string | undefined {
  const direct = process.env[key];
  if (direct) return direct;

  for (const filePath of [
    resolve(process.cwd(), ".env.local"),
    resolve(process.cwd(), ".env"),
    resolve(process.cwd(), "..", ".env"),
  ]) {
    const value = readDotEnvValue(filePath, key);
    if (value) return value;
  }
  return undefined;
}

function readDotEnvValue(filePath: string, key: string): string | undefined {
  if (!existsSync(filePath)) return undefined;
  const prefix = `${key}=`;
  for (const rawLine of readFileSync(filePath, "utf-8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#") || !line.startsWith(prefix)) continue;
    return stripEnvQuotes(line.slice(prefix.length).trim());
  }
  return undefined;
}

function stripEnvQuotes(value: string) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
