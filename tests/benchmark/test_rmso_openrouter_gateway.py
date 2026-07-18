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
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
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
    assert request_artifact["attribution"] == {
        "arm_id": "arm-a",
        "question_id": "question-1",
    }
    assert request_artifact["reservation_usd"] > 0
    assert response_artifact["response"]["openrouter_metadata"][
        "selected_provider"
    ] == "TestProvider"
    assert gateway.episode_accounting(
        arm_id="arm-a", question_id="question-1"
    ) == {
        "accounting_complete": True,
        "call_numbers": [1],
        "cost_usd": 0.004,
        "known_cost_usd": 0.004,
        "policy_violation_call_numbers": [],
    }


def test_gateway_settles_billed_cost_before_rejecting_output_limit_violation(
    tmp_path: Path,
) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek/deepseek-v4-flash",
                "choices": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 8193,
                    "cost": 0.005,
                },
                "openrouter_metadata": {"selected_provider": "TestProvider"},
            },
        )

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                response = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "inspect"}],
                    },
                )

    assert response.status_code == 502
    assert gateway.actual_spend == 0.005
    assert gateway.accounting_snapshot() == {
        "actual_spend_usd": 0.005,
        "active_reservations_usd": 0.0,
        "accounting_complete": True,
        "attribution_complete": True,
        "unattributed_attempts": 0,
        "spend_cap_complete": True,
        "spend_cap_blocked_attempts": 0,
        "unknown_cost_calls": [],
        "calls": [
            {
                "arm_id": "arm-a",
                "call_number": 1,
                "known_cost_usd": 0.005,
                "question_id": "question-1",
                "reservation_usd": 0.001703632,
                "status": "policy_violation",
            }
        ],
        "policy_violations": [
            {
                "call_number": 1,
                "reason": "OpenRouter response exceeds the output-token ceiling.",
            }
        ],
    }


def test_gateway_releases_reservation_and_marks_transport_failure_unknown_cost(
    tmp_path: Path,
) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider response was lost", request=request)

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                response = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "inspect"}],
                    },
                )

    assert response.status_code == 502
    assert gateway.accounting_snapshot() == {
        "actual_spend_usd": 0.0,
        "active_reservations_usd": 0.0,
        "accounting_complete": False,
        "attribution_complete": True,
        "unattributed_attempts": 0,
        "spend_cap_complete": True,
        "spend_cap_blocked_attempts": 0,
        "unknown_cost_calls": [1],
        "calls": [
            {
                "arm_id": "arm-a",
                "call_number": 1,
                "known_cost_usd": 0.0,
                "question_id": "question-1",
                "reservation_usd": 0.001703632,
                "status": "unknown_cost",
            }
        ],
        "policy_violations": [],
    }


def test_gateway_rejects_and_records_an_unattributed_attempt(tmp_path: Path) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("an unattributed request must not reach OpenRouter")

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
                },
            )

    assert response.status_code == 400
    assert gateway.accounting_snapshot()["attribution_complete"] is False
    assert gateway.accounting_snapshot()["unattributed_attempts"] == 1


def test_gateway_marks_server_error_without_cost_as_unknown_but_402_as_zero(
    tmp_path: Path,
) -> None:
    responses = iter(
        [
            httpx.Response(500, json={"error": "provider failed"}),
            httpx.Response(402, json={"error": "insufficient credits"}),
        ]
    )

    def upstream(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                server_error = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "first"}],
                    },
                )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                payment_error = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "second"}],
                    },
                )

    assert server_error.status_code == 500
    assert payment_error.status_code == 402
    episode = gateway.episode_accounting(
        arm_id="arm-a", question_id="question-1"
    )
    assert episode["accounting_complete"] is False
    assert episode["call_numbers"] == [1, 2]
    assert gateway.accounting_snapshot()["unknown_cost_calls"] == [1]


def test_gateway_records_spend_cap_block_before_any_provider_call(
    tmp_path: Path,
) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("a spend-cap-blocked request must not reach OpenRouter")

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=10_000_000,
        completion_price_per_million=10_000_000,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                response = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "inspect"}],
                    },
                )

    assert response.status_code == 400
    assert gateway.accounting_snapshot()["spend_cap_complete"] is False
    assert gateway.accounting_snapshot()["spend_cap_blocked_attempts"] == 1


def test_gateway_settles_cost_then_rejects_missing_resolved_provider_identity(
    tmp_path: Path,
) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek/deepseek-v4-flash",
                "choices": [],
                "usage": {"completion_tokens": 20, "cost": 0.004},
                "openrouter_metadata": {},
            },
        )

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                response = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "inspect"}],
                    },
                )

    assert response.status_code == 502
    assert gateway.actual_spend == 0.004
    assert gateway.accounting_snapshot()["policy_violations"] == [
        {
            "call_number": 1,
            "reason": "OpenRouter response lacks resolved-provider metadata.",
        }
    ]


def test_gateway_accepts_live_openrouter_top_level_provider_shape(
    tmp_path: Path,
) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek/deepseek-v4-flash",
                "provider": "DeepInfra",
                "choices": [],
                "usage": {"completion_tokens": 20, "cost": 0.004},
                "openrouter_metadata": {
                    "requested": "deepseek/deepseek-v4-flash",
                    "endpoints": {
                        "available": [
                            {
                                "model": "deepseek/deepseek-v4-flash-20260423",
                                "provider": "DeepInfra",
                                "selected": True,
                            }
                        ]
                    },
                },
            },
        )

    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    with httpx.Client(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway = LockedOpenRouterGateway(
            policy=policy,
            credential="test-key",
            artifact_dir=tmp_path / "artifacts",
            reserved_input_tokens=1000,
            upstream_url="https://openrouter.test/api/v1/chat/completions",
            http_client=upstream_client,
        )
        with gateway.attribute_calls(arm_id="arm-a", question_id="question-1"):
            with gateway:
                response = httpx.post(
                    f"{gateway.base_url}/chat/completions",
                    json={
                        "model": "deepseek/deepseek-v4-flash",
                        "messages": [{"role": "user", "content": "inspect"}],
                    },
                )

    assert response.status_code == 200
    assert gateway.accounting_snapshot()["policy_violations"] == []
    assert gateway.actual_spend == 0.004
