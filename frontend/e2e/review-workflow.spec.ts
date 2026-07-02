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

  // Clicking a chip applies highlights in the Cytoscape P&ID graph. The graph
  // renders to a canvas, so highlight state is surfaced via a data attribute.
  const graph = page.getByTestId("cytoscape-pid-graph");
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

  // Clicking the witness chip highlights the structural witness in the Cytoscape
  // P&ID graph (canvas-backed, so highlight state is exposed as a data attribute).
  const graph = page.getByTestId("cytoscape-pid-graph");
  await expect(graph).toBeVisible();
  await page.getByTestId("direction-witness-chip").click();
  await expect(graph).toHaveAttribute("data-highlight-active", "true", { timeout: 3000 });

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

  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("direction-review-card").waitFor({ state: "visible" });
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
        "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack.",
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
  let resumeDecisions: string[] = [];
  await page.route("**/api/review/sessions/*/turns", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(pausedTurn("turn-e2e-1")),
    });
  });
  await page.route("**/api/review/sessions/*/turns/*/datalog-review", async (route) => {
    const body = route.request().postDataJSON() as { decision?: string };
    resumeDecisions.push(body.decision ?? "");
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
  await expect(workflow.confirmationCards).toHaveCount(1);

  // The consent surface: interpretation, scope, assumptions, exact Datalog,
  // and the fixed read-only effect line, plus all four review actions.
  await expect(page.getByTestId("datalog-plain-language")).toContainText(
    "Return objects matching the temporary topology rule.",
  );
  await expect(page.getByTestId("datalog-scope")).toContainText("undirected traversal");
  await expect(page.getByTestId("datalog-assumptions")).toContainText(
    "process-flow piping connectivity",
  );
  await expect(page.getByTestId("datalog-effect")).toHaveText(
    "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack.",
  );
  await expect(page.getByRole("button", { name: "Approve and run" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Revise interpretation" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Revise query" })).toBeEnabled();

  await workflow.datalogDetails.locator("summary").click();
  await expect(workflow.datalogDetails).toContainText('answer("node-p101")');

  // Cancel drives the paused turn to its terminal canceled state via the
  // turn-scoped resume endpoint.
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("datalog-cancel-note")).toContainText(
    "No Datalog query was executed",
  );
  expect(resumeDecisions).toEqual(["cancel"]);

  await workflow.sendPrompt("Must every connected object satisfy the temporary topology rule?");
  await expect(workflow.confirmationCards).toHaveCount(2);
  await workflow.confirmationCards.last().getByRole("button", { name: "Run" }).click();
  await expect(page.getByTestId("qa-answer-text").last()).toContainText(
    "Return objects matching the temporary topology rule.",
  );
  expect(resumeDecisions).toEqual(["cancel", "confirm"]);
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

  // The turn reaches its terminal canceled state and the user can see it.
  await workflow.expectAssistantReply(/The turn was canceled/);
});
