"use client";

import { useEffect } from "react";
import { usePidGraph } from "@/components/pid/graph-context";
import type { RuleEvidenceHighlight, RuleOutcome, RulePackRunState } from "@/lib/rule-pack-run";

const OUTCOME_GLYPH: Record<RuleOutcome, string> = {
  satisfied: "✓",
  violated: "✕",
  indeterminate: "●",
};

const OUTCOME_LABEL: Record<RuleOutcome, string> = {
  satisfied: "Satisfied",
  violated: "Violated",
  indeterminate: "Indeterminate",
};

function hasEvidence(highlight: RuleEvidenceHighlight): boolean {
  return (
    highlight.source_scope_ids.length > 0 ||
    highlight.matched_object_ids.length > 0 ||
    highlight.paths.length > 0
  );
}

// In-thread rule-pack run result (bead pydexpi-datalog-1-2ki.14). Not wrapped
// in SteppedTurnCard: that wrapper only puts a body under the LAST step,
// whereas every rule here needs its own body (summary + evidence chips), and
// glyphs are keyed by rule outcome, not turn-lifecycle TurnStepStatus. Builds
// the same .calm-step-card/-list/-row DOM directly instead.
export function RulePackRunCard({ state }: { state: RulePackRunState }) {
  const { setHighlightedNodeIds, setGraphOpen } = usePidGraph();
  const anyEvidence = state.results.some((result) => hasEvidence(result.evidenceHighlight));

  useEffect(() => {
    if (anyEvidence) setGraphOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="calm-step-card rule-pack-run-card" data-testid="rule-pack-run-card">
      <header className="rule-pack-run-header">
        <p className="pid-eyebrow">{state.packTitle} — Run all checks</p>
        {state.authoritative && <span className="rule-pack-badge">Authoritative</span>}
      </header>
      <ol className="calm-step-list" data-testid="rule-run-step-list">
        {state.results.map((result) => (
          <li
            key={result.ruleId}
            className="calm-step-row"
            data-testid="rule-run-step"
            data-rule-id={result.ruleId}
            data-outcome={result.outcome}
          >
            <span className="calm-step-glyph" data-outcome={result.outcome} aria-hidden="true">
              {OUTCOME_GLYPH[result.outcome]}
            </span>
            <div className="calm-step-content calm-step-content--body">
              <p className="calm-step-label">
                {result.title} —{" "}
                <span data-testid="rule-run-outcome">{OUTCOME_LABEL[result.outcome]}</span>
              </p>
              <div className="calm-step-body">
                <p data-testid="rule-run-summary">{result.summaryText}</p>
                {result.evidenceHighlight.paths.length > 0 && (
                  <div className="qa-evidence-chips" data-testid="rule-evidence-chips">
                    {result.evidenceHighlight.paths.map((path, index) => (
                      <button
                        key={path.id || index}
                        type="button"
                        data-testid="rule-evidence-chip"
                        data-evidence-id={path.id}
                        className="qa-evidence-chip"
                        onClick={() =>
                          setHighlightedNodeIds(
                            Array.from(new Set([...path.node_ids, ...path.edge_ids])),
                          )
                        }
                        title={path.id ? `Show witness path for ${path.id}` : "Show evidence"}
                      >
                        {path.id || `Evidence ${index + 1}`}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
