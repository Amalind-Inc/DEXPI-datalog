import { expect, test } from "@playwright/test";
import { c01DexpiFixture, reviewWorkflow } from "./review-workflow";

test("uploads E06 XML and a direct topology question gets a grounded QA answer without Datalog confirmation", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.expectGraphNonPrimaryBeforeUpload();

  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");
  await expect
    .poll(() => page.evaluate(() => window.__PID_LATENCY_TRACE__?.status))
    .toBe("interactive");
  const latencyTrace = await page.evaluate(() => window.__PID_LATENCY_TRACE__);
  expect(latencyTrace?.server?.phases_ms.xml_parse).toBeGreaterThanOrEqual(0);
  expect(latencyTrace?.server?.phases_ms.graph_extraction).toBeGreaterThanOrEqual(0);
  expect(latencyTrace?.phasesMs.layout).toBeGreaterThanOrEqual(0);
  expect(latencyTrace?.counts.renderedEntities).toBeGreaterThan(0);
  expect(latencyTrace?.counts.svgElements).toBeGreaterThan(0);

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

  // Stepped presentation (bead 2ki.11): no pause happened, so there is no
  // validation step -- just retrieval and the final evidence/answer step.
  await expect(page.locator('[data-testid="turn-step"][data-step-id="validation"]')).toHaveCount(
    0,
  );
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

  // E06 carries no drawable geometry, so it fails the sanity gate and
  // degrades to the auto-layout schematic (bead pydexpi-datalog-1-2ki.5).
  // Clicking a chip applies highlights there, surfaced via a data attribute.
  const graph = page.getByTestId("auto-layout-schematic");
  await expect(graph).toBeVisible();
  await chips.first().click();
  await expect(graph).toHaveAttribute("data-highlight-active", "true", { timeout: 3000 });
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
  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });
  await expect(page.getByTestId("direction-basis")).toHaveText("inferred");
  await expect(page.getByTestId("direction-proposed")).toContainText("downstream");
  await expect(page.getByTestId("direction-confirm")).toBeVisible();
  await expect(page.getByTestId("direction-reverse")).toBeVisible();
  await expect(page.getByTestId("direction-unknown")).toBeVisible();

  // Stepped presentation (bead 2ki.11): the review card is the blocking
  // Validation step, nested inside the paused turn's step list.
  await expect(
    page.locator('[data-testid="turn-step"][data-step-id="validation"][data-step-status="blocked"]'),
  ).toBeVisible();

  // Clicking the witness chip highlights the structural witness in the
  // auto-layout schematic (E06 fails the geometry sanity gate).
  const graph = page.getByTestId("auto-layout-schematic");
  await expect(graph).toBeVisible();
  await page.getByTestId("direction-witness-chip").click();
  await expect(graph).toHaveAttribute("data-highlight-active", "true", { timeout: 3000 });

  // Confirming resumes the original question with a grounded answer.
  await page.getByTestId("direction-confirm").click();
  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /Confirmed downstream flow direction/,
  );

  // The resumed message is its own step list: retrieval (resumed) + the
  // final evidence/answer step, no validation step this time -- the
  // decision belonged to the first message.
  const resumedSteps = page
    .getByTestId("grounded-qa-answer")
    .last()
    .locator("xpath=ancestor::*[@data-testid='stepped-turn-card']")
    .getByTestId("turn-step");
  await expect(resumedSteps).toHaveCount(2);
  await expect(resumedSteps.nth(0)).toHaveAttribute("data-step-id", "retrieval");
  await expect(resumedSteps.nth(1)).toHaveAttribute("data-step-id", "evidence-answer");
});

test("a multi-step scripted turn renders as ordered step rows with per-step disclosure (bead 2ki.11)", async ({
  page,
}) => {
  // Mocked paused turn, independent of a real XML upload -- exercises the
  // step-list rendering directly against a controlled review-required event
  // log, matching the pattern used by the Datalog confirmation test below.
  const pausedTurn = {
    turn_id: "turn-e2e-2",
    session_id: "session-e2e-2",
    status: "paused",
    question: "What is downstream of the segment?",
    request_id: "req-e2e-2",
    events: [
      { sequence: 1, type: "tool-progress", data: { status: "started" } },
      {
        sequence: 2,
        type: "review-required",
        data: {
          review: {
            status: "needs_direction_review",
            direction_review: {
              review_key: "review-key-1",
              proposed_direction: "downstream",
              direction_basis: "inferred",
              review_status: "pending",
              basis_explanation: "Flow direction along this witness is inferred.",
              witness: { node_ids: ["node-a"], edge_ids: ["edge-a"] },
              evidence_highlight: { source_scope_ids: [], matched_object_ids: [], paths: [] },
              actions: ["confirm", "reverse", "unknown"],
            },
          },
        },
      },
    ],
  };
  await page.route("**/api/review/sessions/*/turns", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(pausedTurn) });
  });

  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });

  const steps = page.getByTestId("turn-step");
  await expect(steps).toHaveCount(2);
  await expect(steps.nth(0)).toHaveAttribute("data-step-id", "retrieval");
  await expect(steps.nth(0)).toHaveAttribute("data-step-status", "done");
  await expect(steps.nth(1)).toHaveAttribute("data-step-id", "validation");
  await expect(steps.nth(1)).toHaveAttribute("data-step-status", "blocked");
});

test("reversing an inferred flow direction resumes with the opposite direction", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });
  await expect(
    page.locator('[data-testid="turn-step"][data-step-id="validation"][data-step-status="blocked"]'),
  ).toBeVisible();
  await page.getByTestId("direction-reverse").click();

  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /reviewer-reversed flow direction \(upstream\)/,
  );

  // Reuse: asking the same question again must not pause for review.
  await workflow.sendPrompt("What is downstream of the segment?");
  await expect(page.getByTestId("grounded-qa-answer")).toHaveCount(2);
  await expect(page.getByTestId("direction-review-card")).toHaveCount(1);
});

test("temporary Datalog confirmation can be canceled or run from the chat card", async ({
  page,
}) => {
  // Paused turn carrying a datalog confirmation review. The provider derives
  // the turn id client-side, so accept whatever id the POST implies and
  // return a paused TurnState; the card then resumes via the turn-scoped
  // datalog-review endpoint.
  const review = {
    status: "needs_datalog_confirmation",
    question: "Must every connected object satisfy the temporary topology rule?",
    session_id: "session-e2e",
    datalog_confirmation: {
      plain_language_meaning: "Return objects matching the temporary topology rule.",
      interpretation: "Return objects matching the temporary topology rule.",
      scope: {
        starting_object_ids: ["node-p101"],
        graph: "session-e2e",
        direction: "undirected traversal (structural connectivity, not flow direction)",
        direction_basis: "structural adjacency; explicit flow direction is not applied",
        path_treatment: "breadth-first reachability up to 6 hops",
      },
      assumptions: {
        included_edge_types: ["process-flow piping connectivity"],
        excluded_edge_types: ["instrument signal references"],
      },
      effect:
        "Read-only analysis. Does not modify the source document, graph, annotations, or rule pack.",
      generated_datalog: '.decl answer(x:symbol)\n.output answer\nanswer("node-p101").',
      exact_datalog: '.decl answer(x:symbol)\n.output answer\nanswer("node-p101").',
      validation: { status: "safe_to_confirm" },
      allowed_actions: ["run", "revise_interpretation", "revise_query", "cancel"],
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
  };
  const pausedTurn = (turnId: string) => ({
    turn_id: turnId,
    session_id: "session-e2e",
    status: "paused",
    question: review.question,
    request_id: "req-e2e",
    events: [
      { sequence: 1, type: "tool-progress", data: { status: "started" } },
      { sequence: 2, type: "review-required", data: { review } },
    ],
  });
  let resumeBodies: Array<{ decision?: string; proposal_result?: unknown }> = [];
  await page.route("**/api/review/sessions/*/turns", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(pausedTurn("turn-e2e-1")),
    });
  });
  await page.route("**/api/review/sessions/*/turns/*/datalog-review", async (route) => {
    const body = route.request().postDataJSON() as {
      decision?: string;
      proposal_result?: unknown;
    };
    resumeBodies.push(body);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        body.decision === "cancel"
          ? {
              turn_id: "turn-e2e-1",
              session_id: "session-e2e",
              status: "canceled",
              question: review.question,
              request_id: "req-e2e",
              events: [
                { sequence: 1, type: "tool-progress", data: { status: "started" } },
                { sequence: 2, type: "review-required", data: { review } },
                { sequence: 3, type: "cancellation", data: { message: "Canceled by reviewer." } },
              ],
            }
          : {
              turn_id: "turn-e2e-1",
              session_id: "session-e2e",
              status: "completed",
              question: review.question,
              request_id: "req-e2e",
              events: [
                { sequence: 1, type: "tool-progress", data: { status: "started" } },
                {
                  sequence: 2,
                  type: "text",
                  data: { text: "Return objects matching the temporary topology rule." },
                },
                {
                  sequence: 3,
                  type: "evidence",
                  data: {
                    evidence_references: ["node-p101"],
                    evidence_highlight: {
                      source_scope_ids: [],
                      matched_object_ids: ["node-p101"],
                      paths: [],
                    },
                  },
                },
                { sequence: 4, type: "completion", data: { status: "completed" } },
              ],
              result: {
                answer_text: "Return objects matching the temporary topology rule.",
                evidence_references: ["node-p101"],
                conversation_state: [],
              },
            },
      ),
    });
  });

  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");
  const widgets = page.getByTestId("datalog-confirmation-widget");
  await expect(widgets).toHaveCount(1);
  await expect(workflow.confirmationCards).toHaveCount(0);

  // Stepped presentation (bead 2ki.11): the confirmation widget is the
  // blocking Validation step.
  await expect(
    page.locator('[data-testid="turn-step"][data-step-id="validation"][data-step-status="blocked"]'),
  ).toBeVisible();

  // The inline consent surface leads with the plain-language restatement and
  // scope, keeps exact Datalog collapsed but inspectable, and exposes all four
  // numbered keyboard-selectable actions.
  const widget = widgets.first();
  await expect(widget.getByTestId("datalog-plain-language")).toContainText(
    "Return objects matching the temporary topology rule.",
  );
  await expect(widget.getByTestId("datalog-scope")).toContainText("undirected traversal");
  await expect(widget.getByTestId("datalog-assumptions")).toContainText(
    "process-flow piping connectivity",
  );
  await expect(widget.getByTestId("datalog-effect")).toHaveText(
    "Read-only analysis. Does not modify the source document, graph, annotations, or rule pack.",
  );
  await expect(widget.getByTestId("datalog-widget-option-run")).toContainText("1.");
  await expect(widget.getByTestId("datalog-widget-option-run")).toContainText("Run");
  await expect(widget.getByTestId("datalog-widget-option-revise-interpretation")).toContainText(
    "2.",
  );
  await expect(widget.getByTestId("datalog-widget-option-revise-query")).toContainText("3.");
  await expect(widget.getByTestId("datalog-widget-option-cancel")).toContainText("4.");

  const exactQuery = widget.getByTestId("datalog-exact-query");
  await expect(exactQuery.locator("summary")).toHaveText("Exact Datalog");
  await expect(exactQuery).not.toHaveAttribute("open", "");
  await exactQuery.locator("summary").click();
  await expect(exactQuery).toHaveAttribute("open", "");
  await expect(exactQuery).toContainText('answer("node-p101")');

  // Keyboard cancel: focus the widget, move the visible selection to option 4,
  // and activate it with Enter. The paused turn resumes through the turn-scoped
  // endpoint with the exact proposal_result payload.
  await widget.focus();
  await widget.press("ArrowDown");
  await widget.press("ArrowDown");
  await widget.press("ArrowDown");
  await expect(widget.getByTestId("datalog-widget-option-cancel")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await widget.press("Enter");
  await expect(widget.getByTestId("datalog-widget-decided")).toContainText(/cancel/i);
  expect(resumeBodies.map((body) => body.decision)).toEqual(["cancel"]);
  expect(resumeBodies[0]?.proposal_result).toEqual(review.datalog_confirmation.proposal_result);

  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");
  await expect(widgets).toHaveCount(2);
  await expect(workflow.confirmationCards).toHaveCount(0);
  const runWidget = widgets.last();
  await runWidget.focus();
  await runWidget.press("1");
  await expect(runWidget.getByTestId("datalog-widget-option-run")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await runWidget.press("Enter");
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    "Return objects matching the temporary topology rule.",
  );
  await expect(runWidget.getByTestId("datalog-widget-decided")).toContainText(/run/i);
  expect(resumeBodies.map((body) => body.decision)).toEqual(["cancel", "confirm"]);
  expect(resumeBodies[1]?.proposal_result).toEqual(review.datalog_confirmation.proposal_result);

  // The resumed answer's own final step is done -- no fabricated data, just
  // the real terminal state of the completed turn.
  const finalStep = page
    .getByTestId("qa-answer-text")
    .last()
    .locator("xpath=ancestor::*[@data-testid='turn-step'][1]");
  await expect(finalStep).toHaveAttribute("data-step-status", "done");
});

test("paused direction review survives a page refresh and resumes from persisted state", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  // Pause the turn on a direction review.
  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });

  // Refresh: session id, thread history, and the paused turn are persisted.
  await page.reload();
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });

  // Resuming after the refresh routes through the turn-scoped endpoint and
  // completes the original question.
  await page.getByTestId("direction-confirm").click();
  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    /Confirmed downstream flow direction/,
  );
});

test("duplicate turn requests with the same request id do not re-execute the turn", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml();
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  // Ask once through the UI so the session has a prepared topology and the
  // turn transport is exercised end to end.
  await workflow.sendPrompt("What downstream process objects are reachable from the pump?");
  await page.getByTestId("grounded-qa-answer").waitFor({ state: "visible" });

  // Re-POST the same request id twice straight from the browser: the backend
  // must replay the persisted turn, not run a second execution.
  const [first, second] = await page.evaluate(async () => {
    const sessionId = window.localStorage.getItem("pydexpi.pidQa.sessionId.v1");
    const post = async () => {
      const response = await fetch(`/api/review/sessions/${sessionId}/turns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: "What downstream process objects are reachable from the pump?",
          request_id: "duplicate-request-e2e",
        }),
      });
      return response.json();
    };
    const a = await post();
    const b = await post();
    return [a, b];
  });

  expect(first.turn_id).toBe(second.turn_id);
  expect(first.status).toBe("completed");
  // Identical event log — the duplicate replayed, nothing re-executed.
  expect(second.events).toEqual(first.events);
});

test("canceling an active turn from the chat composer reaches a terminal canceled state", async ({
  page,
}) => {
  // The real backend executes turns synchronously and too fast to catch
  // mid-flight, so mock an active turn lifecycle: hold the start POST until
  // the cancel endpoint is hit, then resolve both with the canceled state.
  const canceledTurn = {
    turn_id: "turn-cancel-e2e",
    session_id: "session-cancel-e2e",
    status: "canceled",
    question: "A long-running question",
    request_id: "req-cancel-e2e",
    events: [
      { sequence: 1, type: "tool-progress", data: { status: "started" } },
      { sequence: 2, type: "cancellation", data: { message: "Canceled by user." } },
    ],
  };
  const { promise: cancelArrived, resolve: cancelRequested } = Promise.withResolvers<void>();
  await page.route("**/api/review/sessions/*/turns", async (route) => {
    // Keep the turn "active" until the user cancels.
    await cancelArrived;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(canceledTurn),
    });
  });
  await page.route("**/api/review/sessions/*/turns/*/cancel", async (route) => {
    cancelRequested();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(canceledTurn),
    });
  });

  const workflow = reviewWorkflow(page);
  await workflow.open();
  await workflow.sendPrompt("A long-running question");

  // The composer switches to a stop control while the turn is running.
  await page.getByRole("button", { name: "Stop generating" }).click();

  // Bead 2ki.12: run() now streams via an AsyncGenerator so steps can tick
  // live. assistant-ui's own runtime marks a message "incomplete/cancelled"
  // the instant it observes abortSignal.aborted, discarding whatever content
  // that final yield carried -- so the terminal state is no longer a custom
  // "The turn was canceled." text, it is the composer returning to its idle
  // (non-running) state with the step trail exactly as it last stood, not
  // replaced by an error or stuck spinner.
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
  await expect(page.locator('[data-role="assistant"]').last()).not.toContainText(/error/i);
});

test("a turn's step list ticks live against the real scripted backend before the final answer lands (bead 2ki.12)", async ({
  page,
}) => {
  // Exercises real timing (not a route mock): the scripted backend sleeps
  // HARBORFIELD_QA_SCRIPTED_STEP_DELAY_MS between each of its multi-round tool
  // calls (playwright.config.ts) specifically so this window is observable.
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  await workflow.sendPrompt("What is downstream of the segment?");

  // The in-progress placeholder ticks in before the turn resolves.
  await expect(
    page.locator('[data-testid="turn-step"][data-step-status="pending"]'),
  ).toBeVisible();

  // ...and the real answer eventually replaces it.
  await page.getByTestId("grounded-qa-answer").last().waitFor({ state: "visible" });
  await expect(
    page.locator('[data-testid="turn-step"][data-step-status="pending"]'),
  ).toHaveCount(0);
});

test("canceling mid-stream against the real scripted backend leaves the step trail intact (bead 2ki.12)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  await workflow.sendPrompt("What is downstream of the segment?");

  // Cancel while the in-progress placeholder is showing -- not after it has
  // already resolved to a real answer.
  await page
    .locator('[data-testid="turn-step"][data-step-status="pending"]')
    .waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Stop generating" }).click();

  // The composer returns to idle and the last-rendered step trail is left
  // exactly as it stood -- no error, no further step ticks, no stale spinner.
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
  await expect(page.locator('[data-role="assistant"]').last()).not.toContainText(/error/i);
  const pendingStepCountAfterCancel = await page
    .locator('[data-testid="turn-step"][data-step-status="pending"]')
    .count();
  await page.waitForTimeout(500);
  await expect(page.locator('[data-testid="turn-step"][data-step-status="pending"]')).toHaveCount(
    pendingStepCountAfterCancel,
  );
});
