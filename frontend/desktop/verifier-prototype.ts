import { randomUUID } from "node:crypto";

import { Type } from "typebox";

const MAX_TASK_LENGTH = 500;
const MAX_INPUT_BYTES = 3_000;
const MAX_SUMMARY_LENGTH = 500;
const MAX_RATIONALE_LENGTH = 500;
const MAX_UNCERTAINTY_ITEMS = 4;
const MAX_UNCERTAINTY_LENGTH = 240;
const MAX_CLAIMS = 5;
const MAX_CLAIM_ID_LENGTH = 80;
const MAX_DEADLINE_MS = 5_000;

export type VerifierAssessment = "supported" | "unsupported" | "indeterminate";
export type VerifierStatus = "ok" | "unavailable" | "cancelled";

export type VerifierRequest = {
  roleId: "bounded-review";
  task: string;
  input?: unknown;
};

export type NormalizedVerifierRequest = {
  roleId: "bounded-review";
  task: string;
  input: unknown;
  depth: number;
};

export type VerifierClaim = {
  id: string;
  assessment: VerifierAssessment;
  rationale: string;
};

export type StrictVerifierAssessment = {
  schemaVersion: 1;
  assessment: VerifierAssessment;
  summary: string;
  claims: VerifierClaim[];
  uncertainty: string[];
};

export type VerifierResponse = {
  schemaVersion: 1;
  status: VerifierStatus;
  verifierId: string;
  depth: number;
  childIds: string[];
  result?: StrictVerifierAssessment;
  diagnostic?: string;
  diagnostics: string[];
  authority: "ordinary";
  origin: "verifier";
  untrusted: true;
  limits: {
    maxDepth: number;
    maxChildrenPerRun: number;
    maxTotalRuns: number;
    deadlineMs: number;
  };
};

export type VerifierChildRequest = VerifierRequest;

export type VerifierRun = {
  assessment: unknown;
  children?: unknown;
};

export type VerifierRunnerContext = {
  readonly tools: readonly never[];
};

export type VerifierRunner = (
  request: NormalizedVerifierRequest,
  context: VerifierRunnerContext,
  signal: AbortSignal,
) => Promise<VerifierRun>;

export type VerifierHistoryRecord = {
  id: string;
  parentId: string | null;
  depth: number;
  task: string;
  status: VerifierStatus;
  authority: "ordinary";
  result?: StrictVerifierAssessment;
  diagnostic?: string;
};

export type VerifierHistory = {
  records: VerifierHistoryRecord[];
  append(record: VerifierHistoryRecord): void;
};

export type VerifierLimits = {
  maxDepth?: number;
  maxChildrenPerRun?: number;
  maxTotalRuns?: number;
  deadlineMs?: number;
};

export type VerifierTool = {
  name: "task";
  label: string;
  description: string;
  parameters: ReturnType<typeof Type.Object>;
  executionMode: "sequential";
  execute(
    toolCallId: string,
    params: unknown,
    signal?: AbortSignal,
  ): Promise<{
    content: Array<{ type: "text"; text: string }>;
    details: Record<string, never>;
  }>;
};

export function createInMemoryVerifierHistory(): VerifierHistory {
  return {
    records: [],
    append(record) {
      this.records.push(record);
    },
  };
}

export async function runBoundedVerifier(
  request: unknown,
  options: {
    runner: VerifierRunner;
    history?: VerifierHistory;
    limits?: VerifierLimits;
    signal?: AbortSignal;
  },
): Promise<VerifierResponse> {
  const limits = normalizeLimits(options.limits);
  const history = options.history ?? createInMemoryVerifierHistory();
  const state = { totalRuns: 0 };
  return executeVerifier(request, null, 0, options.runner, history, limits, state, options.signal);
}

export function createVerifierTool(options: {
  runner: VerifierRunner;
  history?: VerifierHistory;
  limits?: VerifierLimits;
}): VerifierTool {
  return {
    name: "task",
    label: "Bounded verifier",
    description:
      "Run one host-defined bounded verifier assessment. The verifier receives normalized input only and has no filesystem, shell, web, credential, or PortLog tools. Its ordinary result is not PortLog authority.",
    parameters: Type.Object(
      {
        roleId: Type.Literal("bounded-review"),
        task: Type.String({ minLength: 1, maxLength: MAX_TASK_LENGTH }),
        input: Type.Optional(Type.Unknown()),
      },
      { additionalProperties: false },
    ),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const request = parseRequest(params);
      const response = request
        ? await runBoundedVerifier(request, { ...options, signal })
        : unavailableResponse(
            0,
            normalizeLimits(options.limits),
            "Verifier request failed input validation.",
          );
      return toolResponse(response);
    },
  };
}

export function createFixtureVerifierRunner(): VerifierRunner {
  return async (request, context) => {
    if (context.tools.length !== 0) throw new Error("fixture verifier unexpectedly received tools");

    const task = request.task.toLowerCase();
    if (task.includes("invalid output")) {
      return { assessment: { schemaVersion: 99, answer: "fixture prose" } };
    }

    const input = asRecord(request.input);
    const childCount =
      typeof input?.childCount === "number" && Number.isInteger(input.childCount)
        ? Math.max(0, Math.min(input.childCount, 5))
        : 0;
    const children = Array.from({ length: childCount }, (_, index) => ({
      roleId: "bounded-review" as const,
      task: `Fixture child ${index + 1} for ${request.task}`,
      input: { child: index + 1 },
    }));
    const assessment: StrictVerifierAssessment = {
      schemaVersion: 1,
      assessment: task.includes("unsupported") ? "unsupported" : "supported",
      summary: `The bounded fixture assessed: ${request.task}`.slice(0, MAX_SUMMARY_LENGTH),
      claims: [
        {
          id: "fixture-claim",
          assessment: task.includes("unsupported") ? "unsupported" : "supported",
          rationale: "The host fixture supplied a bounded assessment without PortLog authority.",
        },
      ],
      uncertainty: ["This disposable fixture is not a deterministic PortLog rule result."],
    };
    return { assessment, children };
  };
}

async function executeVerifier(
  request: unknown,
  parentId: string | null,
  depth: number,
  runner: VerifierRunner,
  history: VerifierHistory,
  limits: Required<VerifierLimits>,
  state: { totalRuns: number },
  signal?: AbortSignal,
): Promise<VerifierResponse> {
  const normalized = normalizeRequest(request, depth);
  if (!normalized)
    return unavailableResponse(depth, limits, "Verifier request failed bounded normalization.");
  if (signal?.aborted) return cancelledResponse(depth, limits);
  if (depth > limits.maxDepth) {
    return unavailableResponse(depth, limits, "Verifier recursion depth exceeded the host limit.");
  }
  if (state.totalRuns >= limits.maxTotalRuns) {
    return unavailableResponse(depth, limits, "Verifier global run budget exhausted.");
  }

  const verifierId = randomUUID();
  state.totalRuns += 1;
  let response: VerifierResponse;
  try {
    const run = await withDeadline(
      runner(normalized, { tools: [] }, signal ?? new AbortController().signal),
      limits.deadlineMs,
      signal,
    );
    const assessment = parseAssessment(run.assessment);
    if (!assessment) {
      response = unavailableResponse(
        depth,
        limits,
        "Verifier output failed the versioned result schema.",
      );
    } else {
      const children = parseChildren(run.children);
      if (run.children !== undefined && !children) {
        response = unavailableResponse(
          depth,
          limits,
          "Verifier child requests failed bounded validation.",
        );
      } else {
        const diagnostics: string[] = [];
        const childIds: string[] = [];
        for (const child of children ?? []) {
          if (childIds.length >= limits.maxChildrenPerRun) {
            diagnostics.push("Per-child verifier budget exhausted.");
            break;
          }
          if (depth >= limits.maxDepth) {
            diagnostics.push("Maximum verifier recursion depth reached.");
            break;
          }
          if (state.totalRuns >= limits.maxTotalRuns) {
            diagnostics.push("Global verifier run budget exhausted.");
            break;
          }
          const childResponse = await executeVerifier(
            child,
            verifierId,
            depth + 1,
            runner,
            history,
            limits,
            state,
            signal,
          );
          childIds.push(childResponse.verifierId);
        }
        response = {
          schemaVersion: 1,
          status: "ok",
          verifierId,
          depth,
          childIds,
          result: assessment,
          diagnostics,
          authority: "ordinary",
          origin: "verifier",
          untrusted: true,
          limits,
        };
      }
    }
  } catch (error) {
    response = signal?.aborted
      ? cancelledResponse(depth, limits)
      : unavailableResponse(
          depth,
          limits,
          error instanceof Error ? error.message : "Verifier execution failed.",
        );
  }

  history.append({
    id: verifierId,
    parentId,
    depth,
    task: normalized.task,
    status: response.status,
    authority: "ordinary",
    result: response.result,
    diagnostic: response.diagnostic,
  });
  return { ...response, verifierId };
}

function normalizeRequest(request: unknown, depth: number): NormalizedVerifierRequest | undefined {
  if (!request || typeof request !== "object" || Array.isArray(request)) return undefined;
  const record = request as Record<string, unknown>;
  if (record.roleId !== "bounded-review" || typeof record.task !== "string") return undefined;
  const task = record.task.trim();
  if (!task || task.length > MAX_TASK_LENGTH || depth < 0) return undefined;
  let input: unknown = record.input ?? {};
  try {
    const serialized = JSON.stringify(input);
    if (serialized === undefined || Buffer.byteLength(serialized, "utf8") > MAX_INPUT_BYTES)
      return undefined;
    input = JSON.parse(serialized) as unknown;
  } catch {
    return undefined;
  }
  return { roleId: "bounded-review", task, input, depth };
}

function parseRequest(value: unknown): VerifierRequest | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => !["roleId", "task", "input"].includes(key)))
    return undefined;
  if (record.roleId !== "bounded-review" || typeof record.task !== "string") return undefined;
  return { roleId: "bounded-review", task: record.task, input: record.input };
}

function parseAssessment(value: unknown): StrictVerifierAssessment | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).some(
      (key) => !["schemaVersion", "assessment", "summary", "claims", "uncertainty"].includes(key),
    ) ||
    record.schemaVersion !== 1 ||
    !isAssessment(record.assessment) ||
    typeof record.summary !== "string" ||
    record.summary.length > MAX_SUMMARY_LENGTH ||
    !Array.isArray(record.claims) ||
    record.claims.length > MAX_CLAIMS ||
    !Array.isArray(record.uncertainty) ||
    record.uncertainty.length > MAX_UNCERTAINTY_ITEMS
  )
    return undefined;

  const claims: VerifierClaim[] = [];
  for (const value of record.claims) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const claim = value as Record<string, unknown>;
    if (
      Object.keys(claim).some((key) => !["id", "assessment", "rationale"].includes(key)) ||
      typeof claim.id !== "string" ||
      !claim.id ||
      claim.id.length > MAX_CLAIM_ID_LENGTH ||
      !isAssessment(claim.assessment) ||
      typeof claim.rationale !== "string" ||
      claim.rationale.length > MAX_RATIONALE_LENGTH
    )
      return undefined;
    claims.push({
      id: claim.id,
      assessment: claim.assessment,
      rationale: claim.rationale,
    });
  }

  const uncertainty = record.uncertainty as unknown[];
  if (
    uncertainty.some((value) => typeof value !== "string" || value.length > MAX_UNCERTAINTY_LENGTH)
  )
    return undefined;
  const normalizedUncertainty = uncertainty as string[];
  return {
    schemaVersion: 1,
    assessment: record.assessment,
    summary: record.summary,
    claims,
    uncertainty: normalizedUncertainty,
  };
}

function parseChildren(value: unknown): VerifierChildRequest[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((child) => !parseRequest(child))) return undefined;
  return value.map((child) => parseRequest(child) as VerifierChildRequest);
}

function normalizeLimits(limits: VerifierLimits = {}): Required<VerifierLimits> {
  return {
    maxDepth: clampInteger(limits.maxDepth, 0, 2, 2),
    maxChildrenPerRun: clampInteger(limits.maxChildrenPerRun, 0, 5, 2),
    maxTotalRuns: clampInteger(limits.maxTotalRuns, 1, 20, 5),
    deadlineMs: clampInteger(limits.deadlineMs, 1, MAX_DEADLINE_MS, 1_000),
  };
}

function clampInteger(
  value: number | undefined,
  minimum: number,
  maximum: number,
  fallback: number,
): number {
  return typeof value === "number" && Number.isInteger(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : fallback;
}

function isAssessment(value: unknown): value is VerifierAssessment {
  return value === "supported" || value === "unsupported" || value === "indeterminate";
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function unavailableResponse(
  depth: number,
  limits: Required<VerifierLimits>,
  diagnostic: string,
): VerifierResponse {
  return {
    schemaVersion: 1,
    status: "unavailable",
    verifierId: "",
    depth,
    childIds: [],
    diagnostic,
    diagnostics: [],
    authority: "ordinary",
    origin: "verifier",
    untrusted: true,
    limits,
  };
}

function cancelledResponse(depth: number, limits: Required<VerifierLimits>): VerifierResponse {
  return {
    ...unavailableResponse(depth, limits, "Verifier execution was cancelled."),
    status: "cancelled",
  };
}

function toolResponse(response: VerifierResponse): {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, never>;
} {
  return { content: [{ type: "text", text: JSON.stringify(response) }], details: {} };
}

async function withDeadline<T>(
  promise: Promise<T>,
  deadlineMs: number,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) throw new DOMException("Verifier cancelled", "AbortError");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unlink: (() => void) | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("Verifier deadline exceeded.")), deadlineMs);
  });
  const cancellation = signal
    ? new Promise<never>((_, reject) => {
        const abort = () => reject(new DOMException("Verifier cancelled", "AbortError"));
        signal.addEventListener("abort", abort, { once: true });
        unlink = () => signal.removeEventListener("abort", abort);
      })
    : undefined;
  try {
    return await Promise.race([promise, timeout, ...(cancellation ? [cancellation] : [])]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    unlink?.();
  }
}
