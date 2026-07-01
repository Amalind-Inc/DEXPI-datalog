from __future__ import annotations

from copy import deepcopy

from .verify_suite import evaluate_graph_fixture


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
        }
    ],
}


def bundled_rule_packs() -> list[dict[str, object]]:
    """Return provider-independent metadata for repository-bundled rule packs."""
    return [deepcopy(_DEMO_PACK)]


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

    legacy = evaluate_graph_fixture(graph_facts, rule_id=rule_id)
    outcome = {
        "pass": "satisfied",
        "hard_violation": "violated",
        "bounded_failure_off_page": "indeterminate",
        "evaluation_diagnostic": "indeterminate",
    }.get(str(legacy["result_type"]), "indeterminate")
    evidence = deepcopy(legacy["evidence"])
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
