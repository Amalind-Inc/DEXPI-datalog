import type { PidGraph } from "@/components/pid/types";

export const samplePidGraph: PidGraph = {
  nodes: [
    {
      id: "pump-101",
      label: "P-101",
      kind: "Pump",
      description: "Feed pump with discharge path to isolation valve V-102.",
      status: "normal",
    },
    {
      id: "valve-102",
      label: "V-102",
      kind: "Valve",
      description: "Manual isolation valve on pump discharge.",
      status: "normal",
    },
    {
      id: "flow-transmitter-101",
      label: "FT-101",
      kind: "Instrument",
      description: "Flow transmitter measuring pump discharge flow.",
      status: "warning",
    },
    {
      id: "line-101",
      label: "L-101",
      kind: "Line",
      description: "Discharge line from P-101 through V-102.",
      status: "normal",
    },
  ],
  edges: [
    { id: "e-pump-valve", source: "pump-101", target: "valve-102", label: "discharges to" },
    { id: "e-valve-line", source: "valve-102", target: "line-101", label: "opens to" },
    { id: "e-line-ft", source: "line-101", target: "flow-transmitter-101", label: "measured by" },
  ],
};
