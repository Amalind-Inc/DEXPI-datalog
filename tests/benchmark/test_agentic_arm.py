"""Behavior tests for Arm A agentic: Harbor/Terminus-KIRA sandbox episodes.

The agent works in a sandboxed Terminus episode against the drawing bundle
with a terminal (python/NetworkX allowed, no Souffle, no rule packs, no
bespoke confirmation machinery) and submits ``/workspace/structured_answer.json``
through Harbor's independent verification gate.  The benchmark adapter maps
that episode outcome to a :class:`StructuredAnswer`.

Tests drive episodes through the same :class:`EpisodeRunner` interface the
live Harbor/KIRA runner implements, using a scripted runner: zero live model
calls and no Docker in CI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from pydexpi_datalog.benchmark import (
    POSTURE_SOURCE_GROUNDED,
    VERDICT_UNANSWERABLE,
    VERDICT_VIOLATION_FOUND,
    GroundTruth,
    run_benchmark,
)
from pydexpi_datalog.benchmark.agentic_arm import (
    AGENTIC_ARM_MODELS,
    ANALYSIS_REPLAY_FILENAME,
    ANALYSIS_SCRIPT_FILENAME,
    DEGRADED_VERDICT,
    AgenticArm,
    EpisodeBudgets,
    EpisodeResult,
    HarborKiraEpisodeRunner,
    build_harbor_task,
    create_agentic_arm,
    load_episode_budgets,
    parse_harbor_artifacts,
    requires_analysis_replay,
    verify_agentic_answer_trace,
)
from pydexpi_datalog.benchmark.dataset import BenchmarkQuestion

REPO_ROOT = Path(__file__).resolve().parents[2]
E06_GRAPH_FACTS = (
    REPO_ROOT / "testdata" / "graph_contract" / "e06-pump-hex" / "graph_facts.json"
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


def make_question(
    bundle: Path,
    *,
    text: str = "Is any pump missing a check valve?",
    slice_name: str = "hand_authored",
) -> BenchmarkQuestion:
    graph_facts = json.loads(E06_GRAPH_FACTS.read_text(encoding="utf-8"))
    node_id = str(graph_facts["facts"]["nodes"][0]["node_id"])
    return BenchmarkQuestion(
        question_id="agentic-q1",
        question=text,
        slice=slice_name,
        drawing_ref=bundle,
        ground_truth=GroundTruth(
            verdict=VERDICT_VIOLATION_FOUND, witness_ids=(node_id,)
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


def raw_xml_replay_result(bundle: Path) -> EpisodeResult:
    witness = witness_node_id()
    digest = hashlib.sha256((bundle / "drawing.xml").read_bytes()).hexdigest()
    replay = {"verdict": VERDICT_VIOLATION_FOUND, "witness_ids": [witness]}
    return EpisodeResult(
        structured_answer_text=json.dumps(
            {
                **replay,
                "posture": POSTURE_SOURCE_GROUNDED,
                "support": {
                    "steps": [
                        {
                            "id": "scope",
                            "kind": "xml_scope",
                            "artifact": "drawing.xml",
                            "sha256": digest,
                            "dependencies": [],
                        },
                        {
                            "id": "execution",
                            "kind": "python_execution",
                            "artifact": ANALYSIS_SCRIPT_FILENAME,
                            "input": "drawing.xml",
                            "output": ANALYSIS_REPLAY_FILENAME,
                            **replay,
                            "dependencies": ["scope"],
                        },
                    ],
                    "claims": [
                        {"claim": "verdict", "step_ids": ["execution"]},
                        {
                            "claim": f"witness:{witness}",
                            "step_ids": ["execution"],
                        },
                    ],
                },
            }
        ),
        reward=1.0,
        analysis_script="import json\nprint(json.dumps({}))\n",
        analysis_replay_text=json.dumps(replay),
    )


BUDGETS = EpisodeBudgets(
    max_turns=8,
    max_commands=10,
    agent_timeout_sec=600.0,
    verifier_timeout_sec=120.0,
)


@dataclass
class ScriptedEpisodeRunner:
    """Deterministic EpisodeRunner: records its inputs, returns one result."""

    result: EpisodeResult

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        self.calls.append(
            {"task_dir": task_dir, "jobs_dir": jobs_dir, "budgets": budgets}
        )
        return self.result


def passing_result(witness: str) -> EpisodeResult:
    return EpisodeResult(
        structured_answer_text=json.dumps(
            {
                "verdict": VERDICT_VIOLATION_FOUND,
                "witness_ids": [witness],
                "posture": POSTURE_SOURCE_GROUNDED,
            }
        ),
        reward=1.0,
        command_batches=(
            ("cat /input/README.md", "python3 -c 'import json'"),
            ("cat /input/graph_facts.json | head",),
        ),
        model_calls=4,
        usage={"input_tokens": 100, "output_tokens": 20},
    )


def _arm(runner: ScriptedEpisodeRunner) -> AgenticArm:
    return AgenticArm(runner=runner, budgets=BUDGETS, model_name="scripted")


# --------------------------------------------------------------------------
# Episode outcome -> StructuredAnswer
# --------------------------------------------------------------------------


def test_verified_episode_maps_to_structured_answer(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    witness = witness_node_id()
    runner = ScriptedEpisodeRunner(passing_result(witness))
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert answer.witness_ids == (witness,)
    assert answer.posture == POSTURE_SOURCE_GROUNDED
    # The episode ran through the same interface the live runner implements,
    # against a generated Harbor task, with the shared budgets.
    assert len(runner.calls) == 1
    assert runner.calls[0]["budgets"] == BUDGETS


def test_transcript_exposes_executed_analysis_and_submission(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    runner = ScriptedEpisodeRunner(passing_result(witness_node_id()))
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    roles = [str(entry.get("role")) for entry in answer.transcript]
    assert roles[0] == "user"  # the task instruction the agent received
    assert "Is any pump missing a check valve?" in str(answer.transcript[0]["content"])
    command_entries = [
        entry for entry in answer.transcript if entry.get("role") == "tool"
    ]
    executed = [
        command
        for entry in command_entries
        for command in entry["commands"]  # type: ignore[union-attr]
    ]
    assert "cat /input/graph_facts.json | head" in executed
    assert answer.transcript[-1]["role"] == "assistant"
    assert VERDICT_VIOLATION_FOUND in str(answer.transcript[-1]["content"])


def test_usage_records_budgets_and_command_accounting(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    runner = ScriptedEpisodeRunner(passing_result(witness_node_id()))
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.usage["budgets"] == {
        "max_turns": 8,
        "max_commands": 10,
        "max_output_tokens": 8192,
        "agent_timeout_sec": 600.0,
        "verifier_timeout_sec": 120.0,
    }
    assert answer.usage["command_batches"] == 2
    assert answer.usage["commands"] == 3
    assert answer.usage["model_calls"] == 4
    assert answer.usage["input_tokens"] == 100


def test_arm_a_qualifies_only_with_captured_raw_xml_replay(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(raw_xml_replay_result(bundle)),
        budgets=BUDGETS,
        require_analysis_replay=requires_analysis_replay,
        analysis_trace_gate=verify_agentic_answer_trace,
    )

    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)

    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert answer.usage["audit_trace"]["trace_safe"] is True
    tool_names = {entry.get("tool_name") for entry in answer.transcript}
    assert "executed_python_analysis" in tool_names
    assert "captured_analysis_replay" in tool_names


def test_arm_a_degrades_when_captured_replay_is_missing(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    result = replace(raw_xml_replay_result(bundle), analysis_replay_text=None)
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(result),
        budgets=BUDGETS,
        require_analysis_replay=requires_analysis_replay,
        analysis_trace_gate=verify_agentic_answer_trace,
    )

    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)

    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "missing_analysis_replay"


def test_arm_a_permission_control_abstains_without_a_script(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    support = {
        "steps": [
            {
                "id": "policy",
                "kind": "policy_abstention",
                "operation": (
                    "permission_or_defeasible_not_decidable_from_monotone_drawing"
                ),
                "dependencies": [],
            }
        ],
        "claims": [{"claim": "verdict", "step_ids": ["policy"]}],
    }
    result = EpisodeResult(
        structured_answer_text=json.dumps(
            {
                "verdict": VERDICT_UNANSWERABLE,
                "witness_ids": [],
                "posture": "source_data_unavailable",
                "answer_text": (
                    "Permission is not soundly decidable from monotone drawing facts; "
                    "provide the governing policy and exemptions."
                ),
                "support": support,
            }
        ),
        reward=1.0,
    )
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(result),
        budgets=BUDGETS,
        require_analysis_replay=requires_analysis_replay,
        analysis_trace_gate=verify_agentic_answer_trace,
    )

    answer = arm.answer(
        question=make_permission_question(bundle), drawing_ref=bundle
    )

    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.usage["audit_trace"]["trace_safe"] is True


# --------------------------------------------------------------------------
# Degradation: never crash, never creditable
# --------------------------------------------------------------------------


def test_command_budget_overrun_degrades(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    over_budget = replace(
        passing_result(witness_node_id()),
        command_batches=tuple((f"echo step-{index}",) for index in range(11)),
    )
    runner = ScriptedEpisodeRunner(over_budget)
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.witness_ids == ()
    assert answer.usage["degraded_reason"] == "command_budget_exceeded"


def test_failed_verification_gate_degrades(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    rejected = replace(passing_result(witness_node_id()), reward=0.0)
    runner = ScriptedEpisodeRunner(rejected)
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "verification_gate_rejected"


def test_missing_submission_degrades(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    silent = replace(
        passing_result(witness_node_id()),
        structured_answer_text=None,
        reward=0.0,
    )
    runner = ScriptedEpisodeRunner(silent)
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT


def test_malformed_submission_degrades_but_keeps_audit_payload(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    malformed = replace(
        passing_result(witness_node_id()),
        structured_answer_text='{"verdict": "maybe"}',
    )
    runner = ScriptedEpisodeRunner(malformed)
    answer = _arm(runner).answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.witness_ids == ()
    # The executed analysis stays inspectable even on degradation.
    assert any(entry.get("role") == "tool" for entry in answer.transcript)


def test_unanswerable_submission_is_a_valid_verdict(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    unanswerable = replace(
        passing_result(witness_node_id()),
        structured_answer_text=json.dumps(
            {
                "verdict": VERDICT_UNANSWERABLE,
                "witness_ids": [],
                "posture": "out_of_scope",
                "answer_text": (
                    "This request is outside P&ID review. I can check the loaded "
                    "drawing's topology or equipment attributes."
                ),
            }
        ),
    )
    runner = ScriptedEpisodeRunner(unanswerable)
    answer = _arm(runner).answer(
        question=make_question(bundle, slice_name="trap"), drawing_ref=bundle
    )
    assert answer.verdict == VERDICT_UNANSWERABLE
    assert answer.witness_ids == ()


# --------------------------------------------------------------------------
# Budgets: manifest-configurable, identical across agentic arms
# --------------------------------------------------------------------------


def test_budgets_load_from_run_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [],
                "episode_budgets": {
                    "max_turns": 5,
                    "max_commands": 7,
                    "agent_timeout_sec": 300.0,
                    "verifier_timeout_sec": 60.0,
                },
            }
        ),
        encoding="utf-8",
    )
    budgets = load_episode_budgets(manifest)
    assert budgets == EpisodeBudgets(
        max_turns=5,
        max_commands=7,
        agent_timeout_sec=300.0,
        verifier_timeout_sec=60.0,
    )


def test_budgets_default_when_manifest_omits_them(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 2, "questions": []}), encoding="utf-8"
    )
    assert load_episode_budgets(manifest) == EpisodeBudgets()


def test_budgets_reject_unknown_or_invalid_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "questions": [],
                "episode_budgets": {"max_turns": 5, "max_tools": 3},
            }
        ),
        encoding="utf-8",
    )
    try:
        load_episode_budgets(manifest)
    except ValueError as error:
        assert "max_tools" in str(error)
    else:
        raise AssertionError("unknown budget field must be rejected")


# --------------------------------------------------------------------------
# Harbor task generation: read-only bundle mount + independent verifier
# --------------------------------------------------------------------------


def test_task_generation_exposes_only_raw_xml_and_writes_harbor_layout(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    assert task_dir.name == "benchmark-agentic-q1"
    environment = task_dir / "environment"
    assert (environment / "drawing.xml").read_bytes() == (
        bundle / "drawing.xml"
    ).read_bytes()
    for forbidden in ("graph_facts.json", "graph.json", "README.md"):
        assert not (environment / forbidden).exists()
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert "Is any pump missing a check valve?" in instruction
    assert "structured_answer.json" in instruction
    # No Souffle, no rule packs, no ground-truth leak into the episode.
    assert "souffle" not in instruction.lower()
    assert "rule pack" not in instruction.lower()
    assert "graph_facts" not in instruction
    assert "graph.json" not in instruction
    assert witness_node_id() not in instruction
    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert "timeout_sec = 600.0" in task_toml
    assert "timeout_sec = 120.0" in task_toml
    dockerfile = (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "chmod 0555 /input" in dockerfile
    assert "chmod 0444 /input/drawing.xml" in dockerfile
    assert "networkx" not in dockerfile.lower()
    assert (task_dir / "tests" / "test.sh").exists()


def test_task_generation_requires_resolvable_raw_xml(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "drawing.xml").unlink()
    (bundle / "graph_facts.json").unlink()
    try:
        build_harbor_task(
            question=make_question(bundle),
            drawing_ref=bundle,
            output_dir=tmp_path / "tasks",
            budgets=BUDGETS,
        )
    except FileNotFoundError as error:
        assert "neither drawing.xml nor graph provenance" in str(error)
    else:
        raise AssertionError("incomplete bundle must fail task generation")


def _run_generated_verifier(
    task_dir: Path, *, input_dir: Path, workspace_dir: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(task_dir / "tests" / "test_outputs.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "INPUT_DIR": str(input_dir),
            "WORKSPACE_DIR": str(workspace_dir),
        },
    )


def test_generated_verifier_accepts_intact_input_and_json_submission(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "structured_answer.json").write_text(
        json.dumps(
            {"verdict": "unanswerable", "witness_ids": [], "posture": "out_of_scope"}
        ),
        encoding="utf-8",
    )
    (workspace / ANALYSIS_SCRIPT_FILENAME).write_text(
        "import json\nprint(json.dumps({'verdict': 'unanswerable', "
        "'witness_ids': []}))\n",
        encoding="utf-8",
    )
    result = _run_generated_verifier(
        task_dir, input_dir=task_dir / "environment", workspace_dir=workspace
    )
    assert result.returncode == 0, result.stderr
    replay = json.loads((workspace / ANALYSIS_REPLAY_FILENAME).read_text())
    assert replay == {"verdict": "unanswerable", "witness_ids": []}


def test_generated_verifier_rejects_missing_or_inconsistent_analysis_script(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "structured_answer.json").write_text(
        json.dumps(
            {
                "verdict": VERDICT_VIOLATION_FOUND,
                "witness_ids": ["expected"],
                "posture": POSTURE_SOURCE_GROUNDED,
            }
        ),
        encoding="utf-8",
    )
    missing = _run_generated_verifier(
        task_dir, input_dir=task_dir / "environment", workspace_dir=workspace
    )
    assert missing.returncode != 0

    (workspace / ANALYSIS_SCRIPT_FILENAME).write_text(
        "import json\nprint(json.dumps({'verdict': 'no_violation', "
        "'witness_ids': []}))\n",
        encoding="utf-8",
    )
    inconsistent = _run_generated_verifier(
        task_dir, input_dir=task_dir / "environment", workspace_dir=workspace
    )
    assert inconsistent.returncode != 0
    assert "does not match structured answer" in inconsistent.stderr


def test_generated_verifier_rejects_mutated_input(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "structured_answer.json").write_text("{}", encoding="utf-8")
    (task_dir / "environment" / "drawing.xml").write_text("<changed/>", encoding="utf-8")
    result = _run_generated_verifier(
        task_dir, input_dir=task_dir / "environment", workspace_dir=workspace
    )
    assert result.returncode != 0
    assert "read-only input was changed" in result.stderr


def test_generated_verifier_rejects_missing_submission(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    task_dir = build_harbor_task(
        question=make_question(bundle),
        drawing_ref=bundle,
        output_dir=tmp_path / "tasks",
        budgets=BUDGETS,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_generated_verifier(
        task_dir, input_dir=task_dir / "environment", workspace_dir=workspace
    )
    assert result.returncode != 0
    assert "missing structured answer" in result.stderr


# --------------------------------------------------------------------------
# Live Harbor/KIRA runner: exact command, artifact parsing; no Docker in CI
# --------------------------------------------------------------------------


def test_live_runner_command_wires_budgets_and_released_agent() -> None:
    runner = HarborKiraEpisodeRunner(
        kira_dir=Path("/tmp/terminus-kira"),
        model="openrouter/anthropic/claude-sonnet-4",
    )
    command = runner.build_command(
        task_dir=Path("/tasks/benchmark-agentic-q1"),
        jobs_dir=Path("/jobs/run-1"),
        budgets=BUDGETS,
    )
    assert command == (
        "uv",
        "run",
        "--directory",
        "/tmp/terminus-kira",
        "harbor",
        "run",
        "--path",
        "/tasks",
        "--task-name",
        "benchmark-agentic-q1",
        "--agent-import-path",
        "terminus_kira.terminus_kira:TerminusKira",
        "--model",
        "openrouter/anthropic/claude-sonnet-4",
        "--agent-kwarg",
        "max_turns=8",
        "--agent-kwarg",
        'model_info={"max_output_tokens":8192}',
        "--env",
        "docker",
        "--jobs-dir",
        "/jobs/run-1",
    )


def test_live_runner_command_absolutizes_paths_before_uv_changes_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = HarborKiraEpisodeRunner(
        kira_dir=Path("kira"),
        model="openrouter/deepseek/deepseek-v4-flash",
    )

    command = runner.build_command(
        task_dir=Path("run/tasks/benchmark-agentic-q1"),
        jobs_dir=Path("run/jobs"),
        budgets=BUDGETS,
    )

    assert command[command.index("--directory") + 1] == str(tmp_path / "kira")
    assert command[command.index("--path") + 1] == str(tmp_path / "run/tasks")
    assert command[command.index("--jobs-dir") + 1] == str(tmp_path / "run/jobs")


def test_live_runner_command_forwards_api_base_when_set() -> None:
    runner = HarborKiraEpisodeRunner(
        kira_dir=Path("/tmp/terminus-kira"),
        model="openai/scripted",
        api_base="http://127.0.0.1:9999/v1",
    )
    command = runner.build_command(
        task_dir=Path("/tasks/benchmark-agentic-q1"),
        jobs_dir=Path("/jobs/run-1"),
        budgets=BUDGETS,
    )
    assert "api_base=http://127.0.0.1:9999/v1" in command
    api_base_flag = command.index("api_base=http://127.0.0.1:9999/v1")
    assert command[api_base_flag - 1] == "--agent-kwarg"


def test_live_runner_gives_harbor_time_to_enforce_phase_timeouts_and_finalize(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def time_out(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)
    runner = HarborKiraEpisodeRunner(
        kira_dir=Path("/tmp/terminus-kira"),
        model="openrouter/deepseek/deepseek-v4-flash",
    )

    result = runner.run(
        task_dir=tmp_path / "tasks" / "benchmark-agentic-q1",
        jobs_dir=tmp_path / "jobs",
        budgets=EpisodeBudgets(
            agent_timeout_sec=300.0,
            verifier_timeout_sec=60.0,
        ),
    )

    assert len(calls) == 1
    # The task itself gives Harbor 600s for environment setup, 300s for the
    # agent, and 60s for the verifier.  The outer process guard must not bind
    # before Harbor's agent timer or before its result can be persisted.
    assert calls[0][1]["timeout"] == 990.0
    assert result.reward == 0.0
    assert result.usage["timed_out"] is True
    assert result.usage["timeout_sec"] == 990.0


def test_live_runner_routes_episode_through_configured_request_gateway(
    tmp_path: Path, monkeypatch
) -> None:
    commands = []

    class ScriptedGateway:
        base_url = "http://127.0.0.1:43123/v1"
        entered = False
        exited = False
        attributions = []

        @contextmanager
        def attribute_calls(self, *, arm_id, question_id):
            self.attributions.append((arm_id, question_id))
            yield

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, *exc_info):
            self.exited = True

    gateway = ScriptedGateway()

    def complete(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", complete)
    runner = HarborKiraEpisodeRunner(
        kira_dir=Path("/tmp/terminus-kira"),
        model="openrouter/deepseek/deepseek-v4-flash",
        request_gateway=gateway,  # type: ignore[arg-type]
        accounting_arm_id="a-agentic:deepseek",
    )

    runner.run(
        task_dir=tmp_path / "tasks" / "benchmark-agentic-q1",
        jobs_dir=tmp_path / "jobs",
        budgets=EpisodeBudgets(agent_timeout_sec=300.0),
    )

    assert gateway.entered is True
    assert gateway.exited is True
    assert gateway.attributions == [("a-agentic:deepseek", "agentic-q1")]
    assert len(commands) == 1
    assert "api_base=http://127.0.0.1:43123/v1" in commands[0]


def test_harbor_artifacts_parse_into_episode_result(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    trial_dir = jobs_dir / "run" / "trial-0"
    verifier_dir = trial_dir / "verifier"
    verifier_dir.mkdir(parents=True)
    (verifier_dir / "reward.txt").write_text("1\n", encoding="utf-8")
    (verifier_dir / "structured_answer.json").write_text(
        json.dumps(
            {
                "verdict": "violation_found",
                "witness_ids": ["node-1"],
                "posture": "source_grounded",
            }
        ),
        encoding="utf-8",
    )
    (verifier_dir / ANALYSIS_SCRIPT_FILENAME).write_text(
        "print('{}')\n", encoding="utf-8"
    )
    (verifier_dir / ANALYSIS_REPLAY_FILENAME).write_text(
        json.dumps({"verdict": "violation_found", "witness_ids": ["node-1"]}),
        encoding="utf-8",
    )
    (trial_dir / "agent-trajectory.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "function_name": "bash_command",
                        "arguments": {
                            "commands": [
                                {"keystrokes": "cat /input/README.md", "duration": 1},
                                {"keystrokes": "python3 analyze.py", "duration": 5},
                            ]
                        },
                        "prompt_tokens": 120,
                        "completion_tokens": 30,
                        "cost_usd": 0.01,
                    },
                    {
                        "function_name": "mark_task_complete",
                        "prompt_tokens": 40,
                        "completion_tokens": 5,
                        "cost_usd": 0.002,
                    },
                    {"function_name": "mark_task_complete"},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = parse_harbor_artifacts(jobs_dir)
    assert result.reward == 1.0
    assert result.structured_answer_text is not None
    assert json.loads(result.structured_answer_text)["verdict"] == "violation_found"
    assert result.command_batches == (("cat /input/README.md", "python3 analyze.py"),)
    assert result.model_calls == 3
    assert result.usage == {
        "input_tokens": 160,
        "output_tokens": 35,
        "cost_usd": 0.012,
    }
    assert result.analysis_script == "print('{}')\n"
    assert json.loads(result.analysis_replay_text or "null")["witness_ids"] == [
        "node-1"
    ]


def test_harbor_agent_timeout_overrides_persisted_verifier_reward(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    trial_dir = jobs_dir / "run" / "trial-0"
    verifier_dir = trial_dir / "verifier"
    verifier_dir.mkdir(parents=True)
    (verifier_dir / "reward.txt").write_text("1\n", encoding="utf-8")
    (trial_dir / "result.json").write_text(
        json.dumps(
            {
                "verifier_result": {"rewards": {"reward": 1.0}},
                "exception_info": {
                    "exception_type": "AgentTimeoutError",
                    "exception_message": "Agent execution timed out after 300 seconds",
                },
            }
        ),
        encoding="utf-8",
    )

    result = parse_harbor_artifacts(jobs_dir)

    assert result.reward == 0.0
    assert result.usage["timed_out"] is True
    assert result.usage["harbor_exception_type"] == "AgentTimeoutError"


def test_missing_harbor_artifacts_parse_as_rejected_episode(
    tmp_path: Path,
) -> None:
    result = parse_harbor_artifacts(tmp_path / "empty-jobs")
    assert result.reward is None
    assert result.structured_answer_text is None
    assert result.command_batches == ()


def test_create_agentic_arm_requires_credential_and_known_model() -> None:
    try:
        create_agentic_arm(
            "sonnet",
            kira_dir=Path("/tmp/terminus-kira"),
            budgets=BUDGETS,
            environ={},
        )
    except ValueError as error:
        assert "OPENROUTER_API_KEY" in str(error)
    else:
        raise AssertionError("missing credential must fail fast")
    try:
        create_agentic_arm(
            "claude",
            kira_dir=Path("/tmp/terminus-kira"),
            budgets=BUDGETS,
            environ={"OPENROUTER_API_KEY": "x"},
        )
    except ValueError as error:
        assert "claude" in str(error)
    else:
        raise AssertionError("unknown model key must fail fast")
    arm = create_agentic_arm(
        "sonnet",
        kira_dir=Path("/tmp/terminus-kira"),
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
    )
    assert arm.arm_id == "a-agentic:sonnet"
    assert arm.runner.model == AGENTIC_ARM_MODELS["sonnet"]
    assert arm.budgets == BUDGETS
    assert arm.require_analysis_replay is requires_analysis_replay
    assert arm.analysis_trace_gate is not None


def test_deepseek_live_arm_resolves_exact_preregistered_v4_flash_model() -> None:
    arm = create_agentic_arm(
        "deepseek",
        kira_dir=Path("/tmp/terminus-kira"),
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
    )

    assert arm.runner.model == "openrouter/deepseek/deepseek-v4-flash"


def test_live_arm_constructor_accepts_locked_request_gateway() -> None:
    gateway = object()

    arm = create_agentic_arm(
        "deepseek",
        kira_dir=Path("/tmp/terminus-kira"),
        budgets=BUDGETS,
        environ={"OPENROUTER_API_KEY": "x"},
        request_gateway=gateway,  # type: ignore[arg-type]
    )

    assert arm.runner.request_gateway is gateway


# --------------------------------------------------------------------------
# End to end: the agentic arm plugs into run_benchmark
# --------------------------------------------------------------------------


def test_run_benchmark_grades_agentic_episode_end_to_end(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    witness = witness_node_id()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "episode_budgets": {"max_turns": 8, "max_commands": 10},
                "questions": [
                    {
                        "id": "agentic-q1",
                        "question": "Is any pump missing a check valve?",
                        "slice": "hand_authored",
                        "category": "compliance_universal",
                        "drawing": str(bundle),
                        "ground_truth": {
                            "verdict": "violation_found",
                            "witness_ids": [witness],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    budgets = load_episode_budgets(manifest)
    arm = AgenticArm(
        runner=ScriptedEpisodeRunner(passing_result(witness)),
        budgets=budgets,
        model_name="scripted",
    )
    report = run_benchmark(
        manifest_path=manifest, arm=arm, output_dir=tmp_path / "report"
    )
    assert report["arm_id"] == "a-agentic:scripted"
    assert report["totals"] == {"questions": 1, "passed": 1, "failed": 0}
    episode = report["episodes"][0]
    assert episode["grade"]["passed"] is True
    assert episode["usage"]["budgets"]["max_commands"] == 10
    tool_entries = [
        entry for entry in episode["transcript"] if entry.get("role") == "tool"
    ]
    assert tool_entries, "executed analysis must be inspectable in the report"


@dataclass
class ScriptedModelEpisodeRunner:
    """A scripted model working the generated task end to end, no Docker.

    Behaves like a real episode behind the same :class:`EpisodeRunner`
    interface: it reads the generated instruction, runs its scripted
    terminal commands against the task's environment copy of the bundle,
    writes ``/workspace/structured_answer.json``, runs the generated
    independent verifier, persists Harbor-shaped artifacts under
    ``jobs_dir``, and returns ``parse_harbor_artifacts(jobs_dir)``.
    """

    answer: dict[str, object]

    def run(
        self, *, task_dir: Path, jobs_dir: Path, budgets: EpisodeBudgets
    ) -> EpisodeResult:
        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
        assert "structured_answer.json" in instruction
        input_dir = task_dir / "environment"
        workspace = jobs_dir / "workspace"
        verifier_dir = jobs_dir / "trial-0" / "verifier"
        workspace.mkdir(parents=True)
        verifier_dir.mkdir(parents=True)

        # The scripted "model" inspects the read-only input with real
        # commands, observes real output, then writes its submission.
        commands = [
            "head /input/drawing.xml",
            "python3 /workspace/analysis.py /input/drawing.xml",
        ]
        observed = (input_dir / "drawing.xml").read_text(encoding="utf-8")
        assert "PlantModel" in observed, "real observed XML output"
        (workspace / "structured_answer.json").write_text(
            json.dumps(self.answer), encoding="utf-8"
        )
        replay = (
            {
                "verdict": self.answer.get("verdict"),
                "witness_ids": self.answer.get("witness_ids"),
            }
            if isinstance(self.answer, dict)
            else {}
        )
        (workspace / ANALYSIS_SCRIPT_FILENAME).write_text(
            "import json\nprint(json.dumps(" + repr(replay) + "))\n",
            encoding="utf-8",
        )

        # The generated independent verification gate decides the reward.
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
        shutil.copyfile(
            workspace / "structured_answer.json",
            verifier_dir / "structured_answer.json",
        )
        shutil.copyfile(
            workspace / ANALYSIS_SCRIPT_FILENAME,
            verifier_dir / ANALYSIS_SCRIPT_FILENAME,
        )
        if (workspace / ANALYSIS_REPLAY_FILENAME).exists():
            shutil.copyfile(
                workspace / ANALYSIS_REPLAY_FILENAME,
                verifier_dir / ANALYSIS_REPLAY_FILENAME,
            )
        (jobs_dir / "trial-0" / "agent-trajectory.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "function_name": "execute_commands",
                            "arguments": {
                                "commands": [
                                    {"keystrokes": command, "duration": 1}
                                    for command in commands
                                ]
                            },
                            "prompt_tokens": 90,
                            "completion_tokens": 12,
                        },
                        {"function_name": "mark_task_complete"},
                        {"function_name": "mark_task_complete"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return parse_harbor_artifacts(jobs_dir)


def test_scripted_model_episode_flows_through_task_verifier_and_artifacts(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    witness = witness_node_id()
    runner = ScriptedModelEpisodeRunner(
        answer={
            "verdict": VERDICT_VIOLATION_FOUND,
            "witness_ids": [witness],
            "posture": POSTURE_SOURCE_GROUNDED,
        }
    )
    arm = AgenticArm(runner=runner, budgets=BUDGETS, model_name="scripted")
    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == VERDICT_VIOLATION_FOUND
    assert answer.witness_ids == (witness,)
    assert answer.posture == POSTURE_SOURCE_GROUNDED
    # Command accounting flowed from the Harbor-shaped trajectory artifact.
    assert answer.usage["command_batches"] == 1
    assert answer.usage["commands"] == 2
    assert answer.usage["model_calls"] == 3
    assert answer.usage["input_tokens"] == 90
    executed = [
        command
        for entry in answer.transcript
        if entry.get("tool_name") == "execute_commands"
        for command in entry["commands"]  # type: ignore[union-attr]
    ]
    assert "head /input/drawing.xml" in executed


def test_agentic_arm_retains_live_task_and_harbor_artifacts(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    witness = witness_node_id()
    archive = tmp_path / "archive"
    runner = ScriptedModelEpisodeRunner(
        answer={
            "verdict": VERDICT_VIOLATION_FOUND,
            "witness_ids": [witness],
            "posture": POSTURE_SOURCE_GROUNDED,
        }
    )
    arm = AgenticArm(
        runner=runner,
        budgets=BUDGETS,
        model_name="scripted",
        artifact_root=archive,
    )

    arm.answer(question=make_question(bundle), drawing_ref=bundle)

    episode_dir = archive / "agentic-q1"
    assert (episode_dir / "tasks" / "benchmark-agentic-q1" / "instruction.md").is_file()
    assert (episode_dir / "jobs" / "trial-0" / "agent-trajectory.json").is_file()


def test_scripted_model_episode_verifier_gates_invalid_submission(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)
    # A submission the generated verifier rejects: not a JSON object.
    runner = ScriptedModelEpisodeRunner(answer=[])  # type: ignore[arg-type]
    arm = AgenticArm(runner=runner, budgets=BUDGETS, model_name="scripted")
    answer = arm.answer(question=make_question(bundle), drawing_ref=bundle)
    assert answer.verdict == DEGRADED_VERDICT
    assert answer.usage["degraded_reason"] == "verification_gate_rejected"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
