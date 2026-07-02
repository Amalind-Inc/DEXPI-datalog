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

export type PrepareResult = {
  status: "ready" | "failed";
  filename: string;
  graph: PidGraph;
  pidView: PidView;
  sourceScopeIds: string[];
};
