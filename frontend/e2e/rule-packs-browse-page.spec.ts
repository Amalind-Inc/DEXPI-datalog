import { expect, test, type Page } from "@playwright/test";

const demoMarkdown = `---
pack_id: demo-pack
version: 1
title: Demo Pack
authoritative: false
trust_notice: Demo trust notice
---

# Demo Pack

## Rule One {#r1}

Checks X.

\`\`\`souffle-datalog
rule1(X) :- foo(X).
\`\`\`
`;

const otherMarkdown = `---
pack_id: other-pack
version: 2
title: Other Pack
authoritative: false
trust_notice: Other trust notice
---

# Other Pack

## Rule Two {#r2}

Checks Y.

\`\`\`souffle-datalog
rule2(X) :- bar(X).
\`\`\`
`;

const fixturePacks = {
  packs: [
    {
      pack_id: "demo-pack",
      version: 1,
      title: "Demo Pack",
      authoritative: false,
      trust_notice: "Demo trust notice",
      markdown: demoMarkdown,
      rules: [
        {
          rule_id: "r1",
          title: "Rule One",
          outcomes: ["satisfied", "violated", "indeterminate"],
          restatement: { kind: "plain", plain_language_meaning: "Checks X." },
          executable_logic: {
            kind: "datalog",
            language: "souffle_datalog",
            content: "rule1(X) :- foo(X).\n",
            inspectable: true,
            editable: false,
            disclosure: "Exact Datalog",
          },
        },
      ],
    },
    {
      pack_id: "other-pack",
      version: 2,
      title: "Other Pack",
      authoritative: false,
      trust_notice: "Other trust notice",
      markdown: otherMarkdown,
      rules: [
        {
          rule_id: "r2",
          title: "Rule Two",
          outcomes: ["satisfied", "violated", "indeterminate"],
          restatement: { kind: "plain", plain_language_meaning: "Checks Y." },
          executable_logic: {
            kind: "datalog",
            language: "souffle_datalog",
            content: "rule2(X) :- bar(X).\n",
            inspectable: true,
            editable: false,
            disclosure: "Exact Datalog",
          },
        },
      ],
    },
  ],
};

async function mockPackList(page: Page) {
  await page.route("**/api/rule-packs", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(fixturePacks) }),
  );
}

test("rule-packs table is reachable from the sidebar with no active session (bead 2c5.3)", async ({
  page,
}) => {
  await mockPackList(page);

  await page.goto("/assistant");
  await page.getByRole("link", { name: "Rule Packs" }).click();
  await expect(page).toHaveURL(/\/rule-packs$/);
  await expect(page.getByRole("heading", { name: "Rule Packs" })).toBeVisible();
  await expect(page.getByTestId("rule-pack-table")).toBeVisible();
});

test("table search filters by pack name and rule text (bead 2c5.3)", async ({ page }) => {
  await mockPackList(page);

  await page.goto("/rule-packs");

  const rows = page.getByTestId("rule-pack-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Demo Pack");
  await expect(rows.first()).toContainText("System");

  await page.getByPlaceholder("Search rule packs…").fill("Demo");
  await expect(rows).toHaveCount(1);
  await page.getByPlaceholder("Search rule packs…").fill("Checks Y");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Other Pack");
  await page.getByPlaceholder("Search rule packs…").fill("nonexistent");
  await expect(rows).toHaveCount(0);
});

test("pack row opens a read-only markdown document page with datalog disclosure and raw-source toggle (bead 2c5.3)", async ({
  page,
}) => {
  await mockPackList(page);

  await page.goto("/rule-packs");
  await page.getByTestId("rule-pack-row").first().click();
  await expect(page).toHaveURL(/\/rule-packs\/demo-pack$/);

  // Metadata strip + breadcrumb back to the table.
  await expect(page.getByTestId("rule-pack-meta")).toContainText("System");
  await expect(page.getByTestId("rule-pack-meta")).toContainText("Souffle Datalog");
  const breadcrumb = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(breadcrumb).toContainText("Demo Pack");

  // Rendered markdown document: restatement prose visible, Datalog collapsed.
  const rendered = page.getByTestId("rule-pack-doc-rendered");
  await expect(rendered.getByRole("heading", { name: "Rule One" })).toBeVisible();
  await expect(rendered).toContainText("Checks X.");
  const disclosure = page.getByTestId("rule-logic-disclosure").first();
  await expect(disclosure.locator("pre")).not.toBeVisible();
  await disclosure.locator("summary").click();
  await expect(disclosure.locator("pre")).toContainText("rule1(X)");

  // Raw-source toggle shows the canonical markdown including frontmatter.
  await page.getByTestId("rule-pack-source-toggle").click();
  const source = page.getByTestId("rule-pack-doc-source");
  await expect(source).toBeVisible();
  await expect(source).toContainText("pack_id: demo-pack");
  await expect(source).toContainText("```souffle-datalog");
  await page.getByTestId("rule-pack-source-toggle").click();
  await expect(page.getByTestId("rule-pack-doc-rendered")).toBeVisible();

  // Browsing is read-only: no load/run actions on the document page.
  await expect(page.getByTestId("rule-pack-run-all-button")).toHaveCount(0);
  await expect(page.getByTestId("rule-pack-run-one-button")).toHaveCount(0);

  // Breadcrumb navigates back to the table.
  await breadcrumb.getByRole("link", { name: "Rule Packs" }).click();
  await expect(page).toHaveURL(/\/rule-packs$/);
});
