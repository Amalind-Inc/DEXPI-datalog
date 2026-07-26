"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useCallback,
  useMemo,
  useState,
} from "react";
import { samplePidGraph } from "@/components/pid/sample-graph";
import type {
  GeometryReport,
  PidGraph,
  PidNode,
  PidView,
  PrepareResult,
  SchematicScene,
  SchematicSceneKind,
} from "@/components/pid/types";
import { readOrCreateSessionId } from "@/lib/session-id";

const EMPTY_PID_VIEW: PidView = { units: [], lines: [], hiddenTopologyIds: [] };

type GraphContextValue = {
  sessionId: string;
  graph: PidGraph;
  pidView: PidView;
  schematicScene: SchematicScene | null;
  schematicSceneKind: SchematicSceneKind;
  geometryReport: GeometryReport | null;
  loadedFileName: string | null;
  isGraphOpen: boolean;
  selectedNodeId: string | null;
  highlightedNodeIds: string[];
  selectedNode: PidNode | null;
  setSelectedNodeId: (nodeId: string | null) => void;
  setHighlightedNodeIds: (nodeIds: string[]) => void;
  setGraphOpen: (open: boolean) => void;
  applyPrepareResult: (result: PrepareResult) => void;
};

const GraphContext = createContext<GraphContextValue | null>(null);

export function PidGraphProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(readOrCreateSessionId);
  const [graph, setGraph] = useState<PidGraph>(samplePidGraph);
  const [pidView, setPidView] = useState<PidView>(EMPTY_PID_VIEW);
  const [schematicScene, setSchematicScene] = useState<SchematicScene | null>(null);
  const [schematicSceneKind, setSchematicSceneKind] = useState<SchematicSceneKind>("none");
  const [geometryReport, setGeometryReport] = useState<GeometryReport | null>(null);
  const [loadedFileName, setLoadedFileName] = useState<string | null>(null);
  const [isGraphOpen, setGraphOpen] = useState<boolean>(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("pump-101");
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([
    "pump-101",
  ]);

  const applyPrepareResult = useCallback((result: PrepareResult) => {
    setGraph(result.graph);
    setPidView(result.pidView ?? EMPTY_PID_VIEW);
    setSchematicScene(result.schematicScene ?? null);
    setSchematicSceneKind(result.schematicSceneKind ?? "none");
    setGeometryReport(result.geometryReport ?? null);
    setLoadedFileName(result.filename);
    setGraphOpen(true);
    setSelectedNodeId(result.sourceScopeIds[0] ?? result.graph.nodes[0]?.id ?? null);
    setHighlightedNodeIds(result.sourceScopeIds);
  }, []);

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  );

  const value = useMemo<GraphContextValue>(
    () => ({
      sessionId,
      graph,
      pidView,
      schematicScene,
      schematicSceneKind,
      geometryReport,
      loadedFileName,
      isGraphOpen,
      selectedNodeId,
      highlightedNodeIds,
      selectedNode,
      setSelectedNodeId,
      setHighlightedNodeIds,
      setGraphOpen,
      applyPrepareResult,
    }),
    [
      applyPrepareResult,
      sessionId,
      graph,
      pidView,
      schematicScene,
      schematicSceneKind,
      geometryReport,
      highlightedNodeIds,
      isGraphOpen,
      loadedFileName,
      selectedNode,
      selectedNodeId,
    ],
  );

  return <GraphContext.Provider value={value}>{children}</GraphContext.Provider>;
}

export function usePidGraph() {
  const value = useContext(GraphContext);
  if (!value) {
    throw new Error("usePidGraph must be used inside PidGraphProvider");
  }
  return value;
}
