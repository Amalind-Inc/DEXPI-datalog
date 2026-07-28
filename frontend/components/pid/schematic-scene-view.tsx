"use client";

import { useMemo, useState } from "react";
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
  shelfRegionBounds,
  symbolHitRadius,
  symbolTransform,
  textAnchor,
} from "@/lib/schematic-scene";

type Props = {
  scene: SchematicScene;
  selectedId: string | null;
  highlightedIds: string[];
  onSelect: (topologyId: string) => void;
};

// World-space floor for a symbol's invisible hit-circle, so near-zero-scale
// connector glyphs still get a clickable target. Kept small so it doesn't
// overlap neighboring symbols on a dense schematic.
const MIN_HIT_RADIUS = 2;

// Tier-1 drawing-faithful schematic (ADR 0004): paints the backend-owned
// scene verbatim -- no geometry semantics computed here. Proteus is Y-up;
// SVG is Y-down, so the whole world group is flipped once, and each text
// primitive is un-flipped locally so labels read upright.
export function SchematicSceneView({ scene, selectedId, highlightedIds, onSelect }: Props) {
  const box = useMemo(() => sceneViewBox(scene), [scene]);
  const defs = useMemo(() => catalogueShapesUsed(scene), [scene]);
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);
  const shelfBounds = useMemo(() => shelfRegionBounds(scene), [scene]);
  // Hover feedback (bead follow-up: precise-click complaint) -- lets a user
  // preview what a click would select before committing to it.
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  // Per-symbol hit-circle radius: the shape's own generous-but-modest radius,
  // capped by half the distance to the nearest OTHER symbol so two
  // closely-spaced (or coincident, e.g. a nozzle on its parent's boundary)
  // hit-areas never fully cover one another and steal each other's clicks.
  const symbolHitRadii = useMemo(() => {
    const raw = scene.symbols.map((symbol) =>
      Math.max(
        symbolHitRadius(scene.catalogue, symbol.shape) *
          Math.max(Math.abs(symbol.sx), Math.abs(symbol.sy)),
        MIN_HIT_RADIUS,
      ),
    );
    return scene.symbols.map((symbol, index) => {
      let cap = raw[index];
      for (let other = 0; other < scene.symbols.length; other += 1) {
        if (other === index) continue;
        const dx = symbol.tx - scene.symbols[other].tx;
        const dy = symbol.ty - scene.symbols[other].ty;
        const halfDistance = Math.sqrt(dx * dx + dy * dy) / 2 - 0.1;
        if (halfDistance < cap) cap = halfDistance;
      }
      return Math.max(cap, 0.3);
    });
  }, [scene]);

  return (
    <svg
      className="schematic-scene-svg"
      viewBox={`0 0 ${box.width} ${box.height}`}
      role="img"
      aria-label="Schematic view, rendered as drawn"
      data-testid="schematic-scene"
      data-highlight-active={highlighted.size > 0}
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
        {shelfBounds && (
          <g className="schematic-shelf-region" data-testid="schematic-shelf-region">
            <rect
              x={shelfBounds.x}
              y={shelfBounds.y}
              width={shelfBounds.width}
              height={shelfBounds.height}
              rx={2}
            />
            <text
              x={shelfBounds.x + 2}
              y={-(shelfBounds.y + shelfBounds.height - 2)}
              transform="scale(1,-1)"
            >
              UNPLACED — NOT IN SOURCE
            </text>
          </g>
        )}
        {scene.polylines.map((polyline, index) => (
          <SchematicPolylineShape
            // A raw Proteus id can be shared by more than one drawn element
            // (e.g. a signal arrow glyph keyed to its instrument); dedupe the
            // React key with the index while keeping data-id as the identity.
            key={`${polyline.id}-${index}`}
            polyline={polyline}
            selected={polyline.topologyId !== null && polyline.topologyId === selectedId}
            highlighted={polyline.topologyId !== null && highlighted.has(polyline.topologyId)}
            hovered={polyline.topologyId !== null && hoveredId === polyline.topologyId}
            onSelect={onSelect}
            onHover={setHoveredId}
          />
        ))}
        {scene.polygons.map((polygon, index) => (
          <SchematicPrimitiveShape key={index} primitive={{ kind: "polygon", ...polygon }} />
        ))}
        {scene.symbols.map((symbol, index) => (
          <SchematicSymbolUse
            key={`${symbol.id}-${index}`}
            symbol={symbol}
            hitRadius={symbolHitRadii[index]}
            selected={symbol.topologyId !== null && symbol.topologyId === selectedId}
            highlighted={symbol.topologyId !== null && highlighted.has(symbol.topologyId)}
            hovered={symbol.topologyId !== null && hoveredId === symbol.topologyId}
            onSelect={onSelect}
            onHover={setHoveredId}
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
  hovered,
  onSelect,
  onHover,
}: {
  polyline: SchematicPolyline;
  selected: boolean;
  highlighted: boolean;
  hovered: boolean;
  onSelect: (topologyId: string) => void;
  onHover: (topologyId: string | null) => void;
}) {
  const hitTestable =
    polyline.kind !== "frame" && polyline.kind !== "leader" && polyline.topologyId !== null;
  const points = polyline.points.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <>
      {hitTestable && (
        // Invisible, generously wide hit-area -- the painted stroke below is
        // often too thin to click precisely, so this decouples "what you can
        // click" from "what's drawn".
        <polyline
          className="schematic-hit-area"
          points={points}
          fill="none"
          stroke="transparent"
          strokeWidth={Math.max(polyline.width * 6, 3)}
          role="button"
          tabIndex={0}
          aria-label={`Select ${polyline.kind} ${polyline.id}`}
          onClick={() => onSelect(polyline.topologyId as string)}
          onMouseEnter={() => onHover(polyline.topologyId)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(polyline.topologyId)}
          onBlur={() => onHover(null)}
        />
      )}
      <polyline
        className={cn(
          "schematic-polyline",
          `schematic-${polyline.kind}`,
          selected && "selected",
          highlighted && "highlighted",
          hovered && "hovered",
          polyline.inferred && "schematic-inferred",
        )}
        data-id={polyline.id}
        data-inferred={polyline.inferred || undefined}
        points={points}
        fill="none"
        stroke={polyline.stroke}
        strokeWidth={polyline.width}
        // The one uniform inferred-style cue (bead pydexpi-datalog-1-2ki.6)
        // overrides any source-authored dash pattern -- drawn runs keep
        // whatever LineType the source declared, routed runs always get this
        // exact dash so "inferred" reads the same regardless of source style.
        strokeDasharray={polyline.inferred ? "5 3" : (polyline.dash ?? undefined)}
      />
    </>
  );
}

function SchematicSymbolUse({
  symbol,
  hitRadius,
  selected,
  highlighted,
  hovered,
  onSelect,
  onHover,
}: {
  symbol: SchematicSymbol;
  hitRadius: number;
  selected: boolean;
  highlighted: boolean;
  hovered: boolean;
  onSelect: (topologyId: string) => void;
  onHover: (topologyId: string | null) => void;
}) {
  const hitTestable = symbol.topologyId !== null;
  const transform = symbolTransform(symbol);
  return (
    <>
      {hitTestable && (
        // Invisible padding around the symbol -- rendered UNDERNEATH the
        // real <use> below, so it only catches clicks that miss the shape's
        // own painted geometry. Coincident/adjacent symbols (e.g. a nozzle
        // exactly on its parent's boundary) keep resolving via their real,
        // usually-distinct outlines instead of two overlapping blobs fighting
        // over who's on top.
        <circle
          className="schematic-hit-area schematic-symbol-hit"
          cx={symbol.tx}
          cy={symbol.ty}
          r={hitRadius}
          fill="transparent"
          role="button"
          tabIndex={0}
          data-shelved={symbol.shelved || undefined}
          aria-label={`Select ${symbol.className || "object"} ${symbol.id}`}
          onClick={() => onSelect(symbol.topologyId as string)}
          onMouseEnter={() => onHover(symbol.topologyId)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(symbol.topologyId)}
          onBlur={() => onHover(null)}
        />
      )}
      <use
        href={`#schematic-sym-${symbol.shape}`}
        role={hitTestable ? "button" : undefined}
        tabIndex={hitTestable ? 0 : undefined}
        aria-label={hitTestable ? `Select ${symbol.className || "object"} ${symbol.id}` : undefined}
        onClick={hitTestable ? () => onSelect(symbol.topologyId as string) : undefined}
        onMouseEnter={hitTestable ? () => onHover(symbol.topologyId) : undefined}
        onMouseLeave={hitTestable ? () => onHover(null) : undefined}
        onFocus={hitTestable ? () => onHover(symbol.topologyId) : undefined}
        onBlur={hitTestable ? () => onHover(null) : undefined}
        className={cn(
          "schematic-symbol",
          selected && "selected",
          highlighted && "highlighted",
          hovered && "hovered",
          symbol.shelved && "schematic-shelved",
        )}
        data-id={symbol.id}
        data-shelved={symbol.shelved || undefined}
        transform={transform}
      />
    </>
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
      const sweep = (((primitive.end - primitive.start) % 360) + 360) % 360;
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
