import assert from "node:assert/strict";
import test from "node:test";
import {
  type ByokStore,
  clearByokKey,
  maskCredential,
  providerSettingsFromStore,
  readByokStore,
  saveByokKey,
  selectActiveProvider,
  setProviderModel,
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

test("saving a key makes that provider the active one and records a masked preview", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-abcdefgh12345678", model: "gpt-4.1" }, storage);

  const store = readByokStore(storage);
  assert.equal(store.activeProvider, "openai");
  assert.equal(store.keys.openai?.credential, "sk-abcdefgh12345678");
  assert.equal(store.keys.openai?.model, "gpt-4.1");
  assert.equal(maskCredential("sk-abcdefgh12345678"), "sk-a…5678");
});

test("any catalogued provider id can hold a key, not just a fixed few", () => {
  // The provider set comes from the models.dev catalogue at runtime, so the
  // store must not gatekeep on a hardcoded list.
  const storage = memoryStorage();
  for (const provider of ["openrouter", "groq", "cerebras", "zhipuai", "ollama"]) {
    saveByokKey({ provider, credential: `key-for-${provider}`, model: "some-model" }, storage);
  }

  assert.deepEqual(Object.keys(readByokStore(storage).keys).sort(), [
    "cerebras",
    "groq",
    "ollama",
    "openrouter",
    "zhipuai",
  ]);
  assert.equal(readByokStore(storage).activeProvider, "openrouter");
});

test("a second key is stored alongside the first without stealing the active slot", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);
  saveByokKey(
    { provider: "google", credential: "gemini-key-value", model: "gemini-2.5-pro" },
    storage,
  );

  assert.equal(readByokStore(storage).activeProvider, "openai");

  selectActiveProvider("google", storage);
  assert.equal(readByokStore(storage).activeProvider, "google");
});

test("selecting a provider with no stored key is refused", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);

  assert.throws(() => selectActiveProvider("anthropic", storage), /no stored key/i);
  assert.equal(readByokStore(storage).activeProvider, "openai");
});

test("switching the model on a stored key keeps the credential", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);

  setProviderModel("openai", "gpt-5.1", storage);
  const entry = readByokStore(storage).keys.openai;
  assert.equal(entry?.model, "gpt-5.1");
  assert.equal(entry?.credential, "sk-openai-key-value");
});

test("clearing the active key falls back to another stored provider", () => {
  const storage = memoryStorage();
  saveByokKey({ provider: "openai", credential: "sk-openai-key-value", model: "gpt-4.1" }, storage);
  saveByokKey({ provider: "groq", credential: "gsk-key-value", model: "llama-3.3" }, storage);

  clearByokKey("openai", storage);
  const store = readByokStore(storage);
  assert.equal(store.activeProvider, "groq");
  assert.equal(store.keys.openai, undefined);

  clearByokKey("groq", storage);
  assert.equal(readByokStore(storage).activeProvider, null);
});

test("a blank credential is accepted only for a local provider", () => {
  const storage = memoryStorage();
  assert.throws(
    () => saveByokKey({ provider: "openai", credential: "   ", model: "gpt-4.1" }, storage),
    /credential/i,
  );
  // A local server authenticates by endpoint, not by key.
  saveByokKey({ provider: "ollama", credential: "", model: "ornith:35b", isLocal: true }, storage);
  assert.equal(readByokStore(storage).keys.ollama?.model, "ornith:35b");
});

test("a key with no model selected is refused", () => {
  const storage = memoryStorage();
  assert.throws(
    () => saveByokKey({ provider: "openai", credential: "sk-key-value", model: "  " }, storage),
    /model/i,
  );
});

test("provider settings are derived from the active key for the backend call", () => {
  const storage = memoryStorage();
  assert.equal(providerSettingsFromStore(readByokStore(storage)), null);

  saveByokKey(
    { provider: "anthropic", credential: "sk-ant-key-value", model: "claude-sonnet-4-5" },
    storage,
  );
  assert.deepEqual(providerSettingsFromStore(readByokStore(storage)), {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    credential: "sk-ant-key-value",
  });
});

test("corrupt or foreign storage contents read back as an empty store", () => {
  const storage = memoryStorage();
  storage.setItem("pydexpi.byok.v1", "{not json");
  assert.deepEqual(readByokStore(storage), { activeProvider: null, keys: {} } satisfies ByokStore);

  storage.setItem("pydexpi.byok.v1", JSON.stringify({ activeProvider: "openai", keys: 7 }));
  assert.deepEqual(readByokStore(storage), { activeProvider: null, keys: {} });
});

test("an active provider whose key was removed out of band does not stay active", () => {
  const storage = memoryStorage();
  storage.setItem(
    "pydexpi.byok.v1",
    JSON.stringify({ activeProvider: "openai", keys: { groq: { credential: "k", model: "m" } } }),
  );

  assert.equal(readByokStore(storage).activeProvider, null);
});
