"use client";

import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useEffect, useMemo, useRef } from "react";
import type { PidView } from "@/components/pid/types";
import { symbolFor } from "@/components/pid/pid-symbols";
import { highlightSets } from "@/components/pid/pid-highlight";

let registered = false;
function ensureDagre() {
  if (!registered) {
    cytoscape.use(dagre);
    registered = true;
  }
}

type Props = {
  pidView: PidView;
  highlightedNodeIds: string[];
  selectedNodeId: string | null;
  processFlow: boolean;
  onSelect: (id: string) => void;
};

export function CytoscapePidGraph({
  pidView,
  highlightedNodeIds,
  selectedNodeId,
  processFlow,
  onSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const elements = useMemo<ElementDefinition[]>(() => {
    const unitIds = new Set(pidView.units.map((u) => u.id));
    const nodes: ElementDefinition[] = pidView.units.map((unit) => ({
      data: {
        id: unit.id,
        label: unit.label,
        symbol: symbolFor(unit.category, unit.className),
        ports: unit.ports.length,
      },
    }));
    const edges: ElementDefinition[] = pidView.lines
      .filter(
        (l) =>
          l.sourceUnit && l.targetUnit && unitIds.has(l.sourceUnit) && unitIds.has(l.targetUnit),
      )
      .map((line) => ({
        data: {
          id: line.id || `${line.sourceUnit}->${line.targetUnit}`,
          source: line.sourceUnit as string,
          target: line.targetUnit as string,
          label: line.label,
        },
      }));
    return [...nodes, ...edges];
  }, [pidView]);

  // Build / rebuild the graph when the structure changes.
  useEffect(() => {
    ensureDagre();
    const container = containerRef.current;
    if (!container) return;

    const cy = cytoscape({
      container,
      elements,
      style: [
        {
          selector: "node",
          style: {
            "background-image": "data(symbol)",
            "background-fit": "contain",
            "background-clip": "none",
            "background-opacity": 0,
            "border-width": 0,
            shape: "round-rectangle",
            width: 52,
            height: 52,
            label: "data(label)",
            "text-valign": "bottom",
            "text-margin-y": 7,
            "font-size": 11,
            "font-weight": 600,
            "font-family": "inherit",
            color: "#1f2937",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.7,
            "text-background-padding": "1",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#cbd5e1",
            "curve-style": "taxi",
            "taxi-direction": "horizontal",
            "taxi-turn": "50%",
            label: "data(label)",
            "font-size": 9.5,
            "font-family": "inherit",
            color: "#94a3b8",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.9,
            "text-background-padding": "3",
          },
        },
        {
          selector: "edge.flow",
          style: {
            "line-color": "#3b82f6",
            "target-arrow-color": "#3b82f6",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1,
            color: "#3b82f6",
            width: 2,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "border-width": 2,
            "border-color": "#3b82f6",
            "background-opacity": 0.08,
            "background-color": "#3b82f6",
          },
        },
        {
          selector: "edge.highlighted",
          style: { "line-color": "#3b82f6", width: 3, "target-arrow-color": "#3b82f6" },
        },
        {
          selector: "node.selected",
          style: { "border-width": 2, "border-color": "#f59e0b" },
        },
      ],
      layout: {
        name: "dagre",
        rankDir: "LR",
        nodeSep: 56,
        rankSep: 110,
        padding: 40,
        fit: true,
      } as cytoscape.LayoutOptions,
    });

    cy.on("tap", "node", (evt) => onSelectRef.current(evt.target.id()));
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements]);

  // Process-flow styling: colour + direction arrows on the (already
  // source->target oriented) lines. Re-applied after any rebuild.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.edges().forEach((e) => {
        e.toggleClass("flow", processFlow);
      });
    });
    const container = containerRef.current;
    if (container) container.dataset.processFlow = processFlow ? "true" : "false";
  }, [processFlow, elements]);

  // Apply highlight / selection without rebuilding the graph.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const { units, lines } = highlightSets(pidView, highlightedNodeIds);
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        n.toggleClass("highlighted", units.has(n.id()));
        n.toggleClass("selected", n.id() === selectedNodeId);
      });
      cy.edges().forEach((e) => {
        e.toggleClass("highlighted", lines.has(e.id()));
      });
    });
    // Reflect highlight state in the DOM: the Cytoscape canvas isn't queryable,
    // so expose a count for tests and for any DOM-driven affordances.
    const container = containerRef.current;
    if (container) {
      const count = units.size + lines.size;
      container.dataset.highlightCount = String(count);
      container.dataset.highlightActive = count > 0 ? "true" : "false";
    }
  }, [pidView, highlightedNodeIds, selectedNodeId]);

  return (
    <div
      ref={containerRef}
      data-testid="cytoscape-pid-graph"
      style={{ width: "100%", height: "100%", minHeight: 280 }}
    />
  );
}
