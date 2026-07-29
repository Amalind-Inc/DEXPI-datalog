export const FIXED_OPENROUTER_PROVIDER = "openrouter";
export const FIXED_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";
export const FIXED_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash";
export const FIXED_OPENROUTER_CREDENTIAL_SOURCE = "environment";

export type OpenRouterConnectionStatus =
  | { ok: true; provider: typeof FIXED_OPENROUTER_PROVIDER; model: typeof FIXED_OPENROUTER_MODEL }
  | { ok: false; code: "missing_credential" | "rejected_credential" | "unavailable_model" | "rate_limited" | "transport_failure" | "timeout" | "cancelled"; message: string; provider: typeof FIXED_OPENROUTER_PROVIDER; model: typeof FIXED_OPENROUTER_MODEL };

export type OpenRouterCredentialState = {
  provider: typeof FIXED_OPENROUTER_PROVIDER;
  model: typeof FIXED_OPENROUTER_MODEL;
  credentialSource: typeof FIXED_OPENROUTER_CREDENTIAL_SOURCE;
  configured: boolean;
};


export function redactedOpenRouterState(credential: string | undefined): OpenRouterCredentialState {
  return {
    provider: FIXED_OPENROUTER_PROVIDER,
    model: FIXED_OPENROUTER_MODEL,
    credentialSource: FIXED_OPENROUTER_CREDENTIAL_SOURCE,
    configured: Boolean(credential?.trim()),
  };
}

export async function checkFixedOpenRouterConnection({
  credential,
  fetcher = fetch,
  baseUrl = FIXED_OPENROUTER_BASE_URL,
  signal,
  timeoutMs = 10_000,
}: {
  credential: string | undefined;
  fetcher?: typeof fetch;
  baseUrl?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<OpenRouterConnectionStatus> {
  const key = credential?.trim() ?? "";
  if (!key) return failure("missing_credential", "OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.");
  if (signal?.aborted) return failure("cancelled", "OpenRouter connection check was cancelled.");

  try {
    const requestSignal = combineSignals(signal, AbortSignal.timeout(timeoutMs));
    const response = await fetcher(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      signal: requestSignal,
      body: JSON.stringify({
        model: FIXED_OPENROUTER_MODEL,
        messages: [{ role: "user", content: "Respond with ok." }],
        max_tokens: 1,
        temperature: 0,
      }),
    });
    if (response.status === 401 || response.status === 403) return failure("rejected_credential", "OpenRouter rejected the configured API key.");
    if (response.status === 429) return failure("rate_limited", "OpenRouter rate-limited the configured account.");
    if (response.status === 404 || response.status === 400) {
      return failure("unavailable_model", "OpenRouter cannot use deepseek/deepseek-v4-flash for this account.");
    }
    if (!response.ok) return failure("transport_failure", `OpenRouter connection check failed (${response.status}).`);

    const data = (await response.json().catch(() => null)) as { model?: unknown } | null;
    if (typeof data?.model === "string" && data.model !== FIXED_OPENROUTER_MODEL && !data.model.startsWith(`${FIXED_OPENROUTER_MODEL}-`)) {
      return failure("unavailable_model", "OpenRouter cannot use deepseek/deepseek-v4-flash for this account.");
    }
    return { ok: true, provider: FIXED_OPENROUTER_PROVIDER, model: FIXED_OPENROUTER_MODEL };
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") return failure("timeout", "OpenRouter connection check timed out.");
    if (signal?.aborted || (error instanceof Error && error.name === "AbortError")) return failure("cancelled", "OpenRouter connection check was cancelled.");
    return failure("transport_failure", "OpenRouter connection check could not reach OpenRouter.");
  }
}

function failure(code: Exclude<OpenRouterConnectionStatus, { ok: true }>["code"], message: string): OpenRouterConnectionStatus {
  return { ok: false, code, message, provider: FIXED_OPENROUTER_PROVIDER, model: FIXED_OPENROUTER_MODEL };
}

function combineSignals(parent: AbortSignal | undefined, timeoutSignal: AbortSignal): AbortSignal {
  if (!parent) return timeoutSignal;
  const controller = new AbortController();
  const abort = (reason?: unknown) => { if (!controller.signal.aborted) controller.abort(reason); };
  parent.addEventListener("abort", () => abort(parent.reason), { once: true });
  timeoutSignal.addEventListener("abort", () => abort(timeoutSignal.reason), { once: true });
  return controller.signal;
}
