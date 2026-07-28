import assert from "node:assert/strict";
import test from "node:test";

import {
  PiPortLogAgentAdapter,
  PORTLOG_CAPABILITY_TOOLS,
  type PiSession,
} from "../src/portlog-agent-adapter.ts";

test("adapts an in-memory Pi session with only PortLog capabilities", async () => {
  const prompts: string[] = [];
  const session: PiSession = {
    sessionFile: undefined,
    subscribe(listener) {
      listener({ type: "text", text: "Inspecting P-101" });
      listener({ type: "tool_start", name: "inspect_pid_region" });
      return () => {};
    },
    async prompt(text) {
      prompts.push(text);
    },
    async abort() {},
    dispose() {},
  };
  let receivedOptions: unknown;
  const agent = new PiPortLogAgentAdapter({
    createSession: async (options) => {
      receivedOptions = options;
      return session;
    },
  });

  const events = [];
  for await (const event of agent.startTurn({
    turnId: "turn-1",
    text: "Inspect P-101",
  })) {
    events.push(event);
  }

  assert.deepEqual(receivedOptions, {
    noBuiltins: true,
    capabilityTools: PORTLOG_CAPABILITY_TOOLS,
  });
  assert.deepEqual(prompts, ["Inspect P-101"]);
  assert.deepEqual(events, [
    { type: "assistant_text_delta", turnId: "turn-1", text: "Inspecting P-101" },
    { type: "inspection_started", turnId: "turn-1", capability: "inspect_pid_region" },
    { type: "turn_completed", turnId: "turn-1" },
  ]);
});

test("rejects a Pi builtin or unknown tool event", async () => {
  const session: PiSession = {
    sessionFile: undefined,
    subscribe(listener) {
      listener({ type: "tool_start", name: "bash" });
      return () => {};
    },
    async prompt() {},
    async abort() {},
    dispose() {},
  };
  const agent = new PiPortLogAgentAdapter({
    createSession: async () => session,
  });

  await assert.rejects(
    async () => {
      for await (const _event of agent.startTurn({ turnId: "turn-2", text: "Inspect P-101" })) {
        // Exhaust the public event stream.
      }
    },
    /unsupported Pi tool: bash/,
  );
});
