"""Live regression for real ad-hoc Datalog execution (37x.22.34.4).

The confirmed temporary-Datalog executor is a real Souffle subprocess, not a
regex over two blessed text shapes. This module pins the live-model half of
the bead's acceptance: a real tool-calling model drafts one natural-language
rule question into temporary Datalog, the proposal is confirmed exactly as
the web workflow would confirm it, and real execution produces a correct,
non-empty grounded outcome (evidence drawn from the objects genuinely
structurally reachable in the E06 source).

Opt-in like the other live sets: set PYDEXPI_LIVE_QA_PROVIDER and
PYDEXPI_LIVE_QA_MODEL (plus the provider credential env var) to run.

The deterministic half (engine correctness, explicit failure instead of
silent-empty answers, legacy-shape parity) is pinned in
tests/qa/test_temporary_datalog.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pydexpi_datalog.llm.model_access import supported_byok_provider
from pydexpi_datalog.qa.grounded_qa_harness import run_grounded_qa_turn
from pydexpi_datalog.qa.ollama_qa_provider import OllamaQATurnProvider
from pydexpi_datalog.qa.openai_compatible_qa_provider import (
    OpenAICompatibleQATurnProvider,
)
from pydexpi_datalog.qa.topology_tools import TopologyTools

OPENAI_COMPATIBLE_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every live run captures the model-drafted proposal here so validation and
# execution issues can be reproduced offline (deterministically, in
# milliseconds) instead of re-paying a multi-round live model conversation.
CAPTURE_PATH = REPO_ROOT / ".tmp" / "live-captures" / "adhoc-datalog-proposal.json"
E06_GRAPH_FACTS = REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"

QUESTION = (
    "Must every object structurally connected to the piping network also be "
    "reachable from it? List the reachable objects."
)

JOIN_QUESTION = (
    "Using the temporary Datalog predicate contract, list the loaded source "
    "objects that appear as the first argument/source in a direct process "
    "connection."
)


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
        graph_facts=graph_facts,
        session_id="live-adhoc-souffle-session",
    )


def test_model_drafted_generic_schema_join_confirms_executes_and_grounds() -> None:
    """A real model drafts a query using a generic schema predicate beyond
    the old {answer, reachable} surface, and confirmed execution returns the
    same process-connection source objects computed by Souffle."""
    tools = _e06_topology_tools()
    result = run_grounded_qa_turn(
        question=JOIN_QUESTION,
        topology_tools=tools,
        provider=_live_provider(),
    )

    proposal_results = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace.get("tool_name") == "propose_temporary_datalog"
        and isinstance(trace.get("tool_result"), dict)
        and trace["tool_result"].get("status") == "answered"
    ]
    assert proposal_results, (
        "expected the live model to draft the join question into an "
        f"automatically executed temporary Datalog proposal, got: {result.answer_text!r}"
    )
    proposal_result = proposal_results[-1]
    CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE_PATH.write_text(
        json.dumps(proposal_result, indent=2, default=str), encoding="utf-8"
    )
    assert proposal_result.get("executed") is True
    assert proposal_result["disclosure"]["validation"]["status"] == "safe_to_confirm"
    assert (
        "direct_process_connection"
        in proposal_result["disclosure"]["inspectable_datalog"]["generated_datalog"]
    )
    answer = proposal_result

    assert answer["status"] == "answered", f"execution failed: {answer!r}"
    assert {item["id"] for item in answer["evidence"]["items"]} == {
        "3b212201-f8b6-47ed-9019-d7961f3276c8",
        "72b41d51-c363-4b85-94d4-03d0f1a19a63",
    }


def test_model_drafted_datalog_executes_automatically_and_grounds_a_correct_answer() -> None:
    """A real model drafts temporary Datalog that executes automatically on
    real Souffle and yields non-empty evidence that is a subset of the
    session's known evidence identities."""
    tools = _e06_topology_tools()
    result = run_grounded_qa_turn(
        question=QUESTION,
        topology_tools=tools,
        provider=_live_provider(),
    )

    proposal_results = [
        trace["tool_result"]
        for trace in result.tool_call_trace
        if trace.get("tool_name") == "propose_temporary_datalog"
        and isinstance(trace.get("tool_result"), dict)
        and trace["tool_result"].get("status") == "answered"
    ]
    assert proposal_results, (
        "expected the live model to draft the rule question into an "
        f"automatically executed temporary Datalog proposal, got: {result.answer_text!r}"
    )
    proposal_result = proposal_results[-1]
    CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE_PATH.write_text(
        json.dumps(proposal_result, indent=2, default=str), encoding="utf-8"
    )
    answer = proposal_result

    assert answer["status"] == "answered", f"execution failed: {answer!r}"
    assert answer["executed"] is True
    items = answer["evidence"]["items"]
    assert items, "automatic execution must ground the answer in evidence"
    known_ids = tools.known_evidence_ids()
    assert all(item["id"] in known_ids for item in items), (
        "executed evidence must reference known session evidence identities"
    )
