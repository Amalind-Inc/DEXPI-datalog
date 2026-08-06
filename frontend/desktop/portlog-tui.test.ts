import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { Editor } from "./vendor/oh-my-pi-tui/components/editor.ts";
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
import {
  PORTLOG_EDITOR_THEME,
  buildReviewArgs,
  createTuiChatPrompt,
  parseTuiOptions,
  renderTuiWelcome,
  runTuiChatSession,
  runTuiChatTurn,
  runTuiCommandPrompt,
  runTuiRequiredModelSelection,
  runTuiStartupPrompt,
} from "./portlog-tui.ts";
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
test("CLI parsing opens the unified chat shell without a mode or model picker", () => {
  const defaults = parseTuiOptions(["--project", "/tmp/e06-review"]);
  assert.equal(defaults.mode, "chat");
  assert.equal(defaults.selectModelOnStart, false);
  assert.equal(
    parseTuiOptions(["--project", "/tmp/e06-review", "--mode", "review"]).mode,
    "review",
  );
  assert.equal(
    parseTuiOptions(["--project", "/tmp/e06-review", "--provider", "anthropic"]).selectModelOnStart,
    false,
  );
});
test("welcome shell leaves workspace identity for the prompt border", () => {
  const welcome = renderTuiWelcome({
    projectDirectory: "/tmp/e06-review",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
  });
  assert.match(welcome, /PORTLOG CHAT/);
  assert.match(welcome, /Tips/);
  assert.doesNotMatch(welcome, /\/tmp\/e06-review|MODEL/u);
});
test("archived chat messages are plain on a background, without box or identity", async () => {
  const output: string[] = [];
  await runTuiChatSession({
    prompt: {
      question: async () => "/quit",
      close: () => {},
    },
    initialQuestion: "Explain the source.",
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    getIdentity: () => ({
      projectDirectory: "/tmp/e06-review",
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
    }),
    runTurn: async (_question, onEvent) => {
      onEvent({ type: "tool_request", tool: "portlog_evidence", arguments: {} });
      onEvent({ type: "assistant_text_delta", text: "Hello\nworld" });
      return { status: "completed" };
    },
    write: (text) => output.push(text),
  });

  const transcript = stripAnsi(output.join(""));
  assert.match(transcript, /You: Explain the source\./);
  assert.doesNotMatch(transcript, /\[PORTLOG\]|MODEL |┌─ \[|│ You:|e06-review/);
  assert.match(output.join(""), /\u001b\[48;5;236m\u001b\[38;5;250m You: Explain the source\. /);
  assert.match(transcript, /\[PortLog tool: portlog_evidence\]\nAssistant\nHello\nworld/);
  assert.match(output.join(""), /\u001b\[90mAssistant/);
});
test("interactive chat prompt puts identity in the editor label", async () => {
  const answers = ["typed question", "/quit"];
  const prompts: Array<{
    message: string;
    options?: { multiline?: boolean; editorLabel?: string };
  }> = [];
  const output: string[] = [];
  await runTuiChatSession({
    prompt: {
      question: async (message, options) => {
        prompts.push({ message, options });
        return answers.shift() ?? "/quit";
      },
      close: () => {},
    },
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    getIdentity: () => ({
      projectDirectory: "/tmp/e06-review",
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
    }),
    runTurn: async (_question, onEvent) => {
      onEvent({ type: "assistant_text_delta", text: "Done." });
      return { status: "completed" };
    },
    write: (text) => output.push(text),
  });

  assert.deepEqual(prompts[0], {
    message: "",
    options: {
      multiline: true,
      editorLabel: "You · /tmp/e06-review · openrouter/deepseek/deepseek-v4-flash",
    },
  });
  assert.match(stripAnsi(output.join("")), /Assistant\nDone\./u);
});
function createRawPromptFixture(columns = 80) {
  const listeners = new Set<(chunk: string | Buffer) => void>();
  const rawModes: boolean[] = [];
  let pauseCount = 0;
  let resumeCount = 0;
  const output: string[] = [];
  const input = {
    on: (_event: "data", listener: (chunk: string | Buffer) => void) => {
      listeners.add(listener);
      return input;
    },
    off: (_event: "data", listener: (chunk: string | Buffer) => void) => {
      listeners.delete(listener);
      return input;
    },
    pause: () => {
      pauseCount += 1;
    },
    resume: () => {
      resumeCount += 1;
    },
    setRawMode: (enabled: boolean) => rawModes.push(enabled),
  };
  return {
    prompt: createTuiChatPrompt(input, {
      columns,
      write: (text) => {
        output.push(text);
        return true;
      },
    }),
    output,
    rawModes,
    listeners,
    emit: (chunk: string | Buffer) => {
      for (const listener of listeners) listener(chunk);
    },
    get pauseCount() {
      return pauseCount;
    },
    get resumeCount() {
      return resumeCount;
    },
  };
}
test("chat prompt combines identity with You and truncates the label to fit", async () => {
  const fixture = createRawPromptFixture(32);
  const question = fixture.prompt.question("", {
    multiline: true,
    editorLabel:
      "You · ~/pydexpi-datalog-1/.tmp/portlog-user-data/current-project · openrouter/deepseek-v4-flash",
  });
  fixture.emit("\r");

  const raw = fixture.output.join("");
  const transcript = stripAnsi(raw);
  assert.equal(await question, "");
  assert.match(transcript, /┌─ You · .*$/mu);
  assert.match(transcript, /└─+/u);
  assert.doesNotMatch(transcript, /[╭╮╰╯]/u);
  assert.doesNotMatch(transcript, /│[^\n]*│/u);
  assert.doesNotMatch(raw, /\u001b_pi:c\u0007/u);
});

test("chat prompt keeps the left rule and leaves the right side open", async () => {
  const fixture = createRawPromptFixture(24);
  const question = fixture.prompt.question("", {
    multiline: true,
    editorLabel: "You",
  });
  fixture.emit("abc");
  fixture.emit("\u001b[13;2u");
  fixture.emit("def");

  const transcript = stripAnsi(fixture.output.join(""));
  assert.match(transcript, /┌─ You .*$/mu);
  assert.match(transcript, /│ abc[^\n]*$/mu);
  assert.match(transcript, /└─def[^\n]*$/mu);
  assert.match(transcript, /└─+/u);
  assert.doesNotMatch(transcript, /│[^\n]*│/u);

  fixture.emit("\r");
  assert.equal(await question, "abc\ndef");
});

test("PortLog open-right borders suppress scrollbar enclosure glyphs", () => {
  const editor = new Editor(PORTLOG_EDITOR_THEME);
  editor.focused = true;
  editor.setUseTerminalCursor(true);
  editor.setMaxHeight(4);
  editor.setScrollbarVisible(true);
  editor.setText("one\ntwo\nthree\nfour\nfive");

  const transcript = stripAnsi(editor.render(24).join("\n"));
  assert.match(transcript, /┌/u);
  assert.match(transcript, /│/u);
  assert.match(transcript, /└/u);
  assert.doesNotMatch(transcript, /[╭╮╰╯]/u);
  assert.doesNotMatch(transcript, /█/u);
  assert.doesNotMatch(transcript, /│[^\n]*│/u);
  const bottom = transcript.split("\n").find((line) => line.trimStart().startsWith("└"));
  assert.ok(bottom);
  assert.notEqual(bottom!.trimEnd().at(-1), "─");
});
test("open-right prompt leaves no stray dash at the bottom-right corner", async () => {
  const fixture = createRawPromptFixture(24);
  const question = fixture.prompt.question("", { multiline: true, editorLabel: "You" });
  fixture.emit("probe");

  // The prompt redraws in place with cursor-movement escapes, so consecutive frames
  // are glued onto the same text line. Normalize the control sequences, then inspect
  // the final live bottom rule (nothing is glued after it).
  const normalized = stripAnsi(fixture.output.join(""))
    .replace(/\u001b\[[0-9;?]*[A-Za-z]/g, "")
    .replace(/[\r\u0007]/g, "");
  const bottom = normalized
    .split("\n")
    .filter((line) => line.trimStart().startsWith("└"))
    .at(-1);
  assert.ok(bottom);
  assert.notEqual(bottom!.trimEnd().at(-1), "─");

  fixture.emit("\r");
  assert.equal(await question, "probe");
});
test("chat prompt delegates the insertion cursor to the terminal", async () => {
  const fixture = createRawPromptFixture();
  const question = fixture.prompt.question("", { multiline: true });

  const initial = fixture.output.join("");
  assert.match(initial, /\u001b\[3G\u001b\[\?25h/u);

  fixture.emit("abc");
  const beforeNavigation = fixture.output.length;
  fixture.emit("\u001b[D");
  const navigationOutput = fixture.output.slice(beforeNavigation).join("");
  assert.equal(navigationOutput.match(/\u001b\[\d+G\u001b\[\?25h/u)?.[0], "\u001b[5G\u001b[?25h");

  fixture.emit("\r");
  assert.equal(await question, "abc");
});

test("terminal cursor follows the insertion point across multiline editor rows", async () => {
  const fixture = createRawPromptFixture(80);
  const question = fixture.prompt.question("", { multiline: true });
  fixture.emit("abc");
  fixture.emit("\u001b[13;2u");
  fixture.emit("def");
  const beforeNavigation = fixture.output.length;
  fixture.emit("\u001b[A");
  const position = fixture.output.slice(beforeNavigation).join("");

  assert.equal(
    position.match(/\u001b\[1A\u001b\[6G\u001b\[\?25h/u)?.[0],
    "\u001b[1A\u001b[6G\u001b[?25h",
  );

  fixture.emit("\r");
  assert.equal(await question, "abc\ndef");
  assert.match(
    fixture.output.join(""),
    /\u001b\[48;5;236m\u001b\[38;5;250m You: abc \u001b\[0m\n\u001b\[48;5;236m\u001b\[38;5;250m     def \u001b\[0m\u001b\[\?25l$/u,
  );
});
test("terminal cursor tracks a soft-wrapped editor row", async () => {
  const fixture = createRawPromptFixture(16);
  const question = fixture.prompt.question("", { multiline: true });
  fixture.emit("abcdefghijklmnop");
  const beforeNavigation = fixture.output.length;
  fixture.emit("\u001b[A");

  const position = fixture.output.slice(beforeNavigation).join("");
  assert.match(position, /\u001b\[1A\u001b\[\d+G\u001b\[\?25h/u);

  fixture.emit("\r");
  assert.equal(await question, "abcdefghijklmnop");
});
test("backspace after a multiline newline redraws without cursor artifacts", async () => {
  const fixture = createRawPromptFixture(24);
  const question = fixture.prompt.question("", { multiline: true });
  fixture.emit("hello");
  fixture.emit("\u001b[13;2u");
  fixture.emit("\x7f");
  fixture.emit("\r");

  assert.equal(await question, "hello");
  const raw = fixture.output.join("");
  assert.doesNotMatch(raw, /\u001b_pi:c\u0007/u);
  assert.doesNotMatch(raw, /\ufffd/u);
});

test("raw split shift+enter reassembles before reaching the upstream editor", async () => {
  const fixture = createRawPromptFixture(24);
  const question = fixture.prompt.question("header", { multiline: true });
  fixture.emit("hello");
  fixture.emit("\u001b[13;2");
  fixture.emit("u");
  fixture.emit("world");
  fixture.emit("\r");

  assert.equal(await question, "hello\nworld");
  const transcript = stripAnsi(fixture.output.join(""));
  assert.match(transcript, /┌.*You/u);
  assert.match(transcript, /└/u);
  assert.match(transcript, /hello/u);
  assert.match(transcript, /world/u);
  assert.doesNotMatch(transcript, /13~|\[13;2u/u);
  assert.deepEqual(fixture.rawModes, [true, false]);
  assert.equal(fixture.listeners.size, 0);
});

test("raw ctrl+enter and plain enter submit without escape suffixes", async () => {
  const ctrl = createRawPromptFixture();
  const ctrlQuestion = ctrl.prompt.question("header", { multiline: true });
  ctrl.emit("ctrl submit");
  ctrl.emit("\u001b[13;5u");
  assert.equal(await ctrlQuestion, "ctrl submit");

  const plain = createRawPromptFixture();
  const plainQuestion = plain.prompt.question("header", { multiline: true });
  plain.emit("plain submit");
  plain.emit("\r");
  assert.equal(await plainQuestion, "plain submit");
  assert.doesNotMatch(stripAnsi(ctrl.output.join("") + plain.output.join("")), /13~|\[13;5u/u);
});

test("upstream editor surface wraps and preserves cursor-aware backspace edits", async () => {
  const fixture = createRawPromptFixture(16);
  const question = fixture.prompt.question("header", { multiline: true });
  fixture.emit("abcdefghijk");
  fixture.emit("\x7f");
  fixture.emit("Z");
  fixture.emit("\r");

  assert.equal(await question, "abcdefghijZ");
  const transcript = stripAnsi(fixture.output.join(""));
  assert.match(transcript, /┌/u);
  assert.match(transcript, /└/u);
  assert.match(transcript, /abcdef/u);
  assert.match(transcript, /ghijZ/u);
  assert.doesNotMatch(fixture.output.join(""), /▏/u);
  assert.match(fixture.output.join(""), /\u001b\[\d+G\u001b\[\?25h/u);
});

test("raw prompt input cleans up on ctrl+c cancellation and close", async () => {
  const cancelled = createRawPromptFixture();
  let interrupted = false;
  cancelled.prompt.onInterrupt(() => {
    interrupted = true;
  });
  const cancelledQuestion = cancelled.prompt.question("header", { multiline: true });
  cancelled.emit("\u0003");
  await assert.rejects(cancelledQuestion, /Input cancelled/);
  assert.equal(interrupted, true);
  assert.equal(cancelled.listeners.size, 0);
  assert.deepEqual(cancelled.rawModes, [true, false]);
  assert.equal(cancelled.resumeCount, 1);
  assert.equal(cancelled.pauseCount, 1);

  const closed = createRawPromptFixture();
  const closedQuestion = closed.prompt.question("header", { multiline: true });
  closed.prompt.close();
  await assert.rejects(closedQuestion, /Prompt closed/);
  assert.equal(closed.listeners.size, 0);
  assert.equal(closed.rawModes.at(-1), false);
  assert.equal(closed.resumeCount, 1);
  assert.equal(closed.pauseCount, 1);
});
test("inline chat keeps assistant failures outside the input box", async () => {
  const output: string[] = [];
  await runTuiChatSession({
    prompt: {
      question: async () => "/quit",
      close: () => {},
    },
    initialQuestion: "Explain the source.",
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    getIdentity: () => ({
      projectDirectory: "/tmp/e06-review",
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
    }),
    runTurn: async () => ({ status: "failed", message: "provider unavailable" }),
    write: (text) => output.push(text),
  });

  const transcript = stripAnsi(output.join(""));
  assert.match(transcript, /Assistant\nAssistant unavailable: provider unavailable\n/);
  assert.doesNotMatch(transcript, /│ Assistant/);
  assert.match(output.join(""), /\u001b\[90mAssistant/);
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
  assert.equal(args[args.indexOf("--mode") + 1], "chat");
  assert.deepEqual(args.slice(0, 8), [
    "--project",
    "/tmp/e06-review",
    "--mode",
    "chat",
    "--provider",
    "anthropic",
    "--model",
    "claude-sonnet-4-5",
  ]);
  assert.equal(args.at(-2), "--turn-id");
  assert.match(args.at(-1) ?? "", /^tui-/);
  const nextArgs = buildReviewArgs(
    {
      project: "/tmp/e06-review",
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      posture: "inspect",
      help: false,
    },
    "Inspect the source.",
  );
  assert.notEqual(args.at(-1), nextArgs.at(-1));
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
test("chat turns use the project-backed supervisor boundary with fresh turn identities", async () => {
  const options = {
    project: "/tmp/e06-review",
    provider: "openrouter",
    model: "deepseek/deepseek-v4-flash",
    posture: "inspect" as const,
    help: false,
  };
  const started: Array<{ id: string; args: string[] }> = [];
  let processCount = 0;
  let disposedProcesses = 0;
  const startProcess = (processOptions: Parameters<typeof startReviewProcess>[0]) => {
    processCount += 1;
    started.push({ id: processOptions.id, args: [...processOptions.args] });
    queueMicrotask(() => {
      if (processCount === 3) {
        processOptions.onExit({ code: 1, signal: null, cancelled: false });
      } else if (processCount === 4) {
        processOptions.onEvent({ type: "turn_cancelled" });
      } else if (processCount === 5) {
        processOptions.onEvent({ type: "turn_failed", message: "terminal failure" });
      } else {
        processOptions.onEvent({ type: "turn_completed" });
      }
    });
    return {
      id: processOptions.id,
      cancel: () => {},
      dispose: () => {
        disposedProcesses += 1;
      },
    };
  };
  const firstEvents: string[] = [];
  const first = await runTuiChatTurn(
    options,
    "first question",
    (event) => firstEvents.push(event.type),
    startProcess,
  );
  options.provider = "anthropic";
  options.model = "claude-sonnet-4-5";
  const second = await runTuiChatTurn(options, "second question", () => {}, startProcess);
  const failed = await runTuiChatTurn(options, "third question", () => {}, startProcess);
  const cancelled = await runTuiChatTurn(options, "cancelled question", () => {}, startProcess);
  const terminalFailed = await runTuiChatTurn(options, "terminal failure", () => {}, startProcess);

  assert.deepEqual(first, { status: "completed" });
  assert.deepEqual(second, { status: "completed" });
  assert.equal(failed.status, "failed");
  assert.deepEqual(cancelled, { status: "cancelled" });
  assert.deepEqual(terminalFailed, { status: "failed", message: "terminal failure" });
  assert.deepEqual(firstEvents, ["turn_completed"]);
  assert.equal(started.length, 5);
  assert.equal(disposedProcesses, 5);
  assert.match(started[0].id, /^chat-/);
  assert.match(started[1].id, /^chat-/);
  assert.notEqual(started[0].id, started[1].id);
  assert.equal(started[0].args[1], "/tmp/e06-review");
  assert.equal(started[1].args[1], "/tmp/e06-review");
  assert.equal(
    started[0].args[started[0].args.indexOf("--model") + 1],
    "deepseek/deepseek-v4-flash",
  );
  assert.equal(started[1].args[started[1].args.indexOf("--model") + 1], "claude-sonnet-4-5");
  assert.equal(started[0].args[started[0].args.indexOf("--question") + 1], "first question");
  assert.equal(started[1].args[started[1].args.indexOf("--question") + 1], "second question");
  assert.match(started[0].args.at(-1) ?? "", /^tui-/);
  assert.match(started[1].args.at(-1) ?? "", /^tui-/);
  assert.notEqual(started[0].args.at(-1), started[1].args.at(-1));
});

test("chat turns surface supervisor output when the worker exits before a terminal event", async () => {
  const result = await runTuiChatTurn(
    {
      project: "/tmp/e06-review",
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
      posture: "inspect",
      help: false,
    },
    "hello",
    () => {},
    (processOptions) => {
      queueMicrotask(() => {
        processOptions.onOutput?.(
          "ERROR: Prepared project unavailable; create a project manifest first",
        );
        processOptions.onExit({ code: 1, signal: null, cancelled: false });
      });
      return {
        id: processOptions.id,
        cancel: () => {},
        dispose: () => {},
      };
    },
  );
  assert.equal(result.status, "failed");
  assert.match(result.message ?? "", /Prepared project unavailable/);
});
test("chat turn keeps useful worker diagnostics when a Node.js footer follows", async () => {
  const result = await runTuiChatTurn(
    {
      project: "/tmp/e06-review",
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
      posture: "inspect",
      help: false,
    },
    "hello",
    () => {},
    (processOptions) => {
      queueMicrotask(() => {
        processOptions.onOutput?.("stderr: ERROR: Provider credential is missing");
        for (let index = 0; index < 8; index += 1)
          processOptions.onOutput?.(`stderr: at stack frame ${index}`);
        processOptions.onOutput?.("stderr: Node.js v26.5.0");
        processOptions.onExit({ code: 1, signal: null, cancelled: false });
      });
      return {
        id: processOptions.id,
        cancel: () => {},
        dispose: () => {},
      };
    },
  );
  assert.equal(result.status, "failed");
  assert.match(result.message ?? "", /Provider credential is missing/);
  assert.match(result.message ?? "", /Node\.js v26\.5\.0/);
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
test("chat startup keeps prompting until a model is selected", async () => {
  let attempts = 0;
  const prompt = {
    question: async () => "ignored",
    close: () => {},
  };
  const selection = await runTuiRequiredModelSelection(prompt, async () => {
    attempts += 1;
    return attempts === 2 ? { provider: "anthropic", model: "claude-sonnet-4-5" } : undefined;
  });

  assert.deepEqual(selection, { provider: "anthropic", model: "claude-sonnet-4-5" });
  assert.equal(attempts, 2);
});

test("startup flow collects the model before an interactive review question", async () => {
  const steps: string[] = [];
  const prompt = {
    question: async (message: string) => {
      steps.push(message);
      return "What is downstream of P-400?";
    },
    close: () => {},
  };
  const result = await runTuiStartupPrompt(prompt, { chooseModel: true }, async () => {
    steps.push("model-picker");
    return { provider: "anthropic", model: "claude-sonnet-4-5" };
  });
  assert.deepEqual(result, {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    question: "What is downstream of P-400?",
  });
  assert.deepEqual(steps, ["model-picker", "What should this review establish? "]);
});
test("explicit startup arguments bypass the interactive model and question prompts", async () => {
  let asked = false;
  const result = await runTuiStartupPrompt(
    {
      question: async () => {
        asked = true;
        return "unexpected";
      },
      close: () => {},
    },
    {
      chooseModel: false,
      initialQuestion: "  Review the source.  ",
    },
    async () => {
      throw new Error("model picker should not run");
    },
  );
  assert.deepEqual(result, { question: "Review the source." });
  assert.equal(asked, false);
});
test("chat session keeps follow-up questions, model changes, and streamed answers in one loop", async () => {
  const answers = ["follow-up", "/model", "after model", "/quit"];
  const prompts: string[] = [];
  const output: string[] = [];
  const questions: string[] = [];
  let selection = { provider: "openrouter", model: "deepseek/deepseek-v4-flash" };
  const prompt = {
    question: async (message: string) => {
      prompts.push(message);
      return answers.shift() ?? "/quit";
    },
    close: () => {},
  };

  await runTuiChatSession({
    prompt,
    initialQuestion: "first question",
    chooseModel: async () => ({
      provider: "anthropic",
      model: "claude-sonnet-4-5",
    }),
    applyModelSelection: (next) => {
      selection = next;
    },
    runTurn: async (question, onEvent) => {
      questions.push(`${selection.provider}/${selection.model}:${question}`);
      onEvent({ type: "assistant_text_delta", text: "grounded answer" });
      return { status: "completed" };
    },
    write: (text) => output.push(text),
  });
  assert.deepEqual(questions, [
    "openrouter/deepseek/deepseek-v4-flash:first question",
    "openrouter/deepseek/deepseek-v4-flash:follow-up",
    "anthropic/claude-sonnet-4-5:after model",
  ]);
  assert.deepEqual(prompts, ["You: ", "You: ", "You: ", "You: "]);
  assert.equal(selection.provider, "anthropic");
  assert.equal(selection.model, "claude-sonnet-4-5");
  assert.match(output.join(""), /Assistant: grounded answer/);
});

test("chat session reports failed turns and does not start empty or slash-command turns", async () => {
  const answers = ["", "/unknown", "question", "/quit"];
  const questions: string[] = [];
  const output: string[] = [];
  await runTuiChatSession({
    prompt: {
      question: async () => answers.shift() ?? "/quit",
      close: () => {},
    },
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    runTurn: async (question) => {
      questions.push(question);
      return { status: "failed", message: "provider unavailable" };
    },
    write: (text) => output.push(text),
  });

  assert.deepEqual(questions, ["question"]);
  assert.match(output.join(""), /Assistant unavailable: provider unavailable/);
  assert.match(output.join(""), /Unknown command/);
});
test("chat session recovers after cancelled and thrown turns", async () => {
  const answers = ["cancelled turn", "thrown turn", "/quit"];
  const questions: string[] = [];
  const output: string[] = [];
  let turn = 0;
  await runTuiChatSession({
    prompt: {
      question: async () => answers.shift() ?? "/quit",
      close: () => {},
    },
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    runTurn: async (question) => {
      questions.push(question);
      turn += 1;
      if (turn === 1) return { status: "cancelled" };
      throw new Error("worker failed\r\n\tforged-thrown");
    },
    write: (text) => output.push(text),
  });

  const transcript = output.join("");
  assert.deepEqual(questions, ["cancelled turn", "thrown turn"]);
  assert.match(transcript, /Assistant turn cancelled/);
  assert.match(transcript, /Assistant unavailable: worker failed/);
  assert.doesNotMatch(transcript, /\r|\t|worker failed\nforged-thrown/);
});

test("chat session bounds and sanitizes worker-derived output", async () => {
  const hugeTool = `${"portlog_tool ".repeat(300)}\r\n\tforged-tool`;
  const hugeAnswer = `${"A".repeat(20_000)}\r\t\u001b[2J`;
  const hugeFailure = `${"E".repeat(5_000)}\r\n\tforged-failure`;
  const output: string[] = [];
  await runTuiChatSession({
    prompt: {
      question: async () => "/quit",
      close: () => {},
    },
    initialQuestion: "show bounded output",
    chooseModel: async () => undefined,
    applyModelSelection: () => {},
    runTurn: async (_question, onEvent) => {
      for (let index = 0; index < 40; index += 1) {
        onEvent({ type: "tool_request", tool: hugeTool });
      }
      onEvent({ type: "assistant_text_delta", text: hugeAnswer });
      return { status: "failed", message: hugeFailure };
    },
    write: (text) => output.push(text),
  });

  const transcript = output.join("");
  assert.ok(transcript.length < 24_000);
  assert.doesNotMatch(transcript, /\u001b/);
  assert.ok(!transcript.includes(hugeTool));
  assert.match(transcript, /assistant output truncated/);
  assert.doesNotMatch(transcript, /\t|\r/);
  assert.doesNotMatch(transcript, /\[PortLog tool:[^\]]*\nforged-tool/);
  assert.doesNotMatch(transcript, /Assistant unavailable:[^\n]*\nforged-failure/);
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

test("review output parser preserves whitespace at assistant chunk boundaries", () => {
  assert.deepEqual(parseReviewLine("TURN STARTED"), { type: "turn_started" });
  assert.deepEqual(parseReviewLine("ASSISTANT: Evidence is bounded."), {
    type: "assistant_text_delta",
    text: "Evidence is bounded.",
  });
  const first = parseReviewLine("ASSISTANT: How can I");
  const second = parseReviewLine("ASSISTANT:  help you today?");
  const indented = parseReviewLine("ASSISTANT:   keep this indentation");
  assert.equal(first?.type, "assistant_text_delta");
  assert.equal(second?.type, "assistant_text_delta");
  assert.equal(indented?.type, "assistant_text_delta");
  assert.equal(`${first?.text ?? ""}${second?.text ?? ""}`, "How can I help you today?");
  assert.equal(indented?.text, "  keep this indentation");
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
