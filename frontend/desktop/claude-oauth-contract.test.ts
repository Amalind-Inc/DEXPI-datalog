import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { anthropicOAuthProvider, loginAnthropic } from "@earendil-works/pi-ai/oauth";

test("PortLog records the exact pinned Anthropic OAuth provider contract", async () => {
  const packageJson = JSON.parse(
    await readFile(join(process.cwd(), "node_modules/@earendil-works/pi-ai/package.json"), "utf8"),
  ) as { version: string };
  assert.equal(packageJson.version, "0.80.6");
  assert.equal(anthropicOAuthProvider.id, "anthropic");
  assert.equal(anthropicOAuthProvider.name, "Anthropic (Claude Pro/Max)");
  assert.equal(anthropicOAuthProvider.usesCallbackServer, true);
  assert.equal(typeof anthropicOAuthProvider.login, "function");
  assert.equal(typeof anthropicOAuthProvider.refreshToken, "function");
  assert.equal(typeof anthropicOAuthProvider.getApiKey, "function");
});

test("pinned Anthropic callback rejects wrong state and closes against replay", async () => {
  const manual = deferred<string>();
  let authUrl: URL | undefined;
  const login = loginAnthropic({
    onAuth: (info) => {
      authUrl = new URL(info.url);
    },
    onManualCodeInput: () => manual.promise,
    onPrompt: async () => {
      throw new Error("test cancellation");
    },
  });

  await waitFor(() => authUrl !== undefined);
  assert.equal(authUrl?.origin, "https://claude.ai");
  assert.equal(authUrl?.pathname, "/oauth/authorize");
  assert.equal(authUrl?.searchParams.get("code"), "true");
  assert.equal(authUrl?.searchParams.get("code_challenge_method"), "S256");
  assert.equal(authUrl?.searchParams.get("redirect_uri"), "http://localhost:53692/callback");
  const wrongState = await fetch("http://127.0.0.1:53692/callback?code=not-used&state=wrong-state");
  assert.equal(wrongState.status, 400);
  assert.match(await wrongState.text(), /State mismatch/i);

  manual.resolve("");
  await assert.rejects(login, /test cancellation|authorization code/i);
  await assert.rejects(fetch("http://127.0.0.1:53692/callback?code=replay&state=wrong-state"));
});

test("pinned Anthropic callback exchanges a valid one-time code without putting tokens in the URL", async () => {
  const originalFetch = globalThis.fetch;
  let tokenRequest: Record<string, unknown> | undefined;
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url === "https://platform.claude.com/v1/oauth/token") {
      tokenRequest = JSON.parse(String(init?.body ?? "")) as Record<string, unknown>;
      return new Response(
        JSON.stringify({
          access_token: "access-secret",
          refresh_token: "refresh-secret",
          expires_in: 3600,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return originalFetch(input, init);
  };
  try {
    const manual = deferred<string>();
    let authUrl: URL | undefined;
    const login = loginAnthropic({
      onAuth: (info) => {
        authUrl = new URL(info.url);
      },
      onManualCodeInput: () => manual.promise,
      onPrompt: async () => {
        throw new Error("unexpected prompt");
      },
    });
    await waitFor(() => authUrl !== undefined);
    const state = authUrl?.searchParams.get("state");
    assert.ok(state);
    const callback = await fetch(
      `http://127.0.0.1:53692/callback?code=one-time-code&state=${encodeURIComponent(state)}`,
    );
    assert.equal(callback.status, 200);
    const callbackBody = await callback.text();
    assert.match(callbackBody, /PortLog is connected/);
    assert.doesNotMatch(callbackBody, /access-secret|refresh-secret/);
    const credentials = await login;
    assert.equal(credentials.access, "access-secret");
    assert.equal(tokenRequest?.grant_type, "authorization_code");
    assert.equal(tokenRequest?.state, state);
    assert.equal(tokenRequest?.code_verifier, state);
    assert.doesNotMatch(authUrl?.toString() ?? "", /access-secret|refresh-secret/);
    await assert.rejects(fetch("http://127.0.0.1:53692/callback?code=replay&state=" + state));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function waitFor(predicate: () => boolean) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("Timed out waiting for callback server");
}
