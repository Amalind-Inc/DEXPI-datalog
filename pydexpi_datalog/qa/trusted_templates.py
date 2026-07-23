"""Versioned, backend-validated query templates for grounded P&ID QA.

These templates are product logic. They deliberately do not import the benchmark
Arm T implementation: benchmark routes remain evaluation evidence rather than a
production dependency.
"""

from __future__ import annotations

from typing import Mapping

from pydexpi_datalog.semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
    souffle_symbol,
)
from pydexpi_datalog.semantics.souffle_runner import (
    SouffleExecutionError,
    run_souffle_program,
)


TRUSTED_TEMPLATE_CATALOG_VERSION = "1.0.0"
EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_ID = "equipment_without_pump_path"
EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_VERSION = "1.0.0"

_PUMP_CLASSES = ("CentrifugalPump", "ReciprocatingPump")
_EQUIPMENT_CLASSES = (
    "PlateHeatExchanger",
    "TubularHeatExchanger",
    "Tank",
    "ProcessColumn",
)
_REQUIRED_BINDINGS = {
    "equipment_classes",
    "pump_classes",
    "scope",
    "direction",
    "quantifier",
    "negated",
}


def execute_bundled_query_template(
    *,
    request: str,
    template_id: str,
    bindings: object,
    graph_facts: dict[str, object],
) -> dict[str, object]:
    """Validate and execute one supported bundled template through real Souffle."""
    proposed_event = {
        "event": "template_proposed",
        "template_id": template_id,
    }
    validation = _validate_equipment_without_pump_path(
        template_id=template_id,
        bindings=bindings,
        graph_facts=graph_facts,
    )
    validated_event = {
        "event": "template_validated",
        "template_id": template_id,
        "outcome": validation["status"],
    }
    trace_events = [proposed_event, validated_event]
    if validation["status"] != "accepted":
        return {
            "status": "rejected",
            "executed": False,
            "template_id": template_id,
            "template_version": EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_VERSION,
            "bindings": dict(bindings) if isinstance(bindings, Mapping) else {},
            "validation": validation,
            "trace_events": trace_events,
            "confirmation": {"required": False},
            "generated_datalog": {"requested": False},
        }

    validated_bindings = dict(bindings)
    route_artifact = {
        "route": "bundled_template",
        "template_id": template_id,
        "template_version": EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_VERSION,
        "bindings": validated_bindings,
        "validation": validation,
    }
    try:
        relations = run_souffle_program(
            _render_equipment_without_pump_path(graph_facts, validated_bindings)
        )
    except SouffleExecutionError as error:
        diagnostic: dict[str, object] = {
            "code": f"trusted_template.{error.code}",
            "message": str(error),
        }
        if error.detail:
            diagnostic["detail"] = error.detail
        trace_events.append(
            {
                "event": "template_execution_failed",
                "template_id": template_id,
                "engine": "souffle",
            }
        )
        return {
            "status": "execution_failed",
            "executed": False,
            "route_artifact": route_artifact,
            "diagnostics": [diagnostic],
            "trace_events": trace_events,
            "confirmation": {"required": False},
            "generated_datalog": {"requested": False},
        }

    witness_ids = sorted({row[0] for row in relations.get("result_witness", [])})
    verdict = "violation_found" if witness_ids else "no_violation"
    trace_events.extend(
        [
            {
                "event": "template_executed",
                "template_id": template_id,
                "template_version": EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_VERSION,
                "engine": "souffle",
            },
            {
                "event": "result_observed",
                "verdict": verdict,
                "witness_count": len(witness_ids),
            },
        ]
    )
    return {
        "status": "answered",
        "executed": True,
        "verdict": verdict,
        "witnesses": witness_ids,
        "route_artifact": route_artifact,
        "trace_events": trace_events,
        "confirmation": {"required": False},
        "generated_datalog": {"requested": False},
        "diagnostics": [],
    }


def _validate_equipment_without_pump_path(
    *, template_id: str, bindings: object, graph_facts: dict[str, object]
) -> dict[str, object]:
    diagnostics: list[dict[str, str]] = []
    if template_id != EQUIPMENT_WITHOUT_PUMP_PATH_TEMPLATE_ID:
        diagnostics.append(
            {
                "code": "trusted_template.unsupported_template",
                "message": f"Unsupported bundled query template: {template_id}",
            }
        )
    if not isinstance(bindings, Mapping):
        diagnostics.append(
            {
                "code": "trusted_template.bindings_type",
                "message": "Template bindings must be an object.",
            }
        )
        return {
            "status": "rejected",
            "diagnostics": diagnostics,
            "absent_classes": [],
        }

    keys = {str(key) for key in bindings}
    if keys != _REQUIRED_BINDINGS:
        diagnostics.append(
            {
                "code": "trusted_template.binding_shape",
                "message": "Template bindings must contain exactly the supported semantic fields.",
            }
        )
    _require_class_subset(
        bindings, "equipment_classes", _EQUIPMENT_CLASSES, diagnostics
    )
    _require_class_subset(bindings, "pump_classes", _PUMP_CLASSES, diagnostics)
    _require_binding(bindings, "scope", "piping", diagnostics)
    _require_binding(bindings, "direction", "undirected", diagnostics)
    _require_binding(bindings, "quantifier", "every", diagnostics)
    _require_binding(bindings, "negated", True, diagnostics)

    bound_classes: list[str] = []
    for name in ("equipment_classes", "pump_classes"):
        value = bindings.get(name)
        if isinstance(value, list):
            bound_classes.extend(str(item) for item in value)
    present_labels = _graph_node_labels(graph_facts)
    return {
        "status": "rejected" if diagnostics else "accepted",
        "diagnostics": diagnostics,
        # Graph-grounded disclosure (bead 3qo.9.11): bound classes with no
        # instance in the loaded source are legitimate (the quantified check
        # is vacuously satisfied for them) but must be visible to reviewers.
        "absent_classes": sorted(
            item for item in set(bound_classes) if item not in present_labels
        ),
    }


def _graph_node_labels(graph_facts: dict[str, object]) -> set[str]:
    labels: set[str] = set()
    facts = graph_facts.get("facts")
    if not isinstance(facts, dict):
        return labels
    nodes = facts.get("nodes")
    if not isinstance(nodes, list):
        return labels
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attributes = node.get("attributes")
        if isinstance(attributes, dict):
            label = attributes.get("label")
            if isinstance(label, str) and label:
                labels.add(label)
    return labels


def _require_class_subset(
    bindings: Mapping[object, object],
    name: str,
    catalog: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> None:
    """Accept any non-empty, duplicate-free subset of the supported class
    catalog -- the model narrows scope to what the question actually asks
    about instead of being forced to enumerate the entire static catalog."""
    value = bindings.get(name)
    if not (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    ):
        diagnostics.append(
            {
                "code": f"trusted_template.{name}_shape",
                "message": f"Binding {name} must be a non-empty list of distinct class names.",
            }
        )
        return
    unsupported = sorted(item for item in value if item not in catalog)
    if unsupported:
        diagnostics.append(
            {
                "code": f"trusted_template.{name}_unsupported",
                "message": (
                    f"Binding {name} includes classes outside the supported "
                    f"catalog: {unsupported}."
                ),
            }
        )


def _require_binding(
    bindings: Mapping[object, object],
    name: str,
    expected: object,
    diagnostics: list[dict[str, str]],
) -> None:
    if bindings.get(name) != expected:
        diagnostics.append(
            {
                "code": f"trusted_template.{name}_mismatch",
                "message": f"Binding {name} must exactly preserve the supported request semantics.",
            }
        )


def _render_equipment_without_pump_path(
    graph_facts: dict[str, object], bindings: dict[str, object]
) -> str:
    lines = [
        build_graph_facts_datalog(graph_facts),
        load_graph_topology_idb(),
        ".decl template_pump(id:symbol)",
    ]
    lines.extend(
        f"template_pump(N) :- node_label(N, {souffle_symbol(class_name)})."
        for class_name in bindings["pump_classes"]
    )
    lines.append(".decl template_equipment(id:symbol)")
    lines.extend(
        f"template_equipment(N) :- node_label(N, {souffle_symbol(class_name)})."
        for class_name in bindings["equipment_classes"]
    )
    lines.extend(
        [
            ".decl template_hit(id:symbol)",
            "template_hit(T) :- template_equipment(T), template_pump(S), piping_connected(S, T).",
            ".decl result_witness(id:symbol)",
            ".output result_witness",
            "result_witness(T) :- template_equipment(T), !template_hit(T).",
        ]
    )
    return "\n".join(lines) + "\n"
