import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { resolveOpenRouterEnv, redactedOpenRouterState } from "./electron-openrouter-config.cjs";

test("Electron resolves OpenRouter from explicit env first and exposes only redacted state", () => {
  const resolved = resolveOpenRouterEnv({ appIsPackaged: false, repoRoot: "/nope", env: { ...process.env, OPENROUTER_API_KEY: " sk-or-env " } });
  assert.equal(resolved.credential, "sk-or-env");
  assert.deepEqual(redactedOpenRouterState(resolved), {
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
    credentialSource: "environment",
    configured: true,
  });
  assert.equal(JSON.stringify(redactedOpenRouterState(resolved)).includes("sk-or-env"), false);
});

test("Electron development boundary reads only the repository-root .env", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-openrouter-root-"));
  try {
    await writeFile(join(root, ".env"), "OPENROUTER_API_KEY='sk-or-root'\n");
    const resolved = resolveOpenRouterEnv({ appIsPackaged: false, repoRoot: root, env: { ...process.env, OPENROUTER_API_KEY: "" } });
    assert.equal(resolved.credential, "sk-or-root");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron can report a deterministic missing OpenRouter state without reading local files", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-openrouter-ignored-"));
  try {
    await writeFile(join(root, ".env"), "OPENROUTER_API_KEY=sk-or-ignored\n");
    const resolved = resolveOpenRouterEnv({ appIsPackaged: false, repoRoot: root, env: { ...process.env, PORTLOG_IGNORE_LOCAL_OPENROUTER_ENV: "1" } });
    assert.deepEqual(redactedOpenRouterState(resolved), { provider: "openrouter", model: "deepseek/deepseek-v4-flash", credentialSource: "environment", configured: false });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron packaged app never reads a bundled or adjacent .env", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-openrouter-packaged-"));
  try {
    await writeFile(join(root, ".env"), "OPENROUTER_API_KEY=sk-or-should-not-load\n");
    const resolved = resolveOpenRouterEnv({ appIsPackaged: true, repoRoot: root, env: { ...process.env, OPENROUTER_API_KEY: "" } });
    assert.deepEqual(redactedOpenRouterState(resolved), {
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
      credentialSource: "environment",
      configured: false,
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
