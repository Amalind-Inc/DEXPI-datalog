from __future__ import annotations

from pathlib import Path

from ..semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
)
from ..semantics.souffle_runner import run_souffle_program
from .rule_pack_markdown import parse_rule_pack_markdown
from .verify_suite import build_evaluation_diagnostic

RULE_PACKS_DIR = Path(__file__).resolve().parent / "rule_packs"
DEMO_PACK_MARKDOWN_PATH = RULE_PACKS_DIR / "demo_process_safety.md"

# Fixed Souffle relation schema every executable fence must emit so one runner
# can interpret outcomes without a per-rule Python adapter.
RULE_RESULT = "rule_result"
RULE_MESSAGE = "rule_message"
RULE_SUBJECT_ATTR = "rule_subject_attr"
RULE_BOUNDARY = "rule_boundary"
RULE_MATCHED_OBJECT = "rule_matched_object"
RULE_WALK_OBJECT = "rule_walk_object"
RULE_WALK_EDGE = "rule_walk_edge"
RULE_NUMERIC_READING = "rule_numeric_reading"
RULE_THRESHOLD = "rule_threshold"
RULE_LIMITATION = "rule_limitation"
RULE_ENGINE_ATTR = "rule_engine_attr"
RULE_UNCERTAINTY = "rule_uncertainty"


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


def evaluate_rule_fence(
    graph_facts: dict[str, object],
    *,
    rule_id: str,
    fence: str,
) -> dict[str, object]:
    """Evaluate a Souffle fence that emits the rule outcome convention.

    The fence text is concatenated with the shared EDB/IDB and executed as-is
    (displayed == executed). Outcomes and evidence are assembled only from the
    fixed convention relations — no per-rule_id Python adapter is consulted.
    """
    program = (
        build_graph_facts_datalog(graph_facts)
        + "\n"
        + load_graph_topology_idb()
        + "\n"
        + fence
    )
    relations = run_souffle_program(program)
    return _result_from_convention(
        graph_facts,
        rule_id=rule_id,
        relations=relations,
    )


def evaluate_discharge_line_min_diameter_rule(
    graph_facts: dict[str, object], *, rule_id: str
) -> dict[str, object]:
    """Evaluate the diameter rule via the generic convention runner."""
    if rule_id != "discharge_line_min_diameter":
        raise ValueError(f"unsupported souffle rule: {rule_id}")
    return evaluate_rule_fence(
        graph_facts, rule_id=rule_id, fence=load_diameter_rule_datalog()
    )


def evaluate_pump_discharge_rule(
    graph_facts: dict[str, object], *, rule_id: str
) -> dict[str, object]:
    """Evaluate the pump discharge rule via the generic convention runner."""
    if rule_id != "pump_discharge_check_valve":
        raise ValueError(f"unsupported souffle rule: {rule_id}")
    return evaluate_rule_fence(
        graph_facts, rule_id=rule_id, fence=load_rule_datalog()
    )


def _result_from_convention(
    graph_facts: dict[str, object],
    *,
    rule_id: str,
    relations: dict[str, list[tuple[str, ...]]],
) -> dict[str, object]:
    nodes = {
        str(node["node_id"]): node
        for node in graph_facts["facts"]["nodes"]  # type: ignore[index]
    }
    results = list(relations.get(RULE_RESULT, []))
    if not results:
        # No convention rows — fall back to unresolved pump diagnostic when a
        # centrifugal pump exists (preserves prior demo behavior).
        pump = next(
            (
                node
                for node in graph_facts["facts"]["nodes"]  # type: ignore[index]
                if node["attributes"].get("label") == "CentrifugalPump"
            ),
            None,
        )
        if pump is None:
            raise ValueError("rule fence emitted no rule_result rows")
        return build_evaluation_diagnostic(
            pump_id=str(pump["node_id"]),
            rule_id=rule_id,
            semantic_evidence={"engine": "souffle"},
        )

    subject_id = _select_subject_id(graph_facts, results)
    result_type = next(
        str(row[1]) for row in results if str(row[0]) == subject_id
    )
    message = next(
        (
            str(row[1])
            for row in relations.get(RULE_MESSAGE, [])
            if str(row[0]) == subject_id
        ),
        "",
    )
    subject_attrs = {
        str(attr): str(value)
        for sid, attr, value in relations.get(RULE_SUBJECT_ATTR, [])
        if str(sid) == subject_id
    }
    subject = {
        "pump_id": subject_attrs.get("pump_id", subject_id),
        "discharge_nozzle_id": subject_attrs.get("discharge_nozzle_id", "unknown"),
    }

    engine_attrs = {
        str(key): str(value)
        for sid, key, value in relations.get(RULE_ENGINE_ATTR, [])
        if str(sid) == subject_id
    }
    if "engine" not in engine_attrs:
        engine_attrs["engine"] = "souffle"

    evidence: dict[str, object] = {
        "derived_graph_semantics": engine_attrs,
    }

    boundaries = [
        (str(kind), str(object_id))
        for sid, kind, object_id in relations.get(RULE_BOUNDARY, [])
        if str(sid) == subject_id
    ]
    if boundaries:
        kind, object_id = boundaries[0]
        evidence["boundary"] = {"kind": kind, "object_id": object_id}

    matched = [
        {
            "object_id": str(object_id),
            "class": str(klass)
            if klass
            else str(nodes.get(str(object_id), {}).get("attributes", {}).get("label", "")),
        }
        for sid, object_id, *rest in relations.get(RULE_MATCHED_OBJECT, [])
        if str(sid) == subject_id
        for klass in [rest[0] if rest else ""]
    ]
    evidence["matched_objects"] = matched

    walk_objects = sorted(
        (
            (int(step), str(object_id), str(klass) if klass else _node_class(nodes, object_id))
            for sid, step, object_id, *rest in relations.get(RULE_WALK_OBJECT, [])
            if str(sid) == subject_id
            for klass in [rest[0] if rest else ""]
        ),
        key=lambda item: item[0],
    )
    evidence["traversed_objects"] = [
        {"object_id": object_id, "class": klass}
        for _, object_id, klass in walk_objects
    ]

    walk_edges = [
        {
            "source_id": str(source_id),
            "target_id": str(target_id),
            "edge_key": 0,
        }
        for sid, source_id, target_id in relations.get(RULE_WALK_EDGE, [])
        if str(sid) == subject_id
    ]
    evidence["traversed_edges"] = walk_edges

    readings = sorted(
        (
            {
                "object_id": str(object_id),
                "class": str(klass)
                if klass
                else _node_class(nodes, object_id),
                "nominal_diameter_dn": int(float(value)),
            }
            for sid, object_id, klass, value in relations.get(RULE_NUMERIC_READING, [])
            if str(sid) == subject_id
        ),
        key=lambda item: str(item["object_id"]),
    )
    thresholds = [
        (str(attr_name), int(float(min_value)))
        for sid, attr_name, min_value in relations.get(RULE_THRESHOLD, [])
        if str(sid) == subject_id
    ]
    if thresholds or readings or result_type == "source_data_unavailable":
        evidence["diameter_readings"] = readings
        if readings:
            evidence["matched_objects"] = list(readings)

    if thresholds:
        attr_name, min_value = thresholds[0]
        evidence["threshold"] = {
            "attr_name": attr_name,
            "min_diameter_dn": min_value,
        }
        if readings and result_type == "hard_violation":
            worst = min(int(item["nominal_diameter_dn"]) for item in readings)
            message = (
                f"The discharge line declares nominal diameter DN {worst}, below "
                f"the required minimum DN {min_value}."
            )
        elif readings and result_type == "pass":
            best = max(int(item["nominal_diameter_dn"]) for item in readings)
            message = (
                f"The discharge line declares nominal diameter DN {best}, meeting "
                f"the required minimum DN {min_value}."
            )

    limitations = [
        (str(code), str(text))
        for sid, code, text in relations.get(RULE_LIMITATION, [])
        if str(sid) == subject_id
    ]
    if limitations:
        code, text = limitations[0]
        evidence["limitation"] = {"code": code, "message": text}

    uncertainties = [
        str(text)
        for sid, text in relations.get(RULE_UNCERTAINTY, [])
        if str(sid) == subject_id
    ]
    if uncertainties:
        evidence["uncertainty_text"] = uncertainties[0]

    if result_type == "source_data_unavailable":
        evidence["scope_completeness"] = {
            "complete": False,
            "basis": "source_data_unavailable",
            "boundary_kind": "numeric_attribute",
        }
        evidence["matched_objects"] = []
        evidence["diameter_readings"] = []
    elif thresholds or readings:
        evidence["scope_completeness"] = {
            "complete": True,
            "basis": "numeric_attribute_read",
            "boundary_kind": "numeric_attribute",
        }

    # Preserve diagnostic evidence shape for unresolved discharge nozzles.
    if result_type == "evaluation_diagnostic":
        diagnostic = build_evaluation_diagnostic(
            pump_id=str(subject["pump_id"]),
            rule_id=rule_id,
            semantic_evidence={str(k): str(v) for k, v in engine_attrs.items()},
        )
        diagnostic["message"] = message or diagnostic["message"]
        diagnostic["subject"] = subject
        # Keep fence-emitted boundary/engine attrs when present.
        diagnostic_evidence = dict(diagnostic["evidence"])
        diagnostic_evidence["derived_graph_semantics"] = engine_attrs
        if "boundary" in evidence:
            diagnostic_evidence["boundary"] = evidence["boundary"]
        diagnostic["evidence"] = diagnostic_evidence
        return diagnostic

    return {
        "schema_version": 1,
        "result_type": result_type,
        "rule_id": rule_id,
        "message": message,
        "subject": subject,
        "evidence": evidence,
    }


def _select_subject_id(
    graph_facts: dict[str, object],
    results: list[tuple[str, ...]],
) -> str:
    subject_ids = [str(row[0]) for row in results]
    pump_ids = {
        str(node["node_id"])
        for node in graph_facts["facts"]["nodes"]  # type: ignore[index]
        if node["attributes"].get("label") == "CentrifugalPump"
    }
    for subject_id in subject_ids:
        if subject_id in pump_ids:
            return subject_id
    return sorted(subject_ids)[0]


def _node_class(nodes: dict[str, object], object_id: object) -> str:
    node = nodes.get(str(object_id), {})
    if not isinstance(node, dict):
        return ""
    attributes = node.get("attributes", {})
    if not isinstance(attributes, dict):
        return ""
    return str(attributes.get("label", ""))
