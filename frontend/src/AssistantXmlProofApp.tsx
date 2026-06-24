import { ThreadPrimitive } from "@assistant-ui/react";
import { FileUp } from "lucide-react";
import { useState } from "react";

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

type TopologyNode = {
  id: string;
  label: string;
  kind: string;
};

type TopologyEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
};

type TopologyModel = {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
};

type AssistantXmlProofAppProps = {
  fetchImpl?: FetchImpl;
  sessionId?: string;
};

export function AssistantXmlProofApp({
  fetchImpl = fetch,
  sessionId = "assistant-proof",
}: AssistantXmlProofAppProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Attach a DEXPI XML file to prepare the graph workspace.",
    },
  ]);
  const [topology, setTopology] = useState<TopologyModel | null>(null);
  const [processingFile, setProcessingFile] = useState<string | null>(null);

  async function uploadXml(file: File) {
    setProcessingFile(file.name);
    setTopology(null);
    appendMessage("user", `Uploaded ${file.name}`);

    try {
      const response = await fetchImpl(`/api/review/sessions/${sessionId}/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          content: await readFileText(file),
        }),
      });
      if (!response.ok) {
        throw new Error(`Prepare failed with status ${response.status}`);
      }
      const body = (await response.json()) as Record<string, unknown>;
      const nextTopology = readTopology(body);
      setTopology(nextTopology);
      appendMessage(
        "assistant",
        `Topology ready: ${nextTopology.nodes.length} objects and ${nextTopology.edges.length} relationships.`,
      );
    } catch {
      appendMessage("assistant", `Upload failed. Try another XML file.`);
    } finally {
      setProcessingFile(null);
    }
  }

  function appendMessage(role: ChatMessage["role"], text: string) {
    setMessages((current) => [
      ...current,
      { id: `${role}-${current.length + 1}`, role, text },
    ]);
  }

  return (
    <main className="assistant-proof-shell" aria-label="assistant XML proof">
      <ThreadPrimitive.Root className="assistant-thread" data-testid="assistant-ui-thread">
        <div className="assistant-thread-viewport">
          <div className="assistant-thread-messages" aria-label="Conversation">
            {messages.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                <span>{message.role === "user" ? "User" : "Assistant"}</span>
                <p>{message.text}</p>
              </article>
            ))}
            {processingFile && (
              <article className="chat-message assistant">
                <span>Assistant</span>
                <p>Processing {processingFile}</p>
              </article>
            )}
          </div>
        </div>

        <form className="assistant-composer" aria-label="XML upload composer">
          <label className="proof-upload-control">
            <FileUp size={16} aria-hidden="true" />
            <span>Attach DEXPI XML</span>
            <input
              aria-label="Attach DEXPI XML"
              type="file"
              accept=".xml,text/xml,application/xml"
              disabled={Boolean(processingFile)}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadXml(file);
              }}
            />
          </label>
        </form>
      </ThreadPrimitive.Root>

      <section className="proof-topology-panel" aria-label="App-owned topology">
        <h2>Graph workspace</h2>
        {topology ? (
          <div className="proof-topology-grid">
            {topology.nodes.map((node) => (
              <article key={node.id}>
                <strong>{node.label}</strong>
                <span>{node.kind}</span>
              </article>
            ))}
          </div>
        ) : (
          <p>No topology loaded.</p>
        )}
      </section>
    </main>
  );
}

function readTopology(value: Record<string, unknown>): TopologyModel {
  const topology = value.topology;
  if (!topology || typeof topology !== "object") {
    return { nodes: [], edges: [] };
  }
  const candidate = topology as Partial<TopologyModel>;
  return {
    nodes: Array.isArray(candidate.nodes) ? candidate.nodes.filter(isTopologyNode) : [],
    edges: Array.isArray(candidate.edges) ? candidate.edges.filter(isTopologyEdge) : [],
  };
}

function isTopologyNode(value: unknown): value is TopologyNode {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TopologyNode>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.label === "string" &&
    typeof candidate.kind === "string"
  );
}

function isTopologyEdge(value: unknown): value is TopologyEdge {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TopologyEdge>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.source === "string" &&
    typeof candidate.target === "string" &&
    typeof candidate.label === "string"
  );
}

function readFileText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(file);
  });
}
