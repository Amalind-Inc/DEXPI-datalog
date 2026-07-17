"""Adapter tests for the local RMSO OpenRouter enforcement gateway."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from pydexpi_datalog.benchmark.rmso_openrouter_gateway import (
    LockedOpenRouterGateway,
)
from pydexpi_datalog.benchmark.rmso_openrouter_policy import (
    OpenRouterRequestPolicy,
)


def test_gateway_enforces_request_and_archives_resolved_response(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": "deepseek/deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                        "message": {"role": "assistant", "content": "done"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cost": 0.004,
                    "completion_tokens_details": {"reasoning_tokens": 10},
                },
                "openrouter_metadata": {
                    "requested_model": "deepseek/deepseek-v4-flash",
                    "selected_provider": "TestProvider",
                    "attempts": [
                        {
                            "model": "deepseek/deepseek-v4-flash",
                            "provider": "TestProvider",
                        }
                    ],
                },
            },
        )

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        with LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        ) as gateway:
            response = httpx.post(
                f"{gateway.base_url}/chat/completions",
                json={
                    "model": "deepseek/deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "inspect"}],
                    "temperature": 1,
                    "reasoning_effort": "high",
                    "max_tokens": 32768,
                },
            )

    assert response.status_code == 200
    assert response.json()["id"] == "gen-1"
    upstream_body = observed["body"]
    assert isinstance(upstream_body, dict)
    assert upstream_body["temperature"] == 0
    assert upstream_body["reasoning"] == {"effort": "high"}
    assert upstream_body["max_tokens"] == 8192
    assert upstream_body["provider"]["sort"] == "price"
    upstream_headers = observed["headers"]
    assert isinstance(upstream_headers, dict)
    assert upstream_headers["x-openrouter-metadata"] == "enabled"
    assert upstream_headers["authorization"] == "Bearer test-key"
    assert gateway.actual_spend == 0.004
    request_artifact = json.loads(
        (tmp_path / "artifacts" / "call-0001-request.json").read_text()
    )
    response_artifact = json.loads(
        (tmp_path / "artifacts" / "call-0001-response.json").read_text()
    )
    assert request_artifact["request"] == upstream_body
    assert request_artifact["reservation_usd"] > 0
    assert response_artifact["response"]["openrouter_metadata"][
        "selected_provider"
    ] == "TestProvider"
