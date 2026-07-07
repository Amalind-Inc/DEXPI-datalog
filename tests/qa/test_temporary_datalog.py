from __future__ import annotations

from pydexpi_datalog.qa.topology_tools import TopologyTools


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

    assert result["status"] == "confirmation_required"
    assert result["executed"] is False
    assert result["validation"]["status"] == "rejected"
    assert result["validation"]["diagnostics"][0]["code"] == "temporary_datalog.filesystem_forbidden"


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
