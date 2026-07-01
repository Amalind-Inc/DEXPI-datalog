import { expect, test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

test("uploads E06 XML and a direct topology question gets a grounded QA answer without Datalog confirmation", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.expectGraphNonPrimaryBeforeUpload();

  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What downstream process objects are reachable from the pump?");
  await page.getByTestId("grounded-qa-answer").waitFor({ state: "visible" });

  // Must not require confirmation — answer appears immediately
  await expect(workflow.confirmationCards).toHaveCount(0);
  await workflow.expectLatestAssistantReplyNotToContain(/Review before execution/);
  await workflow.expectLatestAssistantReplyNotToContain(/pydexpi:datalog-confirmation/);

  // Answer text is visible
  await expect(page.getByTestId("qa-answer-text")).toBeVisible();
  await workflow.expectLatestAssistantReplyNotToContain(/I am grounding this QA answer/);
  await workflow.expectViewportHeightStable();
});

test("QA answer evidence chips open the topology panel and highlight structural witnesses on click", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What is reachable from the pump?");
  await page.getByTestId("grounded-qa-answer").waitFor({ state: "visible" });

  // Evidence chips are rendered
  const chips = page.getByTestId("qa-evidence-chip");
  await expect(chips.first()).toBeVisible();

  // Clicking a chip applies highlights in the graph panel
  const graphPanel = page.getByRole("complementary", { name: "P&ID graph panel" });
  await chips.first().click();

  // The graph panel must show at least one highlighted node after chip click
  // (the `.highlighted` CSS class is applied to SVG rect elements by graph-panel.tsx)
  await expect(graphPanel.locator("rect.highlighted").first()).toBeVisible({ timeout: 3000 });
});

test("bundled pump discharge check renders tri-state result and inspectable evidence", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");
  await workflow.sendPrompt("Run the bundled pump discharge check.");

  const result = page.getByTestId("grounded-logic-answer").last();
  await expect(result).toBeVisible();
  await expect(result.getByTestId("evidence-summary")).toContainText(
    /satisfied|violated|indeterminate/,
  );
  await expect(result.getByTestId("evidence-summary")).toContainText(
    /not\s+(an\s+)?authoritative/i,
  );
  await result.getByTestId("raw-evidence-details").locator("summary").click();
  await expect(result.getByTestId("raw-evidence-details")).toContainText(/rule_pack_result/);
  await expect(result.getByTestId("raw-evidence-details")).toContainText(/canonical_fact/);
});

test("ambiguous reference yields multiple candidates and a grounded follow-up reuses prior evidence", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  // Ambiguous: E06 has several nozzles. No mandatory selection form should appear.
  await workflow.sendPrompt("What is connected to the nozzle?");
  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });

  // The answer discloses its object interpretation for several candidates.
  await expect(
    page.getByTestId("qa-interpretation").last().getByTestId("qa-interpretation-chip"),
  ).toHaveCount(3);

  // A vague conversational follow-up must reach grounded QA with the prior
  // evidence identities instead of being rejected by the legacy router.
  await workflow.sendPrompt("What does that mean?");
  await expect(page.getByTestId("grounded-qa-answer")).toHaveCount(2);
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /Continuing with the previously identified/,
  );
});

test("inferred flow direction pauses for review and resumes after the reviewer confirms", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  // A piping-rooted directed question has inferred flow direction -> review card.
  await workflow.sendPrompt("What is downstream of the piping?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });
  await expect(page.getByTestId("direction-basis")).toHaveText("inferred");
  await expect(page.getByTestId("direction-proposed")).toContainText("downstream");
  await expect(page.getByTestId("direction-confirm")).toBeVisible();
  await expect(page.getByTestId("direction-reverse")).toBeVisible();
  await expect(page.getByTestId("direction-unknown")).toBeVisible();

  // Clicking the witness chip highlights the structural witness in the graph.
  const graphPanel = page.getByRole("complementary", { name: "P&ID graph panel" });
  await page.getByTestId("direction-witness-chip").click();
  await expect(graphPanel.locator("rect.highlighted").first()).toBeVisible({
    timeout: 3000,
  });

  // Confirming resumes the original question with a grounded answer.
  await page.getByTestId("direction-confirm").click();
  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /Confirmed downstream flow direction/,
  );
});

test("reversing an inferred flow direction resumes with the opposite direction", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What is downstream of the piping?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });
  await page.getByTestId("direction-reverse").click();

  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /reviewer-reversed flow direction \(upstream\)/,
  );

  // Reuse: asking the same question again must not pause for review.
  await workflow.sendPrompt("What is downstream of the piping?");
  await expect(page.getByTestId("grounded-qa-answer")).toHaveCount(2);
  await expect(page.getByTestId("direction-review-card")).toHaveCount(1);
});

test("temporary Datalog confirmation can be canceled or run from the chat card", async ({
  page,
}) => {
  const confirmationMessage = `pydexpi:datalog-confirmation:${JSON.stringify({
    plainLanguageMeaning: "Return objects matching the temporary topology rule.",
    generatedDatalog: '.decl answer(x:symbol)\n.output answer\nanswer("node-p101").',
    validationStatus: "safe_to_confirm",
    allowedActions: ["run", "cancel"],
    raw: {
      confirmation_kind: "temporary_datalog",
      session_id: "session-1",
      question: "Must every connected object satisfy the temporary topology rule?",
      datalog_confirmation: {
        proposal_result: {
          executed: false,
          proposal: {
            proposal_id: "proposal-1",
            generated_datalog: '.decl answer(x:symbol)\n.output answer\nanswer("node-p101").',
            formal_restatement: "Return objects matching the temporary topology rule.",
          },
          confirmation: { proposal_id: "proposal-1" },
        },
      },
    },
  })}`;
  const logicAnswer = `pydexpi:logic-answer:${JSON.stringify({
    summary: "Return objects matching the temporary topology rule.",
    rawEvidence: { items: [{ id: "node-p101", label: "P-101" }] },
    highlightedNodeIds: ["node-p101"],
    raw: {},
  })}`;
  await page.route("**/api/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: confirmationMessage, highlightedNodeIds: [] }),
    });
  });
  await page.route("**/api/review/sessions/*/temporary-datalog-reviews", async (route) => {
    const body = route.request().postDataJSON() as { decision?: string };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        body.decision === "cancel"
          ? {
              status: "canceled",
              message: "Canceled. No Datalog query was executed.",
              highlightedNodeIds: [],
            }
          : { status: "answered", message: logicAnswer, highlightedNodeIds: ["node-p101"] },
      ),
    });
  });

  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");
  await expect(workflow.confirmationCards).toHaveCount(1);
  await workflow.datalogDetails.locator("summary").click();
  await expect(workflow.datalogDetails).toContainText('answer("node-p101")');

  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("datalog-cancel-note")).toContainText(
    "No Datalog query was executed",
  );

  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");
  await expect(workflow.confirmationCards).toHaveCount(2);
  await workflow.confirmationCards.last().getByRole("button", { name: "Run" }).click();
  await expect(page.getByTestId("evidence-summary")).toContainText(
    "Return objects matching the temporary topology rule.",
  );
});
