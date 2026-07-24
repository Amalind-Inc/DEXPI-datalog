from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from ..workflow.workflow_policy import OSS_POLICY, WorkflowPolicy
from .model_catalog import catalog_provider, is_catalogued_model, load_catalog


# Provider and model support is no longer hand-maintained here: it comes from
# the vendored models.dev snapshot (see model_catalog.py, ADR 0015). The
# snapshot only contains models advertising native tool calls, so catalogue
# membership is the capability gate grounded QA needs.


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
    """Legacy shape retained for callers that only need the credential env var
    and a sensible default model."""

    catalogued = catalog_provider(provider)
    default_model = next(iter(catalogued.models), "")
    return {
        "api_key_env_var": catalogued.env_var,
        "default_model": default_model,
    }


def supported_native_tool_models() -> set[tuple[str, str]]:
    """Exact provider/model pairs whose metadata advertises native tool calls."""

    return {
        (provider.id, model_id)
        for provider in load_catalog().providers.values()
        for model_id in provider.models
    }


def require_native_tool_capable_model(*, provider: str, model: str) -> None:
    # Raises UnknownProviderError (a ValueError) for a provider outside the
    # catalogue, matching the previous contract.
    catalog_provider(provider)
    if is_catalogued_model(provider, model):
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
