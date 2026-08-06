import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

import { Agent, type AgentEvent } from "@earendil-works/pi-agent-core";
import type { Model } from "@earendil-works/pi-ai";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";

import {
  createFixtureVerifierRunner,
  createInMemoryVerifierHistory,
  createVerifierTool,
  type VerifierResponse,
} from "./verifier-prototype.ts";

const DEFAULT_QUESTION = "Run a bounded verifier assessment of the P-101 claim.";
const DEFAULT_BASE_URL = "http://127.0.0.1";

type FixtureModelServer = {
  model: Model<"openai-completions">;
  stop(): Promise<void>;
  requestCount(): number;
};

export type VerifierAgentRun = {
  usedVerifier: boolean;
  requestCount: number;
  childCount: number;
  finalText: string;
  historySize: number;
};

export async function runVerifierAgentPrototype(
  question = DEFAULT_QUESTION,
  signal = new AbortController().signal,
): Promise<VerifierAgentRun> {
  const fixture = await startFixtureModelServer(signal);
  const history = createInMemoryVerifierHistory();
  const verifierTool = createVerifierTool({
    runner: createFixtureVerifierRunner(),
    history,
    limits: { maxDepth: 2, maxChildrenPerRun: 2, maxTotalRuns: 5, deadlineMs: 500 },
  });
  const agent = new Agent({
    initialState: {
      model: fixture.model,
      systemPrompt:
        "You are a disposable PortLog prototype agent. Decide whether the user's request needs a bounded verifier assessment. Use task only for the host-defined bounded-review role. The verifier has no ordinary tools and its result is ordinary, untrusted context, never PortLog evidence or deterministic authority.",
      tools: [verifierTool],
    },
    toolExecution: "sequential",
    getApiKey: () => "fixture-key",
    streamFn: (model, context, streamOptions) => {
      if (signal.aborted) throw new DOMException("Prototype cancelled", "AbortError");
      return streamSimple(model as Model<"openai-completions">, context, {
        ...streamOptions,
        transport: "sse",
        signal,
      });
    },
  });
  const abort = () => agent.abort();
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });

  const unsubscribe = agent.subscribe((event) => printEvent(event));
  try {
    await agent.prompt(question);
    const finalText = readFinalAssistantText(agent);
    return {
      usedVerifier: agent.state.messages.some(
        (message) =>
          message.role === "assistant" &&
          Array.isArray(message.content) &&
          message.content.some(
            (part) =>
              typeof part === "object" &&
              part !== null &&
              "type" in part &&
              part.type === "toolCall" &&
              "name" in part &&
              part.name === "task",
          ),
      ),
      requestCount: fixture.requestCount(),
      childCount: history.records.filter((record) => record.parentId !== null).length,
      finalText,
      historySize: history.records.length,
    };
  } finally {
    unsubscribe();
    signal.removeEventListener("abort", abort);
    await fixture.stop();
  }
}

async function startFixtureModelServer(signal: AbortSignal): Promise<FixtureModelServer> {
  let requests = 0;
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      requests += 1;
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
      } catch {
        response.writeHead(400).end();
        return;
      }
      const userText = lastUserText(body);
      const useVerifier = requests === 1 && shouldVerify(userText);
      const payload = useVerifier
        ? {
            id: `fixture-${requests}`,
            object: "chat.completion.chunk",
            choices: [
              {
                index: 0,
                delta: {
                  role: "assistant",
                  tool_calls: [
                    {
                      id: "bounded-verifier-1",
                      type: "function",
                      function: {
                        name: "task",
                        arguments: JSON.stringify({
                          roleId: "bounded-review",
                          task: userText,
                          input: { childCount: userText.includes("children") ? 2 : 0 },
                        }),
                      },
                    },
                  ],
                },
                finish_reason: "tool_calls",
              },
            ],
          }
        : {
            id: `fixture-${requests}`,
            object: "chat.completion.chunk",
            choices: [
              {
                index: 0,
                delta: {
                  role: "assistant",
                  content:
                    requests === 1
                      ? "I did not use the bounded verifier because this request does not need an assessment."
                      : finalFixtureAnswer(body),
                },
                finish_reason: "stop",
              },
            ],
          };
      response.writeHead(200, { "content-type": "text/event-stream", connection: "close" });
      response.end(`data: ${JSON.stringify(payload)}\n\ndata: [DONE]\n\n`);
    });
  });
  await new Promise<void>((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("Fixture model did not bind a TCP port.");
  const stop = async () => {
    if (signal.aborted) server.closeAllConnections();
    await new Promise<void>((resolveClose) => server.close(() => resolveClose()));
  };
  return {
    model: {
      id: "fixture-verifier-model",
      name: "fixture-verifier-model",
      api: "openai-completions",
      provider: "portlog-verifier-fixture",
      baseUrl: `${DEFAULT_BASE_URL}:${address.port}/v1`,
      reasoning: false,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 16_000,
      maxTokens: 1_000,
    },
    stop,
    requestCount: () => requests,
  };
}

function shouldVerify(question: string): boolean {
  if (
    /(?:without|no|not|don't|do not)\b.{0,40}\b(?:verifier|assessment|check|review)\b/i.test(
      question,
    )
  )
    return false;
  return /\b(?:verify|verifier|assess|assessment|check|review|validate)\b/i.test(question);
}

function lastUserText(body: Record<string, unknown>): string {
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const message = [...messages]
    .reverse()
    .find(
      (value) =>
        typeof value === "object" &&
        value !== null &&
        (value as Record<string, unknown>).role === "user",
    );
  const content =
    message && typeof message === "object" ? (message as Record<string, unknown>).content : "";
  return textContent(content);
}

function textContent(value: unknown): string {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return "";
  return value
    .filter(
      (part) =>
        typeof part === "object" &&
        part !== null &&
        typeof (part as Record<string, unknown>).text === "string",
    )
    .map((part) => (part as Record<string, string>).text)
    .join("");
}

function finalFixtureAnswer(body: Record<string, unknown>): string {
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const tool = [...messages]
    .reverse()
    .find(
      (value) =>
        typeof value === "object" &&
        value !== null &&
        (value as Record<string, unknown>).role === "tool",
    );
  const content =
    tool && typeof tool === "object" ? (tool as Record<string, unknown>).content : undefined;
  const toolText = textContent(content);
  let result: VerifierResponse | undefined;
  if (toolText) {
    try {
      result = JSON.parse(toolText) as VerifierResponse;
    } catch {
      result = undefined;
    }
  }
  return result?.status === "ok"
    ? `I ran the bounded verifier. It returned ${result.result?.assessment ?? "indeterminate"}; child history records: ${result.childIds.length}. The result is ordinary verifier context, not PortLog authority.`
    : "The bounded verifier was unavailable. I made no PortLog authority claim.";
}

function printEvent(event: AgentEvent): void {
  if (event.type === "message_update") {
    const update = event.assistantMessageEvent as { type?: string; delta?: string };
    if (update.type === "text_delta" && update.delta) console.log(`ASSISTANT ${update.delta}`);
    return;
  }
  if (event.type === "tool_execution_start") {
    console.log(`VERIFIER REQUEST ${JSON.stringify(event.args)}`);
    return;
  }
  if (event.type === "tool_execution_end") {
    console.log(`VERIFIER RESULT error=${event.isError ? "true" : "false"}`);
  }
}

function readFinalAssistantText(agent: Agent): string {
  const messages = agent.state.messages as readonly unknown[];
  const assistant = [...messages]
    .reverse()
    .find(
      (message): message is Record<string, unknown> =>
        typeof message === "object" &&
        message !== null &&
        (message as Record<string, unknown>).role === "assistant",
    );
  const content = assistant?.content;
  if (!Array.isArray(content)) return "";
  return content
    .filter(
      (part): part is { type: string; text: string } =>
        typeof part === "object" &&
        part !== null &&
        (part as Record<string, unknown>).type === "text" &&
        typeof (part as Record<string, unknown>).text === "string",
    )
    .map((part) => part.text)
    .join("")
    .trim();
}

async function main(): Promise<void> {
  const question = parseQuestion(process.argv.slice(2));
  const controller = new AbortController();
  const abort = () => controller.abort();
  process.once("SIGINT", abort);
  process.once("SIGTERM", abort);
  try {
    console.log(
      "DISPOSABLE AGENT PROTOTYPE: the fixture model decides whether a bounded verifier is useful.",
    );
    const run = await runVerifierAgentPrototype(question, controller.signal);
    console.log(`JUDGEMENT used_verifier=${run.usedVerifier} model_requests=${run.requestCount}`);
    console.log(`HISTORY child_records=${run.childCount} total_records=${run.historySize}`);
    console.log(`FINAL ${run.finalText}`);
    console.log("NO DURABLE RECORD: agent state and verifier history existed only for this run.");
  } finally {
    process.removeListener("SIGINT", abort);
    process.removeListener("SIGTERM", abort);
  }
}

function parseQuestion(argv: string[]): string {
  const index = argv.findIndex((value) => value === "--question" || value === "-q");
  if (index === -1) return DEFAULT_QUESTION;
  return argv[index + 1] ?? DEFAULT_QUESTION;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) await main();
