"use client";

import { Thread } from "@/components/assistant-ui/thread";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";
import { PidAssistantProviders } from "@/components/chat/pid-runtime-provider";
import { PidGraphPanel } from "@/components/pid/graph-panel";

export const Assistant = () => {
  return (
    <PidAssistantProviders>
      <main className="pid-app-shell">
        <ConversationSidebar />
        <section className="chat-column" aria-label="Chat">
          <Thread />
        </section>
        <PidGraphPanel />
      </main>
    </PidAssistantProviders>
  );
};
