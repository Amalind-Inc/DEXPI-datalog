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
  await workflow.expectAssistantReply(/Return deterministic topology evidence/);
  await workflow.expectAssistantReply(/Run/);
  await workflow.expectAssistantReply(/Revise/);
  await workflow.expectAssistantReply(/Cancel/);
  await expect(workflow.datalogDetails).not.toHaveAttribute("open", "");
  await workflow.expectLatestAssistantReplyNotToContain(/I am grounding this QA answer/);
  await workflow.expectLatestAssistantReplyNotToContain(/pydexpi:datalog-confirmation/);
  await workflow.expectViewportHeightStable();
});
