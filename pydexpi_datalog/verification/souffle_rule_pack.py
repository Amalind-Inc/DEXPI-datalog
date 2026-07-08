from __future__ import annotations

from pathlib import Path

from ..semantics.derive_graph_semantics import build_graph_facts_datalog, load_graph_topology_idb
from ..semantics.souffle_runner import run_souffle_program
from .rule_pack_markdown import parse_rule_pack_markdown
from .verify_suite import build_evaluation_diagnostic


RULE_PACKS_DIR = Path(__file__).resolve().parent / "rule_packs"
DEMO_PACK_MARKDOWN_PATH = RULE_PACKS_DIR / "demo_process_safety.md"
DIAMETER_RULE_MIN_DN = 25

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
    return _demo_pack_rule_datalog("pump_discharge_check_valve")


def load_diameter_rule_datalog() -> str:
    """Return the executed diameter-rule Souffle program text (inspectable logic)."""
    return _demo_pack_rule_datalog("discharge_line_min_diameter")


def _demo_pack_rule_datalog(rule_id: str) -> str:
    """Extract a rule's fenced Souffle program from the canonical pack markdown."""
    pack = parse_rule_pack_markdown(DEMO_PACK_MARKDOWN_PATH.read_text(encoding="utf-8"))
    for rule in pack["rules"]:
        if rule["rule_id"] == rule_id:
            return str(rule["executable_logic"]["content"])
    raise ValueError(f"demo pack markdown declares no rule '{rule_id}'")


def evaluate_discharge_line_min_diameter_rule(
    graph_facts: dict[str, object], *, rule_id: str
) -> dict[str, object]:
    """Evaluate the numeric-threshold diameter rule as a real Souffle program.

    Compares the source-provided nominal diameter on the pump's discharge
    line (segment or its composing piping system) against a fixed DN
    threshold via the typed ``node_numeric_attribute`` predicate. A missing
    numeric diameter is an explicit ``source_data_unavailable`` outcome,
    never an invented value.
    """
    if rule_id != "discharge_line_min_diameter":
        raise ValueError(f"unsupported souffle rule: {rule_id}")

    nodes = {node["node_id"]: node for node in graph_facts["facts"]["nodes"]}
    pump = next(
        node
        for node in graph_facts["facts"]["nodes"]
        if node["attributes"].get("label") == "CentrifugalPump"
    )
    pump_id = pump["node_id"]
    semantic_evidence = {
        "numeric_predicate": "node_numeric_attribute",
        "engine": "souffle",
    }

    program = (
        build_graph_facts_datalog(graph_facts)
        + "\n"
        + load_graph_topology_idb()
        + "\n"
        + load_diameter_rule_datalog()
    )
    relations = run_souffle_program(program)

    unresolved = {row[0] for row in relations.get("rule_unresolved", [])}
    segments = [
        row[1] for row in relations.get("discharge_segment", []) if row[0] == pump_id
    ]
    if pump_id in unresolved or not segments:
        return build_evaluation_diagnostic(
            pump_id=pump_id, rule_id=rule_id, semantic_evidence=semantic_evidence
        )

    nozzle_rows = [
        row[1] for row in relations.get("discharge_nozzle", []) if row[0] == pump_id
    ]
    subject = {
        "pump_id": pump_id,
        "discharge_nozzle_id": nozzle_rows[0] if nozzle_rows else "unknown",
    }

    def _readings(relation: str) -> list[dict[str, object]]:
        return sorted(
            (
                {
                    "object_id": object_id,
                    "class": nodes[object_id]["attributes"]["label"],
                    "nominal_diameter_dn": int(dn),
                }
                for rule_pump, object_id, dn in relations.get(relation, [])
                if rule_pump == pump_id
            ),
            key=lambda item: str(item["object_id"]),
        )

    violated = _readings("diameter_violated")
    satisfied = _readings("diameter_satisfied")
    unavailable = pump_id in {
        row[0] for row in relations.get("diameter_unavailable", [])
    }

    evidence: dict[str, object] = {
        "derived_graph_semantics": semantic_evidence,
        "threshold": {
            "attr_name": "nominalDiameterNumericalValueRepresentation",
            "min_diameter_dn": DIAMETER_RULE_MIN_DN,
        },
        "diameter_readings": violated + satisfied,
        "matched_objects": violated or satisfied,
        "scope_completeness": {
            "complete": not unavailable,
            "basis": (
                "source_data_unavailable"
                if unavailable
                else "numeric_attribute_read"
            ),
            "boundary_kind": "numeric_attribute",
        },
    }

    if violated:
        worst = min(int(item["nominal_diameter_dn"]) for item in violated)
        return {
            "schema_version": 1,
            "result_type": "hard_violation",
            "rule_id": rule_id,
            "message": (
                f"The discharge line declares nominal diameter DN {worst}, below "
                f"the required minimum DN {DIAMETER_RULE_MIN_DN}."
            ),
            "subject": subject,
            "evidence": evidence,
        }
    if satisfied:
        best = max(int(item["nominal_diameter_dn"]) for item in satisfied)
        return {
            "schema_version": 1,
            "result_type": "pass",
            "rule_id": rule_id,
            "message": (
                f"The discharge line declares nominal diameter DN {best}, meeting "
                f"the required minimum DN {DIAMETER_RULE_MIN_DN}."
            ),
            "subject": subject,
            "evidence": evidence,
        }

    evidence["limitation"] = {
        "code": "source_data_unavailable",
        "message": (
            "No source-provided numeric nominal diameter exists on the "
            "discharge line; the source does not carry the data this "
            "threshold needs."
        ),
    }
    return {
        "schema_version": 1,
        "result_type": "source_data_unavailable",
        "rule_id": rule_id,
        "message": (
            "The discharge line carries no source-provided numeric nominal "
            f"diameter, so the DN {DIAMETER_RULE_MIN_DN} minimum cannot be "
            "evaluated from the loaded source."
        ),
        "subject": subject,
        "evidence": evidence,
    }


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
