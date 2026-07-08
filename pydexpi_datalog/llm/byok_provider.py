from __future__ import annotations

import httpx

from .model_access import ModelCapabilityError, ModelProvider, native_tool_capability_diagnostic


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENAI_BASE_URL = "https://api.openai.com/v1"
_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"

# Providers reachable through a plain OpenAI-compatible /chat/completions
# endpoint (including native tool_calls). Anthropic and Gemini use different
# request/response shapes and are not part of this family.
OPENAI_COMPATIBLE_BASE_URLS = {
    "openai": _OPENAI_BASE_URL,
    "openrouter": _OPENROUTER_BASE_URL,
    "ollama": _OLLAMA_DEFAULT_BASE_URL,
}

_NATIVE_TOOL_REJECTION_TOKENS = (
    "tool_calls",
    "tool call",
    "function calling",
    "tools are not supported",
    "does not support tools",
    "does not support tool",
)



def create_byok_provider(*, provider: str, model: str, credential: str) -> ModelProvider:
    if provider in ("openai", "openrouter"):
        base_url = _OPENROUTER_BASE_URL if provider == "openrouter" else _OPENAI_BASE_URL
        return _OpenAICompatibleProvider(
            provider=provider, model=model, credential=credential, base_url=base_url
        )
    if provider == "anthropic":
        return _AnthropicProvider(model=model, credential=credential)
    if provider == "gemini":
        return _GeminiProvider(model=model, credential=credential)
    raise ValueError(f"unsupported byok provider: {provider}")


def build_system_prompt(context: dict[str, object]) -> str:
    if context.get("task") == "grounded_logic_answer":
        return _grounded_answer_system_prompt(context)
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

    nodes_block = "\n".join(_node_line(n) for n in topology_nodes if isinstance(n, dict))

    def _edge_line(e: object) -> str:
        if not isinstance(e, dict):
            return ""
        src = str(e.get("source_id", ""))
        tgt = str(e.get("target_id", ""))
        rel = str(e.get("relationship", ""))
        src_label = labels_by_id.get(src, src)
        tgt_label = labels_by_id.get(tgt, tgt)
        return f'  "{src}" ({src_label}) --[{rel}]--> "{tgt}" ({tgt_label})'

    edges_block = "\n".join(_edge_line(e) for e in topology_edges if isinstance(e, dict))
    if not edges_block:
        edges_block = "  (no edges)"

    scope_clause = ""
    if scope.get("kind") == "visible_source_scope" and isinstance(source_scope_ids, list) and source_scope_ids:
        scope_items = ", ".join(
            f'"{s}" ({labels_by_id.get(s, s)})' for s in source_scope_ids
        )
        scope_clause = f"\nSOURCE SCOPE — focus your answer on these objects: {scope_items}\n"

    return f"""\
You are a Souffle Datalog query generator for P&ID (Piping and Instrumentation Diagram) topology analysis.

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
You are a P&ID (Process and Instrumentation Diagram) analysis assistant.

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
        return str(response.json()["choices"][0]["message"]["content"])



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

    def __init__(self, *, model: str, credential: str) -> None:
        self.model = model
        self._credential = credential

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        system_prompt = build_system_prompt(context)
        response = httpx.post(
            f"{_ANTHROPIC_BASE_URL}/messages",
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

    def __init__(self, *, model: str, credential: str) -> None:
        self.model = model
        self._credential = credential

    def complete(self, *, request: str, context: dict[str, object]) -> str:
        system_prompt = build_system_prompt(context)
        response = httpx.post(
            f"{_GEMINI_BASE_URL}/models/{self.model}:generateContent",
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
        return str(
            response.json()["candidates"][0]["content"]["parts"][0]["text"]
        )
