"""Contract tests for OllamaQATurnProvider.

Boundary: OllamaQATurnProvider.complete_with_tools() via a fake HTTP transport.
Tests assert the ToolCall/FinalAnswer protocol only — no internal message inspection.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from pydexpi_datalog.qa.ollama_qa_provider import OllamaQATurnProvider
from pydexpi_datalog.qa.grounded_qa_harness import FinalAnswer, ToolCall


def _tool_call_response(
    name: str, arguments: dict[str, object], call_id: str = "call-1"
) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }
    return mock


def _provide_answer_response(
    answer_text: str,
    evidence_ids: list[str] | None = None,
    interpreted_ids: list[str] | None = None,
) -> MagicMock:
    return _tool_call_response(
        "provide_answer",
        {
            "answer_text": answer_text,
            "evidence_object_ids": evidence_ids or [],
            "interpreted_object_ids": interpreted_ids or [],
        },
    )


def _text_response(content: str) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": None,
                }
            }
        ]
    }
    return mock


SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {"name": "find_equipment", "description": "x", "parameters": {}},
    }
]


class OllamaQATurnProviderTests(unittest.TestCase):
    def _make_provider(self) -> OllamaQATurnProvider:
        return OllamaQATurnProvider(model="ornith:35b")

    def test_native_tool_call_is_returned_as_toolcall(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post",
            return_value=_tool_call_response(
                "find_equipment", {"pattern": "pump"}, "call-9"
            ),
        ):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "find the pump"}],
                tools=SAMPLE_TOOLS,
            )

        self.assertIsInstance(result, ToolCall)
        assert isinstance(result, ToolCall)
        self.assertEqual(result.tool_name, "find_equipment")
        self.assertEqual(result.tool_input, {"pattern": "pump"})
        self.assertEqual(result.tool_call_id, "call-9")

    def test_provide_answer_tool_call_is_returned_as_final_answer(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post",
            return_value=_provide_answer_response(
                "Pump P-101 connects to valve V-102.",
                evidence_ids=["node-a", "node-b"],
                interpreted_ids=["node-a"],
            ),
        ):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "what connects?"}],
                tools=SAMPLE_TOOLS,
            )

        self.assertIsInstance(result, FinalAnswer)
        assert isinstance(result, FinalAnswer)
        self.assertEqual(result.answer_text, "Pump P-101 connects to valve V-102.")
        self.assertEqual(result.evidence_references, ["node-a", "node-b"])
        self.assertEqual(result.interpreted_object_ids, ["node-a"])

    def test_text_only_response_is_final_answer_with_no_evidence(self) -> None:
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response("Happy to help!")):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=SAMPLE_TOOLS,
            )

        self.assertIsInstance(result, FinalAnswer)
        assert isinstance(result, FinalAnswer)
        self.assertEqual(result.answer_text, "Happy to help!")
        self.assertEqual(result.evidence_references, [])

    def test_text_content_resembling_tool_call_is_not_executed(self) -> None:
        """Pseudo-tool-call text must never be parsed as a ToolCall."""
        pseudo = '{"tool": "find_equipment", "arguments": {"pattern": "pump"}}'
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response(pseudo)):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "find something"}],
                tools=SAMPLE_TOOLS,
            )

        self.assertIsInstance(result, FinalAnswer)
        assert isinstance(result, FinalAnswer)
        self.assertEqual(result.evidence_references, [])

    def test_provide_answer_tool_is_always_injected(self) -> None:
        """The provide_answer tool must be included in every request regardless of caller tools."""
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response("ok")) as mock_post:
            provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        payload = mock_post.call_args[1]["json"]
        tool_names = {t["function"]["name"] for t in payload["tools"]}
        self.assertIn("provide_answer", tool_names)
        self.assertIn("find_equipment", tool_names)

    def test_ollama_endpoint_is_used(self) -> None:
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response("ok")) as mock_post:
            provider.complete_with_tools(messages=[], tools=[])

        url = mock_post.call_args[0][0]
        self.assertIn("localhost:11434", url)
        self.assertIn("chat/completions", url)

    def test_usage_is_accumulated_for_benchmark_cost_accounting(self) -> None:
        provider = self._make_provider()
        response = _text_response("ok")
        response.json.return_value["usage"] = {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
            "cost": 0.002,
        }

        with patch("httpx.post", return_value=response):
            provider.complete_with_tools(messages=[], tools=[])
            provider.complete_with_tools(messages=[], tools=[])

        self.assertEqual(
            provider.usage,
            {
                "input_tokens": 24,
                "output_tokens": 6,
                "total_tokens": 30,
                "cost_usd": 0.004,
            },
        )

    def test_internal_message_keys_are_stripped_before_sending(self) -> None:
        """grounded_evidence_ids must never be forwarded to the model API."""
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response("ok")) as mock_post:
            provider.complete_with_tools(
                messages=[
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "hello",
                        "grounded_evidence_ids": ["node-x"],
                    },
                ],
                tools=[],
            )

        sent = mock_post.call_args[1]["json"]["messages"]
        for msg in sent:
            self.assertNotIn("grounded_evidence_ids", msg)

    def test_grounding_posture_is_parsed_from_provide_answer(self) -> None:
        provider = self._make_provider()
        response = _tool_call_response(
            "provide_answer",
            {
                "answer_text": "A centrifugal pump uses an impeller.",
                "evidence_object_ids": [],
                "grounding_posture": "general_knowledge",
            },
        )
        with patch("httpx.post", return_value=response):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "what is a pump?"}],
                tools=SAMPLE_TOOLS,
            )

        assert isinstance(result, FinalAnswer)
        self.assertEqual(result.grounding_posture, "general_knowledge")

    def test_invalid_grounding_posture_falls_back_to_unspecified(self) -> None:
        provider = self._make_provider()
        response = _tool_call_response(
            "provide_answer",
            {"answer_text": "ok", "grounding_posture": "totally-made-up"},
        )
        with patch("httpx.post", return_value=response):
            result = provider.complete_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=SAMPLE_TOOLS,
            )

        assert isinstance(result, FinalAnswer)
        self.assertEqual(result.grounding_posture, "unspecified")

    def test_grounding_posture_is_offered_in_provide_answer_schema(self) -> None:
        provider = self._make_provider()
        with patch("httpx.post", return_value=_text_response("ok")) as mock_post:
            provider.complete_with_tools(messages=[], tools=SAMPLE_TOOLS)

        payload = mock_post.call_args[1]["json"]
        provide_answer = next(
            t for t in payload["tools"] if t["function"]["name"] == "provide_answer"
        )
        properties = provide_answer["function"]["parameters"]["properties"]
        self.assertIn("grounding_posture", properties)
        self.assertEqual(
            set(properties["grounding_posture"]["enum"]),
            {
                "source_grounded",
                "general_knowledge",
                "source_data_unavailable",
                "out_of_scope",
                "needs_clarification",
            },
        )

    def test_custom_base_url(self) -> None:
        provider = OllamaQATurnProvider(
            model="ornith:35b", base_url="http://remote-host:11434"
        )
        with patch("httpx.post", return_value=_text_response("ok")) as mock_post:
            provider.complete_with_tools(messages=[], tools=[])

        url = mock_post.call_args[0][0]
        self.assertIn("remote-host:11434", url)


if __name__ == "__main__":
    unittest.main()
