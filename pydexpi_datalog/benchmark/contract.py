"""Answer and ground-truth contract for the reasoning-architecture benchmark.

Every benchmark arm — LLM-direct, engine-mediated, or agentic — must emit a
:class:`StructuredAnswer`. Grading consumes this contract plus a
:class:`GroundTruth` and the drawing's canonical base fact layer
(``graph_facts.json``); it never inspects arm internals or model prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Verdicts: the graded conclusion of one benchmark question.
VERDICT_VIOLATION_FOUND = "violation_found"
VERDICT_NO_VIOLATION = "no_violation"
# The question cannot be answered from the loaded source (trap-slice ground
# truth uses this for unanswerable/ambiguous/off-domain questions).
VERDICT_UNANSWERABLE = "unanswerable"

VERDICTS = (
    VERDICT_VIOLATION_FOUND,
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
)

# Verdicts that assert a conclusion derived from the loaded source. They are
# only creditable when the answer also declares a source-grounded posture.
SOURCE_CONCLUSION_VERDICTS = (
    VERDICT_VIOLATION_FOUND,
    VERDICT_NO_VIOLATION,
)

# Grounding posture: how the arm declares its answer relates to the loaded
# source. Mirrors the QA harness posture vocabulary at the benchmark seam so
# grading does not import the harness (and its execution stack).
POSTURE_UNSPECIFIED = "unspecified"
POSTURE_SOURCE_GROUNDED = "source_grounded"
POSTURE_GENERAL_KNOWLEDGE = "general_knowledge"
POSTURE_SOURCE_DATA_UNAVAILABLE = "source_data_unavailable"
POSTURE_OUT_OF_SCOPE = "out_of_scope"

POSTURES = (
    POSTURE_UNSPECIFIED,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_OUT_OF_SCOPE,
)


@dataclass(frozen=True)
class StructuredAnswer:
    """The answer contract every benchmark arm emits for one question.

    ``transcript`` and ``usage`` are audit payload: they ship with every
    answer for post-hoc review and cost reporting but never influence the
    grade.
    """

    verdict: str
    witness_ids: tuple[str, ...] = ()
    posture: str = POSTURE_UNSPECIFIED
    transcript: tuple[dict[str, object], ...] = ()
    usage: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundTruth:
    """The pre-committed expected outcome for one benchmark question."""

    verdict: str
    witness_ids: tuple[str, ...] = ()
