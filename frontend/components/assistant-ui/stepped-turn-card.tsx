"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { ExecutionDetailLevel } from "@/lib/execution-detail.ts";
import type { TurnStep } from "@/lib/turn-steps.ts";

const GLYPH: Record<TurnStep["status"], string> = {
  done: "✓",
  blocked: "●",
  canceled: "✕",
  failed: "✕",
  pending: "○",
};

// Thin wrapper (bead pydexpi-datalog-1-2ki.11): renders a turn's synthesized
// step list as ordered rows, with the LAST step's body slot holding the
// existing card content verbatim (DatalogConfirmationCard/DirectionReviewCard/
// GroundedQAAnswerCard/GroundedLogicAnswerCard) -- those components are not
// re-implemented here, only wrapped, so every existing testid/aria-label/
// button stays exactly where Playwright already expects it.
export function SteppedTurnCard({
  steps,
  children,
  detailLevel = "standard",
}: {
  steps: TurnStep[];
  children: ReactNode;
  detailLevel?: ExecutionDetailLevel;
}) {
  // Concise mode keeps the answer card and its evidence summary, while
  // omitting the execution walk entirely.
  if (detailLevel === "concise" || steps.length === 0) return <>{children}</>;

  return (
    <section className="calm-step-card" data-testid="stepped-turn-card">
      <ol className="calm-step-list" data-testid="turn-step-list">
        {steps.map((step, index) => {
          const isLast = index === steps.length - 1;
          return (
            <li
              key={step.id}
              className="calm-step-row"
              data-testid="turn-step"
              data-step-id={step.id}
              data-step-status={step.status}
            >
              <span className="calm-step-glyph" data-status={step.status} aria-hidden="true">
                {GLYPH[step.status]}
              </span>
              <div className={cn("calm-step-content", isLast && "calm-step-content--body")}>
                <p className="calm-step-label">{step.label}</p>
                {detailLevel === "detailed" &&
                  step.detail?.kind === "retrieval-progress" &&
                  step.detail.toolInput && (
                    <details className="calm-step-detail" data-testid="retrieval-detail">
                      <summary>Sanitized tool input</summary>
                      <pre>
                        <code>{formatDetailValue(step.detail.toolInput)}</code>
                      </pre>
                    </details>
                  )}
                {detailLevel === "detailed" &&
                  step.detail?.kind === "retrieval" &&
                  step.detail.rounds &&
                  step.detail.rounds.length > 0 && (
                    <details className="calm-step-detail" data-testid="retrieval-detail">
                      <summary>Sanitized tool inputs and outputs</summary>
                      <div className="calm-step-detail-list">
                        {step.detail.rounds.map((round) => (
                          <div key={`${round.round}-${round.toolName ?? "tool"}`}>
                            <p>
                              Round {round.round} of {round.maxRounds}
                              {round.toolName ? ` — ${round.toolName}` : ""}
                            </p>
                            {round.toolInput && (
                              <pre>
                                <code>{formatDetailValue(round.toolInput)}</code>
                              </pre>
                            )}
                          </div>
                        ))}
                        {step.detail.outputReferences &&
                          step.detail.outputReferences.length > 0 && (
                            <p>Evidence output: {step.detail.outputReferences.join(", ")}</p>
                          )}
                      </div>
                    </details>
                  )}
                {detailLevel === "detailed" && step.detail?.kind === "execution-trace" && (
                  <details className="calm-step-trace-detail" data-testid="execution-trace-detail">
                    <summary>Details</summary>
                    <dl>
                      <div>
                        <dt>Activity</dt>
                        <dd>
                          <code>{step.detail.traceKind}</code>
                        </dd>
                      </div>
                      {step.detail.occurrenceCount > 1 && (
                        <div>
                          <dt>Occurrences</dt>
                          <dd>{step.detail.occurrenceCount}</dd>
                        </div>
                      )}
                      {step.detail.evidenceReferences.length > 0 && (
                        <div>
                          <dt>Evidence</dt>
                          <dd>{step.detail.evidenceReferences.join(", ")}</dd>
                        </div>
                      )}
                      {step.detail.artifactUrl && (
                        <div>
                          <dt>Detail artifact</dt>
                          <dd>
                            <a
                              href={step.detail.artifactUrl}
                              target="_blank"
                              rel="noreferrer"
                              data-testid="execution-trace-artifact-link"
                            >
                              Open bounded detail artifact
                            </a>
                          </dd>
                        </div>
                      )}
                    </dl>
                  </details>
                )}
                {isLast && <div className="calm-step-body">{children}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function formatDetailValue(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Detail unavailable.";
  }
}
