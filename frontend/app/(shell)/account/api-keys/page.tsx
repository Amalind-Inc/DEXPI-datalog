"use client";

import {
  Check,
  ExternalLink,
  Loader2,
  Search,
  ShieldCheck,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  type ByokStore,
  clearByokKey,
  maskCredential,
  readByokStore,
  saveByokKey,
  selectActiveProvider,
  setProviderModel,
} from "@/lib/byok-keys";

type ProviderEntry = {
  id: string;
  name: string;
  doc: string;
  modelCount: number;
  isLocal: boolean;
};

type CatalogModel = { id: string; name: string; context: number | null; reasoning: boolean };

const EMPTY_STORE: ByokStore = { activeProvider: null, keys: {} };

// Bring-your-own-key management (beads 37e2 / hvso). Keys are held in this
// browser's localStorage and travel to the Python backend only as part of the
// turn that uses them, so there is no server-side key store to leak. The
// provider list is the vendored models.dev catalogue (ADR 0015), which is why
// it is searchable rather than a short hand-written list.
export default function ApiKeysPage() {
  const [store, setStore] = useState<ByokStore>(EMPTY_STORE);
  const [hydrated, setHydrated] = useState(false);
  const [providers, setProviders] = useState<ProviderEntry[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setStore(readByokStore());
    setHydrated(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/byok/catalog")
      .then(async (res) => {
        if (!res.ok) throw new Error(`catalogue request failed (${res.status})`);
        const data = (await res.json()) as { providers: ProviderEntry[] };
        if (!cancelled) setProviders(data.providers);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCatalogError(error instanceof Error ? error.message : "Could not load providers.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const configured = useMemo(
    () => (providers ?? []).filter((p) => store.keys[p.id]),
    [providers, store],
  );
  const available = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rest = (providers ?? []).filter((p) => !store.keys[p.id]);
    if (!needle) return rest;
    return rest.filter(
      (p) => p.name.toLowerCase().includes(needle) || p.id.toLowerCase().includes(needle),
    );
  }, [providers, store, query]);

  return (
    <div className="shell-page shell-page-wide" data-testid="api-keys-page">
      <div className="rule-pack-page-header">
        <div>
          <h1 className="shell-page-title">API keys</h1>
          <p className="shell-page-empty">
            Bring your own key. Add a credential for any supported provider, then choose which one
            answers your questions. Keys are stored in this browser only and are sent to the review
            backend solely to run the model you selected.
          </p>
        </div>
      </div>

      <p className="byok-privacy-note">
        <ShieldCheck size={14} aria-hidden="true" />
        <span>
          Nothing is written to the server. Clearing your browser storage removes every key.
        </span>
      </p>

      {catalogError && (
        <p className="byok-message byok-message--bad" role="alert">
          <TriangleAlert size={13} aria-hidden="true" />
          {catalogError}
        </p>
      )}

      {configured.length > 0 && (
        <section className="byok-section">
          <h2 className="byok-section-title">Your providers</h2>
          <div className="byok-provider-list">
            {configured.map((provider) => (
              <ProviderCard
                key={provider.id}
                provider={provider}
                entry={store.keys[provider.id]}
                active={store.activeProvider === provider.id}
                disabled={!hydrated}
                onStoreChange={setStore}
              />
            ))}
          </div>
        </section>
      )}

      {hydrated && configured.length > 0 && !store.activeProvider && (
        <p className="byok-fallback-note" data-testid="byok-no-active-key">
          No key is active. Questions fall back to whatever provider the server is configured with,
          or to the built-in stub when it has none.
        </p>
      )}

      <section className="byok-section">
        <h2 className="byok-section-title">
          Add a provider
          {providers && <span className="byok-section-count">{providers.length} available</span>}
        </h2>
        <label className="pid-search byok-search">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Search providers</span>
          <input
            type="text"
            placeholder="Search providers…"
            value={query}
            data-testid="byok-provider-search"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        {providers === null && !catalogError && <p className="shell-page-empty">Loading…</p>}
        {providers !== null && available.length === 0 && (
          <p className="shell-page-empty">No providers match “{query}”.</p>
        )}

        <div className="byok-provider-list">
          {available.map((provider) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              entry={undefined}
              active={false}
              disabled={!hydrated}
              onStoreChange={setStore}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function ProviderCard({
  provider,
  entry,
  active,
  disabled,
  onStoreChange,
}: {
  provider: ProviderEntry;
  entry: { credential: string; model: string; savedAt: number } | undefined;
  active: boolean;
  disabled: boolean;
  onStoreChange: (store: ByokStore) => void;
}) {
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState(entry?.model ?? "");
  const [models, setModels] = useState<CatalogModel[] | null>(null);
  const [expanded, setExpanded] = useState(Boolean(entry));
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<
    { status: "idle" | "testing" } | { status: "done"; ok: boolean; message: string }
  >({ status: "idle" });

  // Models are fetched per provider: the full catalogue is far too large to
  // hand to the browser in one go.
  useEffect(() => {
    if (!expanded || models !== null || provider.isLocal) return;
    let cancelled = false;
    fetch(`/api/byok/catalog?provider=${encodeURIComponent(provider.id)}`)
      .then(async (res) => (await res.json()) as { models: CatalogModel[] })
      .then((data) => {
        if (cancelled) return;
        setModels(data.models);
        setModel((current) => current || data.models[0]?.id || "");
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [expanded, models, provider.id, provider.isLocal]);

  const apply = useCallback(
    (change: () => ByokStore) => {
      try {
        setError(null);
        onStoreChange(change());
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not update this key.");
      }
    },
    [onStoreChange],
  );

  async function runTest(credential: string) {
    setTest({ status: "testing" });
    try {
      const response = await fetch("/api/byok/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: provider.id, credential }),
      });
      const result = (await response.json()) as { ok?: boolean; message?: string };
      setTest({
        status: "done",
        ok: result.ok === true,
        message:
          result.ok === true
            ? `${provider.name} accepted this key.`
            : (result.message ?? "The provider rejected this key."),
      });
    } catch (cause) {
      setTest({
        status: "done",
        ok: false,
        message: cause instanceof Error ? cause.message : "The provider could not be reached.",
      });
    }
  }

  return (
    <section className="byok-card" data-testid={`byok-card-${provider.id}`}>
      <header className="byok-card-header">
        <div>
          <h3 className="byok-card-title">{provider.name}</h3>
          <div className="byok-card-meta">
            {provider.isLocal ? (
              <span>Local server · any pulled model</span>
            ) : (
              <span>{provider.modelCount} tool-capable models</span>
            )}
            {provider.doc && (
              <a className="byok-card-console" href={provider.doc} target="_blank" rel="noreferrer">
                Get a key
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
        {entry ? (
          active ? (
            <span className="byok-active-badge" data-testid={`byok-active-${provider.id}`}>
              <Check size={13} aria-hidden="true" />
              Active
            </span>
          ) : (
            <button
              type="button"
              className="calm-chat-bar-btn"
              data-testid={`byok-activate-${provider.id}`}
              onClick={() => apply(() => selectActiveProvider(provider.id))}
            >
              Use this provider
            </button>
          )
        ) : (
          <button
            type="button"
            className="calm-chat-bar-btn"
            data-testid={`byok-add-${provider.id}`}
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? "Cancel" : "Add key"}
          </button>
        )}
      </header>

      {entry && (
        <div className="byok-card-body">
          <dl className="byok-key-summary">
            <div>
              <dt>Key</dt>
              <dd data-testid={`byok-masked-${provider.id}`}>
                {provider.isLocal && !entry.credential ? "local" : maskCredential(entry.credential)}
              </dd>
            </div>
            <div>
              <dt>Added</dt>
              <dd>{entry.savedAt ? new Date(entry.savedAt).toLocaleDateString() : "—"}</dd>
            </div>
          </dl>

          <label className="byok-field">
            <span className="byok-field-label">Model</span>
            <ModelControl
              provider={provider}
              models={models}
              value={entry.model}
              testId={`byok-model-${provider.id}`}
              onChange={(next) => apply(() => setProviderModel(provider.id, next))}
            />
          </label>

          <div className="byok-card-actions">
            <Button
              type="button"
              variant="outline"
              disabled={test.status === "testing"}
              onClick={() => void runTest(entry.credential)}
            >
              {test.status === "testing" && <Loader2 size={14} className="byok-spin" />}
              Test key
            </Button>
            <button
              type="button"
              className="byok-remove-btn"
              data-testid={`byok-remove-${provider.id}`}
              onClick={() => {
                setTest({ status: "idle" });
                setExpanded(false);
                apply(() => clearByokKey(provider.id));
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Remove
            </button>
          </div>
        </div>
      )}

      {!entry && expanded && (
        <div className="byok-card-body">
          {!provider.isLocal && (
            <label className="byok-field">
              <span className="byok-field-label">API key</span>
              <input
                className="byok-input"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={`Paste your ${provider.name} key`}
                value={draft}
                data-testid={`byok-input-${provider.id}`}
                onChange={(event) => setDraft(event.target.value)}
              />
            </label>
          )}

          <label className="byok-field">
            <span className="byok-field-label">Model</span>
            <ModelControl
              provider={provider}
              models={models}
              value={model}
              testId={`byok-model-${provider.id}`}
              onChange={setModel}
            />
          </label>

          <div className="byok-card-actions">
            <Button
              type="button"
              disabled={
                disabled || model.trim() === "" || (!provider.isLocal && draft.trim() === "")
              }
              data-testid={`byok-save-${provider.id}`}
              onClick={() => {
                apply(() =>
                  saveByokKey({
                    provider: provider.id,
                    credential: draft,
                    model,
                    isLocal: provider.isLocal,
                  }),
                );
                setDraft("");
                setTest({ status: "idle" });
              }}
            >
              Save key
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={(!provider.isLocal && draft.trim() === "") || test.status === "testing"}
              onClick={() => void runTest(draft)}
            >
              {test.status === "testing" && <Loader2 size={14} className="byok-spin" />}
              Test key
            </Button>
          </div>
        </div>
      )}

      {error && (
        <p className="byok-message byok-message--bad" role="alert">
          <TriangleAlert size={13} aria-hidden="true" />
          {error}
        </p>
      )}
      {test.status === "done" && (
        <p
          className={test.ok ? "byok-message byok-message--good" : "byok-message byok-message--bad"}
          data-testid={`byok-test-result-${provider.id}`}
          role="status"
        >
          {test.ok ? (
            <Check size={13} aria-hidden="true" />
          ) : (
            <TriangleAlert size={13} aria-hidden="true" />
          )}
          {test.message}
        </p>
      )}
    </section>
  );
}

/** A local server's models cannot be enumerated, so it gets a free-text field;
 * catalogued providers get a select. */
function ModelControl({
  provider,
  models,
  value,
  testId,
  onChange,
}: {
  provider: ProviderEntry;
  models: CatalogModel[] | null;
  value: string;
  testId: string;
  onChange: (next: string) => void;
}) {
  if (provider.isLocal) {
    return (
      <input
        className="byok-input"
        type="text"
        spellCheck={false}
        placeholder="e.g. ornith:35b"
        value={value}
        data-testid={testId}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  if (models === null) {
    return <select className="byok-select" disabled data-testid={testId} />;
  }
  return (
    <select
      className="byok-select"
      value={value}
      data-testid={testId}
      onChange={(event) => onChange(event.target.value)}
    >
      {models.map((entry) => (
        <option key={entry.id} value={entry.id}>
          {entry.name} — {entry.id}
        </option>
      ))}
    </select>
  );
}
