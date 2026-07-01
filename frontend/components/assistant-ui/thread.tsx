import {
  ComposerAddAttachment,
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/assistant-ui/attachment";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { usePidGraph } from "@/components/pid/graph-context";
import {
  parseDatalogConfirmationMessage,
  parseGroundedLogicAnswerMessage,
  type DatalogConfirmationState,
  type GroundedLogicAnswerState,
} from "@/lib/datalog-confirmation";
import {
  parseGroundedQAAnswerMessage,
  type GroundedQAAnswerState,
  type EvidencePath,
} from "@/lib/grounded-qa-answer";
import { parseDirectionReviewMessage, type DirectionReviewState } from "@/lib/direction-review";
import {
  readTurnIdentity,
  resumeDatalogReview,
  resumeDirectionReview,
  turnToMessage,
} from "@/lib/turn-client";
import { cn } from "@/lib/utils";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  type AssistantState,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  SuggestionPrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  MicIcon,
  MoreHorizontalIcon,
  PencilIcon,
  RefreshCwIcon,
  SquareIcon,
} from "lucide-react";
import { type FC, useState } from "react";

// Startup exposes a loading placeholder thread; treat it as a new chat so
// the composer mounts centered. Loads after startup keep the docked layout.
const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 && (!s.thread.isLoading || s.threads.isLoading);

export const Thread: FC = () => {
  const isEmpty = useAuiState(isNewChatView);

  return (
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root bg-background @container flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-bg" as string]:
          "color-mix(in oklab, var(--color-muted) 30%, var(--color-background))",
        ["--composer-radius" as string]: "1.5rem",
        ["--composer-padding" as string]: "8px",
      }}
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        data-slot="aui_thread-viewport"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 pt-4",
            isEmpty && "justify-center",
          )}
        >
          <AuiIf condition={isNewChatView}>
            <ThreadWelcome />
          </AuiIf>

          <div data-slot="aui_message-group" className="mb-14 flex flex-col gap-y-6 empty:hidden">
            <ThreadPrimitive.Messages>{() => <ThreadMessage />}</ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "aui-thread-viewport-footer bg-background flex flex-col gap-4 overflow-visible pb-4 md:pb-6",
              !isEmpty && "sticky bottom-0 mt-auto rounded-t-(--composer-radius)",
            )}
          >
            <ThreadScrollToBottom />
            <Composer />
            <AuiIf condition={(s) => isNewChatView(s) && s.composer.isEmpty}>
              <ThreadSuggestions />
            </AuiIf>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);

  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  return <AssistantMessage />;
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="aui-thread-scroll-to-bottom dark:border-border dark:bg-background dark:hover:bg-accent absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  return (
    <div className="aui-thread-welcome-root mb-6 flex flex-col items-center px-4 text-center">
      <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both text-2xl font-semibold duration-200">
        How can I help you today?
      </h1>
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestions flex w-full flex-wrap items-center justify-center gap-2 px-4">
      <ThreadPrimitive.Suggestions>{() => <ThreadSuggestionItem />}</ThreadPrimitive.Suggestions>
    </div>
  );
};

const ThreadSuggestionItem: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 animate-in fill-mode-both duration-200">
      <SuggestionPrimitive.Trigger send asChild>
        <Button
          variant="ghost"
          className="aui-thread-welcome-suggestion text-foreground hover:bg-muted border-border/60 h-auto gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-normal whitespace-nowrap transition-colors"
        >
          <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1" />
          <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 empty:hidden" />
        </Button>
      </SuggestionPrimitive.Trigger>
    </div>
  );
};

const Composer: FC = () => {
  return (
    <ComposerPrimitive.Root className="aui-composer-root relative flex w-full flex-col">
      <ComposerPrimitive.AttachmentDropzone asChild>
        <div
          data-slot="aui_composer-shell"
          className="border-border/60 data-[dragging=true]:border-ring focus-within:border-border dark:border-muted-foreground/15 dark:focus-within:border-muted-foreground/30 flex w-full flex-col gap-2 rounded-(--composer-radius) border bg-(--composer-bg) p-(--composer-padding) shadow-[0_4px_16px_-8px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] focus-within:shadow-[0_6px_24px_-8px_rgba(0,0,0,0.12),0_1px_2px_rgba(0,0,0,0.05)] data-[dragging=true]:border-dashed data-[dragging=true]:bg-[color-mix(in_oklab,var(--color-accent)_50%,var(--color-background))] dark:shadow-none"
        >
          <ComposerAttachments />
          <ComposerPrimitive.Input
            placeholder="Send a message..."
            className="aui-composer-input placeholder:text-muted-foreground/80 max-h-32 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base outline-none"
            rows={1}
            autoFocus
            aria-label="Message input"
          />
          <ComposerAction />
        </div>
      </ComposerPrimitive.AttachmentDropzone>
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC = () => {
  return (
    <div className="aui-composer-action-wrapper relative flex items-center justify-between">
      <ComposerAddAttachment />
      <div className="flex items-center gap-1.5">
        <AuiIf condition={(s) => s.thread.capabilities.dictation}>
          <AuiIf condition={(s) => s.composer.dictation == null}>
            <ComposerPrimitive.Dictate asChild>
              <TooltipIconButton
                tooltip="Voice input"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className="aui-composer-dictate size-7 rounded-full"
                aria-label="Start voice input"
              >
                <MicIcon className="aui-composer-dictate-icon size-4" />
              </TooltipIconButton>
            </ComposerPrimitive.Dictate>
          </AuiIf>
          <AuiIf condition={(s) => s.composer.dictation != null}>
            <ComposerPrimitive.StopDictation asChild>
              <TooltipIconButton
                tooltip="Stop dictation"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className="aui-composer-stop-dictation text-destructive size-7 rounded-full"
                aria-label="Stop voice input"
              >
                <SquareIcon className="aui-composer-stop-dictation-icon size-3.5 animate-pulse fill-current" />
              </TooltipIconButton>
            </ComposerPrimitive.StopDictation>
          </AuiIf>
        </AuiIf>
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send asChild>
            <TooltipIconButton
              tooltip="Send message"
              side="bottom"
              type="button"
              variant="default"
              size="icon"
              className="aui-composer-send size-7 rounded-full"
              aria-label="Send message"
            >
              <ArrowUpIcon className="aui-composer-send-icon size-4.5" />
            </TooltipIconButton>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <Button
              type="button"
              variant="default"
              size="icon"
              className="aui-composer-cancel size-7 rounded-full"
              aria-label="Stop generating"
            >
              <SquareIcon className="aui-composer-cancel-icon size-3.5 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root border-destructive bg-destructive/10 text-destructive dark:bg-destructive/5 mt-2 rounded-md border p-3 text-sm dark:text-red-200">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantMessage: FC = () => {
  const ACTION_BAR_PT = "pt-1.5";
  const ACTION_BAR_HEIGHT = `-mb-7.5 min-h-7.5 ${ACTION_BAR_PT}`;

  return (
    <MessagePrimitive.Root
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      className="fade-in slide-in-from-bottom-1 animate-in relative duration-150"
    >
      <div
        data-slot="aui_assistant-message-content"
        // [contain-intrinsic-size:auto_24px] fixes issue #4104, don't change without checking for regressions
        className="text-foreground px-2 leading-relaxed wrap-break-word [contain-intrinsic-size:auto_24px] [content-visibility:auto]"
      >
        <MessagePrimitive.Parts>
          {({ part }) => {
            if (part.type === "text") {
              const confirmation = parseDatalogConfirmationMessage(part.text);
              if (confirmation) {
                return <DatalogConfirmationCard confirmation={confirmation} />;
              }
              const directionReview = parseDirectionReviewMessage(part.text);
              if (directionReview) {
                return <DirectionReviewCard review={directionReview} />;
              }
              const qaAnswer = parseGroundedQAAnswerMessage(part.text);
              if (qaAnswer) {
                return <GroundedQAAnswerCard answer={qaAnswer} />;
              }
              const answer = parseGroundedLogicAnswerMessage(part.text);
              if (answer) {
                return <GroundedLogicAnswerCard answer={answer} />;
              }
              return <MarkdownText />;
            }
            if (part.type === "tool-call") return part.toolUI ?? <ToolFallback {...part} />;
            return null;
          }}
        </MessagePrimitive.Parts>
        <AuiIf
          condition={(s) => s.message.status?.type === "running" && s.message.parts.length === 0}
        >
          <span
            data-slot="aui_assistant-message-indicator"
            className="animate-pulse font-sans"
            aria-label="Assistant is working"
          >
            {"●"}
          </span>
        </AuiIf>
        <MessageError />
      </div>

      <div
        data-slot="aui_assistant-message-footer"
        className={cn("ms-2 flex items-center", ACTION_BAR_HEIGHT)}
      >
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

const DatalogConfirmationCard: FC<{
  confirmation: DatalogConfirmationState;
}> = ({ confirmation }) => {
  const aui = useAui();
  const { setHighlightedNodeIds } = usePidGraph();
  const [state, setState] = useState<"ready" | "running" | "canceled" | "revise">("ready");
  const [error, setError] = useState<string | null>(null);
  const sessionId = readSessionId(confirmation.raw);
  const isTemporaryDatalog = confirmation.raw.confirmation_kind === "temporary_datalog";

  const turnIdentity = readTurnIdentity(confirmation.raw);

  const run = async () => {
    if (state === "running") return;
    setState("running");
    setError(null);
    try {
      let result: { message: string; highlightedNodeIds?: string[] };
      if (turnIdentity.turnId && turnIdentity.sessionId) {
        // Turn-lifecycle path: resume the paused turn; the response carries
        // the turn's final state.
        const turn = await resumeDatalogReview(turnIdentity.sessionId, turnIdentity.turnId, {
          decision: "confirm",
          proposalResult: readTemporaryProposalResult(confirmation.raw),
        });
        result = turnToMessage(turn);
      } else {
        const response = await fetch(
          isTemporaryDatalog
            ? `/api/review/sessions/${encodeURIComponent(sessionId)}/temporary-datalog-reviews`
            : `/api/review/sessions/${encodeURIComponent(sessionId)}/logic-requests/execute`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(
              isTemporaryDatalog
                ? {
                    question: confirmation.raw.question,
                    decision: "confirm",
                    proposalResult: readTemporaryProposalResult(confirmation.raw),
                  }
                : { confirmation: confirmation.raw },
            ),
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
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Execution failed.");
      setState("ready");
    }
  };

  const cancel = async () => {
    if (state !== "ready") return;
    if (!isTemporaryDatalog && !turnIdentity.turnId) {
      setState("canceled");
      return;
    }
    setError(null);
    try {
      if (turnIdentity.turnId && turnIdentity.sessionId) {
        // Drive the paused turn to its terminal canceled state.
        await resumeDatalogReview(turnIdentity.sessionId, turnIdentity.turnId, {
          decision: "cancel",
          proposalResult: readTemporaryProposalResult(confirmation.raw),
        });
      } else {
        await fetch(`/api/review/sessions/${encodeURIComponent(sessionId)}/temporary-datalog-reviews`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: confirmation.raw.question,
            decision: "cancel",
            proposalResult: readTemporaryProposalResult(confirmation.raw),
          }),
        });
      }
    } catch {
      // A cancel action is still locally final: no query is executed from this card.
    }
    setState("canceled");
  };

  return (
    <section
      className="datalog-confirmation-card"
      data-testid="datalog-confirmation-card"
      aria-label="Datalog confirmation"
    >
      <header>
        <div>
          <p className="pid-eyebrow">Datalog confirmation</p>
          <h3>Review before execution</h3>
        </div>
        <span data-testid="datalog-validation-status">{confirmation.validationStatus}</span>
      </header>

      <p data-testid="datalog-plain-language">{confirmation.plainLanguageMeaning}</p>

      <details data-testid="datalog-details">
        <summary>Generated Datalog</summary>
        <pre>
          <code>{confirmation.generatedDatalog}</code>
        </pre>
      </details>

      <div className="datalog-confirmation-actions">
        <button type="button" disabled={state !== "ready"} onClick={run}>
          {state === "running" ? "Running" : "Run"}
        </button>
        <button type="button" disabled={state !== "ready"} onClick={() => setState("revise")}>
          Revise
        </button>
        <button type="button" disabled={state !== "ready"} onClick={cancel}>
          Cancel
        </button>
      </div>
      {state === "revise" && (
        <p className="datalog-confirmation-note" data-testid="datalog-revise-note">
          Revision is not wired yet. Edit your prompt and send a new request.
        </p>
      )}
      {state === "canceled" && (
        <p className="datalog-confirmation-note" data-testid="datalog-cancel-note">
          Canceled. No Datalog query was executed.
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


const DirectionReviewCard: FC<{ review: DirectionReviewState }> = ({ review }) => {
  const aui = useAui();
  const { setHighlightedNodeIds } = usePidGraph();
  const [state, setState] = useState<"ready" | "submitting" | "done">("ready");
  const [error, setError] = useState<string | null>(null);

  const witnessIds = Array.from(
    new Set(review.evidenceHighlight.paths.flatMap((p) => [...p.node_ids, ...p.edge_ids])),
  );

  const turnIdentity = readTurnIdentity(review.raw);

  const submit = async (decision: "confirm" | "reverse" | "unknown") => {
    if (state !== "ready") return;
    setState("submitting");
    setError(null);
    try {
      let result: { message: string; highlightedNodeIds?: string[] };
      if (turnIdentity.turnId && turnIdentity.sessionId) {
        // Turn-lifecycle path: resume the paused turn with the decision; the
        // response carries the turn's final state.
        const turn = await resumeDirectionReview(turnIdentity.sessionId, turnIdentity.turnId, {
          decision,
          reviewKey: review.reviewKey,
        });
        result = turnToMessage(turn);
      } else {
        const response = await fetch(
          `/api/review/sessions/${encodeURIComponent(readSessionIdFromRaw(review.raw))}/direction-reviews`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question: review.question,
              decision,
              reviewKey: review.reviewKey,
              conversation: review.conversation,
            }),
          },
        );
        if (!response.ok) {
          throw new Error(`Direction review failed: ${response.status}`);
        }
        result = (await response.json()) as {
          message: string;
          highlightedNodeIds?: string[];
        };
      }
      if (result.highlightedNodeIds) {
        setHighlightedNodeIds(result.highlightedNodeIds);
      }
      aui.thread().append({
        role: "assistant",
        content: [{ type: "text", text: result.message }],
      });
      setState("done");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Direction review failed.");
      setState("ready");
    }
  };

  return (
    <section
      className="direction-review-card"
      data-testid="direction-review-card"
      aria-label="Flow direction review"
    >
      <header>
        <p className="pid-eyebrow">Flow direction review</p>
        <span data-testid="direction-basis">{review.directionBasis}</span>
      </header>
      <p data-testid="direction-proposed">
        Proposed direction: <strong>{review.proposedDirection}</strong>
      </p>
      <p data-testid="direction-basis-explanation">{review.basisExplanation}</p>

      {witnessIds.length > 0 && (
        <button
          type="button"
          data-testid="direction-witness-chip"
          className="qa-evidence-chip"
          onClick={() => setHighlightedNodeIds(witnessIds)}
          title="Highlight the structural witness"
        >
          Show witness
        </button>
      )}

      <div className="direction-review-actions">
        <button
          type="button"
          data-testid="direction-confirm"
          disabled={state !== "ready"}
          onClick={() => submit("confirm")}
        >
          Confirm
        </button>
        <button
          type="button"
          data-testid="direction-reverse"
          disabled={state !== "ready"}
          onClick={() => submit("reverse")}
        >
          Reverse
        </button>
        <button
          type="button"
          data-testid="direction-unknown"
          disabled={state !== "ready"}
          onClick={() => submit("unknown")}
        >
          Unknown
        </button>
      </div>
      {error && (
        <p className="direction-review-error" data-testid="direction-review-error">
          {error}
        </p>
      )}
    </section>
  );
};

function readSessionIdFromRaw(raw: Record<string, unknown>) {
  return typeof raw.session_id === "string" ? raw.session_id : "local-session";
}

const GroundedQAAnswerCard: FC<{ answer: GroundedQAAnswerState }> = ({ answer }) => {
  const { setHighlightedNodeIds } = usePidGraph();

  const handleEvidenceChipClick = (path: EvidencePath) => {
    const ids = Array.from(new Set([...path.node_ids, ...path.edge_ids]));
    setHighlightedNodeIds(ids.length > 0 ? ids : [path.id].filter(Boolean));
  };

  const handleAllEvidenceClick = () => {
    const { source_scope_ids, matched_object_ids, paths } = answer.evidenceHighlight;
    const pathIds = paths.flatMap((p) => [...p.node_ids, ...p.edge_ids]);
    const ids = Array.from(new Set([...source_scope_ids, ...matched_object_ids, ...pathIds]));
    setHighlightedNodeIds(ids);
  };

  return (
    <section
      className="grounded-qa-answer-card"
      data-testid="grounded-qa-answer"
      aria-label="Grounded topology answer"
    >
      <p className="pid-eyebrow">Topology answer</p>
      <p data-testid="qa-answer-text">{answer.answerText}</p>

      {answer.interpretedObjectIds.length > 0 && (
        <p className="qa-interpretation" data-testid="qa-interpretation">
          Interpreted as{" "}
          {answer.interpretedObjectIds.length === 1
            ? "object"
            : `${answer.interpretedObjectIds.length} objects`}
          :{" "}
          {answer.interpretedObjectIds.map((id) => (
            <button
              key={id}
              type="button"
              data-testid="qa-interpretation-chip"
              data-evidence-id={id}
              className="qa-evidence-chip qa-evidence-chip--interpretation"
              onClick={() => setHighlightedNodeIds([id])}
              title={`Highlight ${id}`}
            >
              {id}
            </button>
          ))}
        </p>
      )}

      {answer.evidenceHighlight.paths.length > 0 && (
        <div className="qa-evidence-chips" data-testid="qa-evidence-chips">
          {answer.evidenceHighlight.paths.map((path) => (
            <button
              key={path.id}
              type="button"
              data-testid="qa-evidence-chip"
              data-evidence-id={path.id}
              className="qa-evidence-chip"
              onClick={() => handleEvidenceChipClick(path)}
              title={`Show witness path for ${path.id}`}
            >
              {path.id}
            </button>
          ))}
          {answer.evidenceHighlight.paths.length > 1 && (
            <button
              type="button"
              data-testid="qa-evidence-highlight-all"
              className="qa-evidence-chip qa-evidence-chip--all"
              onClick={handleAllEvidenceClick}
            >
              Highlight all
            </button>
          )}
        </div>
      )}

      {answer.evidenceHighlight.paths.length === 0 && answer.evidenceReferences.length > 0 && (
        <div className="qa-evidence-chips" data-testid="qa-evidence-chips">
          {answer.evidenceReferences.map((ref) => (
            <button
              key={ref}
              type="button"
              data-testid="qa-evidence-chip"
              data-evidence-id={ref}
              className="qa-evidence-chip qa-evidence-chip--generic"
              onClick={() => setHighlightedNodeIds([ref])}
              title={`Inspect evidence: ${ref}`}
            >
              {ref}
            </button>
          ))}
        </div>
      )}
    </section>
  );
};

const GroundedLogicAnswerCard: FC<{ answer: GroundedLogicAnswerState }> = ({ answer }) => {
  return (
    <section
      className="grounded-logic-answer-card"
      data-testid="grounded-logic-answer"
      aria-label="Grounded logic-request answer"
    >
      <p className="pid-eyebrow">Grounded answer</p>
      <p data-testid="evidence-summary">{answer.summary}</p>
      <details data-testid="raw-evidence-details">
        <summary>Raw evidence details</summary>
        <pre>
          <code>{JSON.stringify(answer.rawEvidence, null, 2)}</code>
        </pre>
      </details>
    </section>
  );
};

function readSessionId(raw: Record<string, unknown>) {
  return typeof raw.session_id === "string" ? raw.session_id : "local-confirmation";
}

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root text-muted-foreground animate-in fade-in col-start-3 row-start-2 -ms-1 flex gap-1 duration-200"
    >
      <ActionBarPrimitive.Copy asChild>
        <TooltipIconButton tooltip="Copy">
          <AuiIf condition={(s) => s.message.isCopied}>
            <CheckIcon className="animate-in zoom-in-50 fade-in duration-200 ease-out" />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <CopyIcon className="animate-in zoom-in-75 fade-in duration-150" />
          </AuiIf>
        </TooltipIconButton>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="Refresh">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger asChild>
          <TooltipIconButton tooltip="More" className="data-[state=open]:bg-accent">
            <MoreHorizontalIcon />
          </TooltipIconButton>
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className="aui-action-bar-more-content bg-popover/95 text-popover-foreground data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-[8rem] overflow-hidden rounded-xl border p-1.5 shadow-lg backdrop-blur-sm"
        >
          <ActionBarPrimitive.ExportMarkdown asChild>
            <ActionBarMorePrimitive.Item className="aui-action-bar-more-item hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none">
              <DownloadIcon className="size-4" />
              Export as Markdown
            </ActionBarMorePrimitive.Item>
          </ActionBarPrimitive.ExportMarkdown>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      className="fade-in slide-in-from-bottom-1 animate-in grid auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 duration-150 [contain-intrinsic-size:auto_60px] [content-visibility:auto] [&:where(>*)]:col-start-2"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
        <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
          <MessagePrimitive.Parts />
        </div>
        <div className="aui-user-action-bar-wrapper absolute start-0 top-1/2 -translate-x-full -translate-y-1/2 pe-2 peer-empty:hidden rtl:translate-x-full">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker
        data-slot="aui_user-branch-picker"
        className="col-span-full col-start-1 row-start-3 -me-1 justify-end"
      />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton tooltip="Edit" className="aui-user-action-edit">
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

const EditComposer: FC = () => {
  return (
    <MessagePrimitive.Root data-slot="aui_edit-composer-wrapper" className="flex flex-col px-2">
      <ComposerPrimitive.Root className="aui-edit-composer-root border-border/60 dark:border-muted-foreground/15 ms-auto flex w-full max-w-[85%] flex-col rounded-(--composer-radius) border bg-(--composer-bg) shadow-[0_4px_16px_-8px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] dark:shadow-none">
        <ComposerPrimitive.Input
          className="aui-edit-composer-input text-foreground min-h-14 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-base outline-none"
          autoFocus
        />
        <div className="aui-edit-composer-footer mx-2.5 mb-2.5 flex items-center gap-1.5 self-end">
          <ComposerPrimitive.Cancel asChild>
            <Button variant="ghost" size="sm" className="h-8 rounded-full px-3.5">
              Cancel
            </Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button size="sm" className="h-8 rounded-full px-3.5">
              Update
            </Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({ className, ...rest }) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root text-muted-foreground -ms-2 me-2 inline-flex items-center text-xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="Previous">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="Next">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
