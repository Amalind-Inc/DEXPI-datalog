import { spawn } from "node:child_process";

import type {
  BashExecutionResult,
  NormalizedBashRequest,
  RunGovernedBash,
} from "./bash-capability.ts";

const MAX_OUTPUT_BYTES = 16_384;
const MINIMAL_ENV = {
  PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
  LC_ALL: "C",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_TERMINAL_PROMPT: "0",
};

const HOST_COMMANDS = new Map<string, { file: string; args: string[] }>([
  ["pwd", { file: "/bin/pwd", args: [] }],
  ["git status --short", { file: "/usr/bin/git", args: ["status", "--short"] }],
  ["git diff --stat", { file: "/usr/bin/git", args: ["diff", "--stat"] }],
  ["git diff --check", { file: "/usr/bin/git", args: ["diff", "--check"] }],
  [
    "git rev-parse --show-toplevel",
    { file: "/usr/bin/git", args: ["rev-parse", "--show-toplevel"] },
  ],
]);

export const runHostSafeBash: RunGovernedBash = async (request, signal, onUpdate) => {
  const command = HOST_COMMANDS.get(request.command);
  if (!command)
    return {
      outcome: "unavailable",
      stdout: "",
      stderr: "",
      diagnostic: "The host-safe executor received a command outside its exact allowlist.",
    };

  const child = spawn(command.file, command.args, {
    cwd: request.cwd,
    env: MINIMAL_ENV as unknown as NodeJS.ProcessEnv,
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  let timedOut = false;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const append = (target: "stdout" | "stderr", chunk: Buffer) => {
    const next = (target === "stdout" ? stdout : stderr) + chunk.toString("utf8");
    const bounded = next.slice(0, MAX_OUTPUT_BYTES);
    if (target === "stdout") stdout = bounded;
    else stderr = bounded;
    onUpdate?.({ stdout, stderr });
  };
  child.stdout?.on("data", (chunk: Buffer) => append("stdout", chunk));
  child.stderr?.on("data", (chunk: Buffer) => append("stderr", chunk));

  const abort = () => {
    cancelled = true;
    child.kill("SIGTERM");
  };
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });
  timer = setTimeout(() => {
    timedOut = true;
    child.kill("SIGTERM");
  }, request.timeoutMs);

  try {
    const close = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
      (resolve, reject) => {
        child.once("error", reject);
        child.once("close", (code, childSignal) => resolve({ code, signal: childSignal }));
      },
    );
    if (cancelled || signal.aborted)
      return { outcome: "cancelled", stdout, stderr, diagnostic: "Host-safe bash was cancelled." };
    if (timedOut)
      return {
        outcome: "timed_out",
        stdout,
        stderr,
        diagnostic: "Host-safe bash exceeded its bounded timeout.",
      };
    if (close.code === 0)
      return {
        outcome: "admitted",
        stdout,
        stderr,
        diagnostic: "Host-safe command completed.",
        exitCode: 0,
      };
    return {
      outcome: "failed",
      stdout,
      stderr,
      diagnostic: `Host-safe command exited with ${close.code ?? close.signal ?? "unknown status"}.`,
      ...(close.code === null ? {} : { exitCode: close.code }),
    };
  } catch (error) {
    return {
      outcome: cancelled || signal.aborted ? "cancelled" : "failed",
      stdout,
      stderr,
      diagnostic: error instanceof Error ? error.message.slice(0, 240) : "Host-safe bash failed.",
    };
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
};
