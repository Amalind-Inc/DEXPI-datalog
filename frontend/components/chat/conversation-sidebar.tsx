"use client";

import { History, Plus } from "lucide-react";

const threads = [
  { id: "thread-current", title: "Current P&ID QA", meta: "P-101 discharge review" },
  { id: "thread-cooling", title: "Cooling loop checks", meta: "saved locally" },
  { id: "thread-instruments", title: "Instrument evidence", meta: "sample thread" },
];

export function ConversationSidebar() {
  return (
    <aside className="conversation-sidebar" aria-label="Conversations">
      <header>
        <div>
          <p className="pid-eyebrow">Conversations</p>
          <h2>P&ID QA</h2>
        </div>
        <button type="button" aria-label="New chat">
          <Plus size={16} aria-hidden="true" />
        </button>
      </header>
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
      <footer>
        Thread messages are persisted in browser storage through the runtime
        history adapter for this local prototype.
      </footer>
    </aside>
  );
}
