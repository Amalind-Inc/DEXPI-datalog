from __future__ import annotations

from copy import deepcopy

from .rule_pack_markdown import parse_rule_pack_markdown
from .souffle_rule_pack import RULE_PACKS_DIR, evaluate_rule_fence


def bundled_rule_packs() -> list[dict[str, object]]:
    """Return provider-independent metadata for repository-bundled rule packs.

    Each pack is authored as a canonical markdown document under
    ``rule_packs/`` (frontmatter metadata, per-rule restatement prose, and
    fenced Souffle programs); see ``rule_pack_markdown``.
    """
    return [
        parse_rule_pack_markdown(path.read_text(encoding="utf-8"))
        for path in sorted(RULE_PACKS_DIR.glob("*.md"))
    ]


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
    return evaluate_pack_rule(
        graph_facts,
        pack=_pack(pack_id),
        rule_id=rule_id,
        direction_basis=direction_basis,
        direction_review_status=direction_review_status,
    )


def evaluate_pack_rule(
    graph_facts: dict[str, object],
    *,
    pack: dict[str, object],
    rule_id: str,
    direction_basis: str = "explicit",
    direction_review_status: str | None = None,
    scope_entity_id: str | None = None,
) -> dict[str, object]:
    rule = next(
        (
            candidate
            for candidate in pack["rules"]  # type: ignore[union-attr]
            if str(candidate["rule_id"]) == rule_id
        ),
        None,
    )
    if rule is None:
        raise ValueError(f"unknown rule: {pack['pack_id']}/{rule_id}")

    fence = str(rule["executable_logic"]["content"])
    legacy = evaluate_rule_fence(
        graph_facts,
        rule_id=rule_id,
        fence=fence,
        scope_entity_id=scope_entity_id,
    )
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
