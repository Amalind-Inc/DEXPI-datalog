"""Behavior tests for the synthetic truth-by-construction slice (3q1.11).

The generator produces drawings across a declared graph-size sweep with
injected violations whose ground truth follows from construction - no hand
labeling. Every drawing ships as a bundle-layout directory (minimal XML
wrapper + canonical base fact layer + NetworkX export + README) consumable
by every arm, and the manifest is loader-valid with a size bucket per entry.
"""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark import (
    SIZE_BUCKETS,
    SLICE_SYNTHETIC,
    SYNTHETIC_FIDELITY_LIMIT,
    SYNTHETIC_MANIFEST_FILENAME,
    generate_synthetic_slice,
    load_question_manifest,
)
from pydexpi_datalog.benchmark.agentic_arm import BUNDLE_FILES, validate_bundle
from pydexpi_datalog.cli.cli import main as cli_main


@pytest.fixture(scope="module")
def slice_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("synthetic-slice")
    generate_synthetic_slice(output_dir=output_dir)
    return output_dir


@pytest.fixture(scope="module")
def manifest_path(slice_dir: Path) -> Path:
    return slice_dir / SYNTHETIC_MANIFEST_FILENAME


# --------------------------------------------------------------------------
# ~30 loader-valid entries, ground truth from construction
# --------------------------------------------------------------------------


def test_manifest_is_loader_valid_with_about_thirty_questions(
    manifest_path: Path,
) -> None:
    dataset = load_question_manifest(manifest_path)
    assert len(dataset.questions) == 30
    assert all(q.slice == SLICE_SYNTHETIC for q in dataset.questions)


def test_ground_truth_mixes_verdicts_within_every_bucket(
    manifest_path: Path,
) -> None:
    dataset = load_question_manifest(manifest_path)
    for bucket in SIZE_BUCKETS:
        verdicts = {
            q.ground_truth.verdict
            for q in dataset.questions
            if q.size_bucket == bucket
        }
        assert verdicts == {"violation_found", "no_violation"}


def test_violation_witnesses_are_constructed_pump_nodes(
    manifest_path: Path,
) -> None:
    dataset = load_question_manifest(manifest_path)
    violating = [
        q
        for q in dataset.questions
        if q.ground_truth.verdict == "violation_found"
    ]
    assert violating
    for question in violating:
        assert question.ground_truth.witness_ids
        graph_facts = json.loads(
            (question.drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        labels = {
            node["node_id"]: node["attributes"]["label"]
            for node in graph_facts["facts"]["nodes"]
        }
        for witness_id in question.ground_truth.witness_ids:
            assert labels[witness_id] == "CentrifugalPump"


def test_no_violation_entries_carry_no_witnesses(manifest_path: Path) -> None:
    dataset = load_question_manifest(manifest_path)
    clean = [
        q for q in dataset.questions if q.ground_truth.verdict == "no_violation"
    ]
    assert clean
    assert all(q.ground_truth.witness_ids == () for q in clean)


# --------------------------------------------------------------------------
# Declared size sweep, recorded per entry
# --------------------------------------------------------------------------


def test_every_entry_records_a_declared_size_bucket(manifest_path: Path) -> None:
    dataset = load_question_manifest(manifest_path)
    buckets = {q.size_bucket for q in dataset.questions}
    assert buckets == set(SIZE_BUCKETS)


def test_graph_size_grows_across_the_sweep(manifest_path: Path) -> None:
    dataset = load_question_manifest(manifest_path)
    node_counts: dict[str, set[int]] = {bucket: set() for bucket in SIZE_BUCKETS}
    for question in dataset.questions:
        graph_facts = json.loads(
            (question.drawing_ref / "graph_facts.json").read_text(encoding="utf-8")
        )
        assert question.size_bucket is not None
        node_counts[question.size_bucket].add(graph_facts["graph"]["node_count"])
    assert max(node_counts["small"]) < min(node_counts["medium"])
    assert max(node_counts["medium"]) < min(node_counts["large"])


# --------------------------------------------------------------------------
# Bundle layout consumable by every arm
# --------------------------------------------------------------------------


def test_each_drawing_is_a_valid_bundle_with_xml_and_facts(
    manifest_path: Path,
) -> None:
    dataset = load_question_manifest(manifest_path)
    drawing_refs = {q.drawing_ref for q in dataset.questions}
    for drawing_ref in drawing_refs:
        bundle_dir = validate_bundle(drawing_ref)
        for name in BUNDLE_FILES:
            assert (bundle_dir / name).is_file()
        graph_facts = json.loads(
            (bundle_dir / "graph_facts.json").read_text(encoding="utf-8")
        )
        root = ET.parse(bundle_dir / "drawing.xml").getroot()
        xml_nodes = root.findall(".//Node")
        xml_edges = root.findall(".//Edge")
        assert len(xml_nodes) == graph_facts["graph"]["node_count"]
        assert len(xml_edges) == graph_facts["graph"]["edge_count"]
        networkx_payload = json.loads(
            (bundle_dir / "graph.json").read_text(encoding="utf-8")
        )
        assert len(networkx_payload["nodes"]) == graph_facts["graph"]["node_count"]


def test_generation_is_deterministic_across_every_artifact(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    generate_synthetic_slice(output_dir=first_dir)
    generate_synthetic_slice(output_dir=second_dir)
    first_files = sorted(
        path.relative_to(first_dir) for path in first_dir.rglob("*") if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second_dir)
        for path in second_dir.rglob("*")
        if path.is_file()
    )
    assert first_files == second_files
    for relative in first_files:
        assert (first_dir / relative).read_bytes() == (
            second_dir / relative
        ).read_bytes(), f"non-deterministic artifact: {relative}"


def test_generated_bundles_feed_the_souffle_arm_task_builder(
    manifest_path: Path, tmp_path: Path
) -> None:
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets
    from pydexpi_datalog.benchmark.souffle_arm import build_souffle_harbor_task

    dataset = load_question_manifest(manifest_path)
    question = dataset.questions[0]
    task_dir = build_souffle_harbor_task(
        question=question,
        drawing_ref=question.drawing_ref,
        output_dir=tmp_path,
        budgets=EpisodeBudgets(),
    )
    assert (task_dir / "environment" / "graph_facts.dl").is_file()
    assert (task_dir / "environment" / "drawing.xml").is_file()


# --------------------------------------------------------------------------
# XML-wrapper fallback fidelity limit is citable
# --------------------------------------------------------------------------


def test_manifest_documents_the_xml_wrapper_fidelity_limit(
    manifest_path: Path,
) -> None:
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fidelity = raw_manifest["fidelity"]
    assert fidelity["mode"] == "xml_graph_wrapper"
    assert fidelity["limit"] == SYNTHETIC_FIDELITY_LIMIT
    assert "not" in SYNTHETIC_FIDELITY_LIMIT and "DEXPI" in SYNTHETIC_FIDELITY_LIMIT


def test_fidelity_limit_survives_manifest_loading(manifest_path: Path) -> None:
    dataset = load_question_manifest(manifest_path)
    assert dataset.fidelity is not None
    assert dataset.fidelity.mode == "xml_graph_wrapper"
    assert dataset.fidelity.limit == SYNTHETIC_FIDELITY_LIMIT


def test_datasets_without_fidelity_note_load_as_before(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    e06_graph_facts = (
        repo_root / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
    )
    node_id = json.loads(e06_graph_facts.read_text(encoding="utf-8"))["facts"][
        "nodes"
    ][0]["node_id"]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "questions": [
                    {
                        "id": "plain",
                        "question": "Is any pump missing a check valve?",
                        "slice": "hand_authored",
                        "drawing": str(e06_graph_facts),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": [node_id],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    dataset = load_question_manifest(manifest)
    assert dataset.fidelity is None
    assert dataset.questions[0].size_bucket is None


def test_bundle_readme_carries_a_consistent_fidelity_account(
    manifest_path: Path,
) -> None:
    dataset = load_question_manifest(manifest_path)
    readme = (
        dataset.questions[0].drawing_ref / "README.md"
    ).read_text(encoding="utf-8")
    assert SYNTHETIC_FIDELITY_LIMIT in readme
    # One non-contradictory provenance account: the wrapper must never be
    # described as an original DEXPI export.
    assert "original DEXPI source drawing" not in readme
    assert "SyntheticGraphDrawing XML wrapper" in readme


# --------------------------------------------------------------------------
# CLI vertical slice
# --------------------------------------------------------------------------


def test_cli_generates_a_loadable_slice(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "cli-slice"
    exit_code = cli_main(["synthetic-slice", "--output-dir", str(output_dir)])
    assert exit_code == 0
    dataset = load_question_manifest(output_dir / SYNTHETIC_MANIFEST_FILENAME)
    assert len(dataset.questions) == 30
    report = capsys.readouterr().out
    assert "30" in report


# --------------------------------------------------------------------------
# Truth by construction, cross-checked against the real engine
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle binary not on PATH"
)
def test_constructed_truth_matches_real_souffle_rule_output(
    manifest_path: Path,
) -> None:
    from pydexpi_datalog.semantics.derive_graph_semantics import (
        build_graph_facts_datalog,
        load_graph_topology_idb,
    )
    from pydexpi_datalog.semantics.souffle_runner import run_souffle_program
    from pydexpi_datalog.verification.souffle_rule_pack import (
        load_diameter_rule_datalog,
        load_rule_datalog,
    )

    dataset = load_question_manifest(manifest_path)
    rule_programs = {
        "check-valve": (load_rule_datalog(), "walk_boundary"),
        "diameter": (load_diameter_rule_datalog(), "diameter_violated"),
    }
    relations_by_drawing: dict[tuple[Path, str], dict[str, list]] = {}
    for question in dataset.questions:
        kind = "check-valve" if "check valve" in question.question else "diameter"
        rule_datalog, _ = rule_programs[kind]
        cache_key = (question.drawing_ref, kind)
        if cache_key not in relations_by_drawing:
            graph_facts = json.loads(
                (question.drawing_ref / "graph_facts.json").read_text(
                    encoding="utf-8"
                )
            )
            program = (
                build_graph_facts_datalog(graph_facts)
                + "\n"
                + load_graph_topology_idb()
                + "\n"
                + rule_datalog
            )
            relations_by_drawing[cache_key] = run_souffle_program(program)
        relations = relations_by_drawing[cache_key]

        if kind == "check-valve":
            engine_violators = sorted(
                {
                    pump
                    for pump, _step, _object, boundary_kind in relations.get(
                        "walk_boundary", []
                    )
                    if boundary_kind == "terminal_object"
                }
            )
        else:
            engine_violators = sorted(
                {pump for pump, _object, _dn in relations.get("diameter_violated", [])}
            )
        assert engine_violators == sorted(question.ground_truth.witness_ids), (
            f"{question.question_id}: constructed truth disagrees with engine"
        )
        assert not relations.get("rule_unresolved"), (
            f"{question.question_id}: synthetic drawing must be rule-resolvable"
        )
