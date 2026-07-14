"""Behavior tests for the SME-reviewable hand-authored benchmark slice."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from pydexpi_datalog.benchmark.dataset import (
    CATEGORY_COMPLIANCE_UNIVERSAL,
    CATEGORY_RETRIEVAL_LOCAL,
    SLICE_HAND_AUTHORED,
    load_question_manifest,
)
from pydexpi_datalog.benchmark.hand_authored import verify_hand_authored_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "testdata" / "benchmark" / "hand_authored_manifest.json"


def test_manifest_is_loader_valid_with_thirty_balanced_questions() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    assert len(dataset.questions) == 30
    assert all(question.slice == SLICE_HAND_AUTHORED for question in dataset.questions)
    assert Counter(question.category for question in dataset.questions) == {
        CATEGORY_COMPLIANCE_UNIVERSAL: 15,
        CATEGORY_RETRIEVAL_LOCAL: 15,
    }
    assert len({question.question_id for question in dataset.questions}) == 30
    for category in (CATEGORY_COMPLIANCE_UNIVERSAL, CATEGORY_RETRIEVAL_LOCAL):
        assert {
            question.ground_truth.verdict
            for question in dataset.questions
            if question.category == category
        } == {"violation_found", "no_violation"}


def test_questions_use_real_dexpi_training_fixtures() -> None:
    dataset = load_question_manifest(MANIFEST_PATH)

    for drawing_ref in {question.drawing_ref for question in dataset.questions}:
        graph_facts = json.loads(
            (drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        assert graph_facts["source_path"].startswith("TrainingTestCases/dexpi 1.3/")
        assert graph_facts["provenance"]["extractor"] == "pyDEXPI"


def test_every_ground_truth_is_reproduced_from_canonical_graph_facts() -> None:
    assert verify_hand_authored_manifest(MANIFEST_PATH) == 30
