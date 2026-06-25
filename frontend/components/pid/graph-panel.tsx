"use client";

import { Search, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { usePidGraph } from "@/components/pid/graph-context";
import type { PidNodeKind } from "@/components/pid/types";

const positions: Record<string, { x: number; y: number }> = {
  "pump-101": { x: 68, y: 120 },
  "valve-102": { x: 220, y: 96 },
  "flow-transmitter-101": { x: 350, y: 164 },
  "line-101": { x: 248, y: 208 },
};

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
    highlightedNodeIds,
    loadedFileName,
    selectedNode,
    selectedNodeId,
    setSelectedNodeId,
  } = usePidGraph();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<PidNodeKind | "All">("All");

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

  return (
    <aside className="pid-panel" aria-label="P&ID graph panel">
      <header className="pid-panel-header">
        <div>
          <p className="pid-eyebrow">Graph workspace</p>
          <h2>Plant topology</h2>
        </div>
        <span className="pid-file-chip">{loadedFileName ?? "sample graph"}</span>
      </header>

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
        <svg viewBox="0 0 430 290" role="img" aria-label="P&ID topology graph">
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
          </>
        ) : (
          <p>Select a graph node to ground assistant answers.</p>
        )}
      </section>
    </aside>
  );
}
