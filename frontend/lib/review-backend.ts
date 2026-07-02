import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { samplePidGraph } from "../components/pid/sample-graph.ts";
import type {
  PidGraph,
  PidNode,
  PidNodeKind,
  PidView,
  PrepareResult,
} from "../components/pid/types.ts";

const EMPTY_PID_VIEW: PidView = { units: [], lines: [], hiddenTopologyIds: [] };
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
  status: "answered" | "canceled";
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
  provider: "openrouter" | "openai" | "anthropic" | "gemini" | "ollama";
  model: string;
  credential: string;
  base_url?: string;
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
    pidView: EMPTY_PID_VIEW,
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
  if (body.sessionId && isBundledPumpCheckCommand(prompt)) {
    const ruleResult = await runBundledPumpCheck(body.sessionId, options);
    if (ruleResult) return ruleResult;
  }
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

function isBundledPumpCheckCommand(prompt: string) {
  return prompt.trim().toLowerCase() === "run the bundled pump discharge check.";
}

async function runBundledPumpCheck(
  sessionId: string,
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions,
): Promise<ChatResult | null> {
  if (!baseUrl) return null;
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/rule-pack-results`,
    body: {
      pack_id: "demo-process-safety",
      rule_id: "pump_discharge_check_valve",
    },
  });
  if (!result || result.status !== "answered") return null;

  const pack = isRecord(result.pack) ? result.pack : {};
  const summary = isRecord(result.summary) ? result.summary : {};
  const summaryText = typeof summary.text === "string" ? summary.text : readAnswerText(result);
  const trustNotice = typeof pack.trust_notice === "string" ? pack.trust_notice : "";
  const highlightedNodeIds = readEvidenceHighlightIds(result.evidence_highlight);
  return {
    status: "answered",
    message: serializeGroundedLogicAnswer({
      summary: [summaryText, trustNotice].filter(Boolean).join(" "),
      rawEvidence: readRawEvidence(result),
      highlightedNodeIds,
      raw: result,
    }),
    highlightedNodeIds,
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
      pidView: readPidView(data),
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

    // When a tool-calling model is configured, the agentic QA harness handles
    // everything: open conversation, follow-ups, and grounded topology questions.
    // The model decides when to call topology tools. The keyword router below is
    // only a fallback for the no-model (deterministic stub) case.
    if (providerSettings || conversation.length > 0) {
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

  if (result.status === "needs_datalog_confirmation") {
    return temporaryDatalogConfirmationResult(result);
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

export async function submitTemporaryDatalogReview(
  sessionId: string,
  params: {
    question: string;
    decision: "confirm" | "cancel";
    proposalResult: Record<string, unknown>;
  },
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<ExecuteConfirmedDatalogResult> {
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/temporary-datalog-reviews`,
    body: {
      question: params.question,
      decision: params.decision,
      proposal_result: params.proposalResult,
    },
  });
  if (!result) {
    throw new BackendExecutionUnavailableError();
  }
  if (result.status === "canceled") {
    return {
      status: "canceled",
      message: "Canceled. No Datalog query was executed.",
      highlightedNodeIds: [],
    };
  }
  if (result.status !== "answered") {
    throw new GeneratedDatalogExecutionError(readExecutionFailureMessage(result));
  }
  const highlightedNodeIds = readEvidenceHighlightIds(result.evidence_highlight);
  return {
    status: "answered",
    message: serializeGroundedLogicAnswer({
      summary: readAnswerText(result),
      rawEvidence: readRawEvidence(result),
      highlightedNodeIds,
      raw: result,
    }),
    highlightedNodeIds,
  };
}

function temporaryDatalogConfirmationResult(result: Record<string, unknown>): ChatResult {
  const confirmation = result.datalog_confirmation;
  const confirmationRecord = isRecord(confirmation) ? confirmation : {};
  return {
    status: "confirmation_ready",
    message: serializeDatalogConfirmation({
      plainLanguageMeaning: readTemporaryDatalogMeaning(confirmationRecord),
      generatedDatalog: readTemporaryGeneratedDatalog(confirmationRecord),
      validationStatus: readTemporaryValidationStatus(confirmationRecord),
      allowedActions: readStringArray(confirmationRecord.allowed_actions),
      raw: {
        confirmation_kind: "temporary_datalog",
        ...result,
      },
    }),
    highlightedNodeIds: [],
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
      // Prefer the engineer-facing identifier (tag / line / qualified nozzle).
      const label = String(node.display_name ?? node.tag_name ?? node.label ?? id);
      const className = String(node.class_name ?? node.label ?? "");
      const category = String(node.category ?? "");
      const description =
        typeof node.description === "string" && node.description
          ? node.description
          : `${className || "Topology object"} ${label}`.trim();
      return {
        id,
        label,
        kind: classifyKind(category, label),
        description,
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

function readPidView(data: Record<string, unknown>): PidView {
  const source = (data.topology_view ?? data.topology ?? data) as Record<string, unknown>;
  const raw = (source.pid_view ?? data.pid_view) as Record<string, unknown> | undefined;
  if (!raw || typeof raw !== "object") return EMPTY_PID_VIEW;
  const units = Array.isArray(raw.units)
    ? raw.units.map((u) => {
        const unit = u as Record<string, unknown>;
        return {
          id: String(unit.id ?? ""),
          label: String(unit.label ?? unit.id ?? ""),
          className: String(unit.class_name ?? ""),
          category: String(unit.category ?? ""),
          description: String(unit.description ?? ""),
          ports: Array.isArray(unit.ports)
            ? unit.ports.map((p) => {
                const port = p as Record<string, unknown>;
                return { id: String(port.id ?? ""), label: String(port.label ?? port.id ?? "") };
              })
            : [],
        };
      })
    : [];
  const lines = Array.isArray(raw.lines)
    ? raw.lines.map((l) => {
        const line = l as Record<string, unknown>;
        return {
          id: String(line.id ?? ""),
          label: String(line.label ?? ""),
          sourceUnit: line.source_unit ? String(line.source_unit) : null,
          targetUnit: line.target_unit ? String(line.target_unit) : null,
          sourcePort: line.source_port ? String(line.source_port) : null,
          targetPort: line.target_port ? String(line.target_port) : null,
          memberTopologyIds: Array.isArray(line.member_topology_ids)
            ? line.member_topology_ids.map((m) => String(m))
            : [],
        };
      })
    : [];
  const hiddenTopologyIds = Array.isArray(raw.hidden_topology_ids)
    ? raw.hidden_topology_ids.map((h) => String(h))
    : [];
  return { units, lines, hiddenTopologyIds };
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

function readTemporaryDatalogMeaning(confirmation: Record<string, unknown>) {
  const value = confirmation.plain_language_meaning;
  if (typeof value === "string") return value;
  const proposal = confirmation.proposal;
  if (isRecord(proposal) && typeof proposal.formal_restatement === "string") {
    return proposal.formal_restatement;
  }
  return "Review generated Datalog before execution.";
}

function readTemporaryGeneratedDatalog(confirmation: Record<string, unknown>) {
  const value = confirmation.generated_datalog;
  if (typeof value === "string") return value;
  const proposal = confirmation.proposal;
  if (isRecord(proposal) && typeof proposal.generated_datalog === "string") {
    return proposal.generated_datalog;
  }
  return "";
}

function readTemporaryValidationStatus(confirmation: Record<string, unknown>) {
  const validation = confirmation.validation;
  if (isRecord(validation) && typeof validation.status === "string") {
    return validation.status;
  }
  return "pending_safety_validation";
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

function classifyNode(label: string): PidNodeKind {
  if (label.startsWith("P-")) return "Pump";
  if (label.startsWith("V-")) return "Valve";
  if (label.startsWith("FT-")) return "Instrument";
  if (label.startsWith("L-") || label.startsWith("Line ")) return "Line";
  return "Equipment";
}

// Map the backend topology category to a graph node kind, falling back to
// label-prefix heuristics for equipment tags (P-4713 -> Pump).
function classifyKind(category: string, label: string): PidNodeKind {
  if (category === "line") return "Line";
  if (category === "equipment") return classifyNode(label);
  if (category === "nozzle" || category === "connection" || category === "piping") {
    return "Equipment";
  }
  return classifyNode(label);
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
  // Explicit escape hatch for deterministic e2e: force the stub provider even
  // when a real key is present in the environment or a .env file.
  if (process.env.PYDEXPI_DISABLE_BYOK) return null;

  const ollamaModel = readEnvValue("OLLAMA_MODEL");
  const openrouterKey = readEnvValue("OPENROUTER_API_KEY");
  const openaiKey = readEnvValue("OPENAI_API_KEY");
  const anthropicKey = readEnvValue("ANTHROPIC_API_KEY");
  const geminiKey = readEnvValue("GEMINI_API_KEY");

  if (ollamaModel) {
    return {
      provider: "ollama",
      model: ollamaModel,
      credential: "",
      base_url: readEnvValue("OLLAMA_BASE_URL") ?? "http://localhost:11434/v1",
    };
  }
  if (openrouterKey) {
    return {
      provider: "openrouter",
      model: readEnvValue("OPENROUTER_MODEL") ?? "anthropic/claude-sonnet-4",
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

export async function startTurnOnBackend(
  sessionId: string,
  body: {
    question: string;
    request_id: string;
    conversation?: unknown[];
    selected_node_id?: string;
  },
  {
    baseUrl = backendBaseUrl(),
    fetcher = fetch,
    providerSettings = readProviderSettingsFromEnv(),
  }: BackendOptions = {},
): Promise<Record<string, unknown>> {
  // Pin the selected topology scope. This is only sent when the caller
  // resolved a real node (selectedNode?.id), so failures are real backend
  // errors and must surface rather than be swallowed.
  if (body.selected_node_id) {
    const scopeResponse = await fetcher(
      `${baseUrl}/api/review/sessions/${sessionId}/source-scope`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_scope_ids: [body.selected_node_id] }),
      },
    );
    if (!scopeResponse.ok) throw new Error("source-scope update failed");
  }
  // Apply env-configured provider settings. Skip obviously-test credentials
  // (sk-test sentinel) so the backend uses its scripted provider, which
  // avoids real LLM API calls during automated testing.
  const isTestCredential = providerSettings?.credential
    .toLowerCase()
    .startsWith("sk-test");
  if (providerSettings && !isTestCredential) {
    const providerResponse = await fetcher(
      `${baseUrl}/api/review/sessions/${sessionId}/provider-settings`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(providerSettings),
      },
    );
    if (!providerResponse.ok) throw new Error("provider-settings update failed");
  }
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/turns`,
    body: {
      question: body.question,
      request_id: body.request_id,
      conversation: body.conversation,
    },
  });
  if (!result) throw new Error("turn start failed");
  return result;
}

export async function getTurnFromBackend(
  sessionId: string,
  turnId: string,
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<{ turn: Record<string, unknown> | null; status: number }> {
  const res = await fetcher(`${baseUrl}/api/review/sessions/${sessionId}/turns/${turnId}`);
  if (!res.ok) return { turn: null, status: res.status };
  return { turn: (await res.json()) as Record<string, unknown>, status: res.status };
}

export async function cancelTurnOnBackend(
  sessionId: string,
  turnId: string,
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<Record<string, unknown>> {
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/turns/${turnId}/cancel`,
    body: {},
  });
  if (!result) throw new Error("turn cancel failed");
  return result;
}

export async function resumeDirectionReviewOnBackend(
  sessionId: string,
  turnId: string,
  body: { decision: string; review_key: string },
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<Record<string, unknown>> {
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/turns/${turnId}/direction-review`,
    body,
  });
  if (!result) throw new Error("direction-review resume failed");
  return result;
}

export async function resumeDatalogReviewOnBackend(
  sessionId: string,
  turnId: string,
  body: { decision: string; proposal_result: unknown },
  { baseUrl = backendBaseUrl(), fetcher = fetch }: BackendOptions = {},
): Promise<Record<string, unknown>> {
  const result = await postJson(fetcher, {
    url: `${baseUrl}/api/review/sessions/${sessionId}/turns/${turnId}/datalog-review`,
    body,
  });
  if (!result) throw new Error("datalog-review resume failed");
  return result;
}
