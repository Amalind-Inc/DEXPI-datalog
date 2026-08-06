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
  question?: string;
  selectModelOnStart?: boolean;
  baseUrl?: string;
  sidecarEndpoint?: string;
  help: boolean;
};

const USAGE = `Usage:
  npm run portlog:tui -- --project PATH \\
    [--provider PROVIDER --model MODEL] [--posture inspect|verify|review] \\
    [--question QUESTION]

Omit --model to choose the provider/model during startup. Omit --question
to enter the review question during startup.

The control room keeps the review event feed bounded and labels PortLog-owned
outcomes separately from ordinary model context. Provider credentials stay in
the host environment, as they do for portlog:review.

Interactive commands:
  /model  choose the provider/model for the next review run
  Set PORTLOG_TUI_MODELS to comma-separated provider:model choices.

Keys:
  c cancel   space pause/follow feed   ↑/↓ scroll  r run again
  n new question   / command   ? help   q quit
`;

export async function runPortLogTui(
  argv: readonly string[] = process.argv.slice(2),
): Promise<void> {
  const options = parseArgs(argv);
  if (options.help) {
    output.write(`${USAGE}\n`);
    return;
  }
  if (!input.isTTY || !output.isTTY)
    throw new Error("The PortLog control room requires an interactive terminal.");
  const project = options.project;
  if (!project) throw new Error(`--project is required.\n\n${USAGE}`);

  const app = new PortLogTuiApp({
    ...options,
    project,
    question: options.question?.trim() ?? "",
  });
  await app.run();
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

function parseArgs(argv: readonly string[]): CliOptions {
  const options: CliOptions = {
    provider: process.env.PORTLOG_RUNTIME_PROVIDER?.trim() || "openrouter",
    model: process.env.PORTLOG_RUNTIME_MODEL?.trim() || "deepseek/deepseek-v4-flash",
    posture: "inspect",
    help: false,
  };
  const aliases: Record<string, keyof CliOptions> = {
    "--project": "project",
    "-p": "project",
    "--provider": "provider",
    "--model": "model",
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
    if (!value) throw new Error(`${name} requires a value.\n\n${USAGE}`);
    if (key === "posture" && value !== "inspect" && value !== "verify" && value !== "review")
      throw new Error(`Unsupported posture ${value}.\n\n${USAGE}`);
    options[key] = value as never;
  }
  options.selectModelOnStart = !argv.some(
    (argument) => argument === "--model" || argument.startsWith("--model="),
  );
  return options;
}

export function buildReviewArgs(
  options: CliOptions & { project: string },
  question: string,
): string[] {
  const args = [
    "--project",
    options.project,
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
