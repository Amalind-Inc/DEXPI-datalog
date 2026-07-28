import assert from "node:assert/strict";
import test from "node:test";

import {
  PiPortLogAgentAdapter,
  type PiSession,
} from "../src/portlog-agent-adapter.ts";

test("adapts an in-memory Pi session into PortLog-owned events without a session file", async () => {
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

  const agent = new PiPortLogAgentAdapter({
    createSession: async () => session,
  });

  const events = [];
  for await (const event of agent.startTurn({
    turnId: "turn-1",
    text: "Inspect P-101",
  })) {
    events.push(event);
  }

  assert.deepEqual(prompts, ["Inspect P-101"]);
  assert.deepEqual(events, [
    { type: "assistant_text_delta", turnId: "turn-1", text: "Inspecting P-101" },
    { type: "inspection_started", turnId: "turn-1", capability: "inspect_pid_region" },
    { type: "turn_completed", turnId: "turn-1" },
  ]);
});
