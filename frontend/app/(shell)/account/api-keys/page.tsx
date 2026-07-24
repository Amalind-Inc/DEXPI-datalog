"use client";

import { Check, ExternalLink, Loader2, ShieldCheck, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  BYOK_PROVIDERS,
  type ByokProviderInfo,
  type ByokStore,
  clearByokKey,
  maskCredential,
  readByokStore,
  saveByokKey,
  selectActiveProvider,
  setProviderModel,
} from "@/lib/byok-keys";

type TestState =
  | { status: "idle" }
  | { status: "testing" }
  | {
      status: "done";
      ok: boolean;
      message: string;
    };

const EMPTY_STORE: ByokStore = { activeProvider: null, keys: {} };

// Bring-your-own-key management (bead pydexpi-datalog-1-37e2). Keys are held in
// this browser's localStorage and travel to the Python backend only as part of
// the turn that uses them, so there is no server-side key store to leak.
export default function ApiKeysPage() {
  // Rendered empty on the server, then hydrated from localStorage, so SSR and
  // the first client paint agree.
  const [store, setStore] = useState<ByokStore>(EMPTY_STORE);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setStore(readByokStore());
    setHydrated(true);
  }, []);

  const activeProvider = store.activeProvider;

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

      <div className="byok-provider-list">
        {BYOK_PROVIDERS.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            entry={store.keys[provider.id]}
            active={activeProvider === provider.id}
            disabled={!hydrated}
            onStoreChange={setStore}
          />
        ))}
      </div>

      {hydrated && !activeProvider && (
        <p className="byok-fallback-note" data-testid="byok-no-active-key">
          No key is active. Questions fall back to whatever provider the server is configured with,
          or to the built-in stub when it has none.
        </p>
      )}
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
  provider: ByokProviderInfo;
  entry: { credential: string; model: string; savedAt: number } | undefined;
  active: boolean;
  disabled: boolean;
  onStoreChange: (store: ByokStore) => void;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ status: "idle" });

  function apply(change: () => ByokStore) {
    try {
      setError(null);
      onStoreChange(change());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this key.");
    }
  }

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
            ? `${provider.label} accepted this key.`
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
          <h2 className="byok-card-title">{provider.label}</h2>
          <a
            className="byok-card-console"
            href={provider.consoleUrl}
            target="_blank"
            rel="noreferrer"
          >
            Get a key
            <ExternalLink size={12} aria-hidden="true" />
          </a>
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
          <span className="byok-empty-badge">Not configured</span>
        )}
      </header>

      {entry ? (
        <div className="byok-card-body">
          <dl className="byok-key-summary">
            <div>
              <dt>Key</dt>
              <dd data-testid={`byok-masked-${provider.id}`}>{maskCredential(entry.credential)}</dd>
            </div>
            <div>
              <dt>Added</dt>
              <dd>{entry.savedAt ? new Date(entry.savedAt).toLocaleDateString() : "—"}</dd>
            </div>
          </dl>

          <label className="byok-field">
            <span className="byok-field-label">Model</span>
            <select
              className="byok-select"
              value={entry.model}
              data-testid={`byok-model-${provider.id}`}
              onChange={(event) => apply(() => setProviderModel(provider.id, event.target.value))}
            >
              {provider.models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
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
                apply(() => clearByokKey(provider.id));
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Remove
            </button>
          </div>
        </div>
      ) : (
        <div className="byok-card-body">
          <label className="byok-field">
            <span className="byok-field-label">API key</span>
            <input
              className="byok-input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={`${provider.keyPrefix}…`}
              value={draft}
              data-testid={`byok-input-${provider.id}`}
              onChange={(event) => setDraft(event.target.value)}
            />
          </label>
          <div className="byok-card-actions">
            <Button
              type="button"
              disabled={disabled || draft.trim() === ""}
              data-testid={`byok-save-${provider.id}`}
              onClick={() => {
                apply(() => saveByokKey({ provider: provider.id, credential: draft }));
                setDraft("");
                setTest({ status: "idle" });
              }}
            >
              Save key
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={draft.trim() === "" || test.status === "testing"}
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
