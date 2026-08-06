import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyBashRequest,
  createGovernedBashTool,
  type BashExecutionResult,
  type NormalizedBashRequest,
} from "./bash-capability.ts";

const workspaceRoot = "/workspace/project";

function result(stdout = "ok"): BashExecutionResult {
  return {
    outcome: "admitted",
    stdout,
    stderr: "",
    diagnostic: "Command completed.",
    exitCode: 0,
  };
}

test("classifier keeps only exact read-only commands on the host", () => {
  assert.equal(
    classifyBashRequest({ command: " git status   --short " }, workspaceRoot).route,
    "host-safe",
  );
  assert.equal(
    classifyBashRequest({ command: "git status --short && cat secrets.txt" }, workspaceRoot).route,
    "gondolin",
  );
  assert.equal(classifyBashRequest({ command: "rm -rf build" }, workspaceRoot).route, "gondolin");
  assert.equal(
    classifyBashRequest({ command: "git status --short", pty: true }, workspaceRoot).route,
    "unavailable",
  );
  assert.equal(
    classifyBashRequest({ command: "pwd", cwd: "/tmp" }, workspaceRoot).route,
    "unavailable",
  );
});

test("host-safe execution receives normalized input and emits bounded output", async () => {
  let received: NormalizedBashRequest | undefined;
  const updates: string[] = [];
  const tool = createGovernedBashTool({
    workspaceRoot,
    runHostSafe: async (request, _signal, onUpdate) => {
      received = request;
      onUpdate?.({ stdout: "live output", stderr: "" });
      return result("final output");
    },
  });

  const response = await tool.execute(
    "bash-host-safe",
    { command: "  pwd  " },
    undefined,
    (update) => {
      updates.push(update.content[0]?.text ?? "");
    },
  );
  const value = JSON.parse(response.content[0]?.text ?? "{}");

  assert.deepEqual(received, {
    command: "pwd",
    cwd: workspaceRoot,
    timeoutMs: 3_000,
    pty: false,
    env: {},
  });
  assert.equal(value.route, "host-safe");
  assert.equal(value.outcome, "admitted");
  assert.equal(value.stdout, "final output");
  assert.equal(value.authority, "ordinary");
  assert.equal(value.output_truncated, false);
  assert.equal(updates.length, 1);
});

test("compound and risky commands route atomically to Gondolin", async () => {
  let hostCalls = 0;
  let guestCalls = 0;
  let received: NormalizedBashRequest | undefined;
  const tool = createGovernedBashTool({
    workspaceRoot,
    runHostSafe: async () => {
      hostCalls += 1;
      return result();
    },
    runGondolin: async (request) => {
      guestCalls += 1;
      received = request;
      return result("guest output");
    },
  });

  const response = await tool.execute("bash-gondolin", {
    command: "git status --short && cat review.json",
  });
  const value = JSON.parse(response.content[0]?.text ?? "{}");

  assert.equal(hostCalls, 0);
  assert.equal(guestCalls, 1);
  assert.equal(received?.command, "git status --short && cat review.json");
  assert.equal(value.route, "gondolin");
  assert.equal(value.stdout, "guest output");
});

test("Gondolin unavailability never falls back to the host", async () => {
  let hostCalls = 0;
  const tool = createGovernedBashTool({
    workspaceRoot,
    runHostSafe: async () => {
      hostCalls += 1;
      return result();
    },
  });

  const response = await tool.execute("bash-unavailable", { command: "npm test" });
  const value = JSON.parse(response.content[0]?.text ?? "{}");

  assert.equal(hostCalls, 0);
  assert.equal(value.route, "unavailable");
  assert.equal(value.outcome, "unavailable");
});

test("unsupported or malformed requests are rejected without execution", async () => {
  let calls = 0;
  const tool = createGovernedBashTool({
    workspaceRoot,
    runHostSafe: async () => {
      calls += 1;
      return result();
    },
    runGondolin: async () => {
      calls += 1;
      return result();
    },
  });

  const response = await tool.execute("bash-invalid", {
    command: "git status --short",
    env: { SECRET: "x" },
  });
  const value = JSON.parse(response.content[0]?.text ?? "{}");

  assert.equal(calls, 0);
  assert.equal(value.route, "unavailable");
  assert.equal(value.outcome, "rejected");
});
