"""Closed, mechanically decidable audit-trace checks for the RMSO spike."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    StructuredAnswer,
    VERDICT_UNANSWERABLE,
)


POLICY_ABSTENTION_OPERATION = (
    "permission_or_defeasible_not_decidable_from_monotone_drawing"
)


@dataclass(frozen=True)
class AuditTraceReport:
    trace_safe: bool
    coverage: float
    grounded_premise_rate: float
    replay_success: float
    dependency_validity: bool
    consistency: bool
    policy_compliance: bool
    history_integrity: bool
    uncovered_claims: tuple[str, ...]
    invalid_step_ids: tuple[str, ...]
    total_steps: int
    superseded_steps: int
    final_support_steps: int


def verify_audit_trace(
    *,
    answer: StructuredAnswer,
    graph_facts: Mapping[str, object],
    replay_souffle: Callable[[str, str], tuple[str, ...]] | None = None,
    xml_sha256: str | None = None,
    replay_python: Callable[[str, str], Mapping[str, object]] | None = None,
    allow_policy_abstention: bool = False,
) -> AuditTraceReport:
    """Verify only the spike's closed support vocabulary.

    Free-form prose is intentionally absent from this interface. Unknown
    support kinds and operations are uncredited instead of being interpreted
    by an LLM judge.
    """
    raw_steps = answer.support.get("steps", [])
    raw_claims = answer.support.get("claims", [])
    if not isinstance(raw_steps, list) or not isinstance(raw_claims, list):
        return _empty_failure(answer)

    steps: dict[str, Mapping[str, object]] = {}
    duplicate_ids: set[str] = set()
    malformed_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping):
            malformed_ids.add(f"step-index:{index}")
            continue
        step_id = raw_step.get("id")
        if not isinstance(step_id, str) or not step_id:
            malformed_ids.add(f"step-index:{index}")
            continue
        if step_id in steps:
            duplicate_ids.add(step_id)
        steps[step_id] = raw_step

    expected_claims = {"verdict", *(f"witness:{item}" for item in answer.witness_ids)}
    claim_steps: dict[str, tuple[str, ...]] = {}
    malformed_claims = False
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, Mapping):
            malformed_claims = True
            continue
        claim = raw_claim.get("claim")
        raw_ids = raw_claim.get("step_ids")
        if (
            not isinstance(claim, str)
            or claim not in expected_claims
            or claim in claim_steps
            or not isinstance(raw_ids, list)
            or not raw_ids
            or not all(isinstance(item, str) for item in raw_ids)
        ):
            malformed_claims = True
            continue
        claim_steps[claim] = tuple(raw_ids)
    uncovered = tuple(sorted(expected_claims - claim_steps.keys()))
    coverage = (
        (len(expected_claims) - len(uncovered)) / len(expected_claims)
        if expected_claims
        else 1.0
    )

    reachable: set[str] = set()
    dependency_validity = not malformed_claims
    history_integrity = not duplicate_ids and not malformed_ids
    visiting: set[str] = set()

    def visit(step_id: str) -> None:
        nonlocal dependency_validity, history_integrity
        if step_id in reachable:
            return
        if step_id in visiting:
            dependency_validity = False
            history_integrity = False
            return
        step = steps.get(step_id)
        if step is None:
            dependency_validity = False
            return
        visiting.add(step_id)
        raw_dependencies = step.get("dependencies", [])
        if not isinstance(raw_dependencies, list) or not all(
            isinstance(item, str) for item in raw_dependencies
        ):
            dependency_validity = False
        else:
            for dependency in raw_dependencies:
                visit(dependency)
        visiting.remove(step_id)
        reachable.add(step_id)

    for ids in claim_steps.values():
        for step_id in ids:
            visit(step_id)

    invalid = set(duplicate_ids) | malformed_ids
    grounded_total = 0
    grounded_valid = 0
    replay_total = 0
    replay_valid = 0
    policy_abstention_total = 0
    policy_abstention_valid = 0
    consistency = True
    policy_compliance = True
    known_nodes, known_edges = _known_graph_items(graph_facts)
    expected_node_count = len(known_nodes)
    expected_edge_count = len(known_edges)
    python_analysis_input = "graph_facts.json" if graph_facts else "drawing.xml"

    for step_id in reachable:
        step = steps[step_id]
        if step.get("superseded") is True:
            invalid.add(step_id)
            history_integrity = False
        kind = step.get("kind")
        dependencies = step.get("dependencies", [])
        if kind == "graph_node":
            grounded_total += 1
            if step.get("node_id") in known_nodes:
                grounded_valid += 1
            else:
                invalid.add(step_id)
        elif kind == "graph_scope":
            grounded_total += 1
            if (
                step.get("node_count") == expected_node_count
                and step.get("edge_count") == expected_edge_count
            ):
                grounded_valid += 1
            else:
                invalid.add(step_id)
        elif kind == "graph_edge":
            grounded_total += 1
            edge = (step.get("source_id"), step.get("target_id"), step.get("edge_key"))
            if edge in known_edges:
                grounded_valid += 1
            else:
                invalid.add(step_id)
        elif kind == "xml_scope":
            grounded_total += 1
            if (
                step.get("artifact") == "drawing.xml"
                and step.get("sha256") == xml_sha256
                and not dependencies
            ):
                grounded_valid += 1
            else:
                invalid.add(step_id)
        elif kind == "python_execution":
            replay_total += 1
            artifact = step.get("artifact")
            output = step.get("output")
            declared_ids = step.get("witness_ids")
            if (
                artifact != "analysis.py"
                or step.get("input") != python_analysis_input
                or output != "analysis_replay.json"
                or not isinstance(declared_ids, list)
                or not all(isinstance(item, str) for item in declared_ids)
                or not dependencies
                or replay_python is None
            ):
                invalid.add(step_id)
                continue
            replayed = replay_python(artifact, output)
            replayed_ids = replayed.get("witness_ids")
            if (
                replayed.get("verdict") == step.get("verdict")
                and replayed_ids == declared_ids
            ):
                replay_valid += 1
            else:
                invalid.add(step_id)
            if (
                step.get("verdict") != answer.verdict
                or tuple(sorted(set(declared_ids)))
                != tuple(sorted(set(answer.witness_ids)))
            ):
                consistency = False
                invalid.add(step_id)
        elif kind == "souffle_execution":
            replay_total += 1
            artifact = step.get("artifact")
            relation = step.get("relation")
            declared = step.get("witness_ids")
            if (
                artifact != "analysis.dl"
                or relation != "result_witness"
                or not isinstance(declared, list)
                or not all(isinstance(item, str) for item in declared)
                or not dependencies
                or replay_souffle is None
            ):
                invalid.add(step_id)
                continue
            replayed = tuple(sorted(set(replay_souffle(artifact, relation))))
            declared_set = tuple(sorted(set(declared)))
            if replayed == declared_set:
                replay_valid += 1
            else:
                invalid.add(step_id)
            if declared_set != tuple(sorted(set(answer.witness_ids))):
                consistency = False
                invalid.add(step_id)
        elif kind == "derivation":
            if step.get("operation") != "identity" or not dependencies:
                invalid.add(step_id)
                policy_compliance = False
        elif kind == "policy_abstention":
            policy_abstention_total += 1
            if (
                allow_policy_abstention
                and step.get("operation") == POLICY_ABSTENTION_OPERATION
                and not dependencies
                and answer.verdict == VERDICT_UNANSWERABLE
                and answer.posture == POSTURE_SOURCE_DATA_UNAVAILABLE
                and not answer.witness_ids
            ):
                policy_abstention_valid += 1
            else:
                invalid.add(step_id)
                consistency = False
                policy_compliance = False
        else:
            invalid.add(step_id)
            policy_compliance = False

    policy_only = (
        policy_abstention_total == 1
        and policy_abstention_valid == 1
        and len(reachable) == 1
    )
    grounded_rate = (
        grounded_valid / grounded_total if grounded_total else float(policy_only)
    )
    replay_success = (
        replay_valid / replay_total if replay_total else float(policy_only)
    )
    # Every source conclusion needs at least one grounded terminal and one
    # replayed execution in its final relied-upon subgraph.
    if not policy_only and (grounded_valid == 0 or replay_valid == 0):
        consistency = False

    superseded_count = sum(
        isinstance(step, Mapping) and step.get("superseded") is True
        for step in raw_steps
    )
    trace_safe = (
        not uncovered
        and not invalid
        and dependency_validity
        and consistency
        and policy_compliance
        and history_integrity
        and coverage == 1.0
        and grounded_rate == 1.0
        and replay_success == 1.0
    )
    return AuditTraceReport(
        trace_safe=trace_safe,
        coverage=coverage,
        grounded_premise_rate=grounded_rate,
        replay_success=replay_success,
        dependency_validity=dependency_validity,
        consistency=consistency,
        policy_compliance=policy_compliance,
        history_integrity=history_integrity,
        uncovered_claims=uncovered,
        invalid_step_ids=tuple(sorted(invalid)),
        total_steps=len(raw_steps),
        superseded_steps=superseded_count,
        final_support_steps=len(reachable),
    )


def verify_souffle_audit_trace(
    *,
    answer: StructuredAnswer,
    graph_facts: Mapping[str, object],
    executed_program: str,
) -> AuditTraceReport:
    """Verify an Arm B trace by replaying its submitted portable program."""
    from pydexpi_datalog.benchmark.rmso_faithfulness import replay_result_witness

    return verify_audit_trace(
        answer=answer,
        graph_facts=graph_facts,
        replay_souffle=lambda artifact, relation: replay_result_witness(
            executed_program, graph_facts
        ),
    )


def _known_graph_items(
    graph_facts: Mapping[str, object],
) -> tuple[set[object], set[tuple[object, object, object]]]:
    facts = graph_facts.get("facts")
    if not isinstance(facts, Mapping):
        return set(), set()
    raw_nodes = facts.get("nodes", [])
    raw_edges = facts.get("edges", [])
    nodes = {
        item.get("node_id") for item in raw_nodes if isinstance(item, Mapping)
    }
    edges = {
        (item.get("source_id"), item.get("target_id"), item.get("edge_key"))
        for item in raw_edges
        if isinstance(item, Mapping)
    }
    return nodes, edges


def _empty_failure(answer: StructuredAnswer) -> AuditTraceReport:
    claims = ("verdict", *(f"witness:{item}" for item in answer.witness_ids))
    return AuditTraceReport(
        False,
        0.0,
        0.0,
        0.0,
        False,
        False,
        False,
        False,
        tuple(sorted(claims)),
        (),
        0,
        0,
        0,
    )
