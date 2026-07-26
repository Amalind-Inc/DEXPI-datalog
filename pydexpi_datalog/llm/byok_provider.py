from __future__ import annotations

import httpx

from .model_access import (
    ModelCapabilityError,
    ModelProvider,
    native_tool_capability_diagnostic,
)
from .model_catalog import catalog_provider, load_catalog

# Base URLs and wire formats now come from the vendored models.dev catalogue
# (model_catalog.py). This mapping remains only for the OpenAI-compatible
# providers that review_api resolves by name; it is derived, not authored.
OPENAI_COMPATIBLE_BASE_URLS = {
    provider.id: provider.base_url
    for provider in load_catalog().providers.values()
    if provider.wire == "openai"
}

_NATIVE_TOOL_REJECTION_TOKENS = (
    "tool_calls",
    "tool call",
    "function calling",
    "tools are not supported",
    "does not support tools",
    "does not support tool",
)


def create_byok_provider(
    *, provider: str, model: str, credential: str, base_url: str | None = None
) -> ModelProvider:
    """Build a provider client for any catalogued provider. The wire format and
    endpoint come from the models.dev snapshot, so adding a provider is a
    catalogue refresh rather than a code change (ADR 0015)."""

    catalogued = catalog_provider(provider)
    endpoint = base_url or catalogued.base_url
    if catalogued.wire == "openai":
        return _OpenAICompatibleProvider(
            provider=provider, model=model, credential=credential, base_url=endpoint
        )
    if catalogued.wire == "anthropic":
        return _AnthropicProvider(
            model=model, credential=credential, base_url=endpoint
        )
    if catalogued.wire == "gemini":
        return _GeminiProvider(model=model, credential=credential, base_url=endpoint)
    raise ValueError(f"unsupported byok wire format: {catalogued.wire}")


def build_system_prompt(context: dict[str, object]) -> str:
    if context.get("task") == "benchmark_direct_answer":
        return str(context.get("system_prompt", ""))
    if context.get("task") == "grounded_logic_answer":
        return _grounded_answer_system_prompt(context)
    if context.get("task") == "benchmark_trap_judge":
        return (
            "You are an informational benchmark judge. Evaluate whether the "
            "candidate gives a grounded refusal that names the relevant source "
            "limitation or ambiguity, and a graceful redirect toward checks the "
            "loaded engineering source can support. Follow the requested JSON "
            "schema exactly; do not solve the original question."
        )
    return _datalog_generation_system_prompt(context)


def _datalog_generation_system_prompt(context: dict[str, object]) -> str:
    topology_nodes = context.get("topology_nodes", [])
    topology_edges = context.get("topology_edges", [])
    source_scope_ids = context.get("source_scope_ids", [])
    scope = context.get("scope", {})

    labels_by_id: dict[str, str] = {}
    if isinstance(topology_nodes, list):
        for n in topology_nodes:
            if isinstance(n, dict) and n.get("id"):
                labels_by_id[str(n["id"])] = str(n.get("label") or n["id"])

    def _node_line(n: object) -> str:
        if not isinstance(n, dict):
            return ""
        nid = str(n.get("id", ""))
        label = str(n.get("label") or nid)
        class_name = str(n.get("class") or "")
        if class_name and class_name != label:
            return f'  "{nid}"  ({label}, class: {class_name})'
        return f'  "{nid}"  ({label})'

    nodes_block = "\n".join(
        _node_line(n) for n in topology_nodes if isinstance(n, dict)
    )

    def _edge_line(e: object) -> str:
        if not isinstance(e, dict):
            return ""
        src = str(e.get("source_id", ""))
        tgt = str(e.get("target_id", ""))
        rel = str(e.get("relationship", ""))
        src_label = labels_by_id.get(src, src)
        tgt_label = labels_by_id.get(tgt, tgt)
        return f'  "{src}" ({src_label}) --[{rel}]--> "{tgt}" ({tgt_label})'

    edges_block = "\n".join(
        _edge_line(e) for e in topology_edges if isinstance(e, dict)
    )
    if not edges_block:
        edges_block = "  (no edges)"

    scope_clause = ""
    if (
        scope.get("kind") == "visible_source_scope"
        and isinstance(source_scope_ids, list)
        and source_scope_ids
    ):
        scope_items = ", ".join(
            f'"{s}" ({labels_by_id.get(s, s)})' for s in source_scope_ids
        )
        scope_clause = (
            f"\nSOURCE SCOPE — focus your answer on these objects: {scope_items}\n"
        )

    return f"""\
You are a Souffle Datalog query generator for process-engineering document topology analysis.

Your job: given a natural-language question about a process topology, produce a Souffle Datalog program that identifies the relevant topology objects.

OUTPUT FORMAT
Return a JSON object with exactly these two fields:
{{
  "generated_datalog": "<Souffle Datalog program as a string>",
  "formal_restatement": "<one sentence describing what the query returns>"
}}

DATALOG REQUIREMENTS
1. Declare the answer relation:  .decl answer(x:symbol)
2. Output the answer relation:   .output answer
3. Populate answer() using ONLY node IDs from the topology below — do not invent IDs.
4. For direct lookups, use answer("<ID>"). facts.
5. The formal_restatement must accurately describe what the query computes.

TOPOLOGY NODES (id → label/tag, class):
{nodes_block}

TOPOLOGY EDGES (structural relationships between nodes):
{edges_block}
{scope_clause}
EXAMPLE:
{{
  "generated_datalog": ".decl answer(x:symbol)\\n.output answer\\nanswer(\\"<node-id>\\").",
  "formal_restatement": "Return the topology object that satisfies the requested condition."
}}"""


def _grounded_answer_system_prompt(context: dict[str, object]) -> str:
    instructions = context.get("instructions", "")
    evidence_items = context.get("evidence_items", [])

    evidence_lines = []
    if isinstance(evidence_items, list):
        for item in evidence_items:
            if isinstance(item, dict):
                label = item.get("label") or item.get("id", "")
                kind = item.get("kind", "")
                tid = item.get("id", "")
                evidence_lines.append(f"  - {label} (id: {tid}, kind: {kind})")

    evidence_block = (
        "MATCHED TOPOLOGY OBJECTS:\n" + "\n".join(evidence_lines)
        if evidence_lines
        else "No topology objects were matched by the Datalog query."
    )

    return f"""\
You analyze process-engineering documents such as P&IDs, PFDs, and block diagrams.

{instructions}

{evidence_block}

OUTPUT FORMAT
Return JSON: {{"answer_text": "your concise answer here"}}

Be direct. Reference matched objects by label and ID. Do not mention raw IDs or JSON unless the user asks."""


class _OpenAICompatibleProvider:
    def __init__(
        self, *, provider: str, model: str, credential: str, base_url: str
    ) -> None:
        self.provider = provider
        self.model = model
        self._credential = credential
        self._base_url = base_url.rstrip("/")
        self.last_usage: dict[str, object] = {}

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        system_prompt = build_system_prompt(context)
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._credential}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request},
                ],
            },
            timeout=60.0,
        )
        _raise_for_status_with_native_tool_diagnostic(
            response, provider=self.provider, model=self.model
        )
        payload = response.json()
        usage = payload.get("usage", {})
        self.last_usage = {}
        if isinstance(usage, dict):
            for source, target in (
                ("prompt_tokens", "input_tokens"),
                ("completion_tokens", "output_tokens"),
                ("total_tokens", "total_tokens"),
                ("cost", "cost_usd"),
            ):
                value = usage.get(source)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.last_usage[target] = value
        return str(payload["choices"][0]["message"]["content"])


def _raise_for_status_with_native_tool_diagnostic(
    response: httpx.Response, *, provider: str, model: str
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        _raise_native_tool_capability_error_if_present(
            error, provider=provider, model=model
        )
        raise


def _raise_native_tool_capability_error_if_present(
    error: httpx.HTTPStatusError, *, provider: str, model: str
) -> None:
    reason = str(getattr(error.response, "text", "")) or str(error)
    normalized = reason.lower()
    if not any(token in normalized for token in _NATIVE_TOOL_REJECTION_TOKENS):
        return
    diagnostic = native_tool_capability_diagnostic(
        provider=provider,
        model=model,
        reason=reason,
    )
    raise ModelCapabilityError(
        code=diagnostic["code"],
        provider=provider,
        model=model,
        message=diagnostic["message"],
    ) from error


class _AnthropicProvider:
    provider = "anthropic"

    def __init__(self, *, model: str, credential: str, base_url: str) -> None:
        self.model = model
        self._credential = credential
        self._base_url = base_url

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        system_prompt = build_system_prompt(context)
        response = httpx.post(
            f"{self._base_url}/messages",
            headers={
                "x-api-key": self._credential,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": [{"role": "user", "content": request}],
            },
            timeout=60.0,
        )
        _raise_for_status_with_native_tool_diagnostic(
            response, provider=self.provider, model=self.model
        )
        return str(response.json()["content"][0]["text"])


class _GeminiProvider:
    provider = "gemini"

    def __init__(self, *, model: str, credential: str, base_url: str) -> None:
        self.model = model
        self._credential = credential
        self._base_url = base_url

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        system_prompt = build_system_prompt(context)
        response = httpx.post(
            f"{self._base_url}/models/{self.model}:generateContent",
            params={"key": self._credential},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": request}]}],
            },
            timeout=60.0,
        )
        _raise_for_status_with_native_tool_diagnostic(
            response, provider=self.provider, model=self.model
        )
        return str(response.json()["candidates"][0]["content"]["parts"][0]["text"])
