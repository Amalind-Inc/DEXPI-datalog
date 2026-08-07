import { randomUUID } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { access, constants } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadLocalProject } from "./local-project-manifest.cjs";
import { resolveReviewSidecarPaths } from "./electron-sidecar-paths.cjs";
import { resolveReviewArtifactRoot } from "./portlog-review-paths.ts";
import { startLocalReviewRuntime, type LocalReviewRuntime } from "./local-review-runtime.ts";

type Posture = "inspect" | "verify" | "review";
type ReviewMode = "inspection" | "chat";
type Provider = "openrouter" | "anthropic" | "openai-codex";

type CliOptions = {
  project?: string;
  mode?: string;
  provider?: string;
  model?: string;
  posture?: string;
  question?: string;
  baseUrl?: string;
  sidecarEndpoint?: string;
  turnId?: string;
  help: boolean;
};

type ValueOption = Exclude<keyof CliOptions, "help">;

type StoredEvent = {
  type: string;
  [key: string]: unknown;
};

type ReviewRecord = {
  status: string;
  [key: string]: unknown;
};

type WorkerMessage =
  | { kind: "event"; event: StoredEvent }
  | { kind: "result"; record: ReviewRecord };

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const WORKER_PATH = join(dirname(fileURLToPath(import.meta.url)), "local-inspection-worker.ts");
const MAX_DISPLAYED_ASSISTANT_CHARS = 16_000;
const MAX_DISPLAYED_TOOL_VALUE_CHARS = 2_000;

const USAGE = `Usage:
  npm run portlog:review -- --project PATH [--mode inspection|chat] \\
    --provider PROVIDER --model MODEL --posture inspect|verify|review --question QUESTION

Required environment:
  PORTLOG_RUNTIME_API_KEY       Provider credential kept in the host process.
  PORTLOG_OPENROUTER_API_KEY    OpenRouter fallback when the provider is openrouter.
  OPENROUTER_API_KEY            Additional OpenRouter fallback used by local desktop.

Optional environment:
  PORTLOG_RUNTIME_BASE_URL      Provider base URL override.
  PORTLOG_REVIEW_SIDECAR_ENDPOINT  Use an already-running trusted loopback sidecar.
  PORTLOG_REVIEW_ARTIFACT_ROOT  Explicit root override; current-projects reuse PROJECT/../reviews when present.
  PORTLOG_REVIEW_SIDECAR_PYTHON Default: repository .venv/bin/python.
  PORTLOG_QEMU_PATH                 QEMU/HVF executable for --posture review.
`;

await run(process.argv.slice(2));

async function run(argv: string[]): Promise<void> {
  try {
    const options = parseArgs(argv);
    if (options.help) {
      console.log(USAGE);
      return;
    }
    const config = await resolveConfig(options);
    const sidecar =
      config.mode === "chat"
        ? { endpoint: "http://127.0.0.1:0", stop: async () => {} }
        : await connectSidecar(config.projectDirectory, config.sidecarEndpoint);
    try {
      const record = await runWorker(config, sidecar.endpoint);
      console.log("FINAL PORTLOG RECORD");
      console.log(JSON.stringify(record, null, 2));
      if (record.status !== "completed") process.exitCode = 1;
    } finally {
      await sidecar.stop();
    }
  } catch (error) {
    process.exitCode = 1;
    console.error(`ERROR: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { help: false };
  const aliases: Record<string, ValueOption> = {
    "-p": "project",
    "-q": "question",
    "--project": "project",
    "--mode": "mode",
    "--provider": "provider",
    "--model": "model",
    "--posture": "posture",
    "--question": "question",
    "--base-url": "baseUrl",
    "--sidecar-endpoint": "sidecarEndpoint",
    "--turn-id": "turnId",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
      continue;
    }
    const equals = argument.indexOf("=");
    const name = equals === -1 ? argument : argument.slice(0, equals);
    const key = aliases[name];
    if (!key) throw new Error(`Unknown option ${name}.\n\n${USAGE}`);
    const value = equals === -1 ? argv[++index] : argument.slice(equals + 1);
    if (!value) throw new Error(`${name} requires a value.\n\n${USAGE}`);
    options[key] = value;
  }
  return options;
}

async function resolveConfig(options: CliOptions) {
  const projectDirectory = requireValue(options.project, "--project");
  const mode = options.mode ?? "inspection";
  const provider = requireValue(options.provider, "--provider");
  const model = requireValue(options.model, "--model");
  const posture = requireValue(options.posture, "--posture");
  const question = requireValue(options.question, "--question");
  if (!isProvider(provider))
    throw new Error(
      `Unsupported provider ${provider}; choose openrouter, anthropic, or openai-codex.`,
    );
  if (posture !== "inspect" && posture !== "verify" && posture !== "review")
    throw new Error(`Unsupported posture ${posture}; choose inspect, verify, or review.`);
  if (!isReviewMode(mode)) throw new Error(`Unsupported mode ${mode}; choose inspection or chat.`);

  const absoluteProjectDirectory = resolve(projectDirectory);
  let project: Awaited<ReturnType<typeof loadLocalProject>>;
  try {
    project = await loadLocalProject(absoluteProjectDirectory);
  } catch (error) {
    throw new Error(
      `Prepared project is unavailable at ${absoluteProjectDirectory}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
  if (project.preparation?.status !== "ready")
    throw new Error(
      `Project ${absoluteProjectDirectory} is not prepared (status: ${String(project.preparation?.status ?? "unknown")}).`,
    );

  const apiKey =
    process.env.PORTLOG_RUNTIME_API_KEY?.trim() ||
    (provider === "openrouter"
      ? process.env.PORTLOG_OPENROUTER_API_KEY?.trim() || process.env.OPENROUTER_API_KEY?.trim()
      : undefined);
  if (!apiKey)
    throw new Error(
      `Provider credential is missing; set PORTLOG_RUNTIME_API_KEY${
        provider === "openrouter" ? ", PORTLOG_OPENROUTER_API_KEY, or OPENROUTER_API_KEY" : ""
      } in the host environment.`,
    );

  const baseUrl =
    options.baseUrl ??
    process.env.PORTLOG_RUNTIME_BASE_URL ??
    (provider === "anthropic"
      ? "https://api.anthropic.com"
      : provider === "openai-codex"
        ? "https://chatgpt.com/backend-api"
        : "https://openrouter.ai/api/v1");
  try {
    new URL(baseUrl);
  } catch {
    throw new Error(`Model base URL is invalid: ${baseUrl}`);
  }
  if (posture === "review") {
    await checkQemuPrerequisite(
      process.env.PORTLOG_QEMU_PATH ?? "/opt/homebrew/bin/qemu-system-aarch64",
    );
  }
  return {
    projectDirectory: absoluteProjectDirectory,
    mode,
    sessionId: project.projectId,
    provider,
    model,
    posture,
    question,
    baseUrl,
    apiKey,
    turnId: options.turnId ?? `terminal-${randomUUID()}`,
    sidecarEndpoint: options.sidecarEndpoint ?? process.env.PORTLOG_REVIEW_SIDECAR_ENDPOINT,
  } satisfies {
    mode: ReviewMode;
    projectDirectory: string;
    sessionId: string;
    provider: Provider;
    model: string;
    posture: Posture;
    question: string;
    baseUrl: string;
    apiKey: string;
    turnId: string;
    sidecarEndpoint?: string;
  };
}

async function connectSidecar(
  projectDirectory: string,
  configuredEndpoint?: string,
): Promise<LocalReviewRuntime> {
  const endpoint = configuredEndpoint;
  if (endpoint) {
    await checkSidecar(endpoint);
    return { endpoint: stripTrailingSlash(endpoint), stop: async () => {} };
  }

  const paths = resolveReviewSidecarPaths({
    isPackaged: false,
    resourcesPath: "",
    desktopDir: join(REPO_ROOT, "frontend", "desktop"),
  });
  const artifactRoot = await resolveReviewArtifactRoot(projectDirectory);
  await mkdir(artifactRoot, { recursive: true });
  try {
    return await startLocalReviewRuntime({
      command: process.env.PORTLOG_REVIEW_SIDECAR_PYTHON ?? paths.python,
      args: ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "0"],
      workingDirectory: paths.cwd,
      environment: {
        HARBORFIELD_DEPLOYMENT_PROFILE: "local",
        HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifactRoot,
        PYTHONPATH: REPO_ROOT,
      },
      endpointFromStdout: (line) => /Uvicorn running on (http:\/\/\S+)/.exec(line)?.[1] ?? null,
      healthPath: "/openapi.json",
    });
  } catch (error) {
    throw new Error(
      `PortLog review sidecar is unavailable: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

async function checkSidecar(endpoint: string): Promise<void> {
  let healthUrl: URL;
  try {
    healthUrl = new URL("openapi.json", `${stripTrailingSlash(endpoint)}/`);
  } catch {
    throw new Error(`PortLog review sidecar endpoint is invalid: ${endpoint}`);
  }
  try {
    const response = await fetch(healthUrl);
    if (!response.ok) throw new Error(`health check returned HTTP ${response.status}`);
  } catch (error) {
    throw new Error(
      `PortLog review sidecar is unavailable at ${stripTrailingSlash(endpoint)}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

async function checkQemuPrerequisite(qemuPath: string): Promise<void> {
  if (process.platform !== "darwin" || process.arch !== "arm64")
    throw new Error(
      `QEMU/HVF isolated review requires arm64 macOS; current host is ${process.platform}/${process.arch}.`,
    );
  if (!isAbsolute(qemuPath))
    throw new Error(`QEMU/HVF path must be absolute: ${qemuPath}. Set PORTLOG_QEMU_PATH.`);
  try {
    await access(qemuPath, constants.X_OK);
  } catch {
    throw new Error(
      `QEMU/HVF runtime is unavailable at ${qemuPath}; install the local development prerequisite or set PORTLOG_QEMU_PATH.`,
    );
  }
}

async function runWorker(
  config: Awaited<ReturnType<typeof resolveConfig>>,
  sidecarEndpoint: string,
): Promise<ReviewRecord> {
  const worker = spawn(process.execPath, ["--experimental-strip-types", WORKER_PATH], {
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      PORTLOG_RUNTIME_API_KEY: config.apiKey,
      PORTLOG_RUNTIME_PROVIDER: config.provider,
      PORTLOG_RUNTIME_MODEL: config.model,
      PORTLOG_RUNTIME_BASE_URL: config.baseUrl,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  let stderr = "";
  let result: ReviewRecord | undefined;
  let output = "";
  let assistantCharacters = 0;
  let assistantTruncationReported = false;

  const render = (event: StoredEvent) => {
    if (event.type === "turn_started") {
      console.log("TURN STARTED");
    } else if (event.type === "assistant_text_delta") {
      const text = typeof event.text === "string" ? event.text : "";
      const remaining = MAX_DISPLAYED_ASSISTANT_CHARS - assistantCharacters;
      if (remaining > 0) {
        const visible = text.slice(0, remaining);
        assistantCharacters += visible.length;
        console.log(`ASSISTANT: ${visible}`);
      }
      if (text.length > remaining && !assistantTruncationReported) {
        assistantTruncationReported = true;
        console.log("ASSISTANT: [display truncated; see the final PortLog record]");
      }
    } else if (event.type === "tool_request") {
      console.log(
        `TOOL REQUEST ${String(event.tool)} ${boundedJson(event.arguments, MAX_DISPLAYED_TOOL_VALUE_CHARS)}`,
      );
    } else if (event.type === "tool_update") {
      console.log(
        `TOOL UPDATE ${String(event.tool)} ${boundedJson(event.result, MAX_DISPLAYED_TOOL_VALUE_CHARS)}`,
      );
    } else if (event.type === "tool_result") {
      console.log(
        `TOOL RESULT ${String(event.tool)} ${boundedJson(event.result, MAX_DISPLAYED_TOOL_VALUE_CHARS)}`,
      );
    } else if (event.type === "turn_completed") {
      console.log("TURN COMPLETED");
    } else if (event.type === "turn_cancelled") {
      console.log("TURN CANCELLED");
    } else if (event.type === "turn_failed") {
      console.log(`TURN FAILED: ${String(event.message)}`);
    }
  };

  const handleSignal = () => {
    if (worker.exitCode === null) worker.kill("SIGTERM");
  };
  process.once("SIGINT", handleSignal);
  process.once("SIGTERM", handleSignal);
  worker.stderr?.on("data", (chunk) => {
    stderr += String(chunk);
    if (stderr.length > 4_000) stderr = stderr.slice(-4_000);
  });
  worker.stdout?.on("data", (chunk) => {
    output += String(chunk);
    const lines = output.split("\n");
    output = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const message = JSON.parse(line) as WorkerMessage;
        if (message.kind === "event") render(message.event);
        else if (message.kind === "result") result = message.record;
      } catch {
        stderr += "The review worker emitted an invalid event frame. ";
      }
    }
  });
  worker.stdin?.end(
    JSON.stringify({
      mode: config.mode,
      projectDirectory: config.projectDirectory,
      cwd: REPO_ROOT,
      sessionId: config.sessionId,
      turnId: config.turnId,
      question: config.question,
      posture: config.posture,
      provider: config.provider,
      model: config.model,
      baseUrl: config.baseUrl,
      sidecarEndpoint,
    }),
  );

  try {
    const [code, signal] = (await waitForWorker(worker)) as [number | null, NodeJS.Signals | null];
    if (result) return result;
    throw new Error(
      `Review worker exited without a PortLog record (code ${code ?? "none"}, signal ${signal ?? "none"}).${
        stderr ? ` ${stderr.trim()}` : ""
      }`,
    );
  } finally {
    process.removeListener("SIGINT", handleSignal);
    process.removeListener("SIGTERM", handleSignal);
  }
}

function waitForWorker(worker: ChildProcess): Promise<[number | null, NodeJS.Signals | null]> {
  return new Promise((resolveExit, rejectExit) => {
    worker.once("error", rejectExit);
    worker.once("exit", (code, signal) => resolveExit([code, signal]));
  });
}

function requireValue(value: string | undefined, option: string): string {
  if (!value?.trim()) throw new Error(`${option} is required.\n\n${USAGE}`);
  return value.trim();
}

function isReviewMode(value: string): value is ReviewMode {
  return value === "inspection" || value === "chat";
}
function isProvider(value: string): value is Provider {
  return value === "openrouter" || value === "anthropic" || value === "openai-codex";
}

function boundedJson(value: unknown, limit: number): string {
  let serialized: string;
  try {
    serialized = JSON.stringify(value) ?? "null";
  } catch {
    serialized = "[unserializable]";
  }
  return serialized.length <= limit ? serialized : `${serialized.slice(0, limit)}…`;
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}
