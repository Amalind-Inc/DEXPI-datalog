"""Fail-closed OpenRouter request policy for the pre-registered RMSO spike."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


MODEL = "deepseek/deepseek-v4-flash"
MAX_OUTPUT_TOKENS = 8192
CUMULATIVE_SPEND_CAP_USD = 10.0


@dataclass(frozen=True)
class OpenRouterRequestPolicy:
    """Frozen paid-call constraints applied below the external agent."""

    prompt_price_per_million: float
    completion_price_per_million: float

    def __post_init__(self) -> None:
        for value in (
            self.prompt_price_per_million,
            self.completion_price_per_million,
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError("OpenRouter max price must be finite and positive.")

    def apply(self, request: Mapping[str, object]) -> dict[str, object]:
        """Return the exact request allowed to cross the paid-call boundary."""
        if request.get("model") != MODEL:
            raise ValueError(f"RMSO paid calls require the exact model {MODEL!r}.")
        if "models" in request or "route" in request:
            raise ValueError("RMSO paid calls prohibit model fallback routing.")
        locked = dict(request)
        locked.pop("reasoning_effort", None)
        locked.pop("max_completion_tokens", None)
        locked.update(
            {
                "model": MODEL,
                "temperature": 0,
                "reasoning": {"effort": "high"},
                "max_tokens": MAX_OUTPUT_TOKENS,
                "provider": {
                    "sort": "price",
                    "require_parameters": True,
                    "allow_fallbacks": True,
                    "max_price": {
                        "prompt": self.prompt_price_per_million,
                        "completion": self.completion_price_per_million,
                    },
                },
            }
        )
        return locked

    def reserve_call(
        self,
        *,
        input_tokens: int,
        actual_spend: float,
        active_reservations: float,
    ) -> float:
        """Reserve the call's worst-case charge or reject the paid call."""
        if (
            not isinstance(input_tokens, int)
            or isinstance(input_tokens, bool)
            or input_tokens < 0
        ):
            raise ValueError("Input token count must be a non-negative integer.")
        for value in (actual_spend, active_reservations):
            if not isfinite(value) or value < 0:
                raise ValueError(
                    "Spend accounting values must be finite and non-negative."
                )
        reservation = (
            input_tokens * self.prompt_price_per_million
            + MAX_OUTPUT_TOKENS * self.completion_price_per_million
        ) / 1_000_000
        if (
            actual_spend + active_reservations + reservation
            > CUMULATIVE_SPEND_CAP_USD
        ):
            raise ValueError("RMSO cumulative paid-call spend cap would be exceeded.")
        return reservation
