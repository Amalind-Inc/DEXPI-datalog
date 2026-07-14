from __future__ import annotations

import httpx
import json
import unittest
from unittest.mock import MagicMock, patch

from pydexpi_datalog.llm.byok_provider import (
    build_system_prompt,
    create_byok_provider,
)
from pydexpi_datalog.llm.model_access import ModelCapabilityError


def _mock_response(content: str) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    return mock


def _openai_response(content: str) -> MagicMock:
    mock = _mock_response(content)
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock


def _anthropic_response(content: str) -> MagicMock:
    mock = _mock_response(content)
    mock.json.return_value = {"content": [{"text": content}]}
    return mock


def _gemini_response(content: str) -> MagicMock:
    mock = _mock_response(content)
    mock.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": content}]}}]
    }
    return mock


_TOPOLOGY_NODES = [
    {"id": "node-abc", "label": "P-4713", "class": "CentrifugalPump"},
    {"id": "node-def", "label": "H-1009", "class": "PlateHeatExchanger"},
    {"id": "node-ghi", "label": "Nozzle", "class": "Nozzle"},
]
_TOPOLOGY_EDGES = [
    {"source_id": "node-ghi", "target_id": "node-abc", "relationship": "nodes"},
]

_DATALOG_CONTEXT: dict[str, object] = {
    "route": {"kind": "topology_logic"},
    "scope": {"kind": "whole_pid"},
    "source_scope_ids": [],
    "topology_nodes": _TOPOLOGY_NODES,
    "topology_edges": _TOPOLOGY_EDGES,
}

_SCOPED_CONTEXT: dict[str, object] = {
    **_DATALOG_CONTEXT,
    "scope": {"kind": "visible_source_scope"},
    "source_scope_ids": ["node-abc"],
}

_GROUNDED_CONTEXT: dict[str, object] = {
    "task": "grounded_logic_answer",
    "instructions": "Answer the user's topology question directly using only the provided deterministic evidence.",
    "generated_logic": {
        "kind": "generated_datalog",
        "content": '.decl answer(x:symbol)\nanswer("node-abc").',
    },
    "evidence_items": [
        {"id": "node-abc", "kind": "node", "label": "P-4713"},
    ],
}


class SystemPromptTests(unittest.TestCase):
    def test_datalog_prompt_includes_all_node_ids_and_labels(self) -> None:
        prompt = build_system_prompt(_DATALOG_CONTEXT)
        self.assertIn('"node-abc"', prompt)
        self.assertIn('"node-def"', prompt)
        self.assertIn('"node-ghi"', prompt)
        self.assertIn("P-4713", prompt)
        self.assertIn("H-1009", prompt)
        self.assertIn("CentrifugalPump", prompt)

    def test_datalog_prompt_includes_edges_with_relationship(self) -> None:
        prompt = build_system_prompt(_DATALOG_CONTEXT)
        self.assertIn("nodes", prompt)
        self.assertIn("node-ghi", prompt)
        self.assertIn("node-abc", prompt)

    def test_datalog_prompt_does_not_include_scope_clause_for_whole_pid(self) -> None:
        prompt = build_system_prompt(_DATALOG_CONTEXT)
        self.assertNotIn("SOURCE SCOPE", prompt)

    def test_datalog_prompt_includes_scope_clause_with_resolved_label(self) -> None:
        prompt = build_system_prompt(_SCOPED_CONTEXT)
        self.assertIn("SOURCE SCOPE", prompt)
        self.assertIn('"node-abc"', prompt)
        self.assertIn("P-4713", prompt)

    def test_trap_judge_gets_dedicated_non_datalog_system_prompt(self) -> None:
        prompt = build_system_prompt({"task": "benchmark_trap_judge"})

        self.assertIn("grounded refusal", prompt.lower())
        self.assertIn("graceful redirect", prompt.lower())
        self.assertNotIn("datalog", prompt.lower())

    def test_grounded_answer_prompt_includes_evidence_labels_and_ids(self) -> None:
        prompt = build_system_prompt(_GROUNDED_CONTEXT)
        self.assertIn("P-4713", prompt)
        self.assertIn("node-abc", prompt)

    def test_grounded_answer_prompt_includes_instructions(self) -> None:
        prompt = build_system_prompt(_GROUNDED_CONTEXT)
        self.assertIn("deterministic evidence", prompt)

    def test_grounded_answer_prompt_for_empty_evidence_says_no_match(self) -> None:
        context = {**_GROUNDED_CONTEXT, "evidence_items": []}
        prompt = build_system_prompt(context)
        self.assertIn("No topology objects were matched", prompt)


_FAKE_DATALOG_RESPONSE = json.dumps(
    {
        "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-abc").',
        "formal_restatement": "Return node-abc.",
    }
)
_FAKE_ANSWER_RESPONSE = json.dumps(
    {"answer_text": "The pump P-4713 is connected downstream."}
)


class OpenAICompatibleProviderTests(unittest.TestCase):
    def _make_provider(self, provider_name: str = "openai") -> object:
        return create_byok_provider(
            provider=provider_name, model="gpt-4.1", credential="sk-test-key"
        )

    def test_openai_posts_to_correct_endpoint(self) -> None:
        provider = self._make_provider("openai")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            result = provider.complete(
                request="What is connected?", context=_DATALOG_CONTEXT
            )

        url = mock_post.call_args[0][0]
        self.assertIn("api.openai.com", url)
        self.assertIn("chat/completions", url)
        self.assertEqual(result, _FAKE_DATALOG_RESPONSE)

    def test_openrouter_posts_to_openrouter_endpoint(self) -> None:
        provider = self._make_provider("openrouter")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="What is connected?", context=_DATALOG_CONTEXT)

        url = mock_post.call_args[0][0]
        self.assertIn("openrouter.ai", url)

    def test_openrouter_exposes_token_and_cost_usage_for_benchmark_accounting(
        self,
    ) -> None:
        provider = self._make_provider("openrouter")
        response = _openai_response(_FAKE_DATALOG_RESPONSE)
        response.json.return_value["usage"] = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cost": 0.004,
        }

        with patch("httpx.post", return_value=response):
            provider.complete(request="What is connected?", context=_DATALOG_CONTEXT)

        self.assertEqual(
            provider.last_usage,
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "cost_usd": 0.004,
            },
        )

    def test_bearer_auth_header_uses_credential(self) -> None:
        provider = self._make_provider("openai")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-test-key")

    def test_model_is_passed_in_request_body(self) -> None:
        provider = self._make_provider("openai")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["model"], "gpt-4.1")

    def test_system_and_user_messages_are_sent(self) -> None:
        provider = self._make_provider("openai")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="What is downstream?", context=_DATALOG_CONTEXT)

        messages = mock_post.call_args[1]["json"]["messages"]
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["system", "user"])
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        self.assertEqual(user_content, "What is downstream?")

    def test_grounded_answer_context_produces_grounded_system_prompt(self) -> None:
        provider = self._make_provider("openai")
        with patch(
            "httpx.post", return_value=_openai_response(_FAKE_ANSWER_RESPONSE)
        ) as mock_post:
            provider.complete(request="Who is downstream?", context=_GROUNDED_CONTEXT)

        system_content = next(
            m["content"]
            for m in mock_post.call_args[1]["json"]["messages"]
            if m["role"] == "system"
        )
        self.assertIn("P-4713", system_content)
        self.assertNotIn("TOPOLOGY NODES", system_content)

    def test_native_tool_runtime_rejection_is_normalized(self) -> None:
        for provider_name, model in [
            ("openrouter", "anthropic/claude-sonnet-4"),
            ("anthropic", "claude-sonnet-4"),
            ("gemini", "gemini-2.5-pro"),
        ]:
            with self.subTest(provider=provider_name):
                provider = create_byok_provider(
                    provider=provider_name,
                    model=model,
                    credential="sk-test-key",
                )
                response = MagicMock()
                response.text = "This model does not support tool_calls."
                response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "400 Bad Request",
                    request=MagicMock(),
                    response=response,
                )

                with patch("httpx.post", return_value=response):
                    with self.assertRaises(ModelCapabilityError) as caught:
                        provider.complete(
                            request="What is connected?", context=_DATALOG_CONTEXT
                        )

                self.assertEqual(
                    caught.exception.code, "model_access.native_tools_rejected"
                )
                self.assertEqual(caught.exception.provider, provider_name)
                self.assertIn("tool_calls", str(caught.exception))


class AnthropicProviderTests(unittest.TestCase):
    def _make_provider(self) -> object:
        return create_byok_provider(
            provider="anthropic", model="claude-sonnet-4", credential="sk-ant-test"
        )

    def test_posts_to_anthropic_messages_endpoint(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_anthropic_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            result = provider.complete(request="test", context=_DATALOG_CONTEXT)

        url = mock_post.call_args[0][0]
        self.assertIn("api.anthropic.com", url)
        self.assertIn("messages", url)
        self.assertEqual(result, _FAKE_DATALOG_RESPONSE)

    def test_uses_x_api_key_header(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_anthropic_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["x-api-key"], "sk-ant-test")
        self.assertIn("anthropic-version", headers)

    def test_system_prompt_sent_as_top_level_field(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_anthropic_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        body = mock_post.call_args[1]["json"]
        self.assertIn("system", body)
        self.assertIn("TOPOLOGY NODES", body["system"])


class GeminiProviderTests(unittest.TestCase):
    def _make_provider(self) -> object:
        return create_byok_provider(
            provider="gemini", model="gemini-2.5-pro", credential="gemini-key"
        )

    def test_posts_to_gemini_generatecontent_endpoint(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_gemini_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            result = provider.complete(request="test", context=_DATALOG_CONTEXT)

        url = mock_post.call_args[0][0]
        self.assertIn("generativelanguage.googleapis.com", url)
        self.assertIn("gemini-2.5-pro", url)
        self.assertIn("generateContent", url)
        self.assertEqual(result, _FAKE_DATALOG_RESPONSE)

    def test_api_key_sent_as_query_param(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_gemini_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        params = mock_post.call_args[1]["params"]
        self.assertEqual(params["key"], "gemini-key")

    def test_system_instruction_sent_in_body(self) -> None:
        provider = self._make_provider()
        with patch(
            "httpx.post", return_value=_gemini_response(_FAKE_DATALOG_RESPONSE)
        ) as mock_post:
            provider.complete(request="test", context=_DATALOG_CONTEXT)

        body = mock_post.call_args[1]["json"]
        system_text = body["system_instruction"]["parts"][0]["text"]
        self.assertIn("TOPOLOGY NODES", system_text)


class CreateByokProviderTests(unittest.TestCase):
    def test_openai_provider_has_correct_attributes(self) -> None:
        p = create_byok_provider(provider="openai", model="gpt-4.1", credential="key")
        self.assertEqual(p.provider, "openai")
        self.assertEqual(p.model, "gpt-4.1")

    def test_openrouter_provider_has_correct_attributes(self) -> None:
        p = create_byok_provider(
            provider="openrouter", model="anthropic/claude-sonnet-4", credential="key"
        )
        self.assertEqual(p.provider, "openrouter")
        self.assertEqual(p.model, "anthropic/claude-sonnet-4")

    def test_anthropic_provider_has_correct_attributes(self) -> None:
        p = create_byok_provider(
            provider="anthropic", model="claude-sonnet-4", credential="key"
        )
        self.assertEqual(p.provider, "anthropic")
        self.assertEqual(p.model, "claude-sonnet-4")

    def test_gemini_provider_has_correct_attributes(self) -> None:
        p = create_byok_provider(
            provider="gemini", model="gemini-2.5-pro", credential="key"
        )
        self.assertEqual(p.provider, "gemini")
        self.assertEqual(p.model, "gemini-2.5-pro")

    def test_unsupported_provider_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported byok provider"):
            create_byok_provider(provider="bedrock", model="claude", credential="key")


if __name__ == "__main__":
    unittest.main()
