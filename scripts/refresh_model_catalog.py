"""Regenerate the vendored BYOK model catalogue from models.dev.

The catalogue is vendored rather than fetched at runtime so that provider
resolution is deterministic, works offline, and cannot be changed underneath a
running review by an upstream edit. Re-run this script to pick up new providers
and models:

    python scripts/refresh_model_catalog.py

Then commit the regenerated pydexpi_datalog/llm/model_catalog.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

CATALOG_URL = "https://models.dev/api.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "pydexpi_datalog" / "llm" / "model_catalog.json"

# Wire formats we can actually speak. Everything else (Bedrock sigv4, Azure
# deployment routing, Vertex ADC, bespoke vendor SDKs) is skipped rather than
# offered and then failed at request time.
_OPENAI_WIRE_PACKAGES = {
    "@ai-sdk/openai",
    "@ai-sdk/openai-compatible",
    # First-party vendor SDKs that are OpenAI-compatible over the wire.
    "@ai-sdk/cerebras",
    "@ai-sdk/cohere",
    "@ai-sdk/deepinfra",
    "@ai-sdk/groq",
    "@ai-sdk/mistral",
    "@ai-sdk/togetherai",
    "@ai-sdk/xai",
    "@openrouter/ai-sdk-provider",
}
_WIRE_BY_PACKAGE = {
    "@ai-sdk/anthropic": "anthropic",
    "@ai-sdk/google": "gemini",
}

# Providers that omit `api` in models.dev because the base URL is baked into
# their vendor SDK. Each endpoint below was probed for a 401/400 auth
# challenge, confirming the host and path exist.
_DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "cohere": "https://api.cohere.ai/compatibility/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openai": "https://api.openai.com/v1",
    "togetherai": "https://api.together.xyz/v1",
    "xai": "https://api.x.ai/v1",
}

# Where a provider lists several credential env vars, the one we document.
_PREFERRED_ENV_VAR = {"google": "GEMINI_API_KEY"}

# Shown first in the picker. Everything else is reachable by search.
FEATURED_PROVIDERS = (
    "openrouter",
    "anthropic",
    "openai",
    "google",
    "xai",
    "deepseek",
    "groq",
    "mistral",
    "togetherai",
    "fireworks-ai",
    "cerebras",
    "zhipuai",
)


def wire_format(provider_id: str, provider: dict[str, Any]) -> str | None:
    package = provider.get("npm")
    if package in _WIRE_BY_PACKAGE:
        return _WIRE_BY_PACKAGE[package]
    if package in _OPENAI_WIRE_PACKAGES:
        return "openai"
    return None


def credential_env_var(provider_id: str, provider: dict[str, Any]) -> str | None:
    env_vars = [name for name in provider.get("env", []) if name]
    if not env_vars:
        return None
    preferred = _PREFERRED_ENV_VAR.get(provider_id)
    if preferred and preferred in env_vars:
        return preferred
    # A provider needing more than one value (account id, resource name, region)
    # cannot be configured from a single API-key field.
    return env_vars[0] if len(env_vars) == 1 else None


def is_transport_safe(base_url: str) -> bool:
    """A credential may only cross the network over TLS. Plaintext is tolerated
    solely for loopback endpoints, where local model servers (LM Studio and
    friends) legitimately serve http and nothing leaves the machine."""

    if base_url.startswith("https://"):
        return True
    host = urlparse(base_url).hostname or ""
    return host in {"127.0.0.1", "::1", "localhost"}


def trim_provider(provider_id: str, provider: dict[str, Any]) -> dict[str, Any] | None:
    wire = wire_format(provider_id, provider)
    base_url = provider.get("api") or _DEFAULT_BASE_URL.get(provider_id)
    env_var = credential_env_var(provider_id, provider)
    if not (wire and base_url and env_var and is_transport_safe(base_url)):
        return None

    models = []
    for model in provider.get("models", {}).values():
        # Grounded QA drives the model through native tool calls, so a model
        # that does not advertise them cannot be offered at all.
        if model.get("tool_call") is not True:
            continue
        models.append(
            {
                "id": model["id"],
                "name": model.get("name", model["id"]),
                "context": (model.get("limit") or {}).get("context"),
                "reasoning": bool(model.get("reasoning")),
                "released": model.get("release_date") or "",
            }
        )
    if not models:
        return None

    # Newest first: the picker's default is the head of this list, and an
    # alphabetical default would land on whatever model happens to sort first
    # (an aggregator's 273 models would default to "ai21/jamba-...").
    models.sort(key=lambda entry: (entry["released"], entry["id"]), reverse=True)
    return {
        "name": provider.get("name", provider_id),
        "wire": wire,
        "base_url": base_url.rstrip("/"),
        "env_var": env_var,
        "doc": provider.get("doc", ""),
        "models": models,
    }


def build_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    providers = {}
    for provider_id, provider in sorted(raw.items()):
        trimmed = trim_provider(provider_id, provider)
        if trimmed is not None:
            providers[provider_id] = trimmed
    return {
        "source": CATALOG_URL,
        "featured": [pid for pid in FEATURED_PROVIDERS if pid in providers],
        "providers": providers,
    }


def main() -> None:
    raw = httpx.get(CATALOG_URL, timeout=60.0).raise_for_status().json()
    catalog = build_catalog(raw)
    OUTPUT_PATH.write_text(json.dumps(catalog, indent=1, sort_keys=True) + "\n")

    model_count = sum(len(p["models"]) for p in catalog["providers"].values())
    print(
        f"wrote {OUTPUT_PATH.relative_to(Path.cwd())}: "
        f"{len(catalog['providers'])} providers, {model_count} models, "
        f"{OUTPUT_PATH.stat().st_size / 1024:.0f} KiB"
    )


if __name__ == "__main__":
    main()
