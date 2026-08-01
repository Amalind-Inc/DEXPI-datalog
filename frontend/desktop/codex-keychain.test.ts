import assert from "node:assert/strict";
import test from "node:test";

import { ACCOUNT, SERVICE } from "./codex-auth-controller.cjs";
import { createMacOSCodexKeychain } from "./codex-keychain.cjs";

test("macOS Codex Keychain adapter uses a distinct fixed service and account", async () => {
  const calls: Array<{ command: string; args: string[] }> = [];
  const keychain = createMacOSCodexKeychain({
    platform: "darwin",
    execFile: async (command: string, args: string[]) => {
      calls.push({ command, args });
      if (args[0] === "find-generic-password") return { stdout: "codex-token\n" };
      return { stdout: "" };
    },
  });

  assert.equal(await keychain.read(), "codex-token");
  await keychain.write("codex-access");
  await keychain.delete();
  assert.deepEqual(calls, [
    { command: "security", args: ["find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"] },
    {
      command: "security",
      args: ["add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", "codex-access"],
    },
    { command: "security", args: ["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT] },
  ]);
});

test("Codex Keychain adapter rejects non-macOS use", () => {
  assert.throws(() => createMacOSCodexKeychain({ platform: "linux" }), /only on macOS/i);
});

test("Codex Keychain treats a missing item as logged out", async () => {
  const keychain = createMacOSCodexKeychain({
    platform: "darwin",
    execFile: async () => {
      const error = new Error("missing") as Error & { status?: number };
      error.status = 44;
      throw error;
    },
  });
  assert.equal(await keychain.read(), null);
  await keychain.delete();
});
