"""Behavior tests for Arm C: agent + Souffle + rule packs.

Arm C reuses Arm A agentic's episode machinery exactly; the delta is bundle
composition (souffle on PATH, the Datalog EDB/IDB layers, and the bundled
rule-pack markdown inside the sandbox), prompt framing (the CODORD
generate-revise loop), and the executed Datalog program shipping with the
answer for post-hoc audit.  Scripted providers only: no live LLM or Docker
calls in CI.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from pydexpi_datalog.benchmark import (
    POSTURE_SOURCE_DATA_UNAVAILABLE,
    POSTURE_SOURCE_GROUNDED,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
    run_benchmark,
)
from pydexpi_datalog.benchmark.agentic_arm import (
    AGENTIC_ARM_MODELS,
    DEGRADED_VERDICT,
    AgenticArm,
    EpisodeBudgets,
    EpisodeResult,
    parse_harbor_artifacts,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion
from pydexpi_datalog.benchmark.rmso_kira import (
    CHECKPOINT_FIELD,
    CHECKPOINT_VALUE,
    build_checkpoint_kira_class,
)
from pydexpi_datalog.benchmark.souffle_arm import (
    FaithfulnessProgramError,
    PROGRAM_FILENAME,
    SOUFFLE_ARM_MODELS,
    build_rmso_souffle_harbor_task,
    build_souffle_harbor_task,
    create_souffle_arm,
    requires_executed_program,
    validate_faithfulness_program,
    verify_souffle_answer_trace,
)
from pydexpi_datalog.semantics.souffle_runner import (
    SouffleExecutionError,
    run_souffle_program,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
)

BUDGETS = EpisodeBudgets(
    max_turns=8,
    max_commands=10,
    agent_timeout_sec=600.0,
    verifier_timeout_sec=120.0,
)


class FakeKiraResponse:
    def __init__(self, **values):
        self.__dict__.update(values)


@dataclass
class FakeKiraCommand:
    keystrokes: str
    duration_sec: float


class FakeKiraSession:
    async def send_keys(self, *args, **kwargs):
        return None


class FakeKiraBoundary:
    def __init__(self, *, outputs=()):
        self._pending_completion = False
        self.model_calls = 0
        self.outputs = list(outputs)
        self.executed_commands = []
        self._session = FakeKiraSession()

    async def _execute_commands(self, commands, session):
        self.executed_commands.append(commands)
        return False, self.outputs.pop(0)

    async def _handle_llm_interaction(self, *args, **kwargs):
        self.model_calls += 1
        return "called-model"


CheckpointKiraBoundary = build_checkpoint_kira_class(
    FakeKiraBoundary,
    FakeKiraResponse,
    FakeKiraCommand,
)


def make_bundle(tmp_dir: Path) -> Path:
    """A minimal drawing bundle directory in the 3q1.4 export layout."""
    bundle = tmp_dir / "e06-bundle"
    bundle.mkdir(parents=True)
    (bundle / "drawing.xml").write_text(
        "<PlantModel>e06 fixture stand-in</PlantModel>", encoding="utf-8"
    )
    shutil.copyfile(E06_GRAPH_FACTS, bundle / "graph_facts.json")
    (bundle / "graph.json").write_text(
        json.dumps({"nodes": [], "edges": []}), encoding="utf-8"
    )
    (bundle / "README.md").write_text("# Drawing bundle\n", encoding="utf-8")
    return bundle


def make_question(bundle: Path) -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="souffle-q1",
        question="Is any pump missing a check valve?",
        slice="hand_authored",
        drawing_ref=bundle,
        ground_truth=GroundTruth(
            verdict=VERDICT_VIOLATION_FOUND, witness_ids=(witness_node_id(),)
        ),
    )


def make_permission_question(bundle: Path) -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="hq-permission-defeasible-control-small",
        question="Is this arrangement permitted unless an exemption applies?",
        slice="harder_questions",
        drawing_ref=bundle,
        ground_truth=GroundTruth(verdict=VERDICT_UNANSWERABLE, witness_ids=()),
    )


def witness_node_id() -> str:
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    return str(graph_facts["facts"]["nodes"][0]["node_id"])


def build_task(tmp_path: Path) -> Path:
    bundle = make_bundle(tmp_path)
    return build_souffle_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )


# --------------------------------------------------------------------------
# Bundle composition: Datalog layers + rule-pack markdown + souffle on PATH
# --------------------------------------------------------------------------


def test_task_environment_includes_datalog_layers_and_rule_packs(
    tmp_path: Path,
) -> None:
    task_dir = build_task(tmp_path)
    environment = task_dir / "environment"

    # Arm A's bundle files are all still present.
    for name in ("drawing.xml", "graph_facts.json", "graph.json", "README.md"):
        assert (environment / name).is_file(), name

    # The pre-rendered EDB facts mirror the bundle's canonical base fact layer.
    edb = (environment / "graph_facts.dl").read_text(encoding="utf-8")
    assert ".decl node(id:symbol)" in edb
    assert f'node("{witness_node_id()}").' in edb

    # The shared IDB semantics layer ships verbatim.
    idb = (environment / "graph_topology_semantics.dl").read_text(
        encoding="utf-8"
    )
    assert idb == (
        REPO_ROOT
        / "pydexpi_datalog"
        / "semantics"
        / "datalog"
        / "idb"
        / "graph_topology_semantics.dl"
    ).read_text(encoding="utf-8")

    # Every bundled rule pack ships as canonical markdown prior art.
    pack_text = (environment / "rule_pack_demo_process_safety.md").read_text(
        encoding="utf-8"
    )
    assert "pack_id" in pack_text
    assert "```" in pack_text, "fenced Souffle programs must be included"


def test_rmso_task_exposes_only_approved_edb_and_idb_inputs(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_souffle_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "rmso-tasks",
        budgets=BUDGETS,
    )
    environment = task_dir / "environment"
    assert {
        path.name
        for path in environment.iterdir()
        if path.name != "Dockerfile"
    } == {
        "analysis_template.dl",
        "graph_facts.json",
        "graph_facts.dl",
        "graph_inspection.json",
        "graph_topology_semantics.dl",
        "run_query.py",
    }
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    for forbidden in (
        "/input/drawing.xml",
        "/input/graph.json",
        "/input/README.md",
        "/input/rule_pack_",
    ):
        assert forbidden not in instruction
    dockerfile = (environment / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM --platform=linux/amd64 ubuntu:22.04\n")
    assert "python3" in dockerfile
    assert "COPY analysis_template.dl /workspace/analysis.dl" in dockerfile
    assert "chown agent:agent /workspace/analysis.dl" in dockerfile
    assert "cp /input/analysis_template.dl /workspace/analysis.dl" not in instruction
    assert "Edit the preloaded `/workspace/analysis.dl`" in instruction


def test_rmso_query_helper_executes_template_and_reports_bounded_witness_json(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_rmso_souffle_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "rmso-tasks",
        budgets=BUDGETS,
    )
    environment = task_dir / "environment"
    template = (environment / "analysis_template.dl").read_text(encoding="utf-8")
    assert template.startswith('.include "/input/graph_facts.dl"\n')
    assert ".decl result_witness(id:symbol)" in template
    helper = environment / "run_query.py"
    witness = json.loads(
        (environment / "graph_inspection.json").read_text(encoding="utf-8")
    )["nodes"][0]["id"]
    smoke_program = tmp_path / "analysis.dl"
    smoke_program.write_text(
        '.decl result_witness(id:symbol)\n'
        f'result_witness("{witness}").\n'
        ".output result_witness\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(helper), str(smoke_program)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "ok": True,
        CHECKPOINT_FIELD: CHECKPOINT_VALUE,
        "witness_ids": [witness],
    }
    checkpoint = json.loads(
        (tmp_path / "structured_answer.json").read_text(encoding="utf-8")
    )
    assert checkpoint["verdict"] == "violation_found"
    assert checkpoint["witness_ids"] == [witness]
    assert checkpoint["support"]["steps"][1] == {
        "id": "execution",
        "kind": "souffle_execution",
        "artifact": "analysis.dl",
        "relation": "result_witness",
        "witness_ids": [witness],
        "dependencies": ["scope"],
    }

    smoke_program.write_text(
        '.decl result_witness(id:symbol)\n.output result_witness\n',
        encoding="utf-8",
    )
    empty = subprocess.run(
        [sys.executable, str(helper), str(smoke_program)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert empty.returncode == 0, empty.stderr
    empty_checkpoint = json.loads(
        (tmp_path / "structured_answer.json").read_text(encoding="utf-8")
    )
    assert empty_checkpoint["verdict"] == "no_violation"
    assert empty_checkpoint["witness_ids"] == []

    smoke_program.write_text("this is not Souffle\n", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(helper), str(smoke_program)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode != 0
    assert json.loads(
        (tmp_path / "structured_answer.json").read_text(encoding="utf-8")
    ) == empty_checkpoint
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "python3 /input/run_query.py /workspace/analysis.dl" in instruction
    assert "writes a valid provisional structured answer" in instruction
    assert "grep" in instruction
    assert "Avoid printing an entire large input" in instruction


def test_checkpoint_aware_kira_completes_without_another_model_call(
    tmp_path: Path,
) -> None:
    receipt = json.dumps(
        {"ok": True, CHECKPOINT_FIELD: CHECKPOINT_VALUE, "witness_ids": []}
    )
    agent = CheckpointKiraBoundary(outputs=(receipt, receipt))

    first = FakeKiraCommand(keystrokes="run query\n", duration_sec=1)
    prohibited = FakeKiraCommand(keystrokes="keep inspecting\n", duration_sec=60)
    model_commands = [first, prohibited]
    asyncio.run(agent.execute_checkpoint_commands(model_commands, object()))
    completion = asyncio.run(agent.checkpoint_or_model_interaction())

    assert len(agent.executed_commands) == 2
    assert agent.executed_commands[0] == [first]
    assert agent.executed_commands[1] == [
        FakeKiraCommand(
            keystrokes="python3 /input/run_query.py /workspace/analysis.dl\n",
            duration_sec=50.0,
        )
    ]
    flattened_commands = [
        command for batch in agent.executed_commands for command in batch
    ]
    assert prohibited not in flattened_commands
    assert model_commands == [first]
    assert agent.model_calls == 0
    assert completion[1] is True

    (tmp_path / "agent-trajectory.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "function_name": "execute_commands",
                        "arguments": {
                            "commands": [
                                {"keystrokes": command.keystrokes}
                                for command in model_commands
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    persisted = parse_harbor_artifacts(tmp_path)
    assert persisted.command_batches == ((first.keystrokes,),)


def test_checkpoint_aware_kira_keeps_failed_queries_revisable() -> None:
    agent = CheckpointKiraBoundary(outputs=("Error: Ungrounded variable X",))

    command = FakeKiraCommand(keystrokes="bad query\n", duration_sec=1)
    asyncio.run(agent.execute_checkpoint_commands([command], object()))
    result = asyncio.run(agent.checkpoint_or_model_interaction())

    assert result == "called-model"
    assert agent.model_calls == 1


def test_checkpoint_aware_kira_rejects_a_forged_receipt() -> None:
    receipt = json.dumps(
        {"ok": True, CHECKPOINT_FIELD: CHECKPOINT_VALUE, "witness_ids": []}
    )
    agent = CheckpointKiraBoundary(
        outputs=(receipt, "Error: analysis.dl did not compile")
    )

    command = FakeKiraCommand(keystrokes="forge receipt\n", duration_sec=1)
    asyncio.run(agent.execute_checkpoint_commands([command], object()))
    result = asyncio.run(agent.checkpoint_or_model_interaction())

    assert result == "called-model"
    assert agent.model_calls == 1


def test_checkpoint_aware_kira_stops_at_the_finalization_cutoff() -> None:
    agent = CheckpointKiraBoundary(
        outputs=("Error: no executable checkpoint",), checkpoint_cutoff_sec=0
    )

    completion = asyncio.run(agent.checkpoint_or_model_interaction())

    assert agent.model_calls == 0
    assert completion[1] is True
    assert "cutoff" in completion[5].content


def test_dockerfile_installs_souffle_and_mounts_layers_read_only(
    tmp_path: Path,
) -> None:
    task_dir = build_task(tmp_path)
    dockerfile = (task_dir / "environment" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "souffle" in dockerfile
    for name in (
        "graph_facts.dl",
        "graph_topology_semantics.dl",
        "rule_pack_demo_process_safety.md",
    ):
        assert f"COPY {name} /input/{name}" in dockerfile
        assert f"chmod 0444 /input/{name}" in dockerfile


def test_task_toml_tags_arm_c(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path)
    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert "arm-c-souffle" in task_toml
    assert "pydexpi-datalog-1-3q1.9" in task_toml


# --------------------------------------------------------------------------
# Prompt framing: the CODORD generate-revise loop
# --------------------------------------------------------------------------


def test_instruction_frames_generate_revise_loop(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path)
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    # Datalog-first framing with the engine and its layers named.
    assert "souffle" in instruction
    assert "/input/graph_facts.dl" in instruction
    assert "/input/graph_topology_semantics.dl" in instruction
    # Rule-pack markdown is offered as trusted prior art.
    assert "rule_pack_demo_process_safety.md" in instruction
    # Generate -> execute -> observe -> revise loop is explicit.
    assert "revise" in instruction.lower()
    # The executed program must ship with the answer.
    assert f"/workspace/{PROGRAM_FILENAME}" in instruction
    # The structured answer contract is unchanged from Arm A.
    assert "/workspace/structured_answer.json" in instruction
    assert "violation_found" in instruction


def test_instruction_requires_a_portable_standard_witness_program(tmp_path: Path) -> None:
    instruction = (build_task(tmp_path) / "instruction.md").read_text(
        encoding="utf-8"
    )

    assert '.include "/input/graph_facts.dl"' in instruction
    assert '.include "/input/graph_topology_semantics.dl"' in instruction
    assert ".decl result_witness(id:symbol)" in instruction
    assert ".output result_witness" in instruction
    assert "Do not copy EDB declarations or facts" in instruction
    assert '"kind": "graph_scope"' in instruction
    assert '"kind": "souffle_execution"' in instruction
    assert '"claim": "verdict"' in instruction


def test_portable_program_contract_rejects_embedded_edb_and_hidden_uuids() -> None:
    portable = """\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- node(X), node_attribute(X, "label", "Nozzle").
"""
    validate_faithfulness_program(portable)

    with pytest.raises(FaithfulnessProgramError, match="EDB declaration"):
        validate_faithfulness_program(
            portable + "\n.decl node(id:symbol)\nnode(\"invented\").\n"
        )
    with pytest.raises(FaithfulnessProgramError, match="UUID"):
        validate_faithfulness_program(
            portable
            + '\nresult_witness("7fdefa2f-5751-48eb-8c7c-34dd07cc16d3").\n'
        )


# --------------------------------------------------------------------------
# Executed program ships with the answer for post-hoc audit
# --------------------------------------------------------------------------


def run_generated_verifier(
    task_dir: Path, workspace: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(task_dir / "tests" / "test_outputs.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "INPUT_DIR": str(task_dir / "environment"),
            "WORKSPACE_DIR": str(workspace),
        },
    )


def valid_answer() -> str:
    return json.dumps(
        {
            "verdict": VERDICT_VIOLATION_FOUND,
            "witness_ids": [witness_node_id()],
            "posture": POSTURE_SOURCE_GROUNDED,
        }
    )


def valid_permission_abstention() -> str:
    return json.dumps(
        {
            "verdict": VERDICT_UNANSWERABLE,
            "witness_ids": [],
            "posture": POSTURE_SOURCE_DATA_UNAVAILABLE,
            "answer_text": "Permission is not soundly decidable from monotone drawing facts.",
            "support": {
                "steps": [
                    {
                        "id": "policy",
                        "kind": "policy_abstention",
                        "operation": (
                            "permission_or_defeasible_not_decidable_from_"
                            "monotone_drawing"
                        ),
                        "dependencies": [],
                    }
                ],
                "claims": [{"claim": "verdict", "step_ids": ["policy"]}],
            },
        }
    )


def test_permission_task_requires_abstention_without_a_program(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_souffle_harbor_task(
        question=make_permission_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    test_sh = (task_dir / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "must not author or execute" in instruction
    assert PROGRAM_FILENAME not in test_sh

    workspace = tmp_path / "permission-workspace"
    workspace.mkdir()
    (workspace / "structured_answer.json").write_text(
        valid_permission_abstention(), encoding="utf-8"
    )
    accepted = run_generated_verifier(task_dir, workspace)
    assert accepted.returncode == 0, accepted.stderr


def test_permission_arm_checks_abstention_trace_without_a_program(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(
            EpisodeResult(
                structured_answer_text=valid_permission_abstention(),
                reward=1.0,
                executed_program=None,
            )
        ),
        budgets=BUDGETS,
        task_builder=build_souffle_harbor_task,
        require_executed_program=requires_executed_program,
        program_validator=validate_faithfulness_program,
        answer_trace_gate=verify_souffle_answer_trace,
    )

    answer = arm.answer(
        question=make_permission_question(bundle), drawing_ref=bundle
    )

    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.usage["audit_trace"]["trace_safe"] is True


def test_permission_arm_rejects_source_conclusion_without_a_program(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(
            EpisodeResult(
                structured_answer_text=valid_answer(),
                reward=1.0,
                executed_program=None,
            )
        ),
        budgets=BUDGETS,
        task_builder=build_souffle_harbor_task,
        require_executed_program=requires_executed_program,
        answer_trace_gate=verify_souffle_answer_trace,
    )

    answer = arm.answer(
        question=make_permission_question(bundle), drawing_ref=bundle
    )

    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "audit_trace_unsafe"


def test_generated_verifier_requires_executed_program(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "structured_answer.json").write_text(
        valid_answer(), encoding="utf-8"
    )

    rejected = run_generated_verifier(task_dir, workspace)
    assert rejected.returncode != 0, "missing analysis.dl must be rejected"

    (workspace / PROGRAM_FILENAME).write_text("", encoding="utf-8")
    still_rejected = run_generated_verifier(task_dir, workspace)
    assert still_rejected.returncode != 0, "empty analysis.dl must be rejected"

    (workspace / PROGRAM_FILENAME).write_text(
        '.decl answer(x:symbol)\n.output answer\nanswer("p101").\n',
        encoding="utf-8",
    )
    accepted = run_generated_verifier(task_dir, workspace)
    assert accepted.returncode == 0, accepted.stderr


def test_test_sh_preserves_program_artifact(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path)
    test_sh = (task_dir / "tests" / "test.sh").read_text(encoding="utf-8")
    assert PROGRAM_FILENAME in test_sh


def test_parse_harbor_artifacts_reads_executed_program(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    verifier_dir = jobs_dir / "trial-0" / "verifier"
    verifier_dir.mkdir(parents=True)
    (verifier_dir / "reward.txt").write_text("1\n", encoding="utf-8")
    (verifier_dir / "structured_answer.json").write_text(
        valid_answer(), encoding="utf-8"
    )
    (verifier_dir / PROGRAM_FILENAME).write_text(
        ".decl answer(x:symbol)\n", encoding="utf-8"
    )
    result = parse_harbor_artifacts(jobs_dir)
    assert result.executed_program == ".decl answer(x:symbol)\n"


def test_arm_ships_executed_program_in_transcript(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    program = '.decl answer(x:symbol)\n.output answer\nanswer("x").\n'
    runner = ScriptedEpisodeRunner(
        EpisodeResult(
            structured_answer_text=valid_answer(),
            reward=1.0,
            command_batches=(("souffle /tmp/attempt.dl -D out",),),
            model_calls=2,
            executed_program=program,
        )
    )
    arm = AgenticArm(
        runner=runner,
        budgets=BUDGETS,
        model_name="scripted",
        arm_label="c-souffle",
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
    )
    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert arm.arm_id == "c-souffle:scripted"
    program_entries = [
        entry
        for entry in answer.transcript
        if entry.get("tool_name") == "executed_datalog_program"
    ]
    assert len(program_entries) == 1
    assert program_entries[0]["content"] == program


@pytest.mark.parametrize("program", [None, "", "   \n"])
def test_arm_degrades_when_executed_program_missing_or_empty(
    tmp_path: Path, program: str | None
) -> None:
    bundle = make_bundle(tmp_path)
    runner = ScriptedEpisodeRunner(
        EpisodeResult(
            structured_answer_text=valid_answer(),
            reward=1.0,
            executed_program=program,
        )
    )
    arm = AgenticArm(
        runner=runner,
        budgets=BUDGETS,
        model_name="scripted",
        arm_label="c-souffle",
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
    )
    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "missing_executed_program"


def test_arm_degrades_when_program_is_not_portable_for_faithfulness_replay(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    runner = ScriptedEpisodeRunner(
        EpisodeResult(
            structured_answer_text=valid_answer(),
            reward=1.0,
            executed_program='.decl answer(x:symbol)\n.output answer\nanswer("x").\n',
        )
    )
    arm = AgenticArm(
        runner=runner,
        budgets=BUDGETS,
        model_name="scripted",
        arm_label="c-souffle",
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
        program_validator=validate_faithfulness_program,
    )

    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)

    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "invalid_executed_program"
    assert "missing" in str(answer.usage["program_validation_error"])


def test_arm_degrades_when_cross_size_or_counterfactual_gate_fails(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    portable = """\
.include "/input/graph_facts.dl"
.include "/input/graph_topology_semantics.dl"
.decl result_witness(id:symbol)
.output result_witness
result_witness(X) :- node(X), X != X.
"""
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(
            EpisodeResult(
                structured_answer_text=valid_answer(),
                reward=1.0,
                executed_program=portable,
            )
        ),
        budgets=BUDGETS,
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
        program_validator=validate_faithfulness_program,
        program_faithfulness_gate=lambda _program, _question: {
            "family_id": "test-family",
            "passed": False,
            "cases": [{"case_id": "counterfactual", "passed": False}],
        },
    )

    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)

    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "faithfulness_gate_failed"
    assert answer.usage["faithfulness_gate"]["cases"] == [
        {"case_id": "counterfactual", "passed": False}
    ]


# --------------------------------------------------------------------------
# Budgets and model matrix identical to Arm A agentic
# --------------------------------------------------------------------------


def test_model_matrix_identical_to_arm_a() -> None:
    assert SOUFFLE_ARM_MODELS == AGENTIC_ARM_MODELS


def test_create_souffle_arm_rejects_unknown_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bogus"):
        create_souffle_arm(
            "bogus",
            kira_dir=tmp_path,
            budgets=BUDGETS,
            environ={"OPENROUTER_API_KEY": "x"},
        )


def test_create_souffle_arm_builds_arm_c_over_kira_runner(
    tmp_path: Path,
) -> None:
    arm = create_souffle_arm(
        "sonnet",
        kira_dir=tmp_path,
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
    )
    assert arm.arm_id == "c-souffle:sonnet"
    assert arm.budgets == BUDGETS
    assert arm.require_executed_program is requires_executed_program
    assert arm.task_builder is build_rmso_souffle_harbor_task
    assert arm.program_validator is validate_faithfulness_program
    assert arm.program_faithfulness_gate is not None
    assert arm.answer_trace_gate is not None
    assert (
        arm.runner.agent_import_path
        == "rmso_kira:CheckpointTerminusKira"
    )
    assert str(REPO_ROOT / "pydexpi_datalog" / "benchmark") in arm.runner.environ[
        "PYTHONPATH"
    ].split(os.pathsep)
    assert arm.runner.agent_kwargs == {"checkpoint_cutoff_sec": 540.0}
    command = arm.runner.build_command(
        task_dir=tmp_path / "tasks" / "benchmark-souffle-q1",
        jobs_dir=tmp_path / "jobs",
        budgets=BUDGETS,
    )
    cutoff = command.index("checkpoint_cutoff_sec=540.0")
    assert command[cutoff - 1] == "--agent-kwarg"


def test_deepseek_live_arm_resolves_exact_preregistered_v4_flash_model(
    tmp_path: Path,
) -> None:
    arm = create_souffle_arm(
        "deepseek",
        kira_dir=tmp_path,
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
    )

    assert arm.runner.model == "openrouter/deepseek/deepseek-v4-flash"


def test_live_arm_constructor_accepts_locked_request_gateway(tmp_path: Path) -> None:
    gateway = object()

    arm = create_souffle_arm(
        "deepseek",
        kira_dir=tmp_path,
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
        request_gateway=gateway,  # type: ignore[arg-type]
    )

    assert arm.runner.request_gateway is gateway


@dataclass
class ScriptedEpisodeRunner:
    """Deterministic EpisodeRunner returning one canned result."""

    result: EpisodeResult

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        return self.result


# --------------------------------------------------------------------------
# The generate-revise loop against the real Souffle engine
# --------------------------------------------------------------------------


@dataclass
class ScriptedSouffleModelRunner:
    """A scripted model working the generated Arm C task with real Souffle.

    Demonstrates the CODORD generate-revise loop end to end: a first Datalog
    attempt fails, real engine diagnostics are observed, the revised program
    executes, and the executed results are submitted with the program.
    """

    def __post_init__(self) -> None:
        self.observed_diagnostics: list[str] = []
        self.attempted_programs: list[str] = []

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        input_dir = task_dir / "environment"
        edb = (input_dir / "graph_facts.dl").read_text(encoding="utf-8")
        idb = (input_dir / "graph_topology_semantics.dl").read_text(
            encoding="utf-8"
        )

        # Generate: the first program has a bad head arity and must fail.
        failing = edb + "\n.decl hit(x:symbol)\n.output hit\nhit(X, Y) :- node(X).\n"
        self.attempted_programs.append(failing)
        try:
            run_souffle_program(failing)
        except SouffleExecutionError as error:
            self.observed_diagnostics.append(str(error.detail))

        # Revise against the observed diagnostics, then execute for real.
        revised = (
            edb
            + "\n"
            + idb
            + "\n.decl hit(x:symbol)\n.output hit\nhit(X) :- node(X).\n"
        )
        self.attempted_programs.append(revised)
        relations = run_souffle_program(revised)
        rows = relations.get("hit", [])
        assert rows, "revised program must produce real engine output"
        witness = rows[0][0]

        # Submit executed results: answer + the exact executed program.
        workspace = jobs_dir / "workspace"
        verifier_dir = jobs_dir / "trial-0" / "verifier"
        workspace.mkdir(parents=True)
        verifier_dir.mkdir(parents=True)
        (workspace / "structured_answer.json").write_text(
            json.dumps(
                {
                    "verdict": VERDICT_VIOLATION_FOUND,
                    "witness_ids": [witness],
                    "posture": POSTURE_SOURCE_GROUNDED,
                }
            ),
            encoding="utf-8",
        )
        (workspace / PROGRAM_FILENAME).write_text(revised, encoding="utf-8")

        verdict_check = subprocess.run(
            [sys.executable, str(task_dir / "tests" / "test_outputs.py")],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "INPUT_DIR": str(input_dir),
                "WORKSPACE_DIR": str(workspace),
            },
        )
        (verifier_dir / "reward.txt").write_text(
            "1\n" if verdict_check.returncode == 0 else "0\n", encoding="utf-8"
        )
        for name in ("structured_answer.json", PROGRAM_FILENAME):
            shutil.copyfile(workspace / name, verifier_dir / name)
        (jobs_dir / "trial-0" / "agent-trajectory.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "function_name": "execute_commands",
                            "arguments": {
                                "commands": [
                                    {
                                        "keystrokes": "souffle attempt1.dl -D out",
                                        "duration": 5,
                                    },
                                    {
                                        "keystrokes": "souffle analysis.dl -D out",
                                        "duration": 5,
                                    },
                                ]
                            },
                            "prompt_tokens": 120,
                            "completion_tokens": 40,
                        },
                        {"function_name": "mark_task_complete"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return parse_harbor_artifacts(jobs_dir)


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_generate_revise_loop_against_real_engine(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    runner = ScriptedSouffleModelRunner()
    arm = AgenticArm(
        runner=runner,
        budgets=BUDGETS,
        model_name="scripted",
        arm_label="c-souffle",
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
    )
    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)

    # The loop happened: failing Datalog, observed diagnostics, revision.
    assert len(runner.attempted_programs) == 2
    assert runner.observed_diagnostics, "engine diagnostics must be observed"
    assert "hit" in runner.observed_diagnostics[0]

    # The submitted answer carries executed results and the program.
    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert answer.posture == POSTURE_SOURCE_GROUNDED
    assert answer.witness_ids, "witnesses come from executed output"
    program_entries = [
        entry
        for entry in answer.transcript
        if entry.get("tool_name") == "executed_datalog_program"
    ]
    assert len(program_entries) == 1
    assert ".output hit" in str(program_entries[0]["content"])


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle engine not on PATH"
)
def test_run_benchmark_grades_souffle_arm_end_to_end(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "episode_budgets": {"max_turns": 8, "max_commands": 10},
                "questions": [
                    {
                        "id": "souffle-q1",
                        "question": "Is any pump missing a check valve?",
                        "slice": "hand_authored",
                        "category": "compliance_universal",
                        "drawing": str(bundle),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": [witness_node_id()],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    arm = AgenticArm(
        runner=ScriptedSouffleModelRunner(),
        budgets=BUDGETS,
        model_name="scripted",
        arm_label="c-souffle",
        task_builder=build_souffle_harbor_task,
        require_executed_program=True,
    )
    report = run_benchmark(
        manifest_path=manifest, arm=arm, output_dir=tmp_path / "report"
    )
    assert report["arm_id"] == "c-souffle:scripted"
    episode = report["episodes"][0]
    # Witness match depends on the scripted query; the audit trail is the
    # hard requirement here: the executed program ships in the transcript.
    assert any(
        entry.get("tool_name") == "executed_datalog_program"
        for entry in episode["transcript"]
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
