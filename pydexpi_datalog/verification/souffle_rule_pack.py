from __future__ import annotations

from pathlib import Path

from ..semantics.derive_graph_semantics import build_graph_facts_datalog, load_graph_topology_idb
from ..semantics.souffle_runner import run_souffle_program
from .verify_suite import build_evaluation_diagnostic


RULE_DATALOG_PATH = Path(__file__).resolve().parent / "datalog" / "pump_discharge_check_valve.dl"

_MESSAGES = {
    "matched_required_component": (
        "Required downstream check valve was found before the first branch or "
        "terminal boundary."
    ),
    "off_page_connector": (
        "No downstream check valve was found before the discharge path "
        "terminated at an off-page connector."
    ),
    "terminal_object": (
        "No downstream check valve was found before the first terminal boundary."
    ),
}

_RESULT_TYPES = {
    "matched_required_component": "pass",
    "off_page_connector": "bounded_failure_off_page",
    "terminal_object": "hard_violation",
}


def load_rule_datalog() -> str:
    """Return the executed Souffle rule program text (inspectable logic)."""
    return RULE_DATALOG_PATH.read_text(encoding="utf-8")


def evaluate_pump_discharge_rule(
    graph_facts: dict[str, object], *, rule_id: str
) -> dict[str, object]:
    """Evaluate the pump discharge check-valve rule as a real Souffle program.

    Preserves the legacy result contract of
    ``verify_suite.evaluate_graph_fixture`` (result_type, message, subject,
    evidence shape), with the execution engine recorded in
    ``evidence.derived_graph_semantics.engine``.
    """
    if rule_id != "pump_discharge_check_valve":
        raise ValueError(f"unsupported souffle rule: {rule_id}")

    nodes = {node["node_id"]: node for node in graph_facts["facts"]["nodes"]}
    pump = next(
        node
        for node in graph_facts["facts"]["nodes"]
        if node["attributes"].get("label") == "CentrifugalPump"
    )
    pump_id = pump["node_id"]
    semantic_evidence = {
        "traversal_predicate": "downstream_reference",
        "reachability_predicate": "reachable",
        "engine": "souffle",
    }

    program = (
        build_graph_facts_datalog(graph_facts)
        + "\n"
        + load_graph_topology_idb()
        + "\n"
        + load_rule_datalog()
    )
    relations = run_souffle_program(program)

    unresolved = {row[0] for row in relations.get("rule_unresolved", [])}
    boundaries = [
        (int(step), object_id, kind)
        for walked_pump, step, object_id, kind in relations.get("walk_boundary", [])
        if walked_pump == pump_id
    ]
    if pump_id in unresolved or not boundaries:
        return build_evaluation_diagnostic(
            pump_id=pump_id, rule_id=rule_id, semantic_evidence=semantic_evidence
        )

    boundary_step, boundary_id, boundary_kind = min(boundaries)
    walk_steps = sorted(
        (int(step), object_id)
        for walked_pump, step, object_id in relations.get("walk", [])
        if walked_pump == pump_id and int(step) <= boundary_step
    )
    discharge_nozzle_id = walk_steps[0][1]
    traversed_objects = [
        {"object_id": object_id, "class": nodes[object_id]["attributes"]["label"]}
        for _, object_id in walk_steps
    ]
    traversed_edges = [
        {
            "source_id": walk_steps[index][1],
            "target_id": walk_steps[index + 1][1],
            "edge_key": 0,
        }
        for index in range(len(walk_steps) - 1)
    ]

    evidence: dict[str, object] = {
        "derived_graph_semantics": semantic_evidence,
        "traversed_objects": traversed_objects,
        "traversed_edges": traversed_edges,
        "matched_objects": (
            [
                {
                    "object_id": boundary_id,
                    "class": nodes[boundary_id]["attributes"]["label"],
                }
            ]
            if boundary_kind == "matched_required_component"
            else []
        ),
        "boundary": {"kind": boundary_kind, "object_id": boundary_id},
    }
    if boundary_kind == "off_page_connector":
        evidence["uncertainty_text"] = (
            "The discharge path may continue beyond the page edge."
        )

    return {
        "schema_version": 1,
        "result_type": _RESULT_TYPES[boundary_kind],
        "rule_id": rule_id,
        "message": _MESSAGES[boundary_kind],
        "subject": {
            "pump_id": pump_id,
            "discharge_nozzle_id": discharge_nozzle_id,
        },
        "evidence": evidence,
    }
