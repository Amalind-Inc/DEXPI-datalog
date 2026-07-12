"""Reasoning-architecture benchmark package (bead pydexpi-datalog-1-3q1).

The seam every benchmark arm plugs into: the StructuredAnswer contract,
pre-committed GroundTruth, and the pure-function grader.
"""

from pydexpi_datalog.benchmark.contract import (
    POSTURE_GENERAL_KNOWLEDGE,
    POSTURE_OUT_OF_SCOPE,
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    POSTURE_UNSPECIFIED,
    POSTURES,
    SOURCE_CONCLUSION_VERDICTS,
    VERDICT_NO_VIOLATION,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    VERDICTS,
    GroundTruth,
    StructuredAnswer,
)
from pydexpi_datalog.benchmark.grader import Grade, grade, known_node_ids
from pydexpi_datalog.benchmark.dataset import (
    DATASET_SCHEMA_VERSION,
    SLICES,
    SLICE_HAND_AUTHORED,
    SLICE_SYNTHETIC,
    SLICE_TRAP,
    BenchmarkDataset,
    BenchmarkQuestion,
    DatasetManifestError,
    load_question_manifest,
)

__all__ = [
    "BenchmarkDataset",
    "BenchmarkQuestion",
    "DATASET_SCHEMA_VERSION",
    "DatasetManifestError",
    "Grade",
    "GroundTruth",
    "SLICES",
    "SLICE_HAND_AUTHORED",
    "SLICE_SYNTHETIC",
    "SLICE_TRAP",
    "POSTURE_GENERAL_KNOWLEDGE",
    "POSTURE_OUT_OF_SCOPE",
    "POSTURE_SOURCE_DATA_UNAVAILABLE",
    "POSTURE_SOURCE_GROUNDED",
    "POSTURE_UNSPECIFIED",
    "POSTURES",
    "SOURCE_CONCLUSION_VERDICTS",
    "StructuredAnswer",
    "VERDICT_NO_VIOLATION",
    "VERDICT_UNANSWERABLE",
    "VERDICT_VIOLATION_FOUND",
    "VERDICTS",
    "grade",
    "known_node_ids",
    "load_question_manifest",
]
