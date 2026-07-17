"""Frozen evaluation-slice materialization for the RMSO feasibility spike."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydexpi_datalog.benchmark.dataset import DATASET_SCHEMA_VERSION


RMSO_EVAL_LOCK_SCHEMA_VERSION = 1
RMSO_PROTOCOL_BEAD = "pydexpi-datalog-1-rmso.4"
RMSO_CERTIFICATION_BEAD = "pydexpi-datalog-1-rmso.7"
RMSO_CERTIFICATION_STATUS = "product_owner_sme_approved"
_RMSO_EVAL_BUDGETS = {
    "max_turns": 64,
    "max_commands": 128,
    "max_output_tokens": 8192,
    "agent_timeout_sec": 300.0,
    "verifier_timeout_sec": 60.0,
}

RMSO_EVAL_ENTRIES = (
    ("ha-e03-pump-p4713-retrieval", "hand_authored"),
    ("hq-nozzle-piping-attachment-small", "harder_questions"),
    ("hq-nozzle-piping-attachment-large", "harder_questions"),
    ("hq-valve-monitoring-reachability-small", "harder_questions"),
    ("hq-valve-monitoring-reachability-large", "harder_questions"),
    ("hq-equipment-pump-connectivity-small", "harder_questions"),
    ("hq-equipment-pump-connectivity-large", "harder_questions"),
    ("hq-permission-defeasible-control-small", "harder_questions"),
    ("hq-permission-defeasible-control-large", "harder_questions"),
)


class RMSOEvalLockError(ValueError):
    """The preregistered RMSO evaluation lock cannot be trusted."""


def materialize_preregistered_rmso_manifest(
    lock_path: Path, output_path: Path
) -> Path:
    """Materialize the locked RMSO slice from its certified source manifests.

    The checked-in lock owns selection and ordering but not mutable copies of
    ground truth.  Each question is copied from a hash-pinned source manifest,
    and drawing references are rebased to absolute paths so the generated run
    manifest remains valid outside ``testdata/benchmark``.
    """
    lock_path = lock_path.resolve()
    output_path = output_path.resolve()
    lock = _read_object(lock_path, "RMSO evaluation lock")
    _validate_lock_header(lock, lock_path)

    source_questions: dict[str, dict[str, dict[str, Any]]] = {}
    source_paths: dict[str, Path] = {}
    frozen_sources: list[dict[str, str]] = []
    raw_sources = lock.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise RMSOEvalLockError("RMSO evaluation lock requires non-empty sources.")
    for raw_source in raw_sources:
        source_key, source_path, expected_hash = _load_source_spec(
            raw_source, lock_path
        )
        if source_key in source_questions:
            raise RMSOEvalLockError(
                f"RMSO evaluation lock has duplicate source key {source_key!r}."
            )
        actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise RMSOEvalLockError(
                f"Source manifest {source_path} failed SHA-256 validation: "
                f"expected {expected_hash}, got {actual_hash}."
            )
        source_manifest = _read_object(source_path, f"Source manifest {source_path}")
        if source_manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
            raise RMSOEvalLockError(
                f"Source manifest {source_path} has unsupported schema_version."
            )
        source_questions[source_key] = _index_questions(source_manifest, source_path)
        source_paths[source_key] = source_path
        frozen_sources.append(
            {"key": source_key, "path": str(source_path), "sha256": expected_hash}
        )

    raw_entries = lock.get("entries")
    actual_entries = _load_entry_specs(raw_entries)
    if actual_entries != RMSO_EVAL_ENTRIES:
        raise RMSOEvalLockError(
            "RMSO evaluation lock entries do not match the preregistered nine-entry "
            "order."
        )

    selected: list[dict[str, Any]] = []
    for question_id, source_key in actual_entries:
        try:
            raw_question = source_questions[source_key][question_id]
        except KeyError:
            raise RMSOEvalLockError(
                f"Locked entry {question_id!r} is absent from source {source_key!r}."
            ) from None
        question = dict(raw_question)
        source_path = source_paths[source_key]
        drawing = question.get("drawing")
        if not isinstance(drawing, str) or not drawing:
            raise RMSOEvalLockError(
                f"Locked entry {question_id!r} has an invalid drawing reference."
            )
        question["drawing"] = str((source_path.parent / drawing).resolve())
        selected.append(question)

    frozen_protocol = dict(lock["protocol"])
    frozen_protocol["document"] = str(
        (lock_path.parent / frozen_protocol["document"]).resolve()
    )
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "rmso_lock": {
            "schema_version": RMSO_EVAL_LOCK_SCHEMA_VERSION,
            "path": str(lock_path),
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            "protocol_bead": RMSO_PROTOCOL_BEAD,
            "protocol": frozen_protocol,
            "certification": lock["certification"],
            "sources": frozen_sources,
        },
        "episode_budgets": lock["episode_budgets"],
        "questions": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = output_path.with_name(f".{output_path.name}.tmp")
    staging_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    staging_path.replace(output_path)
    return output_path


def _validate_lock_header(lock: dict[str, Any], lock_path: Path) -> None:
    if lock.get("schema_version") != RMSO_EVAL_LOCK_SCHEMA_VERSION:
        raise RMSOEvalLockError("RMSO evaluation lock has an invalid schema_version.")
    protocol = lock.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("bead") != RMSO_PROTOCOL_BEAD:
        raise RMSOEvalLockError("RMSO evaluation lock has an invalid protocol bead.")
    protocol_document = protocol.get("document")
    protocol_hash = protocol.get("sha256")
    if not isinstance(protocol_document, str) or not isinstance(protocol_hash, str):
        raise RMSOEvalLockError("RMSO evaluation lock must hash its protocol document.")
    protocol_path = (lock_path.parent / protocol_document).resolve()
    try:
        actual_protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    except OSError as error:
        raise RMSOEvalLockError(
            f"RMSO protocol document is unreadable: {protocol_path}."
        ) from error
    if actual_protocol_hash != protocol_hash:
        raise RMSOEvalLockError(
            f"RMSO protocol document failed SHA-256 validation: expected "
            f"{protocol_hash}, got {actual_protocol_hash}."
        )
    certification = lock.get("certification")
    if (
        not isinstance(certification, dict)
        or certification.get("bead") != RMSO_CERTIFICATION_BEAD
        or certification.get("status") != RMSO_CERTIFICATION_STATUS
        or not isinstance(certification.get("approved_on"), str)
        or not certification["approved_on"]
    ):
        raise RMSOEvalLockError(
            "RMSO evaluation lock lacks required product-owner SME certification."
        )
    budgets = lock.get("episode_budgets")
    if budgets != _RMSO_EVAL_BUDGETS:
        raise RMSOEvalLockError(
            "RMSO evaluation lock episode_budgets do not match the preregistered "
            "limits."
        )


def _load_source_spec(
    raw_source: object, lock_path: Path
) -> tuple[str, Path, str]:
    if not isinstance(raw_source, dict):
        raise RMSOEvalLockError("Each RMSO source specification must be an object.")
    source_key = raw_source.get("key")
    path_value = raw_source.get("path")
    expected_hash = raw_source.get("sha256")
    if not isinstance(source_key, str) or not source_key:
        raise RMSOEvalLockError("Each RMSO source requires a non-empty key.")
    if not isinstance(path_value, str) or not path_value:
        raise RMSOEvalLockError(f"RMSO source {source_key!r} requires a path.")
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_hash)
    ):
        raise RMSOEvalLockError(
            f"RMSO source {source_key!r} requires a lowercase SHA-256 digest."
        )
    source_path = (lock_path.parent / path_value).resolve()
    if not source_path.is_file():
        raise RMSOEvalLockError(f"RMSO source manifest does not exist: {source_path}.")
    return source_key, source_path, expected_hash


def _index_questions(
    source_manifest: dict[str, Any], source_path: Path
) -> dict[str, dict[str, Any]]:
    raw_questions = source_manifest.get("questions")
    if not isinstance(raw_questions, list):
        raise RMSOEvalLockError(f"Source manifest {source_path} has invalid questions.")
    indexed: dict[str, dict[str, Any]] = {}
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            raise RMSOEvalLockError(
                f"Source manifest {source_path} contains a non-object question."
            )
        question_id = raw_question.get("id")
        if not isinstance(question_id, str) or not question_id:
            raise RMSOEvalLockError(
                f"Source manifest {source_path} contains a question without an ID."
            )
        if question_id in indexed:
            raise RMSOEvalLockError(
                f"Source manifest {source_path} has duplicate ID {question_id!r}."
            )
        indexed[question_id] = raw_question
    return indexed


def _load_entry_specs(raw_entries: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw_entries, list):
        raise RMSOEvalLockError("RMSO evaluation lock entries must be a list.")
    entries: list[tuple[str, str]] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise RMSOEvalLockError("Each RMSO evaluation entry must be an object.")
        question_id = raw_entry.get("id")
        source_key = raw_entry.get("source")
        if not isinstance(question_id, str) or not isinstance(source_key, str):
            raise RMSOEvalLockError(
                "Each RMSO evaluation entry requires string id and source fields."
            )
        if "ground_truth" in raw_entry:
            raise RMSOEvalLockError(
                f"RMSO lock entry {question_id!r} must not duplicate ground truth."
            )
        entries.append((question_id, source_key))
    return tuple(entries)


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RMSOEvalLockError(f"{label} is unreadable: {error}.") from error
    if not isinstance(raw, dict):
        raise RMSOEvalLockError(f"{label} must be a JSON object.")
    return raw
