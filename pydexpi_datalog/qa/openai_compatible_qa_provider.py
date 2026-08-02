from __future__ import annotations

import json

import httpx

from .grounded_qa_harness import (
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_NEEDS_CLARIFICATION,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    FinalAnswer,
    ToolCall,
)

_VALID_POSTURES = frozenset(
    {
        POSTURE_SOURCE_GROUNDED,
        POSTURE_GENERAL_KNOWLEDGE,
        POSTURE_SOURCE_DATA_UNAVAILABLE,
        POSTURE_OUT_OF_SCOPE,
        POSTURE_NEEDS_CLARIFICATION,
    }
)


_INTERNAL_MESSAGE_KEYS = frozenset({"grounded_evidence_ids"})

_PROVIDE_ANSWER_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "provide_answer",
        "description": (
            "Provide your final process-engineering answer to the engineer. Call "
            "this exactly once when ready. Cite topology evidence when the request "
            "depends on the loaded source; omit proof and evidence IDs when they "
            "are not needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer_text": {
                    "type": "string",
                    "description": (
                        "Plain process-engineering language. If a rule, query, or "
                        "agent plan matters, explain its condition, scope, result, "
                        "and limitations; never expose raw node ids."
                    ),
                },
                "evidence_object_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "evidence_id values of topology objects that witness this "
                        "answer. Omit or leave empty for general conversation."
                    ),
                },
                "interpreted_object_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "evidence_id values you interpreted the question to refer to, "
                        "when the reference was ambiguous."
                    ),
                },
                "grounding_posture": {
                    "type": "string",
                    "enum": [
                        POSTURE_SOURCE_GROUNDED,
                        POSTURE_GENERAL_KNOWLEDGE,
                        POSTURE_SOURCE_DATA_UNAVAILABLE,
                        POSTURE_OUT_OF_SCOPE,
                        POSTURE_NEEDS_CLARIFICATION,
                    ],
                    "description": (
                        "How this answer relates to the loaded source. Use "
                        "source_grounded only with cited evidence; otherwise use "
                        "general_knowledge, source_data_unavailable, "
                        "needs_clarification, or out_of_scope as appropriate."
                    ),
                },
            },
            "required": ["answer_text"],
        },
    },
}


class OpenAICompatibleQATurnProvider:
    """QATurnProvider for any provider exposing an OpenAI-compatible
    ``/chat/completions`` endpoint with native structured tool_calls (Ollama,
    OpenAI, OpenRouter, and other OpenAI-compatible gateways/models).

    A ``credential`` is sent as an ``Authorization: Bearer`` header when
    provided; omit it for endpoints that need no auth (e.g. local Ollama).

    Only native structured tool_calls are honored. Text content that resembles
    a tool call is treated as a plain FinalAnswer with no evidence — pseudo-tool
    text is never parsed or executed.

    Anthropic and Gemini are not covered by this class: their tool-calling
    request/response shapes differ from the OpenAI ``tool_calls`` schema and
    would need their own provider implementation.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        credential: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._credential = credential
        self.usage: dict[str, object] = {}

    def complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        tool_choice: str = "auto",
    ) -> ToolCall | FinalAnswer:
        headers = {"Content-Type": "application/json"}
        if self._credential:
            headers["Authorization"] = f"Bearer {self._credential}"
        payload: dict[str, object] = {
            "model": self.model,
            "messages": self._clean_messages(messages),
            "tools": [*tools, _PROVIDE_ANSWER_TOOL],
            "tool_choice": tool_choice,
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Provider {self.provider}/{self.model} request failed."
            ) from error
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            # Preserve the provider/model boundary without leaking an arbitrary
            # upstream response body into transcripts, logs, or benchmark output.
            raise RuntimeError(
                f"Provider {self.provider}/{self.model} returned a non-JSON response."
            ) from error
        if not isinstance(body, dict):
            raise RuntimeError(
                f"Provider {self.provider}/{self.model} returned an invalid JSON object."
            )
        self._record_usage(body)
        return self._interpret(body)

    def _record_usage(self, body: dict[str, object]) -> None:
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            return
        for source, target in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
            ("cost", "cost_usd"),
        ):
            value = usage.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                current = self.usage.get(target, 0)
                if isinstance(current, (int, float)) and not isinstance(current, bool):
                    self.usage[target] = current + value

    def _interpret(self, body: dict[str, object]) -> ToolCall | FinalAnswer:
        message = self._first_message(body)
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            call = tool_calls[0]
            if not isinstance(call, dict):
                return FinalAnswer(answer_text="")
            function = call.get("function", {})
            if not isinstance(function, dict):
                return FinalAnswer(answer_text="")
            name = str(function.get("name", ""))
            arguments = _parse_arguments(function.get("arguments"))
            call_id = str(call.get("id") or "call-0")
            if name == "provide_answer":
                return _final_answer_from_args(arguments)
            return ToolCall(
                tool_name=name,
                tool_input=arguments,
                tool_call_id=call_id,
            )

        content = message.get("content")
        return FinalAnswer(answer_text=str(content or "").strip())

    @staticmethod
    def _first_message(body: dict[str, object]) -> dict[str, object]:
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    return message
        return {}

    @staticmethod
    def _clean_messages(
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            {k: v for k, v in message.items() if k not in _INTERNAL_MESSAGE_KEYS}
            for message in messages
        ]


def _final_answer_from_args(arguments: dict[str, object]) -> FinalAnswer:
    answer_text = str(arguments.get("answer_text", "")).strip()
    evidence = [
        str(x) for x in arguments.get("evidence_object_ids", []) if isinstance(x, str)
    ]
    interpreted = [
        str(x)
        for x in arguments.get("interpreted_object_ids", [])
        if isinstance(x, str)
    ]
    declared_posture = arguments.get("grounding_posture")
    posture = (
        declared_posture
        if isinstance(declared_posture, str) and declared_posture in _VALID_POSTURES
        else POSTURE_UNSPECIFIED
    )
    return FinalAnswer(
        answer_text=answer_text,
        evidence_references=evidence,
        interpreted_object_ids=interpreted,
        grounding_posture=posture,
    )


def _parse_arguments(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}
