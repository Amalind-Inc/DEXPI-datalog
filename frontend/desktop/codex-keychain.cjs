const { createMacOSProviderKeychain } = require("./provider-keychain.cjs");
const { ACCOUNT, SERVICE } = require("./codex-auth-controller.cjs");

function createMacOSCodexKeychain(options = {}) {
  return createMacOSProviderKeychain({
    ...options,
    service: SERVICE,
    account: ACCOUNT,
    label: "OpenAI Codex",
  });
}

module.exports = { createMacOSCodexKeychain };
