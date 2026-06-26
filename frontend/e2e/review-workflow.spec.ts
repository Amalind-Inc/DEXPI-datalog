import { test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

test("uploads E06 XML and sends a review prompt through the assistant UI", async ({ page }) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.expectGraphNonPrimaryBeforeUpload();

  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What downstream process objects are reachable from the pump?");
  await workflow.expectAssistantReply(/Datalog confirmation ready/);
  await workflow.expectAssistantReply(/Review and run this query explicitly/);
  await workflow.expectLatestAssistantReplyNotToContain(/I am grounding this QA answer/);
});
