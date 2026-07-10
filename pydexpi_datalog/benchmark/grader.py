"""Pure-function grading for the reasoning-architecture benchmark.

``grade`` is a pure function of (answer, ground truth, canonical base fact
layer): no I/O, no clock, no model calls. The report generator computes the
benchmark verdict from these grades; no human or agent narrative decides.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydexpi_datalog.benchmark.contract import (
    POSTURE_SOURCE_GROUNDED,
    SOURCE_CONCLUSION_VERDICTS,
    GroundTruth,
    StructuredAnswer,
)


@dataclass(frozen=True)
class Grade:
    """The graded outcome for one answer against one ground truth.

    ``passed`` is the single creditable bit; the remaining fields are the
    per-axis diagnostics that explain it in the benchmark report.
    """

    passed: bool
    verdict_match: bool
    witness_match: bool
    posture_consistent: bool
    missing_witness_ids: tuple[str, ...] = ()
    extra_witness_ids: tuple[str, ...] = ()
    unknown_witness_ids: tuple[str, ...] = ()


def known_node_ids(graph_facts: dict[str, object]) -> frozenset[str]:
    """Node identities of the canonical base fact layer (graph_facts.json)."""
    facts = graph_facts.get("facts")
    if not isinstance(facts, dict):
        return frozenset()
    nodes = facts.get("nodes")
    if not isinstance(nodes, list):
        return frozenset()
    return frozenset(
        str(node["node_id"])
        for node in nodes
        if isinstance(node, dict) and "node_id" in node
    )


def grade(
    *,
    answer: StructuredAnswer,
    ground_truth: GroundTruth,
    graph_facts: dict[str, object],
) -> Grade:
    """Grade one structured answer against pre-committed ground truth.

    - Verdict must match the ground truth exactly.
    - The witness set must equal the ground-truth set exactly, and every
      witness must name a node known to the drawing's canonical base fact
      layer; unknown IDs are never creditable evidence.
    - A source-conclusion verdict (violation_found / no_violation) is only
      creditable under a declared source-grounded posture; a non-conclusion
      verdict must not claim one.
    """
    node_ids = known_node_ids(graph_facts)
    answer_witnesses = frozenset(answer.witness_ids)
    expected_witnesses = frozenset(ground_truth.witness_ids)

    unknown = answer_witnesses - node_ids
    missing = expected_witnesses - answer_witnesses
    extra = (answer_witnesses & node_ids) - expected_witnesses

    verdict_match = answer.verdict == ground_truth.verdict
    witness_match = not unknown and not missing and not extra

    if answer.verdict in SOURCE_CONCLUSION_VERDICTS:
        posture_consistent = answer.posture == POSTURE_SOURCE_GROUNDED
    else:
        posture_consistent = answer.posture != POSTURE_SOURCE_GROUNDED

    return Grade(
        passed=verdict_match and witness_match and posture_consistent,
        verdict_match=verdict_match,
        witness_match=witness_match,
        posture_consistent=posture_consistent,
        missing_witness_ids=tuple(sorted(missing)),
        extra_witness_ids=tuple(sorted(extra)),
        unknown_witness_ids=tuple(sorted(unknown)),
    )
