const { createProviderAuthController } = require("./provider-auth-controller.cjs");

const DEFAULT_TIMEOUT_MS = 120_000;
const PROVIDER = "openai-codex";
const SERVICE = "org.portlog.desktop.openai-codex.oauth";
const ACCOUNT = "default";
const OPENAI_CODEX_BROWSER_LOGIN_METHOD = "browser";
const OPENAI_CODEX_DEVICE_CODE_LOGIN_METHOD = "device_code";

function createCodexAuthController(options) {
  return createProviderAuthController({
    ...options,
    provider: PROVIDER,
    label: "OpenAI Codex",
    service: SERVICE,
    account: ACCOUNT,
    errorCode: "OPENAI_CODEX_AUTH_RECOVERABLE",
    selectLogin:
      options.selectLogin ??
      (async (_prompt, requestedLoginMethod) =>
        requestedLoginMethod ?? OPENAI_CODEX_BROWSER_LOGIN_METHOD),
  });
}

module.exports = {
  ACCOUNT,
  DEFAULT_TIMEOUT_MS,
  OPENAI_CODEX_BROWSER_LOGIN_METHOD,
  OPENAI_CODEX_DEVICE_CODE_LOGIN_METHOD,
  PROVIDER,
  SERVICE,
  createCodexAuthController,
};
