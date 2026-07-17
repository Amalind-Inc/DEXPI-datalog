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
POSTURE_NEEDS_CLARIFICATION = "needs_clarification"

POSTURES = (
    POSTURE_UNSPECIFIED,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_NEEDS_CLARIFICATION,
)

TRAP_EXPECTED_POSTURES = (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_NEEDS_CLARIFICATION,
)


@dataclass(frozen=True)
class TrapRubric:
    """Pre-committed qualitative criteria for one trap-slice question."""

    expected_posture: str
    refusal_basis: str
    redirect_target: str
    human_spot_check: bool = False


@dataclass(frozen=True)
class TrapJudgment:
    """Informational judge assessment of refusal and redirect quality."""

    grounded_refusal: bool
    graceful_redirect: bool
    rationale: str


@dataclass(frozen=True)
class StructuredAnswer:
    """The answer contract every benchmark arm emits for one question.

    ``answer_text`` is the candidate's auditable explanation; trap judges assess
    its refusal and redirect quality, but deterministic compliance scoring does
    not. ``transcript`` and ``usage`` are audit payload that ship with every
    answer for post-hoc review and cost reporting.
    """

    verdict: str
    witness_ids: tuple[str, ...] = ()
    posture: str = POSTURE_UNSPECIFIED
    transcript: tuple[dict[str, object], ...] = ()
    usage: dict[str, object] = field(default_factory=dict)
    answer_text: str = ""
    support: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundTruth:
    """The pre-committed expected outcome for one benchmark question."""

    verdict: str
    witness_ids: tuple[str, ...] = ()
