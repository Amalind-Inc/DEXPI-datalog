const { execFile: nodeExecFile } = require("node:child_process");
const { promisify } = require("node:util");

const execFile = promisify(nodeExecFile);

function createMacOSProviderKeychain(options) {
  const platform = options.platform ?? process.platform;
  const run = options.execFile ?? execFile;
  const label = options.label ?? options.service;
  if (platform !== "darwin")
    throw new Error(`${label} Keychain storage is available only on macOS.`);

  return {
    async read() {
      try {
        const result = await run("security", [
          "find-generic-password",
          "-s",
          options.service,
          "-a",
          options.account,
          "-w",
        ]);
        return String(result.stdout ?? "").trim() || null;
      } catch (error) {
        if (
          Number(error?.status) === 44 ||
          /could not be found|item not found/i.test(String(error?.stderr ?? ""))
        )
          return null;
        throw new Error(`${label} credentials could not be read from Keychain.`);
      }
    },
    async write(value) {
      try {
        await run("security", [
          "add-generic-password",
          "-U",
          "-s",
          options.service,
          "-a",
          options.account,
          "-w",
          value,
        ]);
      } catch {
        throw new Error(`${label} credentials could not be saved to Keychain.`);
      }
    },
    async delete() {
      try {
        await run("security", [
          "delete-generic-password",
          "-s",
          options.service,
          "-a",
          options.account,
        ]);
      } catch (error) {
        if (
          Number(error?.status) === 44 ||
          /could not be found|item not found/i.test(String(error?.stderr ?? ""))
        )
          return;
        throw new Error(`${label} credentials could not be removed from Keychain.`);
      }
    },
  };
}

module.exports = { createMacOSProviderKeychain };
