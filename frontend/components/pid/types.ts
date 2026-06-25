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

export type PrepareResult = {
  status: "ready" | "failed";
  filename: string;
  graph: PidGraph;
  sourceScopeIds: string[];
};
