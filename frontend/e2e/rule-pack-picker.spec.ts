import { expect, test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

const fixturePacks = {
  session_id: "s1",
  packs: [
    {
      pack_id: "demo-pack",
      version: 1,
      title: "Demo Pack",
      authoritative: true,
      trust_notice: "Demo trust notice",
      loaded: false,
      advisory_guidance: [],
      rules: [
        {
          rule_id: "r1",
          title: "Rule One",
          outcomes: ["satisfied", "violated", "indeterminate"],
          restatement: { kind: "plain", plain_language_meaning: "Checks X." },
          executable_logic: {
            kind: "datalog",
            language: "datalog",
            content: "rule1(X) :- foo(X).",
            inspectable: true,
            editable: false,
            disclosure: "Exact Datalog",
          },
        },
        {
          rule_id: "r2",
          title: "Rule Two",
          outcomes: ["satisfied", "violated", "indeterminate"],
          restatement: { kind: "plain", plain_language_meaning: "Checks Y." },
          executable_logic: {
            kind: "datalog",
            language: "datalog",
            content: "rule2(X) :- bar(X).",
            inspectable: true,
            editable: false,
            disclosure: "Exact Datalog",
          },
        },
        {
          rule_id: "r3",
          title: "Rule Three",
          outcomes: ["satisfied", "violated", "indeterminate"],
          restatement: { kind: "plain", plain_language_meaning: "Checks Z." },
          executable_logic: {
            kind: "datalog",
            language: "datalog",
            content: "rule3(X) :- baz(X).",
            inspectable: true,
            editable: false,
            disclosure: "Exact Datalog",
          },
        },
      ],
    },
  ],
};

const fixtureLoad = {
  session_id: "s1",
  pack_id: "demo-pack",
  loaded: true,
  pack: {
    pack_id: "demo-pack",
    version: 1,
    title: "Demo Pack",
    authoritative: true,
    trust_notice: "Demo trust notice",
  },
};

function rulePackResult(ruleId: string, outcome: string, evidenceIds: string[]) {
  return {
    status: "answered",
    session_id: "s1",
    rule_id: ruleId,
    pack: {
      pack_id: "demo-pack",
      version: 1,
      authoritative: true,
      trust_notice: "Demo trust notice",
    },
    outcome,
    confirmation: { required: false },
    summary: { position: "first", text: `${ruleId}: ${outcome}.` },
    result_artifact: { kind: "rule_pack_result", path: `${ruleId}.json` },
    evidence: { display: "expandable", items: evidenceIds.map((id) => ({ id })) },
    evidence_highlight: {
      source_scope_ids: [],
      matched_object_ids: evidenceIds,
      paths: evidenceIds.map((id) => ({ id, node_ids: [id], edge_ids: [] })),
    },
    diagnostics: [],
  };
}

const fixtureRun = {
  status: "answered",
  session_id: "s1",
  pack_id: "demo-pack",
  confirmation: { required: false },
  results: [
    rulePackResult("r1", "satisfied", ["node-a"]),
    rulePackResult("r2", "violated", []),
    rulePackResult("r3", "indeterminate", []),
  ],
};

test("pick, load, and run a rule pack posts a stepped in-thread result (bead 2ki.14)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await expect(workflow.graphPanel.getByText("E06V01-VER.EX01.xml")).toBeVisible();
  await expect(page.getByTestId("auto-layout-schematic")).toBeVisible();

  let loadRequestPackId: string | null = null;
  await page.route("**/api/review/sessions/*/rule-packs", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixturePacks) }),
  );
  await page.route("**/api/review/sessions/*/rule-packs/*/load", async (route) => {
    loadRequestPackId = route.request().url().match(/rule-packs\/([^/]+)\/load/)?.[1] ?? null;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(fixtureLoad) });
  });
  await page.route("**/api/review/sessions/*/rule-packs/*/run", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixtureRun) }),
  );

  await workflow.openRulePacksFlyout();

  // Search filters the list.
  await page.getByPlaceholder("Search rule packs…").fill("Demo");
  await expect(workflow.rulePackListItems).toHaveCount(1);
  await page.getByPlaceholder("Search rule packs…").fill("nonexistent");
  await expect(workflow.rulePackListItems).toHaveCount(0);
  await page.getByPlaceholder("Search rule packs…").fill("");

  // Select a pack: detail pane shows restatement first, Datalog behind disclosure.
  await workflow.rulePackListItems.first().click();
  await expect(page.getByTestId("rule-restatement").first()).toContainText("Checks X.");
  await expect(page.getByTestId("rule-logic-disclosure").first().locator("pre")).not.toBeVisible();
  await page.getByTestId("rule-logic-disclosure").first().locator("summary").click();
  await expect(page.getByTestId("rule-logic-disclosure").first().locator("pre")).toContainText(
    "rule1(X)",
  );

  // Load-on-select: no Load button, the load POST fires automatically.
  await expect
    .poll(() => loadRequestPackId)
    .toBe("demo-pack");
  await expect(page.getByTestId("rule-pack-load-status")).toHaveText("Loaded");
  await expect(page.locator('[data-role="assistant"]')).toHaveCount(0);

  // Run all checks posts a stepped turn with correct outcome glyphs, one step per rule.
  await page.getByTestId("rule-pack-run-all-button").click();
  await page.getByTestId("rule-pack-run-card").waitFor({ state: "visible" });
  await expect(workflow.ruleRunSteps).toHaveCount(3);
  await expect(workflow.ruleRunSteps.nth(0)).toHaveAttribute("data-outcome", "satisfied");
  await expect(workflow.ruleRunSteps.nth(1)).toHaveAttribute("data-outcome", "violated");
  await expect(workflow.ruleRunSteps.nth(2)).toHaveAttribute("data-outcome", "indeterminate");

  // The flyout closed so the thread (single narrative) is visible again.
  await expect(page.getByTestId("rule-pack-picker")).toHaveCount(0);

  // Evidence chip highlights the schematic.
  const graph = page.getByTestId("auto-layout-schematic");
  await expect(graph).toBeVisible();
  await page.getByTestId("rule-evidence-chip").first().click();
  await expect(graph).toHaveAttribute("data-highlight-active", "true", { timeout: 3000 });
});

test("running a single rule from the detail pane posts a one-step in-thread result (bead 2ki.14)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await expect(workflow.graphPanel.getByText("E06V01-VER.EX01.xml")).toBeVisible();
  await expect(page.getByTestId("auto-layout-schematic")).toBeVisible();

  await page.route("**/api/review/sessions/*/rule-packs", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixturePacks) }),
  );
  await page.route("**/api/review/sessions/*/rule-packs/*/load", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixtureLoad) }),
  );
  let singleRuleBody: unknown;
  await page.route("**/api/review/sessions/*/rule-pack-results", async (route) => {
    singleRuleBody = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(rulePackResult("r2", "violated", [])),
    });
  });

  await workflow.openRulePacksFlyout();
  await workflow.rulePackListItems.first().click();
  await page.getByTestId("rule-pack-run-one-button").nth(1).click();

  await page.getByTestId("rule-pack-run-card").waitFor({ state: "visible" });
  await expect(workflow.ruleRunSteps).toHaveCount(1);
  await expect(workflow.ruleRunSteps.first()).toHaveAttribute("data-outcome", "violated");
  await expect
    .poll(() => (singleRuleBody as { rule_id?: string } | undefined)?.rule_id)
    .toBe("r2");
});

test("a session-not-ready load error surfaces inline without posting to the thread (bead 2ki.14)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await expect(workflow.graphPanel.getByText("E06V01-VER.EX01.xml")).toBeVisible();
  await expect(page.getByTestId("auto-layout-schematic")).toBeVisible();

  await page.route("**/api/review/sessions/*/rule-packs", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixturePacks) }),
  );
  await page.route("**/api/review/sessions/*/rule-packs/*/load", (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "session.not_ready", message: "Session is not ready yet." } }),
    }),
  );

  await workflow.openRulePacksFlyout();
  await workflow.rulePackListItems.first().click();

  await expect(page.getByTestId("rule-pack-action-error")).toContainText("Session is not ready yet.");
  await expect(page.locator('[data-role="assistant"]')).toHaveCount(0);
});
