from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from ..workflow.workflow_policy import OSS_POLICY, WorkflowPolicy


@dataclass(frozen=True)
class ModelAccessConfig:
    access_mode: str
    provider: str
    model: str
    api_key_env_var: str
    has_credentials: bool

    def metadata(self) -> dict[str, object]:
        return {
            "access_mode": self.access_mode,
            "provider": self.provider,
            "model": self.model,
            "api_key_env_var": self.api_key_env_var,
            "has_credentials": self.has_credentials,
        }


class ModelProvider(Protocol):
    provider: str
    model: str

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        ...


class FakeModelProvider:
    provider = "fake"
    model = "fake-model"

    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        self.requests.append({"request": request, "context": context})
        return self.response


def resolve_model_access_config(
    *,
    policy: WorkflowPolicy = OSS_POLICY,
    provider: str = "openai",
    model: str = "gpt-4.1",
    environ: dict[str, str] | None = None,
) -> ModelAccessConfig:
    env = os.environ if environ is None else environ
    api_key_env_var = "OPENAI_API_KEY" if provider == "openai" else f"{provider.upper()}_API_KEY"
    return ModelAccessConfig(
        access_mode=policy.model_access,
        provider=provider,
        model=model,
        api_key_env_var=api_key_env_var,
        has_credentials=bool(env.get(api_key_env_var)),
    )


def missing_byok_credentials_diagnostic(
    config: ModelAccessConfig,
) -> dict[str, str]:
    return {
        "code": "model_access.missing_byok_credentials",
        "message": (
            "OSS logic requests require user-supplied model provider credentials. "
            f"Set {config.api_key_env_var} to use {config.provider}."
        ),
    }
