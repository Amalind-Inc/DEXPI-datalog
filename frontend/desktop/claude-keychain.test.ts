import assert from "node:assert/strict";
import test from "node:test";

import { createMacOSClaudeKeychain } from "./claude-keychain.cjs";
import { ACCOUNT, SERVICE } from "./claude-auth-controller.cjs";

test("macOS Claude Keychain adapter uses the fixed service/account and redacts failures", async () => {
  const calls: Array<{ command: string; args: string[] }> = [];
  const keychain = createMacOSClaudeKeychain({
    platform: "darwin",
    execFile: async (command: string, args: string[]) => {
      calls.push({ command, args });
      if (args[0] === "find-generic-password") return { stdout: "stored-token\n" };
      return { stdout: "" };
    },
  });

  assert.equal(await keychain.read(), "stored-token");
  await keychain.write("access-secret");
  await keychain.delete();
  assert.deepEqual(calls, [
    { command: "security", args: ["find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"] },
    {
      command: "security",
      args: ["add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", "access-secret"],
    },
    { command: "security", args: ["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT] },
  ]);
});

test("Keychain adapter treats a missing item as logged out and rejects non-macOS use", async () => {
  const missing = createMacOSClaudeKeychain({
    platform: "darwin",
    execFile: async () => {
      const error = new Error("missing") as Error & { status?: number };
      error.status = 44;
      throw error;
    },
  });
  assert.equal(await missing.read(), null);
  await assert.rejects(
    Promise.resolve().then(() => createMacOSClaudeKeychain({ platform: "linux" })),
    /only on macOS/i,
  );
});
