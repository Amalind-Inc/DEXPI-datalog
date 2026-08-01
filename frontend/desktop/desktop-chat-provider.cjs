const fs = require("node:fs/promises");
const path = require("node:path");

const CHAT_PROVIDERS = new Set(["anthropic", "openai-codex"]);
const FILE_NAME = "chat-provider.json";

function isChatProvider(value) {
  return typeof value === "string" && CHAT_PROVIDERS.has(value);
}

function createDesktopChatProviderStore({ directory }) {
  const filePath = path.join(directory, FILE_NAME);

  return {
    async load() {
      try {
        const parsed = JSON.parse(await fs.readFile(filePath, "utf8"));
        return isChatProvider(parsed?.provider) ? parsed.provider : null;
      } catch {
        return null;
      }
    },

    async save(provider) {
      if (provider !== null && !isChatProvider(provider))
        throw new Error(`Unsupported desktop chat provider: ${String(provider)}`);

      await fs.mkdir(directory, { recursive: true });
      const temporaryPath = `${filePath}.${process.pid}.tmp`;
      try {
        await fs.writeFile(temporaryPath, `${JSON.stringify({ provider })}\n`, {
          encoding: "utf8",
          mode: 0o600,
        });
        await fs.rename(temporaryPath, filePath);
      } finally {
        await fs.rm(temporaryPath, { force: true });
      }
      return provider;
    },
  };
}

module.exports = { createDesktopChatProviderStore, isChatProvider };
