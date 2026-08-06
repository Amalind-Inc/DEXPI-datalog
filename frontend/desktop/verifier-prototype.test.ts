import assert from "node:assert/strict";
import test from "node:test";

import {
  createInMemoryVerifierHistory,
  createVerifierTool,
  runBoundedVerifier,
  type VerifierRunner,
} from "./verifier-prototype.ts";

const supported = {
  schemaVersion: 1,
  assessment: "supported" as const,
  summary: "The bounded fixture supports the requested claim.",
  claims: [
    {
      id: "claim-1",
      assessment: "supported" as const,
      rationale: "The normalized fixture input contains the required fact.",
    },
  ],
  uncertainty: [],
};

test("verifier normalizes input, receives no tools, and stores separate host-owned child history", async () => {
  const history = createInMemoryVerifierHistory();
  let received: { task: string; input: unknown; tools: readonly unknown[] } | undefined;
  const runner: VerifierRunner = async (request, context) => {
    received = { task: request.task, input: request.input, tools: context.tools };
    return { assessment: supported };
  };

  const response = await runBoundedVerifier(
    { roleId: "bounded-review", task: "  Check the pump claim.  ", input: { tag: " P-101 " } },
    { runner, history },
  );

  assert.equal(response.status, "ok");
  assert.equal(response.authority, "ordinary");
  assert.equal(response.origin, "verifier");
  assert.deepEqual(received, {
    task: "Check the pump claim.",
    input: { tag: " P-101 " },
    tools: [],
  });
  assert.equal(response.childIds.length, 0);
  assert.equal(history.records.length, 1);
  assert.equal(history.records[0]?.depth, 0);
  assert.equal(history.records[0]?.status, "ok");
});

test("invalid or oversized requests are rejected before the verifier runs", async () => {
  let calls = 0;
  const runner: VerifierRunner = async () => {
    calls += 1;
    return { assessment: supported };
  };

  const response = await runBoundedVerifier(
    { roleId: "arbitrary-role", task: "run anything", input: {} },
    { runner },
  );
  const oversized = await runBoundedVerifier(
    { roleId: "bounded-review", task: "x".repeat(501), input: {} },
    { runner },
  );

  assert.equal(response.status, "unavailable");
  assert.equal(oversized.status, "unavailable");
  assert.equal(calls, 0);
});

test("malformed verifier output is unavailable without automatic retry", async () => {
  let calls = 0;
  const runner: VerifierRunner = async () => {
    calls += 1;
    return { assessment: { schemaVersion: 99, answer: "model prose" } };
  };

  const response = await runBoundedVerifier(
    { roleId: "bounded-review", task: "Check the claim.", input: {} },
    { runner },
  );

  assert.equal(response.status, "unavailable");
  assert.match(response.diagnostic ?? "", /schema/i);
  assert.equal(calls, 1);
});

test("recursion and global child budgets are enforced by the host", async () => {
  const history = createInMemoryVerifierHistory();
  const runner: VerifierRunner = async (request) => ({
    assessment: supported,
    children:
      request.depth < 3
        ? [
            { roleId: "bounded-review", task: `child-a-${request.depth}`, input: {} },
            { roleId: "bounded-review", task: `child-b-${request.depth}`, input: {} },
          ]
        : [],
  });

  const response = await runBoundedVerifier(
    { roleId: "bounded-review", task: "Root assessment", input: {} },
    {
      runner,
      history,
      limits: { maxDepth: 2, maxChildrenPerRun: 2, maxTotalRuns: 3 },
    },
  );

  assert.equal(response.status, "ok");
  assert.equal(response.childIds.length, 1);
  assert.equal(history.records.length, 3);
  assert.deepEqual(
    history.records.map((record) => record.depth),
    [2, 1, 0],
  );
  assert.ok(history.records.every((record) => record.authority === "ordinary"));
});

test("task tool returns the strict ordinary verifier envelope", async () => {
  const tool = createVerifierTool({
    runner: async () => ({ assessment: supported }),
  });
  const response = await tool.execute("task-1", {
    roleId: "bounded-review",
    task: "Check P-101.",
    input: { tag: "P-101" },
  });
  const text = response.content.find((part) => part.type === "text")?.text;
  assert.ok(text);
  const value = JSON.parse(text) as Record<string, unknown>;
  assert.equal(tool.name, "task");
  assert.equal(value.status, "ok");
  assert.equal(value.authority, "ordinary");
  assert.equal(value.origin, "verifier");
});
