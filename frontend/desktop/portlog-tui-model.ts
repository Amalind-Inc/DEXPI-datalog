export type TuiPosture = "inspect" | "verify" | "review";
export type TuiRunStatus =
  | "idle"
  | "connecting"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";
export type TuiPhase = "prepare" | "inspect" | "check" | "isolate" | "report";
export type TuiAuthority = "ordinary" | "portlog" | "system";
export type TuiEventKind =
  | "turn_started"
  | "assistant_text_delta"
  | "tool_request"
  | "tool_result"
  | "turn_completed"
  | "turn_cancelled"
  | "turn_failed"
  | "system";

export interface TuiSessionIdentity {
  readonly sessionId?: string;
  readonly projectDirectory?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly sourceRevision?: string;
  readonly policyRevision?: string;
}

export interface TuiEvent {
  readonly type: Exclude<TuiEventKind, "system">;
  readonly text?: string;
  readonly tool?: string;
  readonly arguments?: unknown;
  readonly result?: unknown;
  readonly message?: string;
  readonly sequence?: number;
  readonly timestamp?: string;
}

export interface TuiFeedEntry {
  readonly sequence: number;
  readonly kind: TuiEventKind;
  readonly authority: TuiAuthority;
  readonly phase: TuiPhase;
  readonly summary: string;
  readonly detail?: string;
  readonly timestamp: string;
}

export interface TuiLane {
  readonly id: "review" | "evidence" | "check" | "isolation";
  readonly label: string;
  readonly status: "waiting" | "working" | "complete" | "blocked" | "cancelled";
  readonly note: string;
}

export interface TuiCapabilities {
  readonly cancel: "available" | "unavailable";
  readonly backgroundWorkers: "deferred";
  readonly messageBack: "deferred";
  readonly redelegation: "deferred";
}

export interface TuiState {
  readonly identity: TuiSessionIdentity;
  readonly posture: TuiPosture;
  readonly question: string;
  readonly status: TuiRunStatus;
  readonly phase: TuiPhase;
  readonly startedAt?: string;
  readonly completedAt?: string;
  readonly cancelRequestedAt?: string;
  readonly terminalMessage?: string;
  readonly assistantText: string;
  readonly feed: readonly TuiFeedEntry[];
  readonly feedTruncated: number;
  readonly cursor: number;
  readonly followLive: boolean;
  readonly lanes: readonly TuiLane[];
  readonly capabilities: TuiCapabilities;
  readonly lastSequence: number;
}

export const MAX_FEED_ENTRIES = 240;
export const MAX_ASSISTANT_TEXT = 16_000;
const MAX_SUMMARY = 220;
const MAX_DETAIL = 700;

const DEFAULT_LANES: readonly TuiLane[] = [
  { id: "review", label: "Review lead", status: "waiting", note: "Waiting to start" },
  { id: "evidence", label: "Evidence", status: "waiting", note: "No evidence request yet" },
  { id: "check", label: "Deterministic check", status: "waiting", note: "No check request yet" },
  { id: "isolation", label: "Isolated action", status: "waiting", note: "No isolated action yet" },
];

export function createTuiState(options: {
  identity?: TuiSessionIdentity;
  posture: TuiPosture;
  question: string;
}): TuiState {
  return {
    identity: options.identity ?? {},
    posture: options.posture,
    question: options.question,
    status: "idle",
    phase: "prepare",
    assistantText: "",
    feed: [],
    feedTruncated: 0,
    cursor: 0,
    followLive: true,
    lanes: DEFAULT_LANES,
    capabilities: {
      cancel: "available",
      backgroundWorkers: "deferred",
      messageBack: "deferred",
      redelegation: "deferred",
    },
    lastSequence: 0,
  };
}

export function reduceTuiEvent(state: TuiState, event: TuiEvent, now = new Date()): TuiState {
  const timestamp = event.timestamp ?? now.toISOString();
  const sequence = event.sequence ?? state.lastSequence + 1;
  const base = { ...state, lastSequence: Math.max(sequence, state.lastSequence) };

  if (event.type === "turn_started") {
    return appendFeed(
      {
        ...base,
        status: "running",
        phase: "inspect",
        startedAt: state.startedAt ?? timestamp,
        terminalMessage: undefined,
        lanes: updateLane(state.lanes, "review", "working", "Review is underway"),
      },
      makeFeedEntry(
        sequence,
        "turn_started",
        "system",
        "inspect",
        "Review started",
        undefined,
        timestamp,
      ),
    );
  }

  if (event.type === "assistant_text_delta") {
    const nextText = `${state.assistantText}${event.text ?? ""}`;
    const boundedText = nextText.slice(0, MAX_ASSISTANT_TEXT);
    return {
      ...base,
      status: state.status === "idle" ? "running" : state.status,
      phase: state.phase === "prepare" ? "inspect" : state.phase,
      assistantText: boundedText,
    };
  }

  if (event.type === "tool_request") {
    const tool = event.tool ?? "unknown action";
    const phase = phaseForTool(tool);
    const lane = laneForPhase(phase);
    const authority = authorityForTool(tool);
    return appendFeed(
      {
        ...base,
        status: state.status === "idle" ? "running" : state.status,
        phase,
        lanes: lane
          ? updateLane(
              state.lanes,
              lane,
              "working",
              actionNote(tool, "Working from the prepared review"),
            )
          : state.lanes,
      },
      makeFeedEntry(
        sequence,
        "tool_request",
        authority,
        phase,
        actionLabel(tool),
        boundedJson(event.arguments),
        timestamp,
      ),
    );
  }

  if (event.type === "tool_result") {
    const tool = event.tool ?? "unknown action";
    const phase = phaseForTool(tool);
    const lane = laneForPhase(phase);
    return appendFeed(
      {
        ...base,
        phase,
        lanes: lane
          ? updateLane(state.lanes, lane, "complete", resultNote(tool, event.result))
          : state.lanes,
      },
      makeFeedEntry(
        sequence,
        "tool_result",
        authorityForTool(tool),
        phase,
        `${actionLabel(tool)} complete`,
        boundedJson(event.result),
        timestamp,
      ),
    );
  }

  if (event.type === "turn_completed") {
    return appendFeed(
      {
        ...base,
        status: "completed",
        phase: "report",
        completedAt: timestamp,
        terminalMessage: "Review complete. Read the conclusion and coverage separately.",
        lanes: state.lanes.map((lane) =>
          lane.status === "working" ? { ...lane, status: "complete", note: "Completed" } : lane,
        ),
      },
      makeFeedEntry(
        sequence,
        "turn_completed",
        "system",
        "report",
        "Review complete",
        undefined,
        timestamp,
      ),
    );
  }

  if (event.type === "turn_cancelled") {
    return appendFeed(
      {
        ...base,
        status: "cancelled",
        phase: "report",
        completedAt: timestamp,
        terminalMessage: "Review cancelled. No engineering outcome is available from this run.",
        lanes: state.lanes.map((lane) =>
          lane.status === "working"
            ? { ...lane, status: "cancelled", note: "Stopped before completion" }
            : lane.id === "review" && lane.status === "waiting"
              ? { ...lane, status: "cancelled", note: "Cancelled before review started" }
              : lane,
        ),
      },
      makeFeedEntry(
        sequence,
        "turn_cancelled",
        "system",
        "report",
        "Review cancelled",
        undefined,
        timestamp,
      ),
    );
  }

  if (event.type === "turn_failed") {
    const message = bounded(event.message ?? "Review failed", MAX_SUMMARY);
    return appendFeed(
      {
        ...base,
        status: "failed",
        phase: "report",
        completedAt: timestamp,
        terminalMessage: message,
        lanes: state.lanes.map((lane) =>
          lane.status === "working"
            ? { ...lane, status: "blocked", note: "Stopped after a failure" }
            : lane.id === "review" && lane.status === "waiting"
              ? { ...lane, status: "blocked", note: "Review did not start" }
              : lane,
        ),
      },
      makeFeedEntry(sequence, "turn_failed", "system", "report", message, undefined, timestamp),
    );
  }

  return state;
}

export function requestTuiCancellation(state: TuiState, now = new Date()): TuiState {
  if (state.status !== "running" && state.status !== "connecting") return state;
  const timestamp = now.toISOString();
  return {
    ...state,
    status: "cancelling",
    cancelRequestedAt: timestamp,
    terminalMessage: "Cancellation requested; stopping work…",
    feed: [
      ...state.feed,
      makeFeedEntry(
        state.lastSequence + 1,
        "system",
        "system",
        state.phase,
        "Cancellation requested",
        undefined,
        timestamp,
      ),
    ].slice(-MAX_FEED_ENTRIES),
    lastSequence: state.lastSequence + 1,
  };
}

export function moveTuiCursor(state: TuiState, delta: number): TuiState {
  if (!state.feed.length) return state;
  const cursor = Math.max(0, Math.min(state.feed.length - 1, state.cursor + delta));
  return { ...state, cursor, followLive: cursor === state.feed.length - 1 };
}

export function setTuiFollowLive(state: TuiState, followLive: boolean): TuiState {
  return {
    ...state,
    followLive,
    cursor: followLive ? Math.max(0, state.feed.length - 1) : state.cursor,
  };
}

export function phaseForTool(tool: string): TuiPhase {
  if (tool === "portlog_rule_check") return "check";
  if (tool === "portlog_isolated_command" || tool === "bash") return "isolate";
  if (tool === "portlog_evidence" || tool === "portlog_workspace_read") return "inspect";
  return "inspect";
}

export function actionLabel(tool: string): string {
  if (tool === "portlog_evidence") return "Evidence review";
  if (tool === "portlog_rule_check") return "Deterministic check";
  if (tool === "portlog_isolated_command" || tool === "bash") return "Isolated action";
  if (tool === "portlog_workspace_read") return "Source context";
  return "Assistant action";
}

export function authorityForTool(tool: string): TuiAuthority {
  if (tool.startsWith("portlog_")) return "portlog";
  return tool === "bash" ? "ordinary" : "ordinary";
}

function appendFeed(state: TuiState, entry: TuiFeedEntry): TuiState {
  const overflow = Math.max(0, state.feed.length + 1 - MAX_FEED_ENTRIES);
  const feed = [...state.feed, entry].slice(-MAX_FEED_ENTRIES);
  return {
    ...state,
    feed,
    feedTruncated: state.feedTruncated + overflow,
    cursor: state.followLive
      ? Math.max(0, feed.length - 1)
      : Math.min(state.cursor, feed.length - 1),
  };
}

function makeFeedEntry(
  sequence: number,
  kind: TuiEventKind,
  authority: TuiAuthority,
  phase: TuiPhase,
  summary: string,
  detail: string | undefined,
  timestamp: string,
): TuiFeedEntry {
  return {
    sequence,
    kind,
    authority,
    phase,
    summary: bounded(summary, MAX_SUMMARY),
    detail: detail ? bounded(detail, MAX_DETAIL) : undefined,
    timestamp,
  };
}

function laneForPhase(phase: TuiPhase): TuiLane["id"] | undefined {
  if (phase === "inspect") return "evidence";
  if (phase === "check") return "check";
  if (phase === "isolate") return "isolation";
  return undefined;
}

function updateLane(
  lanes: readonly TuiLane[],
  id: TuiLane["id"],
  status: TuiLane["status"],
  note: string,
): readonly TuiLane[] {
  return lanes.map((lane) => (lane.id === id ? { ...lane, status, note } : lane));
}

function actionNote(tool: string, suffix: string): string {
  return `${actionLabel(tool)}: ${suffix}`;
}

function resultNote(tool: string, result: unknown): string {
  if (tool === "portlog_isolated_command" || tool === "bash") {
    const outcome = readString(result, "outcome");
    return outcome ? `Isolated action: ${outcome}` : "Isolated action returned";
  }
  if (tool === "portlog_rule_check") {
    const outcome = readNestedString(result, ["deterministic_result", "outcome"]);
    return outcome ? `Rule result: ${outcome}` : "Check result returned";
  }
  return "Result returned";
}

function readString(value: unknown, key: string): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const result = (value as Record<string, unknown>)[key];
  return typeof result === "string" ? result : undefined;
}

function readNestedString(value: unknown, path: string[]): string | undefined {
  let current = value;
  for (const key of path) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "string" ? current : undefined;
}

function boundedJson(value: unknown): string {
  try {
    return bounded(JSON.stringify(value) ?? "null", MAX_DETAIL);
  } catch {
    return "[unavailable]";
  }
}

function bounded(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
