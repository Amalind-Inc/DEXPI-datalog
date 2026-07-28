import assert from "node:assert/strict";
import test from "node:test";
import { parseInProgressTurnMessage, serializeInProgressTurn } from "./in-progress-turn.ts";

test("serializeInProgressTurn/parseInProgressTurnMessage round-trip", () => {
  const state = {
    steps: [{ id: "retrieval" as const, label: "Retrieval", status: "pending" as const }],
  };
  const parsed = parseInProgressTurnMessage(serializeInProgressTurn(state));
  assert.deepEqual(parsed, state);
});

test("parseInProgressTurnMessage returns null for unrelated text", () => {
  assert.equal(parseInProgressTurnMessage("pydexpi:qa-answer:{}"), null);
  assert.equal(parseInProgressTurnMessage("plain markdown text"), null);
});
