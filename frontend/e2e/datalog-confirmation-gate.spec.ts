import { expect, test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

// Bead 37x.22.34.2 acceptance: a REAL question typed into the running web
// app's chat pauses the REAL backend turn with needs_datalog_confirmation,
// the inline confirmation widget renders, "Run" is selected via keyboard,
// and an executed result renders. No route mocking: this exercises the real
// browser against a real backend turn (scripted OSS default provider).
//
// Bead 37x.22.34.4/.6 acceptance: the confirmed query now ACTUALLY EXECUTES
// on a real Souffle engine. The OSS default provider deliberately generates a
// generic-schema join (`direct_process_connection`) that the retired two-shape
// regex executor could not evaluate -- it would have silently produced zero
// evidence. Real evidence chips rendering after keyboard-Run therefore prove
// genuine engine execution, not text pattern matching.
test("chat rule question pauses for keyboard-confirmed Datalog execution", async ({ page }) => {
  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");

  // The turn pauses: the purpose-built confirmation widget renders inline in
  // the chat thread with restatement + scope first, Datalog collapsed.
  const widget = page.getByTestId("datalog-confirmation-widget");
  await expect(widget).toBeVisible({ timeout: 30_000 });
  await expect(widget).toContainText(/direct process-connection target/i);
  await expect(page.getByTestId("datalog-exact-query")).toBeVisible();
  // Generated Datalog is collapsed by default but inspectable.
  await expect(page.getByTestId("datalog-exact-query").locator("summary")).toBeVisible();

  // Numbered, keyboard-navigable choices. Select "Run" via keyboard only.
  await expect(widget.getByTestId("datalog-widget-option-run")).toContainText(/1/);
  await widget.press("1");
  await widget.press("Enter");

  // Selecting Run resumes the turn via TurnLifecycleStore.resume() and the
  // EXECUTED answer renders as a grounded QA answer card with evidence
  // chips -- asserting on the answer card (not widget prose) proves the
  // /datalog-review resume actually executed the query.
  await expect(page.getByTestId("datalog-widget-decided")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("qa-answer-text").last()).toBeVisible({
    timeout: 30_000,
  });
  // Correctness of the executed answer (37x.22.34.4/.6): the confirmed query
  // returns direct process-connection targets from the generic schema. A
  // silent-empty executor renders zero chips; real execution of this E06
  // fixture must ground the answer in at least one object, and the answer text
  // must be the confirmed restatement, not model prose.
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /direct process-connection target/i,
  );
  const chips = page.getByTestId("qa-evidence-chip");
  await expect(chips.first()).toBeVisible();
  expect(await chips.count()).toBeGreaterThan(0);
});

test("cancel via keyboard produces the non-executing outcome", async ({ page }) => {
  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");

  const widget = page.getByTestId("datalog-confirmation-widget");
  await expect(widget).toBeVisible({ timeout: 30_000 });

  // ArrowDown three times from Run -> Revise interpretation -> Revise query
  // -> Cancel, then Enter.
  await widget.press("ArrowDown");
  await widget.press("ArrowDown");
  await widget.press("ArrowDown");
  await widget.press("Enter");

  await expect(page.getByTestId("datalog-widget-decided")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("datalog-widget-decided")).toContainText(/cancel/i);
});
