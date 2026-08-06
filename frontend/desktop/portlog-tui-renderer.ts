import type { TuiFeedEntry, TuiLane, TuiPhase, TuiState } from "./portlog-tui-model.ts";

const ANSI = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  bold: "\x1b[1m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  white: "\x1b[37m",
  gray: "\x1b[90m",
} as const;

const ANSI_PATTERN = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const OSC_PATTERN = /\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
const ESCAPE_PATTERN = /\x1b(?:[@-_])/g;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f-\u009f]/g;

export interface TuiRenderOptions {
  readonly width: number;
  readonly height: number;
  readonly now?: Date;
  readonly showHelp?: boolean;
}

export function renderTui(state: TuiState, options: TuiRenderOptions): readonly string[] {
  const width = Math.max(40, options.width);
  const height = Math.max(12, options.height);
  if (options.showHelp) return renderHelp(width, height);

  const lines: string[] = [];
  lines.push(
    fit(
      `${paint(ANSI.cyan, "PORTLOG")} ${paint(ANSI.dim, "/")} ${paint(ANSI.bold, "REVIEW CONTROL ROOM")} ${paint(ANSI.gray, "· prepared process review")}`,
      width,
    ),
  );
  lines.push(
    fit(
      `${paint(ANSI.gray, "SOURCE")} ${paint(ANSI.white, sourceLabel(state))}  ${paint(ANSI.gray, "MODEL")} ${paint(ANSI.white, modelLabel(state))}  ${paint(ANSI.gray, "STATUS")} ${statusLabel(state)}  ${paint(ANSI.gray, "ELAPSED")} ${elapsed(state, options.now ?? new Date())}`,
      width,
    ),
  );
  lines.push(rule(width));
  lines.push(fit(renderPhaseRail(state.phase), width));
  lines.push(fit(`${paint(ANSI.gray, "QUESTION")} ${paint(ANSI.white, state.question)}`, width));
  lines.push(rule(width));

  const feedHeight = Math.max(5, height - (width >= 100 ? 17 : 24));
  if (width >= 100) {
    const leftWidth = Math.max(58, Math.floor(width * 0.69));
    const rightWidth = width - leftWidth - 3;
    const feed = renderFeed(state, feedHeight, leftWidth);
    const summary = renderSummary(state, feedHeight, rightWidth);
    for (let index = 0; index < Math.max(feed.length, summary.length); index += 1) {
      lines.push(
        `${fit(feed[index] ?? "", leftWidth)} ${paint(ANSI.gray, "│")} ${fit(summary[index] ?? "", rightWidth)}`,
      );
    }
  } else {
    lines.push(...renderSummary(state, 7, width));
    lines.push(rule(width));
    lines.push(...renderFeed(state, feedHeight, width));
  }

  while (lines.length < height - 3) lines.push("");
  lines.push(rule(width));
  lines.push(
    fit(
      `${paint(ANSI.yellow, "[c]")} cancel  ${paint(ANSI.yellow, "[space]")} ${state.followLive ? "pause feed" : "follow live"}  ${paint(ANSI.yellow, "[↑↓]")} scroll  ${paint(ANSI.yellow, "[r]")} run again  ${paint(ANSI.yellow, "[?]")} help  ${paint(ANSI.yellow, "[q]")} quit`,
      width,
    ),
  );
  lines.push(
    fit(
      `${paint(ANSI.gray, "Future controls")}  background review team · send back · assign again  ${paint(ANSI.gray, "(not active in this slice)")}`,
      width,
    ),
  );
  return lines.slice(0, height).map((line) => fit(line, width));
}

function renderFeed(state: TuiState, height: number, width: number): string[] {
  const entries = state.feed;
  const selected = entries[state.cursor];
  const title = `${paint(ANSI.bold, "LIVE REVIEW")} ${paint(ANSI.gray, state.followLive ? "· following" : "· paused for viewing")} ${paint(ANSI.gray, `· ${entries.length}/${entries.length + state.feedTruncated} events`)}`;
  const result = [fit(title, width)];
  if (!entries.length) {
    result.push(paint(ANSI.gray, "Waiting for the first review event…"));
    result.push(paint(ANSI.gray, "The review will show evidence, checks, and actions here."));
    return result;
  }

  const bodyHeight = Math.max(1, height - 1);
  const start = state.followLive
    ? Math.max(0, entries.length - bodyHeight)
    : Math.max(0, Math.min(state.cursor - bodyHeight + 1, entries.length - bodyHeight));
  for (const [offset, entry] of entries.slice(start, start + bodyHeight).entries()) {
    const index = start + offset;
    result.push(formatFeedEntry(entry, index === state.cursor && !state.followLive, width));
  }
  if (selected && !state.followLive && selected.detail) {
    result.push(fit(`${paint(ANSI.gray, "DETAIL")} ${paint(ANSI.white, selected.detail)}`, width));
  }
  return result;
}

function renderSummary(state: TuiState, height: number, width: number): string[] {
  if (width < 100) {
    const answer =
      state.assistantText.trim() || state.terminalMessage || "Waiting for the review to report.";
    const lines = [
      paint(ANSI.bold, "REVIEW SUMMARY"),
      `${paint(ANSI.gray, "Status")} ${statusLabel(state)}`,
      `${paint(ANSI.gray, "Phase")} ${phaseLabel(state.phase)}`,
      `${paint(ANSI.gray, "Coverage")} ${coverageLabel(state)}`,
      paint(ANSI.bold, "CURRENT ANSWER"),
      ...wrapText(answer, width, 2),
    ];
    return lines.slice(0, height).map((line) => fit(line, width));
  }

  const lines = [
    paint(ANSI.bold, "REVIEW SUMMARY"),
    `${paint(ANSI.gray, "Posture")} ${state.posture}`,
    `${paint(ANSI.gray, "Phase")} ${phaseLabel(state.phase)}`,
    `${paint(ANSI.gray, "Events")} ${state.feed.length + state.feedTruncated}${state.feedTruncated ? ` ${paint(ANSI.yellow, `(${state.feedTruncated} older hidden)`)}` : ""}`,
    `${paint(ANSI.gray, "Authority")} PortLog outcomes stay explicit`,
    `${paint(ANSI.gray, "Coverage")} ${coverageLabel(state)}`,
  ];
  if (state.assistantText.trim()) {
    lines.push("", paint(ANSI.bold, "CURRENT ANSWER"), ...wrapText(state.assistantText, width, 4));
  }
  lines.push("", paint(ANSI.bold, "WORK LANES"), ...state.lanes.map(formatLane));
  if (state.terminalMessage) {
    lines.push("");
    lines.push(paint(state.status === "failed" ? ANSI.red : ANSI.yellow, "OPERATOR NOTE"));
    lines.push(paint(state.status === "failed" ? ANSI.red : ANSI.yellow, state.terminalMessage));
  }
  return lines.slice(0, height).map((line) => fit(line, width));
}

function formatFeedEntry(entry: TuiFeedEntry, selected: boolean, width: number): string {
  const marker = selected ? paint(ANSI.cyan, "›") : " ";
  const authority =
    entry.authority === "portlog"
      ? paint(ANSI.magenta, "PORTLOG")
      : entry.authority === "ordinary"
        ? paint(ANSI.blue, "CONTEXT")
        : paint(ANSI.gray, "SYSTEM");
  const time = entry.timestamp.slice(11, 19);
  return fit(
    `${marker} ${paint(ANSI.gray, String(entry.sequence).padStart(3, "0"))} ${authority} ${paint(ANSI.gray, phaseLabel(entry.phase))} ${paint(ANSI.white, entry.summary)}`,
    width,
  );
}

function formatLane(lane: TuiLane): string {
  const symbol =
    lane.status === "working"
      ? paint(ANSI.cyan, "●")
      : lane.status === "complete"
        ? paint(ANSI.green, "✓")
        : lane.status === "blocked"
          ? paint(ANSI.red, "!")
          : lane.status === "cancelled"
            ? paint(ANSI.yellow, "—")
            : paint(ANSI.gray, "○");
  return `${symbol} ${paint(ANSI.white, lane.label)}: ${paint(ANSI.gray, lane.note)}`;
}

function renderPhaseRail(current: TuiPhase): string {
  const phases: TuiPhase[] = ["prepare", "inspect", "check", "isolate", "report"];
  return phases
    .map((phase) => {
      const state = phase === current ? paint(ANSI.cyan, "●") : paint(ANSI.gray, "○");
      return `${state} ${phaseLabel(phase)}`;
    })
    .join(paint(ANSI.gray, "  →  "));
}

function renderHelp(width: number, height: number): readonly string[] {
  const content = [
    paint(ANSI.bold, "PORTLOG REVIEW CONTROL ROOM / HELP"),
    "",
    `${paint(ANSI.yellow, "↑ / ↓")} move through the bounded event feed`,
    `${paint(ANSI.yellow, "space")} pause or resume following new events (the review keeps running)`,
    `${paint(ANSI.yellow, "c")} request cancellation; the final state remains visible`,
    `${paint(ANSI.yellow, "r")} run the same question again after a terminal outcome`,
    `${paint(ANSI.yellow, "/")} enter a command; use ${paint(ANSI.yellow, "/model")} to choose the next review model`,
    `${paint(ANSI.yellow, "q")} quit; active reviews ask for confirmation`,
    "",
    paint(
      ANSI.gray,
      "The feed shows normalized review events only. It does not show hidden model reasoning.",
    ),
    paint(
      ANSI.gray,
      "Evidence and deterministic checks are PortLog-owned authority. Ordinary context is labeled.",
    ),
    paint(
      ANSI.gray,
      "Background workers, send-back, and assign-again controls are deliberately deferred.",
    ),
    "",
    paint(ANSI.cyan, "Press any key to return to the review."),
  ];
  const lines = content.map((line) => fit(line, width));
  while (lines.length < height) lines.push("");
  return lines.slice(0, height);
}

function sourceLabel(state: TuiState): string {
  const directory = state.identity.projectDirectory;
  if (!directory) return "prepared project";
  const parts = directory.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? directory;
}

function modelLabel(state: TuiState): string {
  if (!state.identity.provider || !state.identity.model) return "not selected";
  return sanitizeTerminalText(`${state.identity.provider}/${state.identity.model}`);
}

function statusLabel(state: TuiState): string {
  const label = state.status === "cancelling" ? "CANCELLING…" : state.status.toUpperCase();
  const color =
    state.status === "completed"
      ? ANSI.green
      : state.status === "failed"
        ? ANSI.red
        : state.status === "cancelled" || state.status === "cancelling"
          ? ANSI.yellow
          : ANSI.cyan;
  return paint(color, label);
}

function coverageLabel(state: TuiState): string {
  if (state.status === "completed") return "Read conclusion and scope";
  if (state.status === "cancelled") return "Incomplete / not evaluated";
  if (state.status === "failed") return "Outcome unavailable";
  return "Not evaluated yet";
}

function phaseLabel(phase: TuiPhase): string {
  return {
    prepare: "prepare",
    inspect: "inspect",
    check: "check",
    isolate: "isolate",
    report: "report",
  }[phase];
}
function sanitizeTerminalText(value: string): string {
  return value
    .replace(OSC_PATTERN, "")
    .replace(ANSI_PATTERN, "")
    .replace(ESCAPE_PATTERN, "")
    .replace(CONTROL_PATTERN, " ");
}

function wrapText(value: string, width: number, maxLines: number): string[] {
  const cleaned = sanitizeTerminalText(value);
  const words = cleaned.replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (!words.length) return ["—"];
  const maxWidth = Math.max(1, width - 2);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (lines.length >= maxLines) break;
    const next = line ? `${line} ${word}` : word;
    if (terminalCellWidth(next) <= maxWidth) {
      line = next;
      continue;
    }
    if (line) {
      lines.push(line);
      if (lines.length >= maxLines) break;
    }
    line = truncateToWidth(word, maxWidth);
    if (terminalCellWidth(word) > maxWidth) {
      lines.push(line);
      line = "";
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (
    lines.length === maxLines &&
    terminalCellWidth(words.join(" ")) > terminalCellWidth(lines.join(" "))
  ) {
    const last = lines.length - 1;
    const ellipsisWidth = terminalCellWidth("…");
    lines[last] = `${truncateToWidth(lines[last], Math.max(0, maxWidth - ellipsisWidth))}…`;
  }
  return lines;
}

function elapsed(state: TuiState, now: Date): string {
  if (!state.startedAt) return "—";
  const start = Date.parse(state.startedAt);
  if (!Number.isFinite(start)) return "—";
  const end = state.completedAt ? Date.parse(state.completedAt) : now.getTime();
  const seconds = Math.max(0, Math.floor((end - start) / 1_000));
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function rule(width: number): string {
  return paint(ANSI.gray, "─".repeat(Math.max(1, width)));
}

function paint(color: string, value: string): string {
  return `${color}${sanitizeTerminalText(value)}${ANSI.reset}`;
}

function fit(value: string, width: number): string {
  const cleanWidth = terminalCellWidth(value);
  if (cleanWidth > width) {
    const truncated = truncateToWidth(
      stripAnsi(value),
      Math.max(0, width - terminalCellWidth("…")),
    );
    return `${truncated}…`;
  }
  return `${value}${" ".repeat(Math.max(0, width - cleanWidth))}`;
}

function stripAnsi(value: string): string {
  return value.replace(ANSI_PATTERN, "");
}

export function terminalCellWidth(value: string): number {
  return graphemes(stripAnsi(value)).reduce(
    (total, grapheme) => total + graphemeCellWidth(grapheme),
    0,
  );
}

function graphemes(value: string): string[] {
  const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
  return Array.from(segmenter.segment(value), (part) => part.segment);
}

function truncateToWidth(value: string, width: number): string {
  if (width <= 0) return "";
  let used = 0;
  let result = "";
  for (const grapheme of graphemes(value)) {
    const nextWidth = graphemeCellWidth(grapheme);
    if (used + nextWidth > width) break;
    result += grapheme;
    used += nextWidth;
  }
  return result;
}

function graphemeCellWidth(grapheme: string): number {
  if (grapheme.includes("\u200d") || grapheme.includes("\u20e3")) return 2;
  return Array.from(grapheme).reduce((total, character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return total + codePointCellWidth(codePoint);
  }, 0);
}

function codePointCellWidth(codePoint: number): number {
  if (
    codePoint === 0 ||
    codePoint === 0x200d ||
    codePoint === 0xfe0e ||
    codePoint === 0xfe0f ||
    (codePoint >= 0x1f3fb && codePoint <= 0x1f3ff) ||
    /^\p{Mark}$/u.test(String.fromCodePoint(codePoint))
  )
    return 0;
  if (
    (codePoint >= 0x1100 && codePoint <= 0x115f) ||
    codePoint === 0x2329 ||
    codePoint === 0x232a ||
    (codePoint >= 0x2e80 && codePoint <= 0xa4cf) ||
    (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
    (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
    (codePoint >= 0xfe10 && codePoint <= 0xfe19) ||
    (codePoint >= 0xfe30 && codePoint <= 0xfe6f) ||
    (codePoint >= 0xff00 && codePoint <= 0xff60) ||
    (codePoint >= 0xffe0 && codePoint <= 0xffe6) ||
    (codePoint >= 0x1f000 && codePoint <= 0x1faff)
  )
    return 2;
  return 1;
}
