import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { TuiEvent } from "./portlog-tui-model.ts";

type ReviewProcessOptions = {
  readonly id: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly entrypoint?: string;
  readonly onEvent: (event: TuiEvent) => void;
  readonly onOutput?: (line: string) => void;
  readonly onExit: (result: ReviewProcessExit) => void;
};
type ReviewProcessExit = {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly cancelled: boolean;
};
type ReviewProcess = {
  readonly id: string;
  readonly child: ChildProcess;
  cancel(): void;
  dispose(): void;
};

export const REVIEW_ENTRYPOINT = join(dirname(fileURLToPath(import.meta.url)), "portlog-review.ts");

export function startReviewProcess(options: ReviewProcessOptions): ReviewProcess {
  const entrypoint = options.entrypoint ?? REVIEW_ENTRYPOINT;
  const child = spawn(
    process.execPath,
    ["--experimental-strip-types", entrypoint, ...options.args],
    {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  let cancelled = false;
  let terminalEventSeen = false;
  let disposed = false;

  const emit = (event: TuiEvent) => {
    if (disposed) return;
    if (
      event.type === "turn_completed" ||
      event.type === "turn_cancelled" ||
      event.type === "turn_failed"
    )
      terminalEventSeen = true;
    options.onEvent(event);
  };

  child.stdout.on("data", (chunk) => {
    if (disposed) return;
    output += String(chunk);
    const lines = output.split("\n");
    output = lines.pop() ?? "";
    for (const line of lines) {
      if (disposed) return;
      const event = parseReviewLine(line);
      if (event) emit(event);
      if (!disposed) options.onOutput?.(line);
    }
  });
  child.stderr.on("data", (chunk) => {
    if (disposed) return;
    for (const line of String(chunk).split("\n")) {
      if (disposed) return;
      const trimmed = line.trim();
      if (trimmed) options.onOutput?.(`stderr: ${trimmed}`);
    }
  });
  child.once("error", (error) => {
    if (disposed || terminalEventSeen) return;
    emit({ type: "turn_failed", message: error.message });
  });
  child.once("exit", (code, signal) => {
    if (!disposed && !terminalEventSeen && cancelled) emit({ type: "turn_cancelled" });
    else if (!disposed && !terminalEventSeen && code !== 0) {
      emit({
        type: "turn_failed",
        message: `Review process stopped before a terminal result (code ${code ?? "none"}, signal ${signal ?? "none"}).`,
      });
    }
    options.onExit({ code, signal, cancelled });
  });

  return {
    id: options.id,
    child,
    cancel: () => {
      if (disposed || child.exitCode !== null) return;
      cancelled = true;
      child.kill("SIGTERM");
    },
    dispose: () => {
      disposed = true;
      if (child.exitCode === null) child.kill("SIGTERM");
    },
  };
}

export function parseReviewLine(line: string): TuiEvent | undefined {
  const value = line.trim();
  if (!value) return undefined;
  if (value === "TURN STARTED") return { type: "turn_started" };
  if (value === "TURN COMPLETED") return { type: "turn_completed" };
  if (value === "TURN CANCELLED") return { type: "turn_cancelled" };
  if (value.startsWith("TURN FAILED:"))
    return { type: "turn_failed", message: value.slice("TURN FAILED:".length).trim() };
  if (value.startsWith("ASSISTANT:"))
    return { type: "assistant_text_delta", text: value.slice("ASSISTANT:".length).trimStart() };

  const request = parseToolLine(value, "TOOL REQUEST");
  if (request) return { type: "tool_request", ...request };
  const result = parseToolLine(value, "TOOL RESULT");
  if (result) return { type: "tool_result", ...result };
  return undefined;
}

function parseToolLine(
  value: string,
  prefix: string,
): Pick<TuiEvent, "tool" | "arguments" | "result"> | undefined {
  if (!value.startsWith(`${prefix} `)) return undefined;
  const remainder = value.slice(prefix.length + 1);
  const separator = remainder.indexOf(" ");
  const tool = separator === -1 ? remainder : remainder.slice(0, separator);
  const json = separator === -1 ? "null" : remainder.slice(separator + 1);
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    parsed = json;
  }
  return prefix === "TOOL REQUEST" ? { tool, arguments: parsed } : { tool, result: parsed };
}
