import { randomUUID } from "node:crypto";
import { emitKeypressEvents } from "node:readline";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  createTuiState,
  moveTuiCursor,
  reduceTuiEvent,
  requestTuiCancellation,
  setTuiFollowLive,
  type TuiPosture,
  type TuiEvent,
  type TuiState,
} from "./portlog-tui-model.ts";
import { renderTui } from "./portlog-tui-renderer.ts";
import { startReviewProcess } from "./portlog-tui-supervisor.ts";
import {
  buildTuiModelChoices,
  parseTuiCommand,
  parseTuiModelSelection,
  type TuiModelSelection,
} from "./portlog-tui-model-selector.ts";

const REPO_ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));
export type CliOptions = {
  project?: string;
  provider: string;
  model: string;
  posture: TuiPosture;
  mode?: "review" | "chat";
  question?: string;
  selectModelOnStart?: boolean;
  baseUrl?: string;
  sidecarEndpoint?: string;
  help: boolean;
};

const USAGE = `Usage:
  npm run portlog:tui -- --project PATH \\
    [--mode review|chat] [--provider PROVIDER --model MODEL] \\
    [--posture inspect|verify|review] [--question QUESTION]

The default mode is chat. Provider and model use the configured runtime
defaults; use /model only when you want to switch them during the session.
Omit --question to enter the first question interactively.

The control room keeps the review event feed bounded and labels PortLog-owned
outcomes separately from ordinary model context. Provider credentials stay in
the host environment, as they do for portlog:review.

Interactive commands:
  /model  choose the provider/model for the next turn
  /quit   leave chat mode
  Set PORTLOG_TUI_MODELS to comma-separated provider:model choices.

Keys:
  c cancel   space pause/follow feed   ↑/↓ scroll  r run again
  n new question   / command   ? help   q quit
`;
export interface TuiWelcomeOptions {
  readonly projectDirectory: string;
  readonly provider: string;
  readonly model: string;
}

export function renderTuiWelcome(options: TuiWelcomeOptions): string {
  return [
    "PORTLOG / CHAT",
    "",
    `WORKSPACE ${resolve(options.projectDirectory)}`,
    `MODEL ${options.provider}/${options.model}`,
    "",
    "Ask a question about the project, its diagrams, or its review evidence.",
    "Tips: /model changes the model; /quit exits. PortLog tools appear as they run.",
  ].join("\n");
}

export async function runPortLogTui(
  argv: readonly string[] = process.argv.slice(2),
): Promise<void> {
  const options = parseTuiOptions(argv);
  if (options.help) {
    output.write(`${USAGE}\n`);
    return;
  }
  if (!input.isTTY || !output.isTTY)
    throw new Error("The PortLog control room requires an interactive terminal.");
  const project = options.project;
  if (!project) throw new Error(`--project is required.\n\n${USAGE}`);

  const appOptions = {
    ...options,
    project,
    question: options.question?.trim() ?? "",
  };
  if (options.mode === "chat") {
    await new PortLogChatApp(appOptions).run();
    return;
  }
  await new PortLogTuiApp(appOptions).run();
}
export interface TuiCommandPrompt {
  question(prompt: string): Promise<string>;
  close(): void;
}

export interface TuiCommandPromptLifecycle {
  detachKeypress(): void;
  setRawMode(enabled: boolean): void;
  resume(): void;
  attachKeypress(): void;
  render(): void;
}

export async function runTuiCommandPrompt(
  prompt: TuiCommandPrompt,
  lifecycle: TuiCommandPromptLifecycle,
  write: (text: string) => void,
  onModel: (prompt: TuiCommandPrompt) => Promise<void>,
): Promise<void> {
  lifecycle.detachKeypress();
  lifecycle.setRawMode(false);
  try {
    const command = parseTuiCommand(await prompt.question("\nCommand: "));
    if (command === "model") await onModel(prompt);
    else if (command === "unknown") write("Unknown command. Use /model.\n");
  } catch {
    write("Command input was cancelled; no change was made.\n");
  } finally {
    prompt.close();
    lifecycle.setRawMode(true);
    lifecycle.resume();
    lifecycle.attachKeypress();
    lifecycle.render();
  }
}
export interface TuiStartupPromptOptions {
  readonly chooseModel: boolean;
  readonly initialQuestion?: string;
}

export interface TuiStartupSelection {
  readonly provider?: TuiModelSelection["provider"];
  readonly model?: string;
  readonly question: string;
}

export async function runTuiStartupPrompt(
  prompt: TuiCommandPrompt,
  options: TuiStartupPromptOptions,
  chooseModel: (prompt: TuiCommandPrompt) => Promise<TuiModelSelection | undefined>,
): Promise<TuiStartupSelection> {
  const selection = options.chooseModel ? await chooseModel(prompt) : undefined;
  const question =
    options.initialQuestion?.trim() ||
    (await prompt.question("What should this review establish? ")).trim();
  if (!question) throw new Error("A review question is required.");
  return {
    ...(selection ? { provider: selection.provider, model: selection.model } : {}),
    question,
  };
}
export interface TuiChatTurnResult {
  readonly status: "completed" | "cancelled" | "failed";
  readonly message?: string;
}

export interface TuiChatSessionOptions {
  readonly prompt: TuiCommandPrompt;
  readonly initialQuestion?: string;
  readonly chooseModel: (prompt: TuiCommandPrompt) => Promise<TuiModelSelection | undefined>;
  readonly applyModelSelection: (selection: TuiModelSelection) => void;
  readonly runTurn: (
    question: string,
    onEvent: (event: TuiEvent) => void,
  ) => Promise<TuiChatTurnResult>;
  readonly write: (text: string) => void;
}

const MAX_CHAT_ASSISTANT_CHARS = 16_000;
const MAX_CHAT_TOOL_EVENTS = 32;
const MAX_CHAT_TOOL_NAME_CHARS = 120;
const MAX_CHAT_ERROR_CHARS = 1_000;
const MAX_CHAT_DIAGNOSTIC_LINES = 8;
export async function runTuiChatSession(options: TuiChatSessionOptions): Promise<void> {
  let nextQuestion = options.initialQuestion?.trim();

  while (true) {
    const providedQuestion = nextQuestion !== undefined;
    let answer: string;
    try {
      answer = nextQuestion ?? (await options.prompt.question("You: "));
    } catch {
      return;
    }
    nextQuestion = undefined;
    const question = answer.trim();
    if (!question) continue;
    if (question === "q" || question === "/quit" || question === "/exit") return;

    const command = parseTuiCommand(question);
    if (command === "model") {
      try {
        const selection = await options.chooseModel(options.prompt);
        if (selection) {
          options.applyModelSelection(selection);
          options.write(`Selected ${selection.provider}/${selection.model} for the next turn.\n`);
        }
      } catch {
        options.write("Model selection was cancelled; no change was made.\n");
      }
      continue;
    }
    if (command === "unknown") {
      options.write("Unknown command. Use /model or /quit.\n");
      continue;
    }

    options.write(`${providedQuestion ? `\nYou: ${question}\n` : "\n"}Assistant: `);
    let assistantCharacters = 0;
    let assistantTruncated = false;
    let toolEvents = 0;
    let toolEventsTruncated = false;
    try {
      const result = await options.runTurn(question, (event) => {
        if (event.type === "assistant_text_delta") {
          const text = sanitizeChatText(event.text ?? "");
          const remaining = MAX_CHAT_ASSISTANT_CHARS - assistantCharacters;
          if (remaining > 0) {
            const visible = text.slice(0, remaining);
            assistantCharacters += visible.length;
            options.write(visible);
          }
          if (text.length > remaining && !assistantTruncated) {
            assistantTruncated = true;
            options.write("\n[assistant output truncated]");
          }
        } else if (event.type === "tool_request") {
          if (toolEvents < MAX_CHAT_TOOL_EVENTS) {
            toolEvents += 1;
            const toolName = boundChatText(
              sanitizeSingleLineChatText(event.tool ?? "unknown"),
              MAX_CHAT_TOOL_NAME_CHARS,
            );
            options.write(`\n[PortLog tool: ${toolName}]\nAssistant: `);
          } else if (!toolEventsTruncated) {
            toolEventsTruncated = true;
            options.write("\n[additional PortLog tool events truncated]\nAssistant: ");
          }
        }
      });
      if (result.status === "failed") {
        const message = boundChatText(
          sanitizeSingleLineChatText(result.message ?? "unknown error"),
          MAX_CHAT_ERROR_CHARS,
        );
        options.write(`\nAssistant unavailable: ${message}\n`);
      } else if (result.status === "cancelled") {
        options.write("\nAssistant turn cancelled.\n");
      } else {
        options.write("\n");
      }
    } catch (error) {
      const message = boundChatText(
        sanitizeSingleLineChatText(error instanceof Error ? error.message : String(error)),
        MAX_CHAT_ERROR_CHARS,
      );
      options.write(`\nAssistant unavailable: ${message}\n`);
    }
  }
}

function sanitizeChatText(value: string): string {
  return value
    .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/gu, "")
    .replace(/\u001b(?:\[[0-?]*[ -/]*[@-~]|\][^\u0007]*(?:\u0007|\u001b\\))/gu, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/gu, "")
    .replace(/[\t\r]/gu, " ");
}
function sanitizeSingleLineChatText(value: string): string {
  return sanitizeChatText(value).replace(/[\t\n\r\u2028\u2029]+/gu, " ");
}

function boundChatText(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  return `${value.slice(0, Math.max(0, maximum - 1))}…`;
}
type TuiChatProcess = Pick<ReturnType<typeof startReviewProcess>, "cancel" | "dispose"> & {
  readonly id: string;
};

type TuiChatProcessStarter = (options: Parameters<typeof startReviewProcess>[0]) => TuiChatProcess;

export function runTuiChatTurn(
  options: CliOptions & { project: string },
  question: string,
  onEvent: (event: TuiEvent) => void,
  startProcess: TuiChatProcessStarter = startReviewProcess,
  onProcessChange?: (process: TuiChatProcess | undefined) => void,
): Promise<TuiChatTurnResult> {
  return new Promise((resolveTurn) => {
    let settled = false;
    let startedProcess: TuiChatProcess | undefined;
    let processDisposed = false;
    const processOutputLines: string[] = [];
    const diagnostic = (message: string): string => {
      const output = boundChatText(processOutputLines.join(" "), MAX_CHAT_ERROR_CHARS).trim();
      return output ? `${message} Diagnostic: ${output}` : message;
    };
    const disposeStartedProcess = () => {
      if (processDisposed || !startedProcess) return;
      processDisposed = true;
      startedProcess.dispose();
    };
    const settle = (result: TuiChatTurnResult) => {
      if (settled) return;
      settled = true;
      disposeStartedProcess();
      onProcessChange?.(undefined);
      resolveTurn(result);
    };
    startedProcess = startProcess({
      id: `chat-${randomUUID()}`,
      cwd: REPO_ROOT,
      args: buildReviewArgs(options, question),
      env: process.env,
      onOutput: (line) => {
        const output = boundChatText(sanitizeSingleLineChatText(line), MAX_CHAT_ERROR_CHARS);
        if (!output) return;
        if (processOutputLines.length >= MAX_CHAT_DIAGNOSTIC_LINES)
          processOutputLines.splice(Math.floor(MAX_CHAT_DIAGNOSTIC_LINES / 2), 1);
        processOutputLines.push(output);
      },
      onEvent: (event) => {
        onEvent(event);
        if (event.type === "turn_completed") settle({ status: "completed" });
        else if (event.type === "turn_cancelled") settle({ status: "cancelled" });
        else if (event.type === "turn_failed")
          settle({
            status: "failed",
            message: diagnostic(event.message ?? "The chat turn failed."),
          });
      },
      onExit: ({ cancelled, code, signal }) => {
        if (cancelled) settle({ status: "cancelled" });
        else if (!settled)
          settle({
            status: "failed",
            message: diagnostic(
              `Chat process stopped before a terminal result (code ${
                code ?? "none"
              }, signal ${signal ?? "none"}).`,
            ),
          });
      },
    });
    if (settled) disposeStartedProcess();
    else onProcessChange?.(startedProcess);
  });
}

export async function runTuiRequiredModelSelection(
  prompt: TuiCommandPrompt,
  chooseModel: (prompt: TuiCommandPrompt) => Promise<TuiModelSelection | undefined>,
): Promise<TuiModelSelection> {
  while (true) {
    const selection = await chooseModel(prompt);
    if (selection) return selection;
  }
}

class PortLogChatApp {
  private readonly options: CliOptions & { project: string; question: string };
  private activeProcess: TuiChatProcess | undefined;

  constructor(options: CliOptions & { project: string; question: string }) {
    this.options = options;
  }

  async run(): Promise<void> {
    const prompt = createInterface({ input, output });
    prompt.on("SIGINT", () => {
      this.activeProcess?.cancel();
      prompt.close();
    });
    try {
      output.write(
        `${renderTuiWelcome({
          projectDirectory: this.options.project,
          provider: this.options.provider,
          model: this.options.model,
        })}\n\n`,
      );
      await runTuiChatSession({
        prompt,
        initialQuestion: this.options.question,
        chooseModel: (activePrompt) => this.chooseModel(activePrompt),
        applyModelSelection: (selection) => this.applyModelSelection(selection),
        runTurn: (question, onEvent) => this.runTurn(question, onEvent),
        write: (text) => output.write(text),
      });
    } finally {
      this.activeProcess?.dispose();
      this.activeProcess = undefined;
      prompt.close();
      output.write("\n");
    }
  }

  private async chooseModel(prompt: TuiCommandPrompt): Promise<TuiModelSelection | undefined> {
    const current = {
      provider: this.options.provider,
      model: this.options.model,
    };
    const choices = buildTuiModelChoices(current, process.env.PORTLOG_TUI_MODELS?.trim() ?? "");
    output.write("\nAvailable chat models:\n");
    for (const [index, choice] of choices.entries()) {
      const marker =
        choice.provider === current.provider && choice.model === current.model ? " (current)" : "";
      output.write(`  ${index + 1}. ${choice.label}${marker}\n`);
    }
    const answer = await prompt.question("Select a number or provider:model: ");
    const selection = parseTuiModelSelection(answer, choices);
    if (!selection) {
      output.write(
        "No model change was made. Enter a listed number or supported provider:model.\n",
      );
      return undefined;
    }
    return selection;
  }

  private applyModelSelection(selection: TuiModelSelection): void {
    this.options.provider = selection.provider;
    this.options.model = selection.model;
  }

  private runTurn(
    question: string,
    onEvent: (event: TuiEvent) => void,
  ): Promise<TuiChatTurnResult> {
    return runTuiChatTurn(this.options, question, onEvent, startReviewProcess, (process) => {
      this.activeProcess = process;
    });
  }
}

class PortLogTuiApp {
  private readonly options: CliOptions & { project: string; question: string };
  private state: TuiState;
  private process: ReturnType<typeof startReviewProcess> | undefined;
  private showHelp = false;
  private closing = false;

  constructor(options: CliOptions & { project: string; question: string }) {
    this.options = options;
    this.state = createTuiState({
      identity: {
        projectDirectory: resolve(options.project),
        provider: options.provider,
        model: options.model,
      },
      posture: options.posture,
      question: options.question,
    });
  }

  private async configureStartup(): Promise<void> {
    if (!this.options.selectModelOnStart && this.state.question) return;
    const prompt = createInterface({ input, output });
    try {
      const startup = await runTuiStartupPrompt(
        prompt,
        {
          chooseModel: this.options.selectModelOnStart === true,
          initialQuestion: this.state.question,
        },
        (activePrompt) => this.chooseModel(activePrompt),
      );
      if (startup.provider && startup.model) {
        this.applyModelSelection({ provider: startup.provider, model: startup.model });
        output.write(`Selected ${startup.provider}/${startup.model} for this review.\n`);
      }
      this.state = { ...this.state, question: startup.question };
    } finally {
      prompt.close();
    }
  }

  async run(): Promise<void> {
    await this.configureStartup();
    emitKeypressEvents(input);
    input.resume();
    process.stdout.on("resize", this.render);
    input.on("keypress", this.handleKeypress);
    this.render();
    this.startReview();

    await new Promise<void>((resolveExit) => {
      this.resolveExit = resolveExit;
    });
    input.off("keypress", this.handleKeypress);
    process.stdout.off("resize", this.render);
    input.setRawMode?.(false);
    input.pause();
    this.process?.dispose();
    output.write("\x1b[?25h\n");
  }

  private resolveExit: (() => void) | undefined;

  private readonly render = (): void => {
    const width = output.columns || 80;
    const height = output.rows || 24;
    output.write("\x1b[?25l\x1b[2J\x1b[H");
    output.write(renderTui(this.state, { width, height, showHelp: this.showHelp }).join("\n"));
  };

  private readonly handleKeypress = (
    value: string,
    key: { name?: string; ctrl?: boolean },
  ): void => {
    if (this.showHelp) {
      this.showHelp = false;
      this.render();
      return;
    }
    if (key.ctrl && key.name === "c") {
      this.cancelOrQuit();
      return;
    }
    if (key.name === "q" || value === "q") {
      this.cancelOrQuit();
      return;
    }
    if (key.name === "up" || value === "k") {
      this.state = moveTuiCursor(this.state, -1);
      this.render();
      return;
    }
    if (key.name === "down" || value === "j") {
      this.state = moveTuiCursor(this.state, 1);
      this.render();
      return;
    }
    if (key.name === "space" || value === " ") {
      this.state = setTuiFollowLive(this.state, !this.state.followLive);
      this.render();
      return;
    }
    if (value === "c") {
      this.cancelReview();
      return;
    }
    if (value === "?") {
      this.showHelp = true;
      this.render();
      return;
    }
    if (value === "/") {
      void this.startCommandPrompt();
      return;
    }
    if (value === "r" && isTerminal(this.state.status)) {
      this.startReview();
      return;
    }
    if (value === "n" && isTerminal(this.state.status)) {
      void this.startNewQuestion();
    }
  };

  private startReview(): void {
    this.process?.dispose();
    this.state = createTuiState({
      identity: this.state.identity,
      posture: this.options.posture,
      question: this.state.question,
    });
    this.state = { ...this.state, status: "connecting" };
    this.render();
    this.process = startReviewProcess({
      id: `review-${randomUUID()}`,
      cwd: REPO_ROOT,
      args: buildReviewArgs(this.options, this.state.question),
      env: process.env,
      onEvent: (event) => {
        this.state = reduceTuiEvent(this.state, event);
        this.render();
      },
      onExit: ({ cancelled }) => {
        if (cancelled && this.state.status === "cancelling") {
          this.state = reduceTuiEvent(this.state, { type: "turn_cancelled" });
          this.render();
        }
      },
    });
  }

  private cancelReview(): void {
    if (this.state.status !== "running" && this.state.status !== "connecting") return;
    this.state = requestTuiCancellation(this.state);
    this.process?.cancel();
    this.render();
  }

  private cancelOrQuit(): void {
    if (this.closing) return;
    if (this.state.status === "running" || this.state.status === "connecting") {
      this.cancelReview();
      this.closing = true;
      setTimeout(() => this.resolveExit?.(), 250);
      return;
    }
    this.closing = true;
    this.resolveExit?.();
  }

  private async startNewQuestion(): Promise<void> {
    input.off("keypress", this.handleKeypress);
    input.setRawMode?.(false);
    const prompt = createInterface({ input, output });
    try {
      const question = (await prompt.question("\nNew review question: ")).trim();
      if (question) {
        this.options.question = question;
        this.startReview();
      }
    } finally {
      prompt.close();
      input.setRawMode?.(true);
      input.resume();
      input.on("keypress", this.handleKeypress);
      this.render();
    }
  }
  private async startCommandPrompt(): Promise<void> {
    const prompt = createInterface({ input, output });
    await runTuiCommandPrompt(
      prompt,
      {
        detachKeypress: () => input.off("keypress", this.handleKeypress),
        setRawMode: (enabled) => input.setRawMode?.(enabled),
        resume: () => input.resume(),
        attachKeypress: () => input.on("keypress", this.handleKeypress),
        render: this.render,
      },
      (text) => output.write(text),
      (activePrompt) => this.startModelSelector(activePrompt),
    );
  }

  private async chooseModel(prompt: TuiCommandPrompt): Promise<TuiModelSelection | undefined> {
    const current = {
      provider: this.options.provider,
      model: this.options.model,
    };
    const choices = buildTuiModelChoices(current, process.env.PORTLOG_TUI_MODELS?.trim() ?? "");
    output.write("\nAvailable review models:\n");
    for (const [index, choice] of choices.entries()) {
      const marker =
        choice.provider === current.provider && choice.model === current.model ? " (current)" : "";
      output.write(`  ${index + 1}. ${choice.label}${marker}\n`);
    }
    const answer = await prompt.question("Select a number or provider:model: ");
    const selection = parseTuiModelSelection(answer, choices);
    if (!selection) {
      output.write(
        "No model change was made. Enter a listed number or supported provider:model.\n",
      );
      return undefined;
    }
    return selection;
  }

  private applyModelSelection(selection: TuiModelSelection): void {
    this.options.provider = selection.provider;
    this.options.model = selection.model;
    this.state = {
      ...this.state,
      identity: {
        ...this.state.identity,
        provider: selection.provider,
        model: selection.model,
      },
    };
  }

  private async startModelSelector(prompt: TuiCommandPrompt): Promise<void> {
    const selection = await this.chooseModel(prompt);
    if (!selection) return;
    this.applyModelSelection(selection);
    output.write(`Selected ${selection.provider}/${selection.model} for the next review run.\n`);
  }
}

export function parseTuiOptions(argv: readonly string[]): CliOptions {
  const options: CliOptions = {
    provider: process.env.PORTLOG_RUNTIME_PROVIDER?.trim() || "openrouter",
    model: process.env.PORTLOG_RUNTIME_MODEL?.trim() || "deepseek/deepseek-v4-flash",
    posture: "inspect",
    mode: "chat",
    help: false,
  };
  const aliases: Record<string, keyof CliOptions> = {
    "--project": "project",
    "-p": "project",
    "--provider": "provider",
    "--model": "model",
    "--mode": "mode",
    "--posture": "posture",
    "--question": "question",
    "-q": "question",
    "--base-url": "baseUrl",
    "--sidecar-endpoint": "sidecarEndpoint",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
      continue;
    }
    const equals = argument.indexOf("=");
    const name = equals === -1 ? argument : argument.slice(0, equals);
    const key = aliases[name];
    if (!key) throw new Error(`Unknown option ${name}.\n\n${USAGE}`);
    const value = equals === -1 ? argv[++index] : argument.slice(equals + 1);
    if (key === "mode" && value !== "review" && value !== "chat")
      throw new Error(`Unsupported mode ${value}.\n\n${USAGE}`);
    if (key === "posture" && value !== "inspect" && value !== "verify" && value !== "review")
      throw new Error(`Unsupported posture ${value}.\n\n${USAGE}`);
    options[key] = value as never;
  }
  options.selectModelOnStart = false;
  return options;
}

export function buildReviewArgs(
  options: CliOptions & { project: string },
  question: string,
): string[] {
  const mode = options.mode === "review" ? "inspection" : "chat";
  const args = [
    "--project",
    options.project,
    "--mode",
    mode,
    "--provider",
    options.provider,
    "--model",
    options.model,
    "--posture",
    options.posture,
    "--question",
    question,
    "--turn-id",
    `tui-${randomUUID()}`,
  ];
  if (options.baseUrl) args.push("--base-url", options.baseUrl);
  if (options.sidecarEndpoint) args.push("--sidecar-endpoint", options.sidecarEndpoint);
  return args;
}

function isTerminal(status: TuiState["status"]): boolean {
  return status === "completed" || status === "cancelled" || status === "failed";
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await runPortLogTui();
  } catch (error) {
    output.write(`ERROR: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
