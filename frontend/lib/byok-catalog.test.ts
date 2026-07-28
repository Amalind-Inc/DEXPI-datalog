import assert from "node:assert/strict";
import test from "node:test";
import {
  loadByokCatalog,
  providerIndex,
  providerModels,
  validateProviderSettings,
} from "./byok-catalog.ts";

test("the vendored catalogue exposes a broad provider set", () => {
  const catalog = loadByokCatalog();

  assert.ok(Object.keys(catalog.providers).length > 100);
  assert.ok(catalog.featured.includes("openrouter"));
  // Local model servers ride along with the hosted catalogue.
  assert.equal(catalog.providers.ollama?.is_local, true);
});

test("the index is small enough to ship to the browser and is featured-first", () => {
  const index = providerIndex();

  assert.ok(index.length > 100);
  assert.deepEqual(
    index.slice(0, 4).map((p) => p.id),
    ["openrouter", "anthropic", "openai", "google"],
  );
  // No model lists in the index — those are fetched per provider.
  assert.deepEqual(Object.keys(index[0]).sort(), ["doc", "id", "isLocal", "modelCount", "name"]);
  assert.ok(JSON.stringify(index).length < 60_000);
});

test("models are served per provider, newest first", () => {
  const models = providerModels("anthropic");

  assert.ok(models.length > 5);
  assert.ok(models.every((m) => m.id && m.name));
  // The picker defaults to the head of the list, so it must be current.
  const released = models.map((m) => m.released).filter(Boolean);
  assert.deepEqual(released, [...released].sort().reverse());
  assert.equal(providerModels("nope-not-real").length, 0);
});

test("a local provider reports no fixed model list", () => {
  assert.deepEqual(providerModels("ollama"), []);
});

test("provider settings are validated against the catalogue", () => {
  assert.deepEqual(
    validateProviderSettings({
      provider: "openrouter",
      model: "deepseek/deepseek-v4-pro",
      credential: "sk-or-key",
    }),
    { provider: "openrouter", model: "deepseek/deepseek-v4-pro", credential: "sk-or-key" },
  );

  // Unknown provider, blank credential, and a model the provider does not
  // serve are all refused so the caller falls back to server configuration.
  assert.equal(validateProviderSettings({ provider: "hotdog", model: "m", credential: "k" }), null);
  assert.equal(
    validateProviderSettings({ provider: "openai", model: "gpt-4.1", credential: "  " }),
    null,
  );
  assert.equal(
    validateProviderSettings({ provider: "openai", model: "claude-opus-4-6", credential: "k" }),
    null,
  );
  assert.equal(validateProviderSettings(undefined), null);
});

test("a local provider accepts whatever model the operator has pulled", () => {
  assert.deepEqual(
    validateProviderSettings({ provider: "ollama", model: "ornith:35b", credential: "" }),
    { provider: "ollama", model: "ornith:35b", credential: "" },
  );
  // Still needs *a* model.
  assert.equal(validateProviderSettings({ provider: "ollama", model: "", credential: "" }), null);
});

test("the legacy gemini provider id still resolves", () => {
  // Keys stored before the catalogue adoption used "gemini"; models.dev calls
  // the same provider "google".
  const settings = validateProviderSettings({
    provider: "gemini",
    model: "gemini-2.5-pro",
    credential: "AIza-key",
  });

  assert.equal(settings?.provider, "google");
  assert.equal(settings?.model, "gemini-2.5-pro");
});
