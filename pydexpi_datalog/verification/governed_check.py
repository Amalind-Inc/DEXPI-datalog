"""Narrow, PortLog-owned deterministic checks exposed to the agent."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

from .bundled_rule_pack import evaluate_pack_rule, pack_metadata

CHECK_ID = "pump_discharge_check_valve"
CHECK_VERSION = 1
PACK_ID = "demo-process-safety"

REQUIRED_FACTS = (
    "scoped object is a DEXPI CentrifugalPump",
    "one unambiguous discharge nozzle",
    "directed first-unbranched discharge connectivity",
    "DEXPI component class for every traversed object",
    "first branch or terminal boundary",
)


class GovernedCheckExecutionError(ValueError):
    """An invalid check request that PortLog must reject before execution."""

    pass


def governed_check_cache_key(
    *,
    document_digest: str,
    check_id: str,
    check_version: int,
    parameters: dict[str, object],
) -> str:
    """Build a collision-resistant key for one exact deterministic input."""

    payload = {
        "document_digest": document_digest,
        "check_id": check_id,
        "check_version": check_version,
        "parameters": parameters,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"governed-check:{hashlib.sha256(encoded).hexdigest()}"


def run_governed_check(
    graph_facts: dict[str, object],
    *,
    check_id: str,
    scope_entity_id: str,
    document_digest: str | None = None,
    cache_provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run one allowlisted check over one explicitly scoped pump.

    The model supplies only ``check_id`` and ``scope_entity_id``.  The rule
    source, rule version, required facts, engine, and outcome remain owned by
    this module and the bundled Souffle rule pack.
    """

    if check_id != CHECK_ID:
        raise GovernedCheckExecutionError(f"check.invalid: unknown check '{check_id}'")
    if not isinstance(scope_entity_id, str) or not scope_entity_id.strip():
        raise GovernedCheckExecutionError("scope.invalid: a pump entity ID is required")

    pump_id = _resolve_pump_id(graph_facts, scope_entity_id)
    started = datetime.now(UTC)
    cache_key = governed_check_cache_key(
        document_digest=document_digest or str(graph_facts.get("source_id", "unknown")),
        check_id=check_id,
        check_version=CHECK_VERSION,
        parameters={"scope_entity_id": scope_entity_id},
    )
    provenance = {
        "hit": False,
        "key": cache_key,
        **(cache_provenance or {}),
    }

    try:
        rule_result = evaluate_pack_rule(
            graph_facts,
            pack=pack_metadata(PACK_ID),
            rule_id=CHECK_ID,
            scope_entity_id=pump_id,
        )
    except Exception as error:
        ended = datetime.now(UTC)
        return _failed_result(
            check_id=check_id,
            scope_entity_id=scope_entity_id,
            pump_id=pump_id,
            started=started,
            ended=ended,
            provenance=provenance,
            document_digest=document_digest,
            error=error,
        )

    ended = datetime.now(UTC)
    outcome = str(rule_result.get("outcome", "indeterminate"))
    if outcome not in {"satisfied", "violated", "indeterminate"}:
        return _failed_result(
            check_id=check_id,
            scope_entity_id=scope_entity_id,
            pump_id=pump_id,
            started=started,
            ended=ended,
            provenance=provenance,
            document_digest=document_digest,
            error=RuntimeError("rule engine returned an invalid outcome"),
        )

    evidence = deepcopy(rule_result.get("evidence", {}))
    if not isinstance(evidence, dict):
        evidence = {}
    ordered_ids = _ordered_evidence_ids(
        pump_id=pump_id,
        subject=rule_result.get("subject"),
        evidence=evidence,
    )
    boundary = evidence.get("boundary")
    boundary_kind = boundary.get("kind") if isinstance(boundary, dict) else None
    reason_code = _reason_code(outcome=outcome, boundary_kind=boundary_kind)
    scope_completeness = evidence.get("scope_completeness")
    coverage_complete = (
        isinstance(scope_completeness, dict)
        and scope_completeness.get("complete") is True
    )
    coverage = {
        "requested_entity_id": scope_entity_id,
        "evaluated_entity_id": pump_id,
        "required_facts": list(REQUIRED_FACTS),
        "missing_facts": [] if coverage_complete else list(REQUIRED_FACTS),
        "complete": coverage_complete,
    }
    limitations = (
        []
        if coverage_complete
        else [
            {
                "code": "coverage.incomplete",
                "message": "The prepared discharge scope is incomplete; no pass or fail is authoritative.",
            }
        ]
    )
    evidence["ordered_entity_ids"] = ordered_ids
    evidence["source_references"] = [
        {
            "entity_id": entity_id,
            "source": str(graph_facts.get("source_path", graph_facts.get("fixture_id", "prepared-facts"))),
        }
        for entity_id in ordered_ids
    ]
    evaluated_source_revision = document_digest or str(
        graph_facts.get("source_id", graph_facts.get("fixture_id", "unknown"))
    )

    return {
        "schema_version": 1,
        "check_id": check_id,
        "check_version": CHECK_VERSION,
        "rule": {
            "pack_id": PACK_ID,
            "pack_version": rule_result.get("pack", {}).get("version", 1)
            if isinstance(rule_result.get("pack"), dict)
            else 1,
            "plain_language_question": (
                "Does this centrifugal pump have a DEXPI CheckValve subclass "
                "on the first unbranched downstream segment starting at its discharge nozzle?"
            ),
        },
        "scope": {
            "requested_entity_id": scope_entity_id,
            "pump_id": pump_id,
            "class": "CentrifugalPump",
        },
        "required_facts": list(REQUIRED_FACTS),
        "coverage": coverage,
        "limitations": limitations,
        "run_status": "completed",
        "outcome": outcome,
        "reason_code": reason_code,
        "message": str(rule_result.get("message", "")),
        "evidence": evidence,
        "engine": {
            "name": "souffle",
            "status": "completed",
            "runner": "pydexpi_datalog.semantics.souffle_runner",
            "rule_source": "demo-process-safety.md",
        },
        "document_preparation_digest": evaluated_source_revision,
        "source_attestation": {
            "revision": evaluated_source_revision,
            "kind": "prepared-review-source",
            "authority": "governed-check-engine",
        },
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_ms": max(0.0, (ended - started).total_seconds() * 1000),
        "cache_provenance": provenance,
        "diagnostics": [],
    }


def _resolve_pump_id(graph_facts: dict[str, object], requested: str) -> str:
    nodes = graph_facts.get("facts", {}).get("nodes", [])
    if not isinstance(nodes, list):
        raise GovernedCheckExecutionError("scope.invalid: prepared node facts are unavailable")
    matches: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attributes = node.get("attributes", {})
        if not isinstance(attributes, dict):
            continue
        node_id = str(node.get("node_id", ""))
        if requested in {node_id, str(attributes.get("proteusId", "")), str(attributes.get("tagName", ""))}:
            if attributes.get("label") == "CentrifugalPump":
                matches.append(node_id)
    if len(matches) != 1:
        raise GovernedCheckExecutionError(
            "scope.invalid: scope must identify exactly one DEXPI CentrifugalPump"
        )
    return matches[0]


def _ordered_evidence_ids(*, pump_id: str, subject: object, evidence: dict[str, object]) -> list[str]:
    ordered = [pump_id]
    if isinstance(subject, dict):
        nozzle = subject.get("discharge_nozzle_id")
        if isinstance(nozzle, str) and nozzle != "unknown":
            ordered.append(nozzle)
    traversed = evidence.get("traversed_objects", [])
    if isinstance(traversed, list):
        for item in traversed:
            if isinstance(item, dict) and isinstance(item.get("object_id"), str):
                ordered.append(str(item["object_id"]))
    boundary = evidence.get("boundary")
    if isinstance(boundary, dict) and isinstance(boundary.get("object_id"), str):
        ordered.append(str(boundary["object_id"]))
    return list(dict.fromkeys(ordered))


def _reason_code(*, outcome: str, boundary_kind: object) -> str:
    if outcome == "satisfied":
        return "check_valve_found"
    if outcome == "violated":
        return "no_check_valve_on_complete_segment"
    if boundary_kind == "unresolved_discharge_nozzle":
        return "ambiguous_discharge_nozzle"
    if boundary_kind == "off_page_connector":
        return "incomplete_discharge_segment"
    return "incomplete_discharge_segment"


def _failed_result(
    *,
    check_id: str,
    scope_entity_id: str,
    pump_id: str,
    started: datetime,
    ended: datetime,
    provenance: dict[str, object],
    document_digest: str | None,
    error: Exception,
) -> dict[str, object]:
    error_code = str(getattr(error, "code", "engine.execution_failed"))
    if not error_code.startswith("engine."):
        error_code = "engine.execution_failed"
    evaluated_source_revision = document_digest or "unknown"
    return {
        "schema_version": 1,
        "check_id": check_id,
        "check_version": CHECK_VERSION,
        "scope": {
            "requested_entity_id": scope_entity_id,
            "pump_id": pump_id,
            "class": "CentrifugalPump",
        },
        "required_facts": list(REQUIRED_FACTS),
        "coverage": {
            "requested_entity_id": scope_entity_id,
            "evaluated_entity_id": pump_id,
            "required_facts": list(REQUIRED_FACTS),
            "missing_facts": list(REQUIRED_FACTS),
            "complete": False,
        },
        "limitations": [
            {
                "code": "coverage.incomplete",
                "message": "The deterministic engine did not complete; no pass or fail is authoritative.",
            }
        ],
        "run_status": "failed",
        "outcome": None,
        "reason_code": error_code,
        "message": "The deterministic check did not complete; no engineering outcome was produced.",
        "evidence": {
            "ordered_entity_ids": [],
            "source_references": [],
            "scope_completeness": {"complete": False, "basis": "engine_failed"},
        },
        "engine": {
            "name": "souffle",
            "status": "failed",
            "runner": "pydexpi_datalog.semantics.souffle_runner",
        },
        "document_preparation_digest": evaluated_source_revision,
        "source_attestation": {
            "revision": evaluated_source_revision,
            "kind": "prepared-review-source",
            "authority": "governed-check-engine",
        },
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_ms": max(0.0, (ended - started).total_seconds() * 1000),
        "cache_provenance": provenance,
        "diagnostics": [{"code": error_code, "message": str(error)}],
    }
