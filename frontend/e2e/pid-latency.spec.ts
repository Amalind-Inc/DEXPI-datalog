import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { reviewWorkflow } from "./review-workflow";

const fixtureRoot = path.resolve("..", "TrainingTestCases", "dexpi 1.3", "example pids");
const budgets = JSON.parse(
  readFileSync(path.resolve("e2e", "pid-latency-budgets.json"), "utf8"),
) as {
  profiles: Record<string, { totalMs: number; serverMs: number; browserMainThreadMs: number }>;
};

const cases = [
  {
    profile: "small",
    fixture: path.join(fixtureRoot, "E09 Tank with equipment bar", "E09V01-VER.EX01.xml"),
  },
  {
    profile: "medium",
    fixture: path.join(fixtureRoot, "I02 Control", "I02V01-VER.EX01.xml"),
  },
  {
    profile: "large",
    fixture: path.join(fixtureRoot, "C01 DEXPI Reference P&ID", "C01V04-VER.EX01.xml"),
  },
] as const;

test.describe.configure({ mode: "serial" });

for (const benchmark of cases) {
  test(`${benchmark.profile} DEXPI upload emits a budgeted interactive latency trace`, async ({
    page,
  }, testInfo) => {
    test.setTimeout(45_000);
    const workflow = reviewWorkflow(page);
    await workflow.open();
    await workflow.uploadPlantXml(benchmark.fixture);

    await expect
      .poll(() => page.evaluate(() => window.__PID_LATENCY_TRACE__?.status), {
        timeout: budgets.profiles[benchmark.profile].totalMs,
      })
      .toBe("interactive");

    const trace = await page.evaluate(() => window.__PID_LATENCY_TRACE__);
    expect(trace).toBeDefined();
    if (!trace) throw new Error("P&ID latency trace was not published");

    await testInfo.attach("pid-latency-trace", {
      body: JSON.stringify({ profile: benchmark.profile, ...trace }, null, 2),
      contentType: "application/json",
    });

    const budget = budgets.profiles[benchmark.profile];
    expect(trace.totalMs).toBeLessThanOrEqual(budget.totalMs);
    expect(trace.server?.total_ms).toBeLessThanOrEqual(budget.serverMs);
    expect(
      (trace.phasesMs.layout ?? 0) + (trace.phasesMs.react_commit_to_interactive ?? 0),
    ).toBeLessThanOrEqual(budget.browserMainThreadMs);
    expect(trace.server?.phases_ms.xml_parse).toBeGreaterThanOrEqual(0);
    expect(trace.server?.phases_ms.graph_extraction).toBeGreaterThanOrEqual(0);
    expect(trace.counts.uploadBytes).toBeGreaterThan(0);
    expect(trace.counts.responseBytes).toBeGreaterThan(0);
    expect(trace.counts.renderedEntities).toBeGreaterThan(0);
    expect(trace.counts.svgElements).toBeGreaterThan(0);
  });
}
