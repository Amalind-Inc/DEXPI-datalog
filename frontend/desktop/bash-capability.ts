import { isAbsolute, relative, resolve } from "node:path";

import { Type } from "typebox";

const MAX_COMMAND_LENGTH = 2_000;
const MAX_OUTPUT_LENGTH = 8_192;
const MAX_TIMEOUT_MS = 10_000;
const DEFAULT_TIMEOUT_MS = 3_000;
const HOST_SAFE_COMMANDS = new Set([
  "pwd",
  "git status --short",
  "git diff --stat",
  "git diff --check",
  "git rev-parse --show-toplevel",
]);

export type BashRoute = "host-safe" | "gondolin" | "unavailable";
export type BashOutcome =
  | "admitted"
  | "rejected"
  | "unavailable"
  | "failed"
  | "cancelled"
  | "timed_out";

export type BashRequest = {
  command: string;
  cwd?: string;
  timeoutMs?: number;
  pty?: boolean;
  env?: Record<string, string>;
};

export type NormalizedBashRequest = {
  command: string;
  cwd: string;
  timeoutMs: number;
  pty: false;
  env: Record<string, never>;
};

export type BashClassification =
  | { route: "host-safe" | "gondolin"; request: NormalizedBashRequest; diagnostic: string }
  | { route: "unavailable"; diagnostic: string };

export type BashExecutionResult = {
  outcome: BashOutcome;
  stdout: string;
  stderr: string;
  diagnostic: string;
  exitCode?: number;
};

export type BashOutputUpdate = {
  stdout: string;
  stderr: string;
};

export type RunGovernedBash = (
  request: NormalizedBashRequest,
  signal: AbortSignal,
  onUpdate?: (update: BashOutputUpdate) => void,
) => Promise<BashExecutionResult>;

export type GovernedBashTool = {
  name: "bash";
  label: string;
  description: string;
  parameters: ReturnType<typeof Type.Object>;
  executionMode: "sequential";
  execute(
    toolCallId: string,
    params: unknown,
    signal?: AbortSignal,
    onUpdate?: (partialResult: {
      content: Array<{ type: "text"; text: string }>;
      details: Record<string, never>;
    }) => void,
  ): Promise<{
    content: Array<{ type: "text"; text: string }>;
    details: Record<string, never>;
  }>;
};

export function classifyBashRequest(
  request: BashRequest,
  workspaceRoot: string,
): BashClassification {
  if (!request || typeof request.command !== "string")
    return { route: "unavailable", diagnostic: "Bash command is missing." };
  const command = request.command.trim().replace(/\s+/g, " ");
  if (!command) return { route: "unavailable", diagnostic: "Bash command must not be empty." };
  if (command.length > MAX_COMMAND_LENGTH)
    return { route: "unavailable", diagnostic: "Bash command exceeds the bounded command length." };

  const root = resolve(workspaceRoot);
  const cwd = resolve(root, request.cwd?.trim() || ".");
  const cwdRelative = relative(root, cwd);
  if (cwdRelative.startsWith("..") || isAbsolute(cwdRelative))
    return {
      route: "unavailable",
      diagnostic: "Bash cwd must remain inside the authorized workspace.",
    };
  if (request.pty === true)
    return { route: "unavailable", diagnostic: "PTY bash execution is typed unavailable." };
  if (request.env && Object.keys(request.env).length > 0)
    return { route: "unavailable", diagnostic: "Bash environment overlays are not authorized." };
  if (
    request.timeoutMs !== undefined &&
    (!Number.isInteger(request.timeoutMs) || request.timeoutMs < 1)
  )
    return { route: "unavailable", diagnostic: "Bash timeout must be a positive integer." };

  const normalized: NormalizedBashRequest = {
    command,
    cwd,
    timeoutMs: Math.min(MAX_TIMEOUT_MS, request.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    pty: false,
    env: {},
  };
  if (HOST_SAFE_COMMANDS.has(command))
    return {
      route: "host-safe",
      request: normalized,
      diagnostic: "Exact read-only host-safe command.",
    };
  return {
    route: "gondolin",
    request: normalized,
    diagnostic: "Command is compound, mutating, or outside the narrow host-safe allowlist.",
  };
}

export function createGovernedBashTool(options: {
  workspaceRoot: string;
  runHostSafe?: RunGovernedBash;
  runGondolin?: RunGovernedBash;
}): GovernedBashTool {
  return {
    name: "bash",
    label: "Policy-routed bash",
    description:
      "Run a familiar bash request through whole-request policy classification. Exact read-only commands may use a minimal host-safe environment; compound or risky requests route atomically to Gondolin. PTY, environment overlays, host paths, and fallback execution are unavailable.",
    parameters: Type.Object(
      {
        command: Type.String({ minLength: 1, maxLength: MAX_COMMAND_LENGTH }),
        cwd: Type.Optional(Type.String({ minLength: 1, maxLength: 1_000 })),
        timeoutMs: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_TIMEOUT_MS })),
        pty: Type.Optional(Type.Boolean()),
        env: Type.Optional(Type.Record(Type.String(), Type.String())),
      },
      { additionalProperties: false },
    ),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, onUpdate) {
      const request = parseRequest(params);
      if (!request)
        return toolResponse("unavailable", "rejected", "Bash request failed parameter validation.");
      const classification = classifyBashRequest(request, options.workspaceRoot);
      if (classification.route === "unavailable")
        return toolResponse("unavailable", "rejected", classification.diagnostic);

      const runner =
        classification.route === "host-safe" ? options.runHostSafe : options.runGondolin;
      if (!runner)
        return toolResponse(
          "unavailable",
          "unavailable",
          "The selected bash route is unavailable; no host fallback was used.",
        );
      const controller = new AbortController();
      const activeSignal = signal ?? controller.signal;
      const emitUpdate = (update: BashOutputUpdate) => {
        onUpdate?.(toolResponse(classification.route, "admitted", "Bash output update.", update));
      };
      try {
        const result = await runner(classification.request, activeSignal, emitUpdate);
        return toolResponse(classification.route, result.outcome, result.diagnostic, result);
      } catch (error) {
        return toolResponse(
          classification.route,
          activeSignal.aborted ? "cancelled" : "failed",
          activeSignal.aborted
            ? "Bash execution was cancelled."
            : error instanceof Error
              ? error.message
              : "Bash execution failed before a result was available.",
        );
      }
    },
  };
}

function parseRequest(value: unknown): BashRequest | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).some((key) => !["command", "cwd", "timeoutMs", "pty", "env"].includes(key))
  )
    return undefined;
  if (typeof record.command !== "string") return undefined;
  if (record.cwd !== undefined && typeof record.cwd !== "string") return undefined;
  if (record.timeoutMs !== undefined && typeof record.timeoutMs !== "number") return undefined;
  if (record.pty !== undefined && typeof record.pty !== "boolean") return undefined;
  if (
    record.env !== undefined &&
    (!record.env || typeof record.env !== "object" || Array.isArray(record.env))
  )
    return undefined;
  const env: Record<string, string> = {};
  if (record.env) {
    for (const [key, item] of Object.entries(record.env)) {
      if (typeof item !== "string" || key.length > 120 || item.length > 500) return undefined;
      env[key] = item;
    }
  }
  return {
    command: record.command,
    cwd: record.cwd,
    timeoutMs: record.timeoutMs,
    pty: record.pty,
    env,
  };
}

function toolResponse(
  route: BashRoute,
  outcome: BashOutcome,
  diagnostic: string,
  result?: Partial<BashExecutionResult> & BashOutputUpdate,
): {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, never>;
} {
  const stdout = boundOutput(result?.stdout ?? "");
  const stderr = boundOutput(result?.stderr ?? "");
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          schemaVersion: 1,
          outcome,
          route,
          authority: "ordinary",
          stdout: stdout.value,
          stderr: stderr.value,
          diagnostic: diagnostic.slice(0, 240),
          output_truncated: stdout.truncated || stderr.truncated,
          ...(result?.exitCode === undefined ? {} : { exitCode: result.exitCode }),
        }),
      },
    ],
    details: {},
  };
}

function boundOutput(value: string): { value: string; truncated: boolean } {
  const safe = typeof value === "string" ? value : "";
  return safe.length > MAX_OUTPUT_LENGTH
    ? { value: safe.slice(0, MAX_OUTPUT_LENGTH), truncated: true }
    : { value: safe, truncated: false };
}
