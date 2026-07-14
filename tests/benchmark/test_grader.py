from __future__ import annotations

import json
from pathlib import Path

from pydexpi_datalog.benchmark import (
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
    StructuredAnswer,
    grade,
)
from pydexpi_datalog.benchmark.contract import TrapJudgment, TrapRubric

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)


def make_graph_facts(node_ids: list[str]) -> dict[str, object]:
    """A minimal canonical base fact layer, shaped like graph_facts.json."""
    return {
        "fixture_id": "grader-test-fixture",
        "facts": {
            "nodes": [
                {"fact_type": "node", "node_id": node_id, "attributes": {}}
                for node_id in node_ids
            ],
            "edges": [],
        },
    }


def test_exact_verdict_and_witness_match_passes() -> None:
    """
    Behavior: an answer that reproduces the ground-truth verdict and the exact
    witness set, with witnesses known to the drawing's canonical base fact
    layer, grades as a pass on every axis.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201", "T-301"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("CV-201", "P-101"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is True
    assert result.verdict_match is True
    assert result.witness_match is True
    assert result.posture_consistent is True
    assert result.missing_witness_ids == ()
    assert result.extra_witness_ids == ()
    assert result.unknown_witness_ids == ()


def test_wrong_verdict_fails_even_with_correct_witnesses() -> None:
    """
    Behavior: verdict matching is exact — reporting no_violation against a
    violation_found ground truth fails, even when the witness set is right.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_NO_VIOLATION,
        witness_ids=("P-101", "CV-201"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.verdict_match is False
    assert result.witness_match is True


def test_missing_witness_fails_and_is_reported() -> None:
    """
    Behavior: an answer that omits a ground-truth witness fails witness
    verification and names the missing IDs in the grade diagnostics.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101",),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.verdict_match is True
    assert result.witness_match is False
    assert result.missing_witness_ids == ("CV-201",)
    assert result.extra_witness_ids == ()
    assert result.unknown_witness_ids == ()


def test_extra_known_witness_fails_and_is_reported() -> None:
    """
    Behavior: padding the witness set with additional drawing nodes beyond the
    ground truth fails — witness sets match exactly, not as supersets.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201", "T-301"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201", "T-301"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.witness_match is False
    assert result.extra_witness_ids == ("T-301",)
    assert result.missing_witness_ids == ()
    assert result.unknown_witness_ids == ()


def test_witness_unknown_to_graph_facts_is_never_creditable() -> None:
    """
    Behavior: a witness ID that does not name a node in the drawing's
    canonical base fact layer is reported as unknown, not as extra — a
    hallucinated ID can never be creditable evidence.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201", "GHOST-999"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.witness_match is False
    assert result.unknown_witness_ids == ("GHOST-999",)
    assert result.extra_witness_ids == ()


def test_duplicate_witness_ids_grade_as_a_set() -> None:
    """
    Behavior: witness verification is set-based — repeating a correct witness
    neither helps nor hurts.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "P-101", "CV-201"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is True
    assert result.witness_match is True


def test_source_conclusion_without_grounded_posture_fails() -> None:
    """
    Behavior: a violation_found verdict declared under a general-knowledge
    posture is posture-inconsistent — a source conclusion must be declared
    source-grounded, even when verdict and witnesses are correct.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
        posture=POSTURE_GENERAL_KNOWLEDGE,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.verdict_match is True
    assert result.witness_match is True
    assert result.posture_consistent is False


def test_unanswerable_claiming_source_grounded_posture_fails() -> None:
    """
    Behavior: the reverse disagreement — an unanswerable verdict must not be
    dressed up as a source-grounded conclusion.
    """
    graph_facts = make_graph_facts(["P-101"])
    answer = StructuredAnswer(
        verdict=VERDICT_UNANSWERABLE,
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(verdict=VERDICT_UNANSWERABLE)

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.verdict_match is True
    assert result.posture_consistent is False


def test_graceful_refusal_passes_without_witnesses() -> None:
    """
    Behavior: trap-slice credit — an unanswerable ground truth is satisfied by
    an unanswerable verdict under a non-grounded posture with no witnesses.
    """
    graph_facts = make_graph_facts(["P-101"])
    answer = StructuredAnswer(
        verdict=VERDICT_UNANSWERABLE,
        posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
    )
    ground_truth = GroundTruth(verdict=VERDICT_UNANSWERABLE)

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is True
    assert result.witness_match is True
    assert result.posture_consistent is True


def test_trap_credit_requires_expected_posture_and_both_rubric_axes() -> None:
    graph_facts = make_graph_facts(["P-101"])
    answer = StructuredAnswer(
        verdict=VERDICT_UNANSWERABLE,
        posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
        answer_text=(
            "Approval history is absent. I can check represented topology instead."
        ),
    )
    ground_truth = GroundTruth(verdict=VERDICT_UNANSWERABLE)
    rubric = TrapRubric(
        expected_posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
        refusal_basis="The drawing has no approval-history field.",
        redirect_target="Offer topology and equipment-attribute checks.",
    )

    missing_redirect = grade(
        answer=answer,
        ground_truth=ground_truth,
        graph_facts=graph_facts,
        trap_rubric=rubric,
        trap_judgment=TrapJudgment(
            grounded_refusal=True,
            graceful_redirect=False,
            rationale="Correct limitation, but no useful next step.",
        ),
    )
    complete = grade(
        answer=answer,
        ground_truth=ground_truth,
        graph_facts=graph_facts,
        trap_rubric=rubric,
        trap_judgment=TrapJudgment(
            grounded_refusal=True,
            graceful_redirect=True,
            rationale="Names the missing field and offers drawing checks.",
        ),
    )
    blank_answer = grade(
        answer=StructuredAnswer(
            verdict=VERDICT_UNANSWERABLE,
            posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
        ),
        ground_truth=ground_truth,
        graph_facts=graph_facts,
        trap_rubric=rubric,
        trap_judgment=TrapJudgment(
            grounded_refusal=True,
            graceful_redirect=True,
            rationale="A scripted judgment cannot rescue missing candidate prose.",
        ),
    )
    witnessed_answer = grade(
        answer=StructuredAnswer(
            verdict=VERDICT_UNANSWERABLE,
            witness_ids=("P-101",),
            posture=POSTURE_SOURCE_DATA_UNAVAILABLE,
            answer_text=answer.answer_text,
        ),
        ground_truth=ground_truth,
        graph_facts=graph_facts,
        trap_rubric=rubric,
        trap_judgment=TrapJudgment(
            grounded_refusal=True,
            graceful_redirect=True,
            rationale="A judgment cannot rescue forbidden trap witnesses.",
        ),
    )

    assert missing_redirect.passed is False
    assert missing_redirect.trap_rubric_passed is False
    assert complete.passed is True
    assert complete.trap_rubric_passed is True
    assert complete.grounded_refusal is True
    assert complete.graceful_redirect is True
    assert blank_answer.passed is False
    assert blank_answer.trap_rubric_passed is False
    assert witnessed_answer.passed is False
    assert witnessed_answer.trap_rubric_passed is False


def test_no_violation_with_witnesses_only_when_ground_truth_expects_them() -> None:
    """
    Behavior: a no_violation ground truth with an empty witness set rejects
    answers that attach witnesses anyway — they grade as extra evidence.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    answer = StructuredAnswer(
        verdict=VERDICT_NO_VIOLATION,
        witness_ids=("P-101",),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(verdict=VERDICT_NO_VIOLATION)

    result = grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert result.passed is False
    assert result.extra_witness_ids == ("P-101",)


def test_transcript_and_usage_are_audit_payload_not_grade_inputs() -> None:
    """
    Behavior: transcript and usage ship with every answer for post-hoc audit
    but never influence the grade — identical verdict/witness/posture answers
    grade identically regardless of them.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )
    bare = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    with_audit_payload = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
        posture=POSTURE_SOURCE_GROUNDED,
        transcript=({"role": "assistant", "content": "chain of thought"},),
        usage={"input_tokens": 12345, "output_tokens": 678, "cost_usd": 0.42},
    )

    assert grade(
        answer=bare, ground_truth=ground_truth, graph_facts=graph_facts
    ) == grade(
        answer=with_audit_payload, ground_truth=ground_truth, graph_facts=graph_facts
    )


def test_grade_does_not_mutate_its_inputs() -> None:
    """
    Behavior: grade() is pure — the canonical base fact layer passed in is
    read, never modified.
    """
    graph_facts = make_graph_facts(["P-101", "CV-201"])
    before = json.dumps(graph_facts, sort_keys=True)
    answer = StructuredAnswer(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101",),
        posture=POSTURE_SOURCE_GROUNDED,
    )
    ground_truth = GroundTruth(
        verdict=VERDICT_VIOLATION_FOUND,
        witness_ids=("P-101", "CV-201"),
    )

    grade(answer=answer, ground_truth=ground_truth, graph_facts=graph_facts)

    assert json.dumps(graph_facts, sort_keys=True) == before


def test_grades_against_real_exported_canonical_base_fact_layer() -> None:
    """
    Behavior: witness verification reads the real exported graph_facts.json
    shape — node identities under facts.nodes[].node_id — so a real drawing
    node grades as known and a fabricated ID as unknown.
    """
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    pump_node_id = "16fcf71b-8fb3-4e0c-a6e9-5e9d46af77bb"  # CentrifugalPump P-4713

    result = grade(
        answer=StructuredAnswer(
            verdict=VERDICT_VIOLATION_FOUND,
            witness_ids=(pump_node_id, "not-a-real-node"),
            posture=POSTURE_SOURCE_GROUNDED,
        ),
        ground_truth=GroundTruth(
            verdict=VERDICT_VIOLATION_FOUND,
            witness_ids=(pump_node_id,),
        ),
        graph_facts=graph_facts,
    )

    assert result.unknown_witness_ids == ("not-a-real-node",)
    assert result.missing_witness_ids == ()
    assert result.extra_witness_ids == ()
    assert result.passed is False
