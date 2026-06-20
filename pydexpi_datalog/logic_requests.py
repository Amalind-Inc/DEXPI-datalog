from __future__ import annotations

from .model_access import (
    ModelProvider,
    missing_byok_credentials_diagnostic,
    resolve_model_access_config,
)


def draft_logic_request(
    *,
    logic_request: str,
    provider: ModelProvider | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    model_access = resolve_model_access_config(environ=environ)
    artifact: dict[str, object] = {
        "artifact_type": "logic_request_draft",
        "logic_request": logic_request,
        "route": route_logic_request(logic_request),
        "model_access": model_access.metadata(),
        "diagnostics": [],
    }

    if not model_access.has_credentials:
        artifact["status"] = "failed"
        artifact["diagnostics"] = [missing_byok_credentials_diagnostic(model_access)]
        return artifact

    if provider is None:
        artifact["status"] = "failed"
        artifact["diagnostics"] = [
            {
                "code": "model_access.provider_not_configured",
                "message": "No model provider adapter was configured for this logic request.",
            }
        ]
        return artifact

    response = provider.complete(
        request=logic_request,
        context={
            "route": artifact["route"],
            "model_access": model_access.metadata(),
        },
    )
    artifact["status"] = "drafted"
    artifact["draft"] = {
        "provider": provider.provider,
        "model": provider.model,
        "text": response,
    }
    return artifact


def route_logic_request(logic_request: str) -> dict[str, str]:
    normalized = logic_request.lower()
    if any(term in normalized for term in ("downstream", "reachable", "connected", "source")):
        return {"kind": "topology_logic"}
    if any(term in normalized for term in ("what is", "explain", "document")):
        return {"kind": "documentation_answer"}
    return {"kind": "clarification"}
