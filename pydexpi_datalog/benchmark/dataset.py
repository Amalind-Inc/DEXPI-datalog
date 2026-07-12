"""Data-only dataset manifests for the reasoning-architecture benchmark.

The loader is the trust boundary between checked-in question data and benchmark
execution.  It resolves each drawing reference, reads its canonical base fact
layer, and rejects invalid ground truth before an arm can run.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pydexpi_datalog.benchmark.contract import GroundTruth, VERDICTS
from pydexpi_datalog.benchmark.grader import known_node_ids


DATASET_SCHEMA_VERSION = 1
SLICE_HAND_AUTHORED = "hand_authored"
SLICE_SYNTHETIC = "synthetic"
SLICE_TRAP = "trap"
SLICES = (SLICE_HAND_AUTHORED, SLICE_SYNTHETIC, SLICE_TRAP)


class DatasetManifestError(ValueError):
    """A data manifest cannot safely be used for a benchmark run."""


@dataclass(frozen=True)
class BenchmarkQuestion:
    """One pre-committed benchmark question loaded from data."""

    question_id: str
    question: str
    slice: str
    drawing_ref: Path
    ground_truth: GroundTruth


@dataclass(frozen=True)
class BenchmarkDataset:
    """The validated, immutable question set loaded from one manifest."""

    questions: tuple[BenchmarkQuestion, ...]


def load_question_manifest(path: Path) -> BenchmarkDataset:
    """Load a JSON question manifest and fail before any invalid arm run.

    A ``drawing`` may name ``graph_facts.json`` directly or a drawing bundle
    directory containing that file.  The retained ``drawing_ref`` is the
    manifest's resolved reference, while validation always reads the canonical
    base fact layer at the reference.
    """
    manifest_path = path.resolve()
    raw_manifest = _read_json_object(
        manifest_path,
        error_prefix="Dataset manifest",
    )

    schema_version = raw_manifest.get("schema_version")
    if schema_version != DATASET_SCHEMA_VERSION:
        raise DatasetManifestError(
            "Dataset manifest has invalid schema_version: "
            f"expected {DATASET_SCHEMA_VERSION}, got {schema_version!r}."
        )

    raw_questions = raw_manifest.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise DatasetManifestError(
            "Dataset manifest has invalid questions: expected a non-empty list."
        )

    questions: list[BenchmarkQuestion] = []
    seen_question_ids: set[str] = set()
    for index, raw_question in enumerate(raw_questions):
        question = _load_question(
            raw_question=raw_question,
            manifest_path=manifest_path,
            index=index,
        )
        if question.question_id in seen_question_ids:
            raise DatasetManifestError(
                f"Dataset entry {question.question_id!r} has invalid id: duplicate question ID."
            )
        seen_question_ids.add(question.question_id)
        questions.append(question)

    return BenchmarkDataset(questions=tuple(questions))


def _load_question(
    *, raw_question: object, manifest_path: Path, index: int
) -> BenchmarkQuestion:
    if not isinstance(raw_question, dict):
        raise DatasetManifestError(
            f"Dataset entry at index {index} must be an object."
        )

    question_id = _required_string(raw_question, "id", f"entry at index {index}")
    question = _required_string(raw_question, "question", f"entry {question_id!r}")
    slice_name = _required_string(raw_question, "slice", f"entry {question_id!r}")
    if slice_name not in SLICES:
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has invalid slice {slice_name!r}; "
            f"expected one of {list(SLICES)!r}."
        )

    drawing_value = _required_string(raw_question, "drawing", f"entry {question_id!r}")
    drawing_ref = _resolve_drawing_ref(
        manifest_path=manifest_path,
        drawing_value=drawing_value,
        question_id=question_id,
    )
    graph_facts = _load_canonical_base_fact_layer(
        drawing_ref=drawing_ref,
        question_id=question_id,
    )

    raw_ground_truth = raw_question.get("ground_truth")
    if not isinstance(raw_ground_truth, dict):
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has invalid ground_truth: expected an object."
        )
    verdict = _required_string(
        raw_ground_truth,
        "verdict",
        f"entry {question_id!r} ground_truth",
    )
    if verdict not in VERDICTS:
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has invalid ground_truth.verdict "
            f"{verdict!r}; expected one of {list(VERDICTS)!r}."
        )

    witness_ids = _optional_witness_ids(
        raw_ground_truth=raw_ground_truth,
        question_id=question_id,
    )
    known_ids = known_node_ids(graph_facts)
    unknown_ids = sorted(set(witness_ids) - known_ids)
    if unknown_ids:
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has unknown witness ID "
            f"{unknown_ids[0]!r} in ground_truth.witness_ids."
        )

    return BenchmarkQuestion(
        question_id=question_id,
        question=question,
        slice=slice_name,
        drawing_ref=drawing_ref,
        ground_truth=GroundTruth(verdict=verdict, witness_ids=witness_ids),
    )


def _required_string(raw: dict[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DatasetManifestError(
            f"Dataset {context} has invalid {field}: expected a non-empty string."
        )
    return value


def _optional_witness_ids(
    *, raw_ground_truth: dict[str, object], question_id: str
) -> tuple[str, ...]:
    raw_witness_ids = raw_ground_truth.get("witness_ids", [])
    if not isinstance(raw_witness_ids, list) or any(
        not isinstance(witness_id, str) or not witness_id.strip()
        for witness_id in raw_witness_ids
    ):
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has invalid ground_truth.witness_ids: "
            "expected a list of non-empty strings."
        )
    return tuple(raw_witness_ids)


def _resolve_drawing_ref(
    *, manifest_path: Path, drawing_value: str, question_id: str
) -> Path:
    raw_ref = Path(drawing_value).expanduser()
    drawing_ref = raw_ref if raw_ref.is_absolute() else manifest_path.parent / raw_ref
    drawing_ref = drawing_ref.resolve()
    graph_facts_path = _graph_facts_path(drawing_ref)
    if not graph_facts_path.is_file():
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} has dangling drawing reference "
            f"{drawing_value!r}: expected canonical base fact layer at {graph_facts_path}."
        )
    return drawing_ref


def _load_canonical_base_fact_layer(
    *, drawing_ref: Path, question_id: str
) -> dict[str, object]:
    graph_facts_path = _graph_facts_path(drawing_ref)
    graph_facts = _read_json_object(
        graph_facts_path,
        error_prefix=f"Dataset entry {question_id!r} drawing",
    )
    facts = graph_facts.get("facts")
    if not isinstance(facts, dict) or not isinstance(facts.get("nodes"), list):
        raise DatasetManifestError(
            f"Dataset entry {question_id!r} drawing {graph_facts_path} is not a "
            "canonical base fact layer with facts.nodes."
        )
    return graph_facts


def _graph_facts_path(drawing_ref: Path) -> Path:
    return drawing_ref / "graph_facts.json" if drawing_ref.is_dir() else drawing_ref


def _read_json_object(path: Path, *, error_prefix: str) -> dict[str, object]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DatasetManifestError(f"{error_prefix} cannot be read at {path}: {error}") from error

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise DatasetManifestError(
            f"{error_prefix} is not valid JSON at {path}: {error.msg}."
        ) from error
    if not isinstance(raw, dict):
        raise DatasetManifestError(f"{error_prefix} at {path} must be a JSON object.")
    return raw
