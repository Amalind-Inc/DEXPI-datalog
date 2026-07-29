import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { runLocalReviewInspection } from "./local-review-inspection.ts";

type WorkerRequest = {
  projectDirectory: string;
  sessionId: string;
  turnId: string;
  question: string;
  sidecarEndpoint: string;
};

const controller = new AbortController();
process.once("SIGTERM", () => controller.abort());
process.once("SIGINT", () => controller.abort());

const request = JSON.parse(await readStdin()) as WorkerRequest;
const apiKey = process.env.PORTLOG_OPENROUTER_API_KEY;
if (!apiKey) throw new Error("OpenRouter is not configured");
const agentDir = await mkdtemp(join(tmpdir(), "portlog-inspection-agent-"));

try {
  await writeFile(
    join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        openrouter: {
          baseUrl: process.env.PORTLOG_OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1",
          api: "openai-completions",
          models: [{ id: "deepseek/deepseek-v4-flash", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );
  const record = await runLocalReviewInspection({
    projectDirectory: request.projectDirectory,
    turnId: request.turnId,
    question: request.question,
    model: { provider: "openrouter", id: "deepseek/deepseek-v4-flash" },
    signal: controller.signal,
    agentDir,
    cwd: request.projectDirectory,
    apiKey,
    onEvent: (event) => send({ kind: "event", turnId: request.turnId, event }),
    getEvidence: async ({ artifactId, claim }) => {
      if (artifactId !== "topology")
        return {
          citations: [],
          sourceScopeIds: [],
          diagnostics: [
            { code: "unsupported_artifact", message: "Only the prepared topology is available." },
          ],
          uncertainty: "Evidence is insufficient.",
        };
      const response = await fetch(
        `${request.sidecarEndpoint}/api/review/sessions/${encodeURIComponent(request.sessionId)}/topology`,
        { signal: controller.signal },
      );
      if (!response.ok) throw new Error(`Prepared topology is unavailable (${response.status})`);
      return boundedTopologyEvidence(await response.json(), claim);
    },
  });
  send({ kind: "result", record });
} finally {
  await rm(agentDir, { recursive: true, force: true });
}

function boundedTopologyEvidence(payload: unknown, claim: string) {
  const panel = isRecord(payload) ? payload : {};
  const topology = isRecord(panel.topology_view) ? panel.topology_view : panel;
  const nodes = Array.isArray(topology.nodes) ? topology.nodes.filter(isRecord) : [];
  const edges = Array.isArray(topology.edges) ? topology.edges.filter(isRecord) : [];
  const identifiers = Array.from(
    new Set(claim.match(/[A-Za-z]+[-_]?\d+(?:[-_.][A-Za-z0-9]+)*/g) ?? []),
  ).slice(0, 8);
  const matched = nodes
    .filter((node) =>
      identifiers.some((identifier) =>
        JSON.stringify(node).toLowerCase().includes(identifier.toLowerCase()),
      ),
    )
    .slice(0, 12);
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
