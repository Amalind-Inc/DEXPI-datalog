"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useMemo,
  useState,
} from "react";
import { samplePidGraph } from "@/components/pid/sample-graph";
import type {
  PidGraph,
  PidNode,
  PidView,
  PrepareResult,
  SchematicScene,
  SchematicSceneKind,
} from "@/components/pid/types";

const EMPTY_PID_VIEW: PidView = { units: [], lines: [], hiddenTopologyIds: [] };

type GraphContextValue = {
  graph: PidGraph;
  pidView: PidView;
  schematicScene: SchematicScene | null;
  schematicSceneKind: SchematicSceneKind;
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
  const [graph, setGraph] = useState<PidGraph>(samplePidGraph);
  const [pidView, setPidView] = useState<PidView>(EMPTY_PID_VIEW);
  const [schematicScene, setSchematicScene] = useState<SchematicScene | null>(null);
  const [schematicSceneKind, setSchematicSceneKind] = useState<SchematicSceneKind>("none");
  const [loadedFileName, setLoadedFileName] = useState<string | null>(null);
  const [isGraphOpen, setGraphOpen] = useState<boolean>(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("pump-101");
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([
    "pump-101",
  ]);

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  );

  const value = useMemo<GraphContextValue>(
    () => ({
      graph,
      pidView,
      schematicScene,
      schematicSceneKind,
      loadedFileName,
      isGraphOpen,
      selectedNodeId,
      highlightedNodeIds,
      selectedNode,
      setSelectedNodeId,
      setHighlightedNodeIds,
      setGraphOpen,
      applyPrepareResult(result) {
        setGraph(result.graph);
        setPidView(result.pidView ?? EMPTY_PID_VIEW);
        setSchematicScene(result.schematicScene ?? null);
        setSchematicSceneKind(result.schematicSceneKind ?? "none");
        setLoadedFileName(result.filename);
        setGraphOpen(true);
        setSelectedNodeId(result.sourceScopeIds[0] ?? result.graph.nodes[0]?.id ?? null);
        setHighlightedNodeIds(result.sourceScopeIds);
      },
    }),
    [
      graph,
      pidView,
      schematicScene,
      schematicSceneKind,
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
