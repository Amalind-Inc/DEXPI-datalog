"use client";

import { useAui } from "@assistant-ui/react";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { usePidGraph } from "@/components/pid/graph-context";
import type { RulePackRule, RulePackSummary } from "@/lib/rule-packs";
import { ruleRunResultFromApi, serializeRulePackRun } from "@/lib/rule-pack-run";

type LoadState = "idle" | "loading" | "loaded" | "error";
type RunState = "idle" | "running" | "error";

// Rule-pack picker surface (bead pydexpi-datalog-1-2ki.14): searchable list +
// restatement-first detail pane, load-on-select, and "Run all checks" as the
// primary action, posting an in-thread stepped result. Rule-pack routes
// bypass turn_lifecycle entirely, so the run POST here is followed by a
// manual aui.thread().append(...) -- the same idiom DirectionReviewCard and
// DatalogConfirmationCard use for their resumed second message.
export function RulePackPicker({ onRunPosted }: { onRunPosted: () => void }) {
  const { sessionId } = usePidGraph();
  const aui = useAui();

  const [packs, setPacks] = useState<RulePackSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedPackId, setSelectedPackId] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [runState, setRunState] = useState<RunState>("idle");
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setPacks(null);
    setListError(null);
    fetch(`/api/review/sessions/${sessionId}/rule-packs`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`Rule pack list failed (${res.status})`);
        const body = (await res.json()) as { packs?: RulePackSummary[] };
        if (!cancelled) setPacks(body.packs ?? []);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setListError(error instanceof Error ? error.message : "Rule pack list failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshToken]);

  const filteredPacks = useMemo(() => {
    if (!packs) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return packs;
    return packs.filter((pack) => pack.title.toLowerCase().includes(needle));
  }, [packs, query]);

  const selectedPack = useMemo(
    () => filteredPacks.find((pack) => pack.pack_id === selectedPackId) ?? null,
    [filteredPacks, selectedPackId],
  );

  // Load-on-select: selecting a pack in the list loads it automatically, no
  // separate Load button (per the bead's "load-on-select" language).
  useEffect(() => {
    if (!selectedPackId) return;
    let cancelled = false;
    setLoadState("loading");
    setActionError(null);
    fetch(`/api/review/sessions/${sessionId}/rule-packs/${selectedPackId}/load`, {
      method: "POST",
    })
      .then(async (res) => {
        const body = (await res.json()) as { error?: { message?: string } };
        if (!res.ok) {
          throw new Error(body?.error?.message ?? `Load failed (${res.status})`);
        }
        if (cancelled) return;
        setLoadState("loaded");
        setPacks((prev) =>
          prev?.map((pack) =>
            pack.pack_id === selectedPackId ? { ...pack, loaded: true } : pack,
          ) ?? prev,
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadState("error");
        setActionError(error instanceof Error ? error.message : "Load failed");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPackId, sessionId]);

  async function handleRunAll(pack: RulePackSummary) {
    setRunState("running");
    setActionError(null);
    try {
      const res = await fetch(`/api/review/sessions/${sessionId}/rule-packs/${pack.pack_id}/run`, {
        method: "POST",
      });
      const body = (await res.json()) as {
        results?: Record<string, unknown>[];
        error?: { message?: string };
      };
      if (!res.ok) {
        throw new Error(body?.error?.message ?? `Run failed (${res.status})`);
      }
      const ruleTitleById = new Map(pack.rules.map((rule) => [rule.rule_id, rule.title]));
      const results = (body.results ?? []).map((raw) =>
        ruleRunResultFromApi(raw, ruleTitleById.get(String(raw.rule_id)) ?? String(raw.rule_id)),
      );
      aui.thread().append({
        role: "assistant",
        content: [
          {
            type: "text",
            text: serializeRulePackRun({
              packId: pack.pack_id,
              packTitle: pack.title,
              packVersion: pack.version,
              authoritative: pack.authoritative,
              trustNotice: pack.trust_notice,
              results,
            }),
          },
        ],
      });
      setRunState("idle");
      onRunPosted();
    } catch (error) {
      setRunState("error");
      setActionError(error instanceof Error ? error.message : "Run failed");
    }
  }

  async function handleRunOne(pack: RulePackSummary, rule: RulePackRule) {
    setRunState("running");
    setActionError(null);
    try {
      const res = await fetch(`/api/review/sessions/${sessionId}/rule-pack-results`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack_id: pack.pack_id, rule_id: rule.rule_id }),
      });
      const body = (await res.json()) as Record<string, unknown> & {
        error?: { message?: string };
      };
      if (!res.ok) {
        throw new Error(body?.error?.message ?? `Run failed (${res.status})`);
      }
      aui.thread().append({
        role: "assistant",
        content: [
          {
            type: "text",
            text: serializeRulePackRun({
              packId: pack.pack_id,
              packTitle: pack.title,
              packVersion: pack.version,
              authoritative: pack.authoritative,
              trustNotice: pack.trust_notice,
              results: [ruleRunResultFromApi(body, rule.title)],
            }),
          },
        ],
      });
      setRunState("idle");
      onRunPosted();
    } catch (error) {
      setRunState("error");
      setActionError(error instanceof Error ? error.message : "Run failed");
    }
  }

  return (
    <div className="rule-pack-picker" data-testid="rule-pack-picker">
      <p className="calm-flyout-title">Rule Packs</p>

      <div className="rule-pack-search-row">
        <label className="pid-search">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Search rule packs</span>
          <input
            type="text"
            placeholder="Search rule packs…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {listError && (
        <div className="rule-pack-error" data-testid="rule-pack-list-error">
          <p>{listError}</p>
          <button type="button" onClick={() => setRefreshToken((token) => token + 1)}>
            Retry
          </button>
        </div>
      )}

      {!listError && (
        <div className="rule-pack-layout">
          <ul className="rule-pack-list" data-testid="rule-pack-list">
            {packs === null && <li className="rule-pack-list-empty">Loading…</li>}
            {packs !== null && filteredPacks.length === 0 && (
              <li className="rule-pack-list-empty">No rule packs found.</li>
            )}
            {filteredPacks.map((pack) => (
              <li key={pack.pack_id}>
                <button
                  type="button"
                  data-testid="rule-pack-list-item"
                  data-pack-id={pack.pack_id}
                  aria-pressed={selectedPackId === pack.pack_id}
                  className={cn(
                    "rule-pack-list-item",
                    selectedPackId === pack.pack_id && "active",
                  )}
                  onClick={() => setSelectedPackId(pack.pack_id)}
                >
                  <span className="rule-pack-list-item-title">{pack.title}</span>
                  {pack.loaded && <span className="rule-pack-loaded-badge">Loaded</span>}
                </button>
              </li>
            ))}
          </ul>

          <div className="rule-pack-detail" data-testid="rule-pack-detail">
            {selectedPack ? (
              <RulePackDetail
                pack={selectedPack}
                loadState={loadState}
                runState={runState}
                actionError={actionError}
                onRunAll={() => handleRunAll(selectedPack)}
                onRunOne={(rule) => handleRunOne(selectedPack, rule)}
              />
            ) : (
              <p className="rule-pack-empty-state">Select a rule pack to see details.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function RulePackDetail({
  pack,
  loadState,
  runState,
  actionError,
  onRunAll,
  onRunOne,
}: {
  pack: RulePackSummary;
  loadState: LoadState;
  runState: RunState;
  actionError: string | null;
  onRunAll: () => void;
  onRunOne: (rule: RulePackRule) => void;
}) {
  const loadStatusText =
    loadState === "loading" ? "Loading…" : pack.loaded ? "Loaded" : loadState === "error" ? "Load failed" : null;

  return (
    <div className="rule-pack-detail-content">
      <header className="rule-pack-detail-header">
        <div>
          <h3>{pack.title}</h3>
          <p className="rule-pack-detail-version">Version {pack.version}</p>
        </div>
        {pack.authoritative && <span className="rule-pack-badge">Authoritative</span>}
      </header>
      {loadStatusText && (
        <p className="rule-pack-load-status" data-testid="rule-pack-load-status">
          {loadStatusText}
        </p>
      )}
      <p className="rule-pack-trust-notice">{pack.trust_notice}</p>

      {(pack.advisory_guidance?.length ?? 0) > 0 && (
        <section data-testid="rule-pack-picker-advisory">
          <p className="rule-pack-rule-title">Advisory guidance</p>
          {pack.advisory_guidance.map((section, index) => (
            <div key={`${section.title}-${index}`} className="rule-pack-rule">
              {section.title ? (
                <p className="rule-pack-rule-title">{section.title}</p>
              ) : null}
              <p data-testid="rule-pack-advisory-body">{section.body}</p>
            </div>
          ))}
        </section>
      )}

      {pack.rules.length === 0 && (
        <p className="shell-page-empty" data-testid="rule-pack-picker-no-rules">
          No executable rules in this pack.
        </p>
      )}

      {pack.rules.map((rule) => (
        <div key={rule.rule_id} className="rule-pack-rule">
          <p className="rule-pack-rule-title">{rule.title}</p>
          <p data-testid="rule-restatement">{rule.restatement.plain_language_meaning}</p>
          <details data-testid="rule-logic-disclosure">
            <summary>{rule.executable_logic.disclosure || "Executable logic"}</summary>
            <pre className="datalog-syntax">
              <code>{rule.executable_logic.content}</code>
            </pre>
          </details>
          <button
            type="button"
            data-testid="rule-pack-run-one-button"
            disabled={runState === "running"}
            onClick={() => onRunOne(rule)}
          >
            Run this check
          </button>
        </div>
      ))}

      {actionError && (
        <p className="rule-pack-action-error" data-testid="rule-pack-action-error">
          {actionError}
        </p>
      )}

      <div className="rule-pack-actions">
        <button
          type="button"
          data-testid="rule-pack-run-all-button"
          className="rule-pack-run-all-button"
          disabled={runState === "running"}
          onClick={onRunAll}
        >
          {runState === "running" ? "Running…" : "Run all checks"}
        </button>
      </div>
    </div>
  );
}
