import { usePidGraph } from "@/components/pid/graph-context";
import type { DatalogConfirmationState } from "@/lib/datalog-confirmation";
import { readTurnIdentity, resumeDatalogReview, turnToMessage } from "@/lib/turn-client";
import { useAui } from "@assistant-ui/react";
import { type FC, type KeyboardEvent, useEffect, useRef, useState } from "react";

type DatalogWidgetAction = "run" | "revise_interpretation" | "revise_query" | "cancel";

type WidgetStatus = "selecting" | "running" | "decided" | "revise-note";

const ACTIONS: Record<
  DatalogWidgetAction,
  { label: string; testId: string; decidedMessage: string }
> = {
  run: {
    label: "Run",
    testId: "datalog-widget-option-run",
    decidedMessage: "Approved and run. The Datalog query has executed.",
  },
  revise_interpretation: {
    label: "Revise interpretation",
    testId: "datalog-widget-option-revise-interpretation",
    decidedMessage:
      "Nothing was executed. Send a message describing what the interpretation got wrong and a corrected proposal will be raised for review.",
  },
  revise_query: {
    label: "Revise query",
    testId: "datalog-widget-option-revise-query",
    decidedMessage:
      "Nothing was executed. Send a message describing how the query should change and a corrected proposal will be raised for review.",
  },
  cancel: {
    label: "Cancel",
    testId: "datalog-widget-option-cancel",
    decidedMessage: "Canceled. No Datalog query was executed.",
  },
};

const FALLBACK_ACTIONS: DatalogWidgetAction[] = [
  "run",
  "revise_interpretation",
  "revise_query",
  "cancel",
];

// The effect line is a fixed reviewer guarantee: the temporary Datalog
// executor is strictly read-only, so this text must never come from the model.
const DATALOG_EFFECT_STATEMENT =
  "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack.";

export const DatalogConfirmationWidget: FC<{
  confirmation: DatalogConfirmationState;
}> = ({ confirmation }) => {
  const aui = useAui();
  const { setHighlightedNodeIds } = usePidGraph();
  const widgetRef = useRef<HTMLElement | null>(null);
  const [status, setStatus] = useState<WidgetStatus>("selecting");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [decidedMessage, setDecidedMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rawDatalogConfirmation = confirmation.raw.datalog_confirmation;
  const datalogConfirmation =
    typeof rawDatalogConfirmation === "object" && rawDatalogConfirmation !== null
      ? (rawDatalogConfirmation as Record<string, unknown>)
      : {};
  const options = readAllowedActions(datalogConfirmation, confirmation.allowedActions);
  const plainLanguageMeaning =
    typeof datalogConfirmation.plain_language_meaning === "string" &&
    datalogConfirmation.plain_language_meaning.length > 0
      ? datalogConfirmation.plain_language_meaning
      : confirmation.plainLanguageMeaning;
  const scope = readStringEntries(datalogConfirmation.scope);
  const assumptions = readStringEntries(datalogConfirmation.assumptions);
  const generatedDatalog =
    typeof datalogConfirmation.generated_datalog === "string" &&
    datalogConfirmation.generated_datalog.length > 0
      ? datalogConfirmation.generated_datalog
      : confirmation.generatedDatalog;
  const exactDatalog =
    typeof datalogConfirmation.exact_datalog === "string" &&
    datalogConfirmation.exact_datalog.length > 0
      ? datalogConfirmation.exact_datalog
      : generatedDatalog;
  const activeOption = options[selectedIndex] ?? options[0];
  const activeOptionId = activeOption ? `datalog-widget-option-${activeOption}` : undefined;
  const isInteractive = status === "selecting";

  useEffect(() => {
    if (isInteractive) widgetRef.current?.focus();
  }, [isInteractive]);

  useEffect(() => {
    if (selectedIndex >= options.length) setSelectedIndex(Math.max(options.length - 1, 0));
  }, [options.length, selectedIndex]);

  const run = async () => {
    setStatus("running");
    setError(null);
    try {
      let result: { message: string; highlightedNodeIds?: string[] };
      const turnIdentity = readTurnIdentity(confirmation.raw);
      if (turnIdentity.turnId && turnIdentity.sessionId) {
        const turn = await resumeDatalogReview(turnIdentity.sessionId, turnIdentity.turnId, {
          decision: "confirm",
          proposalResult: readTemporaryProposalResult(confirmation.raw),
        });
        result = turnToMessage(turn);
      } else {
        const sessionId =
          typeof confirmation.raw.session_id === "string"
            ? confirmation.raw.session_id
            : "local-confirmation";
        const response = await fetch(
          `/api/review/sessions/${encodeURIComponent(sessionId)}/temporary-datalog-reviews`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question: confirmation.raw.question,
              decision: "confirm",
              proposalResult: readTemporaryProposalResult(confirmation.raw),
            }),
          },
        );
        if (!response.ok) {
          const errorBody = (await response.json().catch(() => null)) as {
            error?: { message?: string };
          } | null;
          throw new Error(errorBody?.error?.message ?? `Execution failed: ${response.status}`);
        }
        result = (await response.json()) as {
          message: string;
          highlightedNodeIds?: string[];
        };
      }
      if (result.highlightedNodeIds && result.highlightedNodeIds.length > 0) {
        setHighlightedNodeIds(result.highlightedNodeIds);
      }
      aui.thread().append({
        role: "assistant",
        content: [{ type: "text", text: result.message }],
      });
      setDecidedMessage(ACTIONS.run.decidedMessage);
      setStatus("decided");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Execution failed.");
      setStatus("selecting");
    }
  };

  const cancel = async () => {
    setStatus("running");
    setError(null);
    try {
      const turnIdentity = readTurnIdentity(confirmation.raw);
      if (turnIdentity.turnId && turnIdentity.sessionId) {
        await resumeDatalogReview(turnIdentity.sessionId, turnIdentity.turnId, {
          decision: "cancel",
          proposalResult: readTemporaryProposalResult(confirmation.raw),
        });
      } else {
        const sessionId =
          typeof confirmation.raw.session_id === "string"
            ? confirmation.raw.session_id
            : "local-confirmation";
        await fetch(
          `/api/review/sessions/${encodeURIComponent(sessionId)}/temporary-datalog-reviews`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question: confirmation.raw.question,
              decision: "cancel",
              proposalResult: readTemporaryProposalResult(confirmation.raw),
            }),
          },
        );
      }
    } catch {
      // Cancel is still locally final: no query is executed from this widget.
    }
    setDecidedMessage(ACTIONS.cancel.decidedMessage);
    setStatus("decided");
  };

  const activate = async (action: DatalogWidgetAction) => {
    if (!isInteractive) return;
    if (action === "run") {
      await run();
      return;
    }
    if (action === "cancel") {
      await cancel();
      return;
    }
    setDecidedMessage(ACTIONS[action].decidedMessage);
    setStatus("revise-note");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!isInteractive || options.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((index) => (index + 1) % options.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((index) => (index - 1 + options.length) % options.length);
      return;
    }
    if (/^[1-4]$/.test(event.key)) {
      const optionIndex = Number(event.key) - 1;
      if (optionIndex < options.length) {
        event.preventDefault();
        setSelectedIndex(optionIndex);
      }
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      void activate(options[selectedIndex]);
    }
  };

  return (
    <section
      ref={widgetRef}
      className="datalog-confirmation-widget"
      data-testid="datalog-confirmation-widget"
      aria-label="Temporary Datalog confirmation"
      tabIndex={isInteractive ? 0 : -1}
      onKeyDown={handleKeyDown}
    >
      <header className="datalog-widget-header">
        <div>
          <p className="pid-eyebrow">Temporary Datalog confirmation</p>
          <h3>Review the generated query</h3>
        </div>
        <span data-testid="datalog-validation-status">{confirmation.validationStatus}</span>
      </header>

      <div className="datalog-widget-context" aria-label="Datalog meaning and scope">
        <section className="datalog-widget-context-card datalog-widget-context-card--meaning">
          <p className="datalog-widget-context-label">Plain-language meaning</p>
          <p className="datalog-widget-meaning" data-testid="datalog-plain-language">
            {plainLanguageMeaning}
          </p>
        </section>

        {scope.length > 0 && (
          <section className="datalog-widget-context-card" data-testid="datalog-scope">
            <p className="datalog-widget-context-label">Scope</p>
            <dl className="datalog-widget-definition-list">
              {scope.map(([key, value]) => (
                <div key={key}>
                  <dt>{formatConsentKey(key)}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>

      {assumptions.length > 0 && (
        <dl className="datalog-consent-section" data-testid="datalog-assumptions">
          <dt>Assumptions</dt>
          {assumptions.map(([key, value]) => (
            <dd key={key}>
              <span className="datalog-consent-key">{formatConsentKey(key)}:</span> {value}
            </dd>
          ))}
        </dl>
      )}

      <details data-testid="datalog-exact-query">
        <summary>Exact Datalog</summary>
        <pre className="datalog-syntax">
          <code>{exactDatalog}</code>
        </pre>
      </details>

      <p className="datalog-consent-effect" data-testid="datalog-effect">
        {DATALOG_EFFECT_STATEMENT}
      </p>

      {isInteractive || status === "running" ? (
        <div
          className="datalog-widget-options"
          role="listbox"
          aria-label="Datalog review actions"
          aria-activedescendant={activeOptionId}
          aria-disabled={status === "running"}
        >
          <ol className="datalog-widget-option-list">
            {options.map((action, index) => (
              <li
                key={action}
                id={`datalog-widget-option-${action}`}
                className="datalog-widget-option"
                data-testid={ACTIONS[action].testId}
                role="option"
                aria-selected={index === selectedIndex}
                aria-disabled={status === "running"}
                onClick={() => void activate(action)}
              >
                <span className="datalog-widget-option-number" aria-hidden="true">
                  {index + 1}.
                </span>
                <span>{ACTIONS[action].label}</span>
              </li>
            ))}
          </ol>
          <p className="datalog-widget-key-hint">
            Use ↑/↓ to choose, 1-4 to jump, Enter to confirm.
          </p>
        </div>
      ) : null}

      {status === "running" && (
        <p className="datalog-confirmation-note" data-testid="datalog-widget-running">
          Working on the selected action…
        </p>
      )}
      {(status === "decided" || status === "revise-note") && decidedMessage && (
        <p className="datalog-confirmation-note" data-testid="datalog-widget-decided">
          {decidedMessage}
        </p>
      )}
      {error && (
        <p className="datalog-confirmation-error" data-testid="datalog-run-error">
          {error}
        </p>
      )}
    </section>
  );
};


function readAllowedActions(
  datalogConfirmation: Record<string, unknown>,
  fallback: string[],
): DatalogWidgetAction[] {
  const source = Array.isArray(datalogConfirmation.allowed_actions)
    ? datalogConfirmation.allowed_actions
    : fallback;
  const actions = source.filter(isDatalogWidgetAction);
  const unique = actions.filter((action, index) => actions.indexOf(action) === index);
  return unique.length > 0 ? unique : FALLBACK_ACTIONS;
}

function isDatalogWidgetAction(value: unknown): value is DatalogWidgetAction {
  return (
    value === "run" ||
    value === "revise_interpretation" ||
    value === "revise_query" ||
    value === "cancel"
  );
}

function readTemporaryProposalResult(raw: Record<string, unknown>) {
  const confirmation = raw.datalog_confirmation;
  if (
    typeof confirmation === "object" &&
    confirmation !== null &&
    "proposal_result" in confirmation
  ) {
    const proposalResult = (confirmation as Record<string, unknown>).proposal_result;
    if (typeof proposalResult === "object" && proposalResult !== null) {
      return proposalResult;
    }
  }
  return {};
}


function readStringEntries(value: unknown): [string, string][] {
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, entry]) => [
    key,
    Array.isArray(entry)
      ? entry.filter((item) => typeof item === "string").join("; ")
      : String(entry ?? ""),
  ]);
}

function formatConsentKey(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
