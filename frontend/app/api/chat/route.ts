type ChatRequest = {
  messages?: Array<{ role: string; content: string }>;
  sessionId?: string;
  selectedNode?: {
    id: string;
    label: string;
    kind: string;
    description: string;
  } | null;
};

export async function POST(req: Request) {
  const body = (await req.json()) as ChatRequest;
  const prompt = body.messages?.at(-1)?.content ?? "";
  const selectedNode = body.selectedNode ?? null;
  const backendResponse = await askPythonBackend(body.sessionId, prompt);

  if (backendResponse) {
    return Response.json({
      message: backendResponse,
      highlightedNodeIds: selectedNode ? [selectedNode.id] : [],
    });
  }

  const selectedText = selectedNode
    ? `${selectedNode.label} (${selectedNode.kind})`
    : "the currently selected topology scope";
  const mentionedNodeIds = inferHighlights(prompt, selectedNode?.id);

  return Response.json({
    message:
      `I am grounding this QA answer in ${selectedText}. ` +
      `Upload a plant XML to replace the sample graph, then select nodes or paths ` +
      `to focus deterministic checks. For this request I would inspect source scope, ` +
      `derive the topology evidence, and return highlighted equipment/path evidence.`,
    highlightedNodeIds: mentionedNodeIds,
  });
}

async function askPythonBackend(sessionId: string | undefined, prompt: string) {
  const baseUrl = process.env.PYDEXPI_REVIEW_API_URL;
  if (!baseUrl || !sessionId || prompt.trim() === "") return null;

  try {
    const response = await fetch(
      `${baseUrl}/api/review/sessions/${sessionId}/logic-requests/improve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      },
    );
    if (!response.ok) return null;
    const data = (await response.json()) as {
      improvement?: { formal_restatement?: string };
    };
    return data.improvement?.formal_restatement ?? null;
  } catch {
    return null;
  }
}

function inferHighlights(prompt: string, fallbackId: string | undefined) {
  const normalized = prompt.toLowerCase();
  const highlights = new Set<string>();
  if (normalized.includes("p-101") || normalized.includes("pump")) {
    highlights.add("pump-101");
  }
  if (normalized.includes("v-102") || normalized.includes("valve")) {
    highlights.add("valve-102");
  }
  if (normalized.includes("ft-101") || normalized.includes("flow")) {
    highlights.add("flow-transmitter-101");
  }
  if (fallbackId) highlights.add(fallbackId);
  return Array.from(highlights);
}
