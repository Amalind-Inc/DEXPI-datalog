import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createPortLogPiAgent } from "./pi-turn-adapter.ts";

test("Pi exposes the deterministic rule-check tool only when PortLog provides the callback", async () => {
  const agentDir = await mkdtemp(join(tmpdir(), "portlog-rule-tool-"));
  await writeFile(
    join(agentDir, "models.json"),
    JSON.stringify({
      providers: {
        "portlog-test": {
          baseUrl: "http://127.0.0.1:1/v1",
          api: "openai-completions",
          apiKey: "test-key",
          models: [{ id: "review-model", reasoning: false, input: ["text"] }],
        },
      },
    }),
  );

  try {
    const withoutCheck = await createPortLogPiAgent({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [] }),
    });
    assert.deepEqual(
      withoutCheck.agent.state.tools.map((tool) => tool.name),
      ["portlog_evidence"],
    );
    await withoutCheck.dispose();

    let received: { checkId: string; scopeEntityId: string } | undefined;
    const withCheck = await createPortLogPiAgent({
      agentDir,
      cwd: agentDir,
      provider: "portlog-test",
      model: "review-model",
      signal: new AbortController().signal,
      getEvidence: async () => ({ citations: [] }),
      getRuleCheck: async ({ checkId, scopeEntityId }) => {
        received = { checkId, scopeEntityId };
        return {
          deterministic_result: {
            check_id: checkId,
            run_status: "completed",
            outcome: "satisfied",
          },
        };
      },
    });
    try {
      const ruleTool = withCheck.agent.state.tools.find(
        (tool) => tool.name === "portlog_rule_check",
      );
      assert.ok(ruleTool);
      const toolResult = await ruleTool.execute("call-rule", {
        checkId: "pump_discharge_check_valve",
        scopeEntityId: "P-101",
      });
      assert.deepEqual(received, {
        checkId: "pump_discharge_check_valve",
        scopeEntityId: "P-101",
      });
      assert.match(JSON.stringify(toolResult), /outcome.*satisfied/);
    } finally {
      await withCheck.dispose();
    }
  } finally {
    await rm(agentDir, { recursive: true, force: true });
  }
});
