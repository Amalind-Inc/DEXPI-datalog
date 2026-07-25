"""Graph-derived oracle for the SME-reviewed hand-authored benchmark slice.

The questions themselves are authored by a person.  Each manifest entry also
carries a small declarative oracle so its exact verdict and witness set can be
reproduced from the canonical base fact layer before SME sign-off.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydexpi_datalog.benchmark.contract import (
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
)

_MATCH_NODES = "match_nodes"
_OUTGOING_COUNT = "outgoing_edge_count_not_equal"
_INCOMING_COUNT = "incoming_edge_count_not_equal"
_OUTGOING_LESS_THAN = "outgoing_edge_count_less_than"
_NOT_REACHABLE_FROM = "not_reachable_from"
_NO_INCOMING_EDGE_OF_ANY = "no_incoming_edge_of_any"
_ABSTENTION_EXPECTED = "abstention_expected"
_OPERATIONS = {
    _MATCH_NODES,
    _OUTGOING_COUNT,
    _INCOMING_COUNT,
    _OUTGOING_LESS_THAN,
    _NOT_REACHABLE_FROM,
    _NO_INCOMING_EDGE_OF_ANY,
    _ABSTENTION_EXPECTED,
}
_REACHABILITY_DIRECTIONS = ("forward", "reverse", "undirected")


def verify_hand_authored_manifest(path: Path) -> int:
    """Verify every declared answer against its drawing; return entry count."""
    from pydexpi_datalog.benchmark.dataset import load_question_manifest

    raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_questions = raw_manifest.get("questions")
    if not isinstance(raw_questions, list):
        raise ValueError("Hand-authored manifest questions must be a list.")

    loaded = {
        question.question_id: question
        for question in load_question_manifest(path).questions
    }
    for raw_question in raw_questions:
        if not isinstance(raw_question, Mapping):
            raise ValueError("Hand-authored manifest entries must be objects.")
        question_id = raw_question.get("id")
        oracle = raw_question.get("oracle")
        if not isinstance(question_id, str) or not isinstance(oracle, Mapping):
            raise ValueError("Each hand-authored entry requires an id and oracle.")
        question = loaded[question_id]
        graph_facts = json.loads(
            (question.drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        derived = derive_ground_truth(graph_facts, oracle)
        if derived != question.ground_truth:
            raise ValueError(
                f"Hand-authored ground truth mismatch for {question_id!r}: "
                f"declared {question.ground_truth!r}, derived {derived!r}."
            )
    return len(raw_questions)


def derive_ground_truth(
    graph_facts: Mapping[str, object], oracle: Mapping[str, object]
) -> GroundTruth:
    """Recompute one manifest entry's exact answer from canonical graph facts."""
    operation = oracle.get("operation")
    if operation not in _OPERATIONS:
        raise ValueError(f"Unsupported hand-authored oracle operation: {operation!r}")
    if operation == _ABSTENTION_EXPECTED:
        # Permission/defeasible negative control: the drawing's monotone facts
        # cannot soundly settle the question, so the only correct answer is
        # abstention with no witnesses.
        return GroundTruth(verdict=VERDICT_UNANSWERABLE, witness_ids=())

    facts = graph_facts.get("facts")
    if not isinstance(facts, Mapping):
        raise ValueError("Canonical graph facts must contain a facts object.")
    raw_nodes = facts.get("nodes")
    raw_edges = facts.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("Canonical graph facts must contain node and edge lists.")

    node_match = _required_match(oracle, "node")
    candidates = [
        node
        for node in raw_nodes
        if isinstance(node, Mapping)
        and isinstance(node.get("node_id"), str)
        and _attributes_match(node, node_match)
    ]

    if operation == _MATCH_NODES:
        witnesses = _node_ids(candidates)
    elif operation == _NOT_REACHABLE_FROM:
        witnesses = _reachability_witnesses(
            oracle=oracle,
            raw_nodes=raw_nodes,
            raw_edges=raw_edges,
            candidates=candidates,
        )
    elif operation == _NO_INCOMING_EDGE_OF_ANY:
        edge_matches = _required_match_list(oracle, "edges")
        witnesses = tuple(
            sorted(
                str(node["node_id"])
                for node in candidates
                if not any(
                    isinstance(edge, Mapping)
                    and edge.get("target_id") == node["node_id"]
                    and any(_attributes_match(edge, match) for match in edge_matches)
                    for edge in raw_edges
                )
            )
        )
    else:
        edge_match = _required_match(oracle, "edge")
        expected = oracle.get("expected")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValueError("Count oracle expected must be a non-negative integer.")
        endpoint = "target_id" if operation == _INCOMING_COUNT else "source_id"
        witnesses = tuple(
            sorted(
                str(node["node_id"])
                for node in candidates
                if _count_fails(
                    count=sum(
                        1
                        for edge in raw_edges
                        if isinstance(edge, Mapping)
                        and edge.get(endpoint) == node["node_id"]
                        and _attributes_match(edge, edge_match)
                    ),
                    expected=expected,
                    operation=operation,
                )
            )
        )

    return GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND if witnesses else VERDICT_NO_VIOLATION,
        witness_ids=witnesses,
    )


def _required_match(oracle: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = oracle.get(field)
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"Hand-authored oracle {field} must be a non-empty object.")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(
            f"Hand-authored oracle {field} keys must be non-empty strings."
        )
    return value


def _required_match_list(
    oracle: Mapping[str, object], field: str
) -> list[Mapping[str, object]]:
    value = oracle.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"Hand-authored oracle {field} must be a non-empty list of matches."
        )
    return [_required_match({field: match}, field) for match in value]


def _reachability_witnesses(
    *,
    oracle: Mapping[str, object],
    raw_nodes: list[object],
    raw_edges: list[object],
    candidates: list[Mapping[str, object]],
) -> tuple[str, ...]:
    """IDs of candidates with no path from (or to) any matching source node."""
    direction = oracle.get("direction", "forward")
    if direction not in _REACHABILITY_DIRECTIONS:
        raise ValueError(
            f"Reachability oracle direction must be one of "
            f"{list(_REACHABILITY_DIRECTIONS)!r}, got {direction!r}."
        )
    source_match = _required_match(oracle, "source_node")
    raw_edge_matches = oracle.get("edges")
    edge_matches = (
        None if raw_edge_matches is None else _required_match_list(oracle, "edges")
    )

    adjacency: dict[str, list[str]] = {}
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            continue
        if edge_matches is not None and not any(
            _attributes_match(edge, match) for match in edge_matches
        ):
            continue
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        if not isinstance(source_id, str) or not isinstance(target_id, str):
            continue
        if direction in ("forward", "undirected"):
            adjacency.setdefault(source_id, []).append(target_id)
        if direction in ("reverse", "undirected"):
            adjacency.setdefault(target_id, []).append(source_id)

    frontier = [
        str(node["node_id"])
        for node in raw_nodes
        if isinstance(node, Mapping)
        and isinstance(node.get("node_id"), str)
        and _attributes_match(node, source_match)
    ]
    if not frontier:
        raise ValueError(
            "Reachability oracle source_node matches no nodes in this drawing; "
            "the question would be vacuously true for every candidate."
        )
    reached = set(frontier)
    while frontier:
        node_id = frontier.pop()
        for neighbor in adjacency.get(node_id, []):
            if neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)

    return tuple(
        sorted(
            str(node["node_id"])
            for node in candidates
            if node["node_id"] not in reached
        )
    )


def _attributes_match(
    item: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    attributes = item.get("attributes")
    if not isinstance(attributes, Mapping):
        return False
    for name, value in expected.items():
        if isinstance(value, list):
            if attributes.get(name) not in value:
                return False
        elif attributes.get(name) != value:
            return False
    return True


def _count_fails(*, count: int, expected: int, operation: object) -> bool:
    if operation == _OUTGOING_LESS_THAN:
        return count < expected
    return count != expected


def _node_ids(nodes: list[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(sorted(str(node["node_id"]) for node in nodes))


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify hand-authored benchmark ground truth from graph facts."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    count = verify_hand_authored_manifest(args.manifest.resolve())
    print(f"Verified {count} hand-authored benchmark questions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
