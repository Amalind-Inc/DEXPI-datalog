"""Live regression for numeric-threshold questions (37x.22.34.5).

The typed ``node_numeric_attribute`` predicate executes inside the Souffle
rule-pack path (``discharge_line_min_diameter``); the read-only QA tool
surface does not expose numeric attribute values. A real tool-capable model
asked a numeric-threshold question must therefore route it to the
confirmation-gated temporary-Datalog path (or explicitly say the loaded
evidence cannot answer) -- and must NEVER invent a pass/fail verdict about
a threshold it cannot read.

Opt-in like the other live sets: set HARBORFIELD_LIVE_QA_PROVIDER and
HARBORFIELD_LIVE_QA_MODEL (plus the provider credential env var) to run.

The correct-outcome half of the acceptance criterion (DN 80 >= DN 25 ->
satisfied through real Souffle) is deterministic and pinned in
tests/verification/test_discharge_line_min_diameter.py; this module pins the
live-model half: honest routing instead of hallucinated numerics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pydexpi_datalog.llm.byok_provider import OPENAI_COMPATIBLE_BASE_URLS
from pydexpi_datalog.llm.model_access import supported_byok_provider
from pydexpi_datalog.qa.grounded_qa_harness import run_grounded_qa_turn
from pydexpi_datalog.qa.ollama_qa_provider import OllamaQATurnProvider
from pydexpi_datalog.qa.openai_compatible_qa_provider import (
    OpenAICompatibleQATurnProvider,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.verification.bundled_rule_pack import evaluate_bundled_rule

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"

QUESTION = (
    "Must the pump discharge line have a nominal diameter of at least DN 25?"
)


def _live_provider():
    provider_name = os.environ.get("HARBORFIELD_LIVE_QA_PROVIDER", "")
    model = os.environ.get("HARBORFIELD_LIVE_QA_MODEL", "")
    if not provider_name or not model:
        pytest.skip(
            "live model regression: set HARBORFIELD_LIVE_QA_PROVIDER and "
            "HARBORFIELD_LIVE_QA_MODEL to run"
        )
    base_url = os.environ.get(
        "HARBORFIELD_LIVE_QA_BASE_URL",
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


def _e06_topology_tools() -> TopologyTools:
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    nodes = [
        {
            "id": node["node_id"],
            "label": node["attributes"].get("label", ""),
            "tag_name": node["attributes"].get("tagName", ""),
        }
        for node in graph_facts["facts"]["nodes"]
    ]
    return TopologyTools(
        topology_view={
            "nodes": nodes,
            "edges": [],
            "evidence_map": {node["id"]: {"kind": "node"} for node in nodes},
        },
        session_id="live-numeric-session",
    )


def test_rule_pack_outcome_is_correct_for_the_live_question() -> None:
    """Deterministic anchor: the Souffle predicate answers the same question
    the live model is asked, and the answer is objectively correct (DN 80)."""
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    result = evaluate_bundled_rule(
        graph_facts,
        pack_id="demo-process-safety",
        rule_id="discharge_line_min_diameter",
    )
    assert result["outcome"] == "satisfied"
    assert "DN 80" in str(result["message"])


def test_numeric_threshold_question_routes_to_gate_never_invents_a_verdict() -> None:
    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=_e06_topology_tools(),
        provider=_live_provider(),
    )

    proposed = any(
        trace.get("tool_name") == "propose_temporary_datalog"
        and isinstance(trace.get("tool_result"), dict)
        and trace["tool_result"].get("status")
        in {"answered", "rejected", "execution_failed"}
        for trace in result.tool_call_trace
    )
    answer = result.answer_text.lower()
    declined = result.source_grounded is False and any(
        cue in answer for cue in ("unavailable", "cannot", "not able", "confirm")
    )

    assert proposed or declined, (
        "expected the numeric-threshold question to reach temporary Datalog "
        f"or an explicit decline, got: {result.answer_text!r}"
    )
    # Never a fabricated numeric verdict: an ungated grounded pass/fail about
    # the DN threshold is exactly the hallucination this test forbids.
    if not proposed:
        assert not (
            result.source_grounded
            and ("dn 80" in answer or "satisfied" in answer or "meets" in answer)
        ), f"ungated numeric verdict fabricated: {result.answer_text!r}"
