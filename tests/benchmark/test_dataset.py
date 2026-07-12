from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark import (
    DatasetManifestError,
    VERDICT_UNANSWERABLE,
    load_question_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MANIFEST = REPO_ROOT / "testdata" / "benchmark" / "sample_training_manifest.json"
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)
E06_SOURCE = (
    REPO_ROOT
    / "TrainingTestCases"
    / "dexpi 1.3"
    / "example pids"
    / "E06 Pump, HeatExchanger, Nozzles Connected With PNS"
    / "E06V01-VER.EX01.xml"
)


def test_checked_in_manifest_loads_a_trap_over_the_e06_training_fixture() -> None:
    """The sample uses the E06 fixture's canonical base fact layer."""
    dataset = load_question_manifest(SAMPLE_MANIFEST)

    assert len(dataset.questions) == 1
    question = dataset.questions[0]
    assert question.question_id == "e06-approval-date"
    assert question.slice == "trap"
    assert question.drawing_ref == E06_GRAPH_FACTS
    assert E06_SOURCE.is_file()
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    assert graph_facts["source_path"] == str(E06_SOURCE)
    assert question.ground_truth.verdict == VERDICT_UNANSWERABLE
    assert question.ground_truth.witness_ids == ()


def write_graph_facts(tmp_path: Path, node_ids: list[str]) -> Path:
    graph_facts_path = tmp_path / "drawing" / "graph_facts.json"
    graph_facts_path.parent.mkdir()
    graph_facts_path.write_text(
        json.dumps(
            {
                "facts": {
                    "nodes": [
                        {"fact_type": "node", "node_id": node_id, "attributes": {}}
                        for node_id in node_ids
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return graph_facts_path


def write_manifest(tmp_path: Path, questions: list[dict[str, object]]) -> Path:
    manifest_path = tmp_path / "questions.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "questions": questions}),
        encoding="utf-8",
    )
    return manifest_path


def question_data(
    *,
    question_id: str,
    slice_name: str,
    drawing: str = "drawing/graph_facts.json",
    ground_truth: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": question_id,
        "question": "Does this fixture satisfy the stated condition?",
        "slice": slice_name,
        "drawing": drawing,
        "ground_truth": ground_truth
        if ground_truth is not None
        else {"verdict": "no_violation", "witness_ids": []},
    }


def test_manifest_supports_all_slices_and_grounded_witnesses(tmp_path: Path) -> None:
    """Hand-authored, synthetic, and trap data share one loadable contract."""
    write_graph_facts(tmp_path, ["P-101", "CV-201"])
    manifest_path = write_manifest(
        tmp_path,
        [
            question_data(
                question_id="hand-authored",
                slice_name="hand_authored",
                ground_truth={"verdict": "no_violation", "witness_ids": ["P-101"]},
            ),
            question_data(
                question_id="synthetic",
                slice_name="synthetic",
                ground_truth={"verdict": "violation_found", "witness_ids": ["CV-201"]},
            ),
            question_data(
                question_id="trap",
                slice_name="trap",
                ground_truth={"verdict": "unanswerable"},
            ),
        ],
    )

    dataset = load_question_manifest(manifest_path)

    assert [question.slice for question in dataset.questions] == [
        "hand_authored",
        "synthetic",
        "trap",
    ]
    assert dataset.questions[2].ground_truth.witness_ids == ()


def test_manifest_rejects_unknown_witness_with_entry_and_id_diagnostic(
    tmp_path: Path,
) -> None:
    """A witness that the drawing cannot identify is never benchmark ground truth."""
    write_graph_facts(tmp_path, ["P-101"])
    manifest_path = write_manifest(
        tmp_path,
        [
            question_data(
                question_id="unknown-witness",
                slice_name="hand_authored",
                ground_truth={
                    "verdict": "violation_found",
                    "witness_ids": ["does-not-exist"],
                },
            )
        ],
    )

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'unknown-witness'.+unknown witness ID 'does-not-exist'",
    ):
        load_question_manifest(manifest_path)


def test_manifest_rejects_ground_truth_without_a_verdict(tmp_path: Path) -> None:
    """Ground truth must state the outcome that an arm will be graded against."""
    write_graph_facts(tmp_path, ["P-101"])
    manifest_path = write_manifest(
        tmp_path,
        [
            question_data(
                question_id="missing-verdict",
                slice_name="hand_authored",
                ground_truth={"witness_ids": ["P-101"]},
            )
        ],
    )

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'missing-verdict' ground_truth has invalid verdict",
    ):
        load_question_manifest(manifest_path)


def test_manifest_rejects_invalid_slice_tag(tmp_path: Path) -> None:
    """An unclassified entry cannot silently land in the wrong report bucket."""
    write_graph_facts(tmp_path, ["P-101"])
    manifest_path = write_manifest(
        tmp_path,
        [question_data(question_id="invalid-slice", slice_name="not-a-slice")],
    )

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'invalid-slice'.+invalid slice 'not-a-slice'",
    ):
        load_question_manifest(manifest_path)


def test_manifest_rejects_dangling_drawing_reference(tmp_path: Path) -> None:
    """Every manifest drawing reference resolves before an arm can execute."""
    manifest_path = write_manifest(
        tmp_path,
        [
            question_data(
                question_id="missing-drawing",
                slice_name="hand_authored",
                drawing="does-not-exist.json",
            )
        ],
    )

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'missing-drawing'.+dangling drawing reference 'does-not-exist.json'",
    ):
        load_question_manifest(manifest_path)


def test_manifest_rejects_entry_without_a_drawing_reference(tmp_path: Path) -> None:
    """A question cannot reach an arm unless its evidence source is named."""
    incomplete_entry = question_data(
        question_id="absent-drawing",
        slice_name="hand_authored",
    )
    del incomplete_entry["drawing"]
    manifest_path = write_manifest(tmp_path, [incomplete_entry])

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'absent-drawing' has invalid drawing",
    ):
        load_question_manifest(manifest_path)


def test_manifest_rejects_duplicate_question_ids(tmp_path: Path) -> None:
    """A report cannot silently merge two distinct entries under one identity."""
    write_graph_facts(tmp_path, ["P-101"])
    manifest_path = write_manifest(
        tmp_path,
        [
            question_data(question_id="duplicate", slice_name="hand_authored"),
            question_data(question_id="duplicate", slice_name="synthetic"),
        ],
    )

    with pytest.raises(
        DatasetManifestError,
        match=r"entry 'duplicate' has invalid id: duplicate question ID",
    ):
        load_question_manifest(manifest_path)
