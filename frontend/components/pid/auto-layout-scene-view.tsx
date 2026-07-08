"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactZoomPanPinchRef } from "react-zoom-pan-pinch";
import { SchematicSceneView } from "@/components/pid/schematic-scene-view";
import { buildAutoLayoutScene } from "@/components/pid/auto-layout-scene";
import { ZoomableScene, ZoomControls } from "@/components/pid/zoomable-scene";
import type { PidView, SchematicScene } from "@/components/pid/types";

type Props = {
  pidView: PidView;
  selectedId: string | null;
  highlightedIds: string[];
  onSelect: (id: string) => void;
};

// Tier-2 auto-layout schematic (bead pydexpi-datalog-1-2ki.5): the backend
// already decided this source failed the geometry sanity gate
// (schematic_scene_kind === "auto-layout") -- this component only computes
// where things land and always discloses that positions are inferred, never
// claiming the render is as drawn.
export function AutoLayoutSchematicView({ pidView, selectedId, highlightedIds, onSelect }: Props) {
  const [scene, setScene] = useState<SchematicScene | null>(null);
  const zoomRef = useRef<ReactZoomPanPinchRef>(null);

  useEffect(() => {
    let cancelled = false;
    setScene(null);
    buildAutoLayoutScene(pidView).then((built) => {
      if (!cancelled) setScene(built);
    });
    return () => {
      cancelled = true;
    };
  }, [pidView]);

  return (
    <div
      className="pid-auto-layout-wrap"
      data-testid="auto-layout-schematic"
      data-highlight-active={highlightedIds.length > 0}
    >
      <div className="pid-auto-layout-header">
        <div className="pid-auto-layout-badge" data-testid="auto-layout-badge">
          Auto-layout — positions inferred, not as drawn
        </div>
        {scene && <ZoomControls zoomRef={zoomRef} />}
      </div>
      {scene ? (
        <ZoomableScene ref={zoomRef}>
          <SchematicSceneView
            scene={scene}
            selectedId={selectedId}
            highlightedIds={highlightedIds}
            onSelect={onSelect}
          />
        </ZoomableScene>
      ) : (
        <p className="pid-auto-layout-loading">Laying out P&amp;ID…</p>
      )}
    </div>
  );
}
