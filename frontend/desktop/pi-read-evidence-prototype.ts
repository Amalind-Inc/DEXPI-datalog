import { createServer } from "node:http";
import { constants } from "node:fs";
import { mkdtemp, open, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, relative, resolve, join } from "node:path";

import { Agent, type AgentEvent, type AgentTool } from "@earendil-works/pi-agent-core";
import type { Model } from "@earendil-works/pi-ai";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

import { boundedTopologyEvidence } from "./topology-evidence.ts";

type Scenario = "happy" | "ambiguous" | "protected" | "failure" | "cancel";
type Mode = "fixture" | "live";

type CliOptions = {
  mode: Mode;
  scenario: Scenario;
  workspace?: string;
  topology?: string;
  provider: string;
  model: string;
  baseUrl?: string;
  question: string;
  help: boolean;
};

type PrototypeRuntime = {
  agent: Agent;
  workspaceRoot: string;
  cleanup(): Promise<void>;
};

type ToolMetadata = {
  source: string;
  authority: "ordinary" | "portlog";
  limitations: string[];
};

type ToolPayload = ToolMetadata & {
  content?: string;
  path?: string;
  evidence?: ReturnType<typeof boundedTopologyEvidence>;
};

const MAX_READ_BYTES = 12_000;
const MAX_DISPLAY_CHARS = 2_000;
const DEFAULT_MODEL = "deepseek/deepseek-v4-flash";
const DEFAULT_BASE_URL = "https://openrouter.ai/api/v1";
const FIXTURE_FILE = "operator-notes.txt";
const FIXTURE_TOPOLOGY = {
  topology_view: {
    nodes: [
      { id: "P-101", class: "CentrifugalPump", description: "Feed pump" },
      { id: "V-201", class: "Valve", description: "Pump discharge check valve" },
      { id: "TK-301", class: "Tank", description: "Feed tank" },
    ],
    edges: [
      { id: "edge-1", relationship: "connections", source_id: "P-101", target_id: "V-201" },
      { id: "edge-2", relationship: "connections", source_id: "TK-301", target_id: "P-101" },
    ],
  },
};

const USAGE = `Disposable Pi read + PortLog evidence prototype

Usage:
  npm run prototype:pi-read -- --fixture [--scenario happy|ambiguous|protected|failure|cancel]
  npm run prototype:pi-read -- --live --workspace PATH --topology PATH \
    --provider openrouter --model MODEL [--question QUESTION]

Fixture mode needs no credentials and uses a temporary workspace plus topology.
Live mode reads the supplied workspace/topology and uses an OpenAI-compatible API.
The prototype never writes a LocalInspectionRecord, session file, or durable trace.
`;

let activeAgent: Agent | undefined;

await main(process.argv.slice(2));

async function main(argv: string[]): Promise<void> {
  const controller = new AbortController();
  const abort = () => {
    controller.abort();
    activeAgent?.abort();
  };
  process.once("SIGINT", abort);
  process.once("SIGTERM", abort);

  let runtime: PrototypeRuntime | undefined;
  try {
    const options = parseArgs(argv);
    if (options.help) {
      console.log(USAGE);
      return;
    }
    runtime = await createRuntime(options, controller.signal);
    activeAgent = runtime.agent;
    const unsubscribe = runtime.agent.subscribe((event) => printEvent(event));
    try {
      console.log(
        "DISPOSABLE PROTOTYPE: one ephemeral Pi conversation; no durable record will be written.",
      );
      await runtime.agent.prompt(buildPrompt(options.question));
      if (controller.signal.aborted) throw abortError();
      const finalText = readFinalAssistantText(runtime.agent);
      if (!finalText) throw new Error("Pi completed without a final assistant answer.");
      console.log("FINAL");
      console.log(limit(finalText));
      console.log(
        "NO DURABLE RECORD: prototype state existed only in memory and temporary fixture files.",
      );
    } finally {
      unsubscribe();
    }
  } catch (error) {
    if (controller.signal.aborted || isAbortError(error)) {
      console.log("CANCELLED: the Pi run stopped without writing a durable record.");
      process.exitCode = 130;
    } else {
      process.exitCode = 1;
      console.error(`ERROR: ${error instanceof Error ? error.message : String(error)}`);
    }
  } finally {
    activeAgent = undefined;
    await runtime?.cleanup();
    process.removeListener("SIGINT", abort);
    process.removeListener("SIGTERM", abort);
  }
}

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = {
    mode: "fixture",
    scenario: "happy",
    provider: process.env.PORTLOG_RUNTIME_PROVIDER ?? "openrouter",
    model: process.env.PORTLOG_RUNTIME_MODEL ?? DEFAULT_MODEL,
    baseUrl: process.env.PORTLOG_RUNTIME_BASE_URL,
    question:
      "Read operator-notes.txt and use PortLog evidence to explain what is around P-101. Keep ordinary file context separate from authoritative topology evidence.",
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
      continue;
    }
    if (argument === "--fixture") {
      options.mode = "fixture";
      continue;
    }
    if (argument === "--live") {
      options.mode = "live";
      continue;
    }
    const [name, inlineValue] = splitOption(argument);
    const value = inlineValue ?? argv[++index];
    if (!value) throw new Error(`${name} requires a value.\n\n${USAGE}`);
    if (name === "--scenario") options.scenario = readScenario(value);
    else if (name === "--workspace") options.workspace = value;
    else if (name === "--topology") options.topology = value;
    else if (name === "--provider") options.provider = value;
    else if (name === "--model") options.model = value;
    else if (name === "--base-url") options.baseUrl = value;
    else if (name === "--question" || name === "-q") options.question = value;
    else throw new Error(`Unknown option ${name}.\n\n${USAGE}`);
  }
  return options;
}

function splitOption(argument: string): [string, string | undefined] {
  const equals = argument.indexOf("=");
  return equals === -1
    ? [argument, undefined]
    : [argument.slice(0, equals), argument.slice(equals + 1)];
}

function readScenario(value: string): Scenario {
  if (
    value === "happy" ||
    value === "ambiguous" ||
    value === "protected" ||
    value === "failure" ||
    value === "cancel"
  )
    return value;
  throw new Error(
    `Unknown fixture scenario ${value}; choose happy, ambiguous, protected, failure, or cancel.`,
  );
}

async function createRuntime(options: CliOptions, signal: AbortSignal): Promise<PrototypeRuntime> {
  if (options.mode === "fixture") return createFixtureRuntime(options.scenario, signal);
  return createLiveRuntime(options, signal);
}

async function createFixtureRuntime(
  scenario: Scenario,
  signal: AbortSignal,
): Promise<PrototypeRuntime> {
  const workspaceRoot = await mkdtemp(join(tmpdir(), "portlog-pi-read-prototype-"));
  await writeFile(
    join(workspaceRoot, FIXTURE_FILE),
    "P-101 operator note: the pump is shown upstream of the discharge valve.\nThis note is ordinary workspace context, not PortLog verification evidence.\n",
  );
  await writeFile(join(workspaceRoot, ".env"), "fixture-secret=never-return-this\n", {
    mode: 0o600,
  });
  const fixtureServer = await startFixtureServer(scenario, signal);
  const agent = createAgent({
    model: fixtureServer.model,
    apiKey: "fixture-key",
    workspaceRoot,
    topology: FIXTURE_TOPOLOGY,
    signal,
    fixtureDelayMs: scenario === "cancel" ? 10_000 : 0,
  });
  return {
    agent,
    workspaceRoot,
    cleanup: async () => {
      await fixtureServer.stop();
      await rm(workspaceRoot, { recursive: true, force: true });
    },
  };
}

async function createLiveRuntime(
  options: CliOptions,
  signal: AbortSignal,
): Promise<PrototypeRuntime> {
  const workspaceRoot = resolve(options.workspace ?? process.cwd());
  if (!options.workspace) throw new Error("Live mode requires --workspace PATH.");
  if (!options.topology) throw new Error("Live mode requires --topology PATH.");
  const apiKey =
    process.env.PORTLOG_RUNTIME_API_KEY?.trim() || process.env.PORTLOG_OPENROUTER_API_KEY?.trim();
  if (!apiKey)
    throw new Error("Live mode requires PORTLOG_RUNTIME_API_KEY or PORTLOG_OPENROUTER_API_KEY.");
  const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
  try {
    new URL(baseUrl);
  } catch {
    throw new Error(`Model base URL is invalid: ${baseUrl}`);
  }
  let topology: unknown;
  try {
    const authorized = await authorizeWorkspaceFile(workspaceRoot, options.topology, true);
    topology = JSON.parse(await readAuthorizedUtf8(authorized.path));
  } catch (error) {
    throw new Error(
      `Could not read live topology ${options.topology}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
  return {
    agent: createAgent({
      model: createModel({ provider: options.provider, id: options.model, baseUrl }),
      apiKey,
      workspaceRoot,
      topology,
      signal,
    }),
    workspaceRoot,
    cleanup: async () => {},
  };
}

function createAgent(options: {
  model: Model<"openai-completions">;
  apiKey: string;
  workspaceRoot: string;
  topology: unknown;
  signal: AbortSignal;
  fixtureDelayMs?: number;
}): Agent {
  const readTool: AgentTool = {
    name: "read",
    label: "Pi workspace read",
    description:
      "Read a bounded UTF-8 text file under the authorized workspace. This is ordinary context, not engineering evidence.",
    parameters: Type.Object({ path: Type.String() }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      if (options.signal.aborted || signal?.aborted) throw abortError();
      const path = readStringParam(params, "path");
      if (isAbsolute(path)) throw new Error("Read blocked: absolute paths are not allowed.");
      if (isProtectedPath(path))
        throw new Error(
          "Read blocked: credential-like and protected paths are not available to this prototype.",
        );
      let authorized: AuthorizedFile;
      let text: string;
      try {
        authorized = await authorizeWorkspaceFile(options.workspaceRoot, path, false);
        text = await readAuthorizedUtf8(authorized.path);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (detail.startsWith("Path blocked:"))
          throw new Error(`Read blocked: ${detail.slice(13).trim()}`);
        throw new Error(`Read failed for ${path}: ${detail.slice(0, 240)}`);
      }
      const bounded = boundUtf8(text);
      return toolResult({
        source: "Pi workspace read",
        authority: "ordinary",
        limitations: ["workspace context only", "not PortLog evidence", "bounded output"],
        path: authorized.relativePath,
        content: bounded.truncated ? `${bounded.text}\n[truncated]` : bounded.text,
      });
    },
  };

  const evidenceTool: AgentTool = {
    name: "portlog_evidence",
    label: "PortLog topology evidence",
    description:
      "Retrieve bounded, read-only PortLog topology evidence. Use artifactId=topology and put equipment identifiers in claim.",
    parameters: Type.Object({ artifactId: Type.String(), claim: Type.String() }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      if (options.signal.aborted || signal?.aborted) throw abortError();
      const artifactId = readStringParam(params, "artifactId");
      const claim = readStringParam(params, "claim");
      if (artifactId !== "topology")
        throw new Error("PortLog evidence rejected: artifactId must be exactly topology.");
      if (options.fixtureDelayMs) await delay(options.fixtureDelayMs, options.signal);
      if (options.signal.aborted || signal?.aborted) throw abortError();
      const evidence = boundedTopologyEvidence(options.topology, claim);
      return toolResult({
        source: "PortLog topology evidence",
        authority: "portlog",
        limitations: [
          "bounded and read-only",
          "citations and diagnostics define the supported scope",
          "does not authorize writes or replace deterministic checks",
        ],
        evidence,
      });
    },
  };

  const agent = new Agent({
    initialState: {
      model: options.model,
      systemPrompt:
        "You are a disposable PortLog prototype agent. Use both read and portlog_evidence when the task needs both. Keep ordinary file context separate from PortLog evidence. Never present ordinary read output as authoritative engineering evidence. Report evidence citations, diagnostics, uncertainty, and limitations.",
      tools: [readTool, evidenceTool],
    },
    toolExecution: "sequential",
    getApiKey: () => options.apiKey,
    streamFn: (model, context, streamOptions) => {
      if (options.signal.aborted) throw abortError();
      return streamSimple(model as Model<"openai-completions">, context, {
        ...streamOptions,
        transport: "sse",
        signal: options.signal,
      });
    },
  });
  const abort = () => agent.abort();
  if (options.signal.aborted) abort();
  else options.signal.addEventListener("abort", abort, { once: true });
  return agent;
}

function createModel(options: {
  provider: string;
  id: string;
  baseUrl: string;
}): Model<"openai-completions"> {
  return {
    id: options.id,
    name: options.id,
    api: "openai-completions",
    provider: options.provider,
    baseUrl: options.baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 32_000,
    maxTokens: 2_000,
  };
}

function toolResult(payload: ToolPayload) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload) }],
    details: payload,
  };
}

function printEvent(event: AgentEvent): void {
  if (event.type === "message_update") {
    const update = event.assistantMessageEvent as { type?: string; delta?: string };
    if (update.type === "text_delta" && update.delta)
      console.log(`ASSISTANT ${limit(update.delta)}`);
    return;
  }
  if (event.type === "tool_execution_start") {
    const label = event.toolName === "read" ? "PI READ" : "PORTLOG EVIDENCE";
    console.log(`${label} REQUEST ${limit(JSON.stringify(event.args))}`);
    return;
  }
  if (event.type === "tool_execution_end") {
    const payload = readToolPayload(event.result);
    if (event.isError) {
      console.log(`ERROR ${event.toolName}: ${limit(readToolText(event.result))}`);
      return;
    }
    const label = event.toolName === "read" ? "PI READ" : "PORTLOG EVIDENCE";
    console.log(
      `${label} RESULT source=${payload?.source ?? "unknown"} authority=${payload?.authority ?? "unknown"}`,
    );
    if (payload?.content) console.log(limit(payload.content));
    if (payload?.evidence) console.log(limit(JSON.stringify(payload.evidence)));
    for (const limitation of payload?.limitations ?? []) console.log(`LIMITATION ${limitation}`);
  }
}

function readFinalAssistantText(agent: Agent): string {
  const messages = agent.state.messages as readonly unknown[];
  const assistant = [...messages]
    .reverse()
    .find(
      (message): message is Record<string, unknown> =>
        isRecord(message) && message.role === "assistant",
    );
  const content = assistant?.content;
  if (!Array.isArray(content)) return "";
  return content
    .filter(
      (part: unknown): part is { type: string; text: string } =>
        isRecord(part) && part.type === "text" && typeof part.text === "string",
    )
    .map((part) => part.text)
    .join("")
    .trim();
}

function readToolPayload(value: unknown): ToolPayload | undefined {
  const text = readToolText(value);
  try {
    const parsed = JSON.parse(text);
    return isRecord(parsed) ? (parsed as ToolPayload) : undefined;
  } catch {
    return undefined;
  }
}

function readToolText(value: unknown): string {
  if (!isRecord(value) || !Array.isArray(value.content)) return String(value ?? "");
  const text = value.content.find(
    (part) => isRecord(part) && part.type === "text" && typeof part.text === "string",
  );
  return isRecord(text) && typeof text.text === "string" ? text.text : String(value);
}

async function startFixtureServer(
  scenario: Scenario,
  signal: AbortSignal,
): Promise<{
  model: Model<"openai-completions">;
  stop(): Promise<void>;
}> {
  let requestCount = 0;
  const server = createServer((_request, response) => {
    requestCount += 1;
    response.writeHead(200, { "content-type": "text/event-stream", connection: "close" });
    if (requestCount === 1) {
      const calls = fixtureCalls(scenario);
      response.write(
        `data: ${JSON.stringify({ id: "fixture-1", object: "chat.completion.chunk", choices: [{ index: 0, delta: { role: "assistant", tool_calls: calls }, finish_reason: "tool_calls" }] })}\n\n`,
      );
    } else {
      response.write(
        `data: ${JSON.stringify({ id: "fixture-2", object: "chat.completion.chunk", choices: [{ index: 0, delta: { role: "assistant", content: fixtureAnswer(scenario) }, finish_reason: "stop" }] })}\n\n`,
      );
    }
    response.end("data: [DONE]\n\n");
  });
  await new Promise<void>((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("Fixture server did not bind a TCP port.");
  const stop = async () => {
    if (signal.aborted) server.closeAllConnections();
    await new Promise<void>((resolveClose) => server.close(() => resolveClose()));
  };
  return {
    model: createModel({
      provider: "portlog-fixture",
      id: "fixture-model",
      baseUrl: `http://127.0.0.1:${address.port}/v1`,
    }),
    stop,
  };
}

function fixtureCalls(scenario: Scenario) {
  const path =
    scenario === "protected" ? ".env" : scenario === "failure" ? "missing.txt" : FIXTURE_FILE;
  const claim = scenario === "ambiguous" ? "P-999" : "P-101";
  return [
    {
      id: "read-1",
      type: "function",
      function: { name: "read", arguments: JSON.stringify({ path }) },
    },
    {
      id: "evidence-1",
      type: "function",
      function: {
        name: "portlog_evidence",
        arguments: JSON.stringify({ artifactId: "topology", claim }),
      },
    },
  ];
}

function fixtureAnswer(scenario: Scenario): string {
  if (scenario === "ambiguous")
    return "The PortLog evidence query returned no matching evidence, so I cannot make a topology claim. The file context remains ordinary only.";
  if (scenario === "protected")
    return "The protected workspace read was blocked. I used only the bounded PortLog result and kept the blocked path separate from evidence.";
  if (scenario === "failure")
    return "The workspace read failed because the file was unavailable. The PortLog result is still bounded and separately identified.";
  if (scenario === "cancel")
    return "The fixture would report both sources after the bounded evidence call completes.";
  return "The ordinary note says P-101 is upstream of the discharge valve. PortLog topology evidence cites P-101 and V-201 and shows a connections relationship; the bounded evidence does not authorize broader claims.";
}

function buildPrompt(question: string): string {
  return `${question}\n\nUse the registered read tool for file context and portlog_evidence for authoritative topology evidence. In your answer label which source supports each statement and state limitations.`;
}

function readStringParam(value: unknown, key: string): string {
  if (!isRecord(value) || typeof value[key] !== "string" || !value[key].trim())
    throw new Error(`Invalid ${key} argument.`);
  return value[key] as string;
}

type AuthorizedFile = {
  path: string;
  relativePath: string;
};

async function authorizeWorkspaceFile(
  workspaceRoot: string,
  requestedPath: string,
  allowAbsolute: boolean,
): Promise<AuthorizedFile> {
  if (!allowAbsolute && isAbsolute(requestedPath))
    throw new Error("Path blocked: absolute paths are not allowed.");
  const lexicalTarget = resolve(workspaceRoot, requestedPath);
  if (!isWithin(workspaceRoot, lexicalTarget))
    throw new Error("Path blocked: path escapes the authorized workspace.");
  let realRoot: string;
  let realTarget: string;
  try {
    realRoot = await realpath(workspaceRoot);
    realTarget = await realpath(lexicalTarget);
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : String(error));
  }
  if (!isWithin(realRoot, realTarget))
    throw new Error("Path blocked: resolved target escapes the authorized workspace.");
  const relativePath = relative(realRoot, realTarget);
  if (isProtectedPath(relativePath))
    throw new Error("Path blocked: resolved target is credential-like or protected.");
  return { path: realTarget, relativePath };
}

async function readAuthorizedUtf8(path: string): Promise<string> {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(path, constants.O_RDONLY | noFollow);
  try {
    return await handle.readFile({ encoding: "utf8" });
  } finally {
    await handle.close();
  }
}

function boundUtf8(text: string): { text: string; truncated: boolean } {
  const bytes = Buffer.from(text, "utf8");
  const truncated = bytes.byteLength > MAX_READ_BYTES;
  let end = Math.min(bytes.byteLength, MAX_READ_BYTES);
  while (end > 0 && end < bytes.byteLength && (bytes[end] & 0xc0) === 0x80) end -= 1;
  return { text: bytes.subarray(0, end).toString("utf8"), truncated };
}

function isProtectedPath(path: string): boolean {
  return /(^|[\\/])(?:\.env(?:\..*)?|\.git|\.ssh|credentials?|secrets?|id_rsa|.*\.(?:pem|key))(?:[\\/]|$)/i.test(
    path,
  );
}

function isWithin(root: string, candidate: string): boolean {
  const rootPath = resolve(root);
  const candidatePath = resolve(candidate);
  const suffix = relative(rootPath, candidatePath);
  return (
    suffix === "" ||
    (suffix !== ".." && !suffix.startsWith(`..${requireSeparator()}`) && !isAbsolute(suffix))
  );
}

function requireSeparator(): string {
  return process.platform === "win32" ? "\\" : "/";
}

function limit(value: string): string {
  return value.length <= MAX_DISPLAY_CHARS ? value : `${value.slice(0, MAX_DISPLAY_CHARS)}…`;
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolveDelay, reject) => {
    const timeout = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolveDelay();
    }, milliseconds);
    const onAbort = () => {
      clearTimeout(timeout);
      reject(abortError());
    };
    if (signal.aborted) onAbort();
    else signal.addEventListener("abort", onAbort, { once: true });
  });
}

function abortError(): DOMException {
  return new DOMException("Prototype cancelled", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
