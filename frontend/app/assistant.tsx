"use client";

import { PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { useState } from "react";
import { Thread } from "@/components/assistant-ui/thread";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";
import { PidAssistantProviders } from "@/components/chat/pid-runtime-provider";
import { PidGraphPanel } from "@/components/pid/graph-panel";
import { usePidGraph } from "@/components/pid/graph-context";
import { cn } from "@/lib/utils";

function AssistantShell() {
  const { loadedFileName, isGraphOpen, setGraphOpen } = usePidGraph();
  const hasPid = loadedFileName !== null;
  const showGraph = hasPid && isGraphOpen;

  const [collapsed, setCollapsed] = useState(false);
  const [peeking, setPeeking] = useState(false);

  return (
    <main
      className={cn(
        "pid-app-shell",
        showGraph && "with-graph",
        collapsed && "sidebar-collapsed",
      )}
    >
      {/* Spacer occupies the sidebar's animated grid track; the fixed sidebar
          panel is layered over it (see .sidebar-spacer / .conversation-sidebar). */}
      <div className="sidebar-spacer" aria-hidden="true" />

      {/* Collapsed: a thin left-edge strip reveals the sidebar on hover. */}
      {collapsed && (
        <div
          className="sidebar-hover-zone"
          data-testid="sidebar-hover-zone"
          aria-hidden="true"
          onMouseEnter={() => setPeeking(true)}
        />
      )}
      {collapsed && !peeking && (
        <button
          type="button"
          className="sidebar-expand-btn"
          aria-label="Expand sidebar"
          data-testid="expand-sidebar"
          onClick={() => setCollapsed(false)}
        >
          <PanelLeftOpen size={18} aria-hidden="true" />
        </button>
      )}

      <ConversationSidebar
        peeking={peeking}
        onToggleCollapse={() => {
          setCollapsed((value) => !value);
          setPeeking(false);
        }}
        onPeekEnter={() => collapsed && setPeeking(true)}
        onPeekLeave={() => setPeeking(false)}
      />

      <section className="chat-column" aria-label="Chat">
        {hasPid && !isGraphOpen && (
          <div className="chat-column-bar">
            <button
              type="button"
              className="reopen-graph-btn"
              data-testid="reopen-graph"
              onClick={() => setGraphOpen(true)}
            >
              <PanelRightOpen size={15} aria-hidden="true" />
              <span>View topology · {loadedFileName}</span>
            </button>
          </div>
        )}
        <Thread />
      </section>

      {showGraph && <PidGraphPanel />}
    </main>
  );
}

export const Assistant = () => {
  return (
    <PidAssistantProviders>
      <AssistantShell />
    </PidAssistantProviders>
  );
};
