from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydexpi_datalog.qa.topology_tools import TopologyTools


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    tool_input: dict[str, object]
    tool_call_id: str


# Grounding posture: the model declares how a final answer relates to the loaded
# source. The backend never classifies the question; it only enforces that the
# declared posture is consistent with the validated evidence the answer carries.
POSTURE_UNSPECIFIED = "unspecified"
POSTURE_SOURCE_GROUNDED = "source_grounded"
POSTURE_GENERAL_KNOWLEDGE = "general_knowledge"
POSTURE_SOURCE_DATA_UNAVAILABLE = "source_data_unavailable"
POSTURE_OUT_OF_SCOPE = "out_of_scope"
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
            requires_confirmation=True,
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
            trace.get("tool_name") == "propose_temporary_datalog"
            and _tool_result_status(trace.get("tool_result"))
            in {"confirmation_required", "executed"}
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


class ScriptedQATurnProvider:
    """Deterministic provider used as the OSS default and in tests.

    Behaviors it demonstrates without a real model:
    - Ambiguous text yields several plausible candidates (multi-candidate answer).
    - Follow-ups that use a pronoun reuse prior evidence identities.
    - It discloses which objects it interpreted the question to mean.
    """

    def __init__(self, *, max_candidates: int = 3) -> None:
        self._step = 0
        self._max_candidates = max_candidates
        self._mode = "direct"
        self._candidates: list[str] = []
        self._reachable_ids: list[str] = []
        self._question = ""
        self._anchor = ""

    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ToolCall | FinalAnswer:
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
                # confirmation-gated temporary Datalog capability instead of
                # dead-ending (37x.22.34.2). Prefer a piping/structural
                # anchor: equipment nodes are frequently isolated in the
                # structural view, and an empty sample demos nothing.
                self._mode = "rule_evaluation"
                self._anchor = self._rule_evaluation_anchor(matches)
            return ToolCall(
                tool_name="get_reachable_equipment",
                tool_input={"equipment_id": self._anchor},
                tool_call_id="scripted-reachable",
            )

        self._reachable_ids = self._read_reachable(messages)
        if self._mode == "rule_evaluation":
            return self._propose_temporary_datalog()
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

    def _propose_temporary_datalog(self) -> ToolCall:
        """Escalate a rule-like question to the confirmation-gated capability.

        The restatement states exactly what the temporary query computes --
        nothing more. If the sampled anchor has reachable objects, propose the
        reachability query; otherwise fall back to the resolved objects
        themselves as literal facts.
        """
        if self._reachable_ids:
            return ToolCall(
                tool_name="propose_temporary_datalog",
                tool_input={
                    "request": self._question,
                    # Deliberately not the historical `answer(x) :- ...` text
                    # shape: the executor is a real Souffle engine
                    # (37x.22.34.4), not a regex over two blessed spellings,
                    # so the OSS default provider exercises that for real.
                    "generated_datalog": (
                        ".decl answer(x:symbol)\n"
                        ".output answer\n"
                        f'answer(result) :- reachable("{self._anchor}", result).'
                    ),
                    "formal_restatement": (
                        "Return every object structurally reachable from "
                        f"{self._anchor} as the temporary check result."
                    ),
                    "resolved_identity_ids": [self._anchor],
                },
                tool_call_id="scripted-propose-datalog",
            )
        facts = "\n".join(f'answer("{cid}").' for cid in self._candidates)
        return ToolCall(
            tool_name="propose_temporary_datalog",
            tool_input={
                "request": self._question,
                "generated_datalog": (
                    ".decl answer(x:symbol)\n.output answer\n" + facts
                ),
                "formal_restatement": (
                    "Return the resolved objects "
                    f"{self._describe(self._candidates)} as the temporary "
                    "check result; no further objects were structurally "
                    "reachable from the sampled anchor."
                ),
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
                return [str(item["evidence_id"]) for item in result.get("reachable", [])]
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
    max_rounds: int = 10,
    max_conversation_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
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
    tools = topology_tools.tool_definitions()

    for _ in range(max_rounds):
        response = provider.complete_with_tools(messages=messages, tools=tools)

        if isinstance(response, FinalAnswer):
            if _tool_trace_satisfies_intent(intent, tool_call_trace):
                return _finalize(response, known_ids, tool_call_trace)
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
            tool_result = topology_tools.execute(response.tool_name, response.tool_input)
            tool_result_json = json.dumps(tool_result)

            tool_call_trace.append(
                {
                    "tool_call_id": response.tool_call_id,
                    "tool_name": response.tool_name,
                    "tool_input": response.tool_input,
                    "tool_result": tool_result,
                }
            )

            if (
                response.tool_name == "propose_temporary_datalog"
                and _tool_result_status(tool_result) == "confirmation_required"
            ):
                # The proposal ends the turn deterministically (37x.22.34.2):
                # execution consent belongs to the user, so the model never
                # authors a final answer on top of an unconfirmed proposal.
                # The caller detects the proposal in the trace and pauses the
                # turn with needs_datalog_confirmation.
                return _finalize(
                    FinalAnswer(
                        answer_text=(
                            "A temporary Datalog query was proposed and is "
                            "awaiting your confirmation before it can run."
                        ),
                    ),
                    known_ids,
                    tool_call_trace,
                )

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
    raise RuntimeError(f"QA harness exceeded {max_rounds} rounds without a final answer.")


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

    posture, source_grounded, disclosure = _resolve_grounding(
        response.grounding_posture, valid_references
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
    )


def _resolve_grounding(
    declared_posture: str, valid_references: list[str]
) -> tuple[str, bool, str | None]:
    """Enforce the posture <-> evidence boundary deterministically.

    The backend never decides what a question is about. It only checks that a
    model-declared grounding posture is consistent with the evidence references
    that survived validation, and attaches an authoritative disclosure whenever
    the answer is not a validated conclusion derived from the loaded source.
    """
    has_evidence = bool(valid_references)

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
