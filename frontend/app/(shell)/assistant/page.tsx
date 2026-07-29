"use client";

import { PanelRightOpen } from "lucide-react";
import { useRef, useState } from "react";
import type { LayoutStorage, PanelImperativeHandle } from "react-resizable-panels";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import { cn } from "@/lib/utils";
import { Thread } from "@/components/assistant-ui/thread";
import { PidGraphPanel } from "@/components/pid/graph-panel";
import { DesktopDexpiImport } from "@/components/pid/desktop-dexpi-import";
import { usePidGraph } from "@/components/pid/graph-context";

// react-resizable-panels' storage default resolves to window.localStorage,
// which doesn't exist during Next.js's server-side prerender pass (even for
// a "use client" page) -- fall back to a no-op storage there.
const noopStorage: LayoutStorage = { getItem: () => null, setItem: () => {} };

export default function AssistantPage() {
  const { documentNames, isGraphOpen, setGraphOpen } = usePidGraph();
  const hasPid = documentNames.length > 0;
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    // v2: an earlier build used the Panel's own collapsible/collapsedSize
    // mechanism to open/close, which persisted a collapsed 0% width to
    // storage -- bumped to stop new sessions from inheriting that stale,
    // permanently-closed layout.
    id: "pydexpi.assistantPanels.width.v2",
    panelIds: ["chat", "pid"],
    storage: typeof window === "undefined" ? noopStorage : window.localStorage,
  });
  // Disables the slide transition while the separator is being dragged, so
  // continuous per-pixel resizing stays instant/lag-free -- the transition
  // is only for the discrete open/close toggle.
  const [isResizing, setIsResizing] = useState(false);
  const pidPanelRef = useRef<PanelImperativeHandle>(null);
  // Live drag-to-close threshold (mirrors the left sidebar's own
  // drag-to-collapse behavior): crossing 50% of the panel's width-at-
  // drag-start closes it immediately, while the pointer is still down, via
  // the same setGraphOpen(false) the close-tab button uses -- the CSS
  // collapse transition (`!important`) still animates it smoothly even
  // though the drag itself is otherwise transition-free.
  //
  // The candidate width is computed from the raw pointer delta, not the
  // panel's own (clamped) rendered size -- once the drag pushes past
  // minSize, the library clamps the real width there and it stops
  // shrinking, so reading the rendered size would mean the 50% threshold
  // can never be reached whenever minSize sits above half of the rest
  // width (true at the default size). Tracking the *unclamped* hypothetical
  // width from the raw drag distance instead means continuing to drag past
  // the minSize floor still counts toward the threshold.
  const closeDragRef = useRef<{ startX: number; restWidth: number; triggered: boolean } | null>(
    null,
  );

  const handlePidSeparatorPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    setIsResizing(true);
    closeDragRef.current = {
      startX: event.clientX,
      restWidth: pidPanelRef.current?.getSize().inPixels ?? 0,
      triggered: false,
    };
  };

  const handlePidSeparatorPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = closeDragRef.current;
    if (!drag || drag.triggered || !isGraphOpen || drag.restWidth <= 0) return;
    // Dragging the handle rightward shrinks this (right-hand) panel.
    const candidateWidth = drag.restWidth - (event.clientX - drag.startX);
    if (candidateWidth < drag.restWidth * 0.5) {
      drag.triggered = true;
      setGraphOpen(false);
    }
  };

  const endPidSeparatorDrag = () => {
    setIsResizing(false);
    closeDragRef.current = null;
  };

  return (
    <Group
      orientation="horizontal"
      className={cn("assistant-page-row", isResizing && "assistant-page-row--resizing")}
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
    >
      <Panel id="chat" minSize="30%" className="assistant-chat-panel">
        <section className="calm-chat-column" aria-label="Chat">
          {hasPid && !isGraphOpen && (
            <div className="calm-chat-bar">
              <button
                type="button"
                className="calm-reopen-graph-btn"
                data-testid="reopen-graph"
                onClick={() => setGraphOpen(true)}
              >
                <PanelRightOpen size={15} aria-hidden="true" />
                <span>{documentNames.length === 1 ? "View" : "View topologies"}</span>
              </button>
            </div>
          )}
          <DesktopDexpiImport />
          <Thread />
        </section>
      </Panel>

      {hasPid && (
        <>
          {/* Disabled (not just hidden) while closed -- dragging must never
              be able to pull the panel back open; "View topology" is the
              only way back in. Dragging inward past 50% of its rest-width
              closes it (see closeDragRef above), same gesture as the left
              sidebar. */}
          <Separator
            className={cn(
              "assistant-panel-resize-handle",
              !isGraphOpen && "assistant-panel-resize-handle--disabled",
            )}
            aria-label="Resize chat and topology panels"
            disabled={!isGraphOpen}
            onPointerDown={handlePidSeparatorPointerDown}
            onPointerMove={handlePidSeparatorPointerMove}
            onPointerUp={endPidSeparatorDrag}
            onPointerCancel={endPidSeparatorDrag}
          />
          {/* No `collapsible`/`collapsedSize` here on purpose: that library
              feature auto-snaps the panel shut once a drag crosses halfway
              past minSize (relative to minSize, not the panel's own current
              width) and does so harshly, mid-drag, with no animation.
              Open/close is instead our own pure CSS width override (see
              .assistant-pid-panel--collapsed below) driven by setGraphOpen,
              triggered either by the buttons or by closeDragRef's own
              50%-of-rest-width threshold above -- giving the same smooth,
              always-animated collapse either way. */}
          <Panel
            id="pid"
            panelRef={pidPanelRef}
            minSize="22%"
            maxSize="65%"
            defaultSize="42%"
            className={cn("assistant-pid-panel", !isGraphOpen && "assistant-pid-panel--collapsed")}
            inert={!isGraphOpen || undefined}
          >
            <PidGraphPanel />
          </Panel>
        </>
      )}
    </Group>
  );
}
