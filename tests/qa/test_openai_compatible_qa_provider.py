"""
Behavioral contract tests for OpenAICompatibleQATurnProvider.

Boundary: complete_with_tools() via a fake HTTP transport (patched httpx.post).
Tests assert the ToolCall/FinalAnswer protocol only -- no internal message
inspection beyond the request payload the provider actually sends.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer, ToolCall
from pydexpi_datalog.qa.openai_compatible_qa_provider import (
    OpenAICompatibleQATurnProvider,
)

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_equipment",
            "description": "Search topology objects.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


def _tool_call_response(*, reasoning: object = None) -> _FakeResponse:
    message: dict[str, object] = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "find_equipment",
                    "arguments": '{"pattern": "pump"}',
                },
            }
        ],
    }
    if reasoning is not None:
        message["reasoning"] = reasoning
    return _FakeResponse({"choices": [{"message": message}]})


def _final_answer_response(*, reasoning_content: object = None) -> _FakeResponse:
    message: dict[str, object] = {"role": "assistant", "content": "All good."}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return _FakeResponse({"choices": [{"message": message}]})


def _openrouter_provider() -> OpenAICompatibleQATurnProvider:
    return OpenAICompatibleQATurnProvider(
        provider="openrouter",
        model="anthropic/claude-sonnet-4",
        base_url="https://openrouter.test/api/v1",
        credential="sk-test",
    )


def _openai_provider() -> OpenAICompatibleQATurnProvider:
    return OpenAICompatibleQATurnProvider(
        provider="openai",
        model="gpt-4.1",
        base_url="https://api.openai.test/v1",
        credential="sk-test",
    )


class OpenRouterReasoningRequestTests(unittest.TestCase):
    def test_openrouter_requests_reasoning_tokens(self) -> None:
        provider = _openrouter_provider()

        with patch("httpx.post", return_value=_tool_call_response()) as mock_post:
            provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["reasoning"], {"enabled": True})

    def test_non_reasoning_providers_do_not_send_the_reasoning_parameter(self) -> None:
        provider = _openai_provider()

        with patch("httpx.post", return_value=_tool_call_response()) as mock_post:
            provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        payload = mock_post.call_args[1]["json"]
        self.assertNotIn("reasoning", payload)


class ReasoningCaptureTests(unittest.TestCase):
    def test_tool_call_carries_returned_reasoning(self) -> None:
        provider = _openrouter_provider()
        response = _tool_call_response(reasoning="I should search for pumps first.")

        with patch("httpx.post", return_value=response):
            result = provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        assert isinstance(result, ToolCall)
        self.assertEqual(result.tool_name, "find_equipment")
        self.assertEqual(result.tool_input, {"pattern": "pump"})
        self.assertEqual(result.reasoning, "I should search for pumps first.")

    def test_final_answer_carries_returned_reasoning_content(self) -> None:
        provider = _openrouter_provider()
        response = _final_answer_response(
            reasoning_content="The retrieved evidence answers the question."
        )

        with patch("httpx.post", return_value=response):
            result = provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        assert isinstance(result, FinalAnswer)
        self.assertEqual(
            result.reasoning, "The retrieved evidence answers the question."
        )

    def test_missing_reasoning_degrades_to_none_without_fabrication(self) -> None:
        provider = _openrouter_provider()

        with patch("httpx.post", return_value=_tool_call_response()):
            tool_call = provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)
        with patch("httpx.post", return_value=_final_answer_response()):
            final_answer = provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        assert isinstance(tool_call, ToolCall)
        assert isinstance(final_answer, FinalAnswer)
        self.assertIsNone(tool_call.reasoning)
        self.assertIsNone(final_answer.reasoning)

    def test_non_string_reasoning_is_ignored_not_crashed_on(self) -> None:
        provider = _openrouter_provider()
        response = _tool_call_response(reasoning={"blocks": ["opaque"]})

        with patch("httpx.post", return_value=response):
            result = provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        assert isinstance(result, ToolCall)
        self.assertIsNone(result.reasoning)


if __name__ == "__main__":
    unittest.main()
