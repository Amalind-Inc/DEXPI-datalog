import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createTuiState,
  MAX_FEED_ENTRIES,
  reduceTuiEvent,
  requestTuiCancellation,
  setTuiFollowLive,
  type TuiState,
} from "./portlog-tui-model.ts";
import { renderTui, terminalCellWidth } from "./portlog-tui-renderer.ts";
import {
  buildTuiModelChoices,
  parseTuiCommand,
  parseTuiModelSelection,
  parseTuiModelSpec,
} from "./portlog-tui-model-selector.ts";
import { buildReviewArgs, runTuiCommandPrompt } from "./portlog-tui.ts";
import { parseReviewLine, startReviewProcess } from "./portlog-tui-supervisor.ts";
test("/model is the explicit selector command and unknown slash commands are inert", () => {
  assert.equal(parseTuiCommand("/model"), "model");
  assert.equal(parseTuiCommand(" /model "), "model");
  assert.equal(parseTuiCommand("/other"), "unknown");
  assert.equal(parseTuiCommand("ordinary text"), undefined);
});

test("model selector parses supported provider:model specs and keeps the current choice first", () => {
  const current = { provider: "openrouter", model: "deepseek/deepseek-v4-flash" } as const;
  assert.deepEqual(parseTuiModelSpec("anthropic:claude-sonnet-4-5"), {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
  });
  assert.equal(parseTuiModelSpec("unsupported:model"), undefined);
  assert.equal(parseTuiModelSpec("anthropic:claude-sonnet-4-5\u001b[31m"), undefined);
  const unsupportedCurrent = buildTuiModelChoices(
    { provider: "unsupported", model: "model" },
    "anthropic:claude-sonnet-4-5",
  );
  assert.deepEqual(
    unsupportedCurrent.map(({ provider, model }) => `${provider}:${model}`),
    ["anthropic:claude-sonnet-4-5"],
  );
  const choices = buildTuiModelChoices(
    current,
    "anthropic:claude-sonnet-4-5,openrouter:deepseek/deepseek-v4-flash",
  );
  assert.deepEqual(
    choices.map(({ provider, model }) => `${provider}:${model}`),
    ["openrouter:deepseek/deepseek-v4-flash", "anthropic:claude-sonnet-4-5"],
  );
  assert.deepEqual(parseTuiModelSelection("2", choices), {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
  });
  assert.deepEqual(parseTuiModelSelection("openai-codex:gpt-5.4", choices), {
    provider: "openai-codex",
    model: "gpt-5.4",
  });
  assert.equal(parseTuiModelSelection("0", choices), undefined);
});
test("command prompt restores terminal lifecycle on success, invalid commands, and cancellation", async () => {
  const run = async (
    answer: string,
    questionError = false,
    onModel: () => Promise<void> = async () => {},
  ) => {
    const events: string[] = [];
    const writes: string[] = [];
    const prompt = {
      question: async () => {
        if (questionError) throw new Error("closed");
        return answer;
      },
      close: () => events.push("close"),
    };
    await runTuiCommandPrompt(
      prompt,
      {
        detachKeypress: () => events.push("detach"),
        setRawMode: (enabled) => events.push(`raw:${enabled}`),
        resume: () => events.push("resume"),
        attachKeypress: () => events.push("attach"),
        render: () => events.push("render"),
      },
      (text) => writes.push(text),
      onModel,
    );
    assert.deepEqual(events, [
      "detach",
      "raw:false",
      "close",
      "raw:true",
      "resume",
      "attach",
      "render",
    ]);
    return writes;
  };

  let selected = false;
  await run("/model", false, async () => {
    selected = true;
  });
  assert.equal(selected, true);
  assert.deepEqual(await run("/other"), ["Unknown command. Use /model.\n"]);
  assert.deepEqual(await run("", true), ["Command input was cancelled; no change was made.\n"]);
  assert.deepEqual(
    await run("/model", false, async () => {
      throw new Error("selector failed");
    }),
    ["Command input was cancelled; no change was made.\n"],
  );
});

test("selected provider and model remain explicit in review arguments and TUI identity", () => {
  const args = buildReviewArgs(
    {
      project: "/tmp/e06-review",
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      posture: "inspect",
      help: false,
    },
    "Inspect the source.",
  );
  assert.deepEqual(args.slice(0, 6), [
    "--project",
    "/tmp/e06-review",
    "--provider",
    "anthropic",
    "--model",
    "claude-sonnet-4-5",
  ]);
  const rows = renderTui(
    createTuiState({
      identity: {
        projectDirectory: "/tmp/e06-review",
        provider: "anthropic",
        model: "claude-sonnet-4-5",
      },
      posture: "inspect",
      question: "Inspect the source.",
    }),
    { width: 120, height: 24 },
  );
  assert.ok(rows.some((row) => row.includes("claude-sonnet-4-5")));
});
test("renderer removes terminal controls from initial provider and model identity", () => {
  const rows = renderTui(
    createTuiState({
      identity: {
        projectDirectory: "/tmp/e06-review",
        provider: "anthropic",
        model: "bad\u001b]0;evil\u0007",
      },
      posture: "inspect",
      question: "Inspect the source.",
    }),
    { width: 120, height: 24 },
  );
  const output = rows.join("\n");
  assert.doesNotMatch(output, /\u001b\]0;evil\u0007/);
  assert.doesNotMatch(output, /\u0007/);
});
test("review events become process-engineering phases with explicit PortLog authority", () => {
  let state = createTuiState({
    identity: { projectDirectory: "/tmp/e06-review" },
    posture: "review",
    question: "Review the E06 pump discharge path.",
  });

  state = reduceTuiEvent(state, { type: "turn_started" });
  state = reduceTuiEvent(state, {
    type: "tool_request",
    tool: "portlog_evidence",
    arguments: { artifactId: "topology", claim: "P-101 discharge" },
  });
  state = reduceTuiEvent(state, {
    type: "tool_result",
    tool: "portlog_evidence",
    result: { citations: ["P-101"] },
  });
  state = reduceTuiEvent(state, {
    type: "tool_request",
    tool: "portlog_rule_check",
    arguments: { checkId: "pump_discharge_check_valve", scopeEntityId: "P-101" },
  });

  assert.equal(state.status, "running");
  assert.equal(state.phase, "check");
  assert.equal(state.lanes.find((lane) => lane.id === "check")?.status, "working");
  assert.equal(state.feed[1]?.authority, "portlog");
  assert.equal(state.feed[1]?.phase, "inspect");
  assert.match(state.feed[1]?.summary ?? "", /Evidence review/);
});

test("feed stays bounded and records how much history is hidden", () => {
  let state = createTuiState({ posture: "inspect", question: "Inspect the source." });
  for (let index = 0; index < MAX_FEED_ENTRIES + 7; index += 1) {
    state = reduceTuiEvent(state, {
      type: "tool_result",
      tool: "portlog_workspace_read",
      result: { index },
    });
  }
  assert.equal(state.feed.length, MAX_FEED_ENTRIES);
  assert.equal(state.feedTruncated, 7);
  assert.equal(state.feed[0]?.sequence, 8);
});

test("cancellation is an incomplete outcome until the worker confirms its terminal event", () => {
  let state = createTuiState({ posture: "inspect", question: "Inspect the source." });
  state = reduceTuiEvent(state, { type: "turn_started" });
  state = requestTuiCancellation(state);
  assert.equal(state.status, "cancelling");
  assert.match(state.terminalMessage ?? "", /stopping work/);
  state = reduceTuiEvent(state, { type: "turn_cancelled" });
  assert.equal(state.status, "cancelled");
  assert.match(state.terminalMessage ?? "", /No engineering outcome/);
});
test("startup failure marks the review lane blocked instead of waiting", () => {
  let state = createTuiState({ posture: "inspect", question: "Inspect the source." });
  state = reduceTuiEvent(state, { type: "turn_failed", message: "Project is unavailable." });
  assert.equal(state.status, "failed");
  assert.equal(state.lanes.find((lane) => lane.id === "review")?.status, "blocked");
});

test("renderer keeps every row within terminal width and names deferred controls", () => {
  let state: TuiState = createTuiState({
    posture: "verify",
    question: "Is P-101 discharge protected?",
  });
  state = reduceTuiEvent(state, { type: "turn_started" });
  state = reduceTuiEvent(state, { type: "assistant_text_delta", text: "A bounded answer." });
  const rows = renderTui(state, { width: 80, height: 24 });
  assert.equal(rows.length, 24);
  for (const row of rows) assert.ok(terminalCellWidth(row) <= 80, `wide row: ${stripAnsi(row)}`);
  assert.ok(rows.some((row) => row.includes("background review team")));
  assert.ok(rows.some((row) => row.includes("CURRENT ANSWER")));
  assert.ok(rows.some((row) => row.includes("A bounded answer.")));
});
test("renderer neutralizes terminal controls in question, answer, and event detail", () => {
  const hostile = "\u001b]52;c;clipboard\u0007move\r\n\t\u0007";
  let state: TuiState = createTuiState({
    posture: "inspect",
    question: `What is safe? ${hostile}`,
  });
  state = reduceTuiEvent(state, { type: "turn_started" });
  state = reduceTuiEvent(state, { type: "assistant_text_delta", text: hostile });
  state = reduceTuiEvent(state, {
    type: "tool_result",
    tool: "portlog_evidence",
    result: { detail: hostile },
  });
  state = setTuiFollowLive(state, false);
  state = reduceTuiEvent(state, { type: "turn_failed", message: hostile });

  for (const width of [80, 120]) {
    const rows = renderTui(state, { width, height: 24 });
    assert.equal(rows.length, 24);
    for (const row of rows) {
      const clean = stripAnsi(row);
      assert.ok(terminalCellWidth(row) <= width, `wide row: ${clean}`);
      assert.doesNotMatch(clean, /[\u0000-\u001f\u007f-\u009f]/);
      assert.doesNotMatch(clean, /\u001b/);
    }
  }
});
test("renderer bounds full-width, combining, and emoji text by terminal cells", () => {
  assert.equal(terminalCellWidth("界"), 2);
  assert.equal(terminalCellWidth("e\u0301"), 1);
  assert.equal(terminalCellWidth("👩‍🔬"), 2);
  let state = createTuiState({
    posture: "inspect",
    question: "界界界界界界界界界界 e\u0301 e\u0301 👩‍🔬 👩‍🔬",
  });
  state = reduceTuiEvent(state, { type: "turn_started" });
  state = reduceTuiEvent(state, {
    type: "assistant_text_delta",
    text: "界界界界界界界界界界 e\u0301 e\u0301 👩‍🔬 👩‍🔬",
  });
  for (const width of [80, 120]) {
    const rows = renderTui(state, { width, height: 24 });
    for (const row of rows) {
      assert.ok(terminalCellWidth(row) <= width, `wide row: ${stripAnsi(row)}`);
    }
  }
});
test("supervisor cancellation emits one terminal cancellation event", async () => {
  const events: string[] = [];
  let resolveExit!: (result: { cancelled: boolean }) => void;
  const exited = new Promise<{ cancelled: boolean }>((resolve) => {
    resolveExit = resolve;
  });
  let resolveStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    resolveStarted = resolve;
  });
  const worker = startReviewProcess({
    id: "cancel-fixture",
    args: [],
    cwd: process.cwd(),
    entrypoint: fileURLToPath(new URL("./portlog-tui-test-child.ts", import.meta.url)),
    onEvent: (event) => {
      events.push(event.type);
      if (event.type === "turn_started") resolveStarted();
    },
    onExit: (result) => resolveExit(result),
  });
  await started;
  worker.cancel();
  const result = await exited;
  assert.equal(result.cancelled, true);
  assert.equal(events.filter((event) => event === "turn_cancelled").length, 1);
});

test("disposed supervisor workers cannot report stale failures into a replacement run", async () => {
  const events: string[] = [];
  const outputs: string[] = [];
  let resolveExit!: (result: { cancelled: boolean }) => void;
  const exited = new Promise<{ cancelled: boolean }>((resolve) => {
    resolveExit = resolve;
  });
  let resolveStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    resolveStarted = resolve;
  });
  const worker = startReviewProcess({
    id: "dispose-fixture",
    args: [],
    cwd: process.cwd(),
    entrypoint: fileURLToPath(new URL("./portlog-tui-test-child.ts", import.meta.url)),
    onEvent: (event) => {
      events.push(event.type);
      if (event.type === "turn_started") resolveStarted();
    },
    onOutput: (line) => outputs.push(line),
    onExit: (result) => resolveExit(result),
  });
  await started;
  worker.dispose();
  const result = await exited;
  assert.deepEqual(events, ["turn_started"]);
  assert.equal(
    outputs.some((line) => line.includes("stale-after-dispose")),
    false,
  );
  assert.equal(events.includes("turn_failed"), false);
  assert.equal(events.includes("turn_cancelled"), false);
});

test("review output parser accepts normalized lines and ignores raw noise", () => {
  assert.deepEqual(parseReviewLine("TURN STARTED"), { type: "turn_started" });
  assert.deepEqual(parseReviewLine("ASSISTANT: Evidence is bounded."), {
    type: "assistant_text_delta",
    text: "Evidence is bounded.",
  });
  assert.deepEqual(parseReviewLine('TOOL REQUEST portlog_evidence {"artifactId":"topology"}'), {
    type: "tool_request",
    tool: "portlog_evidence",
    arguments: { artifactId: "topology" },
  });
  assert.equal(parseReviewLine("provider debug noise"), undefined);
});

function stripAnsi(value: string): string {
  return value.replace(/\x1b\[[0-9;]*m/g, "");
}
