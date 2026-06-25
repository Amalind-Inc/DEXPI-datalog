"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useMemo,
  useState,
} from "react";
import { samplePidGraph } from "@/components/pid/sample-graph";
import type { PidGraph, PidNode, PrepareResult } from "@/components/pid/types";

type GraphContextValue = {
  graph: PidGraph;
  loadedFileName: string | null;
  selectedNodeId: string | null;
  highlightedNodeIds: string[];
  selectedNode: PidNode | null;
  setSelectedNodeId: (nodeId: string | null) => void;
  setHighlightedNodeIds: (nodeIds: string[]) => void;
  applyPrepareResult: (result: PrepareResult) => void;
};

const GraphContext = createContext<GraphContextValue | null>(null);

export function PidGraphProvider({ children }: { children: ReactNode }) {
  const [graph, setGraph] = useState<PidGraph>(samplePidGraph);
  const [loadedFileName, setLoadedFileName] = useState<string | null>(null);
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
      loadedFileName,
      selectedNodeId,
      highlightedNodeIds,
      selectedNode,
      setSelectedNodeId,
      setHighlightedNodeIds,
      applyPrepareResult(result) {
        setGraph(result.graph);
        setLoadedFileName(result.filename);
        setSelectedNodeId(result.sourceScopeIds[0] ?? result.graph.nodes[0]?.id ?? null);
        setHighlightedNodeIds(result.sourceScopeIds);
      },
    }),
    [graph, highlightedNodeIds, loadedFileName, selectedNode, selectedNodeId],
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
