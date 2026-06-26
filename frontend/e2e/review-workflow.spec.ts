import { expect, test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

test("uploads E06 XML and sends a review prompt through the assistant UI", async ({ page }) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.expectGraphNonPrimaryBeforeUpload();

  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What downstream process objects are reachable from the pump?");
  await workflow.confirmationCards.last().waitFor({ state: "visible" });
  await workflow.expectAssistantReply(/Review before execution/);
  await workflow.expectAssistantReply(
    /Review a generated Datalog query|Return deterministic topology evidence/,
  );
  await workflow.expectAssistantReply(/Run/);
  await workflow.expectAssistantReply(/Revise/);
  await workflow.expectAssistantReply(/Cancel/);
  await expect(workflow.datalogDetails).not.toHaveAttribute("open", "");
  await workflow.expectLatestAssistantReplyNotToContain(/I am grounding this QA answer/);
  await workflow.expectLatestAssistantReplyNotToContain(/pydexpi:datalog-confirmation/);
  await workflow.expectViewportHeightStable();

  await workflow.confirmationCards.last().getByRole("button", { name: "Run" }).click();
  await page.getByTestId("grounded-logic-answer").waitFor({ state: "visible" });
  await expect(page.getByTestId("evidence-summary")).toContainText(
    /Deterministic execution produced/,
  );
  await expect(page.getByTestId("raw-evidence-details")).toBeVisible();
});

test("canceling a Datalog confirmation does not execute the query", async ({ page }) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");
  await workflow.sendPrompt("What downstream process objects are reachable from the pump?");
  await workflow.confirmationCards.last().waitFor({ state: "visible" });

  await workflow.confirmationCards.last().getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByTestId("datalog-cancel-note")).toContainText(
    "No Datalog query was executed",
  );
  await expect(page.getByTestId("grounded-logic-answer")).toHaveCount(0);
});
