import assert from "node:assert/strict";
import test from "node:test";

import type { OAuthCredentials, OAuthLoginCallbacks } from "@earendil-works/pi-ai/oauth";
import { createCodexAuthController } from "./codex-auth-controller.cjs";

const CREDENTIALS = { access: "codex-access", refresh: "codex-refresh", expires: 20_000 };

test("Codex login selects browser by default, opens authorization, and stores only through its Keychain boundary", async () => {
  const selected: string[] = [];
  const opened: string[] = [];
  const writes: string[] = [];
  const controller = createCodexAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        const choice = await callbacks.onSelect({
          message: "Select OpenAI Codex login method:",
          options: [
            { id: "browser", label: "Browser login (default)" },
            { id: "device_code", label: "Device code login (headless)" },
          ],
        });
        selected.push(choice ?? "cancelled");
        callbacks.onAuth({ url: "https://auth.openai.com/oauth/authorize?state=one-time" });
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
    timeoutMs: 1_000,
  });

  assert.deepEqual(await controller.login(), {
    provider: "openai-codex",
    state: "logged_in",
    recoverable: true,
    expiresAt: 20_000,
  });
  assert.deepEqual(selected, ["browser"]);
  assert.deepEqual(opened, ["https://auth.openai.com/oauth/authorize?state=one-time"]);
  assert.equal(writes.length, 1);
  assert.deepEqual(JSON.parse(writes[0]!), CREDENTIALS);
  assert.doesNotMatch(JSON.stringify(await controller.status()), /codex-access|codex-refresh/);
  assert.equal(await controller.getAccessToken(), "codex-access");
});

test("Codex login can select device code and exposes the verification details", async () => {
  const selected: string[] = [];
  const deviceCodes: unknown[] = [];
  const controller = createCodexAuthController({
    selectLogin: async () => "device_code",
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        const choice = await callbacks.onSelect({
          message: "Select OpenAI Codex login method:",
          options: [
            { id: "browser", label: "Browser login (default)" },
            { id: "device_code", label: "Device code login (headless)" },
          ],
        });
        selected.push(choice ?? "cancelled");
        callbacks.onDeviceCode({
          userCode: "ABCD-EFGH",
          verificationUri: "https://auth.openai.com/codex/device",
          expiresInSeconds: 900,
        });
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
      async delete() {},
    },
    openExternal: async () => {},
    timeoutMs: 1_000,
    onDeviceCode: (info: unknown) => deviceCodes.push(info),
  });

  assert.deepEqual(await controller.login(), {
    provider: "openai-codex",
    state: "logged_in",
    recoverable: true,
    expiresAt: 20_000,
  });
  assert.deepEqual(selected, ["device_code"]);
  assert.deepEqual(deviceCodes, [
    {
      userCode: "ABCD-EFGH",
      verificationUri: "https://auth.openai.com/codex/device",
      expiresInSeconds: 900,
    },
  ]);
});

test("Codex status exposes device-code details while authorization is pending", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const controller = createCodexAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        await callbacks.onSelect({
          message: "Select OpenAI Codex login method:",
          options: [
            { id: "browser", label: "Browser login (default)" },
            { id: "device_code", label: "Device code login (headless)" },
          ],
        });
        callbacks.onDeviceCode({
          userCode: "WXYZ-1234",
          verificationUri: "https://auth.openai.com/codex/device",
          expiresInSeconds: 900,
        });
        await gate;
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
      async delete() {},
    },
    openExternal: async () => {},
    timeoutMs: 1_000,
  });

  const login = controller.login("device_code");
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.deepEqual(await controller.status(), {
    provider: "openai-codex",
    state: "waiting_for_authorization",
    recoverable: true,
    deviceCode: {
      userCode: "WXYZ-1234",
      verificationUri: "https://auth.openai.com/codex/device",
      expiresInSeconds: 900,
    },
  });
  release();
  await login;
});

test("Codex device-code login cancellation settles without writing credentials", async () => {
  let cleanup = false;
  const writes: string[] = [];
  const controller = createCodexAuthController({
    oauth: {
      async login(callbacks: OAuthLoginCallbacks) {
        await callbacks.onSelect({
          message: "Select OpenAI Codex login method:",
          options: [
            { id: "browser", label: "Browser login (default)" },
            { id: "device_code", label: "Device code login (headless)" },
          ],
        });
        callbacks.onDeviceCode({
          userCode: "CANCEL-ME",
          verificationUri: "https://auth.openai.com/codex/device",
        });
        await callbacks.onManualCodeInput?.();
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
    timeoutMs: 10_000,
  });

  const pending = controller.login("device_code");
  await controller.cancel();
  await assert.rejects(pending, /cancelled/i);
  assert.equal(cleanup, true);
  assert.deepEqual(writes, []);
  assert.equal((await controller.status()).state, "cancelled");
});
