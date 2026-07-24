// Server-side probe for a BYOK credential. This runs in a route handler
// rather than the browser on purpose: Anthropic and OpenAI reject cross-origin
// browser calls, and probing from the server keeps the key out of the page's
// network log.

import { type ByokProviderId, isByokProviderId } from "./byok-keys.ts";

export type ByokVerifyResult =
  | { ok: true; provider: ByokProviderId }
  | { ok: false; provider: string; message: string };

const ANTHROPIC_VERSION = "2023-06-01";

function probeRequest(
  provider: ByokProviderId,
  credential: string,
): { url: string; headers: Record<string, string> } {
  switch (provider) {
    case "openrouter":
      return {
        url: "https://openrouter.ai/api/v1/key",
        headers: { Authorization: `Bearer ${credential}` },
      };
    case "openai":
      return {
        url: "https://api.openai.com/v1/models",
        headers: { Authorization: `Bearer ${credential}` },
      };
    case "anthropic":
      return {
        url: "https://api.anthropic.com/v1/models",
        headers: { "x-api-key": credential, "anthropic-version": ANTHROPIC_VERSION },
      };
    case "gemini":
      return {
        // Gemini authenticates by query parameter, not a header.
        url: `https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(
          credential,
        )}`,
        headers: {},
      };
  }
}

/** Pull the provider's own words out of whatever error envelope it used. */
function providerErrorMessage(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>;
    const error = parsed.error;
    if (typeof error === "string" && error) return error;
    if (typeof error === "object" && error !== null) {
      const message = (error as Record<string, unknown>).message;
      if (typeof message === "string" && message) return message;
    }
    if (typeof parsed.message === "string" && parsed.message) return parsed.message;
  } catch {
    // Not JSON — fall through to the status line.
  }
  return status === 401 || status === 403
    ? "The provider rejected this key."
    : `The provider responded with HTTP ${status}.`;
}

export async function verifyByokCredential(
  input: { provider: ByokProviderId; credential: string },
  fetcher: typeof fetch = fetch,
): Promise<ByokVerifyResult> {
  const provider = input.provider;
  if (!isByokProviderId(provider)) {
    return { ok: false, provider: String(provider), message: "Unknown provider." };
  }
  const credential = input.credential.trim();
  if (!credential) {
    return { ok: false, provider, message: "Enter a key before testing it." };
  }

  const { url, headers } = probeRequest(provider, credential);
  try {
    const response = await fetcher(url, { method: "GET", headers });
    if (!response.ok) {
      return {
        ok: false,
        provider,
        message: providerErrorMessage(response.status, await response.text()),
      };
    }
    return { ok: true, provider };
  } catch (error) {
    return {
      ok: false,
      provider,
      message: error instanceof Error ? error.message : "The provider could not be reached.",
    };
  }
}
