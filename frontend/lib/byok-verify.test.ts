import assert from "node:assert/strict";
import test from "node:test";
import { verifyByokCredential } from "./byok-verify.ts";

function respondingFetcher(
  status: number,
  body: unknown = {},
): { fetcher: typeof fetch; calls: Array<{ url: string; headers: Record<string, string> }> } {
  const calls: Array<{ url: string; headers: Record<string, string> }> = [];
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      url: String(url),
      headers: (init?.headers ?? {}) as Record<string, string>,
    });
    return new Response(JSON.stringify(body), { status });
  }) as unknown as typeof fetch;
  return { fetcher, calls };
}

test("a working OpenAI key reports the provider as reachable", async () => {
  const { fetcher, calls } = respondingFetcher(200);
  const result = await verifyByokCredential(
    { provider: "openai", credential: "sk-live-key" },
    fetcher,
  );

  assert.deepEqual(result, { ok: true, provider: "openai" });
  assert.equal(calls[0].url, "https://api.openai.com/v1/models");
  assert.equal(calls[0].headers.Authorization, "Bearer sk-live-key");
});

test("each provider is probed on its own authentication scheme", async () => {
  const anthropic = respondingFetcher(200);
  await verifyByokCredential(
    { provider: "anthropic", credential: "sk-ant-key" },
    anthropic.fetcher,
  );
  assert.equal(anthropic.calls[0].url, "https://api.anthropic.com/v1/models");
  assert.equal(anthropic.calls[0].headers["x-api-key"], "sk-ant-key");
  assert.ok(anthropic.calls[0].headers["anthropic-version"]);

  const gemini = respondingFetcher(200);
  await verifyByokCredential({ provider: "gemini", credential: "AIza-key" }, gemini.fetcher);
  assert.equal(
    gemini.calls[0].url,
    "https://generativelanguage.googleapis.com/v1beta/models?key=AIza-key",
  );
  assert.equal(gemini.calls[0].headers.Authorization, undefined);

  const openrouter = respondingFetcher(200);
  await verifyByokCredential(
    { provider: "openrouter", credential: "sk-or-key" },
    openrouter.fetcher,
  );
  assert.equal(openrouter.calls[0].url, "https://openrouter.ai/api/v1/key");
  assert.equal(openrouter.calls[0].headers.Authorization, "Bearer sk-or-key");
});

test("a rejected key comes back as an actionable failure, not a thrown error", async () => {
  const { fetcher } = respondingFetcher(401, { error: { message: "Incorrect API key provided" } });
  const result = await verifyByokCredential({ provider: "openai", credential: "sk-bad" }, fetcher);

  assert.equal(result.ok, false);
  assert.match(result.ok ? "" : result.message, /incorrect api key/i);
});

test("a network failure is reported rather than crashing the route", async () => {
  const fetcher = (async () => {
    throw new Error("getaddrinfo ENOTFOUND");
  }) as unknown as typeof fetch;

  const result = await verifyByokCredential({ provider: "openai", credential: "sk-x" }, fetcher);
  assert.equal(result.ok, false);
  assert.match(result.ok ? "" : result.message, /ENOTFOUND/);
});

test("an unknown provider or blank credential is refused before any network call", async () => {
  let called = false;
  const fetcher = (async () => {
    called = true;
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;

  const unknown = await verifyByokCredential(
    { provider: "hotdog" as never, credential: "sk-x" },
    fetcher,
  );
  assert.equal(unknown.ok, false);

  const blank = await verifyByokCredential({ provider: "openai", credential: "  " }, fetcher);
  assert.equal(blank.ok, false);
  assert.equal(called, false);
});
