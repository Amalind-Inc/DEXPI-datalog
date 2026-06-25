import { samplePidGraph } from "@/components/pid/sample-graph";
import type { PidGraph, PidNode, PrepareResult } from "@/components/pid/types";

type PrepareBody = {
  filename?: string;
  content?: string;
};

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as PrepareBody;
  const proxied = await prepareWithPythonBackend(sessionId, body);
  if (proxied) return Response.json(proxied);

  const graph = graphFromXml(body.content ?? "");
  return Response.json({
    status: "ready",
    filename: body.filename ?? "plant.xml",
    graph,
    sourceScopeIds: [graph.nodes[0]?.id ?? "pump-101"],
  } satisfies PrepareResult);
}

async function prepareWithPythonBackend(
  sessionId: string,
  body: PrepareBody,
): Promise<PrepareResult | null> {
  const baseUrl = process.env.PYDEXPI_REVIEW_API_URL;
  if (!baseUrl) return null;

  try {
    const response = await fetch(
      `${baseUrl}/api/review/sessions/${sessionId}/prepare`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    return {
      status: "ready",
      filename: body.filename ?? "plant.xml",
      graph: readTopology(data),
      sourceScopeIds: readStringList(data.visible_source_scope),
    };
  } catch {
    return null;
  }
}

function graphFromXml(content: string): PidGraph {
  const graph = structuredClone(samplePidGraph);
  const labels = Array.from(content.matchAll(/\b(P-\d+|V-\d+|FT-\d+)\b/gi)).map(
    (match) => match[1].toUpperCase(),
  );
  if (labels.length === 0) return graph;

  return {
    ...graph,
    nodes: graph.nodes.map((node) =>
      labels.includes(node.label) ? { ...node, status: "selected" } : node,
    ),
  };
}

function readTopology(data: Record<string, unknown>): PidGraph {
  const topology = (data.topology ?? data) as {
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  };
  const nodes =
    topology.nodes?.map((node): PidNode => {
      const id = String(node.id ?? node.label ?? "node");
      const label = String(node.label ?? id);
      return {
        id,
        label,
        kind: classifyNode(label),
        description: `Prepared topology object ${label}.`,
        status: "normal",
      };
    }) ?? samplePidGraph.nodes;
  const edges =
    topology.edges?.map((edge, index) => ({
      id: String(edge.id ?? `edge-${index}`),
      source: String(edge.source ?? ""),
      target: String(edge.target ?? ""),
      label: String(edge.label ?? "connected to"),
    })) ?? samplePidGraph.edges;
  return { nodes, edges };
}

function classifyNode(label: string) {
  if (label.startsWith("P-")) return "Pump";
  if (label.startsWith("V-")) return "Valve";
  if (label.startsWith("FT-")) return "Instrument";
  if (label.startsWith("L-")) return "Line";
  return "Equipment";
}

function readStringList(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
