import {
  createGovernedPiReviewTurn,
  type EvidenceRequest,
  type RuleCheckRequest,
} from "./pi-turn-adapter.ts";
import { upsertLocalTurn } from "./local-project-manifest.cjs";

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
  posture: "inspect" | "verify";
  question: string;
  status: "active" | "completed" | "cancelled" | "failed";
  model: { provider: string; id: string };
  startedAt: string;
  completedAt?: string;
  finalText: string;
  evidenceIds: string[];
  deterministicChecks: Record<string, unknown>[];
  events: StoredEvent[];
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
  getEvidence(request: Omit<EvidenceRequest, "signal">): Promise<unknown>;
  getRuleCheck?(request: RuleCheckRequest): Promise<unknown>;
}

type CreateTurn = (options: CreateTurnOptions) => Promise<TurnRuntime>;

export interface RunLocalReviewInspectionOptions {
  projectDirectory: string;
  turnId: string;
  question: string;
  posture?: "inspect" | "verify";
  model: { provider: string; id: string };
  signal: AbortSignal;
  getEvidence(request: Omit<EvidenceRequest, "signal">): Promise<unknown>;
  getRuleCheck?(request: RuleCheckRequest): Promise<unknown>;
  createTurn?: CreateTurn;
  agentDir?: string;
  cwd?: string;
  apiKey?: string;
  now?: () => Date;
  onEvent?(event: StoredEvent): void;
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
  await upsertLocalTurn(options.projectDirectory, record);

  const getEvidence = async (request: Omit<EvidenceRequest, "signal">) => {
    if (options.signal.aborted) throw abortError();
    return options.getEvidence(request);
  };
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
    });
    if (options.signal.aborted) await runtime.abort();
    else options.signal.addEventListener("abort", abort, { once: true });

    await runtime.prompt(
      record.posture === "verify"
        ? verifyPrompt(options.question)
        : inspectPrompt(options.question),
    );
    if (options.signal.aborted) throw abortError();
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
    await upsertLocalTurn(options.projectDirectory, record);
  }
  return record;
}

async function createPiRuntime(
  options: RunLocalReviewInspectionOptions,
  bridge: CreateTurnOptions,
): Promise<TurnRuntime> {
  if (!options.agentDir || !options.cwd)
    throw new Error("A governed Pi turn requires agentDir and cwd");
  const review = await createGovernedPiReviewTurn({
    agentDir: options.agentDir,
    cwd: options.cwd,
    provider: options.model.provider,
    model: options.model.id,
    signal: options.signal,
    apiKey: options.apiKey,
    getEvidence: ({ artifactId, claim }) => bridge.getEvidence({ artifactId, claim }),
    getRuleCheck: options.getRuleCheck ? (request) => options.getRuleCheck!(request) : undefined,
  });
  const unsubscribe = review.subscribe((event) => {
    const normalized = normalizePiEvent(event);
    if (normalized) bridge.emit(normalized);
  });
  return {
    prompt: review.prompt,
    abort: review.abort,
    dispose: async () => {
      unsubscribe();
      await review.dispose();
    },
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

function verifyPrompt(question: string) {
  return [
    "You are in Verify posture. For the supported pump discharge check, use only the PortLog deterministic rule-check capability.",
    'Call portlog_rule_check with checkId exactly "pump_discharge_check_valve" and scopeEntityId equal to the pump entity identifier from the question or prepared evidence.',
    "Never write Datalog, choose a rule, infer an outcome, or alter deterministic fields.",
    "After the tool returns, explain the PortLog-owned deterministic_result separately; do not present model prose as the outcome.",
    "If the check fails or is indeterminate, say so honestly.",
    "",
    `User question: ${question}`,
  ].join("\n");
}

function inspectPrompt(question: string) {
  return `You are in Inspect posture. Use only the available PortLog read-only evidence capability. Call portlog_evidence with artifactId exactly "topology"; put any equipment tag or identifier in claim. Cite stable evidence IDs for factual claims. If evidence is absent or insufficient, say so explicitly. Never issue or label a satisfied/violated verification verdict.\n\nUser question: ${question}`;
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
