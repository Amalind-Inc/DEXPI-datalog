import {
  CheckCircle2,
  Download,
  FileUp,
  Network,
  Play,
  Save,
  Sparkles,
  X,
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

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

type Provider = "openai" | "anthropic" | "gemini" | "openrouter";

type ProviderSettings = {
  provider: Provider;
  model: string;
  configured: boolean;
};

type Improvement = {
  prompt: string;
  formal_restatement: string;
  source_scope_ids: string[];
};

type Confirmation = {
  formal_restatement: string;
  generated_datalog: string;
};

type DeterministicResult = {
  status: string;
  answer: string;
  evidence_highlights: Array<{ object_id: string; label: string }>;
};

type RulePackResult = {
  rule_id: string;
  status: string;
  evidence: string[];
};

type ExportResult = {
  export_id: string;
  status: string;
};

type ReviewAppProps = {
  fetchImpl?: FetchImpl;
  sessionId?: string;
};

const defaultProviderSettings: ProviderSettings = {
  provider: "openrouter",
  model: "openrouter/owl-alpha",
  configured: false,
};

export function ReviewApp({
  fetchImpl = fetch,
  sessionId = "local-review",
}: ReviewAppProps) {
  const [filename, setFilename] = useState("");
  const [status, setStatus] = useState<"idle" | "preparing" | "ready">("idle");
  const [topology, setTopology] = useState<TopologyModel>({ nodes: [], edges: [] });
  const [sourceScopeIds, setSourceScopeIds] = useState<string[]>([]);
  const [providerSettings, setProviderSettings] = useState<ProviderSettings>(
    defaultProviderSettings,
  );
  const [provider, setProvider] = useState<Provider>(defaultProviderSettings.provider);
  const [model, setModel] = useState(defaultProviderSettings.model);
  const [credential, setCredential] = useState("");
  const [prompt, setPrompt] = useState("");
  const [improvement, setImprovement] = useState<Improvement | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [result, setResult] = useState<DeterministicResult | null>(null);
  const [rulePackResult, setRulePackResult] = useState<RulePackResult | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);

  const isReady = status === "ready";
  const selectedNodes = useMemo(
    () => topology.nodes.filter((node) => sourceScopeIds.includes(node.id)),
    [sourceScopeIds, topology.nodes],
  );

  async function handleUpload(file: File) {
    setFilename(file.name);
    setStatus("preparing");
    const response = await requestJson(fetchImpl, "POST", `/api/review/sessions/${sessionId}/prepare`, {
      filename: file.name,
      content: await readFileText(file),
    });
    setTopology(readTopology(response));
    setProviderSettings(readProviderSettings(response.provider_settings));
    setSourceScopeIds(readStringList(response.visible_source_scope));
    setStatus("ready");
  }

  async function selectSourceScope(nodeId: string) {
    const nextScope = Array.from(new Set([...sourceScopeIds, nodeId]));
    setSourceScopeIds(nextScope);
    await requestJson(fetchImpl, "PUT", `/api/review/sessions/${sessionId}/source-scope`, {
      source_scope_ids: nextScope,
    });
  }

  async function removeSourceScope(nodeId: string) {
    const nextScope = sourceScopeIds.filter((id) => id !== nodeId);
    setSourceScopeIds(nextScope);
    await requestJson(fetchImpl, "PUT", `/api/review/sessions/${sessionId}/source-scope`, {
      source_scope_ids: nextScope,
    });
  }

  async function saveProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const response = await requestJson(
      fetchImpl,
      "PUT",
      `/api/review/sessions/${sessionId}/provider-settings`,
      { provider, model, credential },
    );
    setProviderSettings(readProviderSettings(response));
    setCredential("");
  }

  async function improve() {
    const response = await requestJson(
      fetchImpl,
      "POST",
      `/api/review/sessions/${sessionId}/logic-requests/improve`,
      { prompt },
    );
    setImprovement(readImprovement(response.improvement));
  }

  async function confirm() {
    if (!improvement) return;
    const response = await requestJson(
      fetchImpl,
      "POST",
      `/api/review/sessions/${sessionId}/logic-requests/confirm`,
      { improvement },
    );
    setConfirmation(readConfirmation(response.confirmation));
  }

  async function execute() {
    if (!confirmation) return;
    const response = await requestJson(
      fetchImpl,
      "POST",
      `/api/review/sessions/${sessionId}/logic-requests/execute`,
      { confirmation },
    );
    setResult(readResult(response.result));
  }

  async function runRulePack() {
    const response = await requestJson(
      fetchImpl,
      "POST",
      `/api/review/sessions/${sessionId}/rule-pack-results`,
      { rule_id: "selected-scope-discharge" },
    );
    setRulePackResult(readRulePackResult(response));
  }

  async function exportSession() {
    const response = await requestJson(
      fetchImpl,
      "POST",
      `/api/review/sessions/${sessionId}/exports`,
      {},
    );
    setExportResult(readExportResult(response));
  }

  return (
    <main className="review-shell" aria-label="pyDEXPI review workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">OSS v1 review</p>
          <h1>Single-file P&ID topology review</h1>
        </div>
        <label className="upload-control">
          <FileUp size={18} aria-hidden="true" />
          <span>DEXPI XML file</span>
          <input
            aria-label="DEXPI XML file"
            type="file"
            accept=".xml,text/xml,application/xml"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleUpload(file);
            }}
          />
        </label>
      </header>

      <section className="workspace">
        <section className="topology-panel" aria-label="Topology review view">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Topology</p>
              <h2>{filename || "Upload a DEXPI XML file"}</h2>
            </div>
            <span className={`status-pill ${isReady ? "ready" : ""}`}>
              {status === "preparing" ? "Preparing" : isReady ? "Ready" : "Not ready"}
            </span>
          </div>

          {isReady ? (
            <div className="topology-grid">
              <div className="node-list">
                {topology.nodes.map((node) => (
                  <article
                    className={`node-row ${sourceScopeIds.includes(node.id) ? "selected" : ""}`}
                    key={node.id}
                  >
                    <Network size={18} aria-hidden="true" />
                    <div>
                      <strong>{node.label}</strong>
                      <span>{node.kind}</span>
                    </div>
                    <button type="button" onClick={() => void selectSourceScope(node.id)}>
                      Select {node.label}
                    </button>
                  </article>
                ))}
              </div>
              <div className="edge-list" aria-label="Topology connections">
                {topology.edges.map((edge) => (
                  <div className="edge-row" key={edge.id}>
                    <span>{labelFor(topology, edge.source)}</span>
                    <strong>{edge.label}</strong>
                    <span>{labelFor(topology, edge.target)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-state">
              Upload one DEXPI XML file to prepare topology facts and enable review actions.
            </div>
          )}
        </section>

        <aside className="assistant-panel" aria-label="Assistant panel">
          <form className="provider-form" onSubmit={(event) => void saveProvider(event)}>
            <div className="panel-heading compact">
              <div>
                <p className="eyebrow">Provider</p>
                <h2>
                  {providerSettings.provider} / {providerSettings.model}{" "}
                  {providerSettings.configured ? "configured" : "not configured"}
                </h2>
              </div>
            </div>
            <label>
              Provider
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value as Provider)}
                disabled={!isReady}
              >
                <option value="openrouter">OpenRouter</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Gemini</option>
              </select>
            </label>
            <label>
              Model
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                disabled={!isReady}
              />
            </label>
            <label>
              API key
              <input
                type="password"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
                disabled={!isReady}
                autoComplete="off"
              />
            </label>
            <button type="submit" disabled={!isReady || credential.length === 0}>
              <Save size={16} aria-hidden="true" />
              Save provider
            </button>
          </form>

          <section className="scope-panel" aria-label="Source scope">
            <div className="panel-heading compact">
              <div>
                <p className="eyebrow">Source scope</p>
                <h2>{sourceScopeIds.length} selected</h2>
              </div>
            </div>
            {sourceScopeIds.length === 0 ? (
              <p className="muted">Select topology objects to anchor a request.</p>
            ) : (
              <ul className="scope-list">
                {sourceScopeIds.map((id) => (
                  <li key={id}>
                    <span>{id}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${id}`}
                      onClick={() => void removeSourceScope(id)}
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {selectedNodes.length > 0 && (
              <p className="muted">{selectedNodes.map((node) => node.label).join(", ")}</p>
            )}
          </section>

          <section className="logic-panel" aria-label="Logic request">
            <label>
              Logic request
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                disabled={!isReady}
              />
            </label>
            <button type="button" disabled={!isReady || prompt.length === 0} onClick={() => void improve()}>
              <Sparkles size={16} aria-hidden="true" />
              Improve
            </button>
            {improvement && (
              <article className="result-block">
                <h3>Restatement</h3>
                <p>{improvement.formal_restatement}</p>
                <button type="button" onClick={() => void confirm()}>
                  <CheckCircle2 size={16} aria-hidden="true" />
                  Confirm restatement
                </button>
              </article>
            )}
            {confirmation && (
              <article className="result-block">
                <h3>Generated Datalog</h3>
                <pre>{confirmation.generated_datalog}</pre>
                <button type="button" onClick={() => void execute()}>
                  <Play size={16} aria-hidden="true" />
                  Run deterministic answer
                </button>
              </article>
            )}
            {result && (
              <article className="result-block">
                <h3>Deterministic Answer</h3>
                <p>{result.answer}</p>
                <details open>
                  <summary>Evidence</summary>
                  {result.evidence_highlights.map((highlight) => (
                    <p key={highlight.object_id}>Highlighted: {highlight.label}</p>
                  ))}
                </details>
              </article>
            )}
            <button type="button" disabled={!isReady} onClick={() => void runRulePack()}>
              <Play size={16} aria-hidden="true" />
              Run selected rule pack
            </button>
            {rulePackResult && (
              <p className="state-line">Rule pack {rulePackResult.status}</p>
            )}
            <button type="button" disabled={!isReady} onClick={() => void exportSession()}>
              <Download size={16} aria-hidden="true" />
              Export session
            </button>
            {exportResult && (
              <p className="state-line">
                {exportResult.export_id} {exportResult.status}
              </p>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}

async function requestJson(fetchImpl: FetchImpl, method: string, url: string, body: unknown) {
  const response = await fetchImpl(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

function readFileText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(file);
  });
}

function readTopology(value: Record<string, unknown>): TopologyModel {
  const maybeTopology = value.topology;
  if (isTopologyModel(maybeTopology)) return maybeTopology;
  if (isTopologyModel(value)) return value;
  return { nodes: [], edges: [] };
}

function isTopologyModel(value: unknown): value is TopologyModel {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TopologyModel>;
  return Array.isArray(candidate.nodes) && Array.isArray(candidate.edges);
}

function readProviderSettings(value: unknown): ProviderSettings {
  if (!value || typeof value !== "object") return defaultProviderSettings;
  const candidate = value as Partial<ProviderSettings>;
  return {
    provider: isProvider(candidate.provider) ? candidate.provider : defaultProviderSettings.provider,
    model: typeof candidate.model === "string" ? candidate.model : defaultProviderSettings.model,
    configured: candidate.configured === true,
  };
}

function isProvider(value: unknown): value is Provider {
  return value === "openai" || value === "anthropic" || value === "gemini" || value === "openrouter";
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readImprovement(value: unknown): Improvement {
  const candidate = value as Partial<Improvement>;
  return {
    prompt: typeof candidate.prompt === "string" ? candidate.prompt : "",
    formal_restatement:
      typeof candidate.formal_restatement === "string" ? candidate.formal_restatement : "",
    source_scope_ids: readStringList(candidate.source_scope_ids),
  };
}

function readConfirmation(value: unknown): Confirmation {
  const candidate = value as Partial<Confirmation>;
  return {
    formal_restatement:
      typeof candidate.formal_restatement === "string" ? candidate.formal_restatement : "",
    generated_datalog:
      typeof candidate.generated_datalog === "string" ? candidate.generated_datalog : "",
  };
}

function readResult(value: unknown): DeterministicResult {
  const candidate = value as Partial<DeterministicResult>;
  return {
    status: typeof candidate.status === "string" ? candidate.status : "unknown",
    answer: typeof candidate.answer === "string" ? candidate.answer : "",
    evidence_highlights: Array.isArray(candidate.evidence_highlights)
      ? candidate.evidence_highlights.filter(isEvidenceHighlight)
      : [],
  };
}

function isEvidenceHighlight(
  value: unknown,
): value is { object_id: string; label: string } {
  if (!value || typeof value !== "object") return false;
  const candidate = value as { object_id?: unknown; label?: unknown };
  return typeof candidate.object_id === "string" && typeof candidate.label === "string";
}

function readRulePackResult(value: unknown): RulePackResult {
  const candidate = value as Partial<RulePackResult>;
  return {
    rule_id: typeof candidate.rule_id === "string" ? candidate.rule_id : "",
    status: typeof candidate.status === "string" ? candidate.status : "unknown",
    evidence: readStringList(candidate.evidence),
  };
}

function readExportResult(value: unknown): ExportResult {
  const candidate = value as Partial<ExportResult>;
  return {
    export_id: typeof candidate.export_id === "string" ? candidate.export_id : "",
    status: typeof candidate.status === "string" ? candidate.status : "unknown",
  };
}

function labelFor(topology: TopologyModel, nodeId: string) {
  return topology.nodes.find((node) => node.id === nodeId)?.label ?? nodeId;
}
