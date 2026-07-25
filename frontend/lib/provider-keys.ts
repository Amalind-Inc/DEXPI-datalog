// The hosted profile's server-side provider keys (bead 2afe.9).
//
// ADR 0014 keeps bring-your-own-key credentials in the browser, and in the
// local profile it still does: `byok-keys.ts` is the whole story there. This
// module is the hosted counterpart, where a signed-in user's key is held
// encrypted by the Python backend so their second device finds it.
//
// A credential travels *up* through here and never comes back down: the
// listing carries a masked hint, deliberately, so a compromised page cannot
// read out the keys of the session it is running in.

import { backendFetch } from "./backend-auth.ts";
import { backendBaseUrl } from "./review-backend.ts";

/** A saved key as the server describes it. Carries no key material. */
export type SavedProviderKey = {
  provider: string;
  model: string;
  /** Masked, e.g. `sk-a…mnop`. Enough to recognise, never enough to use. */
  hint: string;
  saved_at: string;
};

export type ProviderKeyOptions = {
  baseUrl?: string;
  fetcher?: typeof fetch;
};

/**
 * Every provider this signed-in user has saved a key for.
 *
 * A local-profile backend answers 404 with
 * `provider_keys.not_in_this_profile`, which is not an error to show: it
 * means keys belong in the browser here. Callers get an empty list and the
 * `serverBacked: false` flag to render the local story instead.
 */
export async function listProviderKeys({
  baseUrl = backendBaseUrl(),
  fetcher = backendFetch,
}: ProviderKeyOptions = {}): Promise<{
  status: number;
  serverBacked: boolean;
  keys: SavedProviderKey[];
}> {
  const res = await fetcher(`${baseUrl}/api/provider-keys`);
  if (res.status === 404) {
    return { status: res.status, serverBacked: false, keys: [] };
  }
  const body: unknown = await res.json();
  return { status: res.status, serverBacked: true, keys: savedKeyList(body) };
}

/** Save or replace this user's credential for one provider. */
export async function saveProviderKey(
  input: { provider: string; model: string; credential: string },
  { baseUrl = backendBaseUrl(), fetcher = backendFetch }: ProviderKeyOptions = {},
): Promise<{ status: number; saved: SavedProviderKey | null; error: string | null }> {
  const res = await fetcher(`${baseUrl}/api/provider-keys/${encodeURIComponent(input.provider)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model: input.model, credential: input.credential }),
  });
  const body: unknown = await res.json();
  if (!res.ok) {
    return { status: res.status, saved: null, error: errorMessage(body) };
  }
  return { status: res.status, saved: asSavedKey(body), error: null };
}

/** The backend's `{error: {message}}` shape, read without asserting it. */
function errorMessage(body: unknown): string {
  if (body && typeof body === "object" && "error" in body) {
    const error = body.error;
    if (error && typeof error === "object" && "message" in error) {
      const message = error.message;
      if (typeof message === "string") return message;
    }
  }
  return "Save failed.";
}

/** Narrow a save response, defaulting each field rather than trusting a cast. */
function asSavedKey(body: unknown): SavedProviderKey | null {
  if (!body || typeof body !== "object") return null;
  const read = (name: string): string => {
    if (name in body) {
      const value = (body as Record<string, unknown>)[name];
      if (typeof value === "string") return value;
    }
    return "";
  };
  const provider = read("provider");
  if (!provider) return null;
  return {
    provider,
    model: read("model"),
    hint: read("hint"),
    saved_at: read("saved_at"),
  };
}

/** The `{keys: [...]}` envelope, narrowed rather than asserted. */
function savedKeyList(body: unknown): SavedProviderKey[] {
  if (!body || typeof body !== "object" || !("keys" in body)) return [];
  const keys = body.keys;
  if (!Array.isArray(keys)) return [];
  return keys.flatMap((entry) => {
    const saved = asSavedKey(entry);
    return saved ? [saved] : [];
  });
}

/** Forget this user's credential for one provider. */
export async function deleteProviderKey(
  provider: string,
  { baseUrl = backendBaseUrl(), fetcher = backendFetch }: ProviderKeyOptions = {},
): Promise<{ status: number; deleted: boolean }> {
  const res = await fetcher(`${baseUrl}/api/provider-keys/${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
  return { status: res.status, deleted: res.ok };
}
