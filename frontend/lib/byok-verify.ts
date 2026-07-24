// Server-side probe for a BYOK credential. This runs in a route handler
// rather than the browser on purpose: most providers reject cross-origin
// browser calls, and probing from the server keeps the key out of the page's
// network log.
//
// The endpoint and auth scheme come from the vendored catalogue's wire format,
// so a newly-catalogued provider is testable without touching this file.

import { catalogProvider, resolveProviderId } from "./byok-catalog.ts";

export type ByokVerifyResult =
  | { ok: true; provider: string }
  | { ok: false; provider: string; message: string };

const ANTHROPIC_VERSION = "2023-06-01";

/** Cheapest authenticated GET each wire format offers. */
function probeRequest(
  wire: string,
  baseUrl: string,
  credential: string,
): { url: string; headers: Record<string, string> } {
  if (wire === "anthropic") {
    return {
      url: `${baseUrl}/models`,
      headers: { "x-api-key": credential, "anthropic-version": ANTHROPIC_VERSION },
    };
  }
  if (wire === "gemini") {
    // Gemini authenticates by query parameter, not a header.
    return { url: `${baseUrl}/models?key=${encodeURIComponent(credential)}`, headers: {} };
  }
  return { url: `${baseUrl}/models`, headers: { Authorization: `Bearer ${credential}` } };
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
  input: { provider: string; credential: string },
  fetcher: typeof fetch = fetch,
): Promise<ByokVerifyResult> {
  const provider = resolveProviderId(input.provider);
  const catalogued = catalogProvider(provider);
  if (!catalogued) {
    return { ok: false, provider, message: "Unknown provider." };
  }
  const credential = input.credential.trim();
  if (!credential && !catalogued.is_local) {
    return { ok: false, provider, message: "Enter a key before testing it." };
  }

  const { url, headers } = probeRequest(catalogued.wire, catalogued.base_url, credential);
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
      message:
        error instanceof Error
          ? `${catalogued.name} could not be reached: ${error.message}`
          : "The provider could not be reached.",
    };
  }
}
