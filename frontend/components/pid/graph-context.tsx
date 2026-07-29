"use client";

import { createContext, type ReactNode, useContext, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  documentNames: string[];
  isGraphOpen: boolean;
  selectedNodeId: string | null;
  highlightedNodeIds: string[];
  selectedNode: PidNode | null;
  setSelectedNodeId: (nodeId: string | null) => void;
  setHighlightedNodeIds: (nodeIds: string[]) => void;
  setGraphOpen: (open: boolean) => void;
  applyPrepareResult: (result: PrepareResult) => void;
  selectDocument: (filename: string) => void;
  deleteDocument: (filename: string) => void;
};

const GraphContext = createContext<GraphContextValue | null>(null);

export function PidGraphProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(readOrCreateSessionId);
  const [documents, setDocuments] = useState<PrepareResult[]>([]);
  const [activeDocumentName, setActiveDocumentName] = useState<string | null>(null);
  const [isGraphOpen, setGraphOpen] = useState<boolean>(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("pump-101");
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>(["pump-101"]);
  const documentRevision = useRef(0);

  const activeDocument = useMemo(
    () => documents.find((document) => document.filename === activeDocumentName) ?? null,
    [activeDocumentName, documents],
  );
  const documentNames = useMemo(() => documents.map((document) => document.filename), [documents]);
  const graph = activeDocument?.graph ?? samplePidGraph;
  const pidView = activeDocument?.pidView ?? EMPTY_PID_VIEW;
  const schematicScene = activeDocument?.schematicScene ?? null;
  const schematicSceneKind = activeDocument?.schematicSceneKind ?? "none";
  const geometryReport = activeDocument?.geometryReport ?? null;
  const loadedFileName = activeDocument?.filename ?? null;

  const activateDocument = useCallback((result: PrepareResult) => {
    setActiveDocumentName(result.filename);
    setGraphOpen(true);
    setSelectedNodeId(result.sourceScopeIds[0] ?? result.graph.nodes[0]?.id ?? null);
    setHighlightedNodeIds(result.sourceScopeIds);
  }, []);

  const applyPrepareResult = useCallback(
    (result: PrepareResult) => {
      documentRevision.current += 1;
      setDocuments((current) => [
        ...current.filter((document) => document.filename !== result.filename),
        result,
      ]);
      activateDocument(result);
    },
    [activateDocument],
  );

  useEffect(() => {
    let cancelled = false;
    const restoreRevision = documentRevision.current;
    void fetch(`/api/review/sessions/${sessionId}/restore`).then(async (response) => {
      if (!response.ok) return null;
      return await response.json() as PrepareResult;
    }).then((restored) => {
      if (!cancelled && restored && documentRevision.current === restoreRevision) applyPrepareResult(restored);
    }).catch(() => { /* A first launch has no durable review to restore. */ });
    return () => { cancelled = true; };
  }, [applyPrepareResult, sessionId]);

  const selectDocument = useCallback(
    (filename: string) => {
      const document = documents.find((candidate) => candidate.filename === filename);
      if (document) activateDocument(document);
    },
    [activateDocument, documents],
  );

  const deleteDocument = useCallback(
    (filename: string) => {
      const remaining = documents.filter((document) => document.filename !== filename);
      setDocuments(remaining);
      if (filename !== activeDocumentName) return;
      const fallback = remaining.at(-1);
      if (fallback) {
        activateDocument(fallback);
        return;
      }
      setActiveDocumentName(null);
      setGraphOpen(false);
      setSelectedNodeId(null);
      setHighlightedNodeIds([]);
    },
    [activateDocument, activeDocumentName, documents],
  );

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
      documentNames,
      isGraphOpen,
      selectedNodeId,
      highlightedNodeIds,
      selectedNode,
      setSelectedNodeId,
      setHighlightedNodeIds,
      setGraphOpen,
      applyPrepareResult,
      selectDocument,
      deleteDocument,
    }),
    [
      applyPrepareResult,
      deleteDocument,
      documentNames,
      geometryReport,
      graph,
      highlightedNodeIds,
      isGraphOpen,
      loadedFileName,
      pidView,
      schematicScene,
      schematicSceneKind,
      selectDocument,
      selectedNode,
      selectedNodeId,
      sessionId,
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
