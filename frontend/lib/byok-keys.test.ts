import assert from "node:assert/strict";
import test from "node:test";
import {
  BYOK_PROVIDERS,
  byokProvider,
  clearByokKey,
  maskCredential,
  providerSettingsFromRequest,
  providerSettingsFromStore,
  readByokStore,
  saveByokKey,
  selectActiveProvider,
  type ByokStore,
} from "./byok-keys.ts";

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, value),
  } as Storage;
}

test("the catalogue covers the four BYOK providers a user can bring keys for", () => {
  assert.deepEqual(
    BYOK_PROVIDERS.map((entry) => entry.id),
    ["openrouter", "openai", "anthropic", "gemini"],
  );
  assert.equal(byokProvider("anthropic").label, "Anthropic (Claude)");
  assert.ok(byokProvider("openrouter").models.length > 0);
  // Every catalogue default must be one of that provider's offered models.
  for (const entry of BYOK_PROVIDERS) {
    assert.ok(entry.models.includes(entry.defaultModel), `${entry.id} default not in models`);
  }
});

test("saving a key makes that provider the active one and records a masked preview", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-abcdefgh12345678", model: "gpt-4.1" }, storage);

  const store = readByokStore(storage);
  assert.equal(store.activeProvider, "openai");
  assert.equal(store.keys.openai?.credential, "sk-abcdefgh12345678");
  assert.equal(store.keys.openai?.model, "gpt-4.1");
  assert.equal(maskCredential("sk-abcdefgh12345678"), "sk-a…5678");
});

test("a second key is stored alongside the first without stealing the active slot", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);
  saveByokKey(
    { provider: "gemini", credential: "gemini-key-value", model: "gemini-2.5-pro" },
    storage,
  );

  const store = readByokStore(storage);
  assert.equal(store.activeProvider, "openai");
  assert.deepEqual(Object.keys(store.keys).sort(), ["gemini", "openai"]);

  selectActiveProvider("gemini", storage);
  assert.equal(readByokStore(storage).activeProvider, "gemini");
});

test("selecting a provider with no stored key is refused", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);

  assert.throws(() => selectActiveProvider("anthropic", storage), /no stored key/i);
  assert.equal(readByokStore(storage).activeProvider, "openai");
});

test("clearing the active key falls back to another stored provider", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);
  saveByokKey(
    { provider: "openrouter", credential: "sk-or-key-value", model: "anthropic/claude-sonnet-4" },
    storage,
  );

  clearByokKey("openai", storage);
  const store = readByokStore(storage);
  assert.equal(store.activeProvider, "openrouter");
  assert.equal(store.keys.openai, undefined);

  clearByokKey("openrouter", storage);
  assert.equal(readByokStore(storage).activeProvider, null);
});

test("an empty credential is rejected rather than stored as a blank key", () => {
  const storage = memoryStorage();
  assert.throws(
    () => saveByokKey({ provider: "openai", credential: "   ", model: "gpt-4.1" }, storage),
    /credential/i,
  );
  assert.deepEqual(readByokStore(storage).keys, {});
});

test("provider settings are derived from the active key for the backend call", () => {
  const storage = memoryStorage();
  assert.equal(providerSettingsFromStore(readByokStore(storage)), null);

  saveByokKey(
    { provider: "anthropic", credential: "sk-ant-key-value", model: "claude-sonnet-4" },
    storage,
  );
  assert.deepEqual(providerSettingsFromStore(readByokStore(storage)), {
    provider: "anthropic",
    model: "claude-sonnet-4",
    credential: "sk-ant-key-value",
  });
});

test("corrupt or foreign storage contents read back as an empty store", () => {
  const storage = memoryStorage();
  storage.setItem("pydexpi.byok.v1", "{not json");
  assert.deepEqual(readByokStore(storage), { activeProvider: null, keys: {} } satisfies ByokStore);

  storage.setItem("pydexpi.byok.v1", JSON.stringify({ activeProvider: "hotdog", keys: 7 }));
  assert.deepEqual(readByokStore(storage), { activeProvider: null, keys: {} });
});

test("an unknown model for a known provider is rejected", () => {
  const storage = memoryStorage();
  assert.throws(
    () =>
      saveByokKey({ provider: "openai", credential: "sk-x-key-value", model: "gpt-9" }, storage),
    /model/i,
  );
});

test("provider settings arriving from the browser are validated before use", () => {
  assert.deepEqual(
    providerSettingsFromRequest({
      provider: "openrouter",
      model: "deepseek/deepseek-v4-pro",
      credential: "sk-or-key",
    }),
    { provider: "openrouter", model: "deepseek/deepseek-v4-pro", credential: "sk-or-key" },
  );

  // An unusable payload is dropped so the caller falls back to server config
  // rather than sending the backend something it will reject.
  assert.equal(providerSettingsFromRequest(undefined), null);
  assert.equal(
    providerSettingsFromRequest({ provider: "hotdog", model: "x", credential: "k" }),
    null,
  );
  assert.equal(
    providerSettingsFromRequest({ provider: "openai", model: "gpt-4.1", credential: "" }),
    null,
  );
  // A model outside the provider's native-tool-capable set is not silently
  // corrected; the backend would reject it, so the payload is refused.
  assert.equal(
    providerSettingsFromRequest({ provider: "openai", model: "gpt-9", credential: "sk-k" }),
    null,
  );
});
