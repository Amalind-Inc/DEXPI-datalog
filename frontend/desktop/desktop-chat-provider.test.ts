import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createDesktopChatProviderStore } from "./desktop-chat-provider.cjs";

test("desktop chat provider selection survives a new store instance", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "portlog-chat-provider-"));
  const firstStore = createDesktopChatProviderStore({ directory });

  assert.equal(await firstStore.load(), null);
  await firstStore.save("openai-codex");

  const secondStore = createDesktopChatProviderStore({ directory });
  assert.equal(await secondStore.load(), "openai-codex");
  assert.deepEqual(JSON.parse(await readFile(path.join(directory, "chat-provider.json"), "utf8")), {
    provider: "openai-codex",
  });
});

test("desktop chat provider selection rejects invalid providers", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "portlog-chat-provider-"));
  const store = createDesktopChatProviderStore({ directory });

  await assert.rejects(() => store.save("not-a-provider"), /Unsupported desktop chat provider/);
  assert.equal(await store.load(), null);
});
