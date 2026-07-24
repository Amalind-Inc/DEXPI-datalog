from __future__ import annotations

import shutil

import pytest

from pydexpi_datalog.qa.capability_manifest import (
    GROUNDING_DISCLOSURE_POLICY,
    PERMISSION_ALLOWED_READ_ONLY,
    default_grounded_qa_manifest,
)
from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools


STRUCTURED_INTENT = {
    "source_classes": ["Pump"],
    "target_classes": ["TopologyObject"],
    "source_role": "resolved_source",
    "target_role": "reachable_result",
    "graph_scope": "all_topology",
    "direction": "directed",
    "quantifier": "any",
    "negated": False,
    "output_obligations": ["answer_ids"],
}


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


def test_default_manifest_exposes_topology_capabilities_with_policy_metadata() -> None:
    manifest = default_grounded_qa_manifest()

    find = manifest.require("find_equipment")
    reachable = manifest.require("get_reachable_equipment")

    assert find.permission_class == PERMISSION_ALLOWED_READ_ONLY
    assert reachable.permission_class == PERMISSION_ALLOWED_READ_ONLY
    assert find.evidence_kind == "topology_object_candidates"
    assert reachable.evidence_kind == "structural_path_witness"
    assert find.source_grounding_posture == "loaded_source"
    assert reachable.citation_metadata["primary_id_field"] == "evidence_id"
    assert reachable.limitations


def test_default_manifest_declares_temporary_datalog_as_allowed_read_only() -> None:
    manifest = default_grounded_qa_manifest()

    proposal = manifest.require("propose_temporary_datalog")

    assert proposal.permission_class == PERMISSION_ALLOWED_READ_ONLY
    assert proposal.evidence_kind == "datalog_query_pair"
    assert "predicate contract" in proposal.when_to_use.lower()
    limitations = " ".join(proposal.limitations).lower()
    assert "automatic" in limitations
    assert "validated" in limitations
    assert "reusable-rule trust" in limitations
    assert "confirmation" not in limitations


def test_provider_tool_definitions_are_projected_from_manifest() -> None:
    manifest = default_grounded_qa_manifest()

    tools = manifest.provider_tool_definitions()
    tool_by_name = {tool["function"]["name"]: tool for tool in tools}

    assert set(tool_by_name) >= {
        "find_equipment",
        "get_reachable_equipment",
        "propose_temporary_datalog",
    }
    reachable_description = tool_by_name["get_reachable_equipment"]["function"][
        "description"
    ]
    assert "Permission: allowed_read_only" in reachable_description
    assert "Evidence: structural_path_witness" in reachable_description


def test_topology_tools_expose_manifest_projected_tools() -> None:
    tools = TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="s")

    initial_tool_names = {tool["function"]["name"] for tool in tools.tool_definitions()}

    assert "find_equipment" in initial_tool_names
    assert "get_reachable_equipment" in initial_tool_names
    assert "report_template_no_fit" in initial_tool_names
    # Generated Datalog is always offered; execute-time gates authorize it.
    assert "propose_temporary_datalog" in initial_tool_names

    tools.begin_request("find pumps")
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this request.",
            "structured_intent": STRUCTURED_INTENT,
        },
    )
    routed_tool_names = {tool["function"]["name"] for tool in tools.tool_definitions()}
    assert "propose_temporary_datalog" in routed_tool_names


def test_topology_tools_reject_unknown_tools_before_execution() -> None:
    tools = TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="s")

    result = tools.execute("delete_graph", {})

    assert result["status"] == "rejected"
    assert result["code"] == "tool.unknown"
    assert result["tool_name"] == "delete_graph"


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_topology_tools_execute_valid_read_only_proposals_and_reject_invalid_ones() -> (
    None
):
    tools = TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="s")
    tools.begin_request("find pumps")
    tools.execute(
        "report_template_no_fit",
        {
            "reason": "No bundled template covers this request.",
            "structured_intent": STRUCTURED_INTENT,
        },
    )

    # A valid proposal executes automatically; an invalid one is rejected back
    # to the model without execution.
    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "find pumps",
            "generated_datalog": encode_structured_intent_program(
                (
                    ".decl answer(x:symbol)\n.output answer\n"
                    'answer(x) :- reachable("node-pump", x).'
                ),
                STRUCTURED_INTENT,
            ),
            "formal_restatement": "Return objects reachable from the pump.",
            "faithfulness_review": {
                "status": "faithful",
                "back_translated_intent": STRUCTURED_INTENT,
                "diagnostics": [],
            },
        },
    )

    assert result["status"] == "answered"
    assert result["tool_name"] == "propose_temporary_datalog"
    assert result["executed"] is True
    assert result["execution_mode"] == "automatic"
    assert result["confirmation"] == {"required": False}

    rejected = tools.execute("propose_temporary_datalog", {"request": "find pumps"})
    assert rejected["status"] == "rejected"
    assert rejected["code"] == "tool.proposal_rejected"
    assert rejected["executed"] is False


def test_system_prompt_includes_grounding_disclosure_policy() -> None:
    manifest = default_grounded_qa_manifest()

    prompt = manifest.system_prompt()

    # Tool guidance and the grounding policy come from one shared projection.
    assert "find_equipment" in prompt
    for posture in (
        "source_grounded",
        "general_knowledge",
        "source_data_unavailable",
        "needs_clarification",
        "out_of_scope",
    ):
        assert posture in prompt
    assert "never invent values" in prompt.lower()


def test_topology_tools_expose_manifest_system_prompt() -> None:
    tools = TopologyTools(topology_view=MINIMAL_TOPOLOGY, session_id="s")

    assert tools.system_prompt() == default_grounded_qa_manifest().system_prompt()


def test_out_of_scope_policy_permits_acknowledgment_before_redirect() -> None:
    """37x.22.34.3: the out_of_scope posture must explicitly allow a brief,
    honest acknowledgment of an off-topic question before redirecting, rather
    than implying a bare non-answer -- while remaining model-owned prompt
    text, not a backend classifier."""
    policy = GROUNDING_DISCLOSURE_POLICY
    out_of_scope_clause = policy.split("- out_of_scope:")[1].split("\n")[0]

    assert "acknowledgment" in out_of_scope_clause
    assert "brief" in out_of_scope_clause
    assert "redirect" in out_of_scope_clause.lower()
    # Acknowledge *then* redirect: the redirect follows the acknowledgment.
    assert out_of_scope_clause.index(
        "acknowledgment"
    ) < out_of_scope_clause.lower().index("then redirect")
