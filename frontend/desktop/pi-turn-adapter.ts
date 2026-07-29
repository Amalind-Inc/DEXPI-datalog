import {
  createAgentSession,
  defineTool,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { InMemoryCredentialStore } from "@earendil-works/pi-ai";
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

/**
 * Creates an in-memory Pi agent for one PortLog turn.
 *
 * Pi supplies model streaming and tool-call orchestration only. The caller
 * remains authoritative for review evidence and owns cancellation; Pi JSONL
 * session persistence and all built-in filesystem/shell tools are disabled.
 */
export async function createGovernedPiReviewTurn(options: GovernedPiReviewTurnOptions) {
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(),
    modelsPath: `${options.agentDir}/models.json`,
  });
  if (options.apiKey) modelRuntime.setRuntimeApiKey(options.provider, options.apiKey);
  const model = modelRuntime.getModel(options.provider, options.model);
  if (!model) {
    throw new Error(`Configured Pi model not found: ${options.provider}/${options.model}`);
  }

  const evidenceTool = defineTool({
    name: "portlog_evidence",
    label: "PortLog evidence",
    description: "Retrieve governed PortLog review evidence for one artifact and claim.",
    parameters: Type.Object({
      artifactId: Type.String(),
      claim: Type.String(),
    }),
    execute: async (_toolCallId, params) => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(await options.getEvidence({ ...params, signal: options.signal })),
        },
      ],
      details: {},
    }),
  });

  const { session } = await createAgentSession({
    agentDir: options.agentDir,
    cwd: options.cwd,
    model,
    modelRuntime,
    customTools: [evidenceTool],
    tools: ["portlog_evidence"],
    sessionManager: SessionManager.inMemory(options.cwd),
  });

  const abort = () => session.abort();
  if (options.signal.aborted) {
    await abort();
  } else {
    options.signal.addEventListener("abort", abort, { once: true });
  }

  return {
    session,
    prompt: (text: string) => session.prompt(text),
    dispose: async () => {
      options.signal.removeEventListener("abort", abort);
      await session.dispose();
    },
  };
}
