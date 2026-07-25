"use client";

import { PanelLeftOpen } from "lucide-react";
import { type ReactNode, useState } from "react";
import { AppSidebar } from "@/components/chat/app-sidebar";
import { PidAssistantProviders } from "@/components/chat/pid-runtime-provider";

// Desktop collapse fully hides the sidebar rather than shrinking it to an
// icon rail (that shrink is a narrow-viewport-only fallback, handled purely
// in CSS) -- see ADR 0006.
export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <PidAssistantProviders>
      <div className="pid-app-shell">
        <AppSidebar collapsed={collapsed} onCollapsedChange={setCollapsed} />
        {collapsed && (
          <button
            type="button"
            aria-label="Show sidebar"
            title="Show sidebar"
            onClick={() => setCollapsed(false)}
            className="app-shell-reopen-btn"
          >
            <PanelLeftOpen size={15} />
          </button>
        )}
        <main className="app-shell-main">{children}</main>
      </div>
    </PidAssistantProviders>
  );
}
