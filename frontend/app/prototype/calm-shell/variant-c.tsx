"use client";

// PROTOTYPE variant C — "Split workspace". Sidebar is a single tabbed panel
// (Assistant / Rule Packs / Sessions share one region instead of stacking).
// Stepped review is a paged stepper -- one step visible at a time behind a
// dot rail -- rather than an always-visible feed (contrast with A and B).
import { useState } from "react";
import { MessageSquare, SlidersHorizontal, Clock, Paperclip, ArrowUp, Check, X } from "lucide-react";
import { fakeRulePacks, fakeSessions, fakeTurns } from "./fake-data";

type Tab = "assistant" | "packs" | "sessions";

export function VariantC() {
  const [mode, setMode] = useState<"empty" | "review">("empty");
  const [tab, setTab] = useState<Tab>("assistant");
  const [selectedPack, setSelectedPack] = useState(fakeRulePacks[0].id);
  const [activeStep, setActiveStep] = useState(1);
  const [decided, setDecided] = useState<"pending" | "approved" | "changes">("pending");

  const currentTurn = fakeTurns.find((turn) => turn.step === activeStep) ?? fakeTurns[0];

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-72 flex-none flex-col border-r border-[var(--calm-line)] bg-white">
        <div className="flex items-center justify-between px-5 py-6">
          <span className="font-[family-name:var(--calm-display-font)] text-lg italic text-[var(--calm-ink)]">
            Aperture
          </span>
          <div className="flex gap-1 rounded-full border border-[var(--calm-line)] p-0.5 text-[10px]">
            <button
              type="button"
              onClick={() => setMode("empty")}
              className={`rounded-full px-2 py-0.5 ${mode === "empty" ? "bg-[var(--calm-ink)] text-white" : "text-[var(--calm-ink-muted)]"}`}
            >
              Empty
            </button>
            <button
              type="button"
              onClick={() => setMode("review")}
              className={`rounded-full px-2 py-0.5 ${mode === "review" ? "bg-[var(--calm-ink)] text-white" : "text-[var(--calm-ink-muted)]"}`}
            >
              Review
            </button>
          </div>
        </div>

        <div className="flex border-b border-[var(--calm-line)] px-3">
          <TabButton icon={<MessageSquare size={14} />} label="Assistant" active={tab === "assistant"} onClick={() => setTab("assistant")} />
          <TabButton icon={<SlidersHorizontal size={14} />} label="Rule Packs" active={tab === "packs"} onClick={() => setTab("packs")} />
          <TabButton icon={<Clock size={14} />} label="Sessions" active={tab === "sessions"} onClick={() => setTab("sessions")} />
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === "assistant" && (
            <p className="text-sm text-[var(--calm-ink-muted)]">
              Reviewing <span className="text-[var(--calm-ink)]">C01V04-VER.EX01.xml</span> against{" "}
              <span className="text-[var(--calm-ink)]">DEXPI Core</span>. 3 steps completed, 1 awaiting your review.
            </p>
          )}
          {tab === "packs" && (
            <div className="flex flex-col gap-2">
              {fakeRulePacks.map((pack) => (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => setSelectedPack(pack.id)}
                  className={`rounded-xl border p-3 text-left ${
                    selectedPack === pack.id ? "border-[var(--calm-accent)] bg-[var(--calm-accent-soft)]" : "border-[var(--calm-line)]"
                  }`}
                >
                  <p className="text-sm font-medium text-[var(--calm-ink)]">{pack.name}</p>
                  <p className="mt-0.5 text-xs text-[var(--calm-ink-muted)]">{pack.description}</p>
                  <p className="mt-1 text-[11px] text-[var(--calm-ink-muted)]">{pack.ruleCount} rules</p>
                </button>
              ))}
            </div>
          )}
          {tab === "sessions" && (
            <div className="flex flex-col gap-1">
              {fakeSessions.map((session) => (
                <div key={session.id} className="rounded-lg px-2 py-2 hover:bg-[var(--calm-paper)]">
                  <p className="text-sm text-[var(--calm-ink)]">{session.title}</p>
                  <p className="text-xs text-[var(--calm-ink-muted)]">
                    {session.status} · {session.updatedAt}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>

      <main className="flex-1">
        {mode === "empty" ? (
          <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-28 text-center">
            <div className="mb-6 flex rounded-full border border-[var(--calm-line)] p-1 text-sm">
              {fakeRulePacks.map((pack) => (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => setSelectedPack(pack.id)}
                  className={`rounded-full px-3.5 py-1.5 ${
                    selectedPack === pack.id ? "bg-[var(--calm-ink)] text-white" : "text-[var(--calm-ink-muted)]"
                  }`}
                >
                  {pack.name}
                </button>
              ))}
            </div>
            <h2 className="font-[family-name:var(--calm-display-font)] text-4xl leading-tight text-[var(--calm-ink)]">
              Let's review this P&ID together.
            </h2>
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
          <div className="flex h-full">
            <div className="flex w-20 flex-none flex-col items-center gap-4 border-r border-[var(--calm-line)] py-10">
              {fakeTurns.map((turn) => (
                <button
                  key={turn.id}
                  type="button"
                  onClick={() => setActiveStep(turn.step)}
                  className="flex flex-col items-center gap-1.5"
                >
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-medium ${
                      activeStep === turn.step
                        ? turn.kind === "consent"
                          ? "bg-[var(--calm-accent)] text-white"
                          : "bg-[var(--calm-ink)] text-white"
                        : "border border-[var(--calm-line)] text-[var(--calm-ink-muted)]"
                    }`}
                  >
                    {turn.step}
                  </span>
                </button>
              ))}
            </div>

            <div className="mx-auto max-w-xl flex-1 px-8 py-16">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--calm-ink-muted)]">
                Step {currentTurn.step} of {fakeTurns.length}
              </p>
              {currentTurn.kind === "assistant" ? (
                <div>
                  <h3 className="font-[family-name:var(--calm-display-font)] text-2xl text-[var(--calm-ink)]">
                    {currentTurn.title}
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-[var(--calm-ink-muted)]">{currentTurn.body}</p>
                  {currentTurn.evidence && (
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {currentTurn.evidence.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-md bg-[var(--calm-paper)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--calm-ink-muted)]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => setActiveStep(Math.min(fakeTurns.length, activeStep + 1))}
                    className="mt-8 rounded-lg bg-[var(--calm-ink)] px-4 py-2 text-sm font-medium text-white"
                  >
                    Next step
                  </button>
                </div>
              ) : (
                <div className="rounded-2xl border border-[var(--calm-accent)] bg-[var(--calm-accent-soft)] p-6 shadow-[0_8px_28px_-14px_rgba(185,84,46,0.4)]">
                  <h3 className="font-[family-name:var(--calm-display-font)] text-xl text-[var(--calm-ink)]">
                    {currentTurn.title}
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-[var(--calm-ink)]/80">{currentTurn.body}</p>
                  {decided === "pending" ? (
                    <div className="mt-5 flex gap-2">
                      <button
                        type="button"
                        onClick={() => setDecided("approved")}
                        className="flex items-center gap-1.5 rounded-lg bg-[var(--calm-accent)] px-4 py-2 text-sm font-medium text-white"
                      >
                        <Check size={14} /> Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => setDecided("changes")}
                        className="flex items-center gap-1.5 rounded-lg border border-[var(--calm-line)] bg-white px-4 py-2 text-sm font-medium text-[var(--calm-ink)]"
                      >
                        <X size={14} /> Request changes
                      </button>
                    </div>
                  ) : (
                    <p className="mt-5 text-sm font-medium text-[var(--calm-ink)]">
                      {decided === "approved" ? "Approved — applying edit." : "Changes requested."}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function TabButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex flex-1 flex-col items-center gap-1 border-b-2 py-2.5 text-[10px] ${
        active ? "border-[var(--calm-accent)] text-[var(--calm-accent)]" : "border-transparent text-[var(--calm-ink-muted)]"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
