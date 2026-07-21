"""Behavior tests for the Arm T prebuilt Datalog template pack (lx6p).

The model's only authored surface is a routing JSON; these tests pin the
mechanical guarantees the design lock promises: routing bindings are validated
against the drawing plus explicit question scope, rendered programs contain
only frozen template bodies and validated bindings, and rendered programs
execute end-to-end on the real engine.
"""

from __future__ import annotations

from dataclasses import replace
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark.template_arm import (
    TEMPLATE_PACK,
    render_program,
    routing_vocabulary,
    validate_routing,
)
import pydexpi_datalog.benchmark.template_arm as template_arm_module
from pydexpi_datalog.benchmark.template_arm_task import (
    RMSO_ROUTE_QUERY_HELPER,
    ROUTE_TRACE_FILENAME,
    ROUTING_FILENAME,
    VALIDATION_RETRY_BUDGET,
    build_rmso_template_harbor_task,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTICS = (
    REPO_ROOT
    / "pydexpi_datalog"
    / "semantics"
    / "datalog"
    / "idb"
    / "graph_topology_semantics.dl"
)

INSPECTION = {
    "nodes": [
        {"id": "pif1", "label": "ProcessInstrumentationFunction", "tag_name": None},
        {"id": "v1", "label": "BallValve", "tag_name": "V-100"},
        {"id": "v2", "label": "BallValve", "tag_name": "V-200"},
        {"id": "p1", "label": "CentrifugalPump", "tag_name": "P-4713"},
    ],
    "edges": [],
}


def vocabulary():
    return routing_vocabulary(json.dumps(INSPECTION))


def test_template_pack_ships_the_six_locked_templates() -> None:
    assert set(TEMPLATE_PACK) == {
        "entity_lookup",
        "attachment",
        "reachability",
        "guarded_reachability",
        "class_count",
        "policy_abstention",
    }
    for template in TEMPLATE_PACK.values():
        assert template.description  # SME-facing, plain language


def test_validate_rejects_unknown_category() -> None:
    errors = validate_routing({"category": "clairvoyance", "parameters": {}}, vocabulary())
    assert any("clairvoyance" in error for error in errors)
    assert any("entity_lookup" in error for error in errors)  # names valid ids


def test_validate_rejects_label_outside_drawing_vocabulary() -> None:
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve", "ImaginaryValve"],
        },
    }
    errors = validate_routing(routing, vocabulary())
    assert any("ImaginaryValve" in error for error in errors)
    assert any("target_labels" in error for error in errors)
    assert any("BallValve" in error for error in errors)  # vocabulary offered


def test_validate_accepts_wellformed_guarded_reachability() -> None:
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve"],
        },
    }
    assert validate_routing(routing, vocabulary()) == []


def test_validate_accepts_complete_explicit_scope_absent_from_drawing() -> None:
    required = frozenset({"BallValve", "ButterflyValve", "GlobeValve"})
    expanded_vocabulary = routing_vocabulary(
        json.dumps(INSPECTION), additional_labels=required
    )
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": sorted(required),
        },
    }

    assert validate_routing(
        routing,
        expanded_vocabulary,
        required_labels=required,
    ) == []


def test_validate_policy_abstention_takes_no_parameters() -> None:
    assert validate_routing(
        {"category": "policy_abstention", "parameters": {}}, vocabulary()
    ) == []
    assert validate_routing(
        {"category": "policy_abstention", "parameters": {}},
        vocabulary(),
        required_labels=frozenset({"BallValve", "GlobeValve"}),
    ) == []
    errors = validate_routing(
        {"category": "policy_abstention", "parameters": {"labels": ["BallValve"]}},
        vocabulary(),
    )
    assert errors


def test_render_refuses_policy_abstention() -> None:
    with pytest.raises(ValueError, match="abstention"):
        render_program({"category": "policy_abstention", "parameters": {}})


def test_rendered_program_passes_the_authored_rule_guard() -> None:
    """Every rendered program must clear run_query.py's starter guard."""
    import re

    routing = {
        "category": "entity_lookup",
        "parameters": {"tags": ["P-4713"]},
    }
    program = render_program(routing)
    assert '.include "/input/graph_facts.dl"' in program
    assert '.include "/input/graph_topology_semantics.dl"' in program
    assert re.search(r"result_witness\s*\([^)]*\)\s*:-", program)
    assert 'node_tag(' in program and '"P-4713"' in program


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle engine not on PATH")
def test_guarded_reachability_template_executes_end_to_end(tmp_path: Path) -> None:
    """PIF reaches v1 but not v2 -> the unguarded valve is the sole witness."""
    (tmp_path / "graph_facts.dl").write_text(
        ".decl node(id:symbol)\n"
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)\n"
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)\n"
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol,"
        " attr_name:symbol, attr_value:symbol)\n"
        'node("pif1").\n'
        'node("v1").\n'
        'node("v2").\n'
        'node_attribute("pif1", "label", "ProcessInstrumentationFunction").\n'
        'node_attribute("v1", "label", "BallValve").\n'
        'node_attribute("v2", "label", "BallValve").\n'
        'graph_edge("pif1", "v1", "e1").\n'
        'graph_edge_attribute("pif1", "v1", "e1", "attr_name", "connections").\n',
        encoding="utf-8",
    )
    shutil.copy(SEMANTICS, tmp_path / "graph_topology_semantics.dl")
    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve"],
        },
    }
    program = render_program(routing, include_dir=str(tmp_path))
    program_path = tmp_path / "analysis.dl"
    program_path.write_text(program, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completed = subprocess.run(
        ["souffle", "-D", str(out_dir), str(program_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    witnesses = (out_dir / "result_witness.csv").read_text(encoding="utf-8").split()
    assert witnesses == ["v2"]


# --------------------------------------------------------------------------
# Slice 2: route_query.py in-container helper
# --------------------------------------------------------------------------


def make_helper_env(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in /input + /workspace pair for exercising the helper."""
    from pydexpi_datalog.benchmark.souffle_arm import RMSO_RUN_QUERY_HELPER

    input_dir = tmp_path / "input"
    workspace = tmp_path / "workspace"
    input_dir.mkdir()
    workspace.mkdir()
    (input_dir / "route_query.py").write_text(
        RMSO_ROUTE_QUERY_HELPER, encoding="utf-8"
    )
    (input_dir / "run_query.py").write_text(
        RMSO_RUN_QUERY_HELPER, encoding="utf-8"
    )
    (input_dir / "template_arm.py").write_text(
        Path(template_arm_module.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (input_dir / "graph_inspection.json").write_text(
        json.dumps(
            {
                "node_count": len(INSPECTION["nodes"]),
                "edge_count": 0,
                **INSPECTION,
            }
        ),
        encoding="utf-8",
    )
    (input_dir / "routing_requirements.json").write_text(
        json.dumps({"schema_version": 1, "required_labels": []}),
        encoding="utf-8",
    )
    return input_dir, workspace


def run_helper(input_dir: Path, workspace: Path) -> subprocess.CompletedProcess:
    import sys

    return subprocess.run(
        [
            sys.executable,
            str(input_dir / "route_query.py"),
            str(workspace / ROUTING_FILENAME),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_route_query_rejects_unknown_category_with_feedback(
    tmp_path: Path,
) -> None:
    input_dir, workspace = make_helper_env(tmp_path)
    (workspace / ROUTING_FILENAME).write_text(
        json.dumps({"category": "clairvoyance", "parameters": {}}),
        encoding="utf-8",
    )
    completed = run_helper(input_dir, workspace)
    assert completed.returncode == 1
    assert "clairvoyance" in completed.stderr
    assert "entity_lookup" in completed.stderr  # corrective vocabulary


def test_route_query_rejects_incomplete_explicit_label_scope(
    tmp_path: Path,
) -> None:
    input_dir, workspace = make_helper_env(tmp_path)
    (input_dir / "routing_requirements.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "required_labels": [
                    "BallValve",
                    "ButterflyValve",
                    "GlobeValve",
                ],
            }
        ),
        encoding="utf-8",
    )
    (workspace / ROUTING_FILENAME).write_text(
        json.dumps(
            {
                "category": "guarded_reachability",
                "parameters": {
                    "source_labels": ["ProcessInstrumentationFunction"],
                    "target_labels": ["BallValve"],
                },
            }
        ),
        encoding="utf-8",
    )

    completed = run_helper(input_dir, workspace)

    assert completed.returncode == 1
    assert "explicitly enumerated" in completed.stderr
    assert "ButterflyValve" in completed.stderr
    assert "GlobeValve" in completed.stderr
    assert not (workspace / "analysis.dl").exists()


def test_route_query_names_fallback_after_retry_budget_exhausted(
    tmp_path: Path,
) -> None:
    input_dir, workspace = make_helper_env(tmp_path)
    (workspace / ROUTING_FILENAME).write_text(
        json.dumps({"category": "clairvoyance", "parameters": {}}),
        encoding="utf-8",
    )
    outcomes = [run_helper(input_dir, workspace) for _ in range(3)]
    assert all(completed.returncode == 1 for completed in outcomes)
    # The first failed attempt and the in-budget retry stay corrective only.
    assert "fall back" not in outcomes[0].stderr
    assert "fall back" not in outcomes[VALIDATION_RETRY_BUDGET - 1].stderr
    # Once the budget is spent the helper names the fallback ladder.
    assert "fall back" in outcomes[VALIDATION_RETRY_BUDGET].stderr
    assert "run_query.py" in outcomes[VALIDATION_RETRY_BUDGET].stderr


def test_route_query_policy_abstention_checkpoints_mechanically(
    tmp_path: Path,
) -> None:
    input_dir, workspace = make_helper_env(tmp_path)
    (workspace / ROUTING_FILENAME).write_text(
        json.dumps({"category": "policy_abstention", "parameters": {}}),
        encoding="utf-8",
    )
    completed = run_helper(input_dir, workspace)
    assert completed.returncode == 0, completed.stderr
    answer = json.loads(
        (workspace / "structured_answer.json").read_text(encoding="utf-8")
    )
    assert answer["verdict"] == "unanswerable"
    assert answer["witness_ids"] == []
    assert answer["posture"] == "source_data_unavailable"
    assert answer["support"]["steps"][0]["kind"] == "policy_abstention"
    trace = json.loads(
        (workspace / ROUTE_TRACE_FILENAME).read_text(encoding="utf-8")
    )
    assert trace["path"] == "abstention"
    receipt_line = completed.stdout.splitlines()[-1]
    assert len(receipt_line) <= 60  # wrap-proof mechanical receipt
    assert json.loads(receipt_line) == {"ok": True, "rmso_checkpoint": "accepted"}


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle engine not on PATH")
def test_route_query_template_path_renders_traces_and_checkpoints(
    tmp_path: Path,
) -> None:
    import hashlib

    input_dir, workspace = make_helper_env(tmp_path)
    (input_dir / "graph_facts.dl").write_text(
        ".decl node(id:symbol)\n"
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)\n"
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)\n"
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol,"
        " attr_name:symbol, attr_value:symbol)\n"
        'node("pif1").\n'
        'node("v1").\n'
        'node("v2").\n'
        'node("p1").\n'
        'node_attribute("v1", "label", "BallValve").\n'
        'node_attribute("v2", "label", "BallValve").\n',
        encoding="utf-8",
    )
    shutil.copy(SEMANTICS, input_dir / "graph_topology_semantics.dl")
    (workspace / ROUTING_FILENAME).write_text(
        json.dumps(
            {"category": "entity_lookup", "parameters": {"labels": ["BallValve"]}}
        ),
        encoding="utf-8",
    )
    completed = run_helper(input_dir, workspace)
    assert completed.returncode == 0, completed.stderr
    program = (workspace / "analysis.dl").read_text(encoding="utf-8")
    assert f'.include "{input_dir}/graph_facts.dl"' in program
    trace = json.loads(
        (workspace / ROUTE_TRACE_FILENAME).read_text(encoding="utf-8")
    )
    assert trace["path"] == "template"
    assert trace["category"] == "entity_lookup"
    assert trace["program_sha256"] == hashlib.sha256(
        program.encode("utf-8")
    ).hexdigest()
    answer = json.loads(
        (workspace / "structured_answer.json").read_text(encoding="utf-8")
    )
    assert answer["verdict"] == "violation_found"
    assert answer["witness_ids"] == ["v1", "v2"]
    witness_line, receipt_line = completed.stdout.splitlines()[-2:]
    assert json.loads(witness_line) == {"witness_ids": ["v1", "v2"]}
    assert json.loads(receipt_line) == {"ok": True, "rmso_checkpoint": "accepted"}


# --------------------------------------------------------------------------
# Slice 2: build_rmso_template_harbor_task
# --------------------------------------------------------------------------

E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)


def make_bundle(tmp_dir: Path) -> Path:
    from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion  # noqa: F401

    bundle = tmp_dir / "e06-bundle"
    bundle.mkdir(parents=True)
    (bundle / "drawing.xml").write_text(
        "<PlantModel>e06 fixture stand-in</PlantModel>", encoding="utf-8"
    )
    shutil.copyfile(E06_GRAPH_FACTS, bundle / "graph_facts.json")
    return bundle


def make_template_question(bundle: Path, *, permission: bool = False):
    from pydexpi_datalog.benchmark.contract import (
        VERDICT_UNANSWERABLE,
        VERDICT_VIOLATION_FOUND,
    )
    from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion, GroundTruth

    if permission:
        return BenchmarkQuestion(
            question_id="hq-permission-defeasible-control-small",
            question="Is this arrangement permitted unless an exemption applies?",
            slice="harder_questions",
            drawing_ref=bundle,
            ground_truth=GroundTruth(
                verdict=VERDICT_UNANSWERABLE, witness_ids=()
            ),
        )
    return BenchmarkQuestion(
        question_id="template-q1",
        question="Find every unattached nozzle.",
        slice="hand_authored",
        drawing_ref=bundle,
        ground_truth=GroundTruth(
            verdict=VERDICT_VIOLATION_FOUND, witness_ids=("n1",)
        ),
    )


def test_template_task_mounts_helpers_and_routing_instruction(
    tmp_path: Path,
) -> None:
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_template_harbor_task(
        question=make_template_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8,
            max_commands=10,
            agent_timeout_sec=600.0,
            verifier_timeout_sec=120.0,
        ),
    )
    environment = task_dir / "environment"
    for name in (
        "route_query.py",
        "run_query.py",
        "template_arm.py",
        "graph_facts.dl",
        "graph_topology_semantics.dl",
        "graph_inspection.json",
        "analysis_template.dl",
        "routing_template.json",
    ):
        assert (environment / name).is_file(), name
    # The mounted template module is the reviewed source, verbatim.
    assert (environment / "template_arm.py").read_text(
        encoding="utf-8"
    ) == Path(template_arm_module.__file__).read_text(encoding="utf-8")
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert ROUTING_FILENAME in instruction
    assert "route_query.py" in instruction
    for category in TEMPLATE_PACK:
        assert category in instruction
    assert str(VALIDATION_RETRY_BUDGET) in instruction
    assert "fall back" in instruction.lower() or "fallback" in instruction.lower()
    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert "arm-t-template" in task_toml


def test_template_task_requires_every_explicitly_enumerated_class(
    tmp_path: Path,
) -> None:
    """A closed class list is an auditable routing requirement, including
    classes absent from the current drawing."""
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    question = replace(
        make_template_question(bundle),
        question=(
            "Find every component (any of BallValve, ButterflyValve, or Tank) "
            "that has no path to a pump "
            "(CentrifugalPump or ReciprocatingPump)."
        ),
    )
    task_dir = build_rmso_template_harbor_task(
        question=question,
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8,
            max_commands=10,
            agent_timeout_sec=600.0,
            verifier_timeout_sec=120.0,
        ),
    )

    requirements = json.loads(
        (task_dir / "environment" / "routing_requirements.json").read_text(
            encoding="utf-8"
        )
    )
    assert requirements["required_labels"] == [
        "BallValve",
        "ButterflyValve",
        "CentrifugalPump",
        "ReciprocatingPump",
        "Tank",
    ]
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "include every" in instruction.lower()
    for label in requirements["required_labels"]:
        assert label in instruction


def test_template_permission_instruction_routes_mechanical_abstention(
    tmp_path: Path,
) -> None:
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_template_harbor_task(
        question=make_template_question(bundle, permission=True),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8,
            max_commands=10,
            agent_timeout_sec=600.0,
            verifier_timeout_sec=120.0,
        ),
    )
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "policy_abstention" in instruction
    assert "route_query.py" in instruction
    assert "must abstain" in instruction
    # The model never hand-authors the answer or a verdict program.
    assert "Do not author or execute" in instruction


# --------------------------------------------------------------------------
# Slice 3: create_template_arm factory + faithfulness of rendered programs
# --------------------------------------------------------------------------


def test_rendered_template_programs_pass_the_faithfulness_validator() -> None:
    """Rendered programs must replay unchanged across frozen EDB probes."""
    from pydexpi_datalog.benchmark.souffle_arm import validate_faithfulness_program

    routings = [
        {"category": "entity_lookup", "parameters": {"tags": ["P-4713"]}},
        {
            "category": "attachment",
            "parameters": {"entity_labels": ["BallValve"], "mode": "unattached"},
        },
        {
            "category": "guarded_reachability",
            "parameters": {
                "source_labels": ["ProcessInstrumentationFunction"],
                "target_labels": ["BallValve"],
            },
        },
        {
            "category": "class_count",
            "parameters": {
                "labels": ["BallValve"],
                "comparator": "at_least",
                "threshold": 2,
            },
        },
    ]
    for routing in routings:
        validate_faithfulness_program(render_program(routing))


def test_create_template_arm_rejects_unknown_model(tmp_path: Path) -> None:
    from pydexpi_datalog.benchmark.template_arm_task import create_template_arm

    with pytest.raises(ValueError, match="bogus"):
        create_template_arm(
            "bogus",
            kira_dir=tmp_path,
            budgets=_budgets(),
            environ={"OPENROUTER_API_KEY": "test-key"},
        )


def test_create_template_arm_requires_api_key(tmp_path: Path) -> None:
    from pydexpi_datalog.benchmark.template_arm_task import create_template_arm

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        create_template_arm(
            "deepseek",
            kira_dir=tmp_path,
            budgets=_budgets(),
            environ={},
        )


def _budgets():
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    return EpisodeBudgets(
        max_turns=8,
        max_commands=10,
        agent_timeout_sec=600.0,
        verifier_timeout_sec=120.0,
    )


def test_create_template_arm_wires_checkpoint_adapter_and_gates(
    tmp_path: Path,
) -> None:
    import os

    from pydexpi_datalog.benchmark.souffle_arm import (
        validate_faithfulness_program,
        verify_souffle_answer_trace,
    )
    from pydexpi_datalog.benchmark.template_arm_task import create_template_arm

    arm = create_template_arm(
        "deepseek",
        kira_dir=tmp_path,
        budgets=_budgets(),
        environ={"OPENROUTER_API_KEY": "test-key"},
    )

    assert arm.arm_label == "t-template"
    assert arm.task_builder is build_rmso_template_harbor_task
    assert arm.require_executed_program is not None
    assert arm.program_validator is validate_faithfulness_program
    assert arm.program_faithfulness_gate is not None
    assert arm.answer_trace_gate is verify_souffle_answer_trace
    # Same checkpoint-aware KIRA adapter as Arm C, same cutoff derivation.
    assert arm.runner.agent_import_path == "rmso_kira:CheckpointTerminusKira"
    assert arm.runner.agent_kwargs == {"checkpoint_cutoff_sec": 540.0}
    benchmark_dir = str(
        Path(template_arm_module.__file__).resolve().parent
    )
    assert benchmark_dir in arm.runner.environ["PYTHONPATH"].split(os.pathsep)


def test_template_task_preserves_route_trace_best_effort(tmp_path: Path) -> None:
    """route_trace.json must be copied to the verifier dir when present,
    without being required (fallback-authoring episodes never write it)."""
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_template_harbor_task(
        question=make_template_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8,
            max_commands=10,
            agent_timeout_sec=600.0,
            verifier_timeout_sec=120.0,
        ),
    )
    test_sh = (task_dir / "tests" / "test.sh").read_text(encoding="utf-8")
    assert f"cp /workspace/{ROUTE_TRACE_FILENAME}" in test_sh
    verifier = (task_dir / "tests" / "test_outputs.py").read_text(encoding="utf-8")
    # Best-effort only: never added to the required-nonempty submission set.
    assert f'"{ROUTE_TRACE_FILENAME}"' not in verifier


# --------------------------------------------------------------------------
# Tooling fix: instrumentation-and-control reachability (scope=any)
# --------------------------------------------------------------------------


def test_guarded_reachability_scope_any_traverses_non_piping_edges(
    tmp_path: Path,
) -> None:
    """Valve-monitoring paths run through I&C edges (attr_name not in the
    piping allowlist). scope=any must reach through them; the default
    piping scope must not - that gap is the confirmed cross-arm bug."""
    if shutil.which("souffle") is None:
        pytest.skip("souffle engine not on PATH")
    (tmp_path / "graph_facts.dl").write_text(
        ".decl node(id:symbol)\n"
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)\n"
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)\n"
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol,"
        " attr_name:symbol, attr_value:symbol)\n"
        'node("pif1").\nnode("v1").\nnode("v2").\n'
        'node_attribute("pif1", "label", "ProcessInstrumentationFunction").\n'
        'node_attribute("v1", "label", "BallValve").\n'
        'node_attribute("v2", "label", "BallValve").\n'
        # Only path pif1 -> v1 is an I&C reference edge ("valve"), NOT piping.
        'graph_edge("pif1", "v1", "e1").\n'
        'graph_edge_attribute("pif1", "v1", "e1", "attr_name", "valve").\n',
        encoding="utf-8",
    )
    shutil.copy(SEMANTICS, tmp_path / "graph_topology_semantics.dl")

    def witnesses(scope):
        params = {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": ["BallValve"],
        }
        if scope is not None:
            params["scope"] = scope
        program = render_program(
            {"category": "guarded_reachability", "parameters": params},
            include_dir=str(tmp_path),
        )
        (tmp_path / "analysis.dl").write_text(program, encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        completed = subprocess.run(
            ["souffle", "-D", str(out), str(tmp_path / "analysis.dl")],
            capture_output=True, text=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return sorted(
            (out / "result_witness.csv").read_text(encoding="utf-8").split()
        )

    # scope=any: v1 IS monitored through the I&C edge -> only v2 unmonitored.
    assert witnesses("any") == ["v2"]
    # default (piping) scope: the I&C edge is invisible -> both look unmonitored.
    assert witnesses(None) == ["v1", "v2"]


def test_scope_validation_rejects_unknown_scope() -> None:
    from pydexpi_datalog.benchmark.template_arm import SCOPE_VALUES

    assert set(SCOPE_VALUES) == {"piping", "any"}
    routing = {
        "category": "reachability",
        "parameters": {
            "source_labels": ["BallValve"],
            "target_labels": ["BallValve"],
            "scope": "telepathic",
        },
    }
    errors = validate_routing(routing, vocabulary())
    assert any("scope" in e and "telepathic" not in e.lower()[:0] for e in errors)
    assert any("piping" in e and "any" in e for e in errors)


def test_instruction_surfaces_enum_slot_values_and_scope_guidance(
    tmp_path: Path,
) -> None:
    """The model must pick scope=any up front for monitoring questions - a
    valid-but-wrong scope never triggers a validation retry - so the
    instruction must name the scope values and when to use them."""
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_template_harbor_task(
        question=make_template_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8, max_commands=10,
            agent_timeout_sec=600.0, verifier_timeout_sec=120.0,
        ),
    )
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    # scope enum values + the directed-edge cue are both present.
    assert "piping" in instruction and "any" in instruction
    assert "any directed edge" in instruction
    # other enum slots surface their allowed values too (fewer wasted retries).
    assert "attached" in instruction and "unattached" in instruction
    assert "at_least" in instruction


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle engine not on PATH")
def test_scope_any_monitoring_program_passes_the_faithfulness_gate() -> None:
    """The frozen valve-monitoring gate (which marked both arms malformed
    last run) passes for a guarded_reachability + scope=any program over the
    full valve family - the tooling fix closes the failure end-to-end."""
    from pydexpi_datalog.benchmark.rmso_faithfulness import (
        run_preregistered_faithfulness_gate,
    )

    routing = {
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["ProcessInstrumentationFunction"],
            "target_labels": [
                "BallValve", "ButterflyValve", "GlobeValve",
                "OperatedValveReference", "SwingCheckValve",
                "SpringLoadedGlobeSafetyValve",
            ],
            "scope": "any",
        },
    }
    program = render_program(routing)
    for qid in (
        "hq-valve-monitoring-reachability-small",
        "hq-valve-monitoring-reachability-large",
    ):
        result = run_preregistered_faithfulness_gate(program, qid)
        assert result is not None and result["passed"], (qid, result)


def test_scope_direction_render_mapping() -> None:
    """The 2x2 (scope, direction) grid maps to the four IDB relations;
    piping scope uses the process-piping relations, not the topology
    `reachable` (which stays a separate, unchanged IDB primitive)."""
    def rel(scope=None, direction=None):
        params = {"source_labels": ["Tank"], "target_labels": ["CentrifugalPump"]}
        if scope is not None:
            params["scope"] = scope
        if direction is not None:
            params["direction"] = direction
        return render_program({"category": "reachability", "parameters": params})

    assert "piping_reachable(S, N)" in rel()  # default piping+directed
    assert "piping_connected(S, N)" in rel(direction="undirected")
    assert "reachable_any(S, N)" in rel(scope="any")
    assert "reachable_any_undirected(S, N)" in rel(scope="any", direction="undirected")


def test_direction_validation_rejects_unknown_direction() -> None:
    from pydexpi_datalog.benchmark.template_arm import DIRECTION_VALUES

    assert set(DIRECTION_VALUES) == {"directed", "undirected"}
    errors = validate_routing({
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["BallValve"], "target_labels": ["BallValve"],
            "direction": "sideways",
        },
    }, vocabulary())
    assert any("direction" in e and "directed" in e and "undirected" in e for e in errors)


def test_undirected_piping_traverses_reverse_composition_edges(
    tmp_path: Path,
) -> None:
    """Equipment-pump connectivity needs a piping path 'in either direction'
    through nozzles: pump ->(nozzles) pump-nozzle ->(connections) equip-nozzle
    <-(nozzles) equipment. The last hop reverses a composition edge, so only
    the undirected process-piping closure connects the equipment."""
    if shutil.which("souffle") is None:
        pytest.skip("souffle engine not on PATH")
    (tmp_path / "graph_facts.dl").write_text(
        ".decl node(id:symbol)\n"
        ".decl node_attribute(id:symbol, attr_name:symbol, attr_value:symbol)\n"
        ".decl graph_edge(source:symbol, target:symbol, edge_key:symbol)\n"
        ".decl graph_edge_attribute(source:symbol, target:symbol, edge_key:symbol,"
        " attr_name:symbol, attr_value:symbol)\n"
        'node("P").\nnode("H").\nnode("Np").\nnode("Nh").\n'
        'node_attribute("P", "label", "CentrifugalPump").\n'
        'node_attribute("H", "label", "PlateHeatExchanger").\n'
        'node_attribute("Np", "label", "Nozzle").\n'
        'node_attribute("Nh", "label", "Nozzle").\n'
        'graph_edge("P", "Np", "e1").\n'
        'graph_edge_attribute("P", "Np", "e1", "attr_name", "nozzles").\n'
        'graph_edge("Np", "Nh", "e2").\n'
        'graph_edge_attribute("Np", "Nh", "e2", "attr_name", "connections").\n'
        'graph_edge("H", "Nh", "e3").\n'
        'graph_edge_attribute("H", "Nh", "e3", "attr_name", "nozzles").\n',
        encoding="utf-8",
    )
    shutil.copy(SEMANTICS, tmp_path / "graph_topology_semantics.dl")

    def witnesses(direction):
        program = render_program({
            "category": "guarded_reachability",
            "parameters": {
                "source_labels": ["CentrifugalPump"],
                "target_labels": ["PlateHeatExchanger"],
                "scope": "piping", "direction": direction,
            },
        }, include_dir=str(tmp_path))
        (tmp_path / "analysis.dl").write_text(program, encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        completed = subprocess.run(
            ["souffle", "-D", str(out), str(tmp_path / "analysis.dl")],
            capture_output=True, text=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return sorted((out / "result_witness.csv").read_text().split())

    assert witnesses("directed") == ["H"]     # can't reverse the H->Nh nozzle edge
    assert witnesses("undirected") == []       # either-direction path connects H


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle engine not on PATH")
def test_undirected_piping_passes_equipment_connectivity_faithfulness_gate() -> None:
    from pydexpi_datalog.benchmark.rmso_faithfulness import (
        run_preregistered_faithfulness_gate,
    )

    program = render_program({
        "category": "guarded_reachability",
        "parameters": {
            "source_labels": ["CentrifugalPump", "ReciprocatingPump"],
            "target_labels": [
                "PlateHeatExchanger", "TubularHeatExchanger", "Tank", "ProcessColumn",
            ],
            "scope": "piping", "direction": "undirected",
        },
    })
    for qid in (
        "hq-equipment-pump-connectivity-small",
        "hq-equipment-pump-connectivity-large",
    ):
        result = run_preregistered_faithfulness_gate(program, qid)
        assert result is not None and result["passed"], (qid, result)


def test_instruction_steers_toward_early_commitment(tmp_path: Path) -> None:
    """The dominant remaining Arm T failure is over-exploration timing out
    before any routing is written. The instruction must steer the model to
    skip helper-source reading, cap inspection, and commit to a routing
    early (refining after execution rather than exploring first)."""
    from pydexpi_datalog.benchmark.agentic_arm import EpisodeBudgets

    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_template_harbor_task(
        question=make_template_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=EpisodeBudgets(
            max_turns=8, max_commands=10,
            agent_timeout_sec=600.0, verifier_timeout_sec=120.0,
        ),
    )
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").lower()
    # Don't read helper source.
    assert "do not read" in instruction or "no need to read" in instruction
    assert "route_query.py" in instruction
    # Commit early / limited turns.
    assert "commit" in instruction
    assert "turn" in instruction  # budget awareness
    # Cap inspection.
    assert "one" in instruction and "grep" in instruction
