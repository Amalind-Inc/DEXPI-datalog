"""Live regression prompt set for off-topic acknowledgment-then-redirect (37x.22.34.3).

The out_of_scope grounding posture is model-owned behavior driven by
GROUNDING_DISCLOSURE_POLICY prompt text -- there is deliberately no backend
intent classifier. These tests run a small fixed set of real off-topic
questions against a real tool-capable model and check *behavioral shape*, not
exact wording: the answer briefly acknowledges the question (it is not a bare
refusal) and then redirects back to P&ID review.

Opt-in: skipped unless PYDEXPI_LIVE_QA_PROVIDER and PYDEXPI_LIVE_QA_MODEL are
set (e.g. PYDEXPI_LIVE_QA_PROVIDER=openrouter PYDEXPI_LIVE_QA_MODEL=... with
the provider's API-key env var exported; or PYDEXPI_LIVE_QA_PROVIDER=ollama
with a local server running).
"""

from __future__ import annotations

import os

import pytest

from pydexpi_datalog.llm.byok_provider import OPENAI_COMPATIBLE_BASE_URLS
from pydexpi_datalog.llm.model_access import supported_byok_provider
from pydexpi_datalog.qa.grounded_qa_harness import (
    POSTURE_OUT_OF_SCOPE,
    POSTURE_UNSPECIFIED,
    run_grounded_qa_turn,
)
from pydexpi_datalog.qa.ollama_qa_provider import OllamaQATurnProvider
from pydexpi_datalog.qa.openai_compatible_qa_provider import (
    OpenAICompatibleQATurnProvider,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

MINIMAL_TOPOLOGY: dict[str, object] = {
    "nodes": [
        {"id": "node-pump", "label": "Pump", "tag_name": "P-101"},
        {"id": "node-valve", "label": "Valve", "tag_name": "V-102"},
    ],
    "edges": [
        {
            "id": "edge-pump-valve",
            "source_id": "node-pump",
            "target_id": "node-valve",
            "relationship": "connections",
        }
    ],
    "evidence_map": {
        "node-pump": {"kind": "node"},
        "node-valve": {"kind": "node"},
        "edge-pump-valve": {"kind": "edge"},
    },
}

_REDIRECT_CUES = ("p&id", "pid", "source", "diagram", "review", "loaded")
_REFUSAL_OPENERS = ("i cannot", "i can't", "i am unable", "i'm unable", "sorry")

# question -> tokens, any of which count as a topical acknowledgment. Empty
# means "rely on the non-refusal check only" (e.g. we cannot predict which
# model name the provider reports).
_OFF_TOPIC_PROMPTS: dict[str, tuple[str, ...]] = {
    "What model am I talking to?": ("model", "assistant", "ai"),
    "What color is the sky?": ("blue",),
    "Tell me a joke.": (),
}


def _live_provider():
    provider_name = os.environ.get("PYDEXPI_LIVE_QA_PROVIDER", "")
    model = os.environ.get("PYDEXPI_LIVE_QA_MODEL", "")
    if not provider_name or not model:
        pytest.skip(
            "live model regression: set PYDEXPI_LIVE_QA_PROVIDER and "
            "PYDEXPI_LIVE_QA_MODEL to run"
        )
    base_url = os.environ.get(
        "PYDEXPI_LIVE_QA_BASE_URL",
        OPENAI_COMPATIBLE_BASE_URLS.get(provider_name, ""),
    )
    if provider_name == "ollama":
        return OllamaQATurnProvider(model=model, base_url=base_url)
    credential = os.environ.get(
        str(supported_byok_provider(provider_name)["api_key_env_var"])
    )
    if not credential:
        pytest.skip(f"live model regression: no credential for {provider_name}")
    return OpenAICompatibleQATurnProvider(
        provider=provider_name,
        model=model,
        base_url=base_url,
        credential=credential,
    )


@pytest.mark.parametrize("question", sorted(_OFF_TOPIC_PROMPTS))
def test_off_topic_question_acknowledged_then_redirected(question: str) -> None:
    result = run_grounded_qa_turn(
        question=question,
        topology_tools=TopologyTools(
            topology_view=MINIMAL_TOPOLOGY, session_id="live-offtopic-session"
        ),
        provider=_live_provider(),
    )

    answer = result.answer_text.lower()
    # The essential invariant is that an off-topic answer is never presented
    # as a source conclusion. Ideally the model declares out_of_scope via the
    # provide_answer tool; models that finalize as plain text land on
    # POSTURE_UNSPECIFIED, which the backend also treats as ungrounded.
    assert result.source_grounded is False
    assert result.grounding_posture in (POSTURE_OUT_OF_SCOPE, POSTURE_UNSPECIFIED), (
        f"expected an ungrounded off-topic posture, got "
        f"{result.grounding_posture!r}: {result.answer_text!r}"
    )
    # Redirect: the answer steers back to P&ID review.
    assert any(cue in answer for cue in _REDIRECT_CUES), (
        f"no redirect back to P&ID review in: {result.answer_text!r}"
    )
    # Acknowledgment: not a bare refusal...
    assert not answer.startswith(_REFUSAL_OPENERS), (
        f"bare refusal instead of acknowledgment: {result.answer_text!r}"
    )
    # ...and where the question has a predictable answer, it is actually
    # engaged with (regression shape, not exact wording).
    ack_tokens = _OFF_TOPIC_PROMPTS[question]
    if ack_tokens:
        assert any(token in answer for token in ack_tokens), (
            f"no acknowledgment of the question in: {result.answer_text!r}"
        )
