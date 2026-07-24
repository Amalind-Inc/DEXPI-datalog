"use client";

import {
  ChevronRight,
  FolderKanban,
  KeyRound,
  Layers,
  MessageSquare,
  PanelLeftClose,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import {
  DEFAULT_WIDTH,
  MAX_WIDTH,
  MIN_WIDTH,
  WIDTH_STORAGE_KEY,
} from "@/components/chat/app-sidebar-constants";
import { startNewSession } from "@/components/chat/pid-runtime-provider";
import { usePidGraph } from "@/components/pid/graph-context";

const NAV_ITEMS = [
  { href: "/assistant", label: "Assistant", icon: MessageSquare },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/rule-packs", label: "Rule Packs", icon: Layers },
] as const;

const SNAP_ANIMATION_MS = 300;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidth(): number {
  if (typeof window === "undefined") return DEFAULT_WIDTH;
  const raw = window.localStorage.getItem(WIDTH_STORAGE_KEY);
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? clamp(parsed, MIN_WIDTH, MAX_WIDTH) : DEFAULT_WIDTH;
}

// Keeps the CSS var in sync so the resting width survives across client
// navigations without needing an inline `style` attribute (which would
// mismatch between SSR's default and the client's persisted value).
function applyWidthVar(w: number) {
  if (typeof document !== "undefined") {
    document.documentElement.style.setProperty("--app-sidebar-width", `${w}px`);
  }
}

export function AppSidebar({
  collapsed,
  onCollapsedChange,
}: {
  collapsed: boolean;
  onCollapsedChange: (next: boolean) => void;
}) {
  const pathname = usePathname();
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  // While dragging, per-pixel width tracking is instant (no transition) so it
  // doesn't lag the cursor; a threshold crossing (collapse/reopen) briefly
  // re-enables the transition so that specific snap eases smoothly instead
  // of jumping, mid-gesture -- matching the reference app's feel.
  const [isSnapping, setIsSnapping] = useState(false);
  const snapTimeoutRef = useRef<number | undefined>(undefined);
  const dragRef = useRef<{ startX: number; restWidth: number; startedCollapsed: boolean } | null>(
    null,
  );

  // A blocking inline script (app/(shell)/layout.tsx) already set the
  // --app-sidebar-width CSS var before the browser's first paint, so there's
  // no flash to fix here -- this just syncs React's own numeric width state
  // (needed for drag-resize math) to match what's already on screen.
  useLayoutEffect(() => {
    const stored = readStoredWidth();
    setWidth(stored);
    applyWidthVar(stored);
  }, []);

  useEffect(() => {
    return () => window.clearTimeout(snapTimeoutRef.current);
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { startX: event.clientX, restWidth: width, startedCollapsed: collapsed };
    setIsDragging(true);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const triggerSnap = (nextCollapsed: boolean) => {
    onCollapsedChange(nextCollapsed);
    setIsSnapping(true);
    window.clearTimeout(snapTimeoutRef.current);
    snapTimeoutRef.current = window.setTimeout(() => setIsSnapping(false), SNAP_ANIMATION_MS);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const { startX, restWidth, startedCollapsed } = dragRef.current;
    const delta = event.clientX - startX;
    // Reopening drags start from the collapsed (0-width) edge, so the
    // candidate width is the raw drag distance rather than restWidth+delta.
    const candidate = startedCollapsed ? delta : restWidth + delta;
    const threshold = restWidth * 0.5;

    if (!collapsed && candidate < threshold) {
      triggerSnap(true);
      return;
    }
    if (collapsed && candidate >= threshold) {
      triggerSnap(false);
      return;
    }
    if (!collapsed) {
      const next = clamp(candidate, MIN_WIDTH, MAX_WIDTH);
      setWidth(next);
      applyWidthVar(next);
    }
  };

  const endDrag = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setIsDragging(false);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    if (!collapsed) {
      window.localStorage.setItem(WIDTH_STORAGE_KEY, String(width));
    }
  };

  return (
    <>
      <aside
        className={cn(
          "app-sidebar",
          collapsed && "app-sidebar--collapsed",
          isDragging && !isSnapping && "app-sidebar--dragging",
        )}
        aria-label="Sidebar navigation"
        aria-hidden={collapsed}
        inert={collapsed || undefined}
      >
        <div className="app-sidebar-header">
          <span className="calm-rail-mark" aria-hidden="true">
            A
          </span>
          <button
            type="button"
            aria-label="Hide sidebar"
            title="Hide sidebar"
            onClick={() => onCollapsedChange(true)}
            className="app-sidebar-collapse-btn"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>

        <button
          type="button"
          aria-label="New chat"
          title="New chat"
          className="app-sidebar-item app-sidebar-new-chat"
          onClick={startNewSession}
        >
          <Plus size={15} aria-hidden="true" />
          <span className="app-sidebar-label">New chat</span>
        </button>

        <div className="calm-rail-divider" aria-hidden="true" />

        <nav className="app-sidebar-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <SidebarLink key={item.href} {...item} active={pathname === item.href} />
          ))}
        </nav>

        <div className="app-sidebar-sections">
          <RecentProjectsSection />
          <AssistantHistorySection />
        </div>

        {/* Account settings sit at the foot of the rail rather than in the
          primary nav: BYOK key management is configuration you visit once,
          not a place you work (bead pydexpi-datalog-1-37e2). */}
        <div className="app-sidebar-footer">
          <div className="calm-rail-divider" aria-hidden="true" />
          <SidebarLink
            href="/account/api-keys"
            label="API keys"
            icon={KeyRound}
            active={pathname === "/account/api-keys"}
          />
        </div>
      </aside>
      <div
        className={cn(
          "app-sidebar-resize-handle",
          isDragging && "app-sidebar-resize-handle--active",
        )}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      />
    </>
  );
}

function SidebarLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: typeof MessageSquare;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      aria-current={active ? "page" : undefined}
      className={cn("app-sidebar-item", active && "active")}
    >
      <Icon size={15} aria-hidden="true" />
      <span className="app-sidebar-label">{label}</span>
    </Link>
  );
}

function AccordionSection({
  title,
  open,
  onToggle,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="app-sidebar-section">
      <button
        type="button"
        className="app-sidebar-section-header"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span>{title}</span>
        <ChevronRight
          size={14}
          aria-hidden="true"
          className={cn("app-sidebar-section-chevron", open && "app-sidebar-section-chevron--open")}
        />
      </button>
      <div className={cn("app-sidebar-section-panel", open && "app-sidebar-section-panel--open")}>
        <div className="app-sidebar-section-panel-inner">{children}</div>
      </div>
    </div>
  );
}

// Projects don't exist as an entity yet (bead 2c5.5 builds the model + pages);
// this section is the accordion shell ready for that data, per the user's
// synara/MikeOSS-style nav reference.
function RecentProjectsSection() {
  const [open, setOpen] = useState(false);
  return (
    <AccordionSection title="Recent Projects" open={open} onToggle={() => setOpen((v) => !v)}>
      <p className="app-sidebar-section-empty">No projects yet</p>
    </AccordionSection>
  );
}

// Replaces the old flat "Sessions" nav item -- per ADR 0006, recent sessions
// become reachable via an expanded nav tree rather than a standalone
// destination. Multi-chat history doesn't exist yet (bead 2yr/2c5.5), so this
// reflects only the single active session for now.
function AssistantHistorySection() {
  const { loadedFileName } = usePidGraph();
  const [open, setOpen] = useState(false);
  const entries = loadedFileName ? [{ id: "current", title: loadedFileName }] : [];

  return (
    <AccordionSection title="Assistant History" open={open} onToggle={() => setOpen((v) => !v)}>
      {entries.length === 0 ? (
        <p className="app-sidebar-section-empty">No past chats yet</p>
      ) : (
        entries.map((entry) => (
          <Link key={entry.id} href="/assistant" className="app-sidebar-history-row">
            {entry.title}
          </Link>
        ))
      )}
    </AccordionSection>
  );
}
