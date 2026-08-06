import assert from "node:assert/strict";
import test from "node:test";

import { runVerifierAgentPrototype } from "./verifier-agent-prototype.ts";

test("fixture Pi agent selects the bounded verifier and keeps child history separate", async () => {
  const run = await runVerifierAgentPrototype("Please assess this claim with two children.");

  assert.equal(run.usedVerifier, true);
  assert.equal(run.requestCount, 2);
  assert.equal(run.childCount, 2);
  assert.equal(run.historySize, 3);
  assert.match(run.finalText, /ordinary verifier context/i);
  assert.match(run.finalText, /PortLog authority/i);
});

test("fixture Pi agent declines the verifier for a self-contained request", async () => {
  const run = await runVerifierAgentPrototype(
    "Summarize this self-contained request without a verifier assessment.",
  );

  assert.equal(run.usedVerifier, false);
  assert.equal(run.requestCount, 1);
  assert.equal(run.childCount, 0);
  assert.equal(run.historySize, 0);
  assert.match(run.finalText, /did not use the bounded verifier/i);
});
