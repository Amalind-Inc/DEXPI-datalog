import type { ServerPipelineMetrics } from "@/lib/pid-latency-trace";

export type PidNodeKind = "Pump" | "Valve" | "Instrument" | "Line" | "Equipment";

export type PidNode = {
  id: string;
  label: string;
  kind: PidNodeKind;
  description: string;
  status: "normal" | "warning" | "selected";
};

export type PidEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
};

export type PidGraph = {
  nodes: PidNode[];
  edges: PidEdge[];
};

export type PidPort = { id: string; label: string };

export type PidUnit = {
  id: string;
  label: string;
  className: string;
  category: string;
  description: string;
  ports: PidPort[];
  // Backend-resolved bundled-symbol key (bead pydexpi-datalog-1-2ki.15): the
  // raw DEXPI component class if a bundled symbol covers it, else "generic".
  symbolKey: string;
};

export type PidLine = {
  id: string;
  label: string;
  sourceUnit: string | null;
  targetUnit: string | null;
  sourcePort: string | null;
  targetPort: string | null;
  memberTopologyIds: string[];
};

// Compressed, P&ID-like reading of the topology: equipment units joined by
// collapsed lines. Empty units => no compression available (topology-only fallback).
export type PidView = {
  units: PidUnit[];
  lines: PidLine[];
  hiddenTopologyIds: string[];
};

// Tier-1 drawing-faithful schematic scene (ADR 0004/0005): file-shape
// symbols placed as drawn, drawn centerlines, drawing-native text. The
// backend owns geometry semantics; the frontend paints this verbatim.
export type SchematicPrimitive =
  | {
      kind: "polyline";
      points: [number, number][];
      stroke: string;
      width: number;
      dash: string | null;
    }
  | {
      kind: "circle";
      cx: number;
      cy: number;
      r: number;
      filled: boolean;
      stroke: string;
      width: number;
      dash: string | null;
    }
  | {
      kind: "arc";
      cx: number;
      cy: number;
      r: number;
      start: number;
      end: number;
      stroke: string;
      width: number;
      dash: string | null;
    }
  | {
      kind: "polygon";
      points: [number, number][];
      filled: boolean;
      stroke: string;
      width: number;
      dash: string | null;
    }
  | SchematicText;

export type SchematicText = {
  kind: "text";
  x: number;
  y: number;
  angle: number;
  string: string;
  height: number;
  font: string;
  just: string;
};

export type SchematicSymbol = {
  id: string;
  topologyId: string | null;
  className: string;
  shape: string;
  tx: number;
  ty: number;
  angle: number;
  mirror: boolean;
  sx: number;
  sy: number;
  // Unplaced-equipment shelf (bead pydexpi-datalog-1-2ki.7): true when this
  // symbol carries no source Position and was placed in the shelf region
  // outside the drawing frame instead. The drawn frame itself never carries
  // an invented position -- this is the only place a backend-computed
  // symbol coordinate appears in an otherwise as-drawn scene.
  shelved: boolean;
};

export type SchematicPolyline = {
  id: string;
  topologyId: string | null;
  kind: "pipe" | "signal" | "leader" | "frame";
  points: [number, number][];
  stroke: string;
  width: number;
  dash: string | null;
  // Per-pipe demotion (bead pydexpi-datalog-1-2ki.6): true when this run's
  // source carried no CenterLine and was routed between its source-stated
  // endpoints instead. Drives the one uniform inferred-style cue; drawn
  // runs (false) are painted byte-identical to their scene geometry.
  inferred: boolean;
};

export type SchematicPolygon = {
  points: [number, number][];
  filled: boolean;
  stroke: string;
  width: number;
  dash: string | null;
};

export type SchematicScene = {
  units: string;
  extent: { x0: number; y0: number; x1: number; y1: number } | null;
  catalogue: Record<string, SchematicPrimitive[]>;
  symbols: SchematicSymbol[];
  polylines: SchematicPolyline[];
  polygons: SchematicPolygon[];
  texts: SchematicText[];
};

// Which schematic tier the geometry sanity gate disclosed (backend-owned,
// bead pydexpi-datalog-1-2ki.5): "as-drawn" when the gate passed, "auto-layout"
// when it failed (source connectivity is real, positions are computed), and
// "none" when there is no DEXPI geometry source to evaluate at all.
export type SchematicSceneKind = "as-drawn" | "auto-layout" | "none";

export type GeometryGateMetric = {
  passed: boolean;
  ratio?: number | null;
};

// Per-pipe demotion diagnostic (bead pydexpi-datalog-1-2ki.6): one entry per
// pipe run routed between source-stated endpoints because its CenterLine
// was missing. topologyId is null when the segment has no stable topology
// counterpart in this session's map.
export type InferredPipeRun = {
  topologyId: string | null;
  rawId: string;
  reason: string;
};

// Unplaced-equipment shelf diagnostic (bead pydexpi-datalog-1-2ki.7): one
// entry per shelved item, independent of the gate's pass/fail.
export type ShelvedEquipmentEntry = {
  topologyId: string | null;
  rawId: string;
  reason: string;
};

export type GeometryReport = {
  passed: boolean;
  reasons: string[];
  extent: GeometryGateMetric & { widthMm: number; heightMm: number };
  pipeCoverage: GeometryGateMetric & { segments: number; segmentsWithCenterline: number };
  unpositionedEquipment: GeometryGateMetric & { total: number; missing: number };
  routedPipeRuns: InferredPipeRun[];
  shelvedEquipment: ShelvedEquipmentEntry[];
};

export type PrepareResult = {
  status: "ready" | "failed";
  filename: string;
  graph: PidGraph;
  pidView: PidView;
  schematicScene: SchematicScene | null;
  schematicSceneKind: SchematicSceneKind;
  geometryReport: GeometryReport | null;
  sourceScopeIds: string[];
  renderBundleKey?: string;
  serverMetrics?: ServerPipelineMetrics | null;
};
