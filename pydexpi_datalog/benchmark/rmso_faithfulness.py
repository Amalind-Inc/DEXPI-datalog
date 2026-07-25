"""Mechanical cross-size and counterfactual faithfulness gates for RMSO."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydexpi_datalog.benchmark.contract import (
    VERDICT_NO_VIOLATION,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
)
from pydexpi_datalog.benchmark.hand_authored import derive_ground_truth
from pydexpi_datalog.benchmark.souffle_arm import validate_faithfulness_program
from pydexpi_datalog.semantics.derive_graph_semantics import (
    build_graph_facts_datalog,
    load_graph_topology_idb,
)
from pydexpi_datalog.semantics.souffle_runner import (
    SouffleExecutionError,
    run_souffle_program,
)

FAITHFULNESS_SUITE_SCHEMA_VERSION = 1
_EXPECTED_FAMILIES = (
    (
        "nozzle_piping_attachment",
        "hq-nozzle-piping-attachment-small",
        "hq-nozzle-piping-attachment-large",
    ),
    (
        "valve_monitoring_reachability",
        "hq-valve-monitoring-reachability-small",
        "hq-valve-monitoring-reachability-large",
    ),
    (
        "equipment_pump_connectivity",
        "hq-equipment-pump-connectivity-small",
        "hq-equipment-pump-connectivity-large",
    ),
)
DEFAULT_FAITHFULNESS_PROBES_PATH = (
    Path(__file__).resolve().parents[2]
    / "testdata"
    / "benchmark"
    / "rmso_faithfulness_probes.json"
)


class FaithfulnessSuiteError(ValueError):
    """The frozen faithfulness suite or a submitted program is invalid."""


@dataclass(frozen=True)
class FaithfulnessCase:
    case_id: str
    question_id: str
    graph_facts: dict[str, object]
    expected: GroundTruth
    is_counterfactual: bool


@dataclass(frozen=True)
class FaithfulnessFamily:
    family_id: str
    small_question_id: str
    large_question_id: str
    cases: tuple[FaithfulnessCase, ...]


@dataclass(frozen=True)
class FaithfulnessSuite:
    source_path: Path
    source_sha256: str
    families: tuple[FaithfulnessFamily, ...]


@dataclass(frozen=True)
class FaithfulnessCaseResult:
    case_id: str
    expected_witness_ids: tuple[str, ...]
    actual_witness_ids: tuple[str, ...]
    passed: bool
    error: str | None = None


@dataclass(frozen=True)
class FaithfulnessReport:
    family_id: str
    passed: bool
    cases: tuple[FaithfulnessCaseResult, ...]


def load_faithfulness_suite(path: Path) -> FaithfulnessSuite:
    """Load and oracle-verify the frozen cross-size/counterfactual suite."""
    path = path.resolve()
    raw = _read_object(path, "Faithfulness probe manifest")
    if raw.get("schema_version") != FAITHFULNESS_SUITE_SCHEMA_VERSION:
        raise FaithfulnessSuiteError("Invalid faithfulness probe schema_version.")
    raw_source = raw.get("source")
    if not isinstance(raw_source, Mapping):
        raise FaithfulnessSuiteError("Faithfulness probe source must be an object.")
    source_value = raw_source.get("path")
    expected_hash = raw_source.get("sha256")
    if not isinstance(source_value, str) or not isinstance(expected_hash, str):
        raise FaithfulnessSuiteError(
            "Faithfulness probe source requires path and sha256."
        )
    source_path = (path.parent / source_value).resolve()
    try:
        actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError as error:
        raise FaithfulnessSuiteError(
            f"Cannot read probe source {source_path}."
        ) from error
    if actual_hash != expected_hash:
        raise FaithfulnessSuiteError(
            "Probe source SHA-256 mismatch: "
            f"expected {expected_hash}, got {actual_hash}."
        )
    source = _read_object(source_path, "Harder-question source manifest")
    raw_questions = source.get("questions")
    if not isinstance(raw_questions, list):
        raise FaithfulnessSuiteError("Harder-question source has invalid questions.")
    questions = {
        question.get("id"): question
        for question in raw_questions
        if isinstance(question, dict) and isinstance(question.get("id"), str)
    }

    raw_families = raw.get("families")
    if not isinstance(raw_families, list):
        raise FaithfulnessSuiteError("Faithfulness probe families must be a list.")
    identities = tuple(
        (
            family.get("id"),
            family.get("small_question_id"),
            family.get("large_question_id"),
        )
        for family in raw_families
        if isinstance(family, Mapping)
    )
    if identities != _EXPECTED_FAMILIES:
        raise FaithfulnessSuiteError(
            "Faithfulness families do not match the preregistered core pairs."
        )

    families: list[FaithfulnessFamily] = []
    for raw_family in raw_families:
        assert isinstance(raw_family, dict)
        family_id = str(raw_family["id"])
        small_id = str(raw_family["small_question_id"])
        large_id = str(raw_family["large_question_id"])
        cases = [
            _base_case(questions[small_id], source_path),
            _base_case(questions[large_id], source_path),
        ]
        raw_probes = raw_family.get("probes")
        if not isinstance(raw_probes, list) or len(raw_probes) != 2:
            raise FaithfulnessSuiteError(
                f"Faithfulness family {family_id!r} requires exactly two probes."
            )
        for raw_probe in raw_probes:
            cases.append(_probe_case(raw_probe, questions, source_path, family_id))
        families.append(
            FaithfulnessFamily(family_id, small_id, large_id, tuple(cases))
        )
    return FaithfulnessSuite(source_path, expected_hash, tuple(families))


def evaluate_faithfulness_program(
    program: str, family: FaithfulnessFamily
) -> FaithfulnessReport:
    """Replay one unchanged portable program across every family case."""
    results: list[FaithfulnessCaseResult] = []
    for case in family.cases:
        try:
            actual = replay_result_witness(program, case.graph_facts)
            expected = tuple(sorted(case.expected.witness_ids))
            inferred_verdict = (
                VERDICT_VIOLATION_FOUND if actual else VERDICT_NO_VIOLATION
            )
            passed = actual == expected and inferred_verdict == case.expected.verdict
            results.append(
                FaithfulnessCaseResult(case.case_id, expected, actual, passed)
            )
        except (SouffleExecutionError, FaithfulnessSuiteError) as error:
            detail = (
                error.detail
                if isinstance(error, SouffleExecutionError)
                else str(error)
            )
            results.append(
                FaithfulnessCaseResult(
                    case.case_id,
                    tuple(sorted(case.expected.witness_ids)),
                    (),
                    False,
                    detail or str(error),
                )
            )
    return FaithfulnessReport(
        family.family_id, all(result.passed for result in results), tuple(results)
    )


def replay_result_witness(
    program: str, graph_facts: Mapping[str, object]
) -> tuple[str, ...]:
    """Replay a portable query module against one frozen graph EDB."""
    validate_faithfulness_program(program)
    query_module = re.sub(
        r'^\s*\.include\s+"/input/(?:graph_facts|graph_topology_semantics)\.dl"\s*$',
        "",
        program,
        flags=re.MULTILINE,
    )
    complete_program = (
        build_graph_facts_datalog(dict(graph_facts))
        + "\n"
        + load_graph_topology_idb()
        + "\n"
        + query_module
    )
    relations = run_souffle_program(complete_program)
    if "result_witness" not in relations:
        raise FaithfulnessSuiteError("Program emitted no result_witness relation.")
    rows = relations["result_witness"]
    if any(len(row) != 1 for row in rows):
        raise FaithfulnessSuiteError("result_witness must have arity one.")
    return tuple(sorted({row[0] for row in rows}))


def run_preregistered_faithfulness_gate(
    program: str,
    question_id: str,
    *,
    probes_path: Path = DEFAULT_FAITHFULNESS_PROBES_PATH,
) -> dict[str, object] | None:
    """Run the applicable frozen gate; return ``None`` for non-core entries."""
    suite = load_faithfulness_suite(probes_path)
    for family in suite.families:
        if question_id in (family.small_question_id, family.large_question_id):
            return asdict(evaluate_faithfulness_program(program, family))
    return None


def _base_case(raw_question: dict[str, Any], source_path: Path) -> FaithfulnessCase:
    question_id = str(raw_question["id"])
    graph = _load_graph(raw_question, source_path)
    oracle = raw_question.get("oracle")
    if not isinstance(oracle, Mapping):
        raise FaithfulnessSuiteError(f"Question {question_id!r} has no oracle.")
    derived = derive_ground_truth(graph, oracle)
    declared = _ground_truth(raw_question.get("ground_truth"), question_id)
    if derived != declared:
        raise FaithfulnessSuiteError(f"Base oracle mismatch for {question_id!r}.")
    return FaithfulnessCase(question_id, question_id, graph, derived, False)


def _probe_case(
    raw_probe: object,
    questions: dict[object, dict[str, Any]],
    source_path: Path,
    family_id: str,
) -> FaithfulnessCase:
    if not isinstance(raw_probe, dict):
        raise FaithfulnessSuiteError(f"Family {family_id!r} has a non-object probe.")
    probe_id = raw_probe.get("id")
    question_id = raw_probe.get("base_question_id")
    if not isinstance(probe_id, str) or not isinstance(question_id, str):
        raise FaithfulnessSuiteError(f"Family {family_id!r} has an invalid probe.")
    question = questions.get(question_id)
    if question is None:
        raise FaithfulnessSuiteError(f"Probe {probe_id!r} has unknown base question.")
    graph = copy.deepcopy(_load_graph(question, source_path))
    _apply_mutations(graph, raw_probe, probe_id)
    oracle = question.get("oracle")
    assert isinstance(oracle, Mapping)
    derived = derive_ground_truth(graph, oracle)
    expected = _ground_truth(raw_probe.get("expected"), probe_id)
    if derived != expected:
        raise FaithfulnessSuiteError(
            f"Counterfactual oracle mismatch for {family_id}/{probe_id}: "
            f"declared {expected!r}, derived {derived!r}."
        )
    return FaithfulnessCase(
        f"{family_id}/{probe_id}", question_id, graph, derived, True
    )


def _apply_mutations(
    graph: dict[str, object], raw_probe: dict[str, Any], probe_id: str
) -> None:
    facts = graph.get("facts")
    if not isinstance(facts, dict):
        raise FaithfulnessSuiteError(f"Probe {probe_id!r} base graph has no facts.")
    nodes = facts.get("nodes")
    edges = facts.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise FaithfulnessSuiteError(f"Probe {probe_id!r} base graph is malformed.")
    raw_nodes = raw_probe.get("add_nodes", [])
    raw_edges = raw_probe.get("add_edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise FaithfulnessSuiteError(f"Probe {probe_id!r} mutations must be lists.")
    node_ids = {
        node.get("node_id") for node in nodes if isinstance(node, Mapping)
    }
    for node in raw_nodes:
        if not isinstance(node, Mapping):
            raise FaithfulnessSuiteError(
                f"Probe {probe_id!r} has invalid node mutation."
            )
        node_id = node.get("node_id")
        label = node.get("label")
        if (
            not isinstance(node_id, str)
            or not isinstance(label, str)
            or node_id in node_ids
        ):
            raise FaithfulnessSuiteError(
                f"Probe {probe_id!r} has invalid or duplicate added node."
            )
        node_ids.add(node_id)
        nodes.append(
            {
                "fact_type": "node",
                "node_id": node_id,
                "attributes": {"label": label},
            }
        )
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            raise FaithfulnessSuiteError(
                f"Probe {probe_id!r} has invalid edge mutation."
            )
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        edge_key = edge.get("edge_key")
        label = edge.get("label")
        attr_name = edge.get("attr_name")
        if (
            source_id not in node_ids
            or target_id not in node_ids
            or not isinstance(edge_key, (str, int))
            or isinstance(edge_key, bool)
            or not isinstance(label, str)
            or not isinstance(attr_name, str)
        ):
            raise FaithfulnessSuiteError(
                f"Probe {probe_id!r} has an invalid added edge."
            )
        edges.append(
            {
                "fact_type": "edge",
                "source_id": source_id,
                "target_id": target_id,
                "edge_key": edge_key,
                "attributes": {
                    "label": label,
                    "attr_name": attr_name,
                },
            }
        )


def _load_graph(
    raw_question: Mapping[str, object], source_path: Path
) -> dict[str, object]:
    drawing = raw_question.get("drawing")
    if not isinstance(drawing, str):
        raise FaithfulnessSuiteError("Question has invalid drawing reference.")
    drawing_path = (source_path.parent / drawing).resolve()
    graph_path = (
        drawing_path / "graph_facts.json" if drawing_path.is_dir() else drawing_path
    )
    return _read_object(graph_path, f"Graph facts {graph_path}")


def _ground_truth(raw: object, context: str) -> GroundTruth:
    if not isinstance(raw, Mapping):
        raise FaithfulnessSuiteError(f"{context!r} has invalid expected ground truth.")
    verdict = raw.get("verdict")
    witnesses = raw.get("witness_ids", [])
    if not isinstance(verdict, str) or not isinstance(witnesses, list) or not all(
        isinstance(witness, str) for witness in witnesses
    ):
        raise FaithfulnessSuiteError(f"{context!r} has invalid expected ground truth.")
    return GroundTruth(verdict, tuple(sorted(witnesses)))


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FaithfulnessSuiteError(f"{label} is unreadable: {error}.") from error
    if not isinstance(raw, dict):
        raise FaithfulnessSuiteError(f"{label} must be a JSON object.")
    return raw
