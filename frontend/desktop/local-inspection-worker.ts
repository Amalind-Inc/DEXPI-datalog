import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { GONDOLIN_REVIEW_CANDIDATE_PROFILE, createGondolinQemuExecutor } from "./gondolin-qemu.ts";
import { runLocalReviewInspection } from "./local-review-inspection.ts";

type WorkerRequest = {
  projectDirectory?: string;
  cwd?: string;
  sessionId?: string;
  turnId: string;
  question: string;
  posture?: "inspect" | "verify" | "review";
  mode?: "inspection" | "chat";
  sidecarEndpoint: string;
  provider?: "openrouter" | "anthropic" | "openai-codex";
  model?: string;
  baseUrl?: string;
};

const controller = new AbortController();
process.once("SIGTERM", () => controller.abort());
process.once("SIGINT", () => controller.abort());

const request = JSON.parse(await readStdin()) as WorkerRequest;
const provider =
  request.provider ??
  (process.env.PORTLOG_RUNTIME_PROVIDER as
    | "openrouter"
    | "anthropic"
    | "openai-codex"
    | undefined) ??
  "openrouter";
const model =
  request.model ??
  process.env.PORTLOG_RUNTIME_MODEL ??
  (provider === "anthropic"
    ? "claude-sonnet-4-5"
    : provider === "openai-codex"
      ? "gpt-5.4"
      : "deepseek/deepseek-v4-flash");
const baseUrl =
  request.baseUrl ??
  process.env.PORTLOG_RUNTIME_BASE_URL ??
  (provider === "anthropic"
    ? "https://api.anthropic.com"
    : provider === "openai-codex"
      ? "https://chatgpt.com/backend-api"
      : "https://openrouter.ai/api/v1");
const apiKey = process.env.PORTLOG_RUNTIME_API_KEY ?? process.env.PORTLOG_OPENROUTER_API_KEY;
if (!apiKey) throw new Error("The selected model provider is not configured");
const agentDir = await mkdtemp(join(tmpdir(), "portlog-inspection-agent-"));

try {
  await writeFile(
    join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        [provider]: {
          baseUrl,
          api:
            provider === "anthropic"
              ? "anthropic-messages"
              : provider === "openai-codex"
                ? "openai-codex-responses"
                : "openai-completions",
          models: [
            {
              id: model,
              reasoning: provider === "openai-codex",
              input: ["text"],
            },
          ],
        },
      },
    }),
  );
  const isChat = request.mode === "chat";
  const isolatedExecutor =
    !isChat && request.posture === "review"
      ? createGondolinQemuExecutor({
          qemuPath: process.env.PORTLOG_QEMU_PATH ?? "/opt/homebrew/bin/qemu-system-aarch64",
        })
      : undefined;
  const runIsolatedCommand = isolatedExecutor
    ? async ({ profileId }: { profileId: string }, signal: AbortSignal) =>
        isolatedExecutor.runIsolatedCommand({
          runId: randomUUID(),
          inputBundle: createE06ReviewInputBundle(),
          commandProfile: { id: profileId, version: GONDOLIN_REVIEW_CANDIDATE_PROFILE.version },
          limits: {
            maxDurationMs: 60_000,
            maxMemoryBytes: 2 * 1024 * 1024 * 1024,
            maxCpuSeconds: 30,
            maxScratchBytes: 64 * 1024,
            maxOutputCount: 1,
            maxOutputBytes: 64 * 1024,
            maxInputFiles: 16,
            maxInputBytes: 4 * 1024 * 1024,
          },
          signal,
        })
    : undefined;
  const workingDirectory = request.cwd ?? request.projectDirectory ?? process.cwd();
  const getEvidence = async ({ artifactId, claim }: { artifactId: string; claim: string }) => {
    if (!request.sessionId) throw new Error("A prepared session is required for P&ID evidence.");
    if (artifactId !== "topology")
      return {
        citations: [],
        sourceScopeIds: [],
        diagnostics: [
          {
            code: "unsupported_artifact",
            message: "Only the prepared topology is available.",
          },
        ],
        uncertainty: "Evidence is insufficient.",
      };
    const response = await fetch(
      `${request.sidecarEndpoint}/api/review/sessions/${encodeURIComponent(request.sessionId)}/topology`,
      { signal: controller.signal },
    );
    if (!response.ok) throw new Error(`Prepared topology is unavailable (${response.status})`);
    return boundedTopologyEvidence(await response.json(), claim);
  };
  const getRuleCheck = async ({
    checkId,
    scopeEntityId,
    signal,
  }: {
    checkId: string;
    scopeEntityId: string;
    signal?: AbortSignal;
  }) => {
    if (!request.sessionId) throw new Error("A prepared session is required for rule checks.");
    const response = await fetch(
      `${request.sidecarEndpoint}/api/review/sessions/${encodeURIComponent(request.sessionId)}/governed-checks`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          check_id: checkId,
          scope_entity_id: scopeEntityId,
        }),
        signal: signal ?? controller.signal,
      },
    );
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Governed rule check rejected (${response.status}): ${body.slice(0, 500)}`);
    }
    return await response.json();
  };
  const record = await runLocalReviewInspection({
    projectDirectory: isChat ? undefined : request.projectDirectory,
    turnId: request.turnId,
    question: request.question,
    posture: isChat ? "chat" : request.posture,
    model: { provider, id: model },
    signal: controller.signal,
    agentDir,
    cwd: workingDirectory,
    apiKey,
    onEvent: (event) => send({ kind: "event", turnId: request.turnId, event }),
    getEvidence: isChat ? undefined : getEvidence,
    getRuleCheck: isChat ? undefined : getRuleCheck,
    runIsolatedCommand,
  });
  send({ kind: "result", record });
} finally {
  await rm(agentDir, { recursive: true, force: true });
}

function createE06ReviewInputBundle() {
  const bytes = new TextEncoder().encode(
    '{"fixture":"E06 Pump, HeatExchanger, Nozzles Connected With PNS","purpose":"bounded native review"}',
  );
  const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  return {
    bundleId: "e06-review-input",
    digest,
    files: [
      {
        relativePath: "review.json",
        bytes,
        digest,
      },
    ],
  };
}
function boundedTopologyEvidence(payload: unknown, claim: string) {
  const panel = isRecord(payload) ? payload : {};
  const topology = isRecord(panel.topology_view) ? panel.topology_view : panel;
  const nodes = Array.isArray(topology.nodes) ? topology.nodes.filter(isRecord) : [];
  const edges = Array.isArray(topology.edges) ? topology.edges.filter(isRecord) : [];
  const identifiers = Array.from(
    new Set(claim.match(/[A-Za-z]+[-_]?\d+(?:[-_.][A-Za-z0-9]+)*/g) ?? []),
  ).slice(0, 8);
  const matched = (
    identifiers.length === 0
      ? nodes
      : nodes.filter((node) =>
          identifiers.some((identifier) =>
            JSON.stringify(node).toLowerCase().includes(identifier.toLowerCase()),
          ),
        )
  ).slice(0, 12);
  const matchedIds = matched.map(readId).filter((id): id is string => id !== null);
  const relationships = edges
    .filter((edge) => matchedIds.some((id) => edgeTouches(edge, id)))
    .slice(0, 25);
  const relatedIds = relationships.flatMap(edgeEndpointIds);
  const citations = Array.from(new Set([...matchedIds, ...relatedIds])).slice(0, 25);
  return {
    artifactId: "topology",
    claim,
    entities: matched,
    relationships,
    citations,
    sourceScopeIds: citations,
    diagnostics: citations.length
      ? []
      : [
          {
            code: "no_matching_evidence",
            message: "No bounded topology evidence matched the requested identifiers.",
          },
        ],
    uncertainty: citations.length ? null : "Evidence is insufficient for this question.",
  };
}

function readId(value: Record<string, unknown>) {
  return typeof value.id === "string" ? value.id : null;
}
function edgeEndpointIds(edge: Record<string, unknown>) {
  return [edge.source, edge.target, edge.source_id, edge.target_id, edge.from, edge.to].filter(
    (value): value is string => typeof value === "string",
  );
}
function edgeTouches(edge: Record<string, unknown>, id: string) {
  return edgeEndpointIds(edge).includes(id);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function send(value: unknown) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}
async function readStdin() {
  let text = "";
  for await (const chunk of process.stdin) text += chunk;
  return text;
}
