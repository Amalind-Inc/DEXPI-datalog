import assert from "node:assert/strict";
import test from "node:test";

import {
  FIXED_OPENROUTER_MODEL,
  checkFixedOpenRouterConnection,
  redactedOpenRouterState,
} from "./local-openrouter.ts";

test("redacted OpenRouter state reports configuration without exposing the key", () => {
  assert.deepEqual(redactedOpenRouterState("sk-or-secret"), {
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
    credentialSource: "environment",
    configured: true,
  });
  assert.equal(JSON.stringify(redactedOpenRouterState("sk-or-secret")).includes("sk-or-secret"), false);
});

test("connection check classifies missing credential before any network call", async () => {
  let called = false;
  const result = await checkFixedOpenRouterConnection({
    credential: " ",
    fetcher: (async () => {
      called = true;
      return Response.json({});
    }) as typeof fetch,
  });
  assert.equal(called, false);
  assert.deepEqual(result, {
    ok: false,
    code: "missing_credential",
    message: "OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
  });
});

test("connection check verifies the fixed DeepSeek V4 Flash model through a minimal OpenRouter chat request", async () => {
  const seen: Array<{ url: string; authorization: string | null; body: unknown }> = [];
  const result = await checkFixedOpenRouterConnection({
    credential: "sk-or-secret",
    baseUrl: "http://openrouter.test/api/v1",
    fetcher: (async (url, init) => {
      const headers = new Headers(init?.headers);
      seen.push({ url: String(url), authorization: headers.get("authorization"), body: JSON.parse(String(init?.body)) });
      return Response.json({ model: FIXED_OPENROUTER_MODEL });
    }) as typeof fetch,
  });

  assert.deepEqual(result, { ok: true, provider: "openrouter", model: "deepseek/deepseek-v4-flash" });
  assert.deepEqual(seen, [{
    url: "http://openrouter.test/api/v1/chat/completions",
    authorization: "Bearer sk-or-secret",
    body: {
      model: "deepseek/deepseek-v4-flash",
      messages: [{ role: "user", content: "Respond with ok." }],
      max_tokens: 1,
      temperature: 0,
    },
  }]);
});

test("connection check classifies rejected credentials, rate limits, transport errors, and unavailable model", async () => {
  assert.equal(
    (await checkFixedOpenRouterConnection({ credential: "sk", fetcher: (async () => new Response("denied", { status: 401 })) as typeof fetch })).ok,
    false,
  );
  assert.equal(
    (await checkFixedOpenRouterConnection({ credential: "sk", fetcher: (async () => new Response("slow", { status: 429 })) as typeof fetch })).ok,
    false,
  );
  const unavailable = await checkFixedOpenRouterConnection({ credential: "sk", fetcher: (async () => Response.json({ model: "other" })) as typeof fetch });
  assert.deepEqual(unavailable, {
    ok: false,
    code: "unavailable_model",
    message: "OpenRouter cannot use deepseek/deepseek-v4-flash for this account.",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
  });
  const transport = await checkFixedOpenRouterConnection({ credential: "sk", fetcher: (async () => { throw new Error("sk secret appears upstream"); }) as typeof fetch });
  assert.deepEqual(transport, {
    ok: false,
    code: "transport_failure",
    message: "OpenRouter connection check could not reach OpenRouter.",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
  });
});


test("connection check owns timeout without exposing credentials", async () => {
  const result = await checkFixedOpenRouterConnection({
    credential: "sk-or-secret",
    timeoutMs: 1,
    fetcher: (async (_url, init) => {
      await new Promise((resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
      });
      return Response.json({});
    }) as typeof fetch,
  });
  assert.deepEqual(result, {
    ok: false,
    code: "timeout",
    message: "OpenRouter connection check timed out.",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
  });
  assert.equal(JSON.stringify(result).includes("sk-or-secret"), false);
});
