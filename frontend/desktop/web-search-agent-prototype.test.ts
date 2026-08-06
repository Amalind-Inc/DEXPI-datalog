import assert from "node:assert/strict";
import test from "node:test";

import { runWebSearchAgentPrototype } from "./web-search-agent-prototype.ts";

test("fixture Pi agent selects web_search for an external research request", async () => {
  const run = await runWebSearchAgentPrototype(
    "Search the web for bounded PortLog review context.",
  );

  assert.equal(run.usedWebSearch, true);
  assert.equal(run.requestCount, 2);
  assert.match(run.finalText, /ordinary, untrusted external context/i);
});

test("fixture Pi agent does not search for a self-contained request", async () => {
  const run = await runWebSearchAgentPrototype(
    "Summarize this self-contained request without external research.",
  );

  assert.equal(run.usedWebSearch, false);
  assert.equal(run.requestCount, 1);
  assert.match(run.finalText, /did not use web_search/i);
});
