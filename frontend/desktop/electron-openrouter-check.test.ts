import assert from "node:assert/strict";
import test from "node:test";

import { checkOpenRouterConnection } from "./electron-openrouter-check.cjs";

const resolved: Record<string, unknown> = {
  provider: "openrouter",
  model: "deepseek/deepseek-v4-flash",
  credentialSource: "environment",
  configured: true,
  credential: "sk-or-secret",
};

test("Electron OpenRouter check sends a bounded non-tool chat completion and redacts the response", async () => {
  const seen: Array<{ url: string; authorization: string | null; body: unknown }> = [];
  const result = await checkOpenRouterConnection({
    resolved,
    baseUrl: "http://openrouter.test/api/v1",
    fetcher: (async (url, init) => {
      const headers = new Headers(init?.headers);
      seen.push({ url: String(url), authorization: headers.get("authorization"), body: JSON.parse(String(init?.body)) });
      return Response.json({ model: "deepseek/deepseek-v4-flash" });
    }) as typeof fetch,
  });

  assert.deepEqual(result, { ok: true, provider: "openrouter", model: "deepseek/deepseek-v4-flash", credentialSource: "environment", configured: true });
  assert.deepEqual(seen, [{
    url: "http://openrouter.test/api/v1/chat/completions",
    authorization: "Bearer sk-or-secret",
    body: { model: "deepseek/deepseek-v4-flash", messages: [{ role: "user", content: "Respond with ok." }], max_tokens: 1, temperature: 0 },
  }]);
  assert.equal(JSON.stringify(result).includes("sk-or-secret"), false);
});

test("Electron OpenRouter check classifies missing, rejected, unavailable, rate-limit, transport, timeout, and cancellation", async () => {
  assert.equal((await checkOpenRouterConnection({ resolved: { ...resolved, credential: "" } }) as { code: string }).code, "missing_credential");
  assert.equal((await checkOpenRouterConnection({ resolved, fetcher: (async () => new Response("", { status: 401 })) as typeof fetch }) as { code: string }).code, "rejected_credential");
  assert.equal((await checkOpenRouterConnection({ resolved, fetcher: (async () => new Response("", { status: 429 })) as typeof fetch }) as { code: string }).code, "rate_limited");
  assert.equal((await checkOpenRouterConnection({ resolved, fetcher: (async () => Response.json({ model: "other" })) as typeof fetch }) as { code: string }).code, "unavailable_model");
  assert.equal((await checkOpenRouterConnection({ resolved, fetcher: (async () => { throw new Error("secret sk-or-secret"); }) as typeof fetch }) as { code: string }).code, "transport_failure");
  assert.equal((await checkOpenRouterConnection({ resolved, timeoutMs: 1, fetcher: (async (_url, init) => new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true }))) as typeof fetch }) as { code: string }).code, "timeout");
  const controller = new AbortController();
  controller.abort();
  assert.equal((await checkOpenRouterConnection({ resolved, signal: controller.signal }) as { code: string }).code, "cancelled");
});
