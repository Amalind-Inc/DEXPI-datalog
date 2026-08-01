const { createProviderAuthController } = require("./provider-auth-controller.cjs");

const DEFAULT_TIMEOUT_MS = 120_000;
const PROVIDER = "anthropic";
const SERVICE = "org.portlog.desktop.anthropic.oauth";
const ACCOUNT = "default";

function createClaudeAuthController(options) {
  return createProviderAuthController({
    ...options,
    provider: PROVIDER,
    label: "Claude",
    service: SERVICE,
    account: ACCOUNT,
    errorCode: "CLAUDE_AUTH_RECOVERABLE",
    selectLogin: async () => undefined,
  });
}

module.exports = {
  ACCOUNT,
  DEFAULT_TIMEOUT_MS,
  PROVIDER,
  SERVICE,
  createClaudeAuthController,
};
