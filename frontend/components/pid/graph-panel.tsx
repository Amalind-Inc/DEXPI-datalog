"use client";

import { Search, SlidersHorizontal, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { ReactZoomPanPinchRef } from "react-zoom-pan-pinch";
import { cn } from "@/lib/utils";
import { usePidGraph } from "@/components/pid/graph-context";
import type { PidNodeKind } from "@/components/pid/types";
import { layoutGraphNodes } from "@/components/pid/graph-layout";
import { CytoscapePidGraph } from "@/components/pid/cytoscape-pid-graph";
import { SchematicSceneView } from "@/components/pid/schematic-scene-view";
import { AutoLayoutSchematicView } from "@/components/pid/auto-layout-scene-view";
import { PidLegend } from "@/components/pid/pid-legend";
import { GeometryHealthCard } from "@/components/pid/geometry-health-card";
import { ZoomableScene, ZoomControls } from "@/components/pid/zoomable-scene";
import { describeSchematicTier } from "@/lib/schematic-scene";

const filters: Array<PidNodeKind | "All"> = [
  "All",
  "Pump",
  "Valve",
  "Instrument",
  "Line",
];

export function PidGraphPanel() {
  const {
    graph,
    pidView,
    schematicScene,
    schematicSceneKind,
    geometryReport,
    highlightedNodeIds,
    loadedFileName,
    selectedNode,
    selectedNodeId,
    setSelectedNodeId,
    setGraphOpen,
  } = usePidGraph();
  const shelvedTopologyIds = useMemo(() => {
    if (!schematicScene) return new Set<string>();
    return new Set(
      schematicScene.symbols
        .filter((symbol) => symbol.shelved && symbol.topologyId !== null)
        .map((symbol) => symbol.topologyId as string),
    );
  }, [schematicScene]);
  const selectedIsShelved = selectedNodeId !== null && shelvedTopologyIds.has(selectedNodeId);
  const hasPidView = pidView.units.length > 0;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<PidNodeKind | "All">("All");
  const [showLegend, setShowLegend] = useState(false);
  const [processFlow, setProcessFlow] = useState(true);
  const schematicZoomRef = useRef<ReactZoomPanPinchRef>(null);

  const visibleNodes = useMemo(
    () =>
      graph.nodes.filter((node) => {
        const matchesFilter = filter === "All" || node.kind === filter;
        const matchesQuery =
          query.trim() === "" ||
          node.label.toLowerCase().includes(query.toLowerCase()) ||
          node.description.toLowerCase().includes(query.toLowerCase());
        return matchesFilter && matchesQuery;
      }),
    [filter, graph.nodes, query],
  );
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const positions = useMemo(() => layoutGraphNodes(graph), [graph]);
  const nodeLabelById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node.label])),
    [graph.nodes],
  );
  const connectedLines = useMemo(() => {
    if (!selectedNodeId) return [];
    return pidView.lines
      .filter((line) => line.sourceUnit === selectedNodeId || line.targetUnit === selectedNodeId)
      .map((line) => {
        const otherUnit =
          line.sourceUnit === selectedNodeId ? line.targetUnit : line.sourceUnit;
        return {
          id: line.id,
          label: line.label || line.id,
          otherUnitLabel: otherUnit ? nodeLabelById.get(otherUnit) ?? otherUnit : "unconnected",
        };
      });
  }, [nodeLabelById, pidView.lines, selectedNodeId]);

  return (
    <aside className="pid-panel" aria-label="Process document graph panel">
      <div className="pid-tabbar">
        <div className="pid-tab" data-testid="pid-tab">
          <span className="pid-tab-name">{loadedFileName ?? "sample graph"}</span>
          <button
            type="button"
            className="pid-tab-close"
            data-testid="close-graph"
            aria-label="Close topology view"
            onClick={() => setGraphOpen(false)}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      <GeometryHealthCard />

      <div className="pid-search-row">
        <label className="pid-search">
          <Search size={15} aria-hidden="true" />
          <span className="sr-only">Search nodes</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search nodes"
          />
        </label>
        <label className="pid-filter">
          <SlidersHorizontal size={15} aria-hidden="true" />
          <span className="sr-only">Filters</span>
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value as PidNodeKind | "All")}
          >
            {filters.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      </div>

      <section className="pid-graph-canvas" aria-label="Graph visualization">
        {schematicScene ? (
          <div className="pid-schematic-wrap" data-testid="schematic-panel">
            <div className="pid-schematic-header">
              <div
                className="pid-tier-badge"
                data-testid="schematic-tier-badge"
                data-tier={describeSchematicTier("as-drawn", geometryReport).tier}
              >
                {describeSchematicTier("as-drawn", geometryReport).label}
              </div>
              <ZoomControls zoomRef={schematicZoomRef} />
            </div>
            <ZoomableScene ref={schematicZoomRef}>
              <SchematicSceneView
                scene={schematicScene}
                selectedId={selectedNodeId}
                highlightedIds={highlightedNodeIds}
                onSelect={setSelectedNodeId}
              />
            </ZoomableScene>
          </div>
        ) : schematicSceneKind === "auto-layout" && hasPidView ? (
          <div className="pid-schematic-wrap" data-testid="auto-layout-panel">
            <AutoLayoutSchematicView
              pidView={pidView}
              selectedId={selectedNodeId}
              highlightedIds={highlightedNodeIds}
              onSelect={setSelectedNodeId}
            />
          </div>
        ) : hasPidView ? (
          <div className="pid-cyto-wrap">
            <div className="pid-cyto-toolbar">
              <button
                type="button"
                data-testid="toggle-process-flow"
                className={cn("pid-toolbar-btn", processFlow && "active")}
                aria-pressed={processFlow}
                onClick={() => setProcessFlow((value) => !value)}
              >
                Process flow
              </button>
              <button
                type="button"
                data-testid="toggle-legend"
                className={cn("pid-toolbar-btn", showLegend && "active")}
                aria-expanded={showLegend}
                onClick={() => setShowLegend((value) => !value)}
              >
                Legend
              </button>
            </div>
            {showLegend && <PidLegend onClose={() => setShowLegend(false)} />}
            <CytoscapePidGraph
              pidView={pidView}
              highlightedNodeIds={highlightedNodeIds}
              selectedNodeId={selectedNodeId}
              processFlow={processFlow}
              onSelect={setSelectedNodeId}
            />
          </div>
        ) : (
        <svg viewBox="0 0 430 290" role="img" aria-label="Process document topology graph">
          {graph.edges.map((edge) => {
            const source = positions[edge.source] ?? { x: 60, y: 60 };
            const target = positions[edge.target] ?? { x: 320, y: 180 };
            const isVisible = visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target);
            const isHighlighted =
              highlightedNodeIds.includes(edge.source) ||
              highlightedNodeIds.includes(edge.target);
            return (
              <g key={edge.id} opacity={isVisible ? 1 : 0.2}>
                <line
                  className={cn("pid-edge", isHighlighted && "highlighted")}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                />
                <text
                  className="pid-edge-label"
                  x={(source.x + target.x) / 2}
                  y={(source.y + target.y) / 2 - 8}
                >
                  {edge.label}
                </text>
              </g>
            );
          })}
          {graph.nodes.map((node) => {
            const position = positions[node.id] ?? { x: 160, y: 140 };
            const isVisible = visibleNodeIds.has(node.id);
            const isSelected = selectedNodeId === node.id;
            const isHighlighted = highlightedNodeIds.includes(node.id);
            return (
              <g
                key={node.id}
                className="pid-node-group"
                opacity={isVisible ? 1 : 0.18}
                onClick={() => setSelectedNodeId(node.id)}
                role="button"
                aria-label={`Select ${node.label}`}
                tabIndex={0}
              >
                <rect
                  className={cn(
                    "pid-node",
                    node.kind.toLowerCase(),
                    isSelected && "selected",
                    isHighlighted && "highlighted",
                  )}
                  x={position.x - 40}
                  y={position.y - 23}
                  width="80"
                  height="46"
                  rx="7"
                />
                <text className="pid-node-label" x={position.x} y={position.y + 4}>
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>
        )}
      </section>

      <section className="pid-details" aria-label="Selected-node details view">
        <p className="pid-eyebrow">Selected node</p>
        {selectedNode ? (
          <>
            <h3>{selectedNode.label}</h3>
            <dl>
              <div>
                <dt>Type</dt>
                <dd>{selectedNode.kind}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{selectedNode.status}</dd>
              </div>
            </dl>
            <p>{selectedNode.description}</p>
            {selectedIsShelved && (
              <p className="pid-shelved-disclosure" data-testid="shelved-disclosure">
                Position not in source — shown on the shelf. Connectivity is exact.
              </p>
            )}
            {connectedLines.length > 0 && (
              <div className="pid-connections" data-testid="pid-connections">
                <p className="pid-eyebrow">Connections</p>
                <ul>
                  {connectedLines.map((line) => (
                    <li key={line.id}>
                      {line.label} → {line.otherUnitLabel}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p>Select a graph node to ground assistant answers.</p>
        )}
      </section>
    </aside>
  );
}
