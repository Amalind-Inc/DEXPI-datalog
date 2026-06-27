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


@dataclass(frozen=True)
class FinalAnswer:
    answer_text: str
    evidence_references: list[str] = field(default_factory=list)
    interpreted_object_ids: list[str] = field(default_factory=list)


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
            return ToolCall(
                tool_name="get_reachable_equipment",
                tool_input={"equipment_id": self._candidates[0]},
                tool_call_id="scripted-reachable",
            )

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


def run_grounded_qa_turn(
    *,
    question: str,
    topology_tools: TopologyTools,
    provider: QATurnProvider,
    conversation: list[ConversationTurn] | None = None,
    max_rounds: int = 10,
) -> QATurnResult:
    """Execute a grounded QA turn: model calls tools, backend executes them, model answers.

    Conversation state seeds prior turns so the model can resolve follow-up
    references. Prior evidence identities are re-validated against the current
    topology before reuse; prior prose is never promoted to evidence.
    """
    known_ids = topology_tools.known_evidence_ids()
    messages: list[dict[str, object]] = []
    for turn in conversation or []:
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

    tool_call_trace: list[dict[str, object]] = []
    tools = topology_tools.tool_definitions()

    for _ in range(max_rounds):
        response = provider.complete_with_tools(messages=messages, tools=tools)

        if isinstance(response, FinalAnswer):
            return _finalize(response, known_ids, tool_call_trace)

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

    return QATurnResult(
        answer_text=response.answer_text,
        evidence_references=valid_references,
        rejected_references=rejected_references,
        interpreted_object_ids=interpreted,
        tool_call_trace=tool_call_trace,
    )
