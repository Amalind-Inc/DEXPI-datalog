"use client";

import { ChevronDown, History, PanelLeftClose, Plus } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const threads = [
  { id: "thread-current", title: "Current P&ID QA", meta: "P-101 discharge review" },
  { id: "thread-cooling", title: "Cooling loop checks", meta: "saved locally" },
  { id: "thread-instruments", title: "Instrument evidence", meta: "sample thread" },
];

type Props = {
  peeking: boolean;
  onToggleCollapse: () => void;
  onPeekEnter: () => void;
  onPeekLeave: () => void;
};

export function ConversationSidebar({
  peeking,
  onToggleCollapse,
  onPeekEnter,
  onPeekLeave,
}: Props) {
  const [showRecent, setShowRecent] = useState(true);

  return (
    <aside
      className={cn("conversation-sidebar", peeking && "peeking")}
      aria-label="Conversations"
      onMouseEnter={onPeekEnter}
      onMouseLeave={onPeekLeave}
    >
      <header>
        <button
          type="button"
          className="sidebar-collapse-btn"
          aria-label="Collapse sidebar"
          data-testid="collapse-sidebar"
          onClick={onToggleCollapse}
        >
          <PanelLeftClose size={17} aria-hidden="true" />
        </button>
        <button type="button" className="sidebar-newchat-btn" aria-label="New chat">
          <Plus size={16} aria-hidden="true" />
        </button>
      </header>

      <div className="sidebar-section">
        <button
          type="button"
          className="sidebar-section-toggle"
          aria-expanded={showRecent}
          onClick={() => setShowRecent((value) => !value)}
        >
          <span>Recent Chats</span>
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={cn("sidebar-chevron", !showRecent && "collapsed")}
          />
        </button>
        {showRecent && (
          <nav aria-label="Thread history">
            {threads.map((thread) => (
              <button
                className={thread.id === "thread-current" ? "active" : ""}
                key={thread.id}
                type="button"
              >
                <History size={15} aria-hidden="true" />
                <span>
                  <strong>{thread.title}</strong>
                  <small>{thread.meta}</small>
                </span>
              </button>
            ))}
          </nav>
        )}
      </div>

      <footer>
        Thread messages are persisted in browser storage through the runtime
        history adapter for this local prototype.
      </footer>
    </aside>
  );
}
