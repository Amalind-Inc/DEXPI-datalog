import {
  type EvidenceRequest,
  type RuleCheckRequest,
  type RunGovernedPiIsolatedCommand,
} from "./pi-turn-adapter.ts";
import { buildRuleDerivation, type AskDerivation } from "./local-ask-execution.ts";
import { upsertLocalTurn } from "./local-project-manifest.cjs";
import type { PortLogPiSessionCoordinator } from "./pi-session-coordinator.ts";

export type LocalInspectionEvent =
  | { type: "turn_started" }
  | { type: "assistant_text_delta"; text: string }
  | {
      type: "tool_request";
      callId: string;
      tool: string;
      arguments: Record<string, unknown>;
    }
  | { type: "tool_result"; callId: string; tool: string; result: unknown }
  | { type: "turn_completed" }
  | { type: "turn_cancelled" }
  | { type: "turn_failed"; message: string };

type StoredEvent = LocalInspectionEvent & {
  sequence: number;
  timestamp: string;
};

export interface LocalInspectionRecord {
  schemaVersion: 1;
  turnId: string;
  posture: "inspect" | "verify" | "review" | "chat";
  question: string;
  status: "active" | "completed" | "cancelled" | "failed";
  model: { provider: string; id: string };
  startedAt: string;
  completedAt?: string;
  finalText: string;
  evidenceIds: string[];
  deterministicChecks: Record<string, unknown>[];
  events: StoredEvent[];
  route?: "evidence" | "rule" | "universal_rule" | "clarification";
  clarification?: {
    prompt: string;
    choices: Array<{ id: string; label: string; question: string }>;
  };
  derivation?: AskDerivation;
  error?: string;
}

interface TurnRuntime {
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): Promise<void>;
}

interface CreateTurnOptions {
  emit(
    event: Exclude<
      LocalInspectionEvent,
      {
        type: "turn_started" | "turn_completed" | "turn_cancelled" | "turn_failed";
      }
    >,
  ): void;
  getEvidence?: (request: Omit<EvidenceRequest, "signal">) => Promise<unknown>;
  getRuleCheck?: (request: RuleCheckRequest) => Promise<unknown>;
  runIsolatedCommand?: RunGovernedPiIsolatedCommand;
}

type CreateTurn = (options: CreateTurnOptions) => Promise<TurnRuntime>;
export interface RunLocalReviewInspectionOptions {
  projectDirectory?: string;
  turnId: string;
  question: string;
  posture?: "inspect" | "verify" | "review" | "chat";
  model: { provider: string; id: string };
  signal: AbortSignal;
  getEvidence?: (request: Omit<EvidenceRequest, "signal">) => Promise<unknown>;
  getRuleCheck?: (request: RuleCheckRequest) => Promise<unknown>;
  runIsolatedCommand?: RunGovernedPiIsolatedCommand;
  session?: PortLogPiSessionCoordinator;
  createTurn?: CreateTurn;
  agentDir?: string;
  cwd?: string;
  apiKey?: string;
  now?: () => Date;
  onEvent?(event: StoredEvent): void;
}

export type RunLocalDesktopChatOptions = Omit<
  RunLocalReviewInspectionOptions,
  "getEvidence" | "getRuleCheck" | "runIsolatedCommand" | "posture" | "projectDirectory"
>;

export async function runLocalDesktopChat(
  options: RunLocalDesktopChatOptions,
): Promise<LocalInspectionRecord> {
  return runLocalReviewInspection({ ...options, posture: "chat" });
}

export async function runLocalReviewInspection(
  options: RunLocalReviewInspectionOptions,
): Promise<LocalInspectionRecord> {
  const now = options.now ?? (() => new Date());
  const record: LocalInspectionRecord = {
    schemaVersion: 1,
    turnId: options.turnId,
    posture: options.posture ?? "inspect",
    question: options.question,
    status: "active",
    model: options.model,
    startedAt: now().toISOString(),
    finalText: "",
    evidenceIds: [],
    deterministicChecks: [],
    events: [],
  };

  const append = (event: LocalInspectionEvent) => {
    const stored = {
      ...event,
      sequence: record.events.length + 1,
      timestamp: now().toISOString(),
    } as StoredEvent;
    record.events.push(stored);
    options.onEvent?.(stored);
    if (event.type === "assistant_text_delta") record.finalText += event.text;
    if (event.type === "tool_result") {
      record.evidenceIds = unique([...record.evidenceIds, ...readEvidenceIds(event.result)]);
      const checks = readDeterministicChecks(event.result);
      for (const check of checks) {
        if (
          !record.deterministicChecks.some(
            (existing) => JSON.stringify(existing) === JSON.stringify(check),
          )
        )
          record.deterministicChecks.push(check);
      }
    }
  };
  append({ type: "turn_started" });
  if (options.session) {
    await options.session.appendCustomEntry("portlog_turn_started", {
      turnId: record.turnId,
      posture: record.posture,
      question: record.question,
      startedAt: record.startedAt,
    });
  }
  if (options.projectDirectory) await upsertLocalTurn(options.projectDirectory, record);

  const getEvidence = options.getEvidence
    ? async (request: Omit<EvidenceRequest, "signal">) => {
        if (options.signal.aborted) throw abortError();
        return options.getEvidence!(request);
      }
    : undefined;
  const createTurn = options.createTurn ?? ((bridge) => createPiRuntime(options, bridge));
  let runtime: TurnRuntime | undefined;
  const abort = () => {
    void runtime?.abort();
  };

  try {
    runtime = await createTurn({
      emit: append,
      getEvidence,
      getRuleCheck: options.getRuleCheck,
      runIsolatedCommand: options.runIsolatedCommand,
    });
    if (options.signal.aborted) await runtime.abort();
    else options.signal.addEventListener("abort", abort, { once: true });

    await runtime.prompt(
      record.posture === "chat"
        ? chatPrompt(options.question)
        : record.posture === "verify"
          ? verifyPrompt(options.question)
          : record.posture === "review"
            ? reviewPrompt(options.question)
            : inspectPrompt(options.question),
    );
    if (options.signal.aborted) throw abortError();
    if (!record.finalText.trim()) throw new Error("Model returned no final answer.");
    const deterministicCheck = record.deterministicChecks.at(-1);
    if (record.posture === "inspect" && /\b(satisfied|violated)\b/i.test(record.finalText)) {
      record.finalText =
        "Evidence is insufficient to provide a verification verdict in Inspect posture.";
    } else if (
      record.posture === "verify" &&
      (!deterministicCheck ||
        deterministicCheck.run_status !== "completed" ||
        !isVerificationOutcome(deterministicCheck.outcome))
    ) {
      record.finalText =
        "The deterministic verification check did not complete, so no engineering outcome is available.";
    } else if (
      record.posture === "verify" &&
      !isApplicableVerifyResult(options.question, deterministicCheck!)
    ) {
      record.finalText =
        "The available deterministic check applies only to one centrifugal-pump discharge scope and does not answer this question.";
    } else if (record.posture === "verify") {
      record.finalText = restateDeterministicCheck(deterministicCheck!);
    } else if (
      record.posture === "inspect" &&
      record.evidenceIds.length === 0 &&
      !/evidence is insufficient/i.test(record.finalText)
    ) {
      record.finalText =
        "Evidence is insufficient to answer this question from the prepared local review.";
    }
    record.status = "completed";
    record.completedAt = now().toISOString();
    append({ type: "turn_completed" });
  } catch (error) {
    record.completedAt = now().toISOString();
    if (options.signal.aborted || isAbortError(error)) {
      record.status = "cancelled";
      append({ type: "turn_cancelled" });
    } else {
      record.status = "failed";
      record.error = error instanceof Error ? error.message : String(error);
      append({ type: "turn_failed", message: record.error });
    }
  } finally {
    options.signal.removeEventListener("abort", abort);
    await runtime?.dispose();
    if (options.session)
      await options.session.appendCustomEntry("portlog_turn_terminal", {
        turnId: record.turnId,
        status: record.status,
        completedAt: record.completedAt,
        error: record.error,
      });
    if (options.projectDirectory) await upsertLocalTurn(options.projectDirectory, record);
  }
  return record;
}

async function createPiRuntime(
  options: RunLocalReviewInspectionOptions,
  bridge: CreateTurnOptions,
): Promise<TurnRuntime> {
  if (!options.agentDir || !options.cwd)
    throw new Error("A governed Pi turn requires agentDir and cwd");
  if (!options.session) throw new Error("A persistent PortLog Pi session is required.");
  let modelError: string | undefined;
  const runtime = await options.session.createPiTurn({
    agentDir: options.agentDir,
    cwd: options.cwd,
    provider: options.model.provider,
    model: options.model.id,
    signal: options.signal,
    apiKey: options.apiKey,
    getEvidence: bridge.getEvidence
      ? ({ artifactId, claim }) => bridge.getEvidence!({ artifactId, claim })
      : undefined,
    getRuleCheck: bridge.getRuleCheck ? (request) => bridge.getRuleCheck!(request) : undefined,
    runIsolatedCommand: bridge.runIsolatedCommand,
    onEvent: (event) => {
      if (isRecord(event) && event.type === "message_end" && isRecord(event.message)) {
        if (typeof event.message.errorMessage === "string" && event.message.errorMessage.trim())
          modelError = event.message.errorMessage;
        else if (event.message.stopReason === "error")
          modelError = "The provider returned a model error without details.";
      }
      if (isRecord(event)) {
        const normalized = normalizePiEvent(event);
        if (normalized) bridge.emit(normalized);
      }
    },
  });
  return {
    prompt: async (text) => {
      await runtime.prompt(text);
      if (modelError) throw new Error(`Model request failed: ${modelError}`);
    },
    abort: runtime.abort,
    dispose: runtime.dispose,
  };
}
function normalizePiEvent(
  event: Record<string, unknown>,
): Parameters<CreateTurnOptions["emit"]>[0] | null {
  if (event.type === "message_update") {
    const update = event.assistantMessageEvent as Record<string, unknown> | undefined;
    if (update?.type === "text_delta" && typeof update.delta === "string")
      return { type: "assistant_text_delta", text: update.delta };
  }
  if (event.type === "tool_execution_start")
    return {
      type: "tool_request",
      callId: String(event.toolCallId ?? ""),
      tool: String(event.toolName ?? ""),
      arguments: isRecord(event.args) ? event.args : {},
    };
  if (event.type === "tool_execution_end")
    return {
      type: "tool_result",
      callId: String(event.toolCallId ?? ""),
      tool: String(event.toolName ?? ""),
      result: readPiToolResult(event.result),
    };
  return null;
}

function readPiToolResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.content)) return value;
  const text = value.content.find(
    (item) => isRecord(item) && item.type === "text" && typeof item.text === "string",
  );
  if (!isRecord(text) || typeof text.text !== "string") return value;
  try {
    return JSON.parse(text.text);
  } catch {
    return value;
  }
}

function restateDeterministicCheck(check: Record<string, unknown>) {
  const evidence = isRecord(check.evidence) ? check.evidence : {};
  const evidenceIds = Array.isArray(evidence.ordered_topology_ids)
    ? evidence.ordered_topology_ids.filter((id): id is string => typeof id === "string")
    : [];
  const checkId = typeof check.check_id === "string" ? check.check_id : "unknown";
  const outcome = typeof check.outcome === "string" ? check.outcome : "indeterminate";
  const reason = typeof check.reason_code === "string" ? " Reason: " + check.reason_code + "." : "";
  const trace = evidenceIds.length ? " Evidence: " + evidenceIds.join(" -> ") + "." : "";
  return "PortLog deterministic check " + checkId + ": " + outcome + "." + reason + trace;
}
function isVerificationOutcome(
  value: unknown,
): value is "satisfied" | "violated" | "indeterminate" {
  return value === "satisfied" || value === "violated" || value === "indeterminate";
}
function isApplicableVerifyResult(question: string, check: Record<string, unknown>): boolean {
  if (check.check_id !== "pump_discharge_check_valve") return false;
  const scope = isRecord(check.scope) ? check.scope : {};
  if (scope.class !== "CentrifugalPump") return false;

  const normalizedQuestion = question.toLowerCase();
  if (/\b(every|each|all|universal|plural|multiple)\b/.test(normalizedQuestion)) return false;

  const identifiers = question.match(/[A-Za-z]+[-_]?\d+(?:[\\/._-][A-Za-z0-9]+)*/g) ?? [];
  const asksAboutPump =
    /\bpump\b/.test(normalizedQuestion) ||
    identifiers.some((identifier) => /^p[-_]\d+/i.test(identifier));
  const asksAboutSupportedCheck = /\b(discharge|check[\s-]?valve|rule|verification|verify)\b/.test(
    normalizedQuestion,
  );
  if (!asksAboutPump || !asksAboutSupportedCheck) return false;

  const requestedScope =
    typeof scope.requested_entity_id === "string" ? scope.requested_entity_id.toLowerCase() : "";
  return (
    identifiers.length === 0 ||
    identifiers.some((identifier) => identifier.toLowerCase() === requestedScope)
  );
}

function chatPrompt(question: string) {
  return `You are the PortLog desktop assistant in general conversation mode. Answer the user's question directly and helpfully. No P&ID has been prepared for this turn, so do not claim to have topology evidence or issue an engineering verification verdict.\n\nUser question: ${question}`;
}

function verifyPrompt(question: string) {
  return [
    "You are in Verify posture. You may use ordinary workspace read for context, but only the PortLog deterministic rule-check capability can establish a verification outcome.",
    'Call portlog_rule_check with checkId exactly "pump_discharge_check_valve" and scopeEntityId equal to the pump entity identifier from the question or prepared evidence.',
    "Do not invoke this pump rule for universal or plural questions, non-pump equipment, or a scope identifier that does not match the question. State that the supported check does not answer those questions.",
    "Never write Datalog, choose a rule, infer an outcome, or alter deterministic fields.",
    "After the tool returns, explain the PortLog-owned deterministic_result separately; do not present model prose as the outcome.",
    "If the check fails or is indeterminate, say so honestly.",
    "",
    `User question: ${question}`,
  ].join("\n");
}

function inspectPrompt(question: string) {
  return `You are in Inspect posture. You may use ordinary workspace read for context, but read output is not PortLog evidence. Call portlog_evidence with artifactId exactly "topology" before making prepared-topology claims; put any equipment tag or identifier in claim. Cite stable evidence IDs for factual claims. If evidence is absent or insufficient, say so explicitly. Never issue or label a satisfied/violated verification verdict.\n\nUser question: ${question}`;
}

function reviewPrompt(question: string) {
  return [
    "You are in E06 terminal review posture. You may use ordinary workspace read for context, but only the available PortLog tools establish PortLog-grounded or deterministic results.",
    'First call portlog_evidence with artifactId exactly "topology" and a claim about the requested E06 equipment or connection.',
    'Then call portlog_rule_check with checkId exactly "pump_discharge_check_valve" and scopeEntityId from the question or prepared evidence.',
    'Then call portlog_isolated_command with profileId exactly "review-bundle-candidate". This runs one approved native command; never provide arbitrary commands, paths, credentials, or VM details.',
    "Wait for each tool result before requesting the next tool. Keep ordinary read results, deterministic results, and isolated-command outcomes separate from model explanation.",
    "After all three tools return, answer the question concisely and state any unavailable, rejected, failed, timed-out, or cancelled outcome honestly.",
    "",
    `User question: ${question}`,
  ].join("\n");
}

function readDeterministicChecks(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.flatMap(readDeterministicChecks);
  if (!isRecord(value)) return [];
  const direct = value.deterministic_result;
  return isRecord(direct) && typeof direct.check_id === "string"
    ? [direct]
    : Object.values(value).flatMap(readDeterministicChecks);
}

function readEvidenceIds(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(readEvidenceIds);
  if (!isRecord(value)) return [];
  const direct = [
    value.citations,
    value.evidenceIds,
    value.evidence_ids,
    value.ordered_topology_ids,
  ]
    .flatMap((candidate) => (Array.isArray(candidate) ? candidate : []))
    .filter((candidate): candidate is string => typeof candidate === "string");
  return [...direct, ...Object.values(value).flatMap(readEvidenceIds)];
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function abortError() {
  return new DOMException("Inspection cancelled", "AbortError");
}
function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

export function createDeterministicAskRecord(options: {
  turnId: string;
  question: string;
  route: "rule" | "universal_rule";
  ruleId: string;
  scopeEntityIds: readonly string[];
  checks: readonly { scopeEntityId: string; result: unknown }[];
  domain?: string;
  model?: { provider: string; id: string };
  now?: () => Date;
}): LocalInspectionRecord {
  const now = options.now ?? (() => new Date());
  const startedAt = now().toISOString();
  const derivation = buildRuleDerivation({
    claim: options.question,
    ruleId: options.ruleId,
    scopeEntityIds: options.scopeEntityIds,
    checks: options.checks,
    domain: options.domain,
  });
  const events: StoredEvent[] = [];
  const append = (event: LocalInspectionEvent) => {
    events.push({
      ...event,
      sequence: events.length + 1,
      timestamp: now().toISOString(),
    });
  };
  append({ type: "turn_started" });
  for (const [index, check] of options.checks.entries()) {
    const callId = `ask-rule-${index + 1}`;
    append({
      type: "tool_request",
      callId,
      tool: "portlog_rule_check",
      arguments: { checkId: options.ruleId, scopeEntityId: check.scopeEntityId },
    });
    append({
      type: "tool_result",
      callId,
      tool: "portlog_rule_check",
      result: check.result,
    });
  }
  append({ type: "turn_completed" });
  const completedAt = now().toISOString();
  return {
    schemaVersion: 1,
    turnId: options.turnId,
    posture: "verify",
    question: options.question,
    status: "completed",
    model: options.model ?? { provider: "portlog", id: "governed-rule-engine" },
    startedAt,
    completedAt,
    finalText: derivation.summary,
    evidenceIds: unique(options.checks.flatMap((check) => readEvidenceIds(check.result))),
    deterministicChecks: options.checks.flatMap((check) => readDeterministicChecks(check.result)),
    events,
    route: options.route,
    derivation,
  };
}

export function createClarificationAskRecord(options: {
  turnId: string;
  question: string;
  prompt: string;
  choices: Array<{ id: string; label: string; question: string }>;
  model?: { provider: string; id: string };
  now?: () => Date;
}): LocalInspectionRecord {
  const now = options.now ?? (() => new Date());
  const startedAt = now().toISOString();
  const events: StoredEvent[] = [
    {
      type: "turn_started",
      sequence: 1,
      timestamp: startedAt,
    },
    {
      type: "turn_completed",
      sequence: 2,
      timestamp: now().toISOString(),
    },
  ];
  return {
    schemaVersion: 1,
    turnId: options.turnId,
    posture: "inspect",
    question: options.question,
    status: "completed",
    model: options.model ?? { provider: "portlog", id: "ask-router" },
    startedAt,
    completedAt: events[1].timestamp,
    finalText: options.prompt,
    evidenceIds: [],
    deterministicChecks: [],
    events,
    route: "clarification",
    clarification: { prompt: options.prompt, choices: options.choices },
  };
}
