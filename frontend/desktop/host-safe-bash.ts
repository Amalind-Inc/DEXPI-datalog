import { spawn } from "node:child_process";
import { resolve } from "node:path";

import type {
  BashExecutionResult,
  NormalizedBashRequest,
  RunGovernedBash,
} from "./bash-capability.ts";

import {
  assertNoWorkspaceSymlinkComponents,
  loadPortLogWorkspacePathPolicy,
} from "./workspace-path-policy.ts";

const MAX_OUTPUT_BYTES = 16_384;
const MAX_LIVE_BYTES = 64 * 1024;
const MAX_LIVE_UPDATE_BYTES = 4 * 1024;
const MINIMAL_ENV: Readonly<NodeJS.ProcessEnv> = {
  PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
  NODE_ENV: "production",
  LC_ALL: "C",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_TERMINAL_PROMPT: "0",
  GIT_OPTIONAL_LOCKS: "0",
  GIT_PAGER: "cat",
  PAGER: "cat",
};

const HOST_COMMANDS: Record<string, { file: string; args: string[] }> = {
  pwd: { file: "/bin/pwd", args: [] },
  "git status --short": {
    file: "/usr/bin/git",
    args: ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "status", "--short"],
  },
  "git diff --stat": {
    file: "/usr/bin/git",
    args: [
      "-c",
      "core.fsmonitor=false",
      "-c",
      "core.hooksPath=/dev/null",
      "diff",
      "--no-ext-diff",
      "--stat",
    ],
  },
  "git diff --check": {
    file: "/usr/bin/git",
    args: [
      "-c",
      "core.fsmonitor=false",
      "-c",
      "core.hooksPath=/dev/null",
      "diff",
      "--no-ext-diff",
      "--check",
    ],
  },
  "git rev-parse --show-toplevel": {
    file: "/usr/bin/git",
    args: [
      "-c",
      "core.fsmonitor=false",
      "-c",
      "core.hooksPath=/dev/null",
      "rev-parse",
      "--show-toplevel",
    ],
  },
};

export const runHostSafeBash: RunGovernedBash = async (request, signal, onUpdate) => {
  const command = HOST_COMMANDS[request.command];
  if (!command)
    return {
      outcome: "unavailable",
      stdout: "",
      stderr: "",
      diagnostic: "The host-safe executor received a command outside its exact allowlist.",
    };
  if (!request.workspaceRoot)
    return {
      outcome: "unavailable",
      stdout: "",
      stderr: "",
      diagnostic: "The host-safe executor is missing its workspace authority.",
    };
  try {
    const identity = await assertNoWorkspaceSymlinkComponents(request.workspaceRoot, request.cwd);
    const policy = await loadPortLogWorkspacePathPolicy(identity.root);
    if (identity.relativePath && !policy.evaluate(identity.relativePath, "directory").include)
      return {
        outcome: "unavailable",
        stdout: "",
        stderr: "",
        diagnostic: "The host-safe cwd is excluded by workspace policy.",
      };
  } catch {
    return {
      outcome: "unavailable",
      stdout: "",
      stderr: "",
      diagnostic: "The host-safe cwd could not be authorized.",
    };
  }

  // Ceiling at the workspace parent so Git can discover a repo inside the
  // workspace, but cannot walk into an enclosing host repository.
  const gitCeiling = resolve(request.workspaceRoot, "..");
  const child = spawn(command.file, command.args, {
    cwd: request.cwd,
    env: {
      ...MINIMAL_ENV,
      GIT_CEILING_DIRECTORIES: gitCeiling,
      GIT_DISCOVERY_ACROSS_FILESYSTEM: "0",
    },
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const captured = { stdout: [] as Buffer[], stderr: [] as Buffer[] };
  const capturedBytes = { stdout: 0, stderr: 0 };
  const totalBytes = { stdout: 0, stderr: 0 };
  const decoders = {
    stdout: new TextDecoder("utf-8", { fatal: false }),
    stderr: new TextDecoder("utf-8", { fatal: false }),
  };
  let liveBytes = 0;
  let liveTruncated = false;
  let sequence = 0;
  let timedOut = false;
  let cancelled = false;
  let timer: NodeJS.Timeout | undefined;
  let forceKillTimer: NodeJS.Timeout | undefined;

  const emitLive = (target: "stdout" | "stderr", chunk: Buffer) => {
    if (chunk.byteLength > MAX_LIVE_BYTES - liveBytes) liveTruncated = true;
    let offset = 0;
    while (offset < chunk.byteLength && liveBytes < MAX_LIVE_BYTES) {
      const available = Math.min(
        MAX_LIVE_UPDATE_BYTES,
        chunk.byteLength - offset,
        MAX_LIVE_BYTES - liveBytes,
      );
      const piece = chunk.subarray(offset, offset + available);
      offset += available;
      liveBytes += available;
      const text = decoders[target].decode(piece, { stream: true });
      if (text && onUpdate) {
        sequence += 1;
        onUpdate({
          stdout: target === "stdout" ? text : "",
          stderr: target === "stderr" ? text : "",
          sequence,
          stdoutBytes: totalBytes.stdout,
          stderrBytes: totalBytes.stderr,
          truncated: liveTruncated,
        });
      }
    }
    if (offset < chunk.byteLength) liveTruncated = true;
  };
  const append = (target: "stdout" | "stderr", chunk: Buffer) => {
    totalBytes[target] += chunk.byteLength;
    const remaining = Math.max(0, MAX_OUTPUT_BYTES - capturedBytes[target]);
    const bounded = chunk.subarray(0, remaining);
    if (bounded.byteLength > 0) {
      captured[target].push(bounded);
      capturedBytes[target] += bounded.byteLength;
    }
    emitLive(target, chunk);
  };
  const flushLive = () => {
    for (const target of ["stdout", "stderr"] as const) {
      const text = decoders[target].decode();
      if (text && onUpdate) {
        sequence += 1;
        onUpdate({
          stdout: target === "stdout" ? text : "",
          stderr: target === "stderr" ? text : "",
          sequence,
          stdoutBytes: totalBytes.stdout,
          stderrBytes: totalBytes.stderr,
          truncated: liveTruncated,
        });
      }
    }
  };
  const output = () => ({
    stdout: Buffer.concat(captured.stdout).toString("utf8"),
    stderr: Buffer.concat(captured.stderr).toString("utf8"),
    stdoutBytes: totalBytes.stdout,
    stderrBytes: totalBytes.stderr,
    stdoutTruncated: totalBytes.stdout > capturedBytes.stdout,
    stderrTruncated: totalBytes.stderr > capturedBytes.stderr,
  });

  child.stdout?.on("data", (chunk: Buffer) => append("stdout", chunk));
  child.stderr?.on("data", (chunk: Buffer) => append("stderr", chunk));

  const stop = (cause: "cancelled" | "timed_out") => {
    if (cause === "cancelled") cancelled = true;
    else timedOut = true;
    child.kill("SIGTERM");
    forceKillTimer ??= setTimeout(() => child.kill("SIGKILL"), 250);
  };
  const abort = () => stop("cancelled");
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });
  timer = setTimeout(() => stop("timed_out"), request.timeoutMs);

  try {
    const close = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
      (resolve, reject) => {
        child.once("error", reject);
        child.once("close", (code, childSignal) => resolve({ code, signal: childSignal }));
      },
    );
    flushLive();
    if (cancelled || signal.aborted)
      return {
        outcome: "cancelled",
        ...output(),
        diagnostic: "Host-safe bash was cancelled.",
      };
    if (timedOut)
      return {
        outcome: "timed_out",
        ...output(),
        diagnostic: "Host-safe bash exceeded its bounded timeout.",
      };
    if (close.code === 0)
      return {
        outcome: "admitted",
        ...output(),
        diagnostic: "Host-safe command completed.",
        exitCode: 0,
      };
    return {
      outcome: "failed",
      ...output(),
      diagnostic: `Host-safe command exited with ${close.code ?? close.signal ?? "unknown status"}.`,
      ...(close.code === null ? {} : { exitCode: close.code }),
    };
  } catch (error) {
    flushLive();
    return {
      outcome: cancelled || signal.aborted ? "cancelled" : "failed",
      ...output(),
      diagnostic: error instanceof Error ? error.message.slice(0, 240) : "Host-safe bash failed.",
    };
  } finally {
    clearTimeout(timer);
    clearTimeout(forceKillTimer);
    signal.removeEventListener("abort", abort);
  }
};
