"use client";

// PROTOTYPE variant A — "Rail + timeline". Persistent left rail with the
// three sidebar destinations and a session list; main pane is a vertical
// stepped timeline. The internal Empty/Review toggle exists only so both
// required states are visible in one variant -- not a real affordance.
import { useState } from "react";
import { MessageSquare, SlidersHorizontal, Clock, Paperclip, ArrowUp, Check, X } from "lucide-react";
import { fakeRulePacks, fakeSessions, fakeTurns } from "./fake-data";

export function VariantA() {
  const [mode, setMode] = useState<"empty" | "review">("review");
  const [selectedPack, setSelectedPack] = useState(fakeRulePacks[0].id);
  const [decided, setDecided] = useState<"pending" | "approved" | "changes">("pending");

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-64 flex-none flex-col border-r border-[var(--calm-line)] bg-white">
        <div className="px-5 py-6">
          <span className="font-[family-name:var(--calm-display-font)] text-lg italic text-[var(--calm-ink)]">
            Aperture
          </span>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          <RailItem icon={<MessageSquare size={16} />} label="Assistant" active />
          <RailItem icon={<SlidersHorizontal size={16} />} label="Rule Packs" />
          <RailItem icon={<Clock size={16} />} label="Sessions" />
        </nav>
        <div className="mt-6 flex-1 overflow-y-auto px-3">
          <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-[var(--calm-ink-muted)]">
            Recent sessions
          </p>
          {fakeSessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className="mb-1 flex w-full flex-col items-start gap-0.5 rounded-lg px-2 py-2 text-left hover:bg-[var(--calm-accent-soft)]"
            >
              <span className="text-sm text-[var(--calm-ink)]">{session.title}</span>
              <span className="flex items-center gap-1.5 text-xs text-[var(--calm-ink-muted)]">
                <StatusDot status={session.status} />
                {session.updatedAt}
              </span>
            </button>
          ))}
        </div>
      </aside>

      <main className="flex-1">
        <header className="flex items-center justify-between border-b border-[var(--calm-line)] px-8 py-4">
          <div>
            <h1 className="font-[family-name:var(--calm-display-font)] text-xl text-[var(--calm-ink)]">
              C01 Reference P&ID
            </h1>
            <p className="text-xs text-[var(--calm-ink-muted)]">C01V04-VER.EX01.xml</p>
          </div>
          <div className="flex gap-1 rounded-full border border-[var(--calm-line)] p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMode("empty")}
              className={`rounded-full px-3 py-1 ${mode === "empty" ? "bg-[var(--calm-ink)] text-white" : "text-[var(--calm-ink-muted)]"}`}
            >
              Empty state
            </button>
            <button
              type="button"
              onClick={() => setMode("review")}
              className={`rounded-full px-3 py-1 ${mode === "review" ? "bg-[var(--calm-ink)] text-white" : "text-[var(--calm-ink-muted)]"}`}
            >
              Stepped review
            </button>
          </div>
        </header>

        {mode === "empty" ? (
          <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-28 text-center">
            <h2 className="font-[family-name:var(--calm-display-font)] text-4xl leading-tight text-[var(--calm-ink)]">
              What should we check today?
            </h2>
            <p className="mt-3 text-[var(--calm-ink-muted)]">
              Drop a DEXPI file or ask a question. Pick a rule pack to ground the review.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-2">
              {fakeRulePacks.map((pack) => (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => setSelectedPack(pack.id)}
                  className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                    selectedPack === pack.id
                      ? "border-[var(--calm-accent)] bg-[var(--calm-accent-soft)] text-[var(--calm-accent)]"
                      : "border-[var(--calm-line)] text-[var(--calm-ink-muted)] hover:border-[var(--calm-ink-muted)]"
                  }`}
                >
                  {pack.name}
                </button>
              ))}
            </div>
            <div className="mt-8 flex w-full items-center gap-2 rounded-2xl border border-[var(--calm-line)] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(28,24,21,0.05),0_8px_24px_-12px_rgba(28,24,21,0.15)]">
              <Paperclip size={16} className="text-[var(--calm-ink-muted)]" />
              <input
                placeholder="Ask about this P&ID or drop a file…"
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--calm-ink-muted)]"
              />
              <button
                type="button"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--calm-accent)] text-white"
              >
                <ArrowUp size={16} />
              </button>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl px-8 py-10">
            {fakeTurns.map((turn, index) => (
              <div key={turn.id} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <span
                    className={`flex h-7 w-7 flex-none items-center justify-center rounded-full text-xs font-medium ${
                      turn.kind === "consent"
                        ? "bg-[var(--calm-accent)] text-white"
                        : "bg-[var(--calm-ink)] text-white"
                    }`}
                  >
                    {turn.step}
                  </span>
                  {index < fakeTurns.length - 1 && <span className="w-px flex-1 bg-[var(--calm-line)]" />}
                </div>
                <div className="flex-1 pb-8">
                  {turn.kind === "assistant" ? (
                    <div className="rounded-xl border border-[var(--calm-line)] bg-white p-4 shadow-[0_1px_2px_rgba(28,24,21,0.04)]">
                      <h3 className="text-sm font-medium text-[var(--calm-ink)]">{turn.title}</h3>
                      <p className="mt-1.5 text-sm text-[var(--calm-ink-muted)]">{turn.body}</p>
                      {turn.evidence && (
                        <div className="mt-2.5 flex flex-wrap gap-1.5">
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
                    <div className="rounded-xl border border-[var(--calm-accent)] bg-[var(--calm-accent-soft)] p-4 shadow-[0_4px_16px_-6px_rgba(185,84,46,0.35)]">
                      <h3 className="text-sm font-semibold text-[var(--calm-ink)]">{turn.title}</h3>
                      <p className="mt-1.5 text-sm text-[var(--calm-ink)]/80">{turn.body}</p>
                      {decided === "pending" ? (
                        <div className="mt-3 flex gap-2">
                          <button
                            type="button"
                            onClick={() => setDecided("approved")}
                            className="flex items-center gap-1.5 rounded-lg bg-[var(--calm-accent)] px-3 py-1.5 text-sm font-medium text-white"
                          >
                            <Check size={14} /> Approve
                          </button>
                          <button
                            type="button"
                            onClick={() => setDecided("changes")}
                            className="flex items-center gap-1.5 rounded-lg border border-[var(--calm-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--calm-ink)]"
                          >
                            <X size={14} /> Request changes
                          </button>
                        </div>
                      ) : (
                        <p className="mt-3 text-sm font-medium text-[var(--calm-ink)]">
                          {decided === "approved" ? "Approved — applying edit." : "Changes requested."}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function RailItem({ icon, label, active }: { icon: React.ReactNode; label: string; active?: boolean }) {
  return (
    <button
      type="button"
      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm ${
        active ? "bg-[var(--calm-accent-soft)] text-[var(--calm-accent)]" : "text-[var(--calm-ink-muted)] hover:bg-[var(--calm-paper)]"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function StatusDot({ status }: { status: "in review" | "blocked" | "approved" }) {
  const color =
    status === "blocked" ? "bg-[var(--calm-accent)]" : status === "approved" ? "bg-emerald-500" : "bg-amber-400";
  return <span className={`h-1.5 w-1.5 rounded-full ${color}`} />;
}
