from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    tool_input: dict[str, object]
    tool_call_id: str
    # Model-supplied reasoning excerpt for this step, when the provider
    # captured one (bead 3qo.9.12). Never fabricated: None when absent.
    reasoning: str | None = None


# Grounding posture: the model declares how a final answer relates to the loaded
# source. The backend never classifies the question; it only enforces that the
# declared posture is consistent with the validated evidence the answer carries.
POSTURE_UNSPECIFIED = "unspecified"
POSTURE_SOURCE_GROUNDED = "source_grounded"
POSTURE_GENERAL_KNOWLEDGE = "general_knowledge"
POSTURE_SOURCE_DATA_UNAVAILABLE = "source_data_unavailable"
POSTURE_OUT_OF_SCOPE = "out_of_scope"
POSTURE_NEEDS_CLARIFICATION = "needs_clarification"
# Backend-assigned only: the model declared a source-grounded conclusion but no
# evidence reference survived validation, so the claim cannot be presented as grounded.
POSTURE_UNSUPPORTED_SOURCE_CLAIM = "unsupported_source_claim"

# Backend-authoritative disclosures attached when an answer is not a validated
# conclusion derived from the loaded source.
_POSTURE_DISCLOSURES: dict[str, str] = {
    POSTURE_GENERAL_KNOWLEDGE: (
        "This is general process-engineering knowledge, not a conclusion derived "
        "from your loaded source."
    ),
    POSTURE_SOURCE_DATA_UNAVAILABLE: (
        "This depends on operating data that is not present in your loaded source, "
        "so the required inputs are unavailable."
    ),
    POSTURE_OUT_OF_SCOPE: (
        "That is outside grounded P&ID source review. I can answer questions about "
        "your loaded source."
    ),
    POSTURE_NEEDS_CLARIFICATION: (
        "The request needs a specific object, scope, or acceptance criterion "
        "before it can be checked against the loaded source."
    ),
    POSTURE_UNSUPPORTED_SOURCE_CLAIM: (
        "This answer is not backed by validated evidence from your loaded source and "
        "should not be treated as a source conclusion."
    ),
}


@dataclass(frozen=True)
class FinalAnswer:
    answer_text: str
    evidence_references: list[str] = field(default_factory=list)
    interpreted_object_ids: list[str] = field(default_factory=list)
    grounding_posture: str = POSTURE_UNSPECIFIED
    # Model-supplied reasoning excerpt for the final answer, when the provider
    # captured one (bead 3qo.9.12). Never fabricated: None when absent.
    reasoning: str | None = None


@dataclass(frozen=True)
class ConversationTurn:
    """A prior grounded turn carried forward as conversation state.

    `evidence_references` are topology identities established by a prior turn and
    may be reused by identity. `answer_text` is prior model prose: it is context
    only and can never itself become engineering evidence.
    """

    question: str
    answer_text: str
    evidence_references: list[str] = field(default_factory=list)


@runtime_checkable
class QATurnProvider(Protocol):
    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ToolCall | FinalAnswer: ...


@dataclass(frozen=True)
class QATurnResult:
    answer_text: str
    evidence_references: list[str]
    rejected_references: list[str]
    interpreted_object_ids: list[str]
    tool_call_trace: list[dict[str, object]]
    grounding_posture: str = POSTURE_UNSPECIFIED
    source_grounded: bool = False
    disclosure: str | None = None
    deterministic_verdict: str | None = None
    witnesses: list[str] = field(default_factory=list)
    route_artifact: dict[str, object] | None = None
    trace_events: list[dict[str, object]] = field(default_factory=list)
    # Set only when a human steering directive or a user answer-constraint
    # ended the run instead of the ordinary model/tool loop (bead 3qo.9.8):
    # "answer_now" | "stop" | "turn_limit" | "duration_limit" | "cost_limit".
    steering_outcome: str | None = None


# Human steering directives, polled between rounds. Backend-owned: the model
# cannot emit these -- only the human operator through the web lifecycle
# (bead 3qo.9.8). Answer Now stops exploration and synthesizes from completed
# validated artifacts; Stop terminates the run while preserving the trace.
STEER_ANSWER_NOW = "answer_now"
STEER_STOP = "stop"

# Polled with no arguments at the top of each round; returns a directive or None.
Steering = Callable[[], str | None]


@dataclass(frozen=True)
class RunConstraints:
    """Optional user-selected answer constraints. These only ever *tighten* a
    run: they never disable a validator, widen a capability permission, or
    raise an operational ceiling (bead 3qo.9.8). Unset fields impose no limit.
    """

    max_rounds: int | None = None
    max_duration_seconds: float | None = None
    max_provider_cost: float | None = None
    allowed_capabilities: frozenset[str] | None = None


@dataclass(frozen=True)
class ReviewIntent:
    intent_type: str
    evidence_need: str
    suggested_next_tools: tuple[str, ...] = ()
    requires_confirmation: bool = False


_FOLLOW_UP_REFERENCES = (
    "it",
    "its",
    "that",
    "those",
    "these",
    "them",
    "they",
    "their",
    "this",
    "same",
)

_EQUIPMENT_TOKENS = (
    "nozzle",
    "pump",
    "valve",
    "exchanger",
    "tank",
    "vessel",
    "column",
    "instrument",
    "pipe",
    "segment",
    "compressor",
)


def _latest_user_question(messages: list[dict[str, object]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _prior_evidence_ids(messages: list[dict[str, object]]) -> list[str]:
    collected: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        grounded = message.get("grounded_evidence_ids")
        if isinstance(grounded, list):
            for evidence_id in grounded:
                if isinstance(evidence_id, str) and evidence_id not in collected:
                    collected.append(evidence_id)
    return collected


def _looks_like_follow_up(question: str) -> bool:
    words = {token.strip(".,!?;:'\"").lower() for token in question.split()}
    return any(reference in words for reference in _FOLLOW_UP_REFERENCES)


def _question_token(question: str) -> str:
    normalized = question.lower()
    for token in _EQUIPMENT_TOKENS:
        if token in normalized:
            return token
    return ""


def _classify_review_intent(question: str) -> ReviewIntent:
    normalized = question.lower()
    if _looks_like_source_mutation(normalized):
        return ReviewIntent(
            intent_type="source_mutation",
            evidence_need="denial",
            suggested_next_tools=("mutate_source_graph",),
        )
    if _looks_like_rule_evaluation(normalized):
        return ReviewIntent(
            intent_type="rule_evaluation",
            evidence_need="rule_result",
            suggested_next_tools=("propose_temporary_datalog",),
            requires_confirmation=False,
        )
    if _looks_like_topology_relationship(normalized):
        return ReviewIntent(
            intent_type="topology_relationship",
            evidence_need="structural_path_witness",
            suggested_next_tools=("get_reachable_equipment",),
        )
    if _question_token(question):
        return ReviewIntent(
            intent_type="object_lookup",
            evidence_need="candidate_objects",
            suggested_next_tools=("find_equipment",),
        )
    return ReviewIntent(intent_type="conversation", evidence_need="none")


def _looks_like_source_mutation(normalized: str) -> bool:
    mutation_phrases = (
        "delete ",
        "remove ",
        "edit ",
        "modify ",
        "change ",
        "replace ",
        "connect ",
        "disconnect ",
    )
    return any(phrase in f"{normalized} " for phrase in mutation_phrases)


def _looks_like_rule_evaluation(normalized: str) -> bool:
    """Deontic/compliance wording alone marks a rule claim; bare quantifiers
    do not. "Any valves?" is a lookup, not a rule -- a quantifier only counts
    when the question also claims a condition over the quantified set."""
    deontic_tokens = (
        " violation",
        " violates",
        " comply",
        " compliant",
        " required",
        " require ",
        " must ",
        " shall ",
        " rule",
        " standard",
    )
    padded = f" {normalized} "
    if any(token in padded for token in deontic_tokens):
        return True
    quantifier_tokens = (" all ", " every ", " any ", " no ", " none ")
    condition_markers = (
        " have ",
        " has ",
        " satisf",
        " connect",
        " reach",
        " contain",
        " include",
    )
    return any(token in padded for token in quantifier_tokens) and any(
        marker in padded for marker in condition_markers
    )


def _looks_like_topology_relationship(normalized: str) -> bool:
    relationship_tokens = (
        "connected",
        "connects",
        "connection",
        "reachable",
        "downstream",
        "upstream",
        "feed",
        "feeds",
        "path",
    )
    return (
        _question_token(normalized) != "" or _looks_like_pid_reference(normalized)
    ) and any(token in normalized for token in relationship_tokens)


def _looks_like_pid_reference(normalized: str) -> bool:
    return any(character.isdigit() for character in normalized) and (
        "-" in normalized or "_" in normalized
    )


def _tool_names(tool_call_trace: list[dict[str, object]]) -> set[str]:
    return {
        str(item.get("tool_name"))
        for item in tool_call_trace
        if isinstance(item.get("tool_name"), str)
    }


def _tool_trace_satisfies_intent(
    intent: ReviewIntent, tool_call_trace: list[dict[str, object]]
) -> bool:
    names = _tool_names(tool_call_trace)
    if intent.evidence_need == "none":
        return True
    if intent.evidence_need == "candidate_objects":
        return "find_equipment" in names
    if intent.evidence_need == "structural_path_witness":
        return any(
            trace.get("tool_name") == "get_reachable_equipment"
            and _has_structural_witness_result(trace.get("tool_result"))
            for trace in tool_call_trace
        )
    if intent.evidence_need == "rule_result":
        return any(
            (
                trace.get("tool_name") == "execute_bundled_query_template"
                and _tool_result_status(trace.get("tool_result")) == "answered"
            )
            or (
                trace.get("tool_name") == "propose_temporary_datalog"
                and _tool_result_status(trace.get("tool_result"))
                in {"confirmation_required", "executed", "answered"}
            )
            for trace in tool_call_trace
        )
    return True


def _has_structural_witness_result(tool_result: object) -> bool:
    if not isinstance(tool_result, dict):
        return False
    if "reachable" not in tool_result:
        return bool(tool_result.get("error"))
    reachable = tool_result.get("reachable")
    if not isinstance(reachable, list):
        return False
    if not reachable:
        return True
    return all(
        isinstance(item, dict) and isinstance(item.get("witness"), dict)
        for item in reachable
    )


def _tool_result_status(tool_result: object) -> str:
    if isinstance(tool_result, dict):
        return str(tool_result.get("status", ""))
    return ""


def _sufficiency_failure(intent: ReviewIntent) -> dict[str, object]:
    return {
        "status": "insufficient_evidence",
        "code": "evidence.insufficient_for_claim",
        "intent_type": intent.intent_type,
        "evidence_need": intent.evidence_need,
        "message": (
            "The proposed answer does not have the evidence kind required for the "
            f"{intent.intent_type} request."
        ),
        "suggested_next_tools": list(intent.suggested_next_tools),
        "recoverable": True,
    }


def _faithfulness_gate_attempt_count(tool_call_trace: list[dict[str, object]]) -> int:
    return sum(
        1
        for trace in tool_call_trace
        if trace.get("tool_name") == "propose_temporary_datalog"
        and isinstance((result := trace.get("tool_result")), dict)
        and isinstance(result.get("faithfulness_gate"), dict)
    )


def _faithfulness_repair_nudge(diagnostics: list[dict[str, object]]) -> str:
    blockers = "; ".join(
        str(item.get("message", "")) for item in diagnostics if item.get("message")
    )
    return (
        "Your answer did not include a faithful generated program, and no "
        f"repair has been attempted yet. Blocking diagnostics: {blockers} "
        "Revise the program and its back-translated intent to resolve these "
        "diagnostics, then call propose_temporary_datalog again before "
        "answering."
    )


# A failed gate with repair guidance must be retried at least once before the
# turn may end in faithfulness.no_faithful_program (bead 3qo.9.11): a total of
# two gate attempts = the original proposal plus one mandatory repair.
MIN_FAITHFULNESS_GATE_ATTEMPTS_BEFORE_GIVING_UP = 2


def _faithfulness_gate_diagnostics(
    tool_call_trace: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Diagnostics and attempts for the latest failed propose_temporary_datalog
    gate result, or None if no proposal has gone through the gate and failed."""
    proposal_results = [
        result
        for trace in tool_call_trace
        if trace.get("tool_name") == "propose_temporary_datalog"
        and isinstance((result := trace.get("tool_result")), dict)
        and isinstance(result.get("faithfulness_gate"), dict)
    ]
    if not proposal_results:
        return None
    latest = proposal_results[-1]
    if latest["faithfulness_gate"].get("status") != "failed":
        return None
    gate = latest["faithfulness_gate"]
    raw_diagnostics = gate.get("diagnostics", [])
    diagnostics: list[dict[str, object]] = [
        dict(item) for item in raw_diagnostics if isinstance(item, dict)
    ]
    if not diagnostics:
        diagnostics = [
            {
                "code": "faithfulness.evidence_incomplete",
                "message": "The layered faithfulness gate did not produce usable diagnostics.",
            }
        ]
    attempts: list[dict[str, object]] = [
        dict(attempt)
        for result in proposal_results
        for attempt in result.get("faithfulness_gate_attempts", [])
        if isinstance(attempt, dict)
    ]
    return diagnostics, attempts


def _missing_faithful_program_result(
    tool_call_trace: list[dict[str, object]],
) -> QATurnResult | None:
    found = _faithfulness_gate_diagnostics(tool_call_trace)
    if found is None:
        return None
    diagnostics, attempts = found
    blockers = "; ".join(
        str(item.get("message", "")) for item in diagnostics if item.get("message")
    )
    outcome = {
        "status": "missing_capability",
        "code": "faithfulness.no_faithful_program",
        "diagnostics": diagnostics,
        "attempts": attempts,
    }
    return QATurnResult(
        answer_text=(
            "I could not produce a faithful generated program, so no engineering "
            f"verdict was returned. Blocking diagnostics: {blockers}"
        ),
        evidence_references=[],
        rejected_references=[],
        interpreted_object_ids=[],
        tool_call_trace=tool_call_trace,
        grounding_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
        source_grounded=False,
        disclosure=_POSTURE_DISCLOSURES[POSTURE_SOURCE_DATA_UNAVAILABLE],
        deterministic_verdict=None,
        witnesses=[],
        route_artifact=None,
        trace_events=[{"event": "route_outcome", "outcome": outcome}],
    )


class ScriptedQATurnProvider:
    """Deterministic provider used as the OSS default and in tests.

    Behaviors it demonstrates without a real model:
    - Ambiguous text yields several plausible candidates (multi-candidate answer).
    - Follow-ups that use a pronoun reuse prior evidence identities.
    - It discloses which objects it interpreted the question to mean.
    """

    def __init__(
        self, *, max_candidates: int = 3, step_delay_seconds: float = 0.0
    ) -> None:
        self._step = 0
        self._max_candidates = max_candidates
        self._mode = "direct"
        self._candidates: list[str] = []
        self._reachable_ids: list[str] = []
        self._question = ""
        self._anchor = ""
        self._step_delay_seconds = step_delay_seconds

    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ToolCall | FinalAnswer:
        # Test-only pacing (bead 2ki.12): gives a polling client a real window
        # to observe the turn mid-flight instead of it resolving before the
        # first poll tick. Zero by default -- never sleeps in production.
        if self._step_delay_seconds:
            time.sleep(self._step_delay_seconds)
        step = self._step
        self._step += 1

        if step == 0:
            self._question = _latest_user_question(messages)
            prior_ids = _prior_evidence_ids(messages)
            if prior_ids and _looks_like_follow_up(self._question):
                self._mode = "follow_up"
                self._candidates = prior_ids[: self._max_candidates]
                return ToolCall(
                    tool_name="get_reachable_equipment",
                    tool_input={"equipment_id": self._candidates[0]},
                    tool_call_id="scripted-followup-reachable",
                )
            return ToolCall(
                tool_name="find_equipment",
                tool_input={"pattern": ""},
                tool_call_id="scripted-find",
            )

        if self._mode == "follow_up":
            self._reachable_ids = self._read_reachable(messages)
            references = self._candidates + self._reachable_ids[:2]
            answer_text = (
                "Continuing with the previously identified "
                f"{self._describe(self._candidates)}: "
                f"{len(self._reachable_ids)} reachable object(s) via the structural graph."
            )
            return FinalAnswer(
                answer_text=answer_text,
                evidence_references=references,
                interpreted_object_ids=list(self._candidates),
            )

        if step == 1:
            matches = self._read_matches(messages)
            token = _question_token(self._question)
            self._candidates = self._select_candidates(matches, token)
            if not self._candidates:
                return FinalAnswer(
                    answer_text="No matching equipment was found in this source.",
                    evidence_references=[],
                    interpreted_object_ids=[],
                )
            self._anchor = self._candidates[0]
            if _looks_like_rule_evaluation(self._question.lower()):
                # Rule-like questions cannot be answered from sampled
                # retrieval; sample reachability once, then escalate to the
                # automatic temporary Datalog capability instead of
                # dead-ending (37x.22.34.2 / 3qo.9.9). Prefer a piping/structural
                # anchor: equipment nodes are frequently isolated in the
                # structural view, and an empty sample demos nothing.
                self._mode = "rule_evaluation"
                self._anchor = self._rule_evaluation_anchor(matches)
            return ToolCall(
                tool_name="get_reachable_equipment",
                tool_input={"equipment_id": self._anchor},
                tool_call_id="scripted-reachable",
            )

        if self._mode == "rule_evaluation":
            offered = {tool["function"]["name"] for tool in tools}
            executed = self._latest_executed_temporary_datalog(messages)
            if executed is not None:
                evidence_ids = self._executed_evidence_ids(executed)
                return FinalAnswer(
                    answer_text=(
                        "The temporary topology rule was evaluated automatically "
                        f"against the loaded source ({len(evidence_ids)} matching "
                        "object(s))."
                    ),
                    evidence_references=evidence_ids,
                    grounding_posture=POSTURE_SOURCE_GROUNDED,
                )
            if "propose_temporary_datalog" not in offered:
                self._reachable_ids = self._read_reachable(messages)
                return ToolCall(
                    tool_name="report_template_no_fit",
                    tool_input={
                        "reason": (
                            "No bundled template represents this sampled universal "
                            "rule condition."
                        ),
                        "structured_intent": self._rule_evaluation_structured_intent(),
                    },
                    tool_call_id="scripted-template-no-fit",
                )
            return self._propose_temporary_datalog()
        self._reachable_ids = self._read_reachable(messages)
        references = self._candidates + self._reachable_ids[:2]
        if len(self._candidates) > 1:
            answer_text = (
                f"That request is ambiguous; I interpreted it as "
                f"{len(self._candidates)} candidates ({self._describe(self._candidates)}). "
                f"From the first, {len(self._reachable_ids)} object(s) are reachable."
            )
        else:
            answer_text = (
                f"I interpreted this as {self._describe(self._candidates)}. "
                f"{len(self._reachable_ids)} object(s) are reachable via the structural graph."
            )
        return FinalAnswer(
            answer_text=answer_text,
            evidence_references=references,
            interpreted_object_ids=list(self._candidates),
        )

    def _select_candidates(
        self, matches: list[dict[str, object]], token: str
    ) -> list[str]:
        if token:
            filtered = [
                match
                for match in matches
                if token in str(match.get("node_class", "")).lower()
                or token in str(match.get("label", "")).lower()
            ]
            if filtered:
                matches = filtered
        return [str(match["evidence_id"]) for match in matches[: self._max_candidates]]

    def _rule_evaluation_anchor(self, matches: list[dict[str, object]]) -> str:
        """Pick the reachability anchor for a rule-evaluation proposal.

        Prefer piping/structural objects: equipment nodes are frequently
        isolated in the structural view, so anchoring there samples nothing.
        """
        for match in matches:
            described = (
                f"{match.get('node_class', '')} {match.get('label', '')}".lower()
            )
            if "pip" in described or "segment" in described or "line" in described:
                return str(match["evidence_id"])
        return self._candidates[0]

    def _rule_evaluation_structured_intent(self) -> dict[str, object]:
        if self._reachable_ids:
            return {
                "source_classes": ["TopologyObject"],
                "target_classes": ["TopologyObject"],
                "source_role": "process_connection_source",
                "target_role": "process_connection_target",
                "graph_scope": "all_topology",
                "direction": "directed",
                "quantifier": "any",
                "negated": False,
                "output_obligations": ["matching_target_ids"],
            }
        return {
            "source_classes": ["ResolvedTopologyObject"],
            "target_classes": ["ResolvedTopologyObject"],
            "source_role": "resolved_object",
            "target_role": "answer_object",
            "graph_scope": "all_topology",
            "direction": "undirected",
            "quantifier": "any",
            "negated": False,
            "output_obligations": ["resolved_answer_ids"],
        }

    def _propose_temporary_datalog(self) -> ToolCall:
        """Escalate a rule-like question to automatic temporary Datalog.

        The restatement states exactly what the temporary query computes --
        nothing more. If the sampled source has reachable objects, propose a
        generic-schema join over direct process connections; otherwise fall
        back to the resolved objects themselves as literal facts.
        """
        structured_intent = self._rule_evaluation_structured_intent()
        if self._reachable_ids:
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": self._question,
                    # Deliberately beyond the historical reachable-only shim:
                    # the executor is a real Souffle engine over the generic
                    # schema, so the OSS default provider exercises an IDB join
                    # that the old regex path could never evaluate.
                    "generated_datalog": encode_structured_intent_program(
                        (
                            ".decl answer(x:symbol)\n"
                            ".output answer\n"
                            "answer(result) :- direct_process_connection(_, result)."
                        ),
                        structured_intent,
                    ),
                    "formal_restatement": (
                        "Return every object that appears as a direct process-"
                        "connection target in the loaded source."
                    ),
                    "faithfulness_review": {
                        "status": "faithful",
                        "back_translated_intent": structured_intent,
                        "diagnostics": [],
                    },
                    "resolved_identity_ids": [],
                },
                tool_call_id="scripted-propose-datalog",
            )
        facts = "\n".join(f'answer("{cid}").' for cid in self._candidates)
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": self._question,
                "generated_datalog": encode_structured_intent_program(
                    ".decl answer(x:symbol)\n.output answer\n" + facts,
                    structured_intent,
                ),
                "formal_restatement": (
                    "Return the resolved objects "
                    f"{self._describe(self._candidates)} as the temporary "
                    "check result; no further objects were structurally "
                    "reachable from the sampled anchor."
                ),
                "faithfulness_review": {
                    "status": "faithful",
                    "back_translated_intent": structured_intent,
                    "diagnostics": [],
                },
                "resolved_identity_ids": list(self._candidates),
            },
            tool_call_id="scripted-propose-datalog",
        )

    @staticmethod
    def _read_matches(messages: list[dict[str, object]]) -> list[dict[str, object]]:
        for message in reversed(messages):
            if message.get("role") == "tool":
                result = json.loads(str(message.get("content", "{}")))
                return list(result.get("matches", []))
        return []

    @staticmethod
    def _read_reachable(messages: list[dict[str, object]]) -> list[str]:
        for message in reversed(messages):
            if message.get("role") == "tool":
                result = json.loads(str(message.get("content", "{}")))
                return [
                    str(item["evidence_id"]) for item in result.get("reachable", [])
                ]
        return []

    @staticmethod
    def _latest_executed_temporary_datalog(
        messages: list[dict[str, object]],
    ) -> dict[str, object] | None:
        for message in reversed(messages):
            if message.get("role") != "tool":
                continue
            result = json.loads(str(message.get("content", "{}")))
            if not isinstance(result, dict):
                continue
            if (
                result.get("executed") is True
                and result.get("status") == "answered"
                and result.get("execution_mode") == "automatic"
            ):
                return result
        return None

    @staticmethod
    def _executed_evidence_ids(executed: dict[str, object]) -> list[str]:
        evidence = executed.get("evidence")
        if isinstance(evidence, dict):
            items = evidence.get("items")
            if isinstance(items, list):
                return [
                    str(item["id"])
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ]
        deterministic = executed.get("disclosure")
        if isinstance(deterministic, dict):
            result = deterministic.get("deterministic_result")
            if isinstance(result, dict):
                matched = result.get("matched_object_ids")
                if isinstance(matched, list):
                    return [str(item) for item in matched if isinstance(item, str)]
        return []

    @staticmethod
    def _describe(ids: list[str]) -> str:
        return ", ".join(ids) if ids else "no objects"


# Compaction: past this many carried turns, older prose is folded into a single
# summary turn. The summary preserves prior user questions (decisions) and the
# union of prior evidence identities so follow-ups can still reuse them; the
# summary prose is context only and is re-validated like any prior turn, so it
# can never smuggle prose in as engineering evidence.
DEFAULT_MAX_CONVERSATION_TURNS = 12

# Heavier reasoning models (large MoE models routed through OpenRouter/BYOK)
# can need more tool-call round trips than the harness was originally tuned
# against (claude-sonnet-4, ornith:35b) to converge on a final answer for
# broad, open-ended questions -- 10 was too tight and produced hard failures
# with no partial credit. There is no guarantee any fixed cap prevents this
# for a given model; raising it only widens the window.
DEFAULT_MAX_ROUNDS = 20

# Reported to an optional progress callback once per round so callers (e.g. the
# web API's turn lifecycle) can surface live progress instead of a static
# "working" placeholder for the whole (potentially long) tool-calling loop.
# (round_number, max_rounds, tool_name, tool_input, reasoning): tool_input and
# reasoning surface what the model is doing and why (bead 3qo.9.12); both are
# None when the provider supplied nothing -- never fabricated.
RoundProgress = Callable[
    [int, int, str | None, dict[str, object] | None, str | None], None
]

# Model reasoning recorded into the audit trace is bounded at the source so no
# unbounded provider output enters persisted proposal/audit records.
MAX_TRACE_REASONING_LENGTH = 2_000


def compact_conversation(
    conversation: list[ConversationTurn],
    *,
    max_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
) -> list[ConversationTurn]:
    """Fold older conversation turns into a leading summary turn once the history
    exceeds ``max_turns``.

    Grounding is preserved structurally: the summary turn carries every prior
    user question (the decisions that shaped the thread) and the ordered union of
    the folded turns' evidence identities. Recent turns are kept verbatim. Prior
    prose is never concatenated into the summary as fact; only the questions and
    the evidence identities survive, and identities are re-validated downstream
    against the current topology before reuse.
    """
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")
    if len(conversation) <= max_turns:
        return list(conversation)

    # One slot is reserved for the summary; keep the most recent turns verbatim.
    recent_count = max_turns - 1
    folded = conversation[: len(conversation) - recent_count]
    recent = conversation[len(conversation) - recent_count :] if recent_count else []

    preserved_ids: list[str] = []
    questions: list[str] = []
    for turn in folded:
        if turn.question:
            questions.append(turn.question)
        for reference in turn.evidence_references:
            if reference not in preserved_ids:
                preserved_ids.append(reference)

    summary_text = "Earlier in this conversation you asked: " + " ".join(
        f"({index}) {question}" for index, question in enumerate(questions, start=1)
    )
    summary = ConversationTurn(
        question="[earlier conversation summary]",
        answer_text=summary_text,
        evidence_references=preserved_ids,
    )
    return [summary, *recent]


def run_grounded_qa_turn(
    *,
    question: str,
    topology_tools: TopologyTools,
    provider: QATurnProvider,
    conversation: list[ConversationTurn] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_conversation_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
    on_round: RoundProgress | None = None,
    resume_route_receipt: dict[str, object] | None = None,
    constraints: RunConstraints | None = None,
    steering: Steering | None = None,
    provider_cost: Callable[[], float] | None = None,
    clock: Callable[[], float] | None = None,
) -> QATurnResult:
    """Execute a grounded QA turn: model calls tools, backend executes them, model answers.

    Conversation state seeds prior turns so the model can resolve follow-up
    references. Prior evidence identities are re-validated against the current
    topology before reuse; prior prose is never promoted to evidence.
    """
    intent = _classify_review_intent(question)
    if intent.intent_type == "source_mutation":
        tool_result = topology_tools.execute("mutate_source_graph", {})
        trace = [
            {
                "tool_call_id": "intent-denied-source-mutation",
                "tool_name": "mutate_source_graph",
                "tool_input": {},
                "tool_result": tool_result,
            }
        ]
        return QATurnResult(
            answer_text=(
                "I cannot modify the loaded source graph. I can inspect the "
                "topology or help write a review note with grounded evidence."
            ),
            evidence_references=[],
            rejected_references=[],
            interpreted_object_ids=[],
            tool_call_trace=trace,
            grounding_posture=POSTURE_OUT_OF_SCOPE,
            source_grounded=False,
            disclosure=None,
        )
    policy_outcome = topology_tools.policy_route_outcome(question)
    if policy_outcome is not None:
        return QATurnResult(
            answer_text=(
                "Permission or defeasible exceptions cannot be decided from "
                "monotone drawing facts; human review is required."
            ),
            evidence_references=[],
            rejected_references=[],
            interpreted_object_ids=[],
            tool_call_trace=[],
            grounding_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
            source_grounded=False,
            trace_events=[
                {
                    "event": "route_outcome",
                    "outcome": policy_outcome,
                }
            ],
        )
    topology_tools.begin_request(question, resume_route_receipt=resume_route_receipt)
    known_ids = topology_tools.known_evidence_ids()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": topology_tools.system_prompt()}
    ]
    carried = compact_conversation(
        list(conversation or []), max_turns=max_conversation_turns
    )
    for turn in carried:
        valid_prior = [ref for ref in turn.evidence_references if ref in known_ids]
        messages.append({"role": "user", "content": turn.question})
        messages.append(
            {
                "role": "assistant",
                "content": turn.answer_text,
                "grounded_evidence_ids": valid_prior,
            }
        )
    messages.append({"role": "user", "content": question})
    last_insufficient_answer: FinalAnswer | None = None
    tool_call_trace: list[dict[str, object]] = []

    # Steering + answer-constraints (bead 3qo.9.8). Every limit only *tightens*
    # the run: the effective turn cap is clamped to the operational ceiling and
    # never raised, and capabilities can only be narrowed -- never widened, and
    # validators (backend gates inside execute()) are never disabled.
    now = clock or time.monotonic
    run_started_at = now()
    effective_max_rounds = max_rounds
    if constraints is not None and constraints.max_rounds is not None:
        effective_max_rounds = max(1, min(max_rounds, constraints.max_rounds))
    user_turn_cap_binds = effective_max_rounds < max_rounds
    duration_limit = constraints.max_duration_seconds if constraints else None
    cost_limit = constraints.max_provider_cost if constraints else None
    allowed_capabilities = _resolve_allowed_capabilities(constraints, topology_tools)

    def _poll_steering() -> str | None:
        if steering is not None:
            directive = steering()
            if directive in (STEER_STOP, STEER_ANSWER_NOW):
                return directive
        if duration_limit is not None and (now() - run_started_at) >= duration_limit:
            return "duration_limit"
        if (
            cost_limit is not None
            and provider_cost is not None
            and provider_cost() >= cost_limit
        ):
            return "cost_limit"
        return None

    for round_index in range(effective_max_rounds):
        steer = _poll_steering()
        if steer is not None:
            return _steered_result(
                steer, known_ids=known_ids, tool_call_trace=tool_call_trace
            )
        response = provider.complete_with_tools(
            messages=messages,
            tools=_narrow_tool_definitions(
                topology_tools.tool_definitions(), allowed_capabilities
            ),
        )
        if on_round is not None and isinstance(response, ToolCall):
            on_round(
                round_index + 1,
                max_rounds,
                response.tool_name,
                dict(response.tool_input),
                response.reasoning,
            )

        if isinstance(response, FinalAnswer):
            if _tool_trace_satisfies_intent(intent, tool_call_trace):
                return _finalize(response, known_ids, tool_call_trace)
            gate_diagnostics = _faithfulness_gate_diagnostics(tool_call_trace)
            if gate_diagnostics is not None:
                remaining_rounds = max_rounds - round_index - 1
                diagnostics, _attempts = gate_diagnostics
                if (
                    remaining_rounds > 0
                    and _faithfulness_gate_attempt_count(tool_call_trace)
                    < MIN_FAITHFULNESS_GATE_ATTEMPTS_BEFORE_GIVING_UP
                ):
                    messages.append(
                        {
                            "role": "user",
                            "content": _faithfulness_repair_nudge(diagnostics),
                        }
                    )
                    continue
                missing_capability = _missing_faithful_program_result(tool_call_trace)
                assert missing_capability is not None
                return missing_capability
            last_insufficient_answer = response
            tool_result = _sufficiency_failure(intent)
            tool_call_trace.append(
                {
                    "tool_call_id": "evidence-sufficiency",
                    "tool_name": "__evidence_sufficiency__",
                    "tool_input": {"question": question},
                    "tool_result": tool_result,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Backend evidence sufficiency check failed: "
                        f"{tool_result['message']} Suggested next tools: "
                        f"{', '.join(tool_result['suggested_next_tools'])}."
                    ),
                }
            )
            continue

        if isinstance(response, ToolCall):
            if (
                allowed_capabilities is not None
                and response.tool_name not in allowed_capabilities
            ):
                # A user capability narrowing blocks this tool. The backend
                # refuses execution rather than only hiding the tool in the
                # prompt (bead 3qo.9.8); validators are not model-facing tools
                # and so are never disabled by narrowing.
                blocked = {
                    "status": "capability_unavailable",
                    "code": "capability.constrained_out",
                    "tool_name": response.tool_name,
                    "message": (
                        "This capability is unavailable under the current answer "
                        "constraints."
                    ),
                }
                tool_call_trace.append(
                    {
                        "tool_call_id": response.tool_call_id,
                        "tool_name": response.tool_name,
                        "tool_input": response.tool_input,
                        "tool_result": blocked,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"The capability '{response.tool_name}' is unavailable "
                            "under the active answer constraints. Use an available "
                            "capability or answer from the evidence already gathered."
                        ),
                    }
                )
                continue
            tool_result = topology_tools.execute(
                response.tool_name, response.tool_input
            )
            tool_result_json = json.dumps(tool_result)

            trace_entry: dict[str, object] = {
                "tool_call_id": response.tool_call_id,
                "tool_name": response.tool_name,
                "tool_input": response.tool_input,
                "tool_result": tool_result,
            }
            if response.reasoning:
                trace_entry["reasoning"] = response.reasoning[
                    :MAX_TRACE_REASONING_LENGTH
                ]
            tool_call_trace.append(trace_entry)

            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": response.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": response.tool_name,
                                "arguments": json.dumps(response.tool_input),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": response.tool_call_id,
                    "content": tool_result_json,
                }
            )
            continue

        raise TypeError(f"Unexpected provider response type: {type(response)}")
    if user_turn_cap_binds:
        # A user turn constraint (not the operational ceiling) ended the run;
        # synthesize from validated artifacts rather than raising (bead 3qo.9.8).
        return _steered_result(
            "turn_limit", known_ids=known_ids, tool_call_trace=tool_call_trace
        )
    missing_capability = _missing_faithful_program_result(tool_call_trace)
    if missing_capability is not None:
        return missing_capability
    if last_insufficient_answer is not None:
        return _finalize(
            FinalAnswer(
                answer_text=(
                    "I could not ground that answer with the required evidence. "
                    "Please narrow the question or approve the suggested deterministic check."
                ),
                evidence_references=last_insufficient_answer.evidence_references,
                interpreted_object_ids=last_insufficient_answer.interpreted_object_ids,
            ),
            known_ids,
            tool_call_trace,
        )
    raise RuntimeError(
        f"QA harness exceeded {max_rounds} rounds without a final answer."
    )


def _extract_deterministic_artifacts(
    tool_call_trace: list[dict[str, object]],
) -> tuple[
    bool, str | None, list[str], dict[str, object] | None, list[dict[str, object]]
]:
    """Locate the answered deterministic route in the trace, if any.

    Both routes ground an answer with a real engine run over the loaded graph:
    an answered bundled-template execution, and an automatically executed
    generated program (3qo.9.7) whose gates all passed before the run. Returns
    (has_result, verdict, witnesses, route_artifact, trace_events).
    """
    deterministic_verdict: str | None = None
    witnesses: list[str] = []
    route_artifact: dict[str, object] | None = None
    trace_events: list[dict[str, object]] = []
    has_deterministic_result = False
    for trace in tool_call_trace:
        tool_name = trace.get("tool_name")
        tool_result = trace.get("tool_result")
        if not isinstance(tool_result, dict) or tool_result.get("status") != "answered":
            continue
        is_answered_template = tool_name == "execute_bundled_query_template"
        is_executed_generated = (
            tool_name == "propose_temporary_datalog"
            and tool_result.get("executed") is True
        )
        if not (is_answered_template or is_executed_generated):
            continue
        has_deterministic_result = True
        verdict = tool_result.get("verdict")
        if isinstance(verdict, str):
            deterministic_verdict = verdict
        raw_witnesses = tool_result.get("witnesses")
        if isinstance(raw_witnesses, list):
            witnesses = [str(witness) for witness in raw_witnesses]
        raw_route = tool_result.get("route_artifact")
        if isinstance(raw_route, dict):
            route_artifact = dict(raw_route)
        raw_events = tool_result.get("trace_events")
        if isinstance(raw_events, list):
            trace_events = [
                dict(event) for event in raw_events if isinstance(event, dict)
            ]
        break
    return (
        has_deterministic_result,
        deterministic_verdict,
        witnesses,
        route_artifact,
        trace_events,
    )


def _finalize(
    response: FinalAnswer,
    known_ids: set[str],
    tool_call_trace: list[dict[str, object]],
) -> QATurnResult:
    valid_references: list[str] = []
    rejected_references: list[str] = []
    for reference in response.evidence_references:
        bucket = valid_references if reference in known_ids else rejected_references
        if reference not in bucket:
            bucket.append(reference)

    interpreted: list[str] = []
    for reference in response.interpreted_object_ids:
        if reference in known_ids and reference not in interpreted:
            interpreted.append(reference)

    (
        has_deterministic_result,
        deterministic_verdict,
        witnesses,
        route_artifact,
        trace_events,
    ) = _extract_deterministic_artifacts(tool_call_trace)

    posture, source_grounded, disclosure = _resolve_grounding(
        response.grounding_posture,
        valid_references,
        has_deterministic_result=has_deterministic_result,
    )

    return QATurnResult(
        answer_text=response.answer_text,
        evidence_references=valid_references,
        rejected_references=rejected_references,
        interpreted_object_ids=interpreted,
        tool_call_trace=tool_call_trace,
        grounding_posture=posture,
        source_grounded=source_grounded,
        disclosure=disclosure,
        deterministic_verdict=deterministic_verdict,
        witnesses=witnesses,
        route_artifact=route_artifact,
        trace_events=trace_events,
    )


def _resolve_grounding(
    declared_posture: str,
    valid_references: list[str],
    *,
    has_deterministic_result: bool = False,
) -> tuple[str, bool, str | None]:
    """Enforce the posture <-> evidence boundary deterministically.

    The backend never decides what a question is about. It only checks that a
    model-declared grounding posture is consistent with the evidence references
    that survived validation, and attaches an authoritative disclosure whenever
    the answer is not a validated conclusion derived from the loaded source.

    An answered deterministic template execution in the same turn counts as
    source grounding even when its verdict produced zero witnesses to cite
    (e.g. a clean ``no_violation`` result): the answer is backed by validated
    bindings plus a real engine run over the loaded graph.
    """
    has_evidence = bool(valid_references) or has_deterministic_result

    if declared_posture == POSTURE_SOURCE_GROUNDED:
        if has_evidence:
            return POSTURE_SOURCE_GROUNDED, True, None
        # A source conclusion was claimed but nothing was validated: it cannot be
        # presented as grounded.
        return (
            POSTURE_UNSUPPORTED_SOURCE_CLAIM,
            False,
            _POSTURE_DISCLOSURES[POSTURE_UNSUPPORTED_SOURCE_CLAIM],
        )

    if declared_posture in _POSTURE_DISCLOSURES:
        # Explicitly non-source postures (general knowledge, missing source data,
        # out of scope) are always disclosed as not derived from the source.
        return declared_posture, False, _POSTURE_DISCLOSURES[declared_posture]

    # Legacy / unspecified posture preserves prior behavior: an answer is treated
    # as source-grounded exactly when it carries validated evidence, with no
    # backend-authored disclosure.
    return POSTURE_UNSPECIFIED, has_evidence, None


# Routes that carry a deterministic verdict (handled via witnesses/route
# artifact); their ids are not re-collected as ordinary established facts.
_VERDICT_ROUTE_TOOLS = {
    "execute_bundled_query_template",
    "propose_temporary_datalog",
}

# Blocker phrasing per reason a steered run ended without model-authored answer.
_STEER_BLOCKERS: dict[str, str] = {
    STEER_ANSWER_NOW: "Answer Now was requested, so further exploration stopped.",
    "turn_limit": "Your turn limit was reached, so further exploration stopped.",
    "duration_limit": "Your time limit was reached, so further exploration stopped.",
    "cost_limit": (
        "Your provider-cost limit was reached, so further exploration stopped."
    ),
}


def _scan_evidence_ids(node: object, collected: list[str]) -> None:
    """Collect string values under ``id``/``evidence_id`` keys, recursively."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("id", "evidence_id") and isinstance(value, str):
                collected.append(value)
            _scan_evidence_ids(value, collected)
    elif isinstance(node, list):
        for item in node:
            _scan_evidence_ids(item, collected)


def _established_evidence_ids(
    tool_call_trace: list[dict[str, object]], known_ids: set[str]
) -> list[str]:
    """Validated evidence object ids surfaced by read-only retrieval tools so
    far. Verdict-route ids are excluded (reported through witnesses instead)."""
    ordered: list[str] = []
    for trace in tool_call_trace:
        if trace.get("tool_name") in _VERDICT_ROUTE_TOOLS:
            continue
        result = trace.get("tool_result")
        if not isinstance(result, dict):
            continue
        found: list[str] = []
        _scan_evidence_ids(result, found)
        for ident in found:
            if ident in known_ids and ident not in ordered:
                ordered.append(ident)
    return ordered


def _rejected_attempt_summaries(
    tool_call_trace: list[dict[str, object]],
) -> list[str]:
    """Human-readable notes for attempts the backend rejected during the run."""
    summaries: list[str] = []
    for trace in tool_call_trace:
        name = trace.get("tool_name")
        result = trace.get("tool_result")
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        gate = result.get("faithfulness_gate")
        if name == "report_template_no_fit":
            summaries.append("No bundled template faithfully matched the question.")
        elif isinstance(gate, dict) and gate.get("status") == "failed":
            summaries.append("A generated program failed the faithfulness gate.")
        elif name == "propose_temporary_datalog" and status not in (
            "answered",
            "confirmation_required",
        ):
            code = str(result.get("code") or status or "rejected")
            summaries.append(f"A generated-Datalog proposal was rejected ({code}).")
    return summaries


def _steered_result(
    reason: str,
    *,
    known_ids: set[str],
    tool_call_trace: list[dict[str, object]],
) -> QATurnResult:
    """Backend-authored result when a human directive or answer-constraint ends
    the run. Reads only completed validated artifacts already in the trace: it
    never runs another tool, so safety and faithfulness gates cannot be bypassed
    (bead 3qo.9.8)."""
    (
        has_deterministic_result,
        deterministic_verdict,
        witnesses,
        route_artifact,
        trace_events,
    ) = _extract_deterministic_artifacts(tool_call_trace)
    events = list(trace_events)

    if reason == STEER_STOP:
        events.append({"event": "steering", "directive": STEER_STOP})
        return QATurnResult(
            answer_text=(
                "The run was stopped. The completed trace and any validated "
                "artifacts are preserved."
            ),
            evidence_references=[],
            rejected_references=[],
            interpreted_object_ids=[],
            tool_call_trace=tool_call_trace,
            grounding_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
            source_grounded=False,
            disclosure=_POSTURE_DISCLOSURES[POSTURE_SOURCE_DATA_UNAVAILABLE],
            deterministic_verdict=deterministic_verdict,
            witnesses=witnesses,
            route_artifact=route_artifact,
            trace_events=events,
            steering_outcome=STEER_STOP,
        )

    established = _established_evidence_ids(tool_call_trace, known_ids)
    events.append(
        {"event": "steering", "directive": STEER_ANSWER_NOW, "reason": reason}
    )

    if has_deterministic_result:
        # Criterion 1: synthesize from the completed validated verdict.
        verdict_text = deterministic_verdict or "a deterministic result"
        answer_text = (
            f"Answering now from the completed validated result: {verdict_text}."
        )
        if witnesses:
            answer_text += " Witnesses: " + ", ".join(witnesses) + "."
        posture, source_grounded, disclosure = _resolve_grounding(
            POSTURE_SOURCE_GROUNDED,
            established,
            has_deterministic_result=True,
        )
        return QATurnResult(
            answer_text=answer_text,
            evidence_references=established,
            rejected_references=[],
            interpreted_object_ids=[],
            tool_call_trace=tool_call_trace,
            grounding_posture=posture,
            source_grounded=source_grounded,
            disclosure=disclosure,
            deterministic_verdict=deterministic_verdict,
            witnesses=witnesses,
            route_artifact=route_artifact,
            trace_events=events,
            steering_outcome=reason,
        )

    # Criterion 2: no validated verdict -- report established facts, rejected
    # attempts, and the blocker, without guessing a conclusion.
    rejected = _rejected_attempt_summaries(tool_call_trace)
    parts = [_STEER_BLOCKERS.get(reason, _STEER_BLOCKERS[STEER_ANSWER_NOW])]
    if established:
        parts.append("Established facts so far: " + ", ".join(established) + ".")
    else:
        parts.append("No validated evidence was established before the interrupt.")
    if rejected:
        parts.append("Rejected attempts: " + " ".join(rejected))
    parts.append(
        "No validated verdict was reached, so no engineering conclusion is asserted."
    )
    return QATurnResult(
        answer_text=" ".join(parts),
        evidence_references=established,
        rejected_references=[],
        interpreted_object_ids=[],
        tool_call_trace=tool_call_trace,
        grounding_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
        source_grounded=False,
        disclosure=_POSTURE_DISCLOSURES[POSTURE_SOURCE_DATA_UNAVAILABLE],
        deterministic_verdict=None,
        witnesses=[],
        route_artifact=None,
        trace_events=events,
        steering_outcome=reason,
    )


def _backend_tool_names(topology_tools: TopologyTools) -> frozenset[str]:
    names: set[str] = set()
    for definition in topology_tools.tool_definitions():
        if not isinstance(definition, dict):
            continue
        function = definition.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
    return frozenset(names)


def _resolve_allowed_capabilities(
    constraints: RunConstraints | None, topology_tools: TopologyTools
) -> frozenset[str] | None:
    """Intersect a user capability request with the backend-authorized tools.

    A user constraint can only *narrow* the tools the backend already exposes;
    it can never add one (no capability widening, bead 3qo.9.8)."""
    if constraints is None or constraints.allowed_capabilities is None:
        return None
    return frozenset(constraints.allowed_capabilities) & _backend_tool_names(
        topology_tools
    )


def _narrow_tool_definitions(
    definitions: list[dict[str, object]], allowed: frozenset[str] | None
) -> list[dict[str, object]]:
    if allowed is None:
        return definitions
    narrowed: list[dict[str, object]] = []
    for definition in definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name in allowed:
            narrowed.append(definition)
    return narrowed
