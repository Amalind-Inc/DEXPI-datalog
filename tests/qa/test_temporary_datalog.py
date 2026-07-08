from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.qa.topology_tools import TopologyTools


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"


TOPOLOGY = {
    "nodes": [
        {"id": "node-pump-p101", "label": "Pump", "tag_name": "P-101"},
        {"id": "node-valve-v102", "label": "Valve", "tag_name": "V-102"},
    ],
    "edges": [
        {
            "id": "edge-pump-valve",
            "source_id": "node-pump-p101",
            "target_id": "node-valve-v102",
            "relationship": "connected_to",
        }
    ],
    "evidence_map": {
        "node-pump-p101": {"id": "node-pump-p101"},
        "node-valve-v102": {"id": "node-valve-v102"},
        "edge-pump-valve": {"id": "edge-pump-valve"},
    },
}


def test_propose_temporary_datalog_returns_confirmation_without_execution() -> None:
    """
    Behavior: the native Datalog escalation capability returns an exact temporary
    query/restatement pair for user confirmation and does not execute it.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects violate the temporary check?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump as the temporary check result.",
            "resolved_identity_ids": ["node-pump-p101"],
        },
    )

    assert result["status"] == "confirmation_required"
    assert result["executed"] is False
    assert result["proposal"]["generated_datalog"] == '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").'
    assert result["proposal"]["formal_restatement"] == "Return the pump as the temporary check result."
    assert result["validation"]["status"] == "safe_to_confirm"
    assert result["confirmation"]["required"] is True


def test_propose_temporary_datalog_describes_interpretation_scope_and_effect() -> None:
    """
    Behavior: a proposal carries everything a reviewer needs for meaningful
    consent — interpretation, scope, traversal assumptions, exact Datalog, and
    a hardcoded read-only effect statement.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects violate the temporary check?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump as the temporary check result.",
            "resolved_identity_ids": ["node-pump-p101"],
        },
    )

    proposal = result["proposal"]
    assert proposal["interpretation"] == "Return the pump as the temporary check result."
    assert proposal["exact_datalog"] == proposal["generated_datalog"]
    assert (
        proposal["effect"]
        == "Read-only analysis. Does not modify the P&ID, graph, annotations, or rule pack."
    )

    scope = proposal["scope"]
    assert scope["starting_object_ids"] == ["node-pump-p101"]
    assert scope["graph"]
    assert scope["direction"]
    assert scope["direction_basis"]
    assert scope["path_treatment"]

    assumptions = proposal["assumptions"]
    assert assumptions["included_edge_types"]
    assert assumptions["excluded_edge_types"]
    assert all(isinstance(item, str) for item in assumptions["included_edge_types"])
    assert all(isinstance(item, str) for item in assumptions["excluded_edge_types"])


def test_propose_temporary_datalog_rejects_filesystem_directives() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use an include",
            "generated_datalog": '.include "/tmp/evil.dl"\n.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump.",
        },
    )

    # Invalid proposals never pause for confirmation (bead 3cq follow-up):
    # the rejection returns to the model as a retryable tool result.
    assert result["status"] == "rejected"
    assert result["code"] == "tool.proposal_rejected"
    assert result["executed"] is False
    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"][0]["code"] == "temporary_datalog.filesystem_forbidden"
    assert "Authoring contract" in result["message"]


def test_execute_confirmed_temporary_datalog_returns_witnessed_answer() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects violate the temporary check?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump as the temporary check result.",
            "resolved_identity_ids": ["node-pump-p101"],
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert answer["status"] == "answered"
    assert answer["executed"] is True
    assert answer["confirmation"]["proposal_id"] == proposal["proposal"]["proposal_id"]
    assert answer["summary"]["text"] == "Return the pump as the temporary check result."
    assert answer["evidence"]["items"] == [
        {
            "id": "node-pump-p101",
            "label": "P-101",
            "source": "temporary_datalog",
            "topology_evidence": {"id": "node-pump-p101"},
        }
    ]


def test_execute_confirmed_temporary_datalog_rejects_tampered_pair() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects violate the temporary check?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump as the temporary check result.",
        },
    )
    proposal["proposal"]["generated_datalog"] = (
        '.decl answer(x:symbol)\n.output answer\nanswer("node-valve-v102").'
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert answer["status"] == "execution_failed"
    assert answer["executed"] is False
    assert answer["diagnostics"] == [
        {
            "code": "temporary_datalog.confirmation_mismatch",
            "message": "Temporary Datalog execution requires the exact confirmed query/restatement pair.",
        }
    ]


def test_propose_temporary_datalog_rejects_unapproved_rule_predicates() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use an unapproved predicate",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- evil_pred(x).',
            "formal_restatement": "Return evil matches.",
        },
    )

    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"][0]["code"] == "temporary_datalog.predicate_not_approved"


def test_propose_temporary_datalog_rejects_basic_syntax_errors() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use malformed syntax",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101"',
            "formal_restatement": "Return the pump.",
        },
    )

    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"][0]["code"] == "temporary_datalog.syntax_invalid"


def test_execute_confirmed_temporary_datalog_executes_shapes_beyond_the_legacy_two() -> None:
    """
    Behavior: a confirmed query built only from approved predicates executes for
    real even when it is not one of the two historical text shapes. The reversed
    reachable argument order used to silently return zero evidence.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "What can reach the valve?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable(x, "node-valve-v102").',
            "formal_restatement": "Return objects that can reach the valve.",
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == ["node-pump-p101"]


def test_execute_confirmed_temporary_datalog_fails_loudly_on_engine_errors() -> None:
    """
    Behavior: a query that passes static validation but cannot execute (wrong
    reachable arity) surfaces an explicit execution error instead of silently
    answering with zero evidence.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use reachable with the wrong arity",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable(x).',
            "formal_restatement": "Return reachable objects.",
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "execution_failed"
    assert answer["executed"] is False
    assert answer["diagnostics"], "engine failure must carry diagnostics"
    assert answer["diagnostics"][0]["code"] == "temporary_datalog.souffle_execution_failed"


def _tools_for_e06(*, loaded_rule_pack_ids: list[str] | None = None) -> TopologyTools:
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
        session_id="e06-session",
        loaded_rule_pack_ids=loaded_rule_pack_ids,
    )


def test_temporary_datalog_contract_mentions_generic_schema_predicates() -> None:
    tools = _tools_for_e06()

    generated_datalog_description = next(
        tool["function"]["parameters"]["properties"]["generated_datalog"]["description"]
        for tool in tools.tool_definitions()
        if tool["function"]["name"] == "propose_temporary_datalog"
    )

    assert "`direct_process_connection`" in generated_datalog_description
    assert "`node_numeric_attribute`" in generated_datalog_description
    assert "`diameter_satisfied`" not in generated_datalog_description


def test_execute_confirmed_temporary_datalog_joins_against_generic_schema_predicate() -> None:
    tools = _tools_for_e06()
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects are direct process targets?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- direct_process_connection(_, x).',
            "formal_restatement": "Return objects that are direct process-connection targets.",
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert {item["id"] for item in answer["evidence"]["items"]} == {
        "57c776dc-fc90-4276-bb53-f0bbdd01bb83",
        "2accb8cf-7c3d-4563-8c22-5d817f464bd5",
    }


def test_temporary_datalog_rejects_predicate_from_unloaded_rule_pack() -> None:
    tools = _tools_for_e06()

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which discharge lines satisfy the diameter rule?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- diameter_satisfied(_, x, _).',
            "formal_restatement": "Return discharge line objects that satisfy the diameter rule.",
        },
    )

    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"] == [
        {
            "code": "temporary_datalog.predicate_not_approved",
            "message": "Temporary Datalog used unapproved predicate(s): diameter_satisfied",
        }
    ]


def test_execute_confirmed_temporary_datalog_joins_against_loaded_rule_pack_idb() -> None:
    tools = _tools_for_e06(loaded_rule_pack_ids=["demo-process-safety"])
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which discharge lines satisfy the diameter rule?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- diameter_satisfied(_, x, _).',
            "formal_restatement": "Return discharge line objects that satisfy the diameter rule.",
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == [
        "152b44e1-3763-4f6f-bb0e-ef69897c2c61"
    ]


def test_execute_confirmed_temporary_datalog_evaluates_approved_reachable_rule() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Return reachable objects",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable("node-pump-p101", x).',
            "formal_restatement": "Return objects reachable from the pump.",
        },
    )

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert proposal["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == ["node-valve-v102"]


def test_temporary_datalog_allows_program_defined_helper_predicates() -> None:
    """
    Behavior (bead 3cq): 'Do all pumps have a check valve?' style questions
    need intermediate predicates (pump, pump_with_check_valve) defined inside
    the temporary program. Predicates the program itself defines are not
    "unapproved" -- only reading a relation that is neither engine-supplied
    nor locally defined is. The confirmed program must execute for real.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    proposal = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which pumps have a check valve?",
            "generated_datalog": (
                ".decl answer(x:symbol)\n"
                ".decl pump(x:symbol)\n"
                ".decl pump_with_check_valve(x:symbol)\n"
                ".output answer\n"
                'pump(x) :- node_attribute(x, "label", "Pump").\n'
                "pump_with_check_valve(x) :- pump(x), reachable(x, v), "
                'node_attribute(v, "label", "Valve").\n'
                "answer(x) :- pump_with_check_valve(x).\n"
            ),
            "formal_restatement": "Return pumps with a reachable check valve.",
        },
    )

    assert proposal["validation"]["status"] == "safe_to_confirm"

    answer = tools.execute_confirmed_temporary_datalog(proposal)

    assert answer["status"] == "answered"
    assert answer["executed"] is True
    assert [item["id"] for item in answer["evidence"]["items"]] == ["node-pump-p101"]


def test_temporary_datalog_still_rejects_read_of_undefined_predicate() -> None:
    """
    Guard for the helper-predicate allowance: a body atom that is neither
    engine-supplied nor defined by the program stays rejected, including a
    misspelled reference to the program's own helper.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Misspell the helper",
            "generated_datalog": (
                ".decl answer(x:symbol)\n"
                ".decl pump(x:symbol)\n"
                ".output answer\n"
                'pump(x) :- node_attribute(x, "label", "Pump").\n'
                "answer(x) :- pumps(x).\n"
            ),
            "formal_restatement": "Return pumps.",
        },
    )

    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"][0]["code"] == (
        "temporary_datalog.predicate_not_approved"
    )
    assert "pumps" in result["validation"]["diagnostics"][0]["message"]
