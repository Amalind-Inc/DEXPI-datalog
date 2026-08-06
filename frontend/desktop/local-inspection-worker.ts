import { createHash, randomUUID } from "node:crypto";
import { access, constants, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";

import { GONDOLIN_REVIEW_CANDIDATE_PROFILE, createGondolinQemuExecutor } from "./gondolin-qemu.ts";
import { runHostSafeBash } from "./host-safe-bash.ts";
import {
  createClarificationAskRecord,
  createDeterministicAskRecord,
  runLocalReviewInspection,
} from "./local-review-inspection.ts";
import { enumerateCentrifugalPumpScopes, routeLocalAsk } from "./local-ask-routing.ts";
import {
  createPortLogToolProfile,
  PORTLOG_HOST_POLICY,
  routeCapabilities,
} from "./capability-routing.ts";
import { boundedTopologyEvidence } from "./topology-evidence.ts";
import { upsertLocalTurn } from "./local-project-manifest.cjs";
import { loadLocalProject } from "./local-project-manifest.cjs";
import type { IsolatedCommandResult } from "./isolated-command.ts";
import {
  PortLogPiSessionCoordinator,
  PortLogSessionError,
  type PortLogSessionIdentity,
} from "./pi-session-coordinator.ts";

type WorkerRequest = {
  projectDirectory?: string;
  cwd?: string;
  sessionId?: string;
  turnId: string;
  question: string;
  posture?: "inspect" | "verify" | "review";
  mode?: "inspection" | "chat" | "ask";
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
const NO_PROJECT_SOURCE_DIGEST = `sha256:${"0".repeat(64)}`;
const isChat = request.mode === "chat";
const workingDirectory = isChat
  ? (request.projectDirectory ?? request.cwd ?? process.cwd())
  : (request.cwd ?? request.projectDirectory ?? process.cwd());
const askRoute = request.mode === "ask" ? routeLocalAsk(request.question) : null;
const posture = isChat ? "chat" : (request.posture ?? "inspect");
const qemuPath = process.env.PORTLOG_QEMU_PATH ?? "/opt/homebrew/bin/qemu-system-aarch64";
const qemuAvailable = !isChat && posture === "review" && (await isExecutableFile(qemuPath));
const preparedToolMode = request.mode === "inspection";
const preparedToolPosture = posture === "inspect" || posture === "verify" || posture === "review";
const preparedSession = preparedToolMode && preparedToolPosture && Boolean(request.sessionId);
const toolProfile = createPortLogToolProfile({
  hostEvidence: preparedSession,
  hostRules: preparedSession,
  isolatedExecution: preparedSession,
  policyRoutedBash: preparedSession,
});
const projectManifest = request.projectDirectory
  ? await loadLocalProject(request.projectDirectory)
  : undefined;
const sessionIdentity =
  request.mode === "inspection" && request.projectDirectory && request.sessionId && projectManifest
    ? ({
        workspaceRoot: request.projectDirectory,
        projectId: projectManifest.projectId,
        sourceDigest: projectManifest.source.digest,
        policy: PORTLOG_HOST_POLICY,
        toolProfile,
      } satisfies PortLogSessionIdentity)
    : undefined;
const sessionRoot = request.projectDirectory
  ? join(request.projectDirectory, ".portlog", "sessions")
  : undefined;
let session: PortLogPiSessionCoordinator | undefined;
const modelFreeAsk =
  askRoute?.kind === "clarification" ||
  askRoute?.kind === "rule" ||
  askRoute?.kind === "universal_rule";
if (!apiKey && !modelFreeAsk) throw new Error("The selected model provider is not configured");
const agentDir = await mkdtemp(join(tmpdir(), "portlog-inspection-agent-"));
const sessionKey = isChat ? `chat-${request.turnId}` : request.sessionId;
const workerSessionIdentity =
  sessionIdentity ??
  (isChat
    ? ({
        workspaceRoot: workingDirectory,
        projectId: sessionKey!,
        sourceDigest: NO_PROJECT_SOURCE_DIGEST,
        policy: PORTLOG_HOST_POLICY,
        toolProfile,
      } satisfies PortLogSessionIdentity)
    : undefined);
const workerSessionRoot = sessionRoot ?? (isChat ? join(agentDir, "sessions") : undefined);
// Session identity and runtime setup are derived above so the coordinator sees
// the same effective policy and capability profile used by the worker.

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
  const isolatedExecutor = qemuAvailable
    ? createGondolinQemuExecutor({
        qemuPath,
      })
    : undefined;
  const runIsolatedCommand = preparedSession
    ? async (
        { profileId }: { profileId: string },
        signal: AbortSignal,
      ): Promise<IsolatedCommandResult> => {
        if (!isolatedExecutor) return createUnavailableIsolatedCommandResult(profileId);
        return isolatedExecutor.runIsolatedCommand({
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
        });
      }
    : undefined;
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
  const getTopology = async () => {
    if (!request.sessionId) throw new Error("A prepared session is required for topology checks.");
    const response = await fetch(
      `${request.sidecarEndpoint}/api/review/sessions/${encodeURIComponent(request.sessionId)}/topology`,
      { signal: controller.signal },
    );
    if (!response.ok) throw new Error(`Prepared topology is unavailable (${response.status})`);
    return response.json();
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
  if (workerSessionIdentity && workerSessionRoot && sessionKey && request.mode !== "ask") {
    const sessionOptions = {
      sessionRoot: workerSessionRoot,
      sessionId: sessionKey,
      identity: workerSessionIdentity,
    };
    try {
      session = await PortLogPiSessionCoordinator.open(sessionOptions);
    } catch (error) {
      if (!(error instanceof PortLogSessionError) || error.code !== "not_found") throw error;
      session = await PortLogPiSessionCoordinator.create(sessionOptions);
    }
  }
  let handledAsk = false;
  if (request.mode === "ask") {
    const route = routeLocalAsk(request.question);
    if (route.kind === "clarification") {
      const record = createClarificationAskRecord({
        turnId: request.turnId,
        question: request.question,
        prompt: route.prompt,
        choices: route.choices,
        model: { provider, id: model },
      });
      if (request.projectDirectory) await upsertLocalTurn(request.projectDirectory, record);
      send({ kind: "result", record });
      handledAsk = true;
    } else if (route.kind === "rule" || route.kind === "universal_rule") {
      const scopeEntityIds =
        route.kind === "rule"
          ? [route.scopeEntityId]
          : enumerateCentrifugalPumpScopes(await getTopology());
      const checks: Array<{ scopeEntityId: string; result: unknown }> = [];
      for (const scopeEntityId of scopeEntityIds) {
        let result: unknown;
        try {
          result = await getRuleCheck({
            checkId: route.checkId,
            scopeEntityId,
            signal: controller.signal,
          });
        } catch (error) {
          result = {
            deterministic_result: {
              check_id: route.checkId,
              run_status: "failed",
              outcome: "indeterminate",
              reason_code: "rule_check_unavailable",
              message: error instanceof Error ? error.message : String(error),
            },
          };
        }
        checks.push({ scopeEntityId, result });
      }
      const record = createDeterministicAskRecord({
        turnId: request.turnId,
        question: request.question,
        route: route.kind,
        ruleId: route.checkId,
        scopeEntityIds,
        checks,
        domain: route.kind === "universal_rule" ? route.domain : undefined,
        model: { provider, id: model },
      });
      if (request.projectDirectory) await upsertLocalTurn(request.projectDirectory, record);
      send({ kind: "result", record });
      handledAsk = true;
    }
  }
  if (!handledAsk) {
    const capabilityMode = request.mode === "ask" ? "inspection" : request.mode;
    const capabilities = routeCapabilities({
      mode: capabilityMode,
      posture,
      getEvidence,
      getRuleCheck,
      runIsolatedCommand,
      runHostSafeBash: preparedSession ? runHostSafeBash : undefined,
    });
    const record = await runLocalReviewInspection({
      projectDirectory: isChat ? undefined : request.projectDirectory,
      turnId: request.turnId,
      question: request.question,
      posture,
      model: { provider, id: model },
      signal: controller.signal,
      agentDir,
      cwd: workingDirectory,
      apiKey,
      onEvent: (event) => send({ kind: "event", turnId: request.turnId, event }),
      getEvidence: capabilities.getEvidence,
      getRuleCheck: capabilities.getRuleCheck,
      runIsolatedCommand: capabilities.runIsolatedCommand,
      runHostSafeBash: capabilities.runHostSafeBash,
      session,
    });
    send({ kind: "result", record });
  }
} finally {
  await session?.close();
  await rm(agentDir, { recursive: true, force: true });
}

async function isExecutableFile(filePath: string): Promise<boolean> {
  if (!isAbsolute(filePath)) return false;
  try {
    await access(filePath, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}
function createUnavailableIsolatedCommandResult(profileId: string): IsolatedCommandResult {
  const timestamp = new Date().toISOString();
  return {
    outcome: "unavailable",
    diagnostic: "Isolated execution is unavailable; no host fallback was used.",
    provenance: {
      runId: randomUUID(),
      backend: { id: "portlog-isolated-command-unavailable", version: "1" },
      image: { id: "none", digest: `sha256:${"0".repeat(64)}` },
      policy: { id: PORTLOG_HOST_POLICY.id, digest: PORTLOG_HOST_POLICY.digest },
      commandProfile: {
        id: profileId,
        version: GONDOLIN_REVIEW_CANDIDATE_PROFILE.version,
      },
      startedAt: timestamp,
      completedAt: timestamp,
      durationMs: 0,
      outcome: "unavailable",
    },
  };
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
function send(value: unknown) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}
async function readStdin() {
  let text = "";
  for await (const chunk of process.stdin) text += chunk;
  return text;
}
