export type ServerPipelineMetrics = {
  schema_version: number;
  total_ms: number;
  phases_ms: Record<string, number>;
  counts: Record<string, number>;
};

export type BrowserPhase =
  | "file_read"
  | "upload_proxy"
  | "response_transfer"
  | "json_decode"
  | "state_apply"
  | "layout"
  | "react_commit_to_interactive";

export type PidLatencyTraceSnapshot = {
  schemaVersion: 1;
  status: "in_progress" | "interactive";
  filename: string;
  totalMs: number;
  phasesMs: Partial<Record<BrowserPhase, number>>;
  server: ServerPipelineMetrics | null;
  counts: {
    uploadBytes: number;
    responseBytes: number;
    renderedEntities: number;
    svgElements: number;
  };
};

type TraceCounts = {
  responseBytes: number;
  renderedEntities: number;
  svgElements: number;
};

type TraceOptions = {
  filename: string;
  uploadBytes: number;
  now?: () => number;
};

export type PidLatencyTrace = {
  endPhase: (phase: BrowserPhase) => void;
  setServerMetrics: (metrics: ServerPipelineMetrics | null) => void;
  complete: (counts: TraceCounts) => void;
  snapshot: () => PidLatencyTraceSnapshot;
};

export function createPidLatencyTrace({
  filename,
  uploadBytes,
  now = () => performance.now(),
}: TraceOptions): PidLatencyTrace {
  const startedAt = now();
  let phaseStartedAt = startedAt;
  let status: PidLatencyTraceSnapshot["status"] = "in_progress";
  let completedAt = startedAt;
  let server: ServerPipelineMetrics | null = null;
  const phasesMs: Partial<Record<BrowserPhase, number>> = {};
  const counts = { uploadBytes, responseBytes: 0, renderedEntities: 0, svgElements: 0 };

  return {
    endPhase(phase) {
      if (status === "interactive") return;
      const endedAt = now();
      phasesMs[phase] = endedAt - phaseStartedAt;
      phaseStartedAt = endedAt;
      completedAt = endedAt;
    },
    setServerMetrics(metrics) {
      server = metrics;
    },
    complete(finalCounts) {
      if (status === "interactive") return;
      const endedAt = now();
      phasesMs.react_commit_to_interactive = endedAt - phaseStartedAt;
      completedAt = endedAt;
      counts.responseBytes = finalCounts.responseBytes;
      counts.renderedEntities = finalCounts.renderedEntities;
      counts.svgElements = finalCounts.svgElements;
      status = "interactive";
    },
    snapshot() {
      return {
        schemaVersion: 1,
        status,
        filename,
        totalMs: completedAt - startedAt,
        phasesMs: { ...phasesMs },
        server,
        counts: { ...counts },
      };
    },
  };
}

let currentTrace: PidLatencyTrace | null = null;
let responseBytes = 0;

declare global {
  interface Window {
    __PID_LATENCY_TRACE__?: PidLatencyTraceSnapshot;
  }
}

function publish(): void {
  if (typeof window !== "undefined" && currentTrace) {
    window.__PID_LATENCY_TRACE__ = currentTrace.snapshot();
  }
}

export function beginPidLatencyTrace(options: TraceOptions): void {
  currentTrace = createPidLatencyTrace(options);
  responseBytes = 0;
  publish();
}

export function endPidLatencyPhase(phase: BrowserPhase): void {
  currentTrace?.endPhase(phase);
  publish();
}

export function setPidServerMetrics(metrics: ServerPipelineMetrics | null): void {
  currentTrace?.setServerMetrics(metrics);
  publish();
}

export function setPidResponseBytes(bytes: number): void {
  responseBytes = bytes;
}

export function completePidLatencyTrace(counts: Omit<TraceCounts, "responseBytes">): void {
  currentTrace?.complete({ ...counts, responseBytes });
  publish();
}
