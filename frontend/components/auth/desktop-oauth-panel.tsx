"use client";

import { Loader2, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import {
  DESKTOP_CHAT_PROVIDER_KEY,
  type ClaudeAuthState,
  type CodexAuthState,
  type DesktopOAuthState,
  type OAuthProviderId,
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
  const [selectedProvider, setSelectedProvider] = useState<ProviderId | null>(null);
  const [desktopReady, setDesktopReady] = useState(false);

  useEffect(() => {
    const desktop = getDesktop();
    if (!desktop) {
      setLoading(false);
      return;
    }
    setDesktopReady(true);
    let cancelled = false;
    const selectedProviderPromise =
      desktop.getSelectedChatProvider?.().catch(() => null) ?? Promise.resolve(null);
    void Promise.all([
      desktop.claudeAuthStatus(),
      desktop.codexAuthStatus(),
      selectedProviderPromise,
    ])
      .then(([claudeStatus, codexStatus, storedProvider]) => {
        if (cancelled) return;
        setClaude(claudeStatus);
        setCodex(codexStatus);
        const saved = storedProvider ?? readSelectedProvider();
        setSelectedProvider(
          saved && isLoggedIn(saved === "anthropic" ? claudeStatus : codexStatus)
            ? saved
            : codexStatus.state === "logged_in"
              ? "openai-codex"
              : claudeStatus.state === "logged_in"
                ? "anthropic"
                : null,
        );
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

  if (!desktopReady) return null;

  const selectProvider = (provider: ProviderId) => {
    window.localStorage.setItem(DESKTOP_CHAT_PROVIDER_KEY, provider);
    const persistence = getDesktop()?.setSelectedChatProvider?.(provider);
    void persistence?.catch(() => undefined);
    setSelectedProvider(provider);
  };
  const forgetProvider = (provider: ProviderId) => {
    if (selectedProvider !== provider) return;
    window.localStorage.removeItem(DESKTOP_CHAT_PROVIDER_KEY);
    const persistence = getDesktop()?.setSelectedChatProvider?.(null);
    void persistence?.catch(() => undefined);
    setSelectedProvider(null);
  };

  const loginClaude = async () => {
    const desktop = getDesktop();
    if (!desktop) return;
    setBusy("anthropic");
    setMessage(null);
    try {
      const next = await desktop.claudeLogin();
      setClaude(next);
      if (isLoggedIn(next)) selectProvider("anthropic");
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
      const next = await desktop.codexLogin(method);
      setCodex(next);
      if (isLoggedIn(next)) selectProvider("openai-codex");
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
      if (provider === "anthropic") {
        setClaude(await desktop.claudeLogout());
      } else {
        setCodex(await desktop.codexLogout());
      }
      forgetProvider(provider);
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
            Connect a provider account for local chat. Tokens stay in this Mac&apos;s Keychain;
            choose which connected account PortLog should use below.
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
          selectedProvider={selectedProvider}
          onLogin={() => void loginClaude()}
          onLogout={() => void logout("anthropic")}
          onSelect={() => selectProvider("anthropic")}
        />
        <OAuthCard
          provider="openai-codex"
          state={codex}
          loading={loading}
          busy={busy}
          selectedProvider={selectedProvider}
          onLogin={(method = "browser") => void loginCodex(method)}
          onLogout={() => void logout("openai-codex")}
          onSelect={() => selectProvider("openai-codex")}
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
  selectedProvider,
  onLogin,
  onLogout,
  onSelect,
}: {
  provider: ProviderId;
  state: AuthState | null;
  loading: boolean;
  busy: BusyProvider;
  selectedProvider: ProviderId | null;
  onLogin: (method?: "browser" | "device_code") => void;
  onLogout: () => void;
  onSelect: () => void;
}) {
  const connected = state?.state === "logged_in";
  const activeForChat = connected && selectedProvider === provider;
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
      className={`desktop-oauth-card${connected ? " desktop-oauth-card--connected" : ""}${activeForChat ? " desktop-oauth-card--active" : ""}`}
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
          <>
            <button
              type="button"
              className="desktop-oauth-button desktop-oauth-button--primary"
              onClick={onSelect}
              disabled={activeForChat}
              aria-pressed={activeForChat}
              data-testid={`desktop-oauth-select-${provider}`}
            >
              {activeForChat ? "Selected for local chat" : "Use for local chat"}
            </button>
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
          </>
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
function readSelectedProvider(): ProviderId | null {
  try {
    const value = window.localStorage.getItem(DESKTOP_CHAT_PROVIDER_KEY);
    return value === "anthropic" || value === "openai-codex" ? value : null;
  } catch {
    return null;
  }
}

function isLoggedIn(state: AuthState | null): boolean {
  return state?.state === "logged_in";
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
