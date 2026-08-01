import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  OPENAI_CODEX_BROWSER_LOGIN_METHOD,
  openaiCodexOAuthProvider,
} from "@earendil-works/pi-ai/oauth";
import { createCodexAuthController } from "./codex-auth-controller.cjs";

const ACCESS_TOKEN = [
  "header",
  Buffer.from(
    JSON.stringify({
      "https://api.openai.com/auth": { chatgpt_account_id: "acct-portlog-test" },
    }),
  ).toString("base64url"),
  "signature",
].join(".");

const CREDENTIALS = {
  access: ACCESS_TOKEN,
  refresh: "refresh-secret",
  expires: Date.now() + 60_000,
  accountId: "acct-portlog-test",
};

test("the pinned Codex browser OAuth flow completes through PortLog's controller boundary", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../node_modules/@earendil-works/pi-ai/package.json", import.meta.url), "utf8"),
  ) as { version: string };
  assert.equal(packageJson.version, "0.80.6");
  assert.equal(openaiCodexOAuthProvider.id, "openai-codex");
  assert.equal(openaiCodexOAuthProvider.usesCallbackServer, true);

  const opened: string[] = [];
  const { promise: openedSignal, resolve: signalOpened } = Promise.withResolvers<void>();
  const writes: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    if (String(input) === "https://auth.openai.com/oauth/token") {
      assert.equal(init?.method, "POST");
      return new Response(
        JSON.stringify({
          access_token: CREDENTIALS.access,
          refresh_token: CREDENTIALS.refresh,
          expires_in: 3600,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return originalFetch(input, init);
  };

  const controller = createCodexAuthController({
    oauth: openaiCodexOAuthProvider,
    keychain: {
      async read() {
        return null;
      },
      async write(value: string) {
        writes.push(value);
      },
      async delete() {},
    },
    openExternal: async (url: string) => {
      opened.push(url);
      signalOpened();
    },
    timeoutMs: 5_000,
  });

  try {
    const login = controller.login(OPENAI_CODEX_BROWSER_LOGIN_METHOD);
    await openedSignal;
    assert.equal(opened.length, 1);
    const authUrl = new URL(opened[0]!);
    assert.equal(authUrl.origin, "https://auth.openai.com");
    assert.equal(authUrl.pathname, "/oauth/authorize");
    assert.equal(authUrl.searchParams.get("redirect_uri"), "http://localhost:1455/auth/callback");
    assert.equal(authUrl.searchParams.get("code_challenge_method"), "S256");

    const callback = await fetch(
      `http://127.0.0.1:1455/auth/callback?code=portlog-code&state=${encodeURIComponent(authUrl.searchParams.get("state") ?? "")}`,
    );
    assert.equal(callback.status, 200);
    assert.match(await callback.text(), /PortLog is connected/);

    const status = await login;
    assert.equal(status.state, "logged_in");
    assert.equal(await controller.getAccessToken(), ACCESS_TOKEN);
    assert.equal(writes.length, 1);
    const stored = JSON.parse(writes[0]!) as Record<string, unknown>;
    assert.equal(stored.access, ACCESS_TOKEN);
    assert.equal(stored.refresh, "refresh-secret");
    assert.equal(typeof stored.expires, "number");
    assert.ok(Number(stored.expires) > Date.now());
    assert.doesNotMatch(JSON.stringify(status), /refresh-secret|acct-portlog-test/);

    await assert.rejects(
      fetch(
        `http://127.0.0.1:1455/auth/callback?code=replay&state=${encodeURIComponent(authUrl.searchParams.get("state") ?? "")}`,
      ),
    );
  } finally {
    globalThis.fetch = originalFetch;
    await controller.logout();
  }
});
