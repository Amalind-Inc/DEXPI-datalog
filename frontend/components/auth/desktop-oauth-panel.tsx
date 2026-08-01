"use client";

import { Loader2, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import type {
  ClaudeAuthState,
  CodexAuthState,
  DesktopOAuthState,
  OAuthProviderId,
} from "@/lib/desktop-auth-types";

type DesktopBridge = NonNullable<Window["portlogDesktop"]>;
type AuthState = DesktopOAuthState;
type ProviderId = OAuthProviderId;
type BusyProvider = ProviderId | "anthropic-logout" | "openai-codex-logout" | null;

const MODEL_BY_PROVIDER: Record<ProviderId, string> = {
  anthropic: "claude-sonnet-4-5",
  "openai-codex": "gpt-5.4",
};

export function DesktopOAuthPanel() {
  const [claude, setClaude] = useState<ClaudeAuthState | null>(null);
  const [codex, setCodex] = useState<CodexAuthState | null>(null);
  const [busy, setBusy] = useState<BusyProvider>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const desktop = getDesktop();
    if (!desktop) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void Promise.all([desktop.claudeAuthStatus(), desktop.codexAuthStatus()])
      .then(([claudeStatus, codexStatus]) => {
        if (cancelled) return;
        setClaude(claudeStatus);
        setCodex(codexStatus);
      })
      .catch((error: unknown) => {
        if (!cancelled) setMessage(errorMessage(error, "Could not read desktop account status."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (typeof window === "undefined" || !window.portlogDesktop) return null;

  const loginClaude = async () => {
    const desktop = getDesktop();
    if (!desktop) return;
    setBusy("anthropic");
    setMessage(null);
    try {
      setClaude(await desktop.claudeLogin());
    } catch (error) {
      setMessage(errorMessage(error, "Claude login failed."));
    } finally {
      setBusy(null);
    }
  };

  const loginCodex = async (method: "browser" | "device_code") => {
    const desktop = getDesktop();
    if (!desktop) return;
    setBusy("openai-codex");
    setMessage(null);
    const poll = window.setInterval(() => {
      void desktop
        .codexAuthStatus()
        .then(setCodex)
        .catch(() => undefined);
    }, 250);
    try {
      setCodex(await desktop.codexLogin(method));
    } catch (error) {
      setMessage(errorMessage(error, "OpenAI Codex login failed."));
    } finally {
      window.clearInterval(poll);
      setBusy(null);
    }
  };

  const logout = async (provider: ProviderId) => {
    const desktop = getDesktop();
    if (!desktop) return;
    const logoutBusy = provider === "anthropic" ? "anthropic-logout" : "openai-codex-logout";
    setBusy(logoutBusy);
    setMessage(null);
    try {
      if (provider === "anthropic") setClaude(await desktop.claudeLogout());
      else setCodex(await desktop.codexLogout());
    } catch (error) {
      setMessage(errorMessage(error, "Could not disconnect the account."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      className="desktop-oauth-panel"
      data-testid="desktop-oauth-panel"
      aria-labelledby="desktop-oauth-title"
    >
      <div className="desktop-oauth-panel-intro">
        <div className="desktop-oauth-index" aria-hidden="true">
          <span>AUTH</span>
          <strong>02</strong>
        </div>
        <div className="desktop-oauth-copy">
          <p className="desktop-oauth-eyebrow">Desktop identity</p>
          <h2 id="desktop-oauth-title">Connected accounts</h2>
          <p>
            Sign in with a provider account to run local inspections from the Electron app. OAuth
            tokens stay in this Mac&apos;s Keychain.
          </p>
        </div>
        <div className="desktop-oauth-privacy">
          <ShieldCheck size={15} aria-hidden="true" />
          <span>Keychain-owned</span>
        </div>
      </div>

      <div className="desktop-oauth-grid">
        <OAuthCard
          provider="anthropic"
          state={claude}
          loading={loading}
          busy={busy}
          onLogin={() => void loginClaude()}
          onLogout={() => void logout("anthropic")}
        />
        <OAuthCard
          provider="openai-codex"
          state={codex}
          loading={loading}
          busy={busy}
          onLogin={(method = "browser") => void loginCodex(method)}
          onLogout={() => void logout("openai-codex")}
        />
      </div>

      {message ? (
        <p className="desktop-oauth-message" role="alert">
          {message}
        </p>
      ) : null}
    </section>
  );
}

function OAuthCard({
  provider,
  state,
  loading,
  busy,
  onLogin,
  onLogout,
}: {
  provider: ProviderId;
  state: AuthState | null;
  loading: boolean;
  busy: BusyProvider;
  onLogin: (method?: "browser" | "device_code") => void;
  onLogout: () => void;
}) {
  const connected = state?.state === "logged_in";
  const waiting =
    busy === provider ||
    state?.state === "opening_browser" ||
    state?.state === "waiting_for_authorization";
  const logoutBusy = busy === `${provider}-logout`;
  const name = provider === "anthropic" ? "Claude" : "OpenAI Codex";
  const organization = provider === "anthropic" ? "Anthropic" : "OpenAI";
  const monogram = provider === "anthropic" ? "CL" : "CX";
  const status = loading ? "Checking" : authStatusLabel(state);

  return (
    <article
      className={`desktop-oauth-card${connected ? " desktop-oauth-card--connected" : ""}`}
      data-testid={`desktop-oauth-${provider}`}
    >
      <header className="desktop-oauth-card-header">
        <span className="desktop-oauth-monogram" aria-hidden="true">
          {monogram}
        </span>
        <div className="desktop-oauth-provider">
          <p>{organization}</p>
          <h3>{name}</h3>
        </div>
        <span
          className={`desktop-oauth-status desktop-oauth-status--${statusClass(state, loading)}`}
          data-testid={`desktop-oauth-status-${provider}`}
        >
          <span aria-hidden="true" />
          {status}
        </span>
      </header>

      <div className="desktop-oauth-card-details">
        <div>
          <span>AUTH METHOD</span>
          <strong>OAuth 2.0</strong>
        </div>
        <div>
          <span>DESKTOP MODEL</span>
          <code>{MODEL_BY_PROVIDER[provider]}</code>
        </div>
      </div>

      {state?.provider === "openai-codex" && state.deviceCode ? (
        <p className="desktop-oauth-device-code" role="status">
          Enter <strong>{state.deviceCode.userCode}</strong> at {state.deviceCode.verificationUri}.
        </p>
      ) : null}

      {state?.error ? (
        <p className="desktop-oauth-error" role="alert">
          {state.error}
        </p>
      ) : null}

      <div className="desktop-oauth-actions">
        {connected ? (
          <button
            type="button"
            className="desktop-oauth-button desktop-oauth-button--quiet"
            onClick={onLogout}
            disabled={logoutBusy}
          >
            {logoutBusy ? (
              <Loader2 size={14} className="byok-spin" />
            ) : (
              <LogOut size={14} aria-hidden="true" />
            )}
            {logoutBusy ? "Disconnecting…" : "Disconnect"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className="desktop-oauth-button desktop-oauth-button--primary"
              onClick={() => onLogin("browser")}
              disabled={waiting || loading}
            >
              {waiting ? <Loader2 size={14} className="byok-spin" /> : null}
              {waiting ? "Waiting for authorization…" : `Connect ${name}`}
            </button>
            {provider === "openai-codex" ? (
              <button
                type="button"
                className="desktop-oauth-button desktop-oauth-button--secondary"
                onClick={() => onLogin("device_code")}
                disabled={waiting || loading}
              >
                Use device code
              </button>
            ) : null}
          </>
        )}
      </div>
    </article>
  );
}

function getDesktop(): DesktopBridge | null {
  return typeof window === "undefined" ? null : (window.portlogDesktop ?? null);
}

function authStatusLabel(state: AuthState | null): string {
  switch (state?.state) {
    case "logged_in":
      return "Connected";
    case "opening_browser":
    case "waiting_for_authorization":
      return "Authorizing";
    case "refresh_failed":
      return "Reconnect needed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Not connected";
  }
}

function statusClass(state: AuthState | null, loading: boolean): string {
  if (loading) return "checking";
  if (state?.state === "logged_in") return "connected";
  if (state?.state === "refresh_failed") return "attention";
  if (state?.state === "opening_browser" || state?.state === "waiting_for_authorization")
    return "waiting";
  return "idle";
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
