import { readFile } from "node:fs/promises";

import { Agent } from "@earendil-works/pi-agent-core";
import type { Model } from "@earendil-works/pi-ai";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

export interface EvidenceRequest {
  artifactId: string;
  claim: string;
  signal: AbortSignal | undefined;
}

export interface GovernedPiReviewTurnOptions {
  agentDir: string;
  cwd: string;
  provider: string;
  model: string;
  signal: AbortSignal;
  apiKey?: string;
  getEvidence(request: EvidenceRequest): Promise<unknown>;
}

type PortLogModelEntry = {
  id: string;
  name?: string;
  reasoning?: boolean;
  input?: Array<"text" | "image">;
  contextWindow?: number;
  maxTokens?: number;
};
type PortLogProviderEntry = {
  baseUrl: string;
  api: "openai-completions";
  apiKey?: string;
  models: PortLogModelEntry[];
};

/**
 * Creates a direct, in-memory Pi core Agent for one PortLog turn.
 *
 * Pi supplies model streaming and sequential tool-call orchestration only.
 * PortLog owns credentials, evidence, cancellation, and durable trace state;
 * no coding-agent session, auth store, built-in tool, or Pi JSONL is created.
 */
export async function createGovernedPiReviewTurn(options: GovernedPiReviewTurnOptions) {
  const model = await readPortLogModel(options);
  const apiKey = options.apiKey ?? model.configuredApiKey;
  if (!apiKey) throw new Error(`No PortLog runtime key for ${options.provider}`);

  const evidenceTool = {
    name: "portlog_evidence",
    label: "PortLog evidence",
    description: "Retrieve bounded, read-only evidence from the prepared PortLog review.",
    parameters: Type.Object({ artifactId: Type.String(), claim: Type.String() }),
    executionMode: "sequential" as const,
    async execute(_toolCallId: string, params: unknown, signal?: AbortSignal) {
      if (!isEvidenceParams(params)) throw new Error("Invalid PortLog evidence arguments");
      const result = await options.getEvidence({ ...params, signal: options.signal });
      if (options.signal.aborted || signal?.aborted)
        throw new DOMException("Inspection cancelled", "AbortError");
      return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: {} };
    },
  };

  const agent = new Agent({
    initialState: { model: model.value, tools: [evidenceTool] },
    toolExecution: "sequential",
    getApiKey: () => apiKey,
    streamFn: (selectedModel, context, streamOptions) => {
      if (options.signal.aborted) throw new DOMException("Inspection cancelled", "AbortError");
      return streamSimple(selectedModel as Model<"openai-completions">, context, streamOptions);
    },
  });
  const abort = async () => {
    agent.abort();
  };
  if (options.signal.aborted) await abort();
  else options.signal.addEventListener("abort", abort, { once: true });

  return {
    agent,
    session: { agent, sessionFile: undefined as string | undefined, abort },
    prompt: (text: string) => agent.prompt(text),
    abort,
    subscribe: agent.subscribe.bind(agent),
    dispose: async () => {
      options.signal.removeEventListener("abort", abort);
    },
  };
}

async function readPortLogModel(
  options: GovernedPiReviewTurnOptions,
): Promise<{ value: Model<"openai-completions">; configuredApiKey?: string }> {
  const raw = JSON.parse(await readFile(`${options.agentDir}/models.json`, "utf8")) as {
    providers?: Record<string, PortLogProviderEntry>;
  };
  const provider = raw.providers?.[options.provider];
  const entry = provider?.models.find((candidate) => candidate.id === options.model);
  if (!provider || !entry)
    throw new Error(`Configured Pi model not found: ${options.provider}/${options.model}`);
  return {
    configuredApiKey: provider.apiKey,
    value: {
      id: entry.id,
      name: entry.name ?? entry.id,
      api: provider.api,
      provider: options.provider,
      baseUrl: provider.baseUrl,
      reasoning: entry.reasoning ?? false,
      input: entry.input ?? ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: entry.contextWindow ?? 128_000,
      maxTokens: entry.maxTokens ?? 8_192,
    },
  };
}

function isEvidenceParams(value: unknown): value is { artifactId: string; claim: string } {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as Record<string, unknown>).artifactId === "string" &&
    typeof (value as Record<string, unknown>).claim === "string"
  );
}
