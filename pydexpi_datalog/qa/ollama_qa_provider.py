from __future__ import annotations

from .openai_compatible_qa_provider import OpenAICompatibleQATurnProvider

_DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaQATurnProvider(OpenAICompatibleQATurnProvider):
    """QATurnProvider backed by a local Ollama model over the OpenAI-compatible API.

    A thin, no-credential preset of OpenAICompatibleQATurnProvider — see that
    class for the shared tool-calling contract (native tool_calls only, no
    pseudo-tool-call text parsing).
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(provider="ollama", model=model, base_url=base_url, credential=None)
