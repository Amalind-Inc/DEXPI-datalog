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
import { persistDocumentSelection } from "@/components/pid/document-selection";
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
  documents: PrepareResult[];
  documentNames: string[];
  activeSourceId: string | null;
  isGraphOpen: boolean;
  selectedNodeId: string | null;
  highlightedNodeIds: string[];
  selectedNode: PidNode | null;
  setSelectedNodeId: (nodeId: string | null) => void;
  setHighlightedNodeIds: (nodeIds: string[]) => void;
  setGraphOpen: (open: boolean) => void;
  beginDocumentImport: () => void;
  applyPrepareResult: (result: PrepareResult) => void;
  selectDocument: (sourceIdOrFilename: string) => void;
  deleteDocument: (sourceIdOrFilename: string) => void;
};

const GraphContext = createContext<GraphContextValue | null>(null);

export function PidGraphProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(readOrCreateSessionId);
  const [documents, setDocuments] = useState<PrepareResult[]>([]);
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [isGraphOpen, setGraphOpen] = useState<boolean>(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("pump-101");
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>(["pump-101"]);
  const documentRevision = useRef(0);
  const selectionRevision = useRef(0);

  const activeDocument = useMemo(
    () => documents.find((document) => document.sourceId === activeSourceId) ?? null,
    [activeSourceId, documents],
  );
  const documentNames = useMemo(() => documents.map((document) => document.filename), [documents]);
  const graph = activeDocument?.graph ?? samplePidGraph;
  const pidView = activeDocument?.pidView ?? EMPTY_PID_VIEW;
  const schematicScene = activeDocument?.schematicScene ?? null;
  const schematicSceneKind = activeDocument?.schematicSceneKind ?? "none";
  const geometryReport = activeDocument?.geometryReport ?? null;
  const loadedFileName = activeDocument?.filename ?? null;

  const clearActiveDocument = useCallback(() => {
    setActiveSourceId(null);
    setGraphOpen(false);
    setSelectedNodeId(null);
    setHighlightedNodeIds([]);
  }, []);

  const activateDocument = useCallback((result: PrepareResult) => {
    if (result.sourceId === null) return;
    setActiveSourceId(result.sourceId);
    setGraphOpen(true);
    setSelectedNodeId(result.sourceScopeIds[0] ?? result.graph.nodes[0]?.id ?? null);
    setHighlightedNodeIds(result.sourceScopeIds);
  }, []);

  const resolveDocument = useCallback(
    (sourceIdOrFilename: string) => {
      const sourceMatch = documents.find((document) => document.sourceId === sourceIdOrFilename);
      if (sourceMatch) return sourceMatch;
      const filenameMatches = documents.filter((document) => document.filename === sourceIdOrFilename);
      return filenameMatches.length === 1 ? filenameMatches[0] : null;
    },
    [documents],
  );

  const beginDocumentImport = useCallback(() => { documentRevision.current += 1; }, []);

  const applyPrepareResult = useCallback(
    (result: PrepareResult) => {
      if (result.sourceId === null) return;
      documentRevision.current += 1;
      setDocuments((current) => [
        ...current.filter((document) => document.sourceId !== result.sourceId),
        result,
      ]);
      activateDocument(result);
    },
    [activateDocument],
  );

  const applyRestoredDocuments = useCallback(
    (restored: { activeSourceId: string | null; documents: PrepareResult[] }) => {
      const restoredDocuments = restored.documents.filter((document) => document.sourceId !== null);
      setDocuments(restoredDocuments);
      const activeDocument = restoredDocuments.find(
        (document) => document.sourceId === restored.activeSourceId,
      );
      if (activeDocument) {
        activateDocument(activeDocument);
      } else {
        clearActiveDocument();
      }
    },
    [activateDocument, clearActiveDocument],
  );

  useEffect(() => {
    if (typeof window !== "undefined" && window.portlogDesktop) return;
    let cancelled = false;
    const restoreRevision = documentRevision.current;
    void fetch(`/api/review/sessions/${sessionId}/sources`).then(async (response) => {
      if (!response.ok) return null;
      return await response.json() as { activeSourceId: string | null; documents: PrepareResult[] };
    }).then((restored) => {
      if (!cancelled && restored && documentRevision.current === restoreRevision) {
        applyRestoredDocuments(restored);
      }
    }).catch(() => { /* A first launch has no durable review to restore. */ });
    return () => { cancelled = true; };
  }, [applyRestoredDocuments, sessionId]);

  const selectDocument = useCallback(
    (sourceIdOrFilename: string) => {
      const document = resolveDocument(sourceIdOrFilename);
      if (!document || document.sourceId === null) return;
      const previousDocument = documents.find(
        (candidate) => candidate.sourceId === activeSourceId,
      );
      const revision = ++selectionRevision.current;
      void persistDocumentSelection({
        activate: () => activateDocument(document),
        restore: () => {
          if (previousDocument) {
            activateDocument(previousDocument);
          } else {
            clearActiveDocument();
          }
        },
        request: () =>
          fetch(
            `/api/review/sessions/${sessionId}/sources/${encodeURIComponent(document.sourceId!)}`,
            { method: "PUT" },
          ),
        isCurrent: () => selectionRevision.current === revision,
      });
    },
    [
      activateDocument,
      activeSourceId,
      clearActiveDocument,
      documents,
      resolveDocument,
      sessionId,
    ],
  );

  const deleteDocument = useCallback(
    (sourceIdOrFilename: string) => {
      const document = resolveDocument(sourceIdOrFilename);
      if (!document || document.sourceId === null) return;
      void fetch(
        `/api/review/sessions/${sessionId}/sources/${encodeURIComponent(document.sourceId)}`,
        { method: "DELETE" },
      ).then(async (response) => {
        if (!response.ok) return null;
        return await response.json() as { deleted_source_id: string; active_source_id: string | null };
      }).then((deleted) => {
        if (!deleted || deleted.deleted_source_id !== document.sourceId) return;
        const remaining = documents.filter((candidate) => candidate.sourceId !== document.sourceId);
        setDocuments(remaining);
        const nextActiveDocument = remaining.find(
          (candidate) => candidate.sourceId === deleted.active_source_id,
        );
        if (nextActiveDocument) {
          activateDocument(nextActiveDocument);
        } else {
          clearActiveDocument();
        }
      }).catch(() => {
        // A failed deletion leaves the local graph intact and can be retried.
      });
    },
    [activateDocument, clearActiveDocument, documents, resolveDocument, sessionId],
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
      documents,
      documentNames,
      activeSourceId,
      isGraphOpen,
      selectedNodeId,
      highlightedNodeIds,
      selectedNode,
      setSelectedNodeId,
      setHighlightedNodeIds,
      setGraphOpen,
      beginDocumentImport,
      applyPrepareResult,
      selectDocument,
      deleteDocument,
    }),
    [
      activeSourceId,
      applyPrepareResult,
      beginDocumentImport,
      deleteDocument,
      documentNames,
      documents,
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
