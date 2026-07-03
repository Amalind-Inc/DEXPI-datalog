"use client";

// PROTOTYPE variant B — "Hero-first, minimal chrome". Icon-only rail;
// Sessions opens as a flyout instead of living permanently on screen. Empty
// state fills the viewport like a landing page. Turns render as full-width
// cards with generous whitespace, no timeline rail.
import { useState } from "react";
import { MessageSquare, SlidersHorizontal, Clock, Paperclip, ArrowUp, Check, X, ChevronDown, Download } from "lucide-react";
import { SchematicSceneView } from "@/components/pid/schematic-scene-view";
import { fakeRulePacks, fakeSessions, fakeTurns } from "./fake-data";
import { fakePidScene } from "./fake-pid-scene";

export function VariantB() {
  const [mode, setMode] = useState<"empty" | "review">("empty");
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [packOpen, setPackOpen] = useState(false);
  const [selectedPack, setSelectedPack] = useState(fakeRulePacks[0]);
  const [decided, setDecided] = useState<"pending" | "approved" | "changes">("pending");
  const [activeTurnId, setActiveTurnId] = useState(fakeTurns[fakeTurns.length - 1].id);
  const activeTurn = fakeTurns.find((turn) => turn.id === activeTurnId);
  const highlightedIds = activeTurn?.evidence ?? [];

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-14 flex-none flex-col items-center gap-1 border-r border-[var(--calm-line)] bg-white py-5">
        <span className="mb-4 font-[family-name:var(--calm-display-font)] text-lg italic">A</span>
        <IconRailButton icon={<MessageSquare size={17} />} label="Assistant" active />
        <IconRailButton icon={<SlidersHorizontal size={17} />} label="Rule Packs" />
        <IconRailButton
          icon={<Clock size={17} />}
          label="Sessions"
          onClick={() => setSessionsOpen((value) => !value)}
        />
        <div className="mt-auto text-[10px] font-medium tracking-wide text-[var(--calm-ink-muted)]">
          Empty / Review
        </div>
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setMode("empty")}
            className={`h-6 w-6 rounded-full text-[10px] ${mode === "empty" ? "bg-[var(--calm-ink)] text-white" : "border border-[var(--calm-line)] text-[var(--calm-ink-muted)]"}`}
          >
            E
          </button>
          <button
            type="button"
            onClick={() => setMode("review")}
            className={`h-6 w-6 rounded-full text-[10px] ${mode === "review" ? "bg-[var(--calm-ink)] text-white" : "border border-[var(--calm-line)] text-[var(--calm-ink-muted)]"}`}
          >
            R
          </button>
        </div>
      </aside>

      {sessionsOpen && (
        <div className="fixed inset-y-0 left-14 z-40 w-72 border-r border-[var(--calm-line)] bg-white p-5 shadow-[8px_0_30px_-12px_rgba(28,24,21,0.2)]">
          <p className="mb-3 text-[11px] font-medium uppercase tracking-wider text-[var(--calm-ink-muted)]">
            Sessions
          </p>
          {fakeSessions.map((session) => (
            <div key={session.id} className="mb-1 rounded-lg px-2 py-2 hover:bg-[var(--calm-paper)]">
              <p className="text-sm text-[var(--calm-ink)]">{session.title}</p>
              <p className="text-xs text-[var(--calm-ink-muted)]">
                {session.status} · {session.updatedAt}
              </p>
            </div>
          ))}
        </div>
      )}

      <main className="relative flex-1">
        {mode === "empty" ? (
          <div className="flex min-h-screen flex-col items-center justify-center px-6">
            <h2 className="max-w-2xl text-center font-[family-name:var(--calm-display-font)] text-5xl leading-[1.1] text-[var(--calm-ink)]">
              Review a P&ID with a second pair of eyes.
            </h2>
            <div className="relative mt-10 w-full max-w-2xl">
              <div className="flex items-center gap-2 rounded-2xl border border-[var(--calm-line)] bg-white px-5 py-4 shadow-[0_1px_2px_rgba(28,24,21,0.05),0_20px_40px_-20px_rgba(28,24,21,0.25)]">
                <Paperclip size={17} className="text-[var(--calm-ink-muted)]" />
                <input
                  placeholder="Ask about this P&ID or drop a file…"
                  className="flex-1 bg-transparent text-base outline-none placeholder:text-[var(--calm-ink-muted)]"
                />
                <button
                  type="button"
                  onClick={() => setPackOpen((value) => !value)}
                  className="flex items-center gap-1 rounded-full border border-[var(--calm-line)] px-3 py-1.5 text-xs text-[var(--calm-ink-muted)]"
                >
                  {selectedPack.name}
                  <ChevronDown size={12} />
                </button>
                <button
                  type="button"
                  className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-[var(--calm-accent)] text-white"
                >
                  <ArrowUp size={17} />
                </button>
              </div>
              {packOpen && (
                <div className="absolute right-0 top-full z-10 mt-2 w-72 rounded-xl border border-[var(--calm-line)] bg-white p-1.5 shadow-[0_12px_32px_-8px_rgba(28,24,21,0.25)]">
                  {fakeRulePacks.map((pack) => (
                    <button
                      key={pack.id}
                      type="button"
                      onClick={() => {
                        setSelectedPack(pack);
                        setPackOpen(false);
                      }}
                      className="flex w-full flex-col items-start rounded-lg px-3 py-2 text-left hover:bg-[var(--calm-paper)]"
                    >
                      <span className="text-sm text-[var(--calm-ink)]">{pack.name}</span>
                      <span className="text-xs text-[var(--calm-ink-muted)]">
                        {pack.ruleCount} rules · {pack.tag}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-screen">
            <div className="flex-1 overflow-y-auto px-8 py-10">
              {fakeTurns.map((turn) => {
                const isActive = turn.id === activeTurnId;
                return (
                  // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
                  <div
                    key={turn.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setActiveTurnId(turn.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setActiveTurnId(turn.id);
                    }}
                    className="mb-6 block w-full cursor-pointer text-left"
                  >
                    <p className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--calm-ink-muted)]">
                      Step {turn.step} of {fakeTurns.length}
                    </p>
                    {turn.kind === "assistant" ? (
                      <div
                        className={`rounded-2xl border bg-white p-6 shadow-[0_1px_2px_rgba(28,24,21,0.04),0_12px_28px_-16px_rgba(28,24,21,0.15)] ${
                          isActive ? "border-[var(--calm-accent)] ring-1 ring-[var(--calm-accent)]" : "border-[var(--calm-line)]"
                        }`}
                      >
                        <h3 className="font-[family-name:var(--calm-display-font)] text-lg text-[var(--calm-ink)]">
                          {turn.title}
                        </h3>
                        <p className="mt-2 text-sm text-[var(--calm-ink-muted)]">{turn.body}</p>
                        {turn.evidence && (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {turn.evidence.map((tag) => (
                              <span
                                key={tag}
                                className="rounded-md bg-[var(--calm-paper)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--calm-ink-muted)]"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div
                        className={`flex overflow-hidden rounded-2xl border bg-white shadow-[0_1px_2px_rgba(28,24,21,0.04),0_16px_36px_-16px_rgba(185,84,46,0.35)] ${
                          isActive ? "border-[var(--calm-accent)] ring-1 ring-[var(--calm-accent)]" : "border-[var(--calm-line)]"
                        }`}
                      >
                        <div className="w-1.5 flex-none bg-[var(--calm-accent)]" />
                        <div className="flex-1 p-6">
                          <h3 className="font-[family-name:var(--calm-display-font)] text-lg text-[var(--calm-ink)]">
                            {turn.title}
                          </h3>
                          <p className="mt-2 text-sm text-[var(--calm-ink-muted)]">{turn.body}</p>
                          {decided === "pending" ? (
                            <div className="mt-4 flex gap-2">
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setDecided("approved");
                                }}
                                className="flex items-center gap-1.5 rounded-lg bg-[var(--calm-accent)] px-3.5 py-2 text-sm font-medium text-white"
                              >
                                <Check size={14} /> Approve
                              </button>
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setDecided("changes");
                                }}
                                className="flex items-center gap-1.5 rounded-lg border border-[var(--calm-line)] px-3.5 py-2 text-sm font-medium text-[var(--calm-ink)]"
                              >
                                <X size={14} /> Request changes
                              </button>
                            </div>
                          ) : (
                            <p className="mt-4 text-sm font-medium text-[var(--calm-ink)]">
                              {decided === "approved" ? "Approved — applying edit." : "Changes requested."}
                            </p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex w-[440px] flex-none flex-col border-l border-[var(--calm-line)] bg-[var(--calm-paper)] p-4">
              <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--calm-line)] bg-white shadow-[0_1px_2px_rgba(28,24,21,0.05),0_16px_36px_-20px_rgba(28,24,21,0.2)]">
                <div className="flex items-center justify-between border-b border-[var(--calm-line)] px-4 py-3">
                  <span className="truncate text-sm text-[var(--calm-ink)]">C01V04-VER.EX01.xml</span>
                  <Download size={15} className="flex-none text-[var(--calm-ink-muted)]" />
                </div>
                <div className="pid-schematic-wrap flex-1 bg-[var(--calm-paper)]">
                  <SchematicSceneView
                    scene={fakePidScene}
                    selectedId={null}
                    highlightedIds={highlightedIds}
                    onSelect={() => {}}
                  />
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function IconRailButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`flex h-9 w-9 items-center justify-center rounded-lg ${
        active ? "bg-[var(--calm-accent-soft)] text-[var(--calm-accent)]" : "text-[var(--calm-ink-muted)] hover:bg-[var(--calm-paper)]"
      }`}
    >
      {icon}
    </button>
  );
}
