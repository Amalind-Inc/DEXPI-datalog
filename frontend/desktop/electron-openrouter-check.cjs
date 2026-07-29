const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1';

/** @param {{resolved:any, fetcher?: typeof fetch, baseUrl?: string, timeoutMs?: number, signal?: AbortSignal}} options */
async function checkOpenRouterConnection({ resolved, fetcher = fetch, baseUrl = OPENROUTER_BASE_URL, timeoutMs = 10000, signal }) {
  const redacted = redactedOpenRouterState(resolved);
  const key = typeof resolved?.credential === 'string' ? resolved.credential.trim() : '';
  if (!key) return { ok: false, code: 'missing_credential', message: 'OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.', ...redacted };
  if (signal?.aborted) return { ok: false, code: 'cancelled', message: 'OpenRouter connection check was cancelled.', ...redacted };
  try {
    const response = await fetcher(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      signal: combineSignals(signal, AbortSignal.timeout(timeoutMs)),
      body: JSON.stringify({ model: resolved.model, messages: [{ role: 'user', content: 'Respond with ok.' }], max_tokens: 1, temperature: 0 }),
    });
    if (response.status === 401 || response.status === 403) return { ok: false, code: 'rejected_credential', message: 'OpenRouter rejected the configured API key.', ...redacted };
    if (response.status === 429) return { ok: false, code: 'rate_limited', message: 'OpenRouter rate-limited the configured account.', ...redacted };
    if (response.status === 400 || response.status === 404) return { ok: false, code: 'unavailable_model', message: `OpenRouter cannot use ${resolved.model} for this account.`, ...redacted };
    if (!response.ok) return { ok: false, code: 'transport_failure', message: `OpenRouter connection check failed (${response.status}).`, ...redacted };
    const data = await response.json().catch(() => null);
    if (data?.model && data.model !== resolved.model && !String(data.model).startsWith(`${resolved.model}-`)) {
      return { ok: false, code: 'unavailable_model', message: `OpenRouter cannot use ${resolved.model} for this account.`, ...redacted };
    }
    return { ok: true, ...redacted };
  } catch (error) {
    if (error instanceof Error && error.name === 'TimeoutError') return { ok: false, code: 'timeout', message: 'OpenRouter connection check timed out.', ...redacted };
    if (signal?.aborted || (error instanceof Error && error.name === 'AbortError')) return { ok: false, code: 'cancelled', message: 'OpenRouter connection check was cancelled.', ...redacted };
    return { ok: false, code: 'transport_failure', message: 'OpenRouter connection check could not reach OpenRouter.', ...redacted };
  }
}

function redactedOpenRouterState(resolved) {
  return { provider: resolved.provider, model: resolved.model, credentialSource: resolved.credentialSource, configured: Boolean(resolved.credential) };
}

function combineSignals(parent, timeoutSignal) {
  if (!parent) return timeoutSignal;
  const controller = new AbortController();
  const abort = (reason) => { if (!controller.signal.aborted) controller.abort(reason); };
  parent.addEventListener('abort', () => abort(parent.reason), { once: true });
  timeoutSignal.addEventListener('abort', () => abort(timeoutSignal.reason), { once: true });
  return controller.signal;
}

module.exports = { checkOpenRouterConnection };
