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
    TrapJudgment,
    TrapRubric,
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
    trap_rubric_passed: bool | None = None
    grounded_refusal: bool | None = None
    graceful_redirect: bool | None = None
    judge_rationale: str | None = None


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
    trap_rubric: TrapRubric | None = None,
    trap_judgment: TrapJudgment | None = None,
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

    if trap_rubric is not None:
        posture_consistent = answer.posture == trap_rubric.expected_posture
        grounded_refusal = (
            trap_judgment.grounded_refusal if trap_judgment is not None else False
        )
        graceful_redirect = (
            trap_judgment.graceful_redirect if trap_judgment is not None else False
        )
        trap_rubric_passed = (
            bool(answer.answer_text.strip())
            and not answer.witness_ids
            and posture_consistent
            and grounded_refusal
            and graceful_redirect
        )
        judge_rationale = (
            trap_judgment.rationale if trap_judgment is not None else None
        )
    else:
        if answer.verdict in SOURCE_CONCLUSION_VERDICTS:
            posture_consistent = answer.posture == POSTURE_SOURCE_GROUNDED
        else:
            posture_consistent = answer.posture != POSTURE_SOURCE_GROUNDED
        grounded_refusal = None
        graceful_redirect = None
        trap_rubric_passed = None
        judge_rationale = None

    return Grade(
        passed=(
            verdict_match
            and witness_match
            and posture_consistent
            and trap_rubric_passed is not False
        ),
        verdict_match=verdict_match,
        witness_match=witness_match,
        posture_consistent=posture_consistent,
        missing_witness_ids=tuple(sorted(missing)),
        extra_witness_ids=tuple(sorted(extra)),
        unknown_witness_ids=tuple(sorted(unknown)),
        trap_rubric_passed=trap_rubric_passed,
        grounded_refusal=grounded_refusal,
        graceful_redirect=graceful_redirect,
        judge_rationale=judge_rationale,
    )
