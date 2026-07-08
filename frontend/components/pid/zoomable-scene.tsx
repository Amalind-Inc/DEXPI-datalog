"use client";

import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { forwardRef, type ReactNode, type RefObject } from "react";
import { TransformComponent, TransformWrapper, type ReactZoomPanPinchRef } from "react-zoom-pan-pinch";

const MIN_SCALE = 0.4;
const MAX_SCALE = 4;

// Wraps the backend-owned schematic/auto-layout scene render (ADR 0005) in
// pan/zoom via a CSS transform on an outer wrapper -- the SVG's own viewBox
// and hit-test geometry underneath are never touched, so selection and
// highlighting keep resolving to the correct element regardless of zoom/pan
// state. The Cytoscape topology-inspection view has its own zoom/pan and
// does not use this wrapper.
//
// Controls are rendered separately (see ZoomControls) in the caller's header
// row rather than floating over the canvas -- an overlaid toolbar would sit
// on top of real, clickable schematic content near that corner.
export const ZoomableScene = forwardRef<ReactZoomPanPinchRef, { children: ReactNode }>(
  function ZoomableScene({ children }, ref) {
    return (
      <TransformWrapper
        ref={ref}
        minScale={MIN_SCALE}
        maxScale={MAX_SCALE}
        initialScale={1}
        centerOnInit
        doubleClick={{ disabled: true }}
      >
        <TransformComponent
          wrapperClass="pid-zoom-wrap"
          wrapperStyle={{ width: "100%", height: "100%" }}
          contentStyle={{ width: "100%", height: "100%" }}
        >
          {children}
        </TransformComponent>
      </TransformWrapper>
    );
  },
);

export function ZoomControls({
  zoomRef,
}: {
  zoomRef: RefObject<ReactZoomPanPinchRef | null>;
}) {
  return (
    <div className="pid-zoom-toolbar">
      <button
        type="button"
        className="pid-toolbar-btn"
        aria-label="Zoom in"
        onClick={() => zoomRef.current?.zoomIn()}
      >
        <ZoomIn size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="pid-toolbar-btn"
        aria-label="Zoom out"
        onClick={() => zoomRef.current?.zoomOut()}
      >
        <ZoomOut size={14} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="pid-toolbar-btn"
        data-testid="reset-view"
        aria-label="Reset view"
        onClick={() => zoomRef.current?.resetTransform()}
      >
        <Maximize2 size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
