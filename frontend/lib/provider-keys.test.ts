// What the hosted key client sends, and what it refuses to carry back.
//
// Bead 2afe.9. The credential goes up and never comes down, so the tests
// that matter here are the negative ones: no response shape, however
// malformed, produces a key in the client's hands.

import assert from "node:assert/strict";
import { test } from "node:test";

import { deleteProviderKey, listProviderKeys, saveProviderKey } from "./provider-keys.ts";

const BASE = "http://backend.test";

function stubFetch(
  response: { status: number; body: unknown },
  seen: { url?: string; init?: RequestInit } = {},
): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    seen.url = String(url);
    seen.init = init;
    return new Response(JSON.stringify(response.body), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

test("a listing returns the saved providers with their masked hints", async () => {
  const fetcher = stubFetch({
    status: 200,
    body: { keys: [{ provider: "openai", model: "gpt-4.1", hint: "sk-a…mnop", saved_at: "t" }] },
  });
  const result = await listProviderKeys({ baseUrl: BASE, fetcher });
  assert.equal(result.serverBacked, true);
  assert.deepEqual(
    result.keys.map((k) => k.provider),
    ["openai"],
  );
  assert.equal(result.keys[0]?.hint, "sk-a…mnop");
});

test("a local-profile 404 is not an error, it means keys live in the browser", async () => {
  const fetcher = stubFetch({
    status: 404,
    body: { error: { code: "provider_keys.not_in_this_profile" } },
  });
  const result = await listProviderKeys({ baseUrl: BASE, fetcher });
  assert.equal(result.serverBacked, false);
  assert.deepEqual(result.keys, []);
});

test("a malformed listing yields no keys rather than undefined entries", async () => {
  for (const body of [null, {}, { keys: null }, { keys: "nope" }, { keys: [1, "x", {}] }]) {
    const result = await listProviderKeys({
      baseUrl: BASE,
      fetcher: stubFetch({ status: 200, body }),
    });
    assert.deepEqual(result.keys, [], `body ${JSON.stringify(body)}`);
  }
});

test("saving sends the credential in the body and never in the URL", async () => {
  const seen: { url?: string; init?: RequestInit } = {};
  const fetcher = stubFetch(
    {
      status: 200,
      body: { provider: "openai", model: "gpt-4.1", hint: "sk-a…mnop", saved_at: "t" },
    },
    seen,
  );
  await saveProviderKey(
    { provider: "openai", model: "gpt-4.1", credential: "sk-abcdefghijklmnop" },
    { baseUrl: BASE, fetcher },
  );
  assert.equal(seen.url, `${BASE}/api/provider-keys/openai`);
  assert.ok(!seen.url?.includes("sk-"), "a key in a URL lands in every access log");
  assert.equal(seen.init?.method, "PUT");
  assert.match(String(seen.init?.body), /sk-abcdefghijklmnop/);
});

test("a provider name with a slash cannot escape its path segment", async () => {
  const seen: { url?: string } = {};
  const fetcher = stubFetch(
    { status: 200, body: { provider: "x", model: "", hint: "", saved_at: "" } },
    seen,
  );
  await saveProviderKey(
    { provider: "../../admin", model: "m", credential: "c" },
    { baseUrl: BASE, fetcher },
  );
  assert.equal(seen.url, `${BASE}/api/provider-keys/..%2F..%2Fadmin`);
});

test("a rejected save surfaces the backend's reason", async () => {
  const fetcher = stubFetch({
    status: 400,
    body: { error: { message: "openai/not-a-model is not available." } },
  });
  const result = await saveProviderKey(
    { provider: "openai", model: "not-a-model", credential: "sk-x" },
    { baseUrl: BASE, fetcher },
  );
  assert.equal(result.saved, null);
  assert.match(String(result.error), /not available/);
});

test("a rejected save with no usable error body still reports something", async () => {
  for (const body of [null, {}, { error: null }, { error: { message: 7 } }]) {
    const result = await saveProviderKey(
      { provider: "openai", model: "m", credential: "c" },
      { baseUrl: BASE, fetcher: stubFetch({ status: 500, body }) },
    );
    assert.equal(result.saved, null);
    assert.ok(result.error, `body ${JSON.stringify(body)}`);
  }
});

test("deleting reports whether anything was there", async () => {
  const gone = await deleteProviderKey("openai", {
    baseUrl: BASE,
    fetcher: stubFetch({ status: 200, body: { deleted: true } }),
  });
  assert.equal(gone.deleted, true);

  const missing = await deleteProviderKey("openai", {
    baseUrl: BASE,
    fetcher: stubFetch({ status: 404, body: { error: {} } }),
  });
  assert.equal(missing.deleted, false);
});
