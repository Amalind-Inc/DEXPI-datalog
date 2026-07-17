"""Behavior tests for the locked RMSO OpenRouter request boundary."""

import pytest

from pydexpi_datalog.benchmark.rmso_openrouter_policy import (
    OpenRouterRequestPolicy,
)


def test_policy_replaces_kira_settings_with_preregistered_request() -> None:
    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )
    incoming = {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "inspect the drawing"}],
        "tools": [{"type": "function", "function": {"name": "execute"}}],
        "temperature": 1,
        "reasoning_effort": "high",
        "max_tokens": 32768,
        "provider": {"sort": "throughput"},
    }

    locked = policy.apply(incoming)

    assert locked["model"] == "deepseek/deepseek-v4-flash"
    assert locked["messages"] == incoming["messages"]
    assert locked["tools"] == incoming["tools"]
    assert locked["temperature"] == 0
    assert locked["reasoning"] == {"effort": "high"}
    assert locked["max_tokens"] == 8192
    assert locked["provider"] == {
        "sort": "price",
        "require_parameters": True,
        "allow_fallbacks": True,
        "max_price": {"prompt": 0.098, "completion": 0.196},
    }
    assert "reasoning_effort" not in locked


def test_policy_rejects_model_fallback_request() -> None:
    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )

    with pytest.raises(ValueError, match="model fallback"):
        policy.apply(
            {
                "model": "deepseek/deepseek-v4-flash",
                "models": [
                    "deepseek/deepseek-v4-flash",
                    "openai/gpt-5.4",
                ],
                "messages": [],
            }
        )


def test_policy_rejects_request_for_a_different_model() -> None:
    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )

    with pytest.raises(ValueError, match="exact model"):
        policy.apply(
            {
                "model": "deepseek/deepseek-v4-pro",
                "messages": [],
            }
        )


@pytest.mark.parametrize("invalid_price", [0, -0.01, float("inf"), float("nan")])
def test_policy_requires_finite_positive_frozen_prices(invalid_price: float) -> None:
    with pytest.raises(ValueError, match="price"):
        OpenRouterRequestPolicy(
            prompt_price_per_million=invalid_price,
            completion_price_per_million=0.196,
        )


def test_reservation_uses_full_output_allowance_and_enforces_ten_dollar_cap() -> None:
    policy = OpenRouterRequestPolicy(
        prompt_price_per_million=0.098,
        completion_price_per_million=0.196,
    )

    reservation = policy.reserve_call(
        input_tokens=1000,
        actual_spend=0,
        active_reservations=0,
    )
    assert reservation == pytest.approx(0.001703632)

    with pytest.raises(ValueError, match="spend cap"):
        policy.reserve_call(
            input_tokens=1000,
            actual_spend=9.998,
            active_reservations=0.0005,
        )
