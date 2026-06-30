from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from ..workflow.workflow_policy import OSS_POLICY, WorkflowPolicy


SUPPORTED_BYOK_PROVIDERS = {
    "openai": {
        "api_key_env_var": "OPENAI_API_KEY",
        "default_model": "gpt-4.1",
    },
    "anthropic": {
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4",
    },
    "gemini": {
        "api_key_env_var": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-pro",
    },
    "openrouter": {
        "api_key_env_var": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-sonnet-4",
    },
    "ollama": {
        "api_key_env_var": "OLLAMA_BASE_URL",
        "default_model": "ornith:35b",
    },
}

NATIVE_TOOL_CAPABLE_MODELS = {
    ("openai", "gpt-4.1"),
    ("anthropic", "claude-sonnet-4"),
    ("gemini", "gemini-2.5-pro"),
    ("openrouter", "anthropic/claude-sonnet-4"),
    ("ollama", "ornith:35b"),
}


class ModelCapabilityError(ValueError):
    def __init__(self, *, code: str, provider: str, model: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.model = model

    def diagnostic(self) -> dict[str, str]:
        return {
            "code": self.code,
            "provider": self.provider,
            "model": self.model,
            "message": str(self),
        }



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
    provider_config = supported_byok_provider(provider)
    env = os.environ if environ is None else environ
    api_key_env_var = str(provider_config["api_key_env_var"])
    return ModelAccessConfig(
        access_mode=policy.model_access,
        provider=provider,
        model=model,
        api_key_env_var=api_key_env_var,
        has_credentials=bool(env.get(api_key_env_var)),
    )


def supported_byok_provider(provider: str) -> dict[str, str]:
    provider_config = SUPPORTED_BYOK_PROVIDERS.get(provider)
    if provider_config is None:
        allowed = ", ".join(sorted(SUPPORTED_BYOK_PROVIDERS))
        raise ValueError(
            f"unsupported model provider: {provider}. Supported providers: {allowed}"
        )
    return provider_config


def supported_native_tool_models() -> set[tuple[str, str]]:
    """Exact provider/model pairs whose metadata advertises native tool calls."""

    return set(NATIVE_TOOL_CAPABLE_MODELS)


def require_native_tool_capable_model(*, provider: str, model: str) -> None:
    supported_byok_provider(provider)
    if (provider, model) in NATIVE_TOOL_CAPABLE_MODELS:
        return
    raise ModelCapabilityError(
        code="model_access.native_tools_unsupported",
        provider=provider,
        model=model,
        message=(
            f"{provider}/{model} is not available for grounded chat because its "
            "metadata does not advertise native tool calling."
        ),
    )


def native_tool_capability_diagnostic(
    *, provider: str, model: str, reason: str
) -> dict[str, str]:
    return {
        "code": "model_access.native_tools_rejected",
        "provider": provider,
        "model": model,
        "message": (
            f"{provider}/{model} rejected native tool calling at runtime. {reason}"
        ),
    }


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
