"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type {
  SchematicPolygon,
  SchematicPolyline,
  SchematicPrimitive,
  SchematicScene,
  SchematicSymbol,
} from "@/components/pid/types";
import {
  catalogueShapesUsed,
  sceneViewBox,
  symbolTransform,
  textAnchor,
} from "@/lib/schematic-scene";

type Props = {
  scene: SchematicScene;
  selectedId: string | null;
  highlightedIds: string[];
  onSelect: (topologyId: string) => void;
};

// Tier-1 drawing-faithful schematic (ADR 0004): paints the backend-owned
// scene verbatim -- no geometry semantics computed here. Proteus is Y-up;
// SVG is Y-down, so the whole world group is flipped once, and each text
// primitive is un-flipped locally so labels read upright.
export function SchematicSceneView({ scene, selectedId, highlightedIds, onSelect }: Props) {
  const box = useMemo(() => sceneViewBox(scene), [scene]);
  const defs = useMemo(() => catalogueShapesUsed(scene), [scene]);
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);

  return (
    <svg
      className="schematic-scene-svg"
      viewBox={`0 0 ${box.width} ${box.height}`}
      role="img"
      aria-label="Schematic view, rendered as drawn"
      data-testid="schematic-scene"
    >
      <defs>
        {defs.map(([shape, primitives]) => (
          <g key={shape} id={`schematic-sym-${shape}`}>
            {primitives.map((primitive, index) => (
              <SchematicPrimitiveShape key={index} primitive={primitive} />
            ))}
          </g>
        ))}
      </defs>
      <g transform={`translate(${-box.x} ${box.y + box.height}) scale(1,-1)`}>
        {scene.polylines.map((polyline, index) => (
          <SchematicPolylineShape
            // A raw Proteus id can be shared by more than one drawn element
            // (e.g. a signal arrow glyph keyed to its instrument); dedupe the
            // React key with the index while keeping data-id as the identity.
            key={`${polyline.id}-${index}`}
            polyline={polyline}
            selected={polyline.topologyId !== null && polyline.topologyId === selectedId}
            highlighted={polyline.topologyId !== null && highlighted.has(polyline.topologyId)}
            onSelect={onSelect}
          />
        ))}
        {scene.polygons.map((polygon, index) => (
          <SchematicPrimitiveShape key={index} primitive={{ kind: "polygon", ...polygon }} />
        ))}
        {scene.symbols.map((symbol, index) => (
          <SchematicSymbolUse
            key={`${symbol.id}-${index}`}
            symbol={symbol}
            selected={symbol.topologyId !== null && symbol.topologyId === selectedId}
            highlighted={symbol.topologyId !== null && highlighted.has(symbol.topologyId)}
            onSelect={onSelect}
          />
        ))}
        {scene.texts.map((text, index) => (
          <SchematicPrimitiveShape key={index} primitive={text} />
        ))}
      </g>
    </svg>
  );
}

function SchematicPolylineShape({
  polyline,
  selected,
  highlighted,
  onSelect,
}: {
  polyline: SchematicPolyline;
  selected: boolean;
  highlighted: boolean;
  onSelect: (topologyId: string) => void;
}) {
  const hitTestable = polyline.kind !== "frame" && polyline.kind !== "leader" && polyline.topologyId !== null;
  return (
    <polyline
      className={cn(
        "schematic-polyline",
        `schematic-${polyline.kind}`,
        selected && "selected",
        highlighted && "highlighted",
        polyline.inferred && "schematic-inferred",
      )}
      data-id={polyline.id}
      data-inferred={polyline.inferred || undefined}
      points={polyline.points.map(([x, y]) => `${x},${y}`).join(" ")}
      fill="none"
      stroke={polyline.stroke}
      strokeWidth={polyline.width}
      // The one uniform inferred-style cue (bead pydexpi-datalog-1-2ki.6)
      // overrides any source-authored dash pattern -- drawn runs keep
      // whatever LineType the source declared, routed runs always get this
      // exact dash so "inferred" reads the same regardless of source style.
      strokeDasharray={polyline.inferred ? "5 3" : polyline.dash ?? undefined}
      role={hitTestable ? "button" : undefined}
      tabIndex={hitTestable ? 0 : undefined}
      aria-label={hitTestable ? `Select ${polyline.kind} ${polyline.id}` : undefined}
      onClick={hitTestable ? () => onSelect(polyline.topologyId as string) : undefined}
    />
  );
}

function SchematicSymbolUse({
  symbol,
  selected,
  highlighted,
  onSelect,
}: {
  symbol: SchematicSymbol;
  selected: boolean;
  highlighted: boolean;
  onSelect: (topologyId: string) => void;
}) {
  const hitTestable = symbol.topologyId !== null;
  return (
    <use
      href={`#schematic-sym-${symbol.shape}`}
      className={cn("schematic-symbol", selected && "selected", highlighted && "highlighted")}
      data-id={symbol.id}
      transform={symbolTransform(symbol)}
      role={hitTestable ? "button" : undefined}
      tabIndex={hitTestable ? 0 : undefined}
      aria-label={hitTestable ? `Select ${symbol.className || "object"} ${symbol.id}` : undefined}
      onClick={hitTestable ? () => onSelect(symbol.topologyId as string) : undefined}
    />
  );
}

function SchematicPrimitiveShape({ primitive }: { primitive: SchematicPrimitive }) {
  switch (primitive.kind) {
    case "polyline":
      return (
        <polyline
          points={primitive.points.map(([x, y]) => `${x},${y}`).join(" ")}
          fill="none"
          stroke={primitive.stroke}
          strokeWidth={primitive.width}
          strokeDasharray={primitive.dash ?? undefined}
        />
      );
    case "circle":
      return (
        <circle
          cx={primitive.cx}
          cy={primitive.cy}
          r={primitive.r}
          fill={primitive.filled ? primitive.stroke : "none"}
          stroke={primitive.stroke}
          strokeWidth={primitive.width}
        />
      );
    case "arc": {
      const a0 = (primitive.start * Math.PI) / 180;
      const a1 = (primitive.end * Math.PI) / 180;
      const x0 = primitive.cx + primitive.r * Math.cos(a0);
      const y0 = primitive.cy + primitive.r * Math.sin(a0);
      const x1 = primitive.cx + primitive.r * Math.cos(a1);
      const y1 = primitive.cy + primitive.r * Math.sin(a1);
      const sweep = ((primitive.end - primitive.start) % 360 + 360) % 360;
      const largeArc = sweep > 180 ? 1 : 0;
      return (
        <path
          d={`M ${x0} ${y0} A ${primitive.r} ${primitive.r} 0 ${largeArc} 1 ${x1} ${y1}`}
          fill="none"
          stroke={primitive.stroke}
          strokeWidth={primitive.width}
        />
      );
    }
    case "polygon": {
      const polygon = primitive as SchematicPolygon;
      return (
        <polygon
          points={polygon.points.map(([x, y]) => `${x},${y}`).join(" ")}
          fill={polygon.filled ? polygon.stroke : "none"}
          stroke={polygon.stroke}
          strokeWidth={polygon.width}
        />
      );
    }
    case "text": {
      const rotation = -primitive.angle;
      const rotate = rotation ? ` rotate(${rotation} ${primitive.x} ${-primitive.y})` : "";
      return (
        <text
          x={primitive.x}
          y={-primitive.y}
          transform={`scale(1,-1)${rotate}`}
          fontSize={primitive.height}
          fontFamily={`${primitive.font}, sans-serif`}
          textAnchor={textAnchor(primitive.just)}
        >
          {primitive.string}
        </text>
      );
    }
    default:
      return null;
  }
}
