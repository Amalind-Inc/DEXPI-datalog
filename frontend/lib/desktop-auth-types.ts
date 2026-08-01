export type OAuthProviderId = "anthropic" | "openai-codex";

export type OAuthLifecycleState =
  | "logged_out"
  | "opening_browser"
  | "waiting_for_authorization"
  | "logged_in"
  | "refresh_failed"
  | "cancelled";

export interface ClaudeAuthState {
  provider: "anthropic";
  state: OAuthLifecycleState;
  recoverable: boolean;
  error?: string;
  expiresAt?: number;
}

export interface CodexDeviceCode {
  userCode: string;
  verificationUri: string;
  expiresInSeconds?: number;
  intervalSeconds?: number;
}

export interface CodexAuthState {
  provider: "openai-codex";
  state: OAuthLifecycleState;
  recoverable: boolean;
  loginMethod?: "browser" | "device_code";
  verificationUri?: string;
  userCode?: string;
  deviceCode?: CodexDeviceCode;
  error?: string;
  expiresAt?: number;
}

export type DesktopOAuthState = ClaudeAuthState | CodexAuthState;
