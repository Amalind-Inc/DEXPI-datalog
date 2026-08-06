import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

import { Agent } from "@earendil-works/pi-agent-core";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { Model } from "@earendil-works/pi-ai";
import { streamSimple as streamAnthropic } from "@earendil-works/pi-ai/api/anthropic-messages";
import { streamSimple as streamCodex } from "@earendil-works/pi-ai/api/openai-codex-responses";
import { streamSimple as streamOpenAI } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

import {
  createPortLogCapabilityRegistry,
  type PortLogCapabilityRegistry,
} from "./portlog-capability-registry.ts";
import { createGovernedBashTool, type RunGovernedBash } from "./bash-capability.ts";
import { PORTLOG_HOST_POLICY } from "./capability-routing.ts";
import { GONDOLIN_REVIEW_CANDIDATE_PROFILE } from "./gondolin-qemu.ts";
import { toIsolatedCommandToolResult, type IsolatedCommandResult } from "./isolated-command.ts";
import { createPortLogWorkspaceReadTool } from "./pi-workspace-read.ts";

export interface EvidenceRequest {
  artifactId: string;
  claim: string;
  signal: AbortSignal | undefined;
}

export interface RuleCheckRequest {
  checkId: string;
  scopeEntityId: string;
  signal: AbortSignal | undefined;
}

export interface IsolatedCommandToolRequest {
  readonly profileId: string;
}

export type RunGovernedPiIsolatedCommand = (
  request: IsolatedCommandToolRequest,
  signal: AbortSignal,
) => Promise<IsolatedCommandResult>;

type BashToolRoute = "gondolin" | "unavailable";

type BashToolResult = ReturnType<typeof toIsolatedCommandToolResult> & {
  readonly route: BashToolRoute;
  readonly authority: "ordinary";
  readonly profile: {
    readonly id: string;
    readonly version: string;
  };
  readonly output_truncated: false;
};

export interface GovernedPiReviewTurnOptions {
  agentDir: string;
  cwd: string;
  provider: string;
  model: string;
  signal: AbortSignal;
  apiKey?: string;
  workspaceRoot?: string;
  initialMessages?: AgentMessage[];
  sessionId?: string;
  getEvidence?: (request: EvidenceRequest) => Promise<unknown>;
  getRuleCheck?: (request: RuleCheckRequest) => Promise<unknown>;
  capabilityRegistry?: PortLogCapabilityRegistry;
  runIsolatedCommand?: RunGovernedPiIsolatedCommand;
  runHostSafeBash?: RunGovernedBash;
  runGondolinBash?: RunGovernedBash;
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
  api: "openai-completions" | "openai-codex-responses" | "anthropic-messages";
  apiKey?: string;
  models: PortLogModelEntry[];
};

type PortLogModel =
  | Model<"openai-completions">
  | Model<"openai-codex-responses">
  | Model<"anthropic-messages">;

/**
 * Constructs the Pi Agent used by the host-owned session coordinator.
 *
 * This is a low-level construction helper. The coordinator owns the fenced
 * session, prompt admission, native JSONL persistence, and terminal lifecycle.
 */
export async function createPortLogPiAgent(options: GovernedPiReviewTurnOptions) {
  const model = await readPortLogModel(options);
  const apiKey = options.apiKey ?? model.configuredApiKey;
  if (!apiKey) throw new Error(`No PortLog runtime key for ${options.provider}`);
  const readTool = options.workspaceRoot
    ? createPortLogWorkspaceReadTool({
        workspaceRoot: options.workspaceRoot,
        signal: options.signal,
      })
    : null;

  const getEvidence = options.getEvidence;
  const evidenceTool = getEvidence
    ? {
        name: "portlog_evidence",
        label: "PortLog evidence",
        description:
          "Retrieve bounded, read-only evidence from the prepared PortLog review. artifactId must be exactly 'topology'; put equipment tags and identifiers in claim.",
        parameters: Type.Object({
          artifactId: Type.String(),
          claim: Type.String(),
        }),
        executionMode: "sequential" as const,
        async execute(_toolCallId: string, params: unknown, signal?: AbortSignal) {
          if (!isEvidenceParams(params)) throw new Error("Invalid PortLog evidence arguments");
          const result = await getEvidence({
            ...params,
            signal: options.signal,
          });
          if (options.signal.aborted || signal?.aborted)
            throw new DOMException("Inspection cancelled", "AbortError");
          return {
            content: [{ type: "text" as const, text: JSON.stringify(result) }],
            details: {},
          };
        },
      }
    : null;
  const capabilityRegistry =
    options.capabilityRegistry ??
    (options.getRuleCheck
      ? createPortLogCapabilityRegistry({ getRuleCheck: options.getRuleCheck })
      : undefined);
  const ruleCheckTool = capabilityRegistry
    ? {
        name: "portlog_rule_check",
        label: "PortLog deterministic rule check",
        description:
          "Run the named PortLog verification check over one review entity. This tool cannot accept Datalog or change rule parameters.",
        parameters: Type.Object({
          checkId: Type.String(),
          scopeEntityId: Type.String(),
        }),
        executionMode: "sequential" as const,
        async execute(_toolCallId: string, params: unknown, signal?: AbortSignal) {
          if (!isRuleCheckParams(params)) throw new Error("Invalid PortLog rule-check arguments");
          const result = await capabilityRegistry.invoke("portlog_rule_check", {
            checkId: params.checkId,
            scopeEntityId: params.scopeEntityId,
            signal: signal ?? options.signal,
          });
          if (options.signal.aborted || signal?.aborted)
            throw new DOMException("Inspection cancelled", "AbortError");
          return {
            content: [{ type: "text" as const, text: JSON.stringify(result) }],
            details: {},
          };
        },
      }
    : null;
  const isolatedCommandTool = options.runIsolatedCommand
    ? {
        name: "portlog_isolated_command",
        label: "PortLog isolated command",
        description:
          "Run one approved isolated command profile. Supply only the approved profile identifier; arbitrary commands, host paths, credentials, and VM details are not accepted.",
        parameters: Type.Object({
          profileId: Type.String(),
        }),
        executionMode: "sequential" as const,
        async execute(_toolCallId: string, params: unknown, signal?: AbortSignal) {
          if (!isIsolatedCommandParams(params))
            throw new Error("Invalid PortLog isolated-command arguments");
          const linked = linkAbortSignals(options.signal, signal);
          try {
            const result = await options.runIsolatedCommand!(params, linked.signal);
            if (linked.signal.aborted) throw new DOMException("Inspection cancelled", "AbortError");
            return {
              content: [
                {
                  type: "text" as const,
                  text: JSON.stringify(toIsolatedCommandToolResult(result)),
                },
              ],
              details: {},
            };
          } finally {
            linked.dispose();
          }
        },
      }
    : null;

  const bashTool =
    !options.runHostSafeBash && !options.runGondolinBash && options.runIsolatedCommand
      ? {
          name: "bash",
          label: "PortLog bash",
          description:
            "Run the one approved immutable PortLog bash profile in Gondolin. Supply only profileId 'review-bundle-candidate'. Arbitrary command strings, argv, paths, environment, PTY, and background execution are not supported.",
          parameters: Type.Object(
            {
              profileId: Type.String(),
            },
            { additionalProperties: false },
          ),
          executionMode: "sequential" as const,
          async execute(
            _toolCallId: string,
            params: unknown,
            signal?: AbortSignal,
            onUpdate?: (partialResult: {
              content: Array<{ type: "text"; text: string }>;
              details: Record<string, never>;
            }) => void,
          ) {
            if (!isApprovedBashParams(params)) {
              return bashToolResponse(
                createBashPolicyResult(
                  "rejected",
                  "The requested bash profile is not approved; no command was executed.",
                ),
                "unavailable",
              );
            }
            const linked = linkAbortSignals(options.signal, signal);
            try {
              onUpdate?.({
                content: [
                  {
                    type: "text",
                    text: JSON.stringify({
                      route: "gondolin",
                      authority: "ordinary",
                      profile: GONDOLIN_REVIEW_CANDIDATE_PROFILE,
                      phase: "gondolin_started",
                    }),
                  },
                ],
                details: {},
              });
              if (linked.signal.aborted) {
                return bashToolResponse(
                  createBashPolicyResult("cancelled", "The approved bash profile was cancelled."),
                  "gondolin",
                );
              }
              const result = await options.runIsolatedCommand!(
                { profileId: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id },
                linked.signal,
              );
              if (linked.signal.aborted) {
                return bashToolResponse(
                  createBashPolicyResult("cancelled", "The approved bash profile was cancelled."),
                  "gondolin",
                );
              }
              if (!hasApprovedBashProfile(result)) {
                return bashToolResponse(
                  createBashPolicyResult(
                    "rejected",
                    "The isolated executor did not preserve the approved bash profile identity.",
                  ),
                  "gondolin",
                );
              }
              return bashToolResponse(result, "gondolin");
            } catch {
              return bashToolResponse(
                createBashPolicyResult(
                  linked.signal.aborted ? "cancelled" : "failed",
                  linked.signal.aborted
                    ? "The approved bash profile was cancelled."
                    : "The approved bash profile failed before a result was available.",
                ),
                "gondolin",
              );
            } finally {
              linked.dispose();
            }
          },
        }
      : null;
  const governedBashTool =
    options.runHostSafeBash || options.runGondolinBash
      ? createGovernedBashTool({
          workspaceRoot: options.workspaceRoot ?? options.cwd,
          runHostSafe: options.runHostSafeBash,
          runGondolin: options.runGondolinBash,
        })
      : null;

  const tools = [
    ...(readTool ? [readTool] : []),
    ...(evidenceTool ? [evidenceTool] : []),
    ...(ruleCheckTool ? [ruleCheckTool] : []),
    ...(isolatedCommandTool ? [isolatedCommandTool] : []),
    ...(bashTool ? [bashTool] : []),
    ...(governedBashTool ? [governedBashTool] : []),
  ];
  const agent = new Agent({
    initialState: {
      model: model.value,
      tools,
      ...(options.initialMessages ? { messages: options.initialMessages } : {}),
    },
    sessionId: options.sessionId,
    toolExecution: "sequential",
    getApiKey: () => apiKey,
    streamFn: (selectedModel, context, streamOptions) => {
      if (options.signal.aborted) throw new DOMException("Inspection cancelled", "AbortError");
      if (selectedModel.api === "anthropic-messages")
        return streamAnthropic(
          selectedModel as Model<"anthropic-messages">,
          context,
          streamOptions,
        );
      if (selectedModel.api === "openai-codex-responses")
        return streamCodex(selectedModel as Model<"openai-codex-responses">, context, {
          ...streamOptions,
          transport: "sse",
        });
      return streamOpenAI(selectedModel as Model<"openai-completions">, context, streamOptions);
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

async function readPortLogModel(options: GovernedPiReviewTurnOptions): Promise<{
  value: PortLogModel;
  configuredApiKey?: string;
}> {
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
    } as PortLogModel,
  };
}

function isRuleCheckParams(value: unknown): value is { checkId: string; scopeEntityId: string } {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as Record<string, unknown>).checkId === "string" &&
    typeof (value as Record<string, unknown>).scopeEntityId === "string"
  );
}

function isEvidenceParams(value: unknown): value is { artifactId: string; claim: string } {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as Record<string, unknown>).artifactId === "string" &&
    typeof (value as Record<string, unknown>).claim === "string"
  );
}
function isIsolatedCommandParams(value: unknown): value is IsolatedCommandToolRequest {
  if (value === null || typeof value !== "object") return false;
  const profileId = (value as Record<string, unknown>).profileId;
  return typeof profileId === "string" && profileId.length > 0;
}

function isApprovedBashParams(value: unknown): value is IsolatedCommandToolRequest {
  if (!isIsolatedCommandParams(value)) return false;
  const keys = Object.keys(value);
  return (
    keys.length === 1 &&
    keys[0] === "profileId" &&
    value.profileId === GONDOLIN_REVIEW_CANDIDATE_PROFILE.id
  );
}

function hasApprovedBashProfile(result: IsolatedCommandResult): boolean {
  return (
    result.provenance.commandProfile.id === GONDOLIN_REVIEW_CANDIDATE_PROFILE.id &&
    result.provenance.commandProfile.version === GONDOLIN_REVIEW_CANDIDATE_PROFILE.version
  );
}

function createBashPolicyResult(
  outcome: Exclude<IsolatedCommandResult["outcome"], "admitted">,
  diagnostic: string,
): IsolatedCommandResult {
  const timestamp = new Date().toISOString();
  return {
    outcome,
    diagnostic,
    provenance: {
      runId: randomUUID(),
      backend: { id: "portlog-bash-policy", version: "1" },
      image: { id: "none", digest: `sha256:${"0".repeat(64)}` },
      policy: { id: PORTLOG_HOST_POLICY.id, digest: PORTLOG_HOST_POLICY.digest },
      commandProfile: {
        id: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id,
        version: GONDOLIN_REVIEW_CANDIDATE_PROFILE.version,
      },
      startedAt: timestamp,
      completedAt: timestamp,
      durationMs: 0,
      outcome,
    },
  };
}

function bashToolResponse(
  result: IsolatedCommandResult,
  route: BashToolRoute,
): {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, never>;
} {
  const toolResult: BashToolResult = {
    ...toIsolatedCommandToolResult(result),
    route,
    authority: "ordinary",
    profile: {
      id: GONDOLIN_REVIEW_CANDIDATE_PROFILE.id,
      version: GONDOLIN_REVIEW_CANDIDATE_PROFILE.version,
    },
    output_truncated: false,
  };
  return {
    content: [{ type: "text", text: JSON.stringify(toolResult) }],
    details: {},
  };
}

interface LinkedAbortSignal {
  signal: AbortSignal;
  dispose(): void;
}

function linkAbortSignals(...signals: Array<AbortSignal | undefined>): LinkedAbortSignal {
  const controller = new AbortController();
  const activeSignals = signals.filter((signal): signal is AbortSignal => signal !== undefined);
  const abort = () => controller.abort();
  for (const signal of activeSignals) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", abort, { once: true });
  }
  return {
    signal: controller.signal,
    dispose: () => {
      for (const signal of activeSignals) signal.removeEventListener("abort", abort);
    },
  };
}
