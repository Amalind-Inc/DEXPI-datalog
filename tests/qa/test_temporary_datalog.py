from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pydexpi_datalog.qa.structured_intent import encode_structured_intent_program
from pydexpi_datalog.qa.topology_tools import TopologyTools as ProductTopologyTools

STRUCTURED_INTENT = {
    "source_classes": ["TopologyObject"],
    "target_classes": ["TopologyObject"],
    "source_role": "resolved_source",
    "target_role": "answer_object",
    "graph_scope": "all_topology",
    "direction": "directed",
    "quantifier": "any",
    "negated": False,
    "output_obligations": ["answer_ids"],
}


class TopologyTools(ProductTopologyTools):
    """Authorize the route so these legacy tests stay focused on proposal mechanics."""

    def execute(
        self, tool_name: str, tool_input: dict[str, object]
    ) -> dict[str, object]:
        tool_input = dict(tool_input)
        if tool_name == "report_template_no_fit":
            tool_input.setdefault("structured_intent", STRUCTURED_INTENT)
        if tool_name == "propose_temporary_datalog":
            tool_input.setdefault(
                "faithfulness_review",
                {
                    "status": "faithful",
                    "back_translated_intent": STRUCTURED_INTENT,
                    "diagnostics": [],
                },
            )
            request = str(tool_input.get("request", ""))
            self.begin_request(request)
            super().execute(
                "report_template_no_fit",
                {
                    "reason": "No bundled template covers this mechanics test.",
                    "structured_intent": STRUCTURED_INTENT,
                },
            )
            generated_datalog = str(tool_input.get("generated_datalog", ""))
            if "answer(" in generated_datalog:
                tool_input["generated_datalog"] = encode_structured_intent_program(
                    generated_datalog,
                    STRUCTURED_INTENT,
                )
        return super().execute(tool_name, tool_input)


REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)
requires_souffle = pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)


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


@requires_souffle
def test_propose_temporary_datalog_executes_automatically() -> None:
    """
    Behavior: a validated temporary query executes automatically and discloses
    the exact query/restatement pair without creating confirmation state.
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

    assert result["status"] == "answered"
    assert result["executed"] is True
    assert result["execution_mode"] == "automatic"
    assert result["confirmation"] == {"required": False}
    assert result["disclosure"]["inspectable_datalog"][
        "generated_datalog"
    ] == encode_structured_intent_program(
        '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
        STRUCTURED_INTENT,
    )
    assert (
        result["disclosure"]["restatement"]
        == "Return the pump as the temporary check result."
    )
    assert result["validation"]["status"] == "safe_to_confirm"


@requires_souffle
def test_propose_temporary_datalog_discloses_interpretation_scope_and_effect() -> None:
    """
    Behavior: automatic execution discloses its interpretation, scope, exact
    Datalog, and read-only route.
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

    disclosure = result["disclosure"]
    assert disclosure["restatement"] == (
        "Return the pump as the temporary check result."
    )
    assert "answer(" in disclosure["inspectable_datalog"]["generated_datalog"]
    scope = disclosure["source_scope"]
    assert scope["starting_object_ids"] == ["node-pump-p101"]
    assert scope["graph"]
    assert scope["direction"]
    assert scope["direction_basis"]
    assert scope["path_treatment"]
    assert disclosure["route"] == "generated_temporary_datalog"
    assert disclosure["effect"] == (
        "Read-only analysis. Does not modify the source document, graph, "
        "annotations, or rule pack."
    )


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
    assert (
        result["validation"]["diagnostics"][0]["code"]
        == "temporary_datalog.filesystem_forbidden"
    )
    assert "Authoring contract" in result["message"]


@requires_souffle
def test_propose_temporary_datalog_returns_witnessed_answer() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects violate the temporary check?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer("node-pump-p101").',
            "formal_restatement": "Return the pump as the temporary check result.",
            "resolved_identity_ids": ["node-pump-p101"],
        },
    )

    assert answer["status"] == "answered"
    assert answer["executed"] is True
    assert answer["confirmation"] == {"required": False}
    assert answer["summary"]["text"] == "Return the pump as the temporary check result."
    assert answer["evidence"]["items"] == [
        {
            "id": "node-pump-p101",
            "label": "P-101",
            "source": "temporary_datalog",
            "topology_evidence": {"id": "node-pump-p101"},
        }
    ]

def test_propose_temporary_datalog_rejects_unapproved_rule_predicates() -> None:
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")

    result = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use an unapproved predicate",
            "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(x) :- evil_pred(x).",
            "formal_restatement": "Return evil matches.",
        },
    )

    assert result["validation"]["status"] == "rejected"
    assert (
        result["validation"]["diagnostics"][0]["code"]
        == "temporary_datalog.predicate_not_approved"
    )


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
    assert (
        result["validation"]["diagnostics"][0]["code"]
        == "temporary_datalog.syntax_invalid"
    )


@requires_souffle
def test_propose_temporary_datalog_executes_shapes_beyond_the_legacy_two() -> (
    None
):
    """
    Behavior: a confirmed query built only from approved predicates executes for
    real even when it is not one of the two historical text shapes. The reversed
    reachable argument order used to silently return zero evidence.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "What can reach the valve?",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable(x, "node-valve-v102").',
            "formal_restatement": "Return objects that can reach the valve.",
        },
    )

    assert answer["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == ["node-pump-p101"]


@requires_souffle
def test_propose_temporary_datalog_fails_loudly_on_engine_errors() -> None:
    """
    Behavior: a query that passes static validation but cannot execute (wrong
    reachable arity) surfaces an explicit execution error instead of silently
    answering with zero evidence.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Use reachable with the wrong arity",
            "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable(x).",
            "formal_restatement": "Return reachable objects.",
        },
    )

    assert answer["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "execution_failed"
    assert answer["executed"] is False
    assert answer["diagnostics"], "engine failure must carry diagnostics"
    assert (
        answer["diagnostics"][0]["code"] == "temporary_datalog.souffle_execution_failed"
    )


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
    tools.begin_request("Describe the generated Datalog contract.")
    tools.execute(
        "report_template_no_fit",
        {"reason": "No bundled template covers this contract inspection."},
    )

    generated_datalog_description = next(
        tool["function"]["parameters"]["properties"]["generated_datalog"]["description"]
        for tool in tools.tool_definitions()
        if tool["function"]["name"] == "propose_temporary_datalog"
    )

    assert "`direct_process_connection`" in generated_datalog_description
    assert "`node_numeric_attribute`" in generated_datalog_description
    assert "`diameter_satisfied`" not in generated_datalog_description


@requires_souffle
def test_propose_temporary_datalog_joins_against_generic_schema_predicate() -> (
    None
):
    tools = _tools_for_e06()
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which objects are direct process targets?",
            "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(x) :- direct_process_connection(_, x).",
            "formal_restatement": "Return objects that are direct process-connection targets.",
        },
    )

    assert answer["validation"]["status"] == "safe_to_confirm"
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
            "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(x) :- diameter_satisfied(_, x, _).",
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


@requires_souffle
def test_propose_temporary_datalog_joins_against_loaded_rule_pack_idb() -> (
    None
):
    tools = _tools_for_e06(loaded_rule_pack_ids=["demo-process-safety"])
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Which discharge lines satisfy the diameter rule?",
            "generated_datalog": ".decl answer(x:symbol)\n.output answer\nanswer(x) :- diameter_satisfied(_, x, _).",
            "formal_restatement": "Return discharge line objects that satisfy the diameter rule.",
        },
    )

    assert answer["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == [
        "152b44e1-3763-4f6f-bb0e-ef69897c2c61"
    ]


@requires_souffle
def test_propose_temporary_datalog_evaluates_approved_reachable_rule() -> (
    None
):
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    answer = tools.execute(
        "propose_temporary_datalog",
        {
            "request": "Return reachable objects",
            "generated_datalog": '.decl answer(x:symbol)\n.output answer\nanswer(x) :- reachable("node-pump-p101", x).',
            "formal_restatement": "Return objects reachable from the pump.",
        },
    )

    assert answer["validation"]["status"] == "safe_to_confirm"
    assert answer["status"] == "answered"
    assert [item["id"] for item in answer["evidence"]["items"]] == ["node-valve-v102"]


@requires_souffle
def test_temporary_datalog_allows_program_defined_helper_predicates() -> None:
    """
    Behavior (bead 3cq): 'Do all pumps have a check valve?' style questions
    need intermediate predicates (pump, pump_with_check_valve) defined inside
    the temporary program. Predicates the program itself defines are not
    "unapproved" -- only reading a relation that is neither engine-supplied
    nor locally defined is. The confirmed program must execute for real.
    """
    tools = TopologyTools(topology_view=TOPOLOGY, session_id="s")
    answer = tools.execute(
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

    assert answer["validation"]["status"] == "safe_to_confirm"
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
