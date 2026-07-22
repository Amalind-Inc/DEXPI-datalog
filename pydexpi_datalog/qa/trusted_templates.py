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
    "source_classes",
    "target_classes",
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
        request=request,
        template_id=template_id,
        bindings=bindings,
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
    *, request: str, template_id: str, bindings: object
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
        return {"status": "rejected", "diagnostics": diagnostics}

    keys = {str(key) for key in bindings}
    if keys != _REQUIRED_BINDINGS:
        diagnostics.append(
            {
                "code": "trusted_template.binding_shape",
                "message": "Template bindings must contain exactly the supported semantic fields.",
            }
        )
    _require_class_binding(bindings, "source_classes", _PUMP_CLASSES, diagnostics)
    _require_class_binding(bindings, "target_classes", _EQUIPMENT_CLASSES, diagnostics)
    _require_binding(bindings, "scope", "piping", diagnostics)
    _require_binding(bindings, "direction", "undirected", diagnostics)
    _require_binding(bindings, "quantifier", "every", diagnostics)
    _require_binding(bindings, "negated", True, diagnostics)

    normalized = " ".join(request.lower().split())
    for class_name in (*_PUMP_CLASSES, *_EQUIPMENT_CLASSES):
        if class_name.lower() not in normalized:
            diagnostics.append(
                {
                    "code": "trusted_template.explicit_class_omitted",
                    "message": f"The request does not explicitly include {class_name}.",
                }
            )
    semantic_cues = {
        "scope": "piping path",
        "direction": "in either direction",
        "quantifier": "every",
        "negation": " no piping path",
    }
    for obligation, cue in semantic_cues.items():
        if cue not in f" {normalized}":
            diagnostics.append(
                {
                    "code": f"trusted_template.{obligation}_not_explicit",
                    "message": f"The request does not explicitly establish {obligation}={bindings.get(obligation)}.",
                }
            )

    return {
        "status": "rejected" if diagnostics else "accepted",
        "diagnostics": diagnostics,
    }


def _require_class_binding(
    bindings: Mapping[object, object],
    name: str,
    expected: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> None:
    value = bindings.get(name)
    valid = (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and set(value) == set(expected)
    )
    if not valid:
        diagnostics.append(
            {
                "code": f"trusted_template.{name}_mismatch",
                "message": f"Binding {name} must exactly preserve the requested class set and role.",
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
        ".decl template_source(id:symbol)",
    ]
    lines.extend(
        f"template_source(N) :- node_label(N, {souffle_symbol(class_name)})."
        for class_name in bindings["source_classes"]
    )
    lines.append(".decl template_target(id:symbol)")
    lines.extend(
        f"template_target(N) :- node_label(N, {souffle_symbol(class_name)})."
        for class_name in bindings["target_classes"]
    )
    lines.extend(
        [
            ".decl template_hit(id:symbol)",
            "template_hit(T) :- template_target(T), template_source(S), piping_connected(S, T).",
            ".decl result_witness(id:symbol)",
            ".output result_witness",
            "result_witness(T) :- template_target(T), !template_hit(T).",
        ]
    )
    return "\n".join(lines) + "\n"
