import assert from "node:assert/strict";
import test from "node:test";

import type { OAuthCredentials, OAuthLoginCallbacks } from "@earendil-works/pi-ai/oauth";
import { createClaudeAuthController } from "./claude-auth-controller.cjs";

const CREDENTIALS = { access: "access-secret", refresh: "refresh-secret", expires: 20_000 };

test("Claude login opens Pi authorization and stores tokens only through the Keychain boundary", async () => {
  const opened: string[] = [];
  const writes: string[] = [];
  const controller = createClaudeAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        callbacks.onAuth({ url: "https://claude.ai/oauth/authorize?state=one-time" });
        return CREDENTIALS;
      },
      async refreshToken(credentials: OAuthCredentials) {
        return credentials;
      },
      getApiKey(credentials: OAuthCredentials) {
        return credentials.access;
      },
    },
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
    },
    now: () => 1_000,
    timeoutMs: 1_000,
  });

  assert.deepEqual(await controller.status(), {
    provider: "anthropic",
    state: "logged_out",
    recoverable: true,
  });
  assert.deepEqual(await controller.login(), {
    provider: "anthropic",
    state: "logged_in",
    recoverable: true,
    expiresAt: 20_000,
  });
  assert.deepEqual(opened, ["https://claude.ai/oauth/authorize?state=one-time"]);
  assert.equal(writes.length, 1);
  assert.deepEqual(JSON.parse(writes[0]!), CREDENTIALS);
  assert.doesNotMatch(JSON.stringify(await controller.status()), /access-secret|refresh-secret/);
  assert.equal(await controller.getAccessToken(), "access-secret");
});

test("Claude login cancellation settles the provider and leaves no Keychain write", async () => {
  let cleanup = false;
  const writes: string[] = [];
  const controller = createClaudeAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        callbacks.onAuth({ url: "https://claude.ai/oauth/authorize?state=cancel" });
        await callbacks.onManualCodeInput?.().then(() => undefined);
        cleanup = true;
        throw new Error("cancelled by test");
      },
      async refreshToken(credentials: OAuthCredentials) {
        return credentials;
      },
      getApiKey(credentials: OAuthCredentials) {
        return credentials.access;
      },
    },
    keychain: {
      async read() {
        return null;
      },
      async write(value: string) {
        writes.push(value);
      },
      async delete() {},
    },
    openExternal: async () => {},
    timeoutMs: 50,
  });

  await assert.rejects(controller.login(), /timed out|cancelled/i);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(cleanup, true);
  assert.deepEqual(writes, []);
  assert.equal((await controller.status()).state, "cancelled");
});

test("expired Claude credentials refresh through Keychain and refresh failure is recoverable", async () => {
  let stored = JSON.stringify({ access: "old-access", refresh: "old-refresh", expires: 10 });
  let refreshCalls = 0;
  const writes: string[] = [];
  const controller = createClaudeAuthController({
    oauth: {
      async login() {
        throw new Error("not used");
      },
      async refreshToken() {
        refreshCalls += 1;
        throw new Error("revoked");
      },
      getApiKey(credentials: OAuthCredentials) {
        return credentials.access;
      },
    },
    keychain: {
      async read() {
        return stored;
      },
      async write(value: string) {
        stored = value;
        writes.push(value);
      },
      async delete() {},
    },
    openExternal: async () => {},
    now: () => 1_000,
  });

  const status = await controller.status();
  assert.equal(status.state, "refresh_failed");
  assert.equal(refreshCalls, 1);
  assert.equal(writes.length, 0);
  await assert.rejects(controller.getAccessToken(), /expired|refreshed|connected/i);
  assert.doesNotMatch(JSON.stringify(status), /old-access|old-refresh/);
});

test("logout deletes Keychain credentials and cancels an in-flight login", async () => {
  let deleted = 0;
  const controller = createClaudeAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        callbacks.onAuth({ url: "https://claude.ai/oauth/authorize?state=logout" });
        await callbacks.onManualCodeInput?.();
        return CREDENTIALS;
      },
      async refreshToken(credentials: OAuthCredentials) {
        return credentials;
      },
      getApiKey(credentials: OAuthCredentials) {
        return credentials.access;
      },
    },
    keychain: {
      async read() {
        return null;
      },
      async write() {},
      async delete() {
        deleted += 1;
      },
    },
    openExternal: async () => {},
    timeoutMs: 10_000,
  });
  const pending = controller.login();
  await controller.logout();
  assert.equal(deleted, 1);
  assert.equal((await controller.status()).state, "logged_out");
  await assert.rejects(pending, /cancelled/i);
});
