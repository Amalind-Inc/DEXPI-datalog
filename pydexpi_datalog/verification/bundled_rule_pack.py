from __future__ import annotations

from copy import deepcopy

from .souffle_rule_pack import (
    DIAMETER_RULE_MIN_DN,
    evaluate_discharge_line_min_diameter_rule,
    evaluate_pump_discharge_rule,
    load_diameter_rule_datalog,
    load_rule_datalog,
)


_DEMO_PACK: dict[str, object] = {
    "pack_id": "demo-process-safety",
    "version": 1,
    "title": "Demo process-safety checks",
    "authoritative": False,
    "trust_notice": (
        "Demonstration content only; this pack is not an authoritative code, "
        "standard, compliance determination, or engineering approval."
    ),
    "rules": [
        {
            "rule_id": "pump_discharge_check_valve",
            "title": "Pump discharge check valve",
            "outcomes": ["satisfied", "violated", "indeterminate"],
            "restatement": {
                "kind": "engineer_readable_rule_restatement",
                "plain_language_meaning": (
                    "If a pump has a discharge nozzle, then a check valve must "
                    "be reachable downstream on that discharge path before the "
                    "scope boundary is reached."
                ),
            },
            "executable_logic": {
                "kind": "collapsed_executable_logic",
                "language": "souffle_datalog",
                "content": load_rule_datalog(),
                "inspectable": True,
                "editable": False,
                "disclosure": "collapsed",
            },
        },
        {
            "rule_id": "discharge_line_min_diameter",
            "title": "Discharge line minimum nominal diameter",
            "outcomes": ["satisfied", "violated", "indeterminate"],
            "restatement": {
                "kind": "engineer_readable_rule_restatement",
                "plain_language_meaning": (
                    "The piping line on a pump's discharge side must declare a "
                    f"nominal diameter of at least DN {DIAMETER_RULE_MIN_DN} in "
                    "the loaded source. The check compares only source-provided "
                    "values; if the source carries no numeric diameter for the "
                    "line, the outcome is indeterminate (source data "
                    "unavailable), never an assumed value."
                ),
            },
            "executable_logic": {
                "kind": "collapsed_executable_logic",
                "language": "souffle_datalog",
                "content": load_diameter_rule_datalog(),
                "inspectable": True,
                "editable": False,
                "disclosure": "collapsed",
            },
        },
    ],
}


def bundled_rule_packs() -> list[dict[str, object]]:
    """Return provider-independent metadata for repository-bundled rule packs."""
    return [deepcopy(_DEMO_PACK)]


def pack_metadata(pack_id: str) -> dict[str, object]:
    """Return metadata for a single bundled rule pack by id."""
    return _pack(pack_id)


def evaluate_bundled_rule(
    graph_facts: dict[str, object],
    *,
    pack_id: str,
    rule_id: str,
    direction_basis: str = "explicit",
    direction_review_status: str | None = None,
) -> dict[str, object]:
    pack = _pack(pack_id)
    if rule_id not in {str(rule["rule_id"]) for rule in pack["rules"]}:
        raise ValueError(f"unknown bundled rule: {pack_id}/{rule_id}")

    evaluator = {
        "pump_discharge_check_valve": evaluate_pump_discharge_rule,
        "discharge_line_min_diameter": evaluate_discharge_line_min_diameter_rule,
    }[rule_id]
    legacy = evaluator(graph_facts, rule_id=rule_id)
    outcome = {
        "pass": "satisfied",
        "hard_violation": "violated",
        "bounded_failure_off_page": "indeterminate",
        "evaluation_diagnostic": "indeterminate",
        "source_data_unavailable": "indeterminate",
    }.get(str(legacy["result_type"]), "indeterminate")
    evidence = deepcopy(legacy["evidence"])
    if "scope_completeness" not in evidence:
        boundary = evidence.get("boundary", {})
        boundary_kind = str(boundary.get("kind", "unknown"))
        complete = boundary_kind in {"matched_required_component", "terminal_object"}
        evidence["scope_completeness"] = {
            "complete": complete,
            "basis": (
                "terminal_boundary_reached"
                if boundary_kind == "terminal_object"
                else "required_component_matched"
                if boundary_kind == "matched_required_component"
                else "evaluation_boundary_incomplete"
            ),
            "boundary_kind": boundary_kind,
        }

    formal_direction_allowed = direction_basis == "explicit" or (
        direction_basis == "inferred"
        and direction_review_status in {"confirmed", "reversed"}
    )
    evidence["direction"] = {
        "basis": direction_basis,
        "review_status": direction_review_status,
        "formal_use_allowed": formal_direction_allowed,
    }
    if not formal_direction_allowed:
        outcome = "indeterminate"
        evidence["limitation"] = {
            "code": "direction.review_required",
            "message": (
                "The discharge direction is inferred and must be reviewed before "
                "it can establish a formal rule outcome."
            ),
        }
    return {
        "schema_version": 1,
        "pack": {
            "pack_id": pack["pack_id"],
            "version": pack["version"],
            "authoritative": pack["authoritative"],
            "trust_notice": pack["trust_notice"],
        },
        "rule_id": rule_id,
        "outcome": outcome,
        "message": legacy["message"],
        "subject": legacy["subject"],
        "evidence": evidence,
        "legacy_result_type": legacy["result_type"],
    }


def _pack(pack_id: str) -> dict[str, object]:
    for pack in bundled_rule_packs():
        if pack["pack_id"] == pack_id:
            return pack
    raise ValueError(f"unknown bundled rule pack: {pack_id}")
