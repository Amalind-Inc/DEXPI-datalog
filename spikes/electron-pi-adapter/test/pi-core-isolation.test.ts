import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

import { Agent } from "@earendil-works/pi-agent-core";
import type { Model } from "@earendil-works/pi-ai";
import { Type } from "typebox";

const model = {
  id: "controlled", name: "controlled", api: "openai-completions", provider: "portlog-test",
  baseUrl: "https://unused.invalid", reasoning: false, input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1024, maxTokens: 128,
} satisfies Model<"openai-completions">;

const toolCallMessage = {
  role: "assistant", content: [{ type: "toolCall", id: "call-1", name: "inspect_prepared_document", arguments: {} }],
  api: "openai-completions", provider: "portlog-test", model: "controlled", timestamp: 0, stopReason: "toolUse",
  usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
};

function settlesWithin<T>(promise: Promise<T>, milliseconds = 1_000): Promise<T> {
  return Promise.race([promise, new Promise<T>((_, reject) => setTimeout(() => reject(new Error(`operation exceeded ${milliseconds}ms`)), milliseconds))]);
}

function parseVersion(version: string): [number, number, number] {
  const matched = version.match(/^(\d+)\.(\d+)\.(\d+)/);
  assert.ok(matched, `expected a semantic version, received ${version}`);
  return [Number(matched[1]), Number(matched[2]), Number(matched[3])];
}

function isAtLeast(version: string, minimum: [number, number, number]): boolean {
  const actual = parseVersion(version);
  return actual[0] > minimum[0] || (actual[0] === minimum[0] && (actual[1] > minimum[1] || (actual[1] === minimum[1] && actual[2] >= minimum[2])));
}

test("pins the public Pi core and Pi AI runtime pair and requires Node 22.19", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(packageJson.devDependencies["@earendil-works/pi-agent-core"], "0.80.6");
  assert.equal(packageJson.devDependencies["@earendil-works/pi-ai"], "0.80.6");
  const lockfile = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
  const piVersions = Object.entries(lockfile.packages).filter(([entry]) => /node_modules\/@earendil-works\/(pi-agent-core|pi-ai)$/.test(entry)).map(([, dependency]) => (dependency as { version: string }).version);
  assert.deepEqual([...new Set(piVersions)], ["0.80.6"]);
  assert.ok(isAtLeast(process.versions.node, [22, 19, 0]), `Node ${process.versions.node} is below Pi's required 22.19.0`);

  const electronNode = execFileSync("./node_modules/.bin/electron", ["--eval", "console.log(process.versions.node)"], { encoding: "utf8", env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" } }).trim();
  assert.ok(isAtLeast(electronNode, [22, 19, 0]), `Electron Node ${electronNode} is below Pi's required 22.19.0`);
});


test("package-root Pi core import creates no files in an isolated HOME or cwd", () => {
  const sandbox = mkdtempSync(join(tmpdir(), "portlog-pi-root-import-"));
  try {
    symlinkSync(join(process.cwd(), "node_modules"), join(sandbox, "node_modules"), "dir");
    execFileSync(process.execPath, ["--input-type=module", "--eval", 'import { Agent } from "@earendil-works/pi-agent-core"; new Agent();'], {
      cwd: sandbox,
      env: { ...process.env, HOME: sandbox, XDG_CONFIG_HOME: join(sandbox, "config"), PI_HOME: join(sandbox, "pi") },
    });
    assert.deepEqual(readdirSync(sandbox), ["node_modules"]);
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});
test("constructing direct Pi core Agent is in-memory and has no built-in tools", () => {
  const agent = new Agent();
  assert.deepEqual(agent.state.tools, []);
  assert.equal(agent.signal, undefined);
  assert.equal(existsSync(".pi"), false);
});

test("runs a PortLog-only sequential tool with injected credentials and no home-state side effects", async () => {
  const sandbox = mkdtempSync(join(tmpdir(), "portlog-pi-core-"));
  const originalHome = process.env.HOME;
  const originalXdg = process.env.XDG_CONFIG_HOME;
  const originalPiHome = process.env.PI_HOME;
  process.env.HOME = sandbox;
  process.env.XDG_CONFIG_HOME = join(sandbox, "config");
  process.env.PI_HOME = join(sandbox, "pi");

  try {
    const events: string[] = [];
    const normalizedTrace: Array<{ type: string; detail?: string }> = [];
    const credentials: string[] = [];
    const toolCalls: string[] = [];
    const signalSeen: AbortSignal[] = [];
    let modelCalls = 0;
    const agent = new Agent({
      initialState: {
        model,
        tools: [{
          name: "inspect_prepared_document", label: "Inspect prepared document", description: "PortLog-owned inspection",
          parameters: Type.Object({}), executionMode: "sequential",
          async execute(callId, _params, signal) {
            toolCalls.push(callId);
            assert.ok(signal);
            normalizedTrace.push({ type: "tool_result", detail: "evidence-1" });
            return { content: [{ type: "text", text: "prepared source" }], details: { evidence_id: "evidence-1" } };
          },
        }],
      },
      toolExecution: "sequential",
      getApiKey(provider) { credentials.push(provider); return "portlog-managed-token"; },
      async streamFn(_model, _context, options) {
        assert.equal(options?.apiKey, "portlog-managed-token");
        assert.ok(options?.signal);
        signalSeen.push(options!.signal!);
        const finalMessage = modelCalls++ === 0 ? toolCallMessage : { ...toolCallMessage, content: [{ type: "text", text: "Inspection complete using evidence-1" }], stopReason: "stop" };
        return { async *[Symbol.asyncIterator]() { yield { type: "start", partial: finalMessage }; yield { type: "done", message: finalMessage }; }, result: async () => finalMessage } as never;
      },
    });
    agent.subscribe((event) => { events.push(event.type); normalizedTrace.push({ type: event.type }); });

    await agent.prompt("Inspect the prepared document");

    assert.deepEqual(credentials, ["portlog-test", "portlog-test"]);
    assert.deepEqual(toolCalls, ["call-1"]);
    assert.equal(signalSeen.length, 2);
    assert.deepEqual(events, ["agent_start", "turn_start", "message_start", "message_end", "message_start", "message_end", "tool_execution_start", "tool_execution_end", "message_start", "message_end", "turn_end", "turn_start", "message_start", "message_end", "turn_end", "agent_end"]);
    assert.ok(normalizedTrace.some((event) => event.type === "tool_result" && event.detail === "evidence-1"));
    assert.deepEqual(readdirSync(sandbox), []);
  } finally {
    if (originalHome === undefined) delete process.env.HOME; else process.env.HOME = originalHome;
    if (originalXdg === undefined) delete process.env.XDG_CONFIG_HOME; else process.env.XDG_CONFIG_HOME = originalXdg;
    if (originalPiHome === undefined) delete process.env.PI_HOME; else process.env.PI_HOME = originalPiHome;
    rmSync(sandbox, { recursive: true, force: true });
  }
});


test("rejects an undeclared built-in tool without executing it", async () => {
  const unknownToolMessage = { ...toolCallMessage, content: [{ type: "toolCall", id: "call-bash", name: "bash", arguments: { command: "pwd" } }] };
  let modelCalls = 0;
  const agent = new Agent({
    initialState: { model, tools: [{ name: "inspect_prepared_document", label: "Inspect", description: "PortLog-owned inspection", parameters: Type.Object({}), async execute() { throw new Error("declared tool must not run"); } }] },
    getApiKey: () => "portlog-managed-token",
    async streamFn() {
      const response = modelCalls++ === 0 ? unknownToolMessage : { ...toolCallMessage, content: [{ type: "text", text: "PortLog rejected the requested tool" }], stopReason: "stop" };
      return { async *[Symbol.asyncIterator]() { yield { type: "done", message: response }; }, result: async () => response } as never;
    },
  });
  await agent.prompt("Inspect the prepared document");
  const rejection = agent.state.messages.find((message) => message.role === "toolResult");
  assert.equal(rejection?.role, "toolResult");
  assert.equal(rejection?.toolName, "bash");
  assert.equal(rejection?.isError, true);
});
test("PortLog abort reaches an active model stream and settles promptly", async () => {
  let streamSignal: AbortSignal | undefined;
  let streamStarted!: () => void;
  const started = new Promise<void>((resolve) => { streamStarted = resolve; });
  const agent = new Agent({
    initialState: { model, tools: [] },
    getApiKey: () => "portlog-managed-token",
    async streamFn(_model, _context, options) {
      streamSignal = options?.signal;
      streamStarted();
      return {
        async *[Symbol.asyncIterator]() {
          if (!streamSignal!.aborted) await new Promise<void>((resolve) => streamSignal!.addEventListener("abort", () => resolve(), { once: true }));
          yield { type: "done", message: { role: "assistant", content: [], api: "openai-completions", provider: "portlog-test", model: "controlled", timestamp: 0, stopReason: "aborted", usage: toolCallMessage.usage } };
        },
        result: async () => ({ role: "assistant", content: [], api: "openai-completions", provider: "portlog-test", model: "controlled", timestamp: 0, stopReason: "aborted", usage: toolCallMessage.usage }),
      } as never;
    },
  });
  const prompt = agent.prompt("Inspect the prepared document");
  await started;
  agent.abort();
  await settlesWithin(prompt);
  assert.equal(streamSignal?.aborted, true);
});

test("PortLog abort reaches an active sequential tool and settles promptly", async () => {
  let toolSignal: AbortSignal | undefined;
  let toolStarted!: () => void;
  const started = new Promise<void>((resolve) => { toolStarted = resolve; });
  const agent = new Agent({
    initialState: { model, tools: [{ name: "inspect_prepared_document", label: "Inspect", description: "PortLog-owned inspection", parameters: Type.Object({}), executionMode: "sequential", async execute(_callId, _params, signal) { toolSignal = signal; toolStarted(); if (!signal!.aborted) await new Promise<void>((resolve) => signal!.addEventListener("abort", () => resolve(), { once: true })); return { content: [{ type: "text", text: "cancelled" }], details: {}, terminate: true }; } }] },
    toolExecution: "sequential",
    getApiKey: () => "portlog-managed-token",
    async streamFn() {
      return { async *[Symbol.asyncIterator]() { yield { type: "done", message: toolCallMessage }; }, result: async () => toolCallMessage } as never;
    },
  });
  const prompt = agent.prompt("Inspect the prepared document");
  await started;
  agent.abort();
  await settlesWithin(prompt);
  assert.equal(toolSignal?.aborted, true);
});
